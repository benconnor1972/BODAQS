#ifndef RTCMANAGER_H
#define RTCMANAGER_H

#include <Arduino.h>
class TwoWire;

// Choose source of time
enum RTCSource {
    RTC_INTERNAL,
    RTC_EXTERNAL
};

// Invalidate ESP32 internal time so next boot forces SNTP/NTP to repopulate it.
// Does not touch any external RTC (not implemented / not in use).
void RTCManager_invalidateInternalTime();

// Initialize RTC system
void RTCManager_begin(RTCSource source = RTC_INTERNAL, TwoWire* extRtcWire = nullptr);

// Apply POSIX TZ string for localtime()/timestamp formatting.
void RTCManager_setTimezone(const char* tz);

// Call periodically to resync epoch once per second
void RTCManager_loop();

String RTCManager_getTimestamp();        // full timestamp with ms
String RTCManager_getFastTimestamp();    // cached / fast timestamp
String RTCManager_getDateTimeString();   // safe for filenames (to the second)
uint64_t RTCManager_getEpochMs();

// Deal with option to have human-readable time stamps
bool RTCManager_isHumanReadable();

void RTCManager_setHumanReadable(bool humanReadable);

// Get raw epoch (seconds since 1970)
time_t RTCManager_getEpoch();

// Force a resync with the RTC/NTP 
void RTCManager_sync();

// Returns true if local time looks valid (SNTP or external RTC has set it)
bool RTCManager_hasValidTime();

// Wait for SNTP to populate time (does NOT manipulate Wi-Fi). Returns true on success.
bool RTCManager_waitForSNTP(uint32_t timeoutMs = 8000);

// Attempt to sync internal time over the network. Applies timezone, tries SNTP,
// and falls back to HTTP if configured.
bool RTCManager_syncNetworkTime(const char* tz,
                                const char* ntpServersCsv,
                                const char* timeCheckUrl,
                                uint32_t sntpTimeoutMs = 8000,
                                uint32_t httpTimeoutMs = 5000);

// Fallback time sync over HTTP(S). Accepts a Unix epoch body, JSON bodies
// containing "unixtime" or "timestamp", or a valid RFC 7231 Date header.
// If the configured URL fails, built-in fallback URLs are also tried.
bool RTCManager_syncFromHttp(const char* url, uint32_t timeoutMs = 5000);


#endif
