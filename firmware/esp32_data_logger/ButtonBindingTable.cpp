#include "ButtonBindingTable.h"
#include "ButtonActions.h"
#include <string.h>
#include <Arduino.h>   // for Serial (optional; remove if you don't want logging)
#include "BoardProfile.h"
#include "BoardSelect.h"    // declares board::gBoard

using ButtonActions::ActionId;

namespace {

  // One resolved mapping: (button index, event) -> action enum
  struct RuntimeBinding {
    uint8_t     buttonIndex;   // index into cfg.buttons[]
    ButtonEvent event;
    ActionId    action;
  };

  RuntimeBinding s_bindings[MAX_BUTTON_BINDINGS];
  uint8_t        s_bindingCount = 0;

  // ---- String helpers ----

  // Case-insensitive string equal
  bool equalsIgnoreCase_(const char* a, const char* b) {
    if (!a || !b) return false;
    return strcasecmp(a, b) == 0;
  }

  // Map config "event" string -> ButtonEvent
  ButtonEvent parseEvent_(const char* s) {
    if (!s || !*s) return BUTTON_NONE;

    // Normalize via Arduino String for convenience
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

  // Map config "action" string -> ButtonActions::ActionId
  ActionId parseAction_(const char* s) {
    if (!s || !*s) return ButtonActions::ACT_NONE;

    String t = String(s);
    t.trim();
    t.toLowerCase();

    // Core logger actions
    if (t == "logging_toggle")  return ButtonActions::ACT_LOGGING_TOGGLE;
    if (t == "mark_event")      return ButtonActions::ACT_MARK_EVENT;
    if (t == "web_toggle")      return ButtonActions::ACT_WEB_TOGGLE;

    // Menu navigation
    if (t == "menu_nav_up")     return ButtonActions::ACT_MENU_NAV_UP;
    if (t == "menu_nav_down")   return ButtonActions::ACT_MENU_NAV_DOWN;
    if (t == "menu_nav_left")   return ButtonActions::ACT_MENU_NAV_LEFT;
    if (t == "menu_nav_right")  return ButtonActions::ACT_MENU_NAV_RIGHT;
    if (t == "menu_nav_enter")  return ButtonActions::ACT_MENU_NAV_ENTER;

    // Unknown action id
    return ButtonActions::ACT_NONE;
  }

} // anonymous namespace

// ---------------------------------------------------------
// Public API
// ---------------------------------------------------------

void ButtonBindingTable::initFromConfig(const LoggerConfig& cfg) {
  s_bindingCount = 0;

  // Helper: find button index by id (config string)
  auto findButtonIndex = [&](const char* id) -> int {
    if (!id || !*id) return -1;
    if (!board::gBoard) return -1;

    const auto& bp = *board::gBoard;
    const uint8_t n =
        (bp.buttons.count < board::BOARD_MAX_BUTTONS)
          ? bp.buttons.count
          : board::BOARD_MAX_BUTTONS;

    for (uint8_t i = 0; i < n; ++i) {
      const auto& b = bp.buttons.btn[i];
      if (!b.present) continue;

      if (equalsIgnoreCase_(b.id, id)) {
        return (int)i;   // index into board buttons
      }
    }
    return -1;
  };


  for (uint8_t i = 0; i < cfg.buttonBindingCount; ++i) {
    const ButtonBindingDef& bd = cfg.buttonBindings[i];

    if (!bd.buttonId[0] || !bd.event[0] || !bd.action[0]) {
      // Incomplete binding, skip
      continue;
    }

    int        bIdx = findButtonIndex(bd.buttonId);
    ButtonEvent ev  = parseEvent_(bd.event);
    ActionId    act = parseAction_(bd.action);

    if (bIdx < 0 || ev == BUTTON_NONE || act == ButtonActions::ACT_NONE) {
      // Unknown button id or event/action; skip
      continue;
    }

    if (s_bindingCount >= MAX_BUTTON_BINDINGS) {
      Serial.println(F("[BTN] Binding table full; extra bindings skipped."));
      break;
    }

    RuntimeBinding& r = s_bindings[s_bindingCount++];
    r.buttonIndex = (uint8_t)bIdx;
    r.event       = ev;
    r.action      = act;
  }

  Serial.printf("[BTN] ButtonBindingTable: %u binding(s) loaded\n",
                (unsigned)s_bindingCount);
}

void ButtonBindingTable::handleButtonEvent(uint8_t buttonIndex, ButtonEvent ev) {
  if (ev == BUTTON_NONE) return;

  for (uint8_t i = 0; i < s_bindingCount; ++i) {
    const RuntimeBinding& r = s_bindings[i];
    if (r.buttonIndex == buttonIndex && r.event == ev) {
      ButtonActions::invoke(r.action, ev);
    }
  }
}
