#include "SharedSpiBus.h"

#if defined(ESP32)
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#endif

namespace {

SPIClass* s_spi = &SPI;
bool s_ready = false;
int8_t s_sck = -1;
int8_t s_miso = -1;
int8_t s_mosi = -1;
SharedSpiBus::Diagnostics s_diagnostics;

#if defined(ESP32)
SemaphoreHandle_t s_mutex = nullptr;
#endif

bool lock_(uint32_t timeoutMs) {
#if defined(ESP32)
  if (!s_mutex) s_mutex = xSemaphoreCreateMutex();
  if (!s_mutex) {
    ++s_diagnostics.lockTimeouts;
    return false;
  }
  if (xSemaphoreTake(s_mutex, pdMS_TO_TICKS(timeoutMs)) == pdTRUE) return true;
  ++s_diagnostics.lockTimeouts;
  return false;
#else
  (void)timeoutMs;
  return true;
#endif
}

void unlock_() {
#if defined(ESP32)
  if (s_mutex) xSemaphoreGive(s_mutex);
#endif
}

}  // namespace

namespace SharedSpiBus {

bool begin(const board::SPIProfile& profile) {
  if (!profile.present || profile.sck < 0 || profile.miso < 0 ||
      profile.mosi < 0) {
    return false;
  }
  if (s_ready) {
    return profile.sck == s_sck && profile.miso == s_miso &&
        profile.mosi == s_mosi;
  }

#if defined(ESP32)
  if (!s_mutex) s_mutex = xSemaphoreCreateMutex();
#endif
  s_spi->begin(profile.sck, profile.miso, profile.mosi);
  s_sck = profile.sck;
  s_miso = profile.miso;
  s_mosi = profile.mosi;
  s_ready = true;
  s_diagnostics.initialized = true;
  return true;
}

bool ready() { return s_ready; }

bool transfer(
    int8_t csPin,
    const SPISettings& settings,
    const uint8_t* tx,
    uint8_t* rx,
    size_t length,
    uint32_t lockTimeoutMs) {
  if (!s_ready || csPin < 0 || length == 0 || (!tx && !rx)) return false;
  if (!lock_(lockTimeoutMs)) return false;

  s_spi->beginTransaction(settings);
  digitalWrite(static_cast<uint8_t>(csPin), LOW);
  for (size_t index = 0; index < length; ++index) {
    const uint8_t received = s_spi->transfer(tx ? tx[index] : 0);
    if (rx) rx[index] = received;
  }
  digitalWrite(static_cast<uint8_t>(csPin), HIGH);
  s_spi->endTransaction();
  ++s_diagnostics.transactions;
  s_diagnostics.bytesTransferred += length;
  unlock_();
  return true;
}

const Diagnostics& diagnostics() { return s_diagnostics; }

}  // namespace SharedSpiBus
