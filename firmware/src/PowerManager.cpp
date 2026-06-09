#include "PowerManager.h"
#include <Arduino.h>
#include <Wire.h>
#include <esp_sleep.h>
#include "esp_system.h"
#include <driver/rtc_io.h>     // rtc_gpio_* APIs
#include "LoggingManager.h"
#include "WebServerManager.h"
#include "DisplayManager.h"
#include "StorageManager.h"    // if you have a flush/close; otherwise remove
#include "UI.h"
#include "I2CManager.h"
#include "ConfigManager.h"
#include "BoardProfile.h"
#include "DebugLog.h"
#include <string.h>

#define PWR_LOGI(...) LOGI_TAG("PWR", __VA_ARGS__)
#define PWR_LOGW(...) LOGW_TAG("PWR", __VA_ARGS__)

static constexpr uint8_t MAX17048_REG_CONFIG = 0x0C;
static constexpr uint8_t MAX17048_REG_STATUS = 0x1A;
static constexpr uint16_t MAX17048_CONFIG_ALRT = 0x0020;
static constexpr uint16_t MAX17048_STATUS_RI = 0x0100;
static constexpr uint16_t MAX17048_STATUS_VH = 0x0200;
static constexpr uint16_t MAX17048_STATUS_VL = 0x0400;
static constexpr uint16_t MAX17048_STATUS_VR = 0x0800;
static constexpr uint16_t MAX17048_STATUS_HD = 0x1000;
static constexpr uint16_t MAX17048_STATUS_SC = 0x2000;
static constexpr uint16_t MAX17048_STATUS_ENVR = 0x4000;

static constexpr float LOW_BATTERY_WARN_V = 3.30f;

// ---------------- Existing CPU-freq logic ----------------
static uint32_t g_prevCpuFreqMhz = 240;    // default / compile-time expectation

// ---------------- Fuel gauge state ----------------
static bool     g_fgInit     = false;
static bool     g_fgOk       = false;
static bool     g_fgDetected = false;
static uint8_t  g_fgAddr     = 0x36;
static TwoWire* g_fgWire     = nullptr;
static float    g_fgSocPct   = 0.0f;
static float    g_fgVbat     = 0.0f;
static uint32_t g_fgLastPoll = 0;
static int8_t   g_fgAlertPin = -1;
static bool     g_fgAlertActiveLow = true;
static bool     g_fgAlertUsePullup = true;
static bool     g_fgAlertActive = false;
static uint16_t g_fgAlertStatusRaw = 0;
static char     g_fgAlertCause[56] = "";
static uint32_t g_fgLastAlertToastMs = 0;
static uint32_t g_lastActivityMs = 0;

// ---------------- Analog rail state ----------------
static int8_t g_analogRailEnablePin = -1;
static bool   g_analogRailActiveHigh = true;
static bool   g_analogRailEnabled = false;
static gpio_num_t g_enterWakePin = GPIO_NUM_NC;
static bool       g_enterWakeActiveLow = true;
static bool       g_currentLimitPresent = false;
static int8_t     g_currentLimitFaultPin = -1;
static bool       g_currentLimitFaultActiveLow = true;
static bool       g_currentLimitFaultUsePullup = true;
static bool       g_analogRailFaultLatched = false;
static bool       g_analogRailFaultActive = false;
static char       g_analogRailFaultText[48] = "";

static bool hasAnalogRailEnable_()
{
  return g_analogRailEnablePin >= 0;
}

static bool readCurrentLimitFaultPin_()
{
  if (!g_currentLimitPresent || g_currentLimitFaultPin < 0) return false;
  const int level = digitalRead((uint8_t)g_currentLimitFaultPin);
  return g_currentLimitFaultActiveLow ? (level == LOW) : (level == HIGH);
}

