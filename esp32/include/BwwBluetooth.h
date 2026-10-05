#pragma once
#include <Arduino.h>
#include <atomic>
#include "ClientSlots.h"
#include <esp_spp_api.h>
#include <esp_gap_bt_api.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/event_groups.h>
// Native SPP is used so the listener explicitly requires authentication AND encryption.
class BwwBluetooth {
public:
    bool begin(const char* name);
    uint32_t clientHandle(size_t index) const { return clients_.handle(index); }
    bool connected(size_t index, uint32_t handle) const { return handle && clientHandle(index) == handle; }
    int available(size_t index) const;
    int read(size_t index, uint32_t handle);
    bool write(size_t index, uint32_t handle, const uint8_t* bytes, size_t size);
    void disconnect(size_t index, uint32_t handle);
    void setCooperate(void (*callback)()) { cooperate_ = callback; }
    void setActivity(void (*callback)()) { activity_ = callback; }
    void handlePairing();
private:
    static BwwBluetooth* instance_;
    static void sppCallback(esp_spp_cb_event_t event, esp_spp_cb_param_t* param);
    static void gapCallback(esp_bt_gap_cb_event_t event, esp_bt_gap_cb_param_t* param);
    struct Client { QueueHandle_t receive = nullptr; EventGroupHandle_t transmit = nullptr; };
    Client buffers_[bww::MAX_BT_CLIENTS];
    bww::ClientSlots clients_;
    void (*cooperate_)() = nullptr;
    void (*activity_)() = nullptr;
    EventBits_t wait(size_t index, uint32_t handle, EventBits_t bits, bool clear);
    std::atomic<bool> pairingPending_{false};
    volatile uint32_t pairingAt_ = 0;
    uint8_t pairingAddress_[6] = {};
    const char* name_ = nullptr;
};
