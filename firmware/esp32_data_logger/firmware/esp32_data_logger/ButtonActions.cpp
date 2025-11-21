#include "ButtonActions.h"
#include "LoggingManager.h"
#include "WebServerManager.h"
#include "StorageManager.h"
#include "SensorManager.h"
#include "UI.h"
#include "WiFi.h"
#include "MenuSystem.h"
#include "ButtonBindingTable.h"
#include "ConfigManager.h"
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
    case BUTTON_NONE:        return "NONE";
    case BUTTON_PRESSED:     return "PRESSED";
    case BUTTON_RELEASED:    return "RELEASED";
    case BUTTON_HELD:        return "HELD";
    case BUTTON_CLICK:       return "CLICK";
    case BUTTON_DOUBLE_CLICK:return "DOUBLE_CLICK";
    default:                 return "?";
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

    // === Runtime binding table: (button index, event) -> ActionId ===

  struct RuntimeBinding {
    uint8_t     buttonIndex;   // index into cfg.buttons[]
    ButtonEvent event;
    ButtonActions::ActionId action;
  };

  static RuntimeBinding s_bindings[MAX_BUTTON_BINDINGS];
  static uint8_t        s_bindingCount = 0;

  // Map config string -> ButtonEvent
  ButtonEvent parseEvent_(const char* s) {
    if (!s || !*s) return BUTTON_NONE;
    String t = String(s);
    t.trim();
    t.toLowerCase();
    if (t == "pressed")       return BUTTON_PRESSED;
    if (t == "released")      return BUTTON_RELEASED;
    if (t == "click")         return BUTTON_CLICK;
    if (t == "double_click")  return BUTTON_DOUBLE_CLICK;
    if (t == "held" || t == "long" || t == "long_press") return BUTTON_HELD;
    return BUTTON_NONE;
  }

  // Map config string -> ActionId
  ButtonActions::ActionId parseAction_(const char* s) {
    using namespace ButtonActions;
    if (!s || !*s) return ACT_NONE;
    String t = String(s);
    t.trim();
    t.toLowerCase();

    if (t == "logging_toggle")  return ACT_LOGGING_TOGGLE;
    if (t == "mark_event")      return ACT_MARK_EVENT;
    if (t == "web_toggle")      return ACT_WEB_TOGGLE;

    if (t == "menu_nav_up")     return ACT_MENU_NAV_UP;
    if (t == "menu_nav_down")   return ACT_MENU_NAV_DOWN;
    if (t == "menu_nav_left")   return ACT_MENU_NAV_LEFT;
    if (t == "menu_nav_right")  return ACT_MENU_NAV_RIGHT;
    if (t == "menu_nav_enter")  return ACT_MENU_NAV_ENTER;

    return ACT_NONE;
  }

  void initBindingsFromConfig_(const LoggerConfig& cfg) {
    s_bindingCount = 0;

    auto findButtonIndex = [&](const char* id) -> int {
      if (!id || !*id) return -1;
      for (uint8_t i = 0; i < cfg.buttonCount; ++i) {
        if (!strcasecmp(cfg.buttons[i].id, id)) return (int)i;
      }
      return -1;
    };

    for (uint8_t i = 0; i < cfg.buttonBindingCount; ++i) {
      const auto& bd = cfg.buttonBindings[i];
      if (!bd.buttonId[0] || !bd.event[0] || !bd.action[0]) continue;

      int        bIdx = findButtonIndex(bd.buttonId);
      ButtonEvent ev  = parseEvent_(bd.event);
      auto       act  = parseAction_(bd.action);

      if (bIdx < 0 || ev == BUTTON_NONE || act == ButtonActions::ACT_NONE) continue;
      if (s_bindingCount >= MAX_BUTTON_BINDINGS) break;

      auto& r      = s_bindings[s_bindingCount++];
      r.buttonIndex = (uint8_t)bIdx;
      r.event       = ev;
      r.action      = act;
    }

    Serial.printf("[BTN] Loaded %u button bindings from config\n", (unsigned)s_bindingCount);
  }

  // Dispatch from (buttonIndex, event) -> one or more actions
  void handleButtonBinding_(uint8_t buttonIndex, ButtonEvent ev) {
    for (uint8_t i = 0; i < s_bindingCount; ++i) {
      const auto& r = s_bindings[i];
      if (r.buttonIndex == buttonIndex && r.event == ev) {
        ButtonActions::invoke(r.action, ev);
      }
    }
  }

  // ======== Per-button callbacks for ButtonManager ========
  // We encode the button index in which static function we register.

  void btnCb0(ButtonEvent ev) { handleButtonBinding_(0, ev); }
  void btnCb1(ButtonEvent ev) { handleButtonBinding_(1, ev); }
  void btnCb2(ButtonEvent ev) { handleButtonBinding_(2, ev); }
  void btnCb3(ButtonEvent ev) { handleButtonBinding_(3, ev); }
  void btnCb4(ButtonEvent ev) { handleButtonBinding_(4, ev); }
  void btnCb5(ButtonEvent ev) { handleButtonBinding_(5, ev); }
  void btnCb6(ButtonEvent ev) { handleButtonBinding_(6, ev); }
  void btnCb7(ButtonEvent ev) { handleButtonBinding_(7, ev); }
  void btnCb8(ButtonEvent ev) { handleButtonBinding_(8, ev); }
  void btnCb9(ButtonEvent ev) { handleButtonBinding_(9, ev); }

  static ButtonCallback s_buttonCallbacks[MAX_BUTTONS] = {
    btnCb0, btnCb1, btnCb2, btnCb3, btnCb4,
    btnCb5, btnCb6, btnCb7, btnCb8, btnCb9
  };
}