static void latchAnalogRailFault_(const char* reason)
{
  g_analogRailFaultActive = true;
  g_analogRailFaultLatched = true;
  snprintf(g_analogRailFaultText,
           sizeof(g_analogRailFaultText),
           "%s",
           reason ? reason : "fault");
  PWR_LOGW("Analog rail fault: %s\n", g_analogRailFaultText);
}

static void applyAnalogRailPin_(bool enabled)
{
  if (!hasAnalogRailEnable_()) {
    g_analogRailEnabled = enabled;
    return;
  }

  const uint8_t level = (enabled == g_analogRailActiveHigh) ? HIGH : LOW;
  digitalWrite((uint8_t)g_analogRailEnablePin, level);
  g_analogRailEnabled = enabled;
}

static bool checkAnalogRailFault_(bool stopLogging)
{
  const bool fault = readCurrentLimitFaultPin_();
  g_analogRailFaultActive = fault;

  if (!fault) {
    if (g_analogRailFaultLatched && !g_analogRailEnabled) {
      g_analogRailFaultLatched = false;
      g_analogRailFaultText[0] = '\0';
      PWR_LOGI("Analog rail fault cleared\n");
    }
    return false;
  }

  latchAnalogRailFault_("current-limit fault");

  if (g_analogRailEnabled) {
    applyAnalogRailPin_(false);
    UI::status("Analog fault");
    UI::toast("Analog fault", 2000, 1);
  }

  if (stopLogging && LoggingManager::isRunning()) {
    PWR_LOGW("Stopping logging because analog rail fault asserted\n");
    LoggingManager::stop();
  }

  return true;
}

static bool batteryLowCached_()
{
  return g_fgOk && g_fgVbat > 0.0f && g_fgVbat < LOW_BATTERY_WARN_V;
}

static void updateAnalogRailForBattery_()
{
  if (batteryLowCached_()) {
    if (g_analogRailEnabled) {
      PWR_LOGW("Battery low %.3f V; disabling analog rail\n", (double)g_fgVbat);
    }
    applyAnalogRailPin_(false);
  }
}

static TwoWire* fuelWire_()
{
  if (g_fgWire) return g_fgWire;
  g_fgWire = I2CManager::bus(0);
  return g_fgWire;
}

static bool i2cRead16_(uint8_t addr, uint8_t reg, uint16_t &out)
{
  TwoWire* wire = fuelWire_();
  if (!wire) return false;
  if (!I2CManager::lock(wire)) return false;

  wire->beginTransmission(addr);
  wire->write(reg);
  if (wire->endTransmission(false) != 0) {
    I2CManager::unlock(wire);
    return false; // repeated-start
  }
  if (wire->requestFrom((int)addr, 2) != 2) {
    I2CManager::unlock(wire);
    return false;
  }

  const uint8_t msb = wire->read();
  const uint8_t lsb = wire->read();
  I2CManager::unlock(wire);
  out = (uint16_t(msb) << 8) | lsb;
  return true;
}

static bool i2cWrite16_(uint8_t addr, uint8_t reg, uint16_t value)
{
  TwoWire* wire = fuelWire_();
  if (!wire) return false;
  if (!I2CManager::lock(wire)) return false;

  wire->beginTransmission(addr);
  wire->write(reg);
  wire->write((uint8_t)(value >> 8));
  wire->write((uint8_t)(value & 0xFF));
  const bool ok = (wire->endTransmission() == 0);
  I2CManager::unlock(wire);
  return ok;
}

static bool max17048_read_(uint8_t addr, float &vbat_V, float &soc_pct)
{
  uint16_t vcell = 0, soc = 0;
  if (!i2cRead16_(addr, 0x02, vcell)) return false; // VCELL
  if (!i2cRead16_(addr, 0x04, soc))   return false; // SOC

  // VCELL conversion commonly used: volts = (raw >> 4) * 1.25mV
  vbat_V = ((vcell >> 4) * 1.25f) / 1000.0f;

  // SOC: MSB integer %, LSB 1/256 %
  soc_pct = float(soc >> 8) + (float(soc & 0xFF) / 256.0f);

  // Clamp just in case
  if (soc_pct < 0.0f) soc_pct = 0.0f;
  if (soc_pct > 100.0f) soc_pct = 100.0f;

  return true;
}

