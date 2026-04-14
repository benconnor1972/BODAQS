#include "RTCManager.h"
#include <WiFi.h>
#include <time.h>
#include <stdlib.h>  // for getenv (only needed if you keep the TZ print)
#include <sys/time.h>  // settimeofday
#include <esp_sntp.h>
#include <HTTPClient.h>
#include "I2CManager.h"
#include "DebugLog.h"

#define RTC_LOGE(...) LOGE_TAG("RTC", __VA_ARGS__)
#define RTC_LOGW(...) LOGW_TAG("RTC", __VA_ARGS__)
#define RTC_LOGI(...) LOGI_TAG("RTC", __VA_ARGS__)
#define RTC_LOGD(...) LOGD_TAG("RTC", __VA_ARGS__)

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
static TwoWire* s_externalRtcWire = nullptr;
static constexpr size_t kMaxSntpServerNameLen_ = 128;
static char s_sntpServerNames_[3][kMaxSntpServerNameLen_] = {{0}, {0}, {0}};
static const char* kBuiltinHttpTimeUrls_[] = {
  "http://connectivitycheck.gstatic.com/generate_204",
  "https://gettimeapi.dev/v1/time?timezone=UTC",
};

static void splitCsv3_(const char* csv, String& s1, String& s2, String& s3) {
  s1 = "";
  s2 = "";
  s3 = "";
  if (!csv) return;

  String src(csv);
  src.trim();
  if (!src.length()) return;

  int p1 = src.indexOf(',');
  if (p1 < 0) {
    s1 = src;
    s1.trim();
    return;
  }

  s1 = src.substring(0, p1);
  s1.trim();

  int p2 = src.indexOf(',', p1 + 1);
  if (p2 < 0) {
    s2 = src.substring(p1 + 1);
    s2.trim();
    return;
  }

  s2 = src.substring(p1 + 1, p2);
  s2.trim();
  s3 = src.substring(p2 + 1);
  s3.trim();
}

static const char* sntpStatusName_(sntp_sync_status_t status) {
  switch (status) {
    case SNTP_SYNC_STATUS_RESET:       return "RESET";
    case SNTP_SYNC_STATUS_COMPLETED:   return "COMPLETED";
    case SNTP_SYNC_STATUS_IN_PROGRESS: return "IN_PROGRESS";
    default:                           return "?";
  }
}

static const char* sntpModeName_(sntp_sync_mode_t mode) {
  switch (mode) {
    case SNTP_SYNC_MODE_IMMED:  return "IMMED";
    case SNTP_SYNC_MODE_SMOOTH: return "SMOOTH";
    default:                    return "?";
  }
}

static void sntpTimeSyncNotification_(struct timeval* tv) {
  if (!tv) {
    RTC_LOGI("SNTP callback: time sync notification with null timeval\n");
    return;
  }

  RTC_LOGI("SNTP callback: tv_sec=%lld tv_usec=%ld\n",
           (long long)tv->tv_sec,
           (long)tv->tv_usec);
}

static bool isSpace_(char c) {
  return c == ' ' || c == '\t' || c == '\r' || c == '\n';
}

static bool parseLeadingEpoch_(const String& body, time_t& epochOut) {
  const char* p = body.c_str();
  while (*p && isSpace_(*p)) ++p;
  if (!*p) return false;

  char* end = nullptr;
  long long v = strtoll(p, &end, 10);
  if (end == p) return false;
  while (*end && isSpace_(*end)) ++end;
  if (*end != '\0') return false;
  if (v < 1577836800LL) return false;

  epochOut = (time_t)v;
  return true;
}

static bool parseJsonUnixtime_(const String& body, time_t& epochOut) {
  const char* key = "\"unixtime\"";
  int pos = body.indexOf(key);
  if (pos < 0) return false;

  pos = body.indexOf(':', pos + (int)strlen(key));
  if (pos < 0) return false;
  ++pos;

  while (pos < body.length() && isSpace_(body[pos])) ++pos;
  if (pos >= body.length()) return false;

  char* end = nullptr;
  long long v = strtoll(body.c_str() + pos, &end, 10);
  if (end == body.c_str() + pos) return false;
  if (v < 1577836800LL) return false;

  epochOut = (time_t)v;
  return true;
}

