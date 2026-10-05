#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <esp_system.h>
#include <mbedtls/md.h>
#include <mbedtls/sha256.h>
#include "BwwCore.h"
#include "BwwBluetooth.h"
#include "RequestFrame.h"
using namespace bww;
class SdStorage : public Storage {
public:
    bool exists(const std::string& path) override { return SD.exists(path.c_str()); }
    bool mkdir(const std::string& path) override { return exists(path) || SD.mkdir(path.c_str()); }
    bool readJson(const std::string& path, JsonDocument& doc) override {
        doc.clear(); File file = SD.open(path.c_str(), FILE_READ);
        if (!file || file.isDirectory()) return false;
        auto result = deserializeJson(doc, file, DeserializationOption::NestingLimit(16)); file.close(); return !result;
    }
    bool writeJson(const std::string& path, const JsonDocument& doc) override {
        // Only inactive manifests or newly allocated site generations are replaced.
        if (exists(path) && !SD.remove(path.c_str())) return false;
        File file = SD.open(path.c_str(), FILE_WRITE); if (!file) return false;
        size_t expected = measureJson(doc), written = serializeJson(doc, file);
        file.flush(); bool ok = written == expected && file.size() == expected; file.close(); return ok;
    }
    bool remove(const std::string& path) override { return !exists(path) || SD.remove(path.c_str()); }
    std::vector<std::string> files(const std::string& directory) override {
        std::vector<std::string> result; File folder = SD.open(directory.c_str()); if (!folder) return result;
        File file;
        while ((file = folder.openNextFile())) { if (!file.isDirectory()) result.push_back(directory + "/" + std::string(file.name())); file.close(); }
        folder.close(); return result;
    }
};
class ShaWriter {
    mbedtls_sha256_context* context_;
public:
    bool good = true;
    explicit ShaWriter(mbedtls_sha256_context* context) : context_(context) {}
    size_t write(uint8_t byte) { return write(&byte, 1); }
    size_t write(const uint8_t* bytes, size_t count) { if (mbedtls_sha256_update_ret(context_, bytes, count) != 0) good = false; return good ? count : 0; }
};
class DeviceCrypto : public Crypto {
public:
    std::string randomHex(size_t bytes) override { std::vector<uint8_t> data(bytes); esp_fill_random(data.data(), bytes); return hex(data.data(), bytes); }
    std::string sha256(const std::string& value) override {
        uint8_t digest[32]; return mbedtls_sha256_ret(reinterpret_cast<const uint8_t*>(value.data()), value.size(), digest, 0) == 0 ? hex(digest, 32) : "";
    }
    std::string jsonDigest(JsonVariantConst value) override {
        mbedtls_sha256_context context; mbedtls_sha256_init(&context);
        bool ok = mbedtls_sha256_starts_ret(&context, 0) == 0;
        ShaWriter writer(&context); if (ok) serializeJson(value, writer);
        uint8_t digest[32]; ok = ok && writer.good && mbedtls_sha256_finish_ret(&context, digest) == 0;
        mbedtls_sha256_free(&context); return ok ? hex(digest, 32) : "";
    }
    std::string passwordHash(const std::string& password, const std::string& saltHex) override {
        std::vector<uint8_t> salt; if (!unhex(saltHex, salt) || salt.size() != 16) return "";
        mbedtls_md_context_t context; mbedtls_md_init(&context);
        const auto* info = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
        bool ok = info && mbedtls_md_setup(&context, info, 1) == 0 && mbedtls_md_hmac_starts(&context, reinterpret_cast<const uint8_t*>(password.data()), password.size()) == 0;
        auto hmac = [&](const uint8_t* data, size_t size, uint8_t out[32]) {
            return mbedtls_md_hmac_reset(&context) == 0 && mbedtls_md_hmac_update(&context, data, size) == 0 && mbedtls_md_hmac_finish(&context, out) == 0;
        };
        uint8_t digest[32]; ok = ok && pbkdf2(salt, hmac, [] { delay(1); }, digest);
        mbedtls_md_free(&context); return ok ? hex(digest, 32) : "";
    }
};
class BluetoothInput {
    BwwBluetooth& link_; uint32_t started_ = millis();
public:
    explicit BluetoothInput(BwwBluetooth& link) : link_(link) {}
    int read() {
        while (link_.connected() && millis() - started_ < 120000) { int c = link_.read(); if (c >= 0) return c; link_.handlePairing(); delay(1); }
        return -1;
    }
};
class ReplyWriter {
    BwwBluetooth& link_; uint8_t buffer_[512]; size_t count_ = 0;
public:
    bool good = true;
    explicit ReplyWriter(BwwBluetooth& link) : link_(link) {}
    size_t write(uint8_t byte) { if (!good) return 0; buffer_[count_++] = byte; if (count_ == sizeof(buffer_)) flush(); return good ? 1 : 0; }
    size_t write(const uint8_t* data, size_t count) { size_t i = 0; while (i < count && write(data[i])) ++i; return i; }
    void flush() { if (count_) { good = good && link_.write(buffer_, count_); count_ = 0; } }
};
SdStorage disk; DeviceCrypto crypto; Core core(disk, crypto); BwwBluetooth bluetooth;
DynamicJsonDocument rpc(RPC_CAPACITY);
bool initialized = false; uint32_t clockAt = 0;
void setup() {
    Serial.begin(115200); delay(300);
    Serial.println("Bluetooth-wide Web ESP32: SD CS=5 SCK=18 MOSI=23 MISO=19");
    SPI.begin(SD_SCK, SD_MISO, SD_MOSI, SD_CS);
    if (rpc.capacity() != RPC_CAPACITY || !SD.begin(SD_CS, SPI, SD_FREQUENCY) || SD.cardType() == CARD_NONE || !core.begin()) {
        Serial.println("SD/storage initialization failed. Check wiring, FAT32, power, and /bww backups. No data is automatically formatted or reset."); return;
    }
    if (!bluetooth.begin("BWW-ESP32")) { Serial.println("Bluetooth initialization failed: original ESP32 Classic required"); return; }
    initialized = true; clockAt = millis();
}
void loop() {
    if (!initialized) { delay(1000); return; }
    bluetooth.handlePairing();
    uint32_t now = millis(), seconds = (now - clockAt) / 1000;
    if (seconds) { clockAt += seconds * 1000; if (!core.advance(seconds)) Serial.println("SD clock checkpoint failed"); }
    if (!bluetooth.connected() || !bluetooth.available()) { delay(1); return; }
    BluetoothInput input(bluetooth); RequestFrame<BluetoothInput> frame(input);
    rpc.clear(); auto result = deserializeJson(rpc, frame, DeserializationOption::NestingLimit(16));
    bool clean = frame.finish();
    if (!frame.complete() || frame.tooLarge) { bluetooth.disconnect(); rpc.clear(); return; }
    if (result || !clean) failure(rpc, result == DeserializationError::NoMemory ? "too_large" : "invalid_json", "Invalid or oversized JSON request");
    else core.execute(rpc);
    ReplyWriter output(bluetooth); serializeJson(rpc, output); output.write('\n'); output.flush();
    rpc.clear(); if (!output.good) bluetooth.disconnect(); delay(10);
}
