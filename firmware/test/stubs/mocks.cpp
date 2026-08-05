// ─────────────────────────────────────────────────────────────────
// Mock implementations for ConfigManager, WiFiManager
//
// These provide the static method implementations that are normally
// in ConfigManager.cpp / WiFiManager.cpp (which we don't compile in
// the test build). The real headers declare the methods; we define them.
// ─────────────────────────────────────────────────────────────────

#include "mocks.h"
#include "ConfigManager.h"
#include "WiFiManager.h"
#include "FirmwareInfo.h"

// ── Mock state ──

static LoggerConfig mockConfig;
static WiFiStatus    mockWifiStatus;
static const char*   mockVersion = MOCK_DEFAULT_VERSION;

// ── ConfigManager static method implementations ──

const LoggerConfig& ConfigManager::get() {
    return mockConfig;
}

const char* ConfigManager::wifiModeLabel(WiFiMode mode) {
    switch (mode) {
        case WiFiMode::Station:     return "Station";
        case WiFiMode::AccessPoint: return "Access Point";
        default:                    return "Unknown";
    }
}

// ── WiFiManager static method implementation ──

WiFiStatus WiFiManager::status() {
    return mockWifiStatus;
}

// ── FirmwareInfo mock implementations ──

const char* FirmwareInfo::version() {
    return mockGetVersion();
}

const char* FirmwareInfo::name() {
    return "BODAQS";
}

const char* FirmwareInfo::buildDateTime() {
    return "test";
}

const char* FirmwareInfo::boardName() {
    return "Test Board";
}

// ── Mock control functions ──

void mockSetLoggerName(const char* name) {
    if (!name) return;
    strncpy(mockConfig.loggerName, name, sizeof(mockConfig.loggerName) - 1);
    mockConfig.loggerName[sizeof(mockConfig.loggerName) - 1] = '\0';
}

void mockSetNetworkUp(bool up) {
    mockWifiStatus.networkUp = up;
}

void mockSetSsid(const char* ssid) {
    mockWifiStatus.ssid = ssid ? ssid : "";
}

void mockSetIp(const char* ip) {
    mockWifiStatus.ip = ip ? ip : "";
}

void mockSetWifiMode(int mode) {
    mockWifiStatus.mode = static_cast<WiFiMode>(mode);
}

void mockSetVersion(const char* version) {
    mockVersion = version ? version : MOCK_DEFAULT_VERSION;
}

const char* mockGetVersion() {
    return mockVersion;
}

void mockResetAll() {
    // Reset config to defaults (uses LoggerConfig's default member initializers)
    mockConfig = LoggerConfig{};

    // Reset WiFi status
    mockWifiStatus = WiFiStatus{};
    mockWifiStatus.networkUp = false;
    mockWifiStatus.ssid = MOCK_DEFAULT_SSID;
    mockWifiStatus.ip = MOCK_DEFAULT_IP;
    mockWifiStatus.mode = WiFiMode::Station;

    // Reset version
    mockVersion = MOCK_DEFAULT_VERSION;
}
