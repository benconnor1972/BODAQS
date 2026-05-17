#pragma once

#include <Arduino.h>

typedef bool (*UploadModeLoggingActiveFn)();

namespace UploadModeManager {

  void begin(UploadModeLoggingActiveFn isLoggingFn = nullptr);
  bool isActive();
  bool canEnter();
  bool enter();
  void exit();
  bool toggle();
  const char* stateLabel();

} // namespace UploadModeManager
