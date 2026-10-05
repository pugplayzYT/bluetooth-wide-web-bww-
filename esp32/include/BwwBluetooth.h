#pragma once
#include <Arduino.h>
#include <atomic>
#include <esp_spp_api.h>
#include <esp_gap_bt_api.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/event_groups.h>
// Native SPP is used so the listener explicitly requires authentication AND encryption.
class BwwBluetooth {
public:
    bool begin(const char* name);
    bool connected() const { return handle_ != 0; }
    int available() const;
    int read();
    bool write(const uint8_t* bytes, size_t size);
    void disconnect();
    void handlePairing();
private:
    static BwwBluetooth* instance_;
    static void sppCallback(esp_spp_cb_event_t event, esp_spp_cb_param_t* param);
    static void gapCallback(esp_bt_gap_cb_event_t event, esp_bt_gap_cb_param_t* param);
    QueueHandle_t receive_ = nullptr;
    EventGroupHandle_t transmit_ = nullptr;
    std::atomic<uint32_t> handle_{0};
    std::atomic<bool> pairingPending_{false};
    volatile uint32_t pairingAt_ = 0;
    uint8_t pairingAddress_[6] = {};
    const char* name_ = nullptr;
};
