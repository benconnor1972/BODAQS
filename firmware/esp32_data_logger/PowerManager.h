#pragma once
#include <stdint.h>

namespace PowerManager {
  // Sleep; wake when ENTER (GPIO13) is pressed (active-LOW -> wake level 0).
  void sleepOnEnterEXT0();

  void setCpuFreqForLogging();

  void restoreCpuFreqAfterLogging();
}
