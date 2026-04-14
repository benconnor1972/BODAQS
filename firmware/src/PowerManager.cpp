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
#include "I2CManager.h"
#include "DebugLog.h"

#define PWR_LOGI(...) LOGI_TAG("PWR", __VA_ARGS__)

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

  // ENTER on GPIO13, active-low. ext0 wake only supports a single RTC IO pin.
  constexpr gpio_num_t WAKE_PIN = GPIO_NUM_21;
  constexpr int WAKE_LEVEL = 0; // wake when pin is low

  // Configure pin for RTC use and pullups so it doesn't float
  rtc_gpio_deinit(WAKE_PIN);
  rtc_gpio_init(WAKE_PIN);
  rtc_gpio_set_direction(WAKE_PIN, RTC_GPIO_MODE_INPUT_ONLY);
  rtc_gpio_pulldown_dis(WAKE_PIN);
  rtc_gpio_pullup_en(WAKE_PIN);

  // Enable wakeup
  esp_sleep_disable_wakeup_source(ESP_SLEEP_WAKEUP_ALL);
  esp_sleep_enable_ext0_wakeup(WAKE_PIN, WAKE_LEVEL);

  PWR_LOGI("Deep sleep (EXT0 on GPIO13, wake on LOW)...\n");
  delay(50);

  esp_deep_sleep_start();
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

void PowerManager::fuelGaugeBegin(uint8_t i2c_addr, TwoWire* wire)
{
  g_fgAddr = i2c_addr ? i2c_addr : 0x36;
  g_fgWire = wire;
  g_fgInit = false;      // force re-init
  g_fgOk   = false;
  g_fgDetected = false;
  fuelGaugeInitIfNeeded_();
}

void PowerManager::fuelGaugeLoop()
{
  fuelGaugeInitIfNeeded_();
  if (!g_fgDetected) return;

  // Poll at ~1 Hz; adjust later as you like
  const uint32_t now = millis();
  if (now - g_fgLastPoll < 1000) return;
  g_fgLastPoll = now;

  float v = 0, s = 0;
  g_fgOk = max17048_read_(g_fgAddr, v, s);
  if (g_fgOk) {
    g_fgVbat = v;
    g_fgSocPct = s;
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