static bool max17048ReadAlert_(uint8_t addr, uint16_t& statusRaw, uint16_t& configRaw)
{
  if (!i2cRead16_(addr, MAX17048_REG_STATUS, statusRaw)) return false;
  if (!i2cRead16_(addr, MAX17048_REG_CONFIG, configRaw)) return false;
  return true;
}

static void appendCause_(char* out, size_t cap, const char* text)
{
  if (!out || cap == 0 || !text || !*text) return;
  const size_t len = strnlen(out, cap);
  if (len >= cap - 1) return;
  if (len > 0) {
    strncat(out, ",", cap - strlen(out) - 1);
  }
  strncat(out, text, cap - strlen(out) - 1);
}

static void decodeMax17048Alert_(uint16_t status, uint16_t config, char* out, size_t cap)
{
  if (!out || cap == 0) return;
  out[0] = '\0';
  if (status & MAX17048_STATUS_HD) appendCause_(out, cap, "low SOC");
  if (status & MAX17048_STATUS_SC) appendCause_(out, cap, "SOC change");
  if (status & MAX17048_STATUS_VL) appendCause_(out, cap, "undervoltage");
  if (status & MAX17048_STATUS_VH) appendCause_(out, cap, "overvoltage");
  if (status & MAX17048_STATUS_VR) appendCause_(out, cap, "voltage reset");
  if (status & MAX17048_STATUS_RI) appendCause_(out, cap, "reset");
  if (!out[0] && (config & MAX17048_CONFIG_ALRT)) {
    snprintf(out, cap, "alert");
  }
  if (!out[0]) {
    snprintf(out, cap, "none");
  }
}

static bool fuelAlertPinAsserted_()
{
  if (g_fgAlertPin < 0) return false;
  const int level = digitalRead((uint8_t)g_fgAlertPin);
  return g_fgAlertActiveLow ? (level == LOW) : (level == HIGH);
}

static void pollFuelAlert_()
{
  if (!g_fgDetected) return;

  const bool pinAsserted = fuelAlertPinAsserted_();
  uint16_t status = 0;
  uint16_t config = 0;
  if (!pinAsserted) {
    g_fgAlertActive = false;
    return;
  }

  if (!max17048ReadAlert_(g_fgAddr, status, config)) {
    g_fgAlertActive = true;
    snprintf(g_fgAlertCause, sizeof(g_fgAlertCause), "read failed");
    return;
  }

  g_fgAlertStatusRaw = status;
  decodeMax17048Alert_(status, config, g_fgAlertCause, sizeof(g_fgAlertCause));
  g_fgAlertActive = true;
  PWR_LOGW("Fuel alert: status=0x%04X config=0x%04X cause=%s\n",
           (unsigned)status,
           (unsigned)config,
           g_fgAlertCause);

  if ((uint32_t)(millis() - g_fgLastAlertToastMs) > 10000UL) {
    g_fgLastAlertToastMs = millis();
    if ((status & (MAX17048_STATUS_HD | MAX17048_STATUS_VL)) != 0) {
      UI::toast("Battery alert", 1800, 1);
      UI::status("Battery alert");
    }
  }

  const uint16_t clearStatus =
      (uint16_t)(status & ~(MAX17048_STATUS_RI |
                            MAX17048_STATUS_VH |
                            MAX17048_STATUS_VL |
                            MAX17048_STATUS_VR |
                            MAX17048_STATUS_HD |
                            MAX17048_STATUS_SC));
  (void)i2cWrite16_(g_fgAddr, MAX17048_REG_STATUS, clearStatus);
  (void)i2cWrite16_(g_fgAddr, MAX17048_REG_CONFIG, (uint16_t)(config & ~MAX17048_CONFIG_ALRT));
}