void ButtonActions::begin() {
  const LoggerConfig& cfg = ConfigManager::get();

  Serial.println("[BTN] Initializing buttons from config:");
  Serial.printf("  buttonCount=%u bindingCount=%u debounce=%u ms\n",
                (unsigned)cfg.buttonCount,
                (unsigned)cfg.buttonBindingCount,
                (unsigned)cfg.debounceMs);

  initBindingsFromConfig_(cfg);
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
  const LoggerConfig& cfg = ConfigManager::get();

  for (uint8_t i = 0; i < cfg.buttonCount && i < MAX_BUTTONS; ++i) {
    const ButtonDef& b = cfg.buttons[i];

    if (b.pin == 0 || b.pin == 0xFF) {
      Serial.printf("[BTN] Skipping '%s' (pin=%u)\n",
                    b.id, (unsigned)b.pin);
      continue;
    }

    ButtonMode mode = (b.mode == 1) ? BUTTON_POLL : BUTTON_INTERRUPT;
    ButtonCallback cb = s_buttonCallbacks[i];

    Serial.printf("[BTN] Register %-12s idx=%u pin=%u mode=%s debounce=%u ms\n",
                  b.id,
                  (unsigned)i,
                  (unsigned)b.pin,
                  (mode == BUTTON_INTERRUPT ? "INT" : "POLL"),
                  (unsigned)cfg.debounceMs);

    ButtonManager_register(b.pin, mode, cfg.debounceMs, cb);
  }
}


void ButtonActions::invoke(ActionId action, ButtonEvent ev) {
  switch (action) {
    case ACT_LOGGING_TOGGLE:
      onToggleLogging(ev);
      return;

    case ACT_MARK_EVENT:
      onMarkEvent(ev);
      return;

    case ACT_WEB_TOGGLE:
      onWebServerToggle(ev);
      return;

    case ACT_MENU_NAV_UP:
      onNavUp(ev);
      return;

    case ACT_MENU_NAV_DOWN:
      onNavDown(ev);
      return;

    case ACT_MENU_NAV_LEFT:
      onNavLeft(ev);
      return;

    case ACT_MENU_NAV_RIGHT:
      onNavRight(ev);
      return;

    case ACT_MENU_NAV_ENTER:
      onNavEnter(ev);
      return;

    case ACT_NONE:
    default:
      return;
  }
}

void ButtonActions::onToggleLogging(ButtonEvent event) {

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
  //if (event != BUTTON_PRESSED) return;

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

