#pragma once
#include <Arduino.h>

// Compile-time master switch: set to 0 to strip logs at build time
#ifndef LOG_COMPILED
#define LOG_COMPILED 1
#endif

#define BODAQS_LOG_LEVEL_NONE  0
#define BODAQS_LOG_LEVEL_ERROR 1
#define BODAQS_LOG_LEVEL_WARN  2
#define BODAQS_LOG_LEVEL_INFO  3
#define BODAQS_LOG_LEVEL_DEBUG 4
#define BODAQS_LOG_LEVEL_TRACE 5

// Compile-time default verbosity. Override in PlatformIO with:
//   -DBODAQS_LOG_LEVEL=BODAQS_LOG_LEVEL_INFO
#ifndef BODAQS_LOG_LEVEL
#define BODAQS_LOG_LEVEL BODAQS_LOG_LEVEL_DEBUG
#endif

// Levels (keep numbers small; lower = more critical)
enum LogLevel : uint8_t {
  LOG_NONE  = BODAQS_LOG_LEVEL_NONE,
  LOG_ERROR = BODAQS_LOG_LEVEL_ERROR,
  LOG_WARN  = BODAQS_LOG_LEVEL_WARN,
  LOG_INFO  = BODAQS_LOG_LEVEL_INFO,
  LOG_DEBUG = BODAQS_LOG_LEVEL_DEBUG,
  LOG_TRACE = BODAQS_LOG_LEVEL_TRACE,
};

void Log_setEnabled(bool on);           // runtime on/off
bool Log_isEnabled();
void Log_setLevel(LogLevel lvl);        // runtime level
void Log_resetLevel();                  // restore compile-time default
LogLevel Log_getLevel();
LogLevel Log_getDefaultLevel();
bool Log_would(LogLevel lvl);           // check if would log
LogLevel Log_clampLevel(uint8_t lvl);
const char* Log_levelName(LogLevel lvl);
bool Log_parseLevel(const char* text, LogLevel& out);
void Log_printf(LogLevel lvl, const char* fmt, ...);
void Log_println(LogLevel lvl, const char* s);
void Log_taggedPrintf(LogLevel lvl, const char* tag, const char* fmt, ...);
void Log_taggedPrintln(LogLevel lvl, const char* tag, const char* s);

#if LOG_COMPILED && (BODAQS_LOG_LEVEL >= BODAQS_LOG_LEVEL_ERROR)
#define LOGE(...) do { if (Log_would(LOG_ERROR)) Log_printf(LOG_ERROR, __VA_ARGS__); } while (0)
#define LOGE_TAG(tag, ...) do { if (Log_would(LOG_ERROR)) Log_taggedPrintf(LOG_ERROR, tag, __VA_ARGS__); } while (0)
#else
#define LOGE(...) do{}while(0)
#define LOGE_TAG(tag, ...) do{}while(0)
#endif

#if LOG_COMPILED && (BODAQS_LOG_LEVEL >= BODAQS_LOG_LEVEL_WARN)
#define LOGW(...) do { if (Log_would(LOG_WARN)) Log_printf(LOG_WARN, __VA_ARGS__); } while (0)
#define LOGW_TAG(tag, ...) do { if (Log_would(LOG_WARN)) Log_taggedPrintf(LOG_WARN, tag, __VA_ARGS__); } while (0)
#else
#define LOGW(...) do{}while(0)
#define LOGW_TAG(tag, ...) do{}while(0)
#endif

#if LOG_COMPILED && (BODAQS_LOG_LEVEL >= BODAQS_LOG_LEVEL_INFO)
#define LOGI(...) do { if (Log_would(LOG_INFO)) Log_printf(LOG_INFO, __VA_ARGS__); } while (0)
#define LOGI_TAG(tag, ...) do { if (Log_would(LOG_INFO)) Log_taggedPrintf(LOG_INFO, tag, __VA_ARGS__); } while (0)
#else
#define LOGI(...) do{}while(0)
#define LOGI_TAG(tag, ...) do{}while(0)
#endif

#if LOG_COMPILED && (BODAQS_LOG_LEVEL >= BODAQS_LOG_LEVEL_DEBUG)
#define LOGD(...) do { if (Log_would(LOG_DEBUG)) Log_printf(LOG_DEBUG, __VA_ARGS__); } while (0)
#define LOGD_TAG(tag, ...) do { if (Log_would(LOG_DEBUG)) Log_taggedPrintf(LOG_DEBUG, tag, __VA_ARGS__); } while (0)
#else
#define LOGD(...) do{}while(0)
#define LOGD_TAG(tag, ...) do{}while(0)
#endif

#if LOG_COMPILED && (BODAQS_LOG_LEVEL >= BODAQS_LOG_LEVEL_TRACE)
#define LOGT(...) do { if (Log_would(LOG_TRACE)) Log_printf(LOG_TRACE, __VA_ARGS__); } while (0)
#define LOGT_TAG(tag, ...) do { if (Log_would(LOG_TRACE)) Log_taggedPrintf(LOG_TRACE, tag, __VA_ARGS__); } while (0)
#else
#define LOGT(...) do{}while(0)
#define LOGT_TAG(tag, ...) do{}while(0)
#endif
