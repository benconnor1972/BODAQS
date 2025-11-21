#include "ButtonManager.h"
#include <Arduino.h>
#include "freertos/FreeRTOS.h"
#include "freertos/portmacro.h"

#define MAX_BUTTONS 10
static Button buttons[MAX_BUTTONS];
static int buttonCount = 0;
static bool s_pollingEnabled = true;
static uint32_t s_pollIntervalMs = 8;  // throttle so we don’t scan every loop() tick
static unsigned long s_lastPollMs = 0;


static portMUX_TYPE buttonMux = portMUX_INITIALIZER_UNLOCKED;

// --- Hold configuration ---
static const unsigned long HOLD_THRESHOLD_MS = 800;  // long-press threshold

void ButtonManager_setPollingEnabled(bool enabled) { s_pollingEnabled = enabled; }
void ButtonManager_setPollIntervalMs(uint32_t ms)  { s_pollIntervalMs = ms ? ms : 1; }


// Per-button hold tracking (kept here to avoid changing the header)
static unsigned long s_pressStartMs[MAX_BUTTONS] = {0};
static bool          s_heldPosted [MAX_BUTTONS] = {0};

// --- Double-click configuration ---
static const unsigned long DOUBLE_CLICK_WINDOW_MS = 350;  // tweak to taste

// Per-button double-click tracking
static unsigned long s_lastReleaseMs     [MAX_BUTTONS] = {0};
static uint8_t       s_clickCount        [MAX_BUTTONS] = {0};
static bool          s_singleClickPending[MAX_BUTTONS] = {0};

// Forward ISR declaration
void IRAM_ATTR handleButtonInterrupt(void* arg);

// Handle a debounced RELEASE edge in non-ISR context
static void handleReleaseGesture_(int idx, Button &b, unsigned long now) {
  // If a hold was already posted, treat this as "long press end":
  // do NOT generate click/double-click.
  if (s_heldPosted[idx]) {
    s_heldPosted[idx]         = false;
    s_clickCount[idx]         = 0;
    s_singleClickPending[idx] = false;
    s_lastReleaseMs[idx]      = 0;
    return;
  }

  // Short press: candidate for single or double click
  if (now - s_lastReleaseMs[idx] <= DOUBLE_CLICK_WINDOW_MS) {
    // second click within window
    s_clickCount[idx]++;
  } else {
    // too late -> start new sequence
    s_clickCount[idx] = 1;
  }

  s_lastReleaseMs[idx] = now;

  if (s_clickCount[idx] >= 2) {
    // Double-click detected
    s_clickCount[idx]         = 0;
    s_singleClickPending[idx] = false;
    if (b.callback) b.callback(BUTTON_DOUBLE_CLICK);
  } else {
    // Maybe-single-click; we’ll confirm later if no second click arrives
    s_singleClickPending[idx] = true;
  }
}

// Utility: post an event (ISR-safe if called with *_ISR variants)
static inline void postEvent_(Button& b, ButtonEvent ev) {
  portENTER_CRITICAL(&buttonMux);
  b.event = ev;
  b.eventFlag = true;
  portEXIT_CRITICAL(&buttonMux);
}

// Utility: get index of a Button* inside buttons[]
static inline int indexOf_(const Button* ptr) {
  int idx = (int)(ptr - buttons);
  return (idx >= 0 && idx < buttonCount) ? idx : -1;
}

void ButtonManager_register(uint8_t pin, ButtonMode mode, unsigned long debounceDelay, ButtonCallback cb) {
  if (buttonCount >= MAX_BUTTONS) return;

  // Active-LOW wiring assumed: use pull-up
  pinMode(pin, INPUT_PULLUP);

  // Initialize lastState from the real pin level
  bool initial = (digitalRead(pin) != 0);

  buttons[buttonCount] = {
    pin,
    initial,             // lastState
    0UL,                 // lastDebounceTime
    debounceDelay,
    mode,
    false,               // eventFlag
    BUTTON_NONE,         // event
    cb
  };

  // init hold tracking for this slot
  s_pressStartMs[buttonCount] = 0;
  s_heldPosted   [buttonCount] = false;
    // init double-click tracking for this slot
  s_lastReleaseMs     [buttonCount] = 0;
  s_clickCount        [buttonCount] = 0;
  s_singleClickPending[buttonCount] = false;


  if (mode == BUTTON_INTERRUPT) {
    attachInterruptArg(digitalPinToInterrupt(pin), handleButtonInterrupt, &buttons[buttonCount], CHANGE);
  }
  buttonCount++;
}

ButtonEvent ButtonManager_read(uint8_t pin) {
  // Optional single-pin polled read (edge with debounce)
  for (int i = 0; i < buttonCount; i++) {
    Button &b = buttons[i];
    if (b.pin != pin) continue;
    bool reading = (digitalRead(b.pin) != 0);
    if (reading != b.lastState) {
      unsigned long now = millis();
      if (now - b.lastDebounceTime >= b.debounceDelay) {
        b.lastDebounceTime = now;
        b.lastState = reading;

        // Start/stop hold timing only when edge is accepted
        if (reading == LOW) { // pressed (active-LOW)
          s_pressStartMs[i] = now;
          s_heldPosted[i]   = false;
          return BUTTON_PRESSED;
        } else {              // released
          s_pressStartMs[i] = 0;
          s_heldPosted[i]   = false;
          return BUTTON_RELEASED;
        }
      }
    } else {
      // If still pressed, check for hold
      if (b.lastState == LOW && s_pressStartMs[i] != 0 && !s_heldPosted[i]) {
        unsigned long now = millis();
        if (now - s_pressStartMs[i] >= HOLD_THRESHOLD_MS) {
          s_heldPosted[i] = true;
          return BUTTON_HELD;  // one-shot
        }
      }
    }
    break;
  }
  return BUTTON_NONE;
}

