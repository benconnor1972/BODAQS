#pragma once

// ─────────────────────────────────────────────────────────────────
// Host-test mocks for ConfigManager, WiFiManager, FirmwareInfo
//
// These provide implementations of the static methods declared in the
// real headers (ConfigManager.h, WiFiManager.h) that are normally
// implemented in ConfigManager.cpp / WiFiManager.cpp — which we do NOT
// compile in the test build.
//
// The real headers are included (via quote includes from src/) and
// declare the types (LoggerConfig, WiFiStatus, WiFiMode, etc.) and
// the static methods. This file provides the mock state and declares
// helper functions. The implementations live in mocks.cpp.
// ─────────────────────────────────────────────────────────────────

#include "Arduino.h"

// Forward-declare types from the real headers (they are defined when
// ConfigManager.h / WiFiManager.h are included by the production source).
// We just need the types for the mock state declarations.
// These enums are defined in ConfigManager.h:
//   enum class WiFiMode : uint8_t { Station = 0, AccessPoint = 1 };
// We re-declare here for when mocks.h is included without ConfigManager.h.
// If ConfigManager.h was already included, the include guards prevent
// redefinition.

// ── Mock state (defined in mocks.cpp) ──

// ConfigManager mock state
// LoggerConfig is defined in ConfigManager.h. We store a pointer to avoid
// needing the full type here. The actual storage is in mocks.cpp where
// ConfigManager.h has been included.
// But since mocks.h may be included before ConfigManager.h, we use a
// different approach: the mock state is accessed via functions.

// ── Mock control functions ──

// Set the logger name returned by ConfigManager::get().loggerName
void mockSetLoggerName(const char* name);

// Set the WiFi status returned by WiFiManager::status()
void mockSetNetworkUp(bool up);
void mockSetSsid(const char* ssid);
void mockSetIp(const char* ip);
void mockSetWifiMode(int mode);  // WiFiMode enum value

// Set the firmware version (for future use when FirmwareInfo is needed)
void mockSetVersion(const char* version);
const char* mockGetVersion();

// Reset all mock state to defaults
void mockResetAll();

// ── Default values ──
#define MOCK_DEFAULT_VERSION  "0.4.1"
#define MOCK_DEFAULT_LOGGER   "BODAQS"
#define MOCK_DEFAULT_SSID     "not connected"
#define MOCK_DEFAULT_IP       "-"
