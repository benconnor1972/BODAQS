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
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
SharedSpiBus::ProbeStats s_probe;
#if defined(ESP32)
portMUX_TYPE s_probeMux = portMUX_INITIALIZER_UNLOCKED;
#define PROBE_ENTER() portENTER_CRITICAL(&s_probeMux)
#define PROBE_EXIT() portEXIT_CRITICAL(&s_probeMux)
#else
#define PROBE_ENTER() ((void)0)
#define PROBE_EXIT() ((void)0)
#endif
void recordProbe_(int8_t cs, size_t bytes, bool ok, uint32_t wait, uint32_t owned) {
  PROBE_ENTER();
  for (auto& p : s_probe.participant) {
    if (p.csPin != cs && p.csPin != -1) continue;
    p.csPin = cs;
    if (ok) {
      ++p.transfers;
      p.bytes += bytes;
      TimingStats_record(p.lockWait, wait);
      TimingStats_record(p.ownership, owned);
    } else {
      ++p.lockFailures;
    }
    break;
  }
  PROBE_EXIT();
}
#endif

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
    uint32_t lockTimeoutMs
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
    , void (*probeAfterCsRelease)(void*), void* probeContext
#endif
    ) {
  if (!s_ready || csPin < 0 || length == 0 || (!tx && !rx)) return false;
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
  const uint32_t requestedUs = micros();
#endif
  if (!lock_(lockTimeoutMs)) {
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
    recordProbe_(csPin, length, false, 0, 0);
#endif
    return false;
  }
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
  const uint32_t lockedUs = micros();
#endif

  s_spi->beginTransaction(settings);
  digitalWrite(static_cast<uint8_t>(csPin), LOW);
#if defined(ESP32)
  s_spi->transferBytes(tx, rx, length);
#else
  for (size_t index = 0; index < length; ++index) {
    const uint8_t received = s_spi->transfer(tx ? tx[index] : 0);
    if (rx) rx[index] = received;
  }
#endif
  digitalWrite(static_cast<uint8_t>(csPin), HIGH);
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
  if (probeAfterCsRelease) probeAfterCsRelease(probeContext);
#endif
  s_spi->endTransaction();
  ++s_diagnostics.transactions;
  s_diagnostics.bytesTransferred += length;
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
  const uint32_t ownedUs = (uint32_t)(micros() - lockedUs);
#endif
  unlock_();
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
  recordProbe_(csPin, length, true, (uint32_t)(lockedUs - requestedUs), ownedUs);
#endif
  return true;
}

const Diagnostics& diagnostics() { return s_diagnostics; }
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
void probeReset() { PROBE_ENTER(); s_probe = ProbeStats{}; PROBE_EXIT(); }
ProbeStats probeSnapshot() { PROBE_ENTER(); const auto copy = s_probe; PROBE_EXIT(); return copy; }
#endif

}  // namespace SharedSpiBus
