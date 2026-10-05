#include "BwwCore.h"
#include "RequestFrame.h"
#include "ClientSlots.h"
#include "FileMemory.h"
#include <new>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <openssl/evp.h>
#include <openssl/hmac.h>
#include <openssl/rand.h>
using namespace bww;
#ifdef BWW_TRACK_JSON_ALLOCATIONS
// Track actual ArduinoJson malloc calls without allocating inside the tracker.
static struct { void* pointer; size_t bytes; } jsonAllocations[128] = {};
static size_t jsonLive = 0, jsonPeak = 0, jsonLimit = SIZE_MAX, jsonRejected = 0;
extern "C" void* __real_malloc(size_t);
extern "C" void __real_free(void*);
// Interpose real C++ string/buffer allocations to detect a retained chunk at commit.
static struct { void* pointer; size_t bytes; } cppAllocations[4096] = {};
void* operator new(size_t bytes) {
    void* pointer = __real_malloc(bytes); if (!pointer) throw std::bad_alloc();
    for (auto& entry : cppAllocations) if (!entry.pointer) { entry = {pointer, bytes}; return pointer; }
    std::abort();
}
void operator delete(void* pointer) noexcept {
    for (auto& entry : cppAllocations) if (pointer && entry.pointer == pointer) { entry = {}; break; }
    __real_free(pointer);
}
void operator delete(void* pointer, size_t) noexcept { ::operator delete(pointer); }
void* operator new[](size_t bytes) { return ::operator new(bytes); }
void operator delete[](void* pointer) noexcept { ::operator delete(pointer); }
void operator delete[](void* pointer, size_t) noexcept { ::operator delete(pointer); }
bool liveChunk(const void* pointer) {
    for (const auto& entry : cppAllocations) if (entry.pointer == pointer && entry.bytes >= CHUNK_BYTES) return true;
    return false;
}
extern "C" void* __wrap_malloc(size_t bytes) {
    bool tracked = bytes == STATE_CAPACITY || bytes == RPC_CAPACITY;
    if (tracked && bytes > jsonLimit - jsonLive) { ++jsonRejected; return nullptr; }
    void* pointer = __real_malloc(bytes);
    if (tracked && pointer) {
        for (auto& entry : jsonAllocations) if (!entry.pointer) {
            entry = {pointer, bytes}; jsonLive += bytes; jsonPeak = std::max(jsonPeak, jsonLive); break;
        }
    }
    return pointer;
}
extern "C" void __wrap_free(void* pointer) {
    for (auto& entry : jsonAllocations) if (pointer && entry.pointer == pointer) { jsonLive -= entry.bytes; entry = {}; break; }
    __real_free(pointer);
}
#endif
class Disk : public Storage {
    std::filesystem::path root_;
public:
    bool failNextState = false;
#ifdef BWW_TRACK_JSON_ALLOCATIONS
    bool guardCommitChunk = false, fragmentedStateReads = false;
    const void* lastChunkBuffer = nullptr;
#endif
    explicit Disk(const char* path) : root_(path) {}
    std::filesystem::path path(const std::string& name) { return root_ / name.substr(1); }
    bool exists(const std::string& name) override { return std::filesystem::exists(path(name)); }
    bool mkdir(const std::string& name) override { std::error_code e; std::filesystem::create_directories(path(name), e); return !e; }
    bool readJson(const std::string& name, JsonDocument& doc) override {
#ifdef BWW_TRACK_JSON_ALLOCATIONS
        if (fragmentedStateReads && name.find("/state-") != std::string::npos && !fileMemoryAvailable(21512, 8180)) return false;
#endif
        doc.clear(); std::ifstream file(path(name)); return file && !deserializeJson(doc, file, DeserializationOption::NestingLimit(16));
    }
    bool writeJson(const std::string& name, const JsonDocument& doc) override {
#ifdef BWW_TRACK_JSON_ALLOCATIONS
        if (guardCommitChunk && name.find("/state-") != std::string::npos && liveChunk(lastChunkBuffer)) return false;
#endif
        std::ofstream file(path(name), std::ios::trunc | std::ios::binary);
        if (!file) return false;
        if (failNextState && name.find("/state-") != std::string::npos) { failNextState = false; file << "{incomplete"; return false; }
        serializeJson(doc, file); file.flush(); return file.good();
    }
    bool writeBytes(const std::string& name, const std::string& bytes) override {
        std::ofstream file(path(name), std::ios::binary | std::ios::trunc);
        file.write(bytes.data(), bytes.size()); file.flush(); return file.good();
    }
    bool readBytes(const std::string& name, size_t maxBytes, std::string& bytes) override {
        std::ifstream file(path(name), std::ios::binary | std::ios::ate);
        if (!file || file.tellg() < 0 || static_cast<size_t>(file.tellg()) > maxBytes) return false;
        bytes.resize(static_cast<size_t>(file.tellg())); file.seekg(0);
        file.read(bytes.data(), bytes.size());
#ifdef BWW_TRACK_JSON_ALLOCATIONS
        lastChunkBuffer = bytes.data();
#endif
        return file.good();
    }
    bool remove(const std::string& name) override { std::error_code e; std::filesystem::remove(path(name), e); return !e; }
    bool visitFiles(const std::string& directory, const std::function<void(const std::string&)>& visitor) override {
        for (auto& p : std::filesystem::directory_iterator(path(directory))) if (p.is_regular_file()) visitor(directory + "/" + p.path().filename().string());
        return true;
    }
};
class HashWriter {
    EVP_MD_CTX* context_;
public:
    bool good = true;
    explicit HashWriter(EVP_MD_CTX* context) : context_(context) {}
    size_t write(uint8_t byte) { return write(&byte, 1); }
    size_t write(const uint8_t* bytes, size_t count) { if (EVP_DigestUpdate(context_, bytes, count) != 1) good = false; return good ? count : 0; }
};
class NativeCrypto : public Crypto {
public:
    std::string randomHex(size_t bytes) override {
        std::vector<uint8_t> data(bytes); return RAND_bytes(data.data(), data.size()) == 1 ? hex(data.data(), data.size()) : "";
    }
    std::string sha256(const std::string& value) override {
        uint8_t digest[32]; unsigned length; return EVP_Digest(value.data(), value.size(), digest, &length, EVP_sha256(), nullptr) == 1 ? hex(digest, 32) : "";
    }
    std::string jsonDigest(JsonVariantConst value) override {
        EVP_MD_CTX* ctx = EVP_MD_CTX_new(); if (!ctx) return "";
        EVP_DigestInit_ex(ctx, EVP_sha256(), nullptr); HashWriter writer(ctx); serializeJson(value, writer);
        uint8_t digest[32]; unsigned length; bool ok = writer.good && EVP_DigestFinal_ex(ctx, digest, &length) == 1;
        EVP_MD_CTX_free(ctx); return ok ? hex(digest, 32) : "";
    }
    std::string passwordHash(const std::string& password, const std::string& saltHex) override {
        std::vector<uint8_t> salt; if (!unhex(saltHex, salt) || salt.size() != 16) return "";
        auto hmac = [&](const uint8_t* input, size_t size, uint8_t out[32]) {
            unsigned length; return HMAC(EVP_sha256(), password.data(), password.size(), input, size, out, &length) && length == 32;
        };
        uint8_t digest[32]; return pbkdf2(salt, hmac, [] {}, digest) ? hex(digest, 32) : "";
    }
};
int main(int argc, char** argv) {
    NativeCrypto crypto;
    if (argc == 2 && std::string(argv[1]) == "--file-memory-check") {
        if (!fileMemoryAvailable(21512, 8180) || fileMemoryAvailable(21512, 8180, 8193) ||
            fileMemoryAvailable(4096, 4096) || fileMemoryAvailable(40000, 3000) ||
            !fileMemoryAvailable(32768, 20000, 8193) || fileMemoryAvailable(SIZE_MAX, SIZE_MAX, SIZE_MAX)) return 1;
        std::cout << "Reported heap permits JSON/file I/O; chunk allocation and unsafe heap states stay guarded\n"; return 0;
    }
    if (argc == 2 && std::string(argv[1]) == "--slots-check") {
        ClientSlots slots;
        if (slots.add(10) != 0 || slots.add(20) != 1 || slots.add(30) != 2 || slots.add(40) != -1 || slots.find(20) != 1) return 1;
        if (!slots.release(1, 20) || slots.add(40) != 1 || slots.release(1, 20) || slots.handle(1) != 40 || slots.find(20) != -1 || slots.add(0) != -1 || slots.add(40) != 1) return 1;
        std::cout << "Three client slots preserve isolation and reject stale callbacks/fourth clients\n"; return 0;
    }
    if (argc == 2 && std::string(argv[1]) == "--crypto-check") {
        std::string password = "correct horse battery", saltHex(32, '0'); std::vector<uint8_t> salt; unhex(saltHex, salt);
        uint8_t expected[32];
        if (PKCS5_PBKDF2_HMAC(password.data(), password.size(), salt.data(), salt.size(), PASSWORD_ITERATIONS, EVP_sha256(), 32, expected) != 1 || !constantTimeEqual(crypto.passwordHash(password, saltHex), hex(expected, 32))) return 1;
        std::cout << "Shared PBKDF2 matches OpenSSL reference\n"; return 0;
    }
    if (argc != 2) return 1;
    Disk disk(argv[1]); Core core(disk, crypto); DynamicJsonDocument rpc(RPC_CAPACITY);
    if (!core.begin()) { std::cerr << "Storage initialization failed\n"; return 2; }
    std::string line;
    while (std::getline(std::cin, line)) {
        struct Source { std::string line; size_t offset = 0; int read() { return offset < line.size() ? static_cast<unsigned char>(line[offset++]) : -1; } } source{line + "\n"};
        RequestFrame<Source> frame(source);
        auto error = deserializeJson(rpc, frame, DeserializationOption::NestingLimit(16));
        bool clean = frame.finish();
        if (!clean && !error) failure(rpc, "invalid_json", "Trailing data or incomplete frame");
        else if (error) failure(rpc, error == DeserializationError::NoMemory ? "too_large" : "invalid_json", "Invalid or oversized JSON request");
        else if (rpc["_test"] == "fail_next_state") { disk.failNextState = true; rpc.clear(); rpc["ok"] = true; rpc.createNestedObject("data"); }
        else if (rpc["_test"] == "advance") { uint32_t seconds = rpc["seconds"]; bool ok = core.advance(seconds); rpc.clear(); rpc["ok"] = ok; rpc.createNestedObject("data"); }
#ifdef BWW_TRACK_JSON_ALLOCATIONS
        else if (rpc["_test"] == "guard_commit_chunk") { disk.guardCommitChunk = true; rpc.clear(); rpc["ok"] = true; rpc.createNestedObject("data"); }
        else if (rpc["_test"] == "fragmented_state_reads") { disk.fragmentedStateReads = true; rpc.clear(); rpc["ok"] = true; rpc.createNestedObject("data"); }
        else if (rpc["_test"] == "memory_budget") { jsonLimit = rpc["bytes"]; jsonPeak = jsonLive; jsonRejected = 0; rpc.clear(); rpc["ok"] = true; rpc.createNestedObject("data"); }
        else if (rpc["_test"] == "memory_stats") { rpc.clear(); rpc["ok"] = true; auto data = rpc.createNestedObject("data"); data["live"] = jsonLive; data["peak"] = jsonPeak; data["rejected"] = jsonRejected; }
#endif
        else core.execute(rpc);
        serializeJson(rpc, std::cout); std::cout << std::endl;
    }
}
