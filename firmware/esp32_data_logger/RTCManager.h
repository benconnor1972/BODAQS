#ifndef RTCMANAGER_H
#define RTCMANAGER_H

#include <Arduino.h>

// Choose source of time
enum RTCSource {
    RTC_INTERNAL,
    RTC_EXTERNAL
};

// Invalidate ESP32 internal time so next boot forces SNTP/NTP to repopulate it.
// Does not touch any external RTC (not implemented / not in use).
void RTCManager_invalidateInternalTime();

// Initialize RTC system
void RTCManager_begin(RTCSource source = RTC_INTERNAL);

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


#endif
