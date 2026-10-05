#pragma once
#include <cstddef>
#include <cstdint>
namespace bww {
constexpr const char* FIRMWARE_VERSION = "0.4.1";
constexpr int SD_CS = 5, SD_SCK = 18, SD_MOSI = 23, SD_MISO = 19;
constexpr uint32_t SD_FREQUENCY = 4000000;
constexpr size_t MAX_BT_CLIENTS = 3;
constexpr size_t MAX_SITE_BYTES = 512 * 1024;
// Whole sites stay on SD; only bounded requests/chunks occupy heap.
constexpr size_t INLINE_SITE_BYTES = 16 * 1024;
constexpr size_t CHUNK_BYTES = 8192;
constexpr size_t MAX_SITE_CHUNKS = MAX_SITE_BYTES / CHUNK_BYTES + 3;
constexpr size_t RPC_CAPACITY = INLINE_SITE_BYTES + 8192;
constexpr uint32_t UPLOAD_IDLE_SECONDS = 300;
constexpr size_t STATE_CAPACITY = 16 * 1024;
constexpr size_t MAX_USERS = 12, MAX_SESSIONS = 24, MAX_SITES = 24, MAX_USER_SITES = 8;
constexpr uint32_t PASSWORD_ITERATIONS = 210000;
constexpr uint64_t SESSION_POWERED_SECONDS = 30ULL * 24 * 60 * 60;
constexpr uint32_t CLOCK_CHECKPOINT_SECONDS = 300;
constexpr size_t MAX_WIRE_BYTES = INLINE_SITE_BYTES * 6 + 8192;
}
