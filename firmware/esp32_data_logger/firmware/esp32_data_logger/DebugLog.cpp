#include "DebugLog.h"
#include <stdarg.h>

static bool     s_enabled = true;
static LogLevel s_level   = LOG_INFO;

void Log_setEnabled(bool on)      { s_enabled = on; }
void Log_setLevel(LogLevel lvl)   { s_level   = lvl; }
bool Log_would(LogLevel lvl)      { return s_enabled && (lvl <= s_level); }

static void vprintToSerial_(const char* fmt, va_list ap) {
  char buf[256];
  vsnprintf(buf, sizeof(buf), fmt, ap);
  Serial.print(buf);
}

void Log_printf(LogLevel lvl, const char* fmt, ...) {
  if (!Log_would(lvl) || !fmt) return;
  va_list ap; va_start(ap, fmt);
  vprintToSerial_(fmt, ap);
  va_end(ap);
}

void Log_println(LogLevel lvl, const char* s) {
  if (!Log_would(lvl)) return;
  Serial.println(s ? s : "");
}
