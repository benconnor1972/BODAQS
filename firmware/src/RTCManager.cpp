#include "RTCManager.h"
#include <WiFi.h>
#include <time.h>
#include <stdlib.h>  // for getenv (only needed if you keep the TZ print)
#include <sys/time.h>  // settimeofday


// For external RTC (stub now, add DS3231 later)
#include <Wire.h>
// #include <RTClib.h>   // Example if you choose Adafruit RTClib

// static RTC_DS3231 externalRTC;  // Uncomment if using DS3231 + RTClib

// --- Internal state ---
static RTCSource currentSource = RTC_INTERNAL;
static unsigned long baseMillis = 0;
static time_t baseEpoch = 0;
static unsigned long lastSyncMs = 0;
static bool useHumanReadableTimestamps = false;

bool RTCManager_hasValidTime() {
  struct tm tmnow;
  // Non-blocking probe; if SNTP/RTC is ready, this will succeed quickly.
  if (!getLocalTime(&tmnow, 0)) return false;
  // Heuristic: reject the 1970 epoch or obviously bogus years
  return (tmnow.tm_year + 1900) >= 2020;
}

bool RTCManager_waitForSNTP(uint32_t timeout_ms) {
  const uint32_t deadline = millis() + timeout_ms;
  // Consider anything >= 2020-01-01 as "valid"
  const time_t sane = 1577836800;  
  time_t now = 0;

  while ((int32_t)(millis() - deadline) < 0) {
    time(&now);
    if (now >= sane) return true;   // SNTP has set the system clock
    delay(200);

    static uint32_t nextLog = 0;
    if ((int32_t)(millis() - nextLog) >= 0) {
      nextLog = millis() + 1000;
      Serial.printf("[RTC] Waiting SNTP… WiFi OK, RSSI %d\n", WiFi.RSSI());
    }
  }
  Serial.println("[RTC] NTP: timeout waiting for SNTP.");
  return false;
}


// --- Setup RTC ---
void RTCManager_begin(RTCSource source) {
  currentSource = source;

  if (currentSource == RTC_EXTERNAL) {
    Wire.begin();
    // externalRTC.begin(); // Uncomment for DS3231
    // if (!externalRTC.isrunning()) {
    //     Serial.println("RTC not running, setting to compile time.");
    //     externalRTC.adjust(DateTime(F(__DATE__), F(__TIME__)));
    // }
  } else {
    // Internal RTC (ESP32 system time)
    configTzTime("AWST-8", "pool.ntp.org", "time.nist.gov");
  }
  RTCManager_sync();
}

// --- Periodic sync (every second) ---
void RTCManager_loop() {
    // No op as this is implicated in time stamp funnies
    //if (millis() - lastSyncMs >= 1000) {
    //    RTCManager_sync();
    //    lastSyncMs = millis();
    //}
}

// --- Manual sync ---
void RTCManager_sync() {
  time_t now = 0;

  if (currentSource == RTC_EXTERNAL) {
      // Replace with DS3231 call:
      // DateTime dt = externalRTC.now();
      // now = dt.unixtime();
      now = baseEpoch + ((millis() - baseMillis) / 1000); // Stub fallback
  } else {
      time(&now);
      // Don't update if system time is obviously invalid (pre-2020)
      if (now < 1577836800) { // 2020-01-01
          return;             // keep previous baseEpoch/baseMillis
      }
  }

  baseMillis = millis();
  baseEpoch = now;

}

uint64_t RTCManager_getEpochMs() {
    // baseEpoch is seconds; baseMillis captured at last sync
    unsigned long elapsedMs = millis() - baseMillis;     // full ms since sync
    return (uint64_t)baseEpoch * 1000ULL + (uint64_t)elapsedMs;
}

// --- Fast timestamp string ---
String RTCManager_getFastTimestamp() {

    uint64_t epochMs = RTCManager_getEpochMs();

    if (!useHumanReadableTimestamps) {
        // IMPORTANT: String(uint64_t) can be flaky — format explicitly:
        char buf[24];
        snprintf(buf, sizeof(buf), "%llu", (unsigned long long)epochMs);
        return String(buf);
    }

    // Convert to human-readable with ms
    time_t sec = (time_t)(epochMs / 1000ULL);
    struct tm tm;
    localtime_r(&sec, &tm);
    unsigned ms = (unsigned)(epochMs % 1000ULL);

    char buf[32];
    snprintf(buf, sizeof(buf), "%04d-%02d-%02d %02d:%02d:%02d.%03u",
             tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday,
             tm.tm_hour, tm.tm_min, tm.tm_sec, ms);
    return String(buf);
}

bool RTCManager_isHumanReadable() {
    return useHumanReadableTimestamps;
}

void RTCManager_setHumanReadable(bool humanReadable) {
    useHumanReadableTimestamps = humanReadable;
}

String RTCManager_getTimestamp() {
    uint64_t ms = RTCManager_getEpochMs();
    time_t sec = (time_t)(ms / 1000ULL);
    struct tm tm;
    localtime_r(&sec, &tm);
    char buf[32];
    snprintf(buf, sizeof(buf), "%04d-%02d-%02d %02d:%02d:%02d.%03u",
             tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday,
             tm.tm_hour, tm.tm_min, tm.tm_sec, (unsigned)(ms % 1000ULL));
    return String(buf);
}


// --- Raw epoch ---
time_t RTCManager_getEpoch() {
    unsigned long elapsedMs = millis() - baseMillis;
    return baseEpoch + (elapsedMs / 1000);
}

// Get low resolution time stamp for file naming
String RTCManager_getDateTimeString() {
    // Use whatever RTC is active (internal or external)
    struct tm timeinfo;
    if (!getLocalTime(&timeinfo)) {
        return "1970-01-01_00-00-00";
    }

    char buf[32];
    // Format as YYYY-MM-DD_HH-MM-SS (safe for filenames)
    strftime(buf, sizeof(buf), "%Y-%m-%d_%H-%M-%S", &timeinfo);
    return String(buf);
}

void RTCManager_invalidateInternalTime() {
  // Set system time to epoch 0 so RTCManager_hasValidTime() becomes false
  // (your validity check is based on year >= 2020).
  struct timeval tv;
  tv.tv_sec  = 0;
  tv.tv_usec = 0;
  settimeofday(&tv, nullptr);

  // Reset cached base so helpers don't continue from a "valid" cached base.
  baseMillis = millis();
  baseEpoch  = 0;
  lastSyncMs = 0;

  Serial.println("[RTC] Internal time invalidated (epoch=0). Next boot should require SNTP.");
}

