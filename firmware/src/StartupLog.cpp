#include "StartupLog.h"
#include "StartupReportBuffer.h"
#include "StorageManager.h"
#include "RTCManager.h"
#include <Arduino.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>

namespace {
constexpr size_t kBufferBytes = 32768;
constexpr size_t kMessageBytes = 768;
char* s_storage = nullptr;
StartupReportBuffer s_buffer;
bool s_readinessKnown = false;
unsigned s_checked = 0, s_failed = 0;

void message_(bool serial, const char* format, va_list args) {
  if (!serial && !s_storage) return;
  char message[kMessageBytes];
  const int length = vsnprintf(message, sizeof(message), format, args);
  if (length < 0) {
    if (s_storage) s_buffer.drop(0);
    return;
  }
  if (serial) Serial.print(message);
  if (!s_storage) return;
  if (static_cast<size_t>(length) >= sizeof(message)) {
    s_buffer.drop(static_cast<size_t>(length));
  } else {
    s_buffer.append(message, static_cast<size_t>(length));
  }
}
}

bool StartupLog::begin(bool enabled) {
  free(s_storage);
  s_storage = nullptr;
  s_buffer.reset();
  s_readinessKnown = false;
  s_checked = s_failed = 0;
  if (!enabled) return false;
  s_storage = static_cast<char*>(malloc(kBufferBytes));
  if (!s_storage) {
    Serial.println("[STARTUP-REPORT] capture unavailable: RAM allocation failed");
    return false;
  }
  s_buffer.reset(s_storage, kBufferBytes);
  recordf("[STARTUP-REPORT] format=1 buffer_capacity=%u capture_begin_ms=%lu\n",
          (unsigned)kBufferBytes, (unsigned long)millis());
  return true;
}

bool StartupLog::active() { return s_storage != nullptr; }

void StartupLog::recordf(const char* format, ...) {
  va_list args;
  va_start(args, format);
  message_(false, format, args);
  va_end(args);
}

void StartupLog::printf(const char* format, ...) {
  va_list args;
  va_start(args, format);
  message_(true, format, args);
  va_end(args);
}

void StartupLog::println(const char* text) { printf("%s\n", text); }

void StartupLog::setFinalReadiness(unsigned checked, unsigned failed) {
  if (!active()) return;
  s_readinessKnown = true;
  s_checked = checked;
  s_failed = failed;
}

void StartupLog::finish() {
  if (!s_storage) return;
  char footer[StartupReportBuffer::kFooterReserve];
  snprintf(footer, sizeof(footer),
           "\n[STARTUP-REPORT] END capture_overflow=%u dropped_messages=%llu dropped_bytes=%llu completion_ms=%lu rtc_valid=%u epoch_ms=%llu readiness_known=%u final_i2c_checked=%u final_i2c_failed=%u\n",
           s_buffer.droppedMessages() ? 1u : 0u,
           (unsigned long long)s_buffer.droppedMessages(),
           (unsigned long long)s_buffer.droppedBytes(),
           (unsigned long)millis(), RTCManager_hasValidTime() ? 1u : 0u,
           (unsigned long long)RTCManager_getEpochMs(), s_readinessKnown ? 1u : 0u,
           s_checked, s_failed);
  s_buffer.footer(footer);
  // Disable capture before any storage/status operation, then release RAM on
  // every outcome. No startup report is written from the sampling loop.
  char* storage = s_storage;
  s_storage = nullptr;
  char path[64] = {};
  const bool saved = StorageManager_saveStartupReport(storage, path, sizeof(path));
  Serial.printf("[STARTUP-REPORT] %s%s%s\n", saved ? "saved " : "save failed",
                saved ? path : "", saved ? " (latest 32 reports retained)" : "");
  free(storage);
  s_buffer.reset();
}
