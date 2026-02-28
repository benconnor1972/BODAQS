#pragma once
#include <Arduino.h>
#include "DebugLog.h"

// Enable / disable tracing here
#define TRACE_ENABLED 1

#if TRACE_ENABLED
  #define TRACE(msg) LOGD_TAG("TRACE", "%10lu ms %s\n", (unsigned long)millis(), msg)
#else
  #define TRACE(msg) do {} while (0)
#endif
