#pragma once

// ─────────────────────────────────────────────────────────────────
// Host-test stub for WiFi.h
// Provides: wl_status_t, IPAddress
// Needed by WiFiManager.h which uses these types
// ─────────────────────────────────────────────────────────────────

#include <stdint.h>

// wl_status_t — matches ESP32 WiFi library enum
typedef enum {
    WL_NO_SHIELD        = 255,
    WL_IDLE_STATUS      = 0,
    WL_NO_SSID_AVAIL    = 1,
    WL_SCAN_COMPLETED   = 2,
    WL_CONNECTED        = 3,
    WL_CONNECT_FAILED   = 4,
    WL_CONNECTION_LOST  = 5,
    WL_DISCONNECTED     = 6
} wl_status_t;

// IPAddress — minimal stub (only type needed for declarations in WiFiManager.h)
class IPAddress {
public:
    IPAddress() {}
    IPAddress(uint8_t /*a*/, uint8_t /*b*/, uint8_t /*c*/, uint8_t /*d*/) {}
};
