#ifndef BUTTON_MANAGER_H
#define BUTTON_MANAGER_H

#include <Arduino.h>

enum ButtonEvent {
    BUTTON_NONE,
    BUTTON_PRESSED,
    BUTTON_RELEASED,
    BUTTON_HELD,        // existing long-press one-shot
    BUTTON_CLICK,       // future: short press+release
    BUTTON_DOUBLE_CLICK // future: double-click
};

enum ButtonMode {
    BUTTON_POLL,
    BUTTON_INTERRUPT
};

typedef void (*ButtonCallback)(ButtonEvent);

struct Button {
    uint8_t pin;
    bool lastState;                 // HIGH idle (pullup), LOW pressed
    unsigned long lastDebounceTime; // last accepted edge time
    unsigned long debounceDelay;    // ms
    ButtonMode mode;
    volatile bool eventFlag;        // set by ISR when an event is ready
    volatile ButtonEvent event;     // PRESSED or RELEASED
    ButtonCallback callback;        // delivered in ButtonManager_loop()
};

void ButtonManager_register(uint8_t pin, ButtonMode mode, unsigned long debounceDelay, ButtonCallback cb);
ButtonEvent ButtonManager_read(uint8_t pin); // optional; returns BUTTON_NONE if unused
void ButtonManager_loop();
void ButtonManager_setPollingEnabled(bool enabled);
void ButtonManager_setPollIntervalMs(uint32_t ms);

#endif
