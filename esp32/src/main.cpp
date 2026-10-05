#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <esp_system.h>
#include <esp_heap_caps.h>
#include "ActivityLed.h"
#include <mbedtls/aes.h>
#include <mbedtls/sha256.h>
#include "BwwCore.h"
#include "BwwBluetooth.h"
#include "RequestFrame.h"
#include "PasswordHmac.h"
#include "FileMemory.h"
using namespace bww;
void pumpNetwork();
void cooperateStorage();
// Newlib may abort instead of returning nullptr when a file mutex cannot be
// allocated. Chunk allocation headroom is requested only by chunk reads.
bool fileMemoryReady(size_t newBufferBytes = 0) {
    const auto caps = MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT;
    size_t free = heap_caps_get_free_size(caps), largest = heap_caps_get_largest_free_block(caps);
    if (fileMemoryAvailable(free, largest, newBufferBytes)) return true;
    Serial.printf("SD file operation deferred: low heap, free=%u largest=%u new_buffer=%u\n", static_cast<unsigned>(free), static_cast<unsigned>(largest), static_cast<unsigned>(newBufferBytes));
    return false;
}
class SdStorage : public Storage {
public:
    uint64_t totalBytes() override { return SD.totalBytes(); }
    uint64_t freeBytes() override {
        uint64_t total = SD.totalBytes(), used = SD.usedBytes();
        return total >= used ? total - used : 0;
    }
    bool exists(const std::string& path) override { return SD.exists(path.c_str()); }
    bool mkdir(const std::string& path) override { return exists(path) || SD.mkdir(path.c_str()); }
    bool readJson(const std::string& path, JsonDocument& doc) override {
        if (!fileMemoryReady()) return false;
        doc.clear(); File file = SD.open(path.c_str(), FILE_READ);
        if (!file || file.isDirectory()) return false;
        auto result = deserializeJson(doc, file, DeserializationOption::NestingLimit(16)); file.close(); return !result;
    }
    bool writeJson(const std::string& path, const JsonDocument& doc) override {
        if (!fileMemoryReady()) return false;
        uint64_t needed = measureJson(doc) + 4096;
        if (freeBytes() < needed) return false;
        // Only inactive manifests or newly allocated site generations are replaced.
        if (exists(path) && !SD.remove(path.c_str())) return false;
        File file = SD.open(path.c_str(), FILE_WRITE); if (!file) return false;
        size_t expected = measureJson(doc), written = serializeJson(doc, file);
        file.flush(); bool ok = written == expected && file.size() == expected; file.close(); return ok;
    }
    bool writeBytes(const std::string& path, const std::string& bytes) override {
        if (!fileMemoryReady()) return false;
        if (freeBytes() < bytes.size() + 4096) return false;
        if (exists(path) && !SD.remove(path.c_str())) return false;
        File file = SD.open(path.c_str(), FILE_WRITE); if (!file) return false;
        size_t written = file.write(reinterpret_cast<const uint8_t*>(bytes.data()), bytes.size());
        file.flush(); bool ok = written == bytes.size() && file.size() == bytes.size(); file.close(); return ok;
    }
    bool readBytes(const std::string& path, size_t maxBytes, std::string& bytes) override {
        if (!fileMemoryReady()) return false;
        File file = SD.open(path.c_str(), FILE_READ);
        if (!file || file.isDirectory() || file.size() > maxBytes) return false;
        size_t size = file.size();
        if (size > bytes.capacity()) {
            if (!fileMemoryReady(size + 1)) { file.close(); return false; }
            // Allocate exactly the required buffer rather than doubling an old capacity.
            std::string replacement(size, '\0'); bytes.swap(replacement);
        } else bytes.resize(size);
        size_t read = file.read(reinterpret_cast<uint8_t*>(bytes.data()), bytes.size()); file.close(); return read == bytes.size();
    }
    bool remove(const std::string& path) override { return !exists(path) || SD.remove(path.c_str()); }
    bool visitFiles(const std::string& directory, const std::function<void(const std::string&)>& visitor) override {
        if (!fileMemoryReady()) return false;
        File folder = SD.open(directory.c_str()); if (!folder || !folder.isDirectory()) return false;
        File file;
        while (true) {
            if (!fileMemoryReady()) { folder.close(); return false; }
            file = folder.openNextFile(); if (!file) break;
            bool regular = !file.isDirectory();
            std::string path = regular ? directory + "/" + std::string(file.name()) : "";
            file.close(); // Release the file before the visitor removes it.
            if (regular) visitor(path);
            cooperateStorage();
        }
        folder.close(); return true;
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
        uint32_t started = millis(); PasswordCooperation cooperation(started);
        PasswordHmac hmac(password);
        uint8_t digest[32];
        bool ok = pbkdf2(salt, [&](const uint8_t* data, size_t size, uint8_t out[32]) { return hmac(data, size, out); },
            [&] { if (cooperation.due(millis())) { pumpNetwork(); delay(1); } }, digest);
        Serial.printf("Password check: iterations=%lu, elapsed=%lu ms, result=%s\n",
            static_cast<unsigned long>(PASSWORD_ITERATIONS), static_cast<unsigned long>(millis() - started), ok ? "complete" : "failed");
        return ok ? hex(digest, 32) : "";
    }
};
class ReplyWriter {
    BwwBluetooth& link_; size_t index_; uint32_t handle_; uint8_t buffer_[512]; size_t count_ = 0;
public:
    bool good = true;
    ReplyWriter(BwwBluetooth& link, size_t index, uint32_t handle) : link_(link), index_(index), handle_(handle) {}
    size_t write(uint8_t byte) { if (!good) return 0; buffer_[count_++] = byte; if (count_ == sizeof(buffer_)) flush(); return good ? 1 : 0; }
    size_t write(const uint8_t* data, size_t count) { size_t i = 0; while (i < count && write(data[i])) ++i; return i; }
    void flush() { if (count_) { good = good && link_.write(index_, handle_, buffer_, count_); count_ = 0; } }
};
SdStorage disk; DeviceCrypto crypto; Core core(disk, crypto); BwwBluetooth bluetooth;
DynamicJsonDocument rpc(RPC_CAPACITY);
bool initialized = false; uint32_t clockAt = 0; size_t nextClient = 0;
// Spool only ciphertext: the AES key changes each boot and stays in RAM.
mbedtls_aes_context spoolCipher;
struct Incoming { uint8_t nonce[16] = {}, counter[16] = {}, streamBlock[16] = {}; size_t cipherOffset = 0; uint32_t handle = 0, started = 0; size_t bytes = 0; File file; bool ready = false, failed = false; };
Incoming incoming[MAX_BT_CLIENTS];
void cooperateStorage() { if (initialized) pumpNetwork(); yield(); }
std::string requestPath(size_t index) { return "/bww/request-" + std::to_string(index) + ".enc"; }
class SpoolInput {
    File& file_; uint8_t counter_[16], stream_[16] = {}, buffer_[512]; size_t offset_ = 0, used_ = 0, available_ = 0;
public:
    bool good = true;
    SpoolInput(File& file, const uint8_t nonce[16]) : file_(file) { memcpy(counter_, nonce, 16); }
    int read() {
        if (!good) return -1;
        if (used_ == available_) {
            available_ = file_.read(buffer_, sizeof(buffer_)); used_ = 0;
            if (!available_) return -1;
            if (mbedtls_aes_crypt_ctr(&spoolCipher, available_, &offset_, counter_, stream_, buffer_, buffer_) != 0) { good = false; return -1; }
        }
        return buffer_[used_++];
    }
};
// Called from the main loop, password hashing, and transmission waits. SD access
// stays on one task; Bluetooth callbacks only enqueue into each client's queue.
void pumpNetwork() {
    bluetooth.handlePairing();
    for (size_t index = 0; index < MAX_BT_CLIENTS; ++index) {
        auto& frame = incoming[index]; uint32_t handle = bluetooth.clientHandle(index);
        if (frame.handle != handle) {
            frame.file.close(); SD.remove(requestPath(index).c_str());
            frame.handle = handle; frame.started = 0; frame.bytes = 0; frame.ready = frame.failed = false;
        }
        if (!handle || frame.ready || frame.failed) continue;
        if (frame.started && millis() - frame.started > 120000) { frame.file.close(); frame.failed = true; bluetooth.disconnect(index, handle); continue; }
        if (!bluetooth.available(index)) continue;
        if (!frame.file) {
            if (!fileMemoryReady()) { frame.failed = true; bluetooth.disconnect(index, handle); continue; }
            SD.remove(requestPath(index).c_str()); frame.file = SD.open(requestPath(index).c_str(), FILE_WRITE); frame.started = millis();
            esp_fill_random(frame.nonce, sizeof(frame.nonce)); memcpy(frame.counter, frame.nonce, sizeof(frame.counter));
            memset(frame.streamBlock, 0, sizeof(frame.streamBlock)); frame.cipherOffset = 0;
            if (!frame.file) { frame.failed = true; bluetooth.disconnect(index, handle); continue; }
        }
        uint8_t buffer[512]; size_t count = 0;
        while (count < sizeof(buffer)) {
            int byte = bluetooth.read(index, handle); if (byte < 0) break;
            if (byte != '\n' && ++frame.bytes > MAX_WIRE_BYTES) { frame.failed = true; bluetooth.disconnect(index, handle); break; }
            buffer[count++] = static_cast<uint8_t>(byte);
            if (byte == '\n') { frame.ready = true; break; }
        }
        if (count && (mbedtls_aes_crypt_ctr(&spoolCipher, count, &frame.cipherOffset, frame.counter, frame.streamBlock, buffer, buffer) != 0 || frame.file.write(buffer, count) != count)) { frame.failed = true; frame.ready = false; bluetooth.disconnect(index, handle); }
        if (frame.ready || frame.failed) { frame.file.flush(); frame.file.close(); }
    }
}
void setup() {
    beginActivityLed();
    bluetooth.setActivity(markActivityLed);
    Serial.begin(115200); delay(300);
    Serial.printf("Bluetooth-wide Web ESP32 firmware %s: SD CS=5 SCK=18 MOSI=23 MISO=19\n", FIRMWARE_VERSION);
    SPI.begin(SD_SCK, SD_MISO, SD_MOSI, SD_CS);
    if (rpc.capacity() != RPC_CAPACITY || !SD.begin(SD_CS, SPI, SD_FREQUENCY) || SD.cardType() == CARD_NONE || !core.begin()) {
        Serial.println("SD/storage initialization failed. Check wiring, FAT32, power, and /bww backups. No data is automatically formatted or reset."); return;
    }
    Serial.printf("SD storage: usable=%llu bytes, free=%llu bytes, upload reserve=%llu bytes; total website count uses SD space, max per account=%u\n",
        static_cast<unsigned long long>(disk.totalBytes()), static_cast<unsigned long long>(disk.freeBytes()),
        static_cast<unsigned long long>(SD_RESERVE_BYTES), static_cast<unsigned>(MAX_USER_SITES));
    if (!bluetooth.begin("BWW-ESP32")) { Serial.println("Bluetooth startup stopped. See the preceding step/error; restart after correcting it."); return; }
    uint8_t key[32]; esp_fill_random(key, sizeof(key)); mbedtls_aes_init(&spoolCipher);
    int cipherResult = mbedtls_aes_setkey_enc(&spoolCipher, key, 256); memset(key, 0, sizeof(key));
    if (cipherResult != 0) { Serial.println("Request spool encryption initialization failed"); return; }
    for (size_t index = 0; index < MAX_BT_CLIENTS; ++index) SD.remove(requestPath(index).c_str());
    bluetooth.setCooperate(pumpNetwork);
    initialized = true; clockAt = millis();
}
void loop() {
    if (!initialized) { delay(1000); return; }
    pumpNetwork();
    uint32_t now = millis(), seconds = (now - clockAt) / 1000;
    if (seconds) { clockAt += seconds * 1000; if (!core.advance(seconds)) Serial.println("SD clock checkpoint failed"); }
    for (size_t offset = 0; offset < MAX_BT_CLIENTS; ++offset) {
        size_t index = (nextClient + offset) % MAX_BT_CLIENTS;
        auto& pending = incoming[index]; if (!pending.ready) continue;
        uint32_t handle = pending.handle;
        if (!fileMemoryReady()) { pending.ready = false; pending.failed = true; bluetooth.disconnect(index, pending.handle); continue; }
        File input = SD.open(requestPath(index).c_str(), FILE_READ);
        SpoolInput plaintext(input, pending.nonce); RequestFrame<SpoolInput> frame(plaintext);
        rpc.clear(); auto result = deserializeJson(rpc, frame, DeserializationOption::NestingLimit(16));
        bool clean = frame.finish(); input.close(); SD.remove(requestPath(index).c_str());
        pending.ready = false; pending.bytes = 0; pending.started = 0;
        if (!frame.complete() || frame.tooLarge) { bluetooth.disconnect(index, handle); rpc.clear(); }
        else {
            bool authentication = rpc["op"] == "login" || rpc["op"] == "register";
            uint32_t requestStarted = millis();
            if (result || !clean) failure(rpc, result == DeserializationError::NoMemory ? "too_large" : "invalid_json", "Invalid or oversized JSON request");
            else core.execute(rpc);
            ReplyWriter output(bluetooth, index, handle); serializeJson(rpc, output); output.write('\n'); output.flush();
            rpc.clear(); if (!output.good) bluetooth.disconnect(index, handle);
            if (authentication) Serial.printf("Authentication processing and reply: elapsed=%lu ms\n", static_cast<unsigned long>(millis() - requestStarted));
        }
        nextClient = (index + 1) % MAX_BT_CLIENTS; break;
    }
    delay(1);
}
