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
#include "DebugLog.h"

#define PWR_LOGI(...) LOGI_TAG("PWR", __VA_ARGS__)

// ---------------- Existing CPU-freq logic ----------------
static uint32_t g_prevCpuFreqMhz = 240;    // default / compile-time expectation

// ---------------- Fuel gauge state ----------------
static bool     g_fgInit     = false;
static bool     g_fgOk       = false;
static uint8_t  g_fgAddr     = 0x36;
static float    g_fgSocPct   = 0.0f;
static float    g_fgVbat     = 0.0f;
static uint32_t g_fgLastPoll = 0;

static bool i2cRead16_(uint8_t addr, uint8_t reg, uint16_t &out)
{
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false; // repeated-start
  if (Wire.requestFrom((int)addr, 2) != 2) return false;

  const uint8_t msb = Wire.read();
  const uint8_t lsb = Wire.read();
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
  Wire.beginTransmission(addr);
  return (Wire.endTransmission() == 0);
}

static void fuelGaugeInitIfNeeded_()
{
  if (g_fgInit) return;
  g_fgInit = true;

  // Start I2C if not already started elsewhere.
  // (Safe to call even if DisplayManager already did it.)
  Wire.begin();
  Wire.setClock(400000);

  // If the configured address doesn't ACK, try common ones.
  if (!i2cProbe_(g_fgAddr)) {
    if (i2cProbe_(0x36)) g_fgAddr = 0x36;
    else if (i2cProbe_(0x32)) g_fgAddr = 0x32;
  }

  // Initial read to set ok flag
  float v = 0, s = 0;
  g_fgOk = max17048_read_(g_fgAddr, v, s);
  if (g_fgOk) {
    g_fgVbat = v;
    g_fgSocPct = s;
  }
}


static void preSleep_() {
  // Stop high-level activities cleanly
  if (LoggingManager::isRunning()) {
    LoggingManager::stop();
  }

  WebServerManager::stop();   // safe even if not started

  // Small UX: say good night and blank the OLED
  DisplayManager::setStatusLine("Sleeping…");
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

void PowerManager::fuelGaugeBegin(uint8_t i2c_addr)
{
  g_fgAddr = i2c_addr ? i2c_addr : 0x36;
  g_fgInit = false;      // force re-init
  g_fgOk   = false;
  fuelGaugeInitIfNeeded_();
}

void PowerManager::fuelGaugeLoop()
{
  fuelGaugeInitIfNeeded_();

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
