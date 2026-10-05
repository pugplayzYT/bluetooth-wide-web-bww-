#include "BwwCore.h"
#include "PasswordHmac.h"
#include <openssl/evp.h>
#include <openssl/hmac.h>
#include <chrono>
#include <iostream>
#include <stdexcept>
using namespace bww;
void require(bool value) { if (!value) throw std::runtime_error("Password hash regression"); }
int main() {
    std::vector<std::string> passwords = {"", "correct horse battery", std::string(63, 'a'), std::string(64, 'b'),
        std::string(65, 'c'), std::string(256, 'd'), "caf\xc3\xa9 \xf0\x9f\x8c\xb1 password", std::string("abc\0def", 7)};
    for (const auto& password : passwords) {
        PasswordHmac hmac(password);
        for (size_t length : {0u, 20u, 32u, 55u, 56u, 64u, 129u}) {
            std::vector<uint8_t> message(length, 0xa5); uint8_t actual[32], expected[32]; unsigned size;
            require(hmac(message.data(), message.size(), actual));
            require(HMAC(EVP_sha256(), password.data(), password.size(), message.data(), message.size(), expected, &size) && size == 32);
            require(memcmp(actual, expected, 32) == 0);
        }
        std::vector<uint8_t> salt(16); for (size_t i = 0; i < salt.size(); ++i) salt[i] = i * 17;
        uint8_t actual[32], expected[32]; unsigned checkpoints = 0;
        require(pbkdf2(salt, [&](const uint8_t* p, size_t n, uint8_t* out) { return hmac(p, n, out); }, [&] { ++checkpoints; }, actual));
        require(PKCS5_PBKDF2_HMAC(password.data(), password.size(), salt.data(), salt.size(), PASSWORD_ITERATIONS, EVP_sha256(), 32, expected) == 1);
        require(memcmp(actual, expected, 32) == 0); require(checkpoints == (PASSWORD_ITERATIONS - 1) / 256);
    }
    PasswordCooperation clock(100);
    require(!clock.due(100) && !clock.due(115) && clock.due(116) && !clock.due(117) && clock.due(132));
    PasswordCooperation rollover(UINT32_MAX - 7);
    require(!rollover.due(7) && rollover.due(8));
    // Compare SHA work on the same host/backend. This is not an ESP32 timing.
    std::string password = "correct horse battery"; uint8_t innerPad[64], outerPad[64];
    for (size_t i = 0; i < 64; ++i) {
        uint8_t key = i < password.size() ? password[i] : 0;
        innerPad[i] = key ^ 0x36; outerPad[i] = key ^ 0x5c;
    }
    auto baseline = [&](const uint8_t* data, size_t size, uint8_t out[32]) {
        mbedtls_sha256_context ctx; mbedtls_sha256_init(&ctx); uint8_t digest[32];
        bool ok = mbedtls_sha256_starts_ret(&ctx, 0) == 0 && mbedtls_sha256_update_ret(&ctx, innerPad, 64) == 0 &&
            mbedtls_sha256_update_ret(&ctx, data, size) == 0 && mbedtls_sha256_finish_ret(&ctx, digest) == 0 &&
            mbedtls_sha256_starts_ret(&ctx, 0) == 0 && mbedtls_sha256_update_ret(&ctx, outerPad, 64) == 0 &&
            mbedtls_sha256_update_ret(&ctx, digest, 32) == 0 && mbedtls_sha256_finish_ret(&ctx, out) == 0;
        mbedtls_sha256_free(&ctx); return ok;
    };
    std::vector<uint8_t> salt(16, 0x12); uint8_t oldHash[32], newHash[32]; PasswordHmac prepared(password);
    auto start = std::chrono::steady_clock::now(); require(pbkdf2(salt, baseline, [] {}, oldHash));
    auto middle = std::chrono::steady_clock::now();
    require(pbkdf2(salt, [&](const uint8_t* p, size_t n, uint8_t* out) { return prepared(p, n, out); }, [] {}, newHash));
    auto end = std::chrono::steady_clock::now(); require(memcmp(oldHash, newHash, 32) == 0);
    std::cout << "Prepared HMAC: 56 HMAC vectors and 8 full 210000-round PBKDF2 vectors matched OpenSSL; cooperation/rollover passed\n"
        << "Host-only SHA benchmark: repeated pads=" << std::chrono::duration_cast<std::chrono::milliseconds>(middle-start).count()
        << " ms; prepared pads=" << std::chrono::duration_cast<std::chrono::milliseconds>(end-middle).count() << " ms\n";
}