static bool parseJsonTimestamp_(const String& body, time_t& epochOut) {
  const char* key = "\"timestamp\"";
  int pos = body.indexOf(key);
  if (pos < 0) return false;

  pos = body.indexOf(':', pos + (int)strlen(key));
  if (pos < 0) return false;
  ++pos;

  while (pos < body.length() && isSpace_(body[pos])) ++pos;
  if (pos >= body.length()) return false;

  char* end = nullptr;
  long long v = strtoll(body.c_str() + pos, &end, 10);
  if (end == body.c_str() + pos) return false;
  if (v < 1577836800LL) return false;

  epochOut = (time_t)v;
  return true;
}

static int64_t daysFromCivil_(int year, unsigned month, unsigned day) {
  year -= month <= 2;
  const int era = (year >= 0 ? year : year - 399) / 400;
  const unsigned yoe = (unsigned)(year - era * 400);
  const unsigned doy = (153 * (month + (month > 2 ? -3 : 9)) + 2) / 5 + day - 1;
  const unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  return (int64_t)era * 146097LL + (int64_t)doe - 719468LL;
}

static bool parseHttpDate_(const String& dateHeader, time_t& epochOut) {
  if (!dateHeader.length()) return false;

  struct tm tm = {};
  if (!strptime(dateHeader.c_str(), "%a, %d %b %Y %H:%M:%S GMT", &tm)) {
    return false;
  }

  const int year = tm.tm_year + 1900;
  const unsigned month = (unsigned)tm.tm_mon + 1U;
  const unsigned day = (unsigned)tm.tm_mday;
  const int64_t days = daysFromCivil_(year, month, day);
  const int64_t epoch =
      days * 86400LL +
      (int64_t)tm.tm_hour * 3600LL +
      (int64_t)tm.tm_min * 60LL +
      (int64_t)tm.tm_sec;

  if (epoch < 1577836800LL) return false;

  epochOut = (time_t)epoch;
  return true;
}

static bool applyEpoch_(time_t epoch, const char* sourceLabel) {
  struct timeval tv;
  tv.tv_sec = epoch;
  tv.tv_usec = 0;
  if (settimeofday(&tv, nullptr) != 0) {
    RTC_LOGW("%s: settimeofday failed\n", sourceLabel ? sourceLabel : "time sync");
    return false;
  }

  RTC_LOGI("%s: set epoch=%lld\n",
           sourceLabel ? sourceLabel : "time sync",
           (long long)epoch);
  RTCManager_sync();
  return true;
}

static bool syncFromHttpUrl_(const char* url, uint32_t timeout_ms) {
  if (!url || !*url) return false;

  static const char* kHeaderKeys[] = {"Date"};

  HTTPClient http;
  http.setReuse(false);
  http.setTimeout(timeout_ms);
  http.setConnectTimeout(timeout_ms);
  http.useHTTP10(true);
  http.collectHeaders(kHeaderKeys, sizeof(kHeaderKeys) / sizeof(kHeaderKeys[0]));

  RTC_LOGI("HTTP time fallback: GET %s\n", url);
  if (!http.begin(url)) {
    RTC_LOGW("HTTP time fallback: begin() failed\n");
    return false;
  }

  const int code = http.GET();
  if (code <= 0) {
    RTC_LOGW("HTTP time fallback: GET failed code=%d (%s)\n",
             code,
             HTTPClient::errorToString(code).c_str());
    http.end();
    return false;
  }

  const String dateHeader = http.header("Date");
  const String body = http.getString();
  RTC_LOGD("HTTP time fallback: HTTP %d\n", code);
  if (code != HTTP_CODE_OK && code != HTTP_CODE_NO_CONTENT) {
    RTC_LOGW("HTTP time fallback: unexpected HTTP status %d\n", code);
    if (body.length()) {
      RTC_LOGD("HTTP time fallback body: %.96s\n", body.c_str());
    }
  }
  http.end();

  time_t epoch = 0;
  if (parseLeadingEpoch_(body, epoch) ||
      parseJsonUnixtime_(body, epoch) ||
      parseJsonTimestamp_(body, epoch)) {
    return applyEpoch_(epoch, "HTTP time fallback");
  }

  if (parseHttpDate_(dateHeader, epoch)) {
    RTC_LOGI("HTTP time fallback: using Date header '%s'\n", dateHeader.c_str());
    return applyEpoch_(epoch, "HTTP time fallback");
  }

  if (!body.length() && dateHeader.length()) {
    RTC_LOGW("HTTP time fallback: Date header present but could not parse '%s'\n",
             dateHeader.c_str());
  } else {
    RTC_LOGW("HTTP time fallback: could not parse epoch from response\n");
  }
  if (body.length()) {
    RTC_LOGD("HTTP time fallback body: %.96s\n", body.c_str());
  }
  return false;
}

