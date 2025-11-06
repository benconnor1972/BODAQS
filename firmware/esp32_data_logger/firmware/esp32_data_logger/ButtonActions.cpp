#include "ButtonActions.h"
#include "LoggingManager.h"
#include "WebServerManager.h"
#include "StorageManager.h"
#include "SensorManager.h"
#include "UI.h"
#include "WiFi.h"
#include "MenuSystem.h"

#ifndef BTN_DEBUG
#define BTN_DEBUG 1
#endif
#if BTN_DEBUG
  #define BLOG(...)  do { Serial.printf(__VA_ARGS__); } while (0)
#else
  #define BLOG(...)  do {} while (0)
#endif

static const char* evName(ButtonEvent e) {
  switch (e) {
    case BUTTON_NONE:     return "NONE";
    case BUTTON_PRESSED:  return "PRESSED";
    case BUTTON_RELEASED: return "RELEASED";
    case BUTTON_HELD:     return "HELD";
    default: return "?";
  }
}

namespace {
  const LoggerConfig* s_cfg = nullptr;
  bool s_enterHoldFired = false;

  struct Slot {
    ButtonActions::MarkOverrideHandle id;
    std::function<void(ButtonEvent)>  fn;
  };
  static std::vector<Slot> s_overrides;
  static ButtonActions::MarkOverrideHandle s_nextId = 1; // 0 = invalid

  Slot* topOverride() {
    if (s_overrides.empty()) return nullptr;
    return &s_overrides.back();
  }
}

void ButtonActions::begin() {
  const LoggerConfig& cfg = ConfigManager::get();

  Serial.println("[BTN] Initializing buttons with config:");
  Serial.printf("  web=%u log=%u mark=%u\n",   cfg.webBtnPin,  cfg.logBtnPin,  cfg.markBtnPin);
  Serial.printf("  navUp=%u navDown=%u navLeft=%u navRight=%u navEnter=%u\n",
                cfg.navUpPin, cfg.navDownPin, cfg.navLeftPin, cfg.navRightPin, cfg.navEnterPin);

  // Register them now
  ButtonActions::registerButtons();
}

static void touchMenuActivity_() {
  if (MenuSystem::isActive()) {
    // simple nudge so idle timer doesn’t close while user taps keys
    // (we don’t expose a method; just re-open to refresh lastInput)
    MenuSystem::requestOpen();
  }
}

void ButtonActions::registerButtons() {
  const LoggerConfig& cfg = ConfigManager::get();  // fetch live config

  auto safeRegister = [&](uint8_t pin, ButtonMode mode,
                          ButtonCallback cb, const char* name) {
    if (pin == 0 || pin == 0xFF) {
      Serial.printf("[BTN] Skipping %-8s (pin=%u)\n", name, pin);
      return;
    }
    Serial.printf("[BTN] Register  %-8s pin=%u  mode=%s  debounce=%u ms\n",
                  name, pin, (mode == BUTTON_INTERRUPT ? "INT" : "POLL"),
                  (unsigned)cfg.debounceMs);
    ButtonManager_register(pin, mode, cfg.debounceMs, cb);
  };

  // Interrupt-driven buttons
 // safeRegister(cfg.webBtnPin,  BUTTON_INTERRUPT, ButtonActions::onWebServerToggle, "web");
 // safeRegister(cfg.logBtnPin,  BUTTON_INTERRUPT, ButtonActions::onToggleLogging,   "log");
  safeRegister(cfg.markBtnPin, BUTTON_INTERRUPT, ButtonActions::onMarkEvent,       "mark");
  safeRegister(cfg.navEnterPin,BUTTON_INTERRUPT, ButtonActions::onNavEnter,        "enter");

  // Polled nav buttons
  safeRegister(cfg.navUpPin,    BUTTON_POLL, ButtonActions::onNavUp,    "navUp");
  safeRegister(cfg.navDownPin,  BUTTON_POLL, ButtonActions::onNavDown,  "navDown");
  safeRegister(cfg.navLeftPin,  BUTTON_POLL, ButtonActions::onNavLeft,  "navLeft");
  safeRegister(cfg.navRightPin, BUTTON_POLL, ButtonActions::onNavRight, "navRight");
}

void ButtonActions::onToggleLogging(ButtonEvent event) {
  if (event != BUTTON_PRESSED) return;

  if (!LoggingManager::isRunning()) {
    // Block if web server is running
    if (WebServerManager::isRunning()) {
      UI::println("Refusing to start logging while web server is running. Stop server first.",
                  "Turn off WiFi", UI::TARGET_BOTH, UI::LVL_WARN);
      return;
    }
    if (LoggingManager::start()) {
      ButtonManager_setPollingEnabled(false);   // suspend nav polling
      UI::println("Logging started with RTC time.", "", UI::TARGET_SERIAL, UI::LVL_INFO, 2000);
      UI::toast("Log start");
      UI::status("Logging");
    } else {
      UI::println("Failed to start logging.", "", UI::TARGET_SERIAL, UI::LVL_ERROR);
      UI::toast("Log start failed");
    }
  } else {
    LoggingManager::stop();
    ButtonManager_setPollingEnabled(true);   // re-enable nav polling
    UI::println("Logging stopped.", "", UI::TARGET_SERIAL, UI::LVL_INFO, 2000);
    UI::toast("Log stop");
    UI::status("Ready");
  }
}

