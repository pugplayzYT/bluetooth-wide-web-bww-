#pragma once
#include <cstddef>
#include <cstdint>
namespace bww {
constexpr int SD_CS = 5, SD_SCK = 18, SD_MOSI = 23, SD_MISO = 19;
constexpr uint32_t SD_FREQUENCY = 4000000;
constexpr size_t MAX_SITE_BYTES = 16 * 1024;
constexpr size_t RPC_CAPACITY = MAX_SITE_BYTES + 8192;
constexpr size_t STATE_CAPACITY = 16 * 1024;
constexpr size_t MAX_USERS = 12, MAX_SESSIONS = 24, MAX_SITES = 24, MAX_USER_SITES = 8;
constexpr uint32_t PASSWORD_ITERATIONS = 210000;
constexpr uint64_t SESSION_POWERED_SECONDS = 30ULL * 24 * 60 * 60;
constexpr uint32_t CLOCK_CHECKPOINT_SECONDS = 300;
constexpr size_t MAX_WIRE_BYTES = MAX_SITE_BYTES * 6 + 8192;
}
