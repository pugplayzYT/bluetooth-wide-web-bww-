#include "BwwBluetooth.h"
#include <esp_bt.h>
#include <esp_bt_main.h>
#include <esp_bt_device.h>
#include <esp_system.h>
#if !defined(CONFIG_BT_SPP_ENABLED)
#error "BWW requires an ORIGINAL ESP32 with Bluetooth Classic SPP, not an ESP32-S3/C3/C6."
#endif
#if CONFIG_BT_ACL_CONNECTIONS < 3
#error "The Bluedroid build must support at least three ACL connections."
#endif
static_assert(bww::MAX_BT_CLIENTS <= BTDM_CONTROLLER_BR_EDR_MAX_ACL_CONN_LIMIT, "Too many controller clients");
static_assert(bww::MAX_BT_CLIENTS <= CONFIG_BT_ACL_CONNECTIONS, "Too many clients for the compiled Bluedroid host");
namespace { constexpr EventBits_t SENT = 1, FAILED = 2, CAN_SEND = 4; constexpr int PAIR_BUTTON = 0; }
BwwBluetooth* BwwBluetooth::instance_ = nullptr;
bool BwwBluetooth::begin(const char* name) {
    instance_ = this; name_ = name;
    for (auto& client : buffers_) {
        client.receive = xQueueCreate(4096, sizeof(uint8_t)); client.transmit = xEventGroupCreate();
        if (!client.receive || !client.transmit) return false;
    }
    pinMode(PAIR_BUTTON, INPUT_PULLUP);
    esp_bt_controller_mem_release(ESP_BT_MODE_BLE);
    esp_bt_controller_config_t config = BT_CONTROLLER_INIT_CONFIG_DEFAULT(); config.mode = ESP_BT_MODE_CLASSIC_BT;
    config.bt_max_acl_conn = bww::MAX_BT_CLIENTS;
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
    case ESP_SPP_SRV_OPEN_EVT: {
        if (param->srv_open.status != ESP_SPP_SUCCESS) break;
        int index = self->clients_.add(param->srv_open.handle);
        if (index < 0) { esp_spp_disconnect(param->srv_open.handle); break; }
        auto& client = self->buffers_[index];
        xQueueReset(client.receive); xEventGroupClearBits(client.transmit, SENT | FAILED);
        xEventGroupSetBits(client.transmit, CAN_SEND); Serial.println("Authenticated Bluetooth client connected (maximum 3)"); break;
    }
    case ESP_SPP_DATA_IND_EVT: {
        int index = self->clients_.find(param->data_ind.handle); if (index < 0) break;
        for (size_t i = 0; i < param->data_ind.len; ++i)
            if (xQueueSend(self->buffers_[index].receive, &param->data_ind.data[i], 0) != pdTRUE) { self->disconnect(index, param->data_ind.handle); break; }
        break;
    }
    case ESP_SPP_WRITE_EVT: {
        int index = self->clients_.find(param->write.handle); if (index < 0) break;
        auto events = self->buffers_[index].transmit;
        if (param->write.cong) xEventGroupClearBits(events, CAN_SEND); else xEventGroupSetBits(events, CAN_SEND);
        xEventGroupSetBits(events, param->write.status == ESP_SPP_SUCCESS ? SENT : FAILED); break;
    }
    case ESP_SPP_CONG_EVT: {
        int index = self->clients_.find(param->cong.handle); if (index < 0) break;
        if (param->cong.cong) xEventGroupClearBits(self->buffers_[index].transmit, CAN_SEND); else xEventGroupSetBits(self->buffers_[index].transmit, CAN_SEND);
        break;
    }
    case ESP_SPP_CLOSE_EVT: {
        int index = self->clients_.find(param->close.handle); if (index < 0) break;
        xEventGroupSetBits(self->buffers_[index].transmit, FAILED);
        self->clients_.release(index, param->close.handle);
        xQueueReset(self->buffers_[index].receive); Serial.println("Bluetooth client disconnected"); break;
    }
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
int BwwBluetooth::available(size_t index) const { return index < bww::MAX_BT_CLIENTS && buffers_[index].receive ? uxQueueMessagesWaiting(buffers_[index].receive) : 0; }
int BwwBluetooth::read(size_t index, uint32_t handle) {
    uint8_t byte; return connected(index, handle) && xQueueReceive(buffers_[index].receive, &byte, 0) == pdTRUE ? byte : -1;
}
EventBits_t BwwBluetooth::wait(size_t index, uint32_t handle, EventBits_t bits, bool clear) {
    uint32_t started = millis();
    while (connected(index, handle) && millis() - started < 20000) {
        auto result = xEventGroupWaitBits(buffers_[index].transmit, bits, clear ? pdTRUE : pdFALSE, pdFALSE, pdMS_TO_TICKS(5));
        if (result & bits) return result;
        handlePairing(); if (cooperate_) cooperate_();
    }
    return 0;
}
bool BwwBluetooth::write(size_t index, uint32_t handle, const uint8_t* bytes, size_t size) {
    while (size) {
        if (!connected(index, handle)) return false;
        size_t chunk = size > 512 ? 512 : size;
        auto ready = wait(index, handle, CAN_SEND | FAILED, false);
        if (!(ready & CAN_SEND) || (ready & FAILED) || !connected(index, handle)) { disconnect(index, handle); return false; }
        xEventGroupClearBits(buffers_[index].transmit, SENT | FAILED);
        if (esp_spp_write(handle, chunk, const_cast<uint8_t*>(bytes)) != ESP_OK) { disconnect(index, handle); return false; }
        auto result = wait(index, handle, SENT | FAILED, true);
        if (!(result & SENT) || (result & FAILED) || !connected(index, handle)) { disconnect(index, handle); return false; }
        bytes += chunk; size -= chunk;
        if (cooperate_) cooperate_();
    }
    return true;
}
void BwwBluetooth::disconnect(size_t index, uint32_t handle) { if (connected(index, handle)) esp_spp_disconnect(handle); }