void ButtonActions::onMarkEvent(ButtonEvent event) {
  // Let the MENU see only PRESSED (avoid double-trigger on RELEASED)
  if (MenuSystem::isActive()) {
    if (event == BUTTON_PRESSED) {
      MenuSystem::onMark();
    }
    return;  // do not fall through to logging, etc.
  }

  // Outside the menu: accept PRESSED or RELEASED as you prefer
  if (event != BUTTON_PRESSED && event != BUTTON_RELEASED) return;

  if (auto* top = topOverride()) {
    auto fn = top->fn; // copy to avoid surprises if it pops itself
    if (fn) fn(event);
    return;
  }

  if (LoggingManager::isRunning()) {
    LoggingManager::mark();
    UI::toast("Marked", 1200);
    UI::println("Record marked.", "", UI::TARGET_SERIAL, UI::LVL_INFO);
  }
}


void ButtonActions::onWebServerToggle(ButtonEvent event) {
  if (event != BUTTON_PRESSED) return;

  if (WebServerManager::isRunning()) {
    WebServerManager::stop();
    UI::println("Web server stopped.", "WiFi off", UI::TARGET_BOTH, UI::LVL_INFO, 2000);
    UI::status("Ready");
    return;
  }

  if (!WebServerManager::canStart()) {
    UI::println("Cannot start server while logging active or SD unavailable.", "Busy Logging", UI::TARGET_BOTH, UI::LVL_WARN);
    return;
  }

  if (WebServerManager::start()) {
    UI::println(String("Web server at ") + WiFi.localIP().toString(), "WiFi on", UI::TARGET_BOTH, UI::LVL_INFO, 2000);        
     
  } else {
    UI::println("Failed to start web server (WiFi or SD issue).", "WiFi fail", UI::TARGET_BOTH, UI::LVL_ERROR);
  }
}

void ButtonActions::onNavUp(ButtonEvent event) {
  BLOG("[BTN] Up %s\n", evName(event));
  if (event != BUTTON_PRESSED) return;
  if (MenuSystem::isActive()) { MenuSystem::navUp(); return; }
  UI::println("Nav Up.", "", UI::TARGET_SERIAL, UI::LVL_INFO);
}

void ButtonActions::onNavDown(ButtonEvent event) {
  BLOG("[BTN] Down %s\n", evName(event));
  if (event != BUTTON_PRESSED) return;
  if (MenuSystem::isActive()) { MenuSystem::navDown(); return; }
  UI::println("Nav Down.", "", UI::TARGET_SERIAL, UI::LVL_INFO);
}

void ButtonActions::onNavLeft(ButtonEvent event) {
  BLOG("[BTN] Left %s\n", evName(event));
  if (event != BUTTON_PRESSED) return;
  if (MenuSystem::isActive()) { MenuSystem::navLeft(); return; }
  UI::println("Nav Left.", "", UI::TARGET_SERIAL, UI::LVL_INFO);
}

void ButtonActions::onNavRight(ButtonEvent event) {
  BLOG("[BTN] Right %s\n", evName(event));
  if (event != BUTTON_PRESSED && event!= BUTTON_RELEASED) return;
  if (MenuSystem::isActive()) { 
      MenuSystem::navRight(); 
      return; 
  } else MenuSystem::requestOpen();

  UI::println("Nav Right.", "", UI::TARGET_SERIAL, UI::LVL_INFO);
}

void ButtonActions::onNavEnter(ButtonEvent event) {
  BLOG("[BTN] Enter %s\n", evName(event));

  if (MenuSystem::isActive()) {
    // When menu is active, Enter only selects
    if (event == BUTTON_RELEASED) {
      MenuSystem::select();
    }
    // (optional) if you want HELD to close the menu:
    // else if (event == BUTTON_HELD) {
    //   MenuSystem::deactivate();
    // }
  } else {
    // When menu is not active, Enter toggles logging on RELEASE
    if (event == BUTTON_RELEASED) {
      ButtonActions::onToggleLogging(BUTTON_PRESSED);
    }
    // You can also reserve HELD for a different function here if desired
  }
}

ButtonActions::MarkOverrideHandle ButtonActions::pushMarkOverride(std::function<void(ButtonEvent)> handler) {
  if (!handler) return 0;
  if (s_overrides.size() > 15) return 0;
  MarkOverrideHandle id = s_nextId++;
  s_overrides.push_back({id, std::move(handler)});
  return id;
}

bool ButtonActions::popMarkOverride(MarkOverrideHandle handle) {
  if (handle == 0 || s_overrides.empty()) return false;
  if (s_overrides.back().id == handle) {
    s_overrides.pop_back();
    return true;
  }
  for (auto it = s_overrides.begin(); it != s_overrides.end(); ++it) {
    if (it->id == handle) { s_overrides.erase(it); return true; }
  }
  return false;
}

bool ButtonActions::hasActiveMarkOverride() {
  return !s_overrides.empty();
}

