#include "SharedSpiBus.h"
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
#include "esp_timer.h"
#endif

#if defined(ESP32)
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
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
SharedSpiBus::ProbeTrafficWindow s_traffic;
bool s_trafficActive=false;
SharedSpiBus::ProbeContext s_previous;
bool s_previousValid=false;
uint32_t s_sequence=0;
board::SPIProfile s_probeProfile;
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
  if(s_trafficActive)for(auto& p:s_traffic.participant) {
    if(p.cs!=cs && p.cs!=-1)continue;
    p.cs=cs;
    p.coreMask|=1U<<xPortGetCoreID();
    if(ok) {
      ++p.transfers;
      if(bytes==5)++p.steps[0];
      else if(bytes==1)++p.steps[1];
      else if(bytes==4)++p.steps[2];
    } else ++p.lockFailures;
    break;
  }
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
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
  s_probeProfile = profile;
#endif
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
    , void (*probeAfterCsRelease)(void*), void* probeContext, ProbeContext* transactionContext,
    bool probeUnselected
#endif
    ) {
  if (!s_ready || csPin < 0 || length == 0 || (!tx && !rx)) return false;
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
  const uint32_t requestedUs = micros();
  const int8_t observedCs = probeUnselected ? -2 : csPin;
#endif
  if (!lock_(lockTimeoutMs)) {
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
    recordProbe_(observedCs, length, false, 0, 0);
#endif
    return false;
  }
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
  const uint32_t lockedUs = micros();
  if (probeUnselected) {
    for (uint8_t i=0;i<s_probeProfile.cs_count && i<8;++i)
      if(s_probeProfile.cs_pins[i]>=0) digitalWrite(static_cast<uint8_t>(s_probeProfile.cs_pins[i]),HIGH);
  }
#endif

  s_spi->beginTransaction(settings);
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
  ProbeContext context;
  context.sequence=++s_sequence;context.cs=observedCs;context.previousValid=s_previousValid;
  context.previousCs=s_previousValid?s_previous.cs:-1;
  context.previousReleaseUs=s_previous.csReleaseUs;
  context.operation.bytes=static_cast<uint16_t>(length);
  context.operation.hasTx=tx!=nullptr;context.operation.hasRx=rx!=nullptr;
  context.operation.tx0=tx?tx[0]:0;
  context.previousOperation=s_previous.operation;
  context.csAssertUs=micros();
  if(!probeUnselected)
#endif
  digitalWrite(static_cast<uint8_t>(csPin), LOW);
#if defined(ESP32)
  s_spi->transferBytes(tx, rx, length);
#else
  for (size_t index = 0; index < length; ++index) {
    const uint8_t received = s_spi->transfer(tx ? tx[index] : 0);
    if (rx) rx[index] = received;
  }
#endif
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
  if(!probeUnselected)
#endif
  digitalWrite(static_cast<uint8_t>(csPin), HIGH);
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
  context.csReleaseUs=micros();
  s_previous=context;s_previousValid=true;
  if(transactionContext)*transactionContext=context;
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
  recordProbe_(observedCs, length, true, (uint32_t)(lockedUs - requestedUs), ownedUs);
#endif
  return true;
}

const Diagnostics& diagnostics() { return s_diagnostics; }
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
void probeReset() {
  // Caller has stopped participants; use the real bus mutex for context state.
  if(!lock_(50))return;
  s_previous=ProbeContext{};s_previousValid=false;s_sequence=0;
  PROBE_ENTER();s_probe=ProbeStats{};PROBE_EXIT();unlock_();
}
bool probeUnselectedClocks(const board::SPIProfile& profile) {
  if(!s_ready || !profile.present)return false;
  const uint32_t requested=micros();
  if(!lock_(50)){recordProbe_(-2,4,false,0,0);return false;}
  const uint32_t began=micros();
  for(uint8_t i=0;i<profile.cs_count && i<8;++i)if(profile.cs_pins[i]>=0)
    digitalWrite(static_cast<uint8_t>(profile.cs_pins[i]),HIGH);
  s_spi->beginTransaction(SPISettings(1000000,MSBFIRST,SPI_MODE1));
  uint8_t bytes[4]={};
#if defined(ESP32)
  s_spi->transferBytes(bytes,nullptr,sizeof(bytes));
#else
  for(uint8_t byte:bytes)s_spi->transfer(byte);
#endif
  s_spi->endTransaction();
  s_previous=ProbeContext{};s_previous.sequence=++s_sequence;s_previous.cs=-2;
  s_previous.operation.bytes=4;s_previous.operation.hasTx=true;
  s_previous.csAssertUs=began;s_previous.csReleaseUs=micros();s_previousValid=true;
  const uint32_t owned=static_cast<uint32_t>(micros()-began);
  ++s_diagnostics.transactions;s_diagnostics.bytesTransferred+=sizeof(bytes);
  unlock_();recordProbe_(-2,sizeof(bytes),true,static_cast<uint32_t>(began-requested),owned);return true;
}
ProbeStats probeSnapshot() { PROBE_ENTER(); const auto copy = s_probe; PROBE_EXIT(); return copy; }
void probeTrafficBegin() {
  PROBE_ENTER();s_traffic=ProbeTrafficWindow{};
  s_traffic.startedUs=esp_timer_get_time();s_trafficActive=true;PROBE_EXIT();
}
ProbeTrafficWindow probeTrafficEnd() {
  PROBE_ENTER();s_traffic.endedUs=s_trafficActive?esp_timer_get_time():0;
  s_trafficActive=false;const auto copy=s_traffic;PROBE_EXIT();return copy;
}
#endif

}  // namespace SharedSpiBus
