#include "PowerManager.h"
#include <Arduino.h>
#include <esp_sleep.h>
#include "esp_system.h"
#include <driver/rtc_io.h>     // rtc_gpio_* APIs
#include "LoggingManager.h"
#include "WebServerManager.h"
#include "DisplayManager.h"
#include "StorageManager.h"    // if you have a flush/close; otherwise remove

static uint32_t g_prevCpuFreqMhz = 240;    // default / compile-time expectation

static void preSleep_() {
  // Stop high-level activities cleanly
  if (LoggingManager::isRunning()) LoggingManager::stop();
  WebServerManager::stop();              // if applicable
  // Flush SD if you have an explicit API; otherwise rely on close-on-stop
  // StorageManager::syncAndClose();

  // Small UX: say good night and blank the OLED
  DisplayManager::setStatusLine("Sleeping…");
  delay(60);
  DisplayManager::clear();
  DisplayManager::present();
  delay(20);

  // Optional: power down radios explicitly
  // WiFi.mode(WIFI_OFF); btStop();
}

void PowerManager::sleepOnEnterEXT0() {
  constexpr gpio_num_t ENTER_GPIO = GPIO_NUM_13;  // your ENTER button pin (RTC capable)
  constexpr int        WAKE_LEVEL = 0;            // active-LOW -> wake on LOW

  preSleep_();

  // Ensure the button is RELEASED before enabling wake (avoid instant wake)
  pinMode(ENTER_GPIO, INPUT_PULLUP);
  while (digitalRead(ENTER_GPIO) == LOW) { delay(5); }

  // Configure RTC-domain pull-up so the pin is defined during deep sleep
  rtc_gpio_init(ENTER_GPIO);
  rtc_gpio_set_direction(ENTER_GPIO, RTC_GPIO_MODE_INPUT_ONLY);
  rtc_gpio_pullup_en(ENTER_GPIO);
  rtc_gpio_pulldown_dis(ENTER_GPIO);

  // Set wake source: single pin (level-sensitive)
  esp_sleep_disable_wakeup_source(ESP_SLEEP_WAKEUP_ALL);
  esp_sleep_enable_ext0_wakeup(ENTER_GPIO, WAKE_LEVEL); // 0=LOW, 1=HIGH

  // Enter deep sleep (CPU restarts at boot on wake)
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