static bool i2cProbe_(uint8_t addr)
{
  TwoWire* wire = fuelWire_();
  if (!wire) return false;
  if (!I2CManager::lock(wire)) return false;
  wire->beginTransmission(addr);
  const bool ok = (wire->endTransmission() == 0);
  I2CManager::unlock(wire);
  return ok;
}

static bool max17048LooksPlausible_(uint8_t addr, float& v, float& s)
{
  if (!max17048_read_(addr, v, s)) return false;
  if (v < 2.0f || v > 5.5f) return false;
  if (s < 0.0f || s > 100.0f) return false;
  return true;
}

static void fuelGaugeInitIfNeeded_()
{
  if (g_fgInit) return;
  g_fgInit = true;

  if (!fuelWire_()) {
    g_fgOk = false;
    g_fgDetected = false;
    PWR_LOGI("Fuel gauge skipped: no I2C bus available\n");
    return;
  }

  float v = 0, s = 0;
  g_fgOk = max17048LooksPlausible_(g_fgAddr, v, s);
  if (!g_fgOk) {
    if (g_fgAddr != 0x36 && max17048LooksPlausible_(0x36, v, s)) {
      g_fgAddr = 0x36;
      g_fgOk = true;
    } else if (g_fgAddr != 0x32 && max17048LooksPlausible_(0x32, v, s)) {
      g_fgAddr = 0x32;
      g_fgOk = true;
    }
  }

  if (g_fgOk) {
    g_fgDetected = true;
    g_fgVbat = v;
    g_fgSocPct = s;
    PWR_LOGI("Fuel gauge detected at 0x%02X: %.3f V %.1f%%\n",
             (unsigned)g_fgAddr,
             (double)g_fgVbat,
             (double)g_fgSocPct);
  } else {
    g_fgDetected = false;
    PWR_LOGI("Fuel gauge not detected on configured/fallback addresses\n");
  }
}


static void preSleep_() {
  // Stop high-level activities cleanly
  if (LoggingManager::isRunning()) {
    LoggingManager::stop();
  }

  WebServerManager::stop();   // safe even if not started
  applyAnalogRailPin_(false);

  // Small UX: say good night and blank the OLED
  DisplayManager::setStatusLine("Sleeping...");
  delay(60);
  DisplayManager::clear();
  DisplayManager::present();
  delay(2000);
}

void PowerManager::sleepOnEnterEXT0()
{
  preSleep_();

  if (g_enterWakePin == GPIO_NUM_NC) {
    PWR_LOGW("No nav_enter wake pin configured; refusing deep sleep\n");
    DisplayManager::setStatusLine("Wake pin missing");
    delay(1200);
    return;
  }

  // ext0 wake only supports a single RTC IO pin.
  const gpio_num_t WAKE_PIN = g_enterWakePin;
  const int WAKE_LEVEL = g_enterWakeActiveLow ? 0 : 1;

  // Configure pin for RTC use and pullups so it doesn't float
  rtc_gpio_deinit(WAKE_PIN);
  rtc_gpio_init(WAKE_PIN);
  rtc_gpio_set_direction(WAKE_PIN, RTC_GPIO_MODE_INPUT_ONLY);
  rtc_gpio_pulldown_dis(WAKE_PIN);
  rtc_gpio_pullup_en(WAKE_PIN);

  // Enable wakeup
  esp_sleep_disable_wakeup_source(ESP_SLEEP_WAKEUP_ALL);
  esp_sleep_enable_ext0_wakeup(WAKE_PIN, WAKE_LEVEL);

  PWR_LOGI("Deep sleep (EXT0 on nav_enter GPIO%d, wake on %s)...\n",
           (int)WAKE_PIN,
           g_enterWakeActiveLow ? "LOW" : "HIGH");
  delay(50);

  esp_deep_sleep_start();
}

