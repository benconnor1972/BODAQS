#pragma once
#include <Arduino.h>
#include <SdFat.h>
#include <stdint.h>
#include "SensorTypes.h"   // owns SensorType + SensorSpec
#include "Calibration.h"

// ----------------- Modes & global config -----------------

// Keep PotMode here (single definition). SensorTypes.h forward-declares it.
enum PotMode : uint8_t {
  POT_MODE_RAW  = 0,
  POT_MODE_NORM = 1,
  POT_MODE_MM   = 2
};

struct SensorSpec; 

// ----------------- Button + binding config -----------------

static constexpr uint8_t MAX_BUTTONS         = 10;
static constexpr uint8_t MAX_BUTTON_BINDINGS = 24;

// Logical button definition: describes one physical button.
struct ButtonDef {
  char    id[16]    = "";  // e.g. "nav_right", "mark"
  uint8_t pin       = 0;   // GPIO number
  bool    activeLow = true;
  uint8_t mode      = 0;   // 0 = interrupt, 1 = poll (or similar)
};

// Binding definition: maps a (button, event) pair to a logical action.
struct ButtonBindingDef {
  char buttonId[16] = "";  // must match ButtonDef::id
  char event[16]    = "";  // "click", "held", "double_click", etc.
  char action[32]   = "";  // "logging_toggle", "wifi_toggle", etc.
};

struct LoggerConfig {
  // sampling / time
  uint16_t sampleRateHz     = 100;
  bool     timestampHuman   = true;
  char     tz[64]           = "UTC";
  char     ntpServers[128]  = "";
  char     timeCheckUrl[96] = "";

  // buttons / debounce
  uint16_t debounceMs = 50;
  uint8_t  webBtnPin  = 0;
  uint8_t  logBtnPin  = 0;
  uint8_t  markBtnPin = 0;
  uint8_t navUpPin     = 0;
  uint8_t navDownPin   = 0;
  uint8_t navLeftPin   = 0;
  uint8_t navRightPin  = 0;
  uint8_t navEnterPin  = 0;
  // RTC choice
  bool     useExternalRTC = false;

  // --- Buttons and button bindings ---

  ButtonDef        buttons[MAX_BUTTONS];
  uint8_t          buttonCount        = 0;

  ButtonBindingDef buttonBindings[MAX_BUTTON_BINDINGS];
  uint8_t          buttonBindingCount = 0;

  //Configured sensors parsed from file
  SensorSpec sensors[MAX_SENSORS];
  uint8_t sensorN=0;

  // WiFi / Web
  char     wifiSSID[64]     = "";
  char     wifiPassword[64] = "";

  // ---- Add below existing WiFi / Web fields in LoggerConfig ----
    // New-style WiFi config (multi-network)
    bool     wifiEnabledDefault       = false;  // Wi-Fi off by default (your preference)
    bool     wifiAutoTimeOnRtcInvalid = true;   // allow Wi-Fi to auto-enable only if RTC invalid

    struct WiFiEntry {
      char     ssid[64]     = "";
      char     password[64] = "";
      // Optional filters
      int16_t  minRssi      = -127;   // -127 = unset; else dBm in [-100..-10]
      uint8_t  bssid[6]     = {0};    // optional BSSID pin
      bool     bssidSet     = false;
      bool     hidden       = false;  // future: attempt without scan
    };

    uint8_t   wifiNetworkCount = 0;   // normalized after load()
    WiFiEntry wifi[5];                // order defines priority

  // UI
  uint8_t uiTarget       = 1;   // 1=serial, 2=oled, 3=both
  uint8_t uiSerialLevel  = 3;
  uint8_t uiOledLevel    = 3;
  uint8_t oledBrightness = 200;
  uint16_t oledIdleDimMs = 30000;

  //Methods
  uint8_t sensorCount() const;
  bool getSensorSpec(uint8_t i, SensorSpec& out) const;
  int8_t findSensorByName(const char* name) const;

};

class ConfigManager {
  public:
    static void begin(SdFat* sdRef, const char* filename);

    // Wi-Fi config accessors (read-only)
    static bool hasConfiguredNetworks();

    // Returns a pointer to the first element of the fixed array of Wi-Fi entries.
    // 'count' is filled with the normalized number of valid networks (0..5).
    static const LoggerConfig::WiFiEntry* wifiNetworks(size_t& count);


    // In ConfigManager.h (public)
    static bool getParam(uint8_t index, const char* key, String& out);
    static bool getIntParam(uint8_t index, const char* key, long& out);
    static bool getFloatParam(uint8_t index, const char* key, double& out);
    static bool getBoolParam(uint8_t index, const char* key, bool& out);
    static bool saveSensorParamByName(const char* sensorName, const char* key, const String& value);
    static bool saveSensorParamByIndex(uint8_t index, const char* key, const String& value);
    static bool setSensorHeaderByIndex(uint8_t index, const SensorSpec& sp);

    static void debugDumpConfigFile();

    // load/save/print the whole config file (includes sensor blocks)
    static bool load(LoggerConfig& cfg);
    static bool save(const LoggerConfig& cfg);
    static void print(const LoggerConfig& cfg);
    static const LoggerConfig& get();

    // Load calibration block for a given sensor (by name or id)
    static bool loadCalibration(const char* sensorName, Calibration& out);
    // Save calibration block (dynamic subset only; do not touch pins/wiring)
    static bool saveCalibration(const char* sensorName, const Calibration& cal);
    // Optional: recompute-and-apply convenience when units range changes
    static bool recomputeCalibrationFromUnits(const char* sensorName, float u0_units, float u1_units);
    // Calibration debug print (to Serial)
    static void printCalibration(const char* sensorName);
    static void printCalibration(int8_t sensorIndex);
    static void printAllCalibrations();
    static CalModeMask calAllowedMaskByIndex(uint8_t index);
    static CalModeMask calAllowedMaskByName(const char* sensorName);
    static bool loadCalibrationByIndex(uint8_t index, Calibration& out);
    static bool saveCalibrationByIndex(uint8_t index, const Calibration& cal);
    static CalMode  loadCalModeByIndex(uint8_t index);
    static void     setCalAllowedByIndex(uint8_t index, CalModeMask m);


    // helpers used by other modules
    static void trimInPlace(char* s);
    static bool parseBool(const String& s, bool& out);

    // --- sensor list API (single source of truth) ---
    static uint8_t sensorCount();                               // # of valid specs
    static bool    getSensorSpec(uint8_t i, SensorSpec& out);   // copy-out by index
    static int8_t  findSensorByName(const char* name);          // -1 if not found
    static void setSampleRateHz(uint16_t hz, bool persist = true);

    // line parser (public so tests or tooling can reuse)
    static bool parseLine(char* line, LoggerConfig& cfg);

  private:
    ConfigManager() = delete;
};


