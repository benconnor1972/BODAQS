#pragma once
#include <Arduino.h>

// Compile-time master switch: set to 0 to strip logs at build time
#ifndef LOG_COMPILED
#define LOG_COMPILED 1
#endif

// Levels (keep numbers small; lower = more critical)
enum LogLevel : uint8_t {
  LOG_NONE  = 0,
  LOG_ERROR = 1,
  LOG_WARN  = 2,
  LOG_INFO  = 3,
  LOG_DEBUG = 4,
  LOG_TRACE = 5,
};

#if LOG_COMPILED

void Log_setEnabled(bool on);           // runtime on/off
void Log_setLevel(LogLevel lvl);        // runtime level
bool Log_would(LogLevel lvl);           // check if would log
void Log_printf(LogLevel lvl, const char* fmt, ...);
void Log_println(LogLevel lvl, const char* s);

#define LOGE(...) Log_printf(LOG_ERROR, __VA_ARGS__)
#define LOGW(...) Log_printf(LOG_WARN,  __VA_ARGS__)
#define LOGI(...) Log_printf(LOG_INFO,  __VA_ARGS__)
#define LOGD(...) Log_printf(LOG_DEBUG, __VA_ARGS__)
#define LOGT(...) Log_printf(LOG_TRACE, __VA_ARGS__)

#else  // LOG_COMPILED == 0 -> strip logs

inline void Log_setEnabled(bool) {}
inline void Log_setLevel(LogLevel) {}
inline bool Log_would(LogLevel) { return false; }
inline void Log_printf(LogLevel, const char*, ...) {}
inline void Log_println(LogLevel, const char*) {}

#define LOGE(...) do{}while(0)
#define LOGW(...) do{}while(0)
#define LOGI(...) do{}while(0)
#define LOGD(...) do{}while(0)
#define LOGT(...) do{}while(0)

#endif