void PowerManager::noteActivity() {
  g_lastActivityMs = millis();
}

void PowerManager::loop() {
  checkAnalogRailFault_(true);

  const uint32_t timeoutMs = ConfigManager::get().autoSleepIdleMs;
  const uint32_t now = millis();

  if (g_lastActivityMs == 0) {
    g_lastActivityMs = now;
  }

  if (LoggingManager::isRunning()) {
    g_lastActivityMs = now;
    return;
  }

  if (timeoutMs == 0) return;

  if ((uint32_t)(now - g_lastActivityMs) < timeoutMs) return;

  PWR_LOGI("Auto-sleep after %lu ms inactivity\n", (unsigned long)timeoutMs);
  sleepOnEnterEXT0();
}

void PowerManager::setCpuFreqForLogging() {
  // Remember the current CPU frequency so we can restore it
  g_prevCpuFreqMhz = getCpuFrequencyMhz();   // Arduino helper

  // Try a lower frequency; 80 or 160 MHz are usually valid.
  setCpuFrequencyMhz(80);
}

void PowerManager::restoreCpuFreqAfterLogging() {
  setCpuFrequencyMhz(g_prevCpuFreqMhz);
}

// ---------------- Fuel gauge public API ----------------

void PowerManager::begin(const board::BoardProfile& board)
{
  g_analogRailEnablePin = board.analog.enable_pin;
  g_analogRailActiveHigh = board.analog.enable_active_high;
  g_fgAlertPin = board.fuel.alert_pin;
  g_fgAlertActiveLow = board.fuel.alert_active_low;
  g_fgAlertUsePullup = board.fuel.alert_use_internal_pullup;
  g_fgAlertActive = false;
  g_fgAlertStatusRaw = 0;
  g_fgAlertCause[0] = '\0';

  g_currentLimitPresent = board.current_limit.present;
  g_currentLimitFaultPin = board.current_limit.fault_pin;
  g_currentLimitFaultActiveLow = board.current_limit.fault_active_low;
  g_currentLimitFaultUsePullup = board.current_limit.fault_use_internal_pullup;
  g_analogRailFaultLatched = false;
  g_analogRailFaultActive = false;
  g_analogRailFaultText[0] = '\0';
  g_enterWakePin = GPIO_NUM_NC;
  g_enterWakeActiveLow = true;

  for (uint8_t i = 0; i < board.buttons.count; ++i) {
    const board::ButtonHW& btn = board.buttons.btn[i];
    if (!btn.present || btn.pin < 0) continue;
    if (strcmp(btn.id, "nav_enter") == 0) {
      g_enterWakePin = (gpio_num_t)btn.pin;
      g_enterWakeActiveLow = btn.active_low;
      break;
    }
  }

  if (g_enterWakePin != GPIO_NUM_NC) {
    PWR_LOGI("Deep-sleep wake button nav_enter GPIO%d active_%s\n",
             (int)g_enterWakePin,
             g_enterWakeActiveLow ? "low" : "high");
  } else {
    PWR_LOGW("nav_enter button not present in board profile; deep sleep disabled\n");
  }

  if (hasAnalogRailEnable_()) {
    pinMode((uint8_t)g_analogRailEnablePin, OUTPUT);
    applyAnalogRailPin_(board.analog.enable_default_on);
    PWR_LOGI("Analog rail enable GPIO%d active_%s default=%s\n",
             (int)g_analogRailEnablePin,
             g_analogRailActiveHigh ? "high" : "low",
             board.analog.enable_default_on ? "on" : "off");
  } else {
    g_analogRailEnabled = true;
  }

  if (g_fgAlertPin >= 0) {
    pinMode((uint8_t)g_fgAlertPin, g_fgAlertUsePullup ? INPUT_PULLUP : INPUT);
    PWR_LOGI("Fuel alert GPIO%d active_%s\n",
             (int)g_fgAlertPin,
             g_fgAlertActiveLow ? "low" : "high");
  }

  if (g_currentLimitPresent && g_currentLimitFaultPin >= 0) {
    pinMode((uint8_t)g_currentLimitFaultPin,
            g_currentLimitFaultUsePullup ? INPUT_PULLUP : INPUT);
    PWR_LOGI("Analog rail fault GPIO%d active_%s\n",
             (int)g_currentLimitFaultPin,
             g_currentLimitFaultActiveLow ? "low" : "high");
    (void)checkAnalogRailFault_(false);
  }
}

