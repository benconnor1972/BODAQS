#pragma once

#include <Arduino.h>

// Optional legacy activity callback; full recording/storage ownership is also
// checked by the manager, including preparation and unfinished finalization.
typedef bool (*UploadModeLoggingActiveFn)();

namespace UploadModeManager {

  void begin(UploadModeLoggingActiveFn isLoggingFn = nullptr);
  void loop();
  bool isActive();
  bool canEnter();
  bool enter();
  void exit();
  bool toggle();
  const char* stateLabel();
  bool usbEnabled();
  bool exitPending();
  bool cancelExit();
  bool retryStorage();
  uint8_t usbPhase();
  const char* usbStateKey();
  const char* transferLabel();
  const char* shortTransferLabel();

} // namespace UploadModeManager
