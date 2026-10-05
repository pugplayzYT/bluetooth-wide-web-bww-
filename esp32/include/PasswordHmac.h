#pragma once
#include <mbedtls/sha256.h>
#include <cstdint>
#include <cstring>
#include <string>

namespace bww {
// PBKDF2 uses one key for every round. Keep the SHA states after the key pads
// instead of hashing those same two 64-byte blocks 210,000 times.
class PasswordHmac {
    mbedtls_sha256_context inner_, outer_;
    bool good_ = false;
    static void erase(uint8_t* bytes, size_t count) {
        volatile uint8_t* p = bytes;
        while (count--) *p++ = 0;
    }
public:
    explicit PasswordHmac(const std::string& password) {
        mbedtls_sha256_init(&inner_); mbedtls_sha256_init(&outer_);
        uint8_t key[64] = {}, pad[64];
        bool ok = true;
        if (password.size() > sizeof(key))
            ok = mbedtls_sha256_ret(reinterpret_cast<const uint8_t*>(password.data()), password.size(), key, 0) == 0;
        else memcpy(key, password.data(), password.size());
        for (unsigned side = 0; ok && side < 2; ++side) {
            for (size_t i = 0; i < sizeof(pad); ++i) pad[i] = key[i] ^ (side ? 0x5c : 0x36);
            mbedtls_sha256_context work; mbedtls_sha256_init(&work);
            ok = mbedtls_sha256_starts_ret(&work, 0) == 0 && mbedtls_sha256_update_ret(&work, pad, sizeof(pad)) == 0;
            // On original ESP32, clone snapshots the hardware state into a
            // software context. Free work immediately to release the SHA engine;
            // never hold its lock while yielding or servicing other clients.
            if (ok) mbedtls_sha256_clone(side ? &outer_ : &inner_, &work);
            mbedtls_sha256_free(&work);
        }
        erase(key, sizeof(key)); erase(pad, sizeof(pad)); good_ = ok;
    }
    ~PasswordHmac() { mbedtls_sha256_free(&inner_); mbedtls_sha256_free(&outer_); }
    PasswordHmac(const PasswordHmac&) = delete;
    PasswordHmac& operator=(const PasswordHmac&) = delete;
    bool operator()(const uint8_t* data, size_t size, uint8_t out[32]) {
        if (!good_) return false;
        uint8_t digest[32] = {};
        mbedtls_sha256_context work; mbedtls_sha256_init(&work);
        mbedtls_sha256_clone(&work, &inner_);
        bool ok = mbedtls_sha256_update_ret(&work, data, size) == 0 && mbedtls_sha256_finish_ret(&work, digest) == 0;
        if (ok) {
            mbedtls_sha256_clone(&work, &outer_);
            ok = mbedtls_sha256_update_ret(&work, digest, sizeof(digest)) == 0 && mbedtls_sha256_finish_ret(&work, out) == 0;
        }
        mbedtls_sha256_free(&work); erase(digest, sizeof(digest)); return ok;
    }
};

// Called at PBKDF2's bounded round checkpoints. Yield by elapsed time rather
// than sleeping after every checkpoint; unsigned subtraction handles rollover.
class PasswordCooperation {
    uint32_t last_;
public:
    explicit PasswordCooperation(uint32_t now) : last_(now) {}
    bool due(uint32_t now) {
        if (static_cast<uint32_t>(now - last_) < 16) return false;
        last_ = now; return true;
    }
};
}