void PowerManager::fuelGaugeBegin(uint8_t i2c_addr, TwoWire* wire)
{
  g_fgAddr = i2c_addr ? i2c_addr : 0x36;
  g_fgWire = wire;
  g_fgInit = false;      // force re-init
  g_fgOk   = false;
  g_fgDetected = false;
  fuelGaugeInitIfNeeded_();
  updateAnalogRailForBattery_();
}

void PowerManager::fuelGaugeLoop()
{
  fuelGaugeInitIfNeeded_();
  if (!g_fgDetected) return;

  if (g_fgAlertPin >= 0) {
    pollFuelAlert_();
  }

  // Poll at ~1 Hz; adjust later as you like
  const uint32_t now = millis();
  if (now - g_fgLastPoll < 1000) return;
  g_fgLastPoll = now;

  float v = 0, s = 0;
  g_fgOk = max17048_read_(g_fgAddr, v, s);
  if (g_fgOk) {
    g_fgVbat = v;
    g_fgSocPct = s;
    updateAnalogRailForBattery_();
  }
}

bool PowerManager::fuelGaugeOk()
{
  fuelGaugeInitIfNeeded_();
  return g_fgOk;
}

float PowerManager::batterySocPercent()
{
  fuelGaugeInitIfNeeded_();
  return g_fgSocPct;
}

float PowerManager::batteryVoltage()
{
  fuelGaugeInitIfNeeded_();
  return g_fgVbat;
}

bool PowerManager::batteryLow()
{
  fuelGaugeInitIfNeeded_();
  return batteryLowCached_();
}

bool PowerManager::fuelAlertActive()
{
  fuelGaugeInitIfNeeded_();
  if (g_fgAlertPin >= 0) {
    pollFuelAlert_();
  }
  return g_fgAlertActive;
}

const char* PowerManager::fuelAlertCause()
{
  return g_fgAlertCause;
}

uint16_t PowerManager::fuelAlertStatusRaw()
{
  return g_fgAlertStatusRaw;
}

void PowerManager::setAnalogRailEnabled(bool enabled)
{
  if (enabled && checkAnalogRailFault_(false)) {
    return;
  }
  applyAnalogRailPin_(enabled);
  if (enabled) {
    delay(5);
    (void)checkAnalogRailFault_(false);
  }
}

bool PowerManager::analogRailEnabled()
{
  return g_analogRailEnabled;
}

bool PowerManager::analogRailFaultActive()
{
  (void)checkAnalogRailFault_(false);
  return g_analogRailFaultActive;
}

bool PowerManager::analogRailFaultLatched()
{
  (void)checkAnalogRailFault_(false);
  return g_analogRailFaultLatched;
}

const char* PowerManager::analogRailFaultText()
{
  return g_analogRailFaultText;
}

bool PowerManager::canStartLogging()
{
  fuelGaugeInitIfNeeded_();
  if (batteryLowCached_()) {
    applyAnalogRailPin_(false);
    return false;
  }

  if (checkAnalogRailFault_(false)) {
    applyAnalogRailPin_(false);
    return false;
  }

  if (!g_analogRailEnabled) {
    applyAnalogRailPin_(true);
    delay(5);
    if (checkAnalogRailFault_(false)) {
      applyAnalogRailPin_(false);
      return false;
    }
  }
  return true;
}
