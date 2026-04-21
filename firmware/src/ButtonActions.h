#pragma once
#include <functional>
#include <stdint.h>

#include "ButtonManager.h"
#include "ConfigManager.h"

namespace ButtonActions {

  // ===========================================================================
  // Lifecycle
  // ===========================================================================
  // Provide config so we can read pins/debounce and register handlers
  void begin();
  void registerButtons();
  void reloadBindingsFromConfig(const LoggerConfig& cfg);

  // ===========================================================================
  // Normal (default) handlers — matching ButtonManager callback signature
  // ===========================================================================
  void onToggleLogging(ButtonEvent event);
  void onMarkEvent(ButtonEvent event);
  void onWebServerToggle(ButtonEvent event);
  void onNavUp(ButtonEvent event);
  void onNavDown(ButtonEvent event);
  void onNavLeft(ButtonEvent event);
  void onNavRight(ButtonEvent event);
  void onNavEnter(ButtonEvent event);
  void onSleep(ButtonEvent event);

  // ===========================================================================
  // Mark-button Override API (for wizards like Calibration)
  // ---------------------------------------------------------------------------
  // Use pushMarkOverride() to temporarily replace the default Mark behavior
  // with your own handler (e.g., the calibration wizard's onMark()).
  //
  // Multiple overrides are supported (stack/LIFO). The most recently pushed
  // handler receives Mark events until it is popped.
  //
  // Typical usage:
  //   auto h = ButtonActions::pushMarkOverride(
  //               [](ButtonEvent ev){ if (ev == ButtonEvent::ShortPress) wizard.onMark(); });
  //   ...
  //   ButtonActions::popMarkOverride(h);
  // ===========================================================================

  // Opaque handle for an installed override.
  using MarkOverrideHandle = uint8_t;

  // Install a temporary handler for the Mark button.
  // Returns a handle (>0) on success; 0 indicates failure (e.g., table full).
  MarkOverrideHandle pushMarkOverride(std::function<void(ButtonEvent)> handler);

  // Remove a previously installed override. Returns true on success.
  // Safe to call with an invalid/expired handle (returns false).
  bool popMarkOverride(MarkOverrideHandle handle);

  // Returns true iff there is at least one active Mark override.
  bool hasActiveMarkOverride();
  // High-level button actions (targets for config bindings)
  
  enum ActionId : uint8_t {
    ACT_NONE = 0,

    ACT_LOGGING_TOGGLE,
    ACT_MARK_EVENT,
    ACT_WEB_TOGGLE,

    ACT_MENU_NAV_UP,
    ACT_MENU_NAV_DOWN,
    ACT_MENU_NAV_LEFT,
    ACT_MENU_NAV_RIGHT,
    ACT_MENU_NAV_ENTER,
    ACT_MENU_SELECT,
    ACT_SLEEP,
  };

  // Central dispatcher used by the binding table
  void invoke(ActionId action, ButtonEvent ev);


} // namespace ButtonActions