static void configureSntp_(const char* ntpServersCsv) {
  String n1, n2, n3;
  splitCsv3_(ntpServersCsv, n1, n2, n3);
  if (!n1.length()) n1 = "pool.ntp.org";
  if (!n2.length()) n2 = "time.nist.gov";

  snprintf(s_sntpServerNames_[0], sizeof(s_sntpServerNames_[0]), "%s", n1.c_str());
  snprintf(s_sntpServerNames_[1], sizeof(s_sntpServerNames_[1]), "%s", n2.c_str());
  snprintf(s_sntpServerNames_[2], sizeof(s_sntpServerNames_[2]), "%s", n3.c_str());

  if (esp_sntp_enabled()) {
    esp_sntp_stop();
  }

  esp_sntp_setoperatingmode(ESP_SNTP_OPMODE_POLL);
  esp_sntp_servermode_dhcp(false);
  esp_sntp_set_sync_mode(SNTP_SYNC_MODE_IMMED);
  esp_sntp_set_time_sync_notification_cb(sntpTimeSyncNotification_);
  esp_sntp_set_sync_status(SNTP_SYNC_STATUS_RESET);
  esp_sntp_setservername(0, s_sntpServerNames_[0]);
  esp_sntp_setservername(1, s_sntpServerNames_[1]);
  esp_sntp_setservername(2, s_sntpServerNames_[2]);
  esp_sntp_init();

  RTC_LOGI("SNTP configured: server0='%s' server1='%s' server2='%s'\n",
           s_sntpServerNames_[0],
           s_sntpServerNames_[1],
           s_sntpServerNames_[2]);
}

bool RTCManager_hasValidTime() {
  struct tm tmnow;
  // Non-blocking probe; if SNTP/RTC is ready, this will succeed quickly.
  if (!getLocalTime(&tmnow, 0)) return false;
  // Heuristic: reject the 1970 epoch or obviously bogus years
  return (tmnow.tm_year + 1900) >= 2020;
}

void RTCManager_setTimezone(const char* tz) {
  const char* applied = (tz && *tz) ? tz : "UTC";
  setenv("TZ", applied, 1);
  tzset();
  RTC_LOGD("Timezone applied: '%s'\n", applied);
}

bool RTCManager_waitForSNTP(uint32_t timeout_ms) {
  const uint32_t deadline = millis() + timeout_ms;
  // Consider anything >= 2020-01-01 as "valid"
  const time_t sane = 1577836800;
  time_t now = 0;

  RTC_LOGD("SNTP wait: enabled=%d mode=%s status=%s server0='%s' server1='%s' server2='%s'\n",
           esp_sntp_enabled() ? 1 : 0,
           sntpModeName_(esp_sntp_get_sync_mode()),
           sntpStatusName_(esp_sntp_get_sync_status()),
           esp_sntp_getservername(0) ? esp_sntp_getservername(0) : "",
           esp_sntp_getservername(1) ? esp_sntp_getservername(1) : "",
           esp_sntp_getservername(2) ? esp_sntp_getservername(2) : "");

  while ((int32_t)(millis() - deadline) < 0) {
    time(&now);
    if (now >= sane) return true;   // SNTP has set the system clock
    delay(200);

    static uint32_t nextLog = 0;
    if ((int32_t)(millis() - nextLog) >= 0) {
      nextLog = millis() + 1000;
      RTC_LOGI("Waiting SNTP... WiFi OK, RSSI %d, enabled=%d, status=%s\n",
               WiFi.RSSI(),
               esp_sntp_enabled() ? 1 : 0,
               sntpStatusName_(esp_sntp_get_sync_status()));
    }
  }
  RTC_LOGW("NTP: timeout waiting for SNTP. enabled=%d status=%s\n",
           esp_sntp_enabled() ? 1 : 0,
           sntpStatusName_(esp_sntp_get_sync_status()));
  return false;
}

bool RTCManager_syncNetworkTime(const char* tz,
                                const char* ntpServersCsv,
                                const char* timeCheckUrl,
                                uint32_t sntpTimeout_ms,
                                uint32_t httpTimeout_ms) {
  RTCManager_setTimezone(tz);
  configureSntp_(ntpServersCsv);

  if (RTCManager_waitForSNTP(sntpTimeout_ms)) {
    RTCManager_sync();
    return true;
  }

  if (RTCManager_syncFromHttp(timeCheckUrl, httpTimeout_ms)) {
    RTCManager_sync();
    return true;
  }

  return false;
}