void ButtonManager_loop() {
  // 1) Deliver events posted by ISR (interrupt-mode buttons)
  for (int i = 0; i < buttonCount; ++i) {
    Button &b = buttons[i];
    if (b.mode != BUTTON_INTERRUPT) continue;

    bool hasEvent = false;
    ButtonEvent ev = BUTTON_NONE;

    portENTER_CRITICAL(&buttonMux);
    if (b.eventFlag) {
      hasEvent = true;
      ev = b.event;
      b.eventFlag = false;
    }
    portEXIT_CRITICAL(&buttonMux);

    if (hasEvent) {
      unsigned long now = millis();

      // Feed RELEASE edges into gesture logic (click/double-click)
      if (ev == BUTTON_RELEASED) {
        handleReleaseGesture_(i, b, now);
      }

      if (b.callback) {
        // still deliver raw PRESSED/RELEASED for configs bound to them
        b.callback(ev);
      }
    }

    // Long-press detection for interrupt-mode:
    // ISR updates b.lastState on edges; we watch for sustained LOW here.
    if (b.lastState == LOW) {
      if (!s_heldPosted[i] && s_pressStartMs[i] != 0) {
        unsigned long now = millis();
        if (now - s_pressStartMs[i] >= HOLD_THRESHOLD_MS) {
          s_heldPosted[i] = true;
          if (b.callback) b.callback(BUTTON_HELD);
        }
      }
    }
    // Note: release cleanup for holds and clicks happens in handleReleaseGesture_()

  }

  // 2) Poll buttons registered in BUTTON_POLL mode
  if (s_pollingEnabled) {
    unsigned long now = millis();
    if (now - s_lastPollMs >= s_pollIntervalMs) {
      s_lastPollMs = now;

      for (int i = 0; i < buttonCount; ++i) {
        Button &b = buttons[i];
        if (b.mode != BUTTON_POLL) continue;

        bool reading = (digitalRead(b.pin) != 0);
        if (reading != b.lastState) {
          unsigned long nowEdge = millis();
          if (nowEdge - b.lastDebounceTime >= b.debounceDelay) {
            b.lastDebounceTime = nowEdge;
            b.lastState = reading;

            if (reading == LOW) {
              s_pressStartMs[i] = nowEdge;
              s_heldPosted[i]   = false;
              if (b.callback) b.callback(BUTTON_PRESSED);
            } else {
              // RELEASE edge: handle click/double-click and reset hold
              handleReleaseGesture_(i, b, nowEdge);

              s_pressStartMs[i] = 0;
              s_heldPosted[i]   = false;
              if (b.callback) b.callback(BUTTON_RELEASED);
            }
          }
        } else {
          if (b.lastState == LOW && s_pressStartMs[i] != 0 && !s_heldPosted[i]) {
            if (now - s_pressStartMs[i] >= HOLD_THRESHOLD_MS) {
              s_heldPosted[i] = true;
              if (b.callback) b.callback(BUTTON_HELD);
            }
          }
        }
      } // for
    }   // interval gate
  }     // s_pollingEnabled
  // 3) Finalize pending single-clicks for all buttons
  unsigned long nowFinal = millis();
  for (int i = 0; i < buttonCount; ++i) {
    if (s_singleClickPending[i] &&
        (nowFinal - s_lastReleaseMs[i] > DOUBLE_CLICK_WINDOW_MS)) {

      s_singleClickPending[i] = false;
      s_clickCount[i]         = 0;

      Button &b = buttons[i];
      if (b.callback) {
        b.callback(BUTTON_CLICK);
      }
    }
  }
}

void IRAM_ATTR handleButtonInterrupt(void* arg) {
  Button* btn = reinterpret_cast<Button*>(arg);
  unsigned long now = millis();

  if (now - btn->lastDebounceTime < btn->debounceDelay) return;

  bool reading = (digitalRead(btn->pin) != 0);
  if (reading == btn->lastState) return;

  btn->lastDebounceTime = now;
  btn->lastState = reading;

  int idx = indexOf_(btn);
  if (idx >= 0) {
    if (reading == LOW) {
      // PRESS
      s_pressStartMs[idx] = now;
      s_heldPosted[idx]   = false;

      portENTER_CRITICAL_ISR(&buttonMux);
      btn->event     = BUTTON_PRESSED;
      btn->eventFlag = true;
      portEXIT_CRITICAL_ISR(&buttonMux);
    } else {
      // RELEASE — post it too
      portENTER_CRITICAL_ISR(&buttonMux);
      btn->event     = BUTTON_RELEASED;
      btn->eventFlag = true;
      portEXIT_CRITICAL_ISR(&buttonMux);

      // Clear timing; keep s_heldPosted as-is so gesture logic can see it
      s_pressStartMs[idx] = 0;
    }
  }
}
