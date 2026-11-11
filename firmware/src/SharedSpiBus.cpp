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
// Every nonnegative int8_t CS value has a stable slot; no eviction can erase
// another device's pacing origin. Access only under the shared bus mutex.
bool s_haveTransactionStart[128] = {};
#if defined(BODAQS_SPI_BOUNDARY_TRACE) && BODAQS_SPI_BOUNDARY_TRACE
uint32_t s_deviceSequence[128] = {};
#endif
uint32_t s_lastTransactionStartUs[128] = {};
#if defined(BODAQS_MEASUREMENT_REPLY_CAPTURE) && BODAQS_MEASUREMENT_REPLY_CAPTURE
SpiTransactionContext s_previousTransaction;
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
    uint32_t lockTimeoutMs,
    uint32_t minimumStartSpacingUs,
    uint32_t csSetupUs,
    SpiTransactionContext* context,
    SpiTransferTiming* timing) {
  if(context) *context={};
  if(timing) *timing={};
  if (!s_ready || csPin < 0 || length == 0 || (!tx && !rx)) return false;
  const auto cs = static_cast<uint8_t>(csPin);
  const uint32_t requestedUs=timing?micros():0;
  for (;;) {
    if (!lock_(lockTimeoutMs)) {
      if(timing) timing->lockWaitUs=micros()-requestedUs;
      return false;
    }
    if (minimumStartSpacingUs && s_haveTransactionStart[cs]) {
      const uint32_t elapsedUs = micros() - s_lastTransactionStartUs[cs];
      if (elapsedUs < minimumStartSpacingUs) {
        unlock_();
        // Other devices can use the bus during this device's quiet interval.
        // Recheck under the mutex: another caller may have used this same CS.
        delayMicroseconds(minimumStartSpacingUs - elapsedUs);
        continue;
      }
    }
    break;
  }
  const uint32_t acquiredUs=timing?micros():0;
  s_spi->beginTransaction(settings);
  digitalWrite(static_cast<uint8_t>(csPin), LOW);
  // Timestamp after asserting CS: preemption between GPIO and timestamp can
  // lengthen the following interval, but cannot make the next start too early.
  s_lastTransactionStartUs[cs] = micros();
  s_haveTransactionStart[cs] = true;
#if defined(BODAQS_MEASUREMENT_REPLY_CAPTURE) && BODAQS_MEASUREMENT_REPLY_CAPTURE
  SpiTransactionContext observed;
  observed.valid=true;observed.sequence=s_previousTransaction.sequence+1;
  observed.cs=csPin;observed.selectedUs=s_lastTransactionStartUs[cs];
  observed.bytes=length>UINT16_MAX?UINT16_MAX:static_cast<uint16_t>(length);
  observed.commandValid=tx!=nullptr;observed.command=tx?tx[0]:0;
  observed.previousValid=s_previousTransaction.valid;
  observed.previousCs=s_previousTransaction.cs;
  observed.previousReleaseUs=s_previousTransaction.releasedUs;
  observed.previousBytes=s_previousTransaction.bytes;
  observed.previousCommand=s_previousTransaction.command;
  observed.previousCommandValid=s_previousTransaction.commandValid;
#if defined(BODAQS_SPI_BOUNDARY_TRACE) && BODAQS_SPI_BOUNDARY_TRACE
  if(s_deviceSequence[cs]!=UINT32_MAX)++s_deviceSequence[cs];
  observed.deviceSequence=s_deviceSequence[cs];
  observed.deviceSequenceValid=s_deviceSequence[cs]!=UINT32_MAX;
#endif
#endif
  if(csSetupUs) delayMicroseconds(csSetupUs);
  const uint32_t preparedUs=timing?micros():0;
#if defined(ESP32)
  s_spi->transferBytes(tx, rx, length);
#else
  for (size_t index = 0; index < length; ++index) {
    const uint8_t received = s_spi->transfer(tx ? tx[index] : 0);
    if (rx) rx[index] = received;
  }
#endif
  const uint32_t transferredUs=timing?micros():0;
  digitalWrite(static_cast<uint8_t>(csPin), HIGH);
  s_spi->endTransaction();
#if defined(BODAQS_MEASUREMENT_REPLY_CAPTURE) && BODAQS_MEASUREMENT_REPLY_CAPTURE
  observed.releasedUs=micros();
  s_previousTransaction=observed;
  if(context) *context=observed;
#endif
  ++s_diagnostics.transactions;
  s_diagnostics.bytesTransferred += length;
  const uint32_t finishedUs=timing?micros():0;
  unlock_();
  // Publish only to the synchronous caller, after releasing the shared bus.
  if(timing) {
    timing->lockWaitUs=acquiredUs-requestedUs;
    timing->prepareUs=preparedUs-acquiredUs;
    timing->transferUs=transferredUs-preparedUs;
    timing->finishUs=finishedUs-transferredUs;
  }
  return true;
}

const Diagnostics& diagnostics() { return s_diagnostics; }

}  // namespace SharedSpiBus
