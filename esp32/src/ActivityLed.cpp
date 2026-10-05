#include "ActivityLed.h"
#include <Arduino.h>
#include <atomic>
#include <esp_timer.h>

// Most esp32dev boards have an active-high user LED on GPIO2.
// Set the pin to -1 for boards without a controllable LED.
#ifndef BWW_ACTIVITY_LED_PIN
#define BWW_ACTIVITY_LED_PIN 2
#endif
#ifndef BWW_ACTIVITY_LED_ACTIVE_LOW
#define BWW_ACTIVITY_LED_ACTIVE_LOW 0
#endif

namespace {
std::atomic<bool> pendingActivity{false};
unsigned ticksRemaining = 0;
esp_timer_handle_t timer = nullptr;
bool lit = false;
void drive(bool on) {
    if (BWW_ACTIVITY_LED_PIN >= 0)
        digitalWrite(BWW_ACTIVITY_LED_PIN, on != bool(BWW_ACTIVITY_LED_ACTIVE_LOW) ? HIGH : LOW);
}
void tick(void*) {
    // The timer task keeps blinking even during SD operations or hashing.
    // Callbacks record activity only; they never delay Bluetooth traffic.
    if (pendingActivity.exchange(false)) ticksRemaining = 3;
    else if (ticksRemaining) --ticksRemaining;
    lit = ticksRemaining && !lit;
    drive(lit);
}
}
void markActivityLed() {
    pendingActivity.store(true);
}
void beginActivityLed() {
    if (BWW_ACTIVITY_LED_PIN < 0) return;
    drive(false);
    pinMode(BWW_ACTIVITY_LED_PIN, OUTPUT);
    esp_timer_create_args_t args = {};
    args.callback = tick;
    args.name = "bww-activity";
    esp_err_t result = esp_timer_create(&args, &timer);
    if (result == ESP_OK) result = esp_timer_start_periodic(timer, 80000);
    if (result != ESP_OK) {
        if (timer) { esp_timer_delete(timer); timer = nullptr; }
        Serial.printf("Activity LED timer unavailable: %d\n", int(result));
    }
}
