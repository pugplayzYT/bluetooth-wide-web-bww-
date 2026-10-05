#pragma once
#include "BwwConfig.h"
#include <array>
#include <atomic>
namespace bww {
// Handles identify connections, so late callbacks cannot affect a reused slot.
class ClientSlots {
    std::array<std::atomic<uint32_t>, MAX_BT_CLIENTS> handles_{};
public:
    uint32_t handle(size_t index) const { return index < handles_.size() ? handles_[index].load() : 0; }
    int find(uint32_t value) const {
        if (value) for (size_t i = 0; i < handles_.size(); ++i) if (handle(i) == value) return static_cast<int>(i);
        return -1;
    }
    int add(uint32_t value) {
        if (!value) return -1;
        int existing = find(value); if (existing >= 0) return existing;
        for (size_t i = 0; i < handles_.size(); ++i) { uint32_t empty = 0; if (handles_[i].compare_exchange_strong(empty, value)) return static_cast<int>(i); }
        return -1;
    }
    bool release(size_t index, uint32_t value) { return index < handles_.size() && value && handles_[index].compare_exchange_strong(value, 0); }
};
}