bool RTCManager_syncFromHttp(const char* url, uint32_t timeout_ms) {
  if (WiFi.status() != WL_CONNECTED) {
    RTC_LOGW("HTTP time fallback skipped: WiFi not connected\n");
    return false;
  }

  if (url && *url) {
    if (syncFromHttpUrl_(url, timeout_ms)) {
      return true;
    }
    if (strstr(url, "worldtimeapi.org") != nullptr) {
      RTC_LOGW("HTTP time fallback: configured WorldTimeAPI URL failed; trying built-in fallbacks\n");
    }
  } else {
    RTC_LOGD("HTTP time fallback: no custom URL configured, trying built-in fallbacks\n");
  }

  for (size_t i = 0; i < sizeof(kBuiltinHttpTimeUrls_) / sizeof(kBuiltinHttpTimeUrls_[0]); ++i) {
    const char* fallbackUrl = kBuiltinHttpTimeUrls_[i];
    if (url && *url && strcmp(url, fallbackUrl) == 0) continue;
    if (syncFromHttpUrl_(fallbackUrl, timeout_ms)) {
      return true;
    }
  }

  RTC_LOGW("HTTP time fallback: all fallback URLs failed\n");
  return false;
}


// --- Setup RTC ---
void RTCManager_begin(RTCSource source, TwoWire* extRtcWire) {
  currentSource = source;

  if (currentSource == RTC_EXTERNAL) {
    s_externalRtcWire = extRtcWire ? extRtcWire : I2CManager::bus(0);
    if (!s_externalRtcWire) {
      RTC_LOGW("External RTC selected but no I2C bus available\n");
    }
    // externalRTC.begin(); // Uncomment for DS3231
    // if (!externalRTC.isrunning()) {
    //     RTC_LOGI("RTC not running, setting to compile time.\n");
    //     externalRTC.adjust(DateTime(F(__DATE__), F(__TIME__)));
    // }
  } else {
    // Internal RTC (ESP32 system time)
    esp_sntp_set_time_sync_notification_cb(sntpTimeSyncNotification_);
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

static void formatTimestampString_(uint64_t epochMs, char* out, size_t outLen) {
    if (!out || outLen == 0) return;

    if (!useHumanReadableTimestamps) {
        snprintf(out, outLen, "%llu", (unsigned long long)epochMs);
        return;
    }

    const time_t sec = (time_t)(epochMs / 1000ULL);
    struct tm tm;
    localtime_r(&sec, &tm);
    const unsigned msecs = (unsigned)(epochMs % 1000ULL);
    snprintf(out, outLen, "%02d:%02d:%02d.%03u",
             tm.tm_hour, tm.tm_min, tm.tm_sec, msecs);
}

// --- Fast timestamp string ---
String RTCManager_getFastTimestamp() {
    char buf[24];
    formatTimestampString_(RTCManager_getEpochMs(), buf, sizeof(buf));
    return String(buf);
}

bool RTCManager_isHumanReadable() {
    return useHumanReadableTimestamps;
}

void RTCManager_setHumanReadable(bool humanReadable) {
    useHumanReadableTimestamps = humanReadable;
}

String RTCManager_getTimestamp() {
    char buf[24];
    formatTimestampString_(RTCManager_getEpochMs(), buf, sizeof(buf));
    return String(buf);
}


// --- Raw epoch ---
time_t RTCManager_getEpoch() {
    unsigned long elapsedMs = millis() - baseMillis;
    return baseEpoch + (elapsedMs / 1000);
}

// Get low resolution time stamp for file naming
String RTCManager_getDateTimeString() {
    // Keep filename generation non-blocking. Arduino's getLocalTime()
    // defaults to a 5 s wait when the system clock is unset, which can
    // stall log start on warm boots or after sleep.
    const time_t sec = RTCManager_getEpoch();
    if (sec < 1577836800) {
        return "1970-01-01_00-00-00";
    }

    struct tm timeinfo;
    localtime_r(&sec, &timeinfo);
    if ((timeinfo.tm_year + 1900) < 2020) {
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

  RTC_LOGI("Internal time invalidated (epoch=0). Next boot should require SNTP.\n");
}
