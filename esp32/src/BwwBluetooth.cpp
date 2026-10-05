#include "BwwBluetooth.h"
#include <esp_bt.h>
#include <esp_bt_main.h>
#include <esp_bt_device.h>
#include <esp_system.h>
#if !defined(CONFIG_BT_SPP_ENABLED)
#error "BWW requires an ORIGINAL ESP32 with Bluetooth Classic SPP, not an ESP32-S3/C3/C6."
#endif
namespace { constexpr EventBits_t SENT = 1, FAILED = 2, CAN_SEND = 4; constexpr int PAIR_BUTTON = 0; }
BwwBluetooth* BwwBluetooth::instance_ = nullptr;
bool BwwBluetooth::begin(const char* name) {
    instance_ = this; name_ = name;
    receive_ = xQueueCreate(4096, sizeof(uint8_t)); transmit_ = xEventGroupCreate();
    if (!receive_ || !transmit_) return false;
    pinMode(PAIR_BUTTON, INPUT_PULLUP);
    esp_bt_controller_mem_release(ESP_BT_MODE_BLE);
    esp_bt_controller_config_t config = BT_CONTROLLER_INIT_CONFIG_DEFAULT(); config.mode = ESP_BT_MODE_CLASSIC_BT;
    if (esp_bt_controller_init(&config) != ESP_OK || esp_bt_controller_enable(ESP_BT_MODE_CLASSIC_BT) != ESP_OK || esp_bluedroid_init() != ESP_OK || esp_bluedroid_enable() != ESP_OK) return false;
    if (esp_bt_gap_register_callback(gapCallback) != ESP_OK || esp_spp_register_callback(sppCallback) != ESP_OK) return false;
    uint8_t capability = ESP_BT_IO_CAP_IO;
    if (esp_bt_gap_set_security_param(ESP_BT_SP_IOCAP_MODE, &capability, sizeof(capability)) != ESP_OK) return false;
    return esp_spp_init(ESP_SPP_MODE_CB) == ESP_OK;
}
void BwwBluetooth::sppCallback(esp_spp_cb_event_t event, esp_spp_cb_param_t* param) {
    auto* self = instance_; if (!self) return;
    switch (event) {
    case ESP_SPP_INIT_EVT:
        if (param->init.status != ESP_SPP_SUCCESS) { Serial.println("Bluetooth initialization failed"); break; }
        esp_bt_dev_set_device_name(self->name_);
        esp_bt_gap_set_scan_mode(ESP_BT_CONNECTABLE, ESP_BT_GENERAL_DISCOVERABLE);
        if (esp_spp_start_srv(ESP_SPP_SEC_AUTHENTICATE | ESP_SPP_SEC_ENCRYPT, ESP_SPP_ROLE_SLAVE, 0, "Bluetooth-wide Web") != ESP_OK) Serial.println("Could not start secure Bluetooth SPP server");
        break;
    case ESP_SPP_START_EVT:
        Serial.println(param->start.status == ESP_SPP_SUCCESS ? "READY Bluetooth: pair with BWW-ESP32 in Android settings" : "Bluetooth SPP listener failed"); break;
    case ESP_SPP_SRV_OPEN_EVT:
        if (param->srv_open.status != ESP_SPP_SUCCESS) break;
        if (self->handle_) { esp_spp_disconnect(param->srv_open.handle); break; }
        xQueueReset(self->receive_); xEventGroupClearBits(self->transmit_, SENT | FAILED);
        self->handle_ = param->srv_open.handle; xEventGroupSetBits(self->transmit_, CAN_SEND); Serial.println("Authenticated Bluetooth client connected"); break;
    case ESP_SPP_DATA_IND_EVT:
        if (param->data_ind.handle != self->handle_) break;
        for (size_t i = 0; i < param->data_ind.len; ++i) if (xQueueSend(self->receive_, &param->data_ind.data[i], 0) != pdTRUE) { self->disconnect(); break; }
        break;
    case ESP_SPP_WRITE_EVT:
        if (param->write.handle == self->handle_) {
            if (param->write.cong) xEventGroupClearBits(self->transmit_, CAN_SEND); else xEventGroupSetBits(self->transmit_, CAN_SEND);
            xEventGroupSetBits(self->transmit_, param->write.status == ESP_SPP_SUCCESS ? SENT : FAILED);
        }
        break;
    case ESP_SPP_CONG_EVT:
        if (param->cong.handle == self->handle_) {
            if (param->cong.cong) xEventGroupClearBits(self->transmit_, CAN_SEND); else xEventGroupSetBits(self->transmit_, CAN_SEND);
        }
        break;
    case ESP_SPP_CLOSE_EVT:
        if (param->close.handle == self->handle_) { self->handle_ = 0; xQueueReset(self->receive_); xEventGroupSetBits(self->transmit_, FAILED); Serial.println("Bluetooth client disconnected"); }
        break;
    default: break;
    }
}
void BwwBluetooth::gapCallback(esp_bt_gap_cb_event_t event, esp_bt_gap_cb_param_t* param) {
    auto* self = instance_; if (!self) return;
    switch (event) {
    case ESP_BT_GAP_CFM_REQ_EVT:
        if (self->pairingPending_) { esp_bt_gap_ssp_confirm_reply(param->cfm_req.bda, false); break; }
        memcpy(self->pairingAddress_, param->cfm_req.bda, 6); self->pairingAt_ = millis();
        Serial.printf("Pairing code: %06lu. Compare with your phone, then type Y or press BOOT. N rejects.\n", static_cast<unsigned long>(param->cfm_req.num_val));
        self->pairingPending_ = true; break;
    case ESP_BT_GAP_PIN_REQ_EVT:
        // Legacy PIN pairing is rejected; use an Android device supporting Secure Simple Pairing.
        { esp_bt_pin_code_t empty = {}; esp_bt_gap_pin_reply(param->pin_req.bda, false, 0, empty); } break;
    case ESP_BT_GAP_AUTH_CMPL_EVT:
        Serial.println(param->auth_cmpl.stat == ESP_BT_STATUS_SUCCESS ? "Bluetooth pairing authenticated" : "Bluetooth pairing failed"); break;
    default: break;
    }
}
void BwwBluetooth::handlePairing() {
    if (!pairingPending_) return;
    bool answer = false, accept = false;
    if (Serial.available()) { char c = Serial.read(); if (c == 'y' || c == 'Y') { answer = true; accept = true; } else if (c == 'n' || c == 'N') answer = true; }
    if (digitalRead(PAIR_BUTTON) == LOW) { answer = true; accept = true; }
    if (millis() - pairingAt_ > 60000) { answer = true; accept = false; }
    if (answer) { esp_bt_gap_ssp_confirm_reply(pairingAddress_, accept); pairingPending_ = false; Serial.println(accept ? "Pairing approved" : "Pairing rejected"); }
}
int BwwBluetooth::available() const { return receive_ ? uxQueueMessagesWaiting(receive_) : 0; }
int BwwBluetooth::read() { uint8_t byte; return receive_ && xQueueReceive(receive_, &byte, 0) == pdTRUE ? byte : -1; }
bool BwwBluetooth::write(const uint8_t* bytes, size_t size) {
    while (size) {
        uint32_t client = handle_; if (!client) return false;
        size_t chunk = size > 512 ? 512 : size;
        auto ready = xEventGroupWaitBits(transmit_, CAN_SEND | FAILED, pdFALSE, pdFALSE, pdMS_TO_TICKS(20000));
        if (!(ready & CAN_SEND) || (ready & FAILED) || handle_ != client) { disconnect(); return false; }
        xEventGroupClearBits(transmit_, SENT | FAILED);
        if (esp_spp_write(client, chunk, const_cast<uint8_t*>(bytes)) != ESP_OK) return false;
        auto result = xEventGroupWaitBits(transmit_, SENT | FAILED, pdTRUE, pdFALSE, pdMS_TO_TICKS(20000));
        if (!(result & SENT) || (result & FAILED) || handle_ != client) { disconnect(); return false; }
        bytes += chunk; size -= chunk;
    }
    return true;
}
void BwwBluetooth::disconnect() { uint32_t client = handle_; if (client) esp_spp_disconnect(client); }
