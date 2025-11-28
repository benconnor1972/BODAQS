#pragma once

#include <stdint.h>
#include "ConfigManager.h"   // for LoggerConfig, MAX_BUTTON_BINDINGS, ButtonBindingDef
#include "ButtonManager.h"   // for ButtonEvent

// Small module that converts (buttonIndex, ButtonEvent) into ButtonActions
// based on the config's buttons[] and buttonBindings[] arrays.
//
// Usage:
//   ButtonBindingTable::initFromConfig(ConfigManager::get());
//   ...
//   // From ButtonManager callback, where "i" is the button's index
//   ButtonBindingTable::handleButtonEvent(i, ev);

namespace ButtonBindingTable {

  // Build the internal binding table from the loaded LoggerConfig.
  void initFromConfig(const LoggerConfig& cfg);

  // Dispatch a button event for a given button index to the appropriate actions.
  void handleButtonEvent(uint8_t buttonIndex, ButtonEvent ev);

} // namespace ButtonBindingTable
