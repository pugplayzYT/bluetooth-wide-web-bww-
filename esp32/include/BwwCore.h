#pragma once
#include <ArduinoJson.h>
#include <cstdint>
#include <string>
#include <vector>
#include <array>
#include <functional>
#include "BwwConfig.h"
namespace bww {
class Storage {
public:
    virtual ~Storage() = default;
    virtual bool exists(const std::string& path) = 0;
    virtual bool mkdir(const std::string& path) = 0;
    virtual bool readJson(const std::string& path, JsonDocument& doc) = 0;
    virtual bool writeJson(const std::string& path, const JsonDocument& doc) = 0;
    virtual bool writeBytes(const std::string& path, const std::string& bytes) = 0;
    virtual bool readBytes(const std::string& path, size_t maxBytes, std::string& bytes) = 0;
    virtual bool remove(const std::string& path) = 0;
    // Stream entries; cleanup must not materialize an SD-sized directory in RAM.
    virtual bool visitFiles(const std::string& directory, const std::function<void(const std::string&)>& visitor) = 0;
};
class Crypto {
public:
    virtual ~Crypto() = default;
    virtual std::string randomHex(size_t bytes) = 0;
    virtual std::string sha256(const std::string& value) = 0;
    virtual std::string jsonDigest(JsonVariantConst value) = 0;
    virtual std::string passwordHash(const std::string& password, const std::string& saltHex) = 0;
};
bool canonicalDomain(const std::string& value, std::string& domain);
bool validUtf8(const std::string& value, size_t* utf16Length = nullptr);
bool constantTimeEqual(const std::string& a, const std::string& b);
std::string hex(const uint8_t* bytes, size_t count);
bool unhex(const std::string& value, std::vector<uint8_t>& bytes);
// Shared PBKDF2 algorithm; both native tests and ESP32 supply a SHA-256 HMAC callback.
template<class Hmac, class Yield>
bool pbkdf2(const std::vector<uint8_t>& salt, Hmac hmac, Yield cooperate, uint8_t out[32]) {
    std::vector<uint8_t> first(salt); first.insert(first.end(), {0, 0, 0, 1});
    uint8_t u[32];
    if (!hmac(first.data(), first.size(), u)) return false;
    for (size_t i = 0; i < 32; ++i) out[i] = u[i];
    for (uint32_t round = 1; round < PASSWORD_ITERATIONS; ++round) {
        uint8_t next[32];
        if (!hmac(u, 32, next)) return false;
        for (size_t i = 0; i < 32; ++i) { u[i] = next[i]; out[i] ^= u[i]; }
        if ((round & 255) == 0) cooperate();
    }
    return true;
}
class Core {
public:
    Core(Storage& storage, Crypto& crypto);
    bool begin();
    // Updates the persisted clock by powered elapsed time, never by an untrusted client clock.
    bool advance(uint32_t elapsedSeconds);
    void execute(JsonDocument& rpc);
    bool ready() const { return ready_; }
private:
    Storage& storage_;
    Crypto& crypto_;
    DynamicJsonDocument state_;
    bool ready_ = false;
    int active_ = 0;
    uint64_t clock_ = 0, checkpoint_ = 0;
    struct Chunk { size_t bytes; std::string hash; };
    struct Upload {
        std::string id, domain, owner, session, expectedFingerprint;
        uint64_t touched = 0;
        size_t bytes = 0;
        bool htmlNonempty = false;
        std::array<std::vector<Chunk>, 3> chunks;
    };
    std::vector<Upload> uploads_;
    void transfer(JsonDocument& rpc, const std::string& op, const std::string& owner);
    bool canPublish(const std::string& domain, const std::string& owner, JsonDocument& rpc);
    bool readSite(JsonDocument& rpc, JsonObjectConst record);
    bool validChunks(JsonObjectConst data);
    std::string siteFingerprint(JsonDocument& rpc, JsonObjectConst record);
    bool syncUnchanged(const std::string& domain, const std::string& expected, JsonDocument& rpc);
    bool validState(JsonDocument& state);
    bool commit();
    void pruneSites();
    std::string identity(JsonObjectConst request);
    std::string sitePath(JsonObjectConst site) const;
    JsonObject site(const std::string& domain);
    JsonObject user(const std::string& username);
};
void failure(JsonDocument& rpc, const char* code, const char* message);
}
