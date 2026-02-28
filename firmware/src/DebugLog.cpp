#include "DebugLog.h"
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>

#if BODAQS_LOG_LEVEL < BODAQS_LOG_LEVEL_NONE
static constexpr uint8_t kDefaultLevelRaw_ = BODAQS_LOG_LEVEL_NONE;
#elif BODAQS_LOG_LEVEL > BODAQS_LOG_LEVEL_TRACE
static constexpr uint8_t kDefaultLevelRaw_ = BODAQS_LOG_LEVEL_TRACE;
#else
static constexpr uint8_t kDefaultLevelRaw_ = BODAQS_LOG_LEVEL;
#endif

static bool     s_enabled = true;
static LogLevel s_level   = static_cast<LogLevel>(kDefaultLevelRaw_);

static bool equalsIgnoreCase_(const char* a, const char* b) {
  if (a == b) return true;
  if (!a || !b) return false;
  while (*a && *b) {
    const char ca = (char)tolower((unsigned char)*a++);
    const char cb = (char)tolower((unsigned char)*b++);
    if (ca != cb) return false;
  }
  return (*a == '\0' && *b == '\0');
}

static void copyTrimmed_(const char* src, char* dst, size_t cap) {
  if (!dst || cap == 0) return;
  dst[0] = '\0';
  if (!src) return;

  while (*src && isspace((unsigned char)*src)) ++src;

  size_t len = strlen(src);
  while (len > 0 && isspace((unsigned char)src[len - 1])) --len;
  if (len >= cap) len = cap - 1;

  memcpy(dst, src, len);
  dst[len] = '\0';
}

static void printTag_(const char* tag) {
  if (!tag || !*tag) return;
  Serial.print('[');
  Serial.print(tag);
  Serial.print("] ");
}

void Log_setEnabled(bool on)      { s_enabled = on; }
bool Log_isEnabled()              { return s_enabled; }
void Log_setLevel(LogLevel lvl)   { s_level = Log_clampLevel((uint8_t)lvl); }
void Log_resetLevel()             { s_level = Log_getDefaultLevel(); }
LogLevel Log_getLevel()           { return s_level; }
LogLevel Log_getDefaultLevel()    { return static_cast<LogLevel>(kDefaultLevelRaw_); }

bool Log_would(LogLevel lvl) {
#if LOG_COMPILED
  return s_enabled && (lvl <= s_level);
#else
  (void)lvl;
  return false;
#endif
}

LogLevel Log_clampLevel(uint8_t lvl) {
  if (lvl > LOG_TRACE) return LOG_TRACE;
  return static_cast<LogLevel>(lvl);
}

const char* Log_levelName(LogLevel lvl) {
  switch (lvl) {
    case LOG_NONE:  return "none";
    case LOG_ERROR: return "error";
    case LOG_WARN:  return "warn";
    case LOG_INFO:  return "info";
    case LOG_DEBUG: return "debug";
    case LOG_TRACE: return "trace";
    default:        return "unknown";
  }
}

bool Log_parseLevel(const char* text, LogLevel& out) {
  char buf[16];
  copyTrimmed_(text, buf, sizeof(buf));
  if (!buf[0]) return false;

  char* end = nullptr;
  long value = strtol(buf, &end, 10);
  if (end && *end == '\0') {
    if (value < LOG_NONE || value > LOG_TRACE) return false;
    out = static_cast<LogLevel>(value);
    return true;
  }

  if (equalsIgnoreCase_(buf, "none"))    { out = LOG_NONE;  return true; }
  if (equalsIgnoreCase_(buf, "error"))   { out = LOG_ERROR; return true; }
  if (equalsIgnoreCase_(buf, "warn") ||
      equalsIgnoreCase_(buf, "warning")) { out = LOG_WARN;  return true; }
  if (equalsIgnoreCase_(buf, "info"))    { out = LOG_INFO;  return true; }
  if (equalsIgnoreCase_(buf, "debug"))   { out = LOG_DEBUG; return true; }
  if (equalsIgnoreCase_(buf, "trace"))   { out = LOG_TRACE; return true; }
  return false;
}

static void vprintToSerial_(const char* fmt, va_list ap) {
  char buf[256];
  vsnprintf(buf, sizeof(buf), fmt, ap);
  Serial.print(buf);
}

void Log_printf(LogLevel lvl, const char* fmt, ...) {
#if LOG_COMPILED
  if (!Log_would(lvl) || !fmt) return;
  va_list ap; va_start(ap, fmt);
  vprintToSerial_(fmt, ap);
  va_end(ap);
#else
  (void)lvl;
  (void)fmt;
#endif
}

void Log_println(LogLevel lvl, const char* s) {
#if LOG_COMPILED
  if (!Log_would(lvl)) return;
  Serial.println(s ? s : "");
#else
  (void)lvl;
  (void)s;
#endif
}

void Log_taggedPrintf(LogLevel lvl, const char* tag, const char* fmt, ...) {
#if LOG_COMPILED
  if (!Log_would(lvl) || !fmt) return;
  printTag_(tag);
  va_list ap; va_start(ap, fmt);
  vprintToSerial_(fmt, ap);
  va_end(ap);
#else
  (void)lvl;
  (void)tag;
  (void)fmt;
#endif
}

void Log_taggedPrintln(LogLevel lvl, const char* tag, const char* s) {
#if LOG_COMPILED
  if (!Log_would(lvl)) return;
  printTag_(tag);
  Serial.println(s ? s : "");
#else
  (void)lvl;
  (void)tag;
  (void)s;
#endif
}
