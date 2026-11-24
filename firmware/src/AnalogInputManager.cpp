#include "CpuOccupancy.h"
#include "AnalogInputManager.h"
#include "SharedSpiBus.h"
#include "AdcReadyWait.h"
#if BODAQS_ADC_ROW_PACING
#include "AdcRowSchedule.h"
#include "freertos/semphr.h"
#endif

#include <Arduino.h>
#include <SPI.h>
#include <string.h>
#include <atomic>
#include <new>

#include "ConfigManager.h"
#include "Rates.h"
#include "SensorTypes.h"
#include "DebugLog.h"
#include "esp_timer.h"

#if defined(ESP32)
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#if BODAQS_ADC_CONCENTRATED_SCAN_BENCH
#include "esp_heap_caps.h"
#endif
#endif

#define AIN_LOGE(...) LOGE_TAG("AIN", __VA_ARGS__)
#define AIN_LOGW(...) LOGW_TAG("AIN", __VA_ARGS__)
#define AIN_LOGI(...) LOGI_TAG("AIN", __VA_ARGS__)
#define AIN_LOGD(...) LOGD_TAG("AIN", __VA_ARGS__)

// The higher-priority mixed-load trial is selected only by its bench environment.
#ifndef BODAQS_ADC_TASK_PRIORITY
#define BODAQS_ADC_TASK_PRIORITY 2
#endif
#if defined(ESP32)
static_assert(BODAQS_ADC_TASK_PRIORITY > 0 && BODAQS_ADC_TASK_PRIORITY < configMAX_PRIORITIES,
              "ADC task priority must fit the FreeRTOS priority range");
#endif

namespace {
#if BODAQS_ADC_CONCENTRATED_SCAN_BENCH
static_assert(BODAQS_ADC_CONTINUOUS_LATEST, "Scan bench requires continuous baseline support");
bool s_scanSession=false;
#if BODAQS_ADC_COMBINED_CAPTURE
bool (*s_scanRowCapture)()=nullptr;
#endif
std::atomic<bool> s_scanFault{false};
std::atomic<bool> s_scanRun{false};
#if BODAQS_ADC_SCAN_ROW_PHASE
uint64_t s_scanRowAnchor=0; // Written once before release-valid; readers acquire-valid within row guard.
std::atomic<bool> s_scanRowAnchorValid{false};
#endif
// Prepared by startup before worker publication; immutable until retirement.
uint8_t s_scanRegisters[2][BODAQS_ADC_BOUNDARY_BENCH?4:2][4]={};
#if BODAQS_PRODUCTION_RECORDING
struct RecordingScanState {
  LocalAnalogRecordingPlan plan;
  AdcAcquisitionCadence::Due row;
  AnalogInputManager::CountPublisher publisher=nullptr;
};
RecordingScanState* s_recordingScan = nullptr; // Persistent, bounded START reservation.
#endif
#if defined(ESP32)
TaskHandle_t s_scanTask=nullptr; // Persistent, parked until priming completes.
#if BODAQS_ADC_BOUNDARY_BENCH
esp_timer_handle_t s_scanAppointmentTimer=nullptr;
void scanAppointmentWake_(void*) {if(s_scanTask)xTaskNotifyGive(s_scanTask);}
#endif
#endif
#endif
#if BODAQS_ADC_CONTINUOUS_LATEST
std::atomic<bool> s_continuousSession{false};
bool s_continuousHealthy=false;
uint8_t s_continuousChannels[board::BOARD_MAX_EXTERNAL_ADCS]={};
uint32_t s_continuousLastDataUs[board::BOARD_MAX_EXTERNAL_ADCS]={};
#endif

#if BODAQS_ADC_ROW_PACING
SemaphoreHandle_t rowGates[board::BOARD_MAX_EXTERNAL_ADCS]={};
esp_timer_handle_t rowTimer=nullptr;
std::atomic<bool> rowActive{false};
int64_t rowOrigin=0; // published by rowActive; changed only after worker retirement
void rowTick(void*) {
  if(!rowActive.load(std::memory_order_acquire))return;
  for(auto gate:rowGates)if(gate)xSemaphoreGive(gate);
}
#endif
constexpr uint8_t ADS1220_CMD_RESET = 0x06;
constexpr uint8_t ADS1220_CMD_START = 0x08;
constexpr uint8_t ADS1220_CMD_RDATA = 0x10;
constexpr uint8_t ADS1220_CMD_WREG  = 0x40;
constexpr uint8_t kInvalidChannel = 0xFF;
constexpr uint32_t kExternalAdcUtilizationPermille = 700;
constexpr uint32_t kFastDrdyPollMaxUs = 1500;
constexpr uint32_t kAsyncStopWaitMs = 100;
constexpr uint32_t kAsyncTaskStackBytes = 4096;
constexpr int64_t kAsyncMaxNoBlockUs = 50000;

struct AdsRateSetting {
  uint16_t sps;
  uint8_t drBits;
  uint8_t modeBits;
};

constexpr AdsRateSetting kAdsRates[] = {
  {20,   0, 0},
  {45,   1, 0},
  {90,   2, 0},
  {175,  3, 0},
  {330,  4, 0},
  {350,  3, 2},
  {600,  5, 0},
  {660,  4, 2},
  {1000, 6, 0},
  {1200, 5, 2},
  {2000, 6, 2},
};

struct AdsDevice {
  bool present = false;
  bool initialized = false;
  board::ExternalAdcProfile cfg;
  uint16_t dataRateSps = 20;
  uint8_t config1 = 0;
  bool channelUsed[4] = {false, false, false, false};
  uint8_t activeChannels = 0;
  int32_t cachedCounts[4] = {0, 0, 0, 0};
  bool cachedValid[4] = {false, false, false, false};
  uint32_t cachedSeq[4] = {0, 0, 0, 0};
  uint32_t lastRowSeq[4] = {0, 0, 0, 0};
  uint64_t cachedAcquiredUs[4] = {0, 0, 0, 0};
  bool cachedReadOk[4] = {false, false, false, false};
  uint32_t nextSeq[4] = {0, 0, 0, 0};
  uint8_t nextAsyncChannel = 0;
#if defined(ESP32)
  TaskHandle_t asyncTask = nullptr;
  TaskHandle_t drdyTask = nullptr;
  volatile bool asyncRun = false;
  volatile bool asyncRunning = false;
#endif
};

#if defined(ESP32)
portMUX_TYPE s_drdyMux = portMUX_INITIALIZER_UNLOCKED;

void ARDUINO_ISR_ATTR adsReadyIsr_(void* arg) {
  AdsDevice& dev = *static_cast<AdsDevice*>(arg);
  BaseType_t higherPriorityTaskWoken = pdFALSE;
  portENTER_CRITICAL_ISR(&s_drdyMux);
  if (dev.drdyTask) {
    vTaskNotifyGiveFromISR(dev.drdyTask, &higherPriorityTaskWoken);
  }
  portEXIT_CRITICAL_ISR(&s_drdyMux);
  if (higherPriorityTaskWoken) portYIELD_FROM_ISR();
}
#endif

const board::BoardProfile* s_board = nullptr;
AdsDevice s_ads[board::BOARD_MAX_EXTERNAL_ADCS];
bool s_spiReady = false;
bool s_inSample = false;
volatile bool s_asyncLoggingActive = false;
uint16_t s_requestedHz = 100;
uint16_t s_effectiveHz = 100;
ExternalAdcTimingStats s_timingStats;
// Publication of final worker statistics, independent of task-handle cleanup.
std::atomic<uint8_t> s_timingWorkers{0};
static_assert(board::BOARD_MAX_EXTERNAL_ADCS <= 8);

#if defined(ESP32)
portMUX_TYPE s_cacheMux = portMUX_INITIALIZER_UNLOCKED;
#endif

bool sensorUsesAnalogInput_(SensorType t) {
  switch (t) {
    case SensorType::AnalogPot:
    case SensorType::AS5600StringPotAnalog:
      return true;
    case SensorType::AS5600StringPotI2C:
    case SensorType::AS5600AngleI2C:
    case SensorType::AS5048BAngleI2C:
    case SensorType::DANF10NGps:
    case SensorType::Unknown:
    default:
      return false;
  }
}

SPISettings spiSettings_(const AdsDevice& dev) {
  const uint32_t boardDefaultHz = (s_board && s_board->spi.hz_default)
    ? s_board->spi.hz_default
    : 1000000UL;
  uint32_t hz = dev.cfg.spi_hz ? dev.cfg.spi_hz : boardDefaultHz;
#if BODAQS_ADC_CONCENTRATED_SCAN_BENCH
  // Exact scan-session override, including full startup priming and POWERDOWN.
  // Split continuous acquisition and all non-scan calls retain board settings.
  if(s_scanSession && (&dev==&s_ads[0] || (BODAQS_ADC_DUAL_SCAN_BENCH && &dev==&s_ads[1])))hz=BODAQS_ADC_SCAN_SPI_HZ;
#endif
  return SPISettings(hz, MSBFIRST, SPI_MODE1);
}

bool validAdcIndex_(uint8_t index) {
  return index < board::BOARD_MAX_EXTERNAL_ADCS && s_ads[index].present;
}

bool validChannel_(const AdsDevice& dev, uint8_t channel) {
  return channel < 4 && channel < dev.cfg.channel_count;
}

uint8_t muxCodeForSingleEnded_(uint8_t channel) {
  switch (channel) {
    case 0: return 0x08;
    case 1: return 0x09;
    case 2: return 0x0A;
    case 3: return 0x0B;
    default: return 0x08;
  }
}

uint8_t gainBits_(uint8_t gain) {
  switch (gain) {
    case 1: return 0;
    case 2: return 1;
    case 4: return 2;
    case 8: return 3;
    case 16: return 4;
    case 32: return 5;
    case 64: return 6;
    case 128: return 7;
    default: return 0;
  }
}

uint8_t referenceBits_(board::AdcReferenceType ref) {
  switch (ref) {
    case board::AdcReferenceType::ExternalRef0: return 1;
    case board::AdcReferenceType::ExternalRef1: return 2;
    case board::AdcReferenceType::AnalogSupply: return 3;
    case board::AdcReferenceType::Internal:
    case board::AdcReferenceType::Default:
    default:
      return 0;
  }
}

AdsRateSetting selectRate_(uint32_t requiredSps) {
  if (requiredSps < 1) requiredSps = 1;
  for (const auto& rate : kAdsRates) {
    if (rate.sps >= requiredSps) return rate;
  }
  return kAdsRates[sizeof(kAdsRates) / sizeof(kAdsRates[0]) - 1];
}

uint16_t snapDownRate_(uint16_t requestedHz, uint32_t maxHz) {
  if (requestedHz <= maxHz) return requestedHz;

  uint16_t best = 1;
  for (size_t i = 0; i < Rates::kCount; ++i) {
    if (Rates::kList[i] <= maxHz) best = Rates::kList[i];
  }
  return best;
}

uint32_t ceilDivU32_(uint32_t num, uint32_t den) {
  if (den == 0) return num;
  return (num + den - 1U) / den;
}

void resetTimingStats_() {
  s_timingStats = ExternalAdcTimingStats{};
  for (uint8_t adc = 0; adc < board::BOARD_MAX_EXTERNAL_ADCS && adc < ExternalAdcTimingStats::kMaxAdcs; ++adc) {
    const AdsDevice& dev = s_ads[adc];
    auto& stats = s_timingStats.adc[adc];
    stats.present = dev.present;
#if defined(ESP32)
    stats.asyncRunning = dev.asyncRunning;
#else
    stats.asyncRunning = false;
#endif
    stats.activeChannels = dev.activeChannels;
    stats.configuredSps = dev.dataRateSps;
  }
}

uint32_t adsMaxSps_(const AdsDevice& dev) {
  return dev.cfg.max_sps ? dev.cfg.max_sps : 1UL;
}

uint32_t usableLoggerHzForAdc_(const AdsDevice& dev, uint8_t activeChannels) {
  if (activeChannels == 0) return 0;
  #if BODAQS_ADC_BOUNDARY_BENCH
  if(AdcConcentratedScan::boundaryCase(activeChannels,s_requestedHz) && adsMaxSps_(dev)>=2000)return s_requestedHz;
#endif
  const uint32_t usableSps = (adsMaxSps_(dev) * kExternalAdcUtilizationPermille) / 1000UL;
  return (usableSps ? usableSps : 1UL) / activeChannels;
}

uint32_t targetDataRateSps_(uint16_t loggerHz, uint8_t activeChannels) {
#if BODAQS_PRODUCTION_RECORDING
  (void)loggerHz; (void)activeChannels;
  return 2000;
#endif
  #if BODAQS_ADC_BOUNDARY_BENCH
  if(AdcConcentratedScan::boundaryCase(activeChannels,loggerHz))return 2000;
#endif
  const uint32_t requiredSps = (uint32_t)loggerHz * (uint32_t)activeChannels;
  return ceilDivU32_(requiredSps * 1000UL, kExternalAdcUtilizationPermille);
}

bool adsTransfer_(AdsDevice& dev, const uint8_t* tx, uint8_t* rx, size_t len) {
#if BODAQS_ADC_SPI_PHASE_TIMING
  // Each ADC has one acquisition owner. Reset/final read use the existing
  // stopped-worker lifecycle; publish aggregates after the bus is released.
  SpiTransferTiming timing;
  const bool ok=SharedSpiBus::transfer(dev.cfg.cs_pin,spiSettings_(dev),tx,rx,len,50,0,0,nullptr,&timing);
  auto& adc=s_timingStats.adc[static_cast<size_t>(&dev-s_ads)];
  const bool setup=tx && ((len==6 && tx[0]==0x43 && tx[5]==ADS1220_CMD_START) ||
      (BODAQS_ADC_SCAN_MUX_ONLY && len==3 && tx[0]==0x40 && tx[2]==ADS1220_CMD_START));
  auto* phases=setup?&adc.setupSpi:
               ((tx && len==4 && tx[0]==ADS1220_CMD_RDATA) || (BODAQS_ADC_CONTINUOUS_LATEST && tx && (len==9 || (BODAQS_ADC_SCAN_PIPELINE && len==12)) && tx[0]==0x23))?&adc.readSpi:nullptr;
  if(phases) {
    if(ok) {
      const uint32_t values[]={timing.lockWaitUs,timing.prepareUs,timing.transferUs,timing.finishUs};
      for(unsigned i=0;i<4;++i) {
        phases->totalUs[i]+=values[i];
        if(values[i]>phases->maxUs[i]) phases->maxUs[i]=values[i];
      }
      ++phases->completed;
    } else {++phases->failed;phases->failedWaitUs+=timing.lockWaitUs;}
  }
  return ok;
#else
  return SharedSpiBus::transfer(
      dev.cfg.cs_pin, spiSettings_(dev), tx, rx, len);
#endif
}

bool adsCommand_(AdsDevice& dev, uint8_t cmd) {
  if (!dev.present || dev.cfg.cs_pin < 0 || !s_spiReady) return false;
  // ESP32 transferBytes reads complete uint32_t source words, even when the
  // selected wire length is shorter. Retain a full aligned backing word.
  alignas(4) const uint8_t tx[4] = {cmd, 0, 0, 0};
  return adsTransfer_(dev, tx, nullptr, 1);
}

bool adsWriteRegistersAndStart_(AdsDevice& dev, uint8_t startReg, const uint8_t* regs, size_t len) {
  if (!dev.present || !regs || len == 0 || len > 4 || !s_spiReady) return false;

  // Six wire bytes still cause two source-word reads in the ESP32 HAL.
  alignas(4) uint8_t tx[8] = {0};
  tx[0] = (uint8_t)(ADS1220_CMD_WREG | ((startReg & 0x03U) << 2) | ((len - 1U) & 0x03U));
  for (size_t i = 0; i < len; ++i) tx[i + 1] = regs[i];
  tx[len + 1] = ADS1220_CMD_START;

  // WREG consumes its declared register bytes; START is the next command.
  // Keep explicit START (required by the physical control) in the same CS span.
  return adsTransfer_(dev, tx, nullptr, len + 2);
}

bool adsReadData_(AdsDevice& dev, int32_t& raw24) {
  if (!dev.present || !s_spiReady) return false;

  alignas(4) uint8_t tx[4] = { ADS1220_CMD_RDATA, 0x00, 0x00, 0x00 };
  alignas(4) uint8_t rx[4] = {0};

  if (!adsTransfer_(dev, tx, rx, sizeof(tx))) return false;

  int32_t v = ((int32_t)rx[1] << 16) | ((int32_t)rx[2] << 8) | rx[3];
  if (v & 0x00800000L) v |= 0xFF000000L;
  raw24 = v;
  return true;
}

bool adsWaitReady_(const AdsDevice& dev, uint32_t timeoutUs,
                   uint32_t* elapsedUs = nullptr,
                   bool* readyImmediately = nullptr) {
  if (elapsedUs) *elapsedUs = 0;
  if (readyImmediately) *readyImmediately = false;
  if (dev.cfg.drdy_pin < 0) {
    const uint32_t t0 = micros();
    delay((timeoutUs + 999UL) / 1000UL);
    if (elapsedUs) *elapsedUs = (uint32_t)(micros() - t0);
    return true;
  }

  const int readyLevel = dev.cfg.drdy_active_low ? LOW : HIGH;
  const uint32_t start = micros();
#if defined(ESP32)
  if (dev.drdyTask == xTaskGetCurrentTaskHandle()) {
    // A notification received before entering the wait remains pending. Check
    // the level too, so an already-completed conversion needs no new edge.
    const auto result = AdcReadyWait::wait(
        timeoutUs, []() { return micros(); },
        [&]() { return digitalRead((uint8_t)dev.cfg.drdy_pin) == readyLevel; },
        [](uint32_t remainingUs) {
          // Round up: sub-millisecond conversions must really block.
          (void)ulTaskNotifyTake(pdTRUE, static_cast<TickType_t>(
              AdcReadyWait::timeoutTicks(remainingUs, configTICK_RATE_HZ)));
        });
    if (elapsedUs) *elapsedUs = result.elapsedUs;
    if (readyImmediately) *readyImmediately = result.ready && result.elapsedUs < 25UL;
    return result.ready;
  }
#endif
  const uint16_t sps = dev.dataRateSps ? dev.dataRateSps : 20;
  uint32_t fastPollUs = (1000000UL / sps) + 250UL;
  if (fastPollUs > kFastDrdyPollMaxUs) fastPollUs = kFastDrdyPollMaxUs;

  while ((uint32_t)(micros() - start) < timeoutUs) {
    const uint32_t elapsedAtTop = (uint32_t)(micros() - start);
    if (digitalRead((uint8_t)dev.cfg.drdy_pin) == readyLevel) {
      if (elapsedUs) *elapsedUs = (uint32_t)(micros() - start);
      if (readyImmediately && elapsedAtTop < 25UL) *readyImmediately = true;
      return true;
    }
    const uint32_t elapsed = (uint32_t)(micros() - start);
    if (elapsed < fastPollUs) {
      delayMicroseconds(20);
    } else {
#if defined(ESP32)
      vTaskDelay(1);
#else
      delay(1);
#endif
    }
  }
  if (elapsedUs) *elapsedUs = (uint32_t)(micros() - start);
  return false;
}

int32_t scaleRaw24ToEffectiveBits_(int32_t raw24, uint8_t bits) {
  if (bits < 1) bits = 12;
  if (bits > 23) bits = 23;

  if (raw24 < 0) raw24 = 0;
  if (raw24 > 0x7FFFFF) raw24 = 0x7FFFFF;

  const uint32_t maxOut = (1UL << bits) - 1UL;
  const uint64_t scaled = ((uint64_t)(uint32_t)raw24 * maxOut + 0x3FFFFFULL) / 0x7FFFFFULL;
  return (int32_t)scaled;
}

void adsChannelRegisters_(const AdsDevice& dev,uint8_t channel,uint8_t (&regs)[4]) {
  regs[0]=static_cast<uint8_t>((muxCodeForSingleEnded_(channel)<<4) |
      ((gainBits_(dev.cfg.gain)&0x07U)<<1) | (dev.cfg.pga_bypass?1U:0U));
  regs[1]=dev.config1;
  regs[2]=static_cast<uint8_t>((referenceBits_(dev.cfg.reference)&0x03U)<<6);
  regs[3]=0;
}
bool configureAndStartAdsChannel_(AdsDevice& dev,uint8_t channel) {
  if(!validChannel_(dev,channel))return false;
  uint8_t regs[4];adsChannelRegisters_(dev,channel,regs);
  // Single-shot baseline retains full configuration and explicit START.
  return adsWriteRegistersAndStart_(dev,0,regs,sizeof(regs));
}

uint32_t conversionTimeoutUs_(const AdsDevice& dev) {
  const uint16_t sps = dev.dataRateSps ? dev.dataRateSps : 20;
  return (1000000UL / sps) + 5000UL;
}

bool readAdsChannelLive_(uint8_t adcIndex, uint8_t channel, int32_t& outCounts) {
  if (!validAdcIndex_(adcIndex)) return false;
  AdsDevice& dev = s_ads[adcIndex];
  if (!dev.initialized || !validChannel_(dev, channel)) return false;
  auto& adcStats = s_timingStats.adc[adcIndex];
#if BODAQS_TIMING_INSTRUMENTATION
  const uint32_t channelT0 = micros();

  uint32_t t0 = micros();
#endif
#if defined(ESP32)
  if (dev.drdyTask == xTaskGetCurrentTaskHandle()) {
    // The combined transfer starts conversion: discard old notification first,
    // never afterwards, which could lose a fast completion.
    (void)ulTaskNotifyTake(pdTRUE, 0);
  }
#endif
  if (!configureAndStartAdsChannel_(dev, channel)) return false;
#if BODAQS_TIMING_INSTRUMENTATION
  // configUs now covers both setup and conversion start; no separate startUs.
  TimingStats_record(adcStats.configUs, (uint32_t)(micros() - t0));
#endif

  uint32_t waitUs = 0;
  bool readyImmediately = false;
  const bool ready = adsWaitReady_(dev, conversionTimeoutUs_(dev), &waitUs, &readyImmediately);
#if BODAQS_TIMING_INSTRUMENTATION
  TimingStats_record(adcStats.waitUs, waitUs);
  TimingStats_record(adcStats.channel[channel].waitUs, waitUs);
  if (readyImmediately) ++adcStats.drdyAlreadyReady;
#endif
  if (!ready) {
#if BODAQS_TIMING_INSTRUMENTATION
    ++adcStats.waitTimeouts;
#endif
    AIN_LOGW("ADS%u channel%u DRDY timeout\n", (unsigned)adcIndex, (unsigned)channel);
    return false;
  }

  int32_t raw24 = 0;
#if BODAQS_TIMING_INSTRUMENTATION
  t0 = micros();
#endif
  if (!adsReadData_(dev, raw24)) return false;
#if BODAQS_TIMING_INSTRUMENTATION
  TimingStats_record(adcStats.readUs, (uint32_t)(micros() - t0));
#endif
  outCounts = scaleRaw24ToEffectiveBits_(raw24, dev.cfg.effective_bits);
#if BODAQS_TIMING_INSTRUMENTATION
  TimingStats_record(adcStats.channel[channel].totalUs, (uint32_t)(micros() - channelT0));
#endif
  return true;
}

const board::AnalogInputHW* inputForAin_(uint8_t ain) {
  if (!s_board || ain >= s_board->analog.count || ain >= board::BOARD_MAX_ANALOG_INPUTS) {
    return nullptr;
  }
  return &s_board->analog.inputs[ain];
}

bool analogInputAvailable_(const board::AnalogInputHW& input) {
  switch (input.source) {
    case board::AnalogSourceType::InternalGpio:
      return input.pin >= 0;
    case board::AnalogSourceType::ExternalAdc:
      return validAdcIndex_(input.external_adc_index) &&
             validChannel_(s_ads[input.external_adc_index], input.external_channel);
    case board::AnalogSourceType::None:
    default:
      return false;
  }
}

uint8_t nthActiveChannel_(const AdsDevice& dev, uint8_t ordinal) {
  uint8_t seen = 0;
  for (uint8_t ch = 0; ch < 4; ++ch) {
    if (!dev.channelUsed[ch]) continue;
    if (seen == ordinal) return ch;
    ++seen;
  }
  return kInvalidChannel;
}

uint8_t nextActiveChannel_(AdsDevice& dev) {
  for (uint8_t i = 0; i < 4; ++i) {
    const uint8_t ch = (uint8_t)((dev.nextAsyncChannel + i) % 4);
    if (!dev.channelUsed[ch]) continue;
    dev.nextAsyncChannel = (uint8_t)((ch + 1) % 4);
    return ch;
  }
  return kInvalidChannel;
}

bool anyActiveExternalAdc_() {
  for (const auto& dev : s_ads) {
    if (dev.present && dev.initialized && dev.activeChannels > 0) return true;
  }
  return false;
}

struct CachedAdcSample {
  bool valid = false;
  int32_t counts = 0;
  uint32_t seq = 0;
  uint64_t acquiredUs = 0;
};
#if BODAQS_ADC_ROW_HANDOFF
const LocalAdcSnapshot* s_rowSnapshot = nullptr;
TaskHandle_t s_rowSnapshotOwner = nullptr;
#endif

void clearCachedSamples_() {
#if defined(ESP32)
  portENTER_CRITICAL(&s_cacheMux);
#endif
  for (auto& dev : s_ads) {
    for (uint8_t ch = 0; ch < 4; ++ch) {
      dev.cachedValid[ch] = false;
      dev.cachedCounts[ch] = 0;
      dev.cachedSeq[ch] = 0;
      dev.lastRowSeq[ch] = 0;
      dev.cachedAcquiredUs[ch] = 0;
      dev.cachedReadOk[ch] = false;
      dev.nextSeq[ch] = 0;
    }
    dev.nextAsyncChannel = 0;
  }
#if defined(ESP32)
  portEXIT_CRITICAL(&s_cacheMux);
#endif
}

void publishCachedSample_(uint8_t adcIndex, uint8_t channel, int32_t counts, bool ok) {
  if (!validAdcIndex_(adcIndex) || channel >= 4) return;
  AdsDevice& dev = s_ads[adcIndex];
#if defined(ESP32)
  portENTER_CRITICAL(&s_cacheMux);
#endif
  if (ok) {
    dev.cachedCounts[channel] = counts;
    dev.cachedValid[channel] = true;
    dev.cachedSeq[channel] = ++dev.nextSeq[channel];
    dev.cachedAcquiredUs[channel] = (uint64_t)esp_timer_get_time();
  }
  dev.cachedReadOk[channel] = ok;
#if defined(ESP32)
  portEXIT_CRITICAL(&s_cacheMux);
#endif
}

bool copyCachedSample_(uint8_t adcIndex, uint8_t channel, CachedAdcSample& out) {
  if (!validAdcIndex_(adcIndex) || channel >= 4) return false;
  const AdsDevice& dev = s_ads[adcIndex];
#if defined(ESP32)
  portENTER_CRITICAL(&s_cacheMux);
#endif
  out.valid = dev.cachedValid[channel];
  out.counts = dev.cachedCounts[channel];
  out.seq = dev.cachedSeq[channel];
  out.acquiredUs = dev.cachedAcquiredUs[channel];
#if defined(ESP32)
  portEXIT_CRITICAL(&s_cacheMux);
#endif
  return out.valid;
}

void recordCachedRowUse_(uint8_t adcIndex, uint8_t channel, bool haveSample, bool fresh, uint32_t ageUs) {
#if BODAQS_TIMING_INSTRUMENTATION
  if (adcIndex >= ExternalAdcTimingStats::kMaxAdcs ||
      channel >= ExternalAdcTimingStats::kMaxChannels) {
    return;
  }

  auto& chStats = s_timingStats.adc[adcIndex].channel[channel];
  ++chStats.rowUses;
  if (!haveSample) {
    ++chStats.rowNoSample;
    return;
  }
  if (fresh) ++chStats.rowFresh;
  else ++chStats.rowReused;
  TimingStats_record(chStats.rowAgeUs, ageUs);
#else
  (void)adcIndex;
  (void)channel;
  (void)haveSample;
  (void)fresh;
  (void)ageUs;
#endif
}

bool acquireAndPublishChannel_(uint8_t adcIndex, uint8_t channel) {
  int32_t counts = 0;
  const bool ok = readAdsChannelLive_(adcIndex, channel, counts);
  publishCachedSample_(adcIndex, channel, counts, ok);

#if BODAQS_TIMING_INSTRUMENTATION
  if (adcIndex < ExternalAdcTimingStats::kMaxAdcs &&
      channel < ExternalAdcTimingStats::kMaxChannels) {
    auto& chStats = s_timingStats.adc[adcIndex].channel[channel];
    if (ok) ++chStats.acquireOk;
    else ++chStats.acquireFail;
  }
#endif

  return ok;
}

#if BODAQS_ADC_CONCENTRATED_SCAN_BENCH
bool concentratedScope_() {
#if BODAQS_PRODUCTION_RECORDING
  if (!s_recordingScan || s_recordingScan->plan.rateHz() != s_effectiveHz) return false;
  for (unsigned adc = 0; adc < 2; ++adc) {
    if (!s_recordingScan->plan.mask(adc)) continue;
    const auto& dev = s_ads[adc];
    if (!dev.present || !dev.initialized || dev.dataRateSps != 2000 || dev.cfg.drdy_pin < 0) return false;
  }
  return true;
#else
  const auto& a=s_ads[0];const auto& b=s_ads[1];
#if BODAQS_ADC_BOUNDARY_BENCH
  if(!AdcConcentratedScan::boundaryCase(a.activeChannels,s_effectiveHz) || b.activeChannels!=a.activeChannels)return false;
  for(unsigned adc=0;adc<2;++adc) {
    const auto& dev=s_ads[adc];
    if(!dev.present || !dev.initialized || dev.dataRateSps!=2000 || dev.cfg.drdy_pin<0)return false;
    for(unsigned ch=0;ch<4;++ch)if(dev.channelUsed[ch]!=(ch<a.activeChannels))return false;
  }
  return true;
#else
  const bool second= !b.activeChannels || (BODAQS_ADC_DUAL_SCAN_BENCH &&
      b.present && b.initialized && b.activeChannels==2 && b.channelUsed[0] && b.channelUsed[1] &&
      b.dataRateSps==2000 && b.cfg.drdy_pin>=0);
  return a.present && a.initialized && a.activeChannels==2 && a.channelUsed[0] && a.channelUsed[1] &&
     a.dataRateSps==2000 && a.cfg.drdy_pin>=0 && second && s_effectiveHz==500;
#endif
#endif
}
// Configuration is immutable from reservation/prime through owner retirement.
unsigned scanAdcCount_() {
#if BODAQS_PRODUCTION_RECORDING
  return 2;
#else
  return BODAQS_ADC_DUAL_SCAN_BENCH && s_ads[1].activeChannels ? 2u : 1u;
#endif
}
unsigned scanChannelCount_() {
#if BODAQS_PRODUCTION_RECORDING
  return s_recordingScan ? (s_recordingScan->plan.channels(0) > s_recordingScan->plan.channels(1)
      ? s_recordingScan->plan.channels(0) : s_recordingScan->plan.channels(1)) : 0;
#else
  return BODAQS_ADC_BOUNDARY_BENCH?s_ads[0].activeChannels:2u;
#endif
}
void scanMemory_(const char* stage) {
#if defined(ESP32)
  AIN_LOGI("scan memory stage=%s internal_free=%u internal_largest=%u dma_free=%u dma_largest=%u\n",
      stage,(unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
      (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
      (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_DMA),
      (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_DMA));
#endif
}
bool concentratedAcquire_(uint8_t channel,bool prime=false,uint8_t adc=0) {
  auto& dev=s_ads[adc];auto& stats=s_timingStats.adc[adc];
  const uint32_t began=micros();++stats.scanStarts;
  if(!validChannel_(dev,channel) || !dev.channelUsed[channel]) {
    ++stats.scanReadFailures;s_scanFault.store(true);return false;
  }
#if defined(ESP32)
  if(dev.drdyTask==xTaskGetCurrentTaskHandle())(void)ulTaskNotifyTake(pdTRUE,0);
#endif
  uint32_t tick=micros();
  // Both startup primes write/verify the complete image. Runtime changes only
  // register0 (MUX plus the retained gain/PGA bits); START stays explicit.
  const bool shortWrite=BODAQS_ADC_SCAN_MUX_ONLY && !prime;
  if(!adsWriteRegistersAndStart_(dev,0,s_scanRegisters[adc][channel],shortWrite?1:4)) {
    ++stats.scanReadFailures;++stats.channel[channel].acquireFail;s_scanFault.store(true);return false;
  }
  TimingStats_record(stats.configUs,micros()-tick);
  uint32_t waited=0;
  if(!adsWaitReady_(dev,conversionTimeoutUs_(dev),&waited)) {
#if defined(ESP32)
    if(!s_scanRun.load() && dev.drdyTask)return false; // STOP, not a conversion fault.
#endif
    ++stats.scanWaitTimeouts;++stats.waitTimeouts;++stats.channel[channel].acquireFail;
    s_scanFault.store(true);return false;
  }
#if defined(ESP32)
  if(!s_scanRun.load() && dev.drdyTask)return false;
#endif
  TimingStats_record(stats.waitUs,waited);TimingStats_record(stats.channel[channel].waitUs,waited);
  // Single-shot conversion is stopped with its result latched. Verify the full
  // selected-channel register image before attributing the result to this cache.
  alignas(4) const uint8_t tx[12]={0x23,0,0,0,0,ADS1220_CMD_RDATA,0,0,0,0,0,0};
  alignas(4) uint8_t rx[12]={};const auto& expected=s_scanRegisters[adc][channel];
  tick=micros();
  if(!adsTransfer_(dev,tx,rx,9)) {
    ++stats.scanReadFailures;++stats.channel[channel].acquireFail;s_scanFault.store(true);return false;
  }
  if(memcmp(rx+1,expected,4)!=0) {
    ++stats.scanConfigFaults;++stats.channel[channel].acquireFail;s_scanFault.store(true);return false;
  }
  int32_t raw=(int32_t(rx[6])<<16)|(int32_t(rx[7])<<8)|rx[8];
  if(raw&0x00800000L)raw|=static_cast<int32_t>(0xFF000000UL);
  publishCachedSample_(adc,channel,scaleRaw24ToEffectiveBits_(raw,dev.cfg.effective_bits),true);
  ++stats.scanReads;++stats.channel[channel].acquireOk;
  TimingStats_record(stats.readUs,micros()-tick);
  TimingStats_record(stats.channel[channel].totalUs,micros()-began);return true;
}
#if defined(ESP32)
#if BODAQS_ADC_SCAN_PIPELINE
bool concentratedExchange_(uint8_t channel,uint8_t adc=0) {
  auto& dev=s_ads[adc];auto& stats=s_timingStats.adc[adc];uint32_t waited=0;
  if(!adsWaitReady_(dev,conversionTimeoutUs_(dev),&waited)) {
    if(!s_scanRun.load())return false;
    ++stats.scanWaitTimeouts;++stats.waitTimeouts;++stats.channel[channel].acquireFail;s_scanFault=true;return false;
  }
  if(!s_scanRun.load())return false;
  TimingStats_record(stats.waitUs,waited);TimingStats_record(stats.channel[channel].waitUs,waited);
#if BODAQS_PRODUCTION_RECORDING
  const uint8_t next = s_recordingScan->plan.nextChannel(adc, channel);
#else
  const uint8_t next=static_cast<uint8_t>((channel+1u)%scanChannelCount_());
#endif
  alignas(4) const uint8_t tx[12]={0x23,0,0,0,0,ADS1220_CMD_RDATA,0,0,0,0x40,s_scanRegisters[adc][next][0],ADS1220_CMD_START};
  alignas(4) uint8_t rx[12]={};
  (void)ulTaskNotifyTake(pdTRUE,0); // Old readiness cleared before the next START.
  const uint32_t began=micros();++stats.scanStarts;
  if(!adsTransfer_(dev,tx,rx,12)) {++stats.scanReadFailures;++stats.channel[channel].acquireFail;s_scanFault=true;return false;}
  ++stats.scanCombinedCalls;
  // The next conversion may already run, but an invalid previous image never
  // authorizes publication. STOP also suppresses this result; retirement follows.
  if(memcmp(rx+1,s_scanRegisters[adc][channel],4)) {++stats.scanConfigFaults;++stats.channel[channel].acquireFail;s_scanFault=true;return false;}
  if(!s_scanRun.load())return false;
  int32_t raw=(int32_t(rx[6])<<16)|(int32_t(rx[7])<<8)|rx[8];
  if(raw&0x00800000L)raw|=static_cast<int32_t>(0xFF000000UL);
  publishCachedSample_(adc,channel,scaleRaw24ToEffectiveBits_(raw,dev.cfg.effective_bits),true);
  ++stats.scanReads;++stats.channel[channel].acquireOk;
  TimingStats_record(stats.readUs,micros()-began);
  TimingStats_record(stats.channel[channel].totalUs,micros()-began+waited);return true;
}
#endif
#if BODAQS_ADC_BOUNDARY_BENCH
void waitScanAppointment_(uint64_t deadlineUs) {
  auto& stats=s_timingStats.scanAppointmentWait;
  const uint64_t began=static_cast<uint64_t>(esp_timer_get_time());
  ++stats.episodes;
  (void)esp_timer_stop(s_scanAppointmentTimer);
  // Stopping the old timer can consume the remaining interval. Use a fresh
  // clock reading, never the remaining duration calculated by the caller.
  const uint64_t now=static_cast<uint64_t>(esp_timer_get_time());
  if(!s_scanRun.load() || s_scanFault.load()) {
    ++stats.cancelledWakes;
  } else if(now>=deadlineUs) {
    ++stats.elapsedBeforeArm;
  } else {
    ++stats.armAttempts;
    if(esp_timer_start_once(s_scanAppointmentTimer,deadlineUs-now)!=ESP_OK) {
      ++stats.armFailures;s_scanFault=true;
    } else {
      // DRDY and stale callbacks are wake hints. Keep this appointment armed
      // until its absolute deadline or cancellation; an early hint cannot
      // authorize a conversion read or postpone the deadline.
      while(s_scanRun.load() && !s_scanFault.load() &&
            static_cast<uint64_t>(esp_timer_get_time())<deadlineUs) {
        (void)ulTaskNotifyTake(pdTRUE,portMAX_DELAY);
        if(!s_scanRun.load() || s_scanFault.load())++stats.cancelledWakes;
        else if(static_cast<uint64_t>(esp_timer_get_time())<deadlineUs)++stats.earlyWakes;
        else ++stats.dueWakes;
      }
    }
  }
  (void)esp_timer_stop(s_scanAppointmentTimer);
  const uint32_t elapsed=static_cast<uint32_t>(static_cast<uint64_t>(esp_timer_get_time())-began);
  stats.totalUs+=elapsed;
  if(elapsed>stats.maxUs)stats.maxUs=elapsed;
}
#endif
void concentratedTask_(void*) {
#if BODAQS_PRODUCTION_RECORDING
  for (;;) {
    (void)ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    if (!(s_timingWorkers.load(std::memory_order_acquire) & 1u)) continue;
    uint8_t pending[2] = {255, 255};
    for (unsigned adc = 0; adc < 2; ++adc) {
      if (!s_recordingScan->plan.mask(adc)) continue;
      auto& dev = s_ads[adc];
      pending[adc] = s_recordingScan->plan.firstChannel(adc);
      portENTER_CRITICAL(&s_drdyMux);
      dev.drdyTask = xTaskGetCurrentTaskHandle();
      portEXIT_CRITICAL(&s_drdyMux);
      attachInterruptArg(uint8_t(dev.cfg.drdy_pin), adsReadyIsr_, &dev,
                         dev.cfg.drdy_active_low ? FALLING : RISING);
      dev.asyncRunning = true; s_timingStats.adc[adc].asyncRunning = true;
      if (s_scanRun.load() && !adsWriteRegistersAndStart_(dev, 0, s_scanRegisters[adc][pending[adc]], 1))
        s_scanFault.store(true);
    }
    AdcAcquisitionCadence cadence;
    if (!cadence.begin(s_recordingScan->plan, static_cast<uint64_t>(esp_timer_get_time())))
      s_scanFault.store(true);
    while (s_scanRun.load() && !s_scanFault.load()) {
      const uint64_t now = static_cast<uint64_t>(esp_timer_get_time());
      const auto due = cadence.claim(now);
      for (unsigned adc = 0; adc < 2; ++adc) {
        if (!(due.adcMask & (1u << adc))) continue;
        auto& stats = s_timingStats.adc[adc];
        stats.scanMissedAppointments += due.missed[adc];
        if (!concentratedExchange_(pending[adc], adc)) break;
        pending[adc] = s_recordingScan->plan.nextChannel(adc, pending[adc]);
      }
      if (!s_scanRun.load() || s_scanFault.load()) break;
      if (due.row && s_scanRowCapture) {
        s_recordingScan->row = due;
        if (!s_scanRowCapture()) { s_scanFault.store(true); break; }
      }
      waitScanAppointment_(due.nextUs);
    }
    (void)esp_timer_stop(s_scanAppointmentTimer);
    for (unsigned adc = 0; adc < 2; ++adc) {
      if (!s_recordingScan->plan.mask(adc)) continue;
      auto& dev = s_ads[adc];
      detachInterrupt(uint8_t(dev.cfg.drdy_pin));
      portENTER_CRITICAL(&s_drdyMux); dev.drdyTask = nullptr; portEXIT_CRITICAL(&s_drdyMux);
      dev.asyncRunning = false; dev.asyncTask = nullptr;
      s_timingStats.adc[adc].asyncRunning = false;
    }
    s_scanRun.store(false);
    s_timingWorkers.fetch_and(static_cast<uint8_t>(~1u), std::memory_order_release);
  }
#else

  static_assert(configTICK_RATE_HZ>=1000 && configTICK_RATE_HZ%1000==0,"Scan bench requires integral 1ms ticks");
  for(;;) {
    // Notifications wake this persistent owner for a new session and for DRDY.
    // A stale notification alone cannot start work. After retirement, no cache,
    // device or timing state is touched until a newly primed session is published.
    (void)ulTaskNotifyTake(pdTRUE,portMAX_DELAY);
    // A session canceled before this first wake still owns the retirement bit.
    // Enter its cleanup even with run=false, or STOP could wait forever.
    if(!(s_timingWorkers.load(std::memory_order_acquire)&1u))continue;
    const unsigned adcCount=scanAdcCount_();
    for(unsigned adc=0;adc<adcCount;++adc) {
      auto& dev=s_ads[adc];
      portENTER_CRITICAL(&s_drdyMux);dev.drdyTask=xTaskGetCurrentTaskHandle();portEXIT_CRITICAL(&s_drdyMux);
      attachInterruptArg(uint8_t(dev.cfg.drdy_pin),adsReadyIsr_,&dev,dev.cfg.drdy_active_low?FALLING:RISING);
      dev.asyncRunning=true;s_timingStats.adc[adc].asyncRunning=true;
    }
    uint32_t next=xTaskGetTickCount();
#if BODAQS_ADC_BOUNDARY_BENCH
    const uint32_t rowUs=Rates::periodUs(s_effectiveHz);
    const unsigned channelCount=scanChannelCount_();
    const bool tickCadence=AdcConcentratedScan::usesTickCadence(rowUs,channelCount);
    uint64_t nextUs=static_cast<uint64_t>(esp_timer_get_time())+rowUs/channelCount;
    unsigned cadenceRemainder=rowUs%channelCount;
#endif
#if BODAQS_ADC_SCAN_PIPELINE
    next+=configTICK_RATE_HZ/1000;bool seeded=false;uint8_t pending=0;
#endif
    while(s_scanRun.load() && !s_scanFault.load()) {
#if BODAQS_ADC_BOUNDARY_BENCH
      uint32_t missed=0,lagUs=0;
      if(!tickCadence) {
        const auto a=AdcConcentratedScan::claimMicros(static_cast<uint64_t>(esp_timer_get_time()),nextUs,rowUs,channelCount,cadenceRemainder);
        if(a.waitUs) {
          waitScanAppointment_(nextUs);
          continue;
        }
        missed=a.missed;lagUs=a.lagUs;
      } else {
        const auto a=AdcConcentratedScan::claim(xTaskGetTickCount(),next,configTICK_RATE_HZ/1000);
        if(a.waitTicks){vTaskDelay(a.waitTicks);continue;}
        missed=a.missed;lagUs=a.lagTicks*1000u;
      }
#else
      const auto appointment=AdcConcentratedScan::claim(xTaskGetTickCount(),next,configTICK_RATE_HZ/1000);
      if(appointment.waitTicks){vTaskDelay(appointment.waitTicks);continue;}
#endif
      for(unsigned adc=0;adc<adcCount;++adc) {
        auto& stats=s_timingStats.adc[adc];
#if BODAQS_ADC_BOUNDARY_BENCH
        stats.scanMissedAppointments+=missed;
        if(lagUs>stats.scanMaximumLagUs)stats.scanMaximumLagUs=lagUs;
        if(lagUs/1000u>stats.scanMaximumLagTicks)stats.scanMaximumLagTicks=lagUs/1000u;
#else
        stats.scanMissedAppointments+=appointment.missed;
        if(appointment.lagTicks>stats.scanMaximumLagTicks)stats.scanMaximumLagTicks=appointment.lagTicks;
#endif
      }
      const uint32_t began=micros();
#if BODAQS_ADC_SCAN_PIPELINE
      if(!seeded) {
        for(unsigned adc=0;adc<adcCount && s_scanRun.load();++adc) {
          auto& stats=s_timingStats.adc[adc];const uint32_t seedBegan=micros();
          (void)ulTaskNotifyTake(pdTRUE,0);++stats.scanStarts;
          if(!adsWriteRegistersAndStart_(s_ads[adc],0,s_scanRegisters[adc][0],1)) {++stats.scanReadFailures;++stats.channel[0].acquireFail;s_scanFault=true;break;}
          TimingStats_record(stats.configUs,micros()-seedBegan);
        }
        if(s_scanFault.load() || !s_scanRun.load())break;
        seeded=true;
      } else {
        bool complete=true;
        for(unsigned adc=0;adc<adcCount;++adc) {
          if(!concentratedExchange_(pending,adc)) {complete=false;break;}
        }
        // No partial four-channel row after either device fails or STOP wins.
        if(!complete)break;
        #if BODAQS_ADC_SCAN_ROW_PHASE
        if(!s_scanRowAnchorValid.load(std::memory_order_acquire)) {
          s_scanRowAnchor=static_cast<uint64_t>(esp_timer_get_time());
          s_scanRowAnchorValid.store(true,std::memory_order_release);
        }
#endif
#if BODAQS_ADC_COMBINED_CAPTURE
        // Every active ADC has a new verified pair. Their next channel0
        // conversions are running; capture copies all owned values once.
        if(pending+1u==scanChannelCount_() && s_scanRun.load() && s_scanRowCapture && !s_scanRowCapture()) {
          s_scanFault.store(true);break;
        }
#endif
        pending=static_cast<uint8_t>((pending+1u)%scanChannelCount_());
      }
#else
      auto& dev=s_ads[0];const uint8_t channel=nextActiveChannel_(dev);
      if(!concentratedAcquire_(channel))break;
#endif
      // One shared owner iteration: duplicated per-device wall scope, not
      // additive CPU time when both ADCs participate.
      const uint32_t ownerElapsed=micros()-began;
      for(unsigned adc=0;adc<adcCount;++adc)TimingStats_record(s_timingStats.adc[adc].asyncLoopUs,ownerElapsed);
    }
#if BODAQS_ADC_BOUNDARY_BENCH
    (void)esp_timer_stop(s_scanAppointmentTimer);
#endif
    for(unsigned adc=0;adc<adcCount;++adc) {
      auto& dev=s_ads[adc];detachInterrupt(uint8_t(dev.cfg.drdy_pin));
      portENTER_CRITICAL(&s_drdyMux);dev.drdyTask=nullptr;portEXIT_CRITICAL(&s_drdyMux);
      dev.asyncRunning=false;s_timingStats.adc[adc].asyncRunning=false;dev.asyncTask=nullptr;
    }
    s_scanRun.store(false);
    s_timingWorkers.fetch_and(static_cast<uint8_t>(~1u),std::memory_order_release);
  }
#endif
}
#endif
bool concentratedStart_() {
  if(!concentratedScope_() || s_timingWorkers.load())return false;
#if defined(ESP32)
  if(!s_scanTask) {AIN_LOGE("scan start refused stage=worker_not_reserved\n");return false;}
#endif
  #if BODAQS_ADC_SCAN_ROW_PHASE
  s_scanRowAnchorValid.store(false,std::memory_order_release);
#endif
  s_scanSession=true;s_scanFault.store(false);
  const unsigned adcCount=scanAdcCount_();
  for(unsigned adc=0;adc<adcCount;++adc) {
    if (!s_ads[adc].activeChannels) continue;
    s_timingStats.adc[adc].concentratedScan=true;
#if BODAQS_ADC_BOUNDARY_BENCH
    s_timingStats.adc[adc].scanRowPeriodUs=Rates::periodUs(s_effectiveHz);
#endif
    for(uint8_t channel=0;channel<4;++channel)if(s_ads[adc].channelUsed[channel])adsChannelRegisters_(s_ads[adc],channel,s_scanRegisters[adc][channel]);
  }
  scanMemory_("before_prime");
  for(unsigned adc=0;adc<adcCount;++adc)for(uint8_t channel=0;channel<4;++channel)if(s_ads[adc].channelUsed[channel] && !concentratedAcquire_(channel,true,adc)) {
    const auto& stats=s_timingStats.adc[adc];
    AIN_LOGE("scan start refused stage=prime adc=%u channel=%u read_failures=%lu config_faults=%lu wait_timeouts=%lu\n",
        adc,(unsigned)channel,(unsigned long)stats.scanReadFailures,(unsigned long)stats.scanConfigFaults,
        (unsigned long)stats.scanWaitTimeouts);return false;
  }
#if defined(ESP32)
  for(unsigned adc=0;adc<adcCount;++adc)if(s_ads[adc].activeChannels) {s_ads[adc].nextAsyncChannel=0;s_ads[adc].asyncTask=s_scanTask;}
#if !BODAQS_PRODUCTION_RECORDING
  s_scanRun.store(true);
  s_timingWorkers.fetch_or(1u,std::memory_order_release);
  xTaskNotifyGive(s_scanTask);
#endif
#if BODAQS_PRODUCTION_RECORDING
  AIN_LOGI("acquisition plan: adc_masks=0x%x,0x%x columns=%u row_rate_hz=%u scheduler=absolute_timer verify_regs=4\n",
      s_recordingScan->plan.mask(0), s_recordingScan->plan.mask(1),
      s_recordingScan->plan.columns(), s_effectiveHz);
  return true;
#elif BODAQS_ADC_BOUNDARY_BENCH
  AIN_LOGI("bounded scan: adcs=%u channels=%u rate_hz=%u configured_sps=2000 row_period_us=%lu appointment=%lu/%u us scheduler=%s spi_hz=%u full_prime=%u verify_regs=4\n",
      adcCount,scanChannelCount_(),s_effectiveHz,(unsigned long)Rates::periodUs(s_effectiveHz),
      (unsigned long)Rates::periodUs(s_effectiveHz),scanChannelCount_(),
      AdcConcentratedScan::usesTickCadence(Rates::periodUs(s_effectiveHz),scanChannelCount_())?"rtos_tick":"timer_deadline_notify",
      (unsigned)BODAQS_ADC_SCAN_SPI_HZ,scanChannelCount_());return true;
#else
  AIN_LOGI("bounded scan: adcs=%u channels0/1,500Hz/channel,2000SPS,1ms appointments spi_hz=%u setup=%s full_prime=2 verify_regs=4\n",
      adcCount,(unsigned)BODAQS_ADC_SCAN_SPI_HZ,BODAQS_ADC_SCAN_MUX_ONLY?"reg0_then_start":"full_wreg_then_start");return true;
#endif
#else
  return false; // No production worker fallback in this exact bench scope.
#endif
}
void concentratedStop_() {
#if defined(ESP32)
  s_scanRun.store(false);
  portENTER_CRITICAL(&s_drdyMux);
  if(s_ads[0].drdyTask){BaseType_t wake=pdFALSE;vTaskNotifyGiveFromISR(s_ads[0].drdyTask,&wake);}
  portEXIT_CRITICAL(&s_drdyMux);
  const uint32_t began=millis();
  while(s_timingWorkers.load(std::memory_order_acquire) && uint32_t(millis()-began)<kAsyncStopWaitMs)vTaskDelay(1);
#endif
  if(s_timingWorkers.load(std::memory_order_acquire)){s_scanFault.store(true);return;}
#if defined(ESP32)
  if(s_scanTask)AIN_LOGI("scan worker parked stack_unused_min_bytes=%u\n",(unsigned)uxTaskGetStackHighWaterMark(s_scanTask));
#endif
  for(unsigned adc=0;adc<scanAdcCount_();++adc)
    if(s_ads[adc].activeChannels && !adsCommand_(s_ads[adc],0x02))++s_timingStats.adc[adc].continuousStopFailures;
  s_continuousSession=false;s_continuousHealthy=false;s_scanSession=false;
}
#endif

#if BODAQS_ADC_CONTINUOUS_LATEST
bool continuousPoll_(uint8_t adc) {
  auto& dev=s_ads[adc];auto& stats=s_timingStats.adc[adc];
  const uint8_t channel=s_continuousChannels[adc];++stats.continuousPolls;
  if(!s_continuousHealthy)return false;
  if(digitalRead(static_cast<uint8_t>(dev.cfg.drdy_pin))!=(dev.cfg.drdy_active_low?LOW:HIGH)) {
    ++stats.continuousNoNew;
    if(static_cast<uint32_t>(micros()-s_continuousLastDataUs[adc])>=10000) {
      ++stats.continuousStalls;s_continuousHealthy=false;
      publishCachedSample_(adc,channel,0,false);AIN_LOGE("ADS%u continuous data activity timeout\n",adc);
    }
    return false;
  }
  // One padded/aligned transaction: RREG all four configuration bytes, RDATA.
  // Validate configuration before publishing; never infer freshness from value changes.
  alignas(4) const uint8_t tx[12]={0x23,0,0,0,0,ADS1220_CMD_RDATA,0,0,0,0,0,0};
  alignas(4) uint8_t rx[12]={};uint8_t expected[4];adsChannelRegisters_(dev,channel,expected);expected[1]|=0x04;
  const uint32_t beginUs=micros();
  if(!adsTransfer_(dev,tx,rx,9)) {
    ++stats.continuousReadFailures;++stats.channel[channel].acquireFail;s_continuousHealthy=false;
    publishCachedSample_(adc,channel,0,false);return false;
  }
  if(memcmp(rx+1,expected,4)!=0) {
    ++stats.continuousConfigFaults;++stats.channel[channel].acquireFail;s_continuousHealthy=false;
    publishCachedSample_(adc,channel,0,false);AIN_LOGE("ADS%u continuous configuration mismatch\n",adc);return false;
  }
  int32_t raw=(static_cast<int32_t>(rx[6])<<16)|(static_cast<int32_t>(rx[7])<<8)|rx[8];
  if(raw&0x00800000L)raw|=static_cast<int32_t>(0xFF000000UL);
  publishCachedSample_(adc,channel,scaleRaw24ToEffectiveBits_(raw,dev.cfg.effective_bits),true);
  s_continuousLastDataUs[adc]=micros();++stats.continuousReads;++stats.channel[channel].acquireOk;
  const uint32_t elapsed=micros()-beginUs;TimingStats_record(stats.readUs,elapsed);
  TimingStats_record(stats.channel[channel].totalUs,elapsed);return true;
}
void continuousStart_() {
  s_continuousSession=true;s_continuousHealthy=true;
#if BODAQS_ADC_CONCENTRATED_SCAN_BENCH
  s_scanSession=false;s_scanFault.store(false);
  if(BODAQS_PRODUCTION_RECORDING || (BODAQS_ADC_BOUNDARY_BENCH && anyActiveExternalAdc_()) ||
     (s_ads[0].activeChannels==2 && (!s_ads[1].activeChannels || BODAQS_ADC_DUAL_SCAN_BENCH))) {
    s_continuousHealthy=concentratedStart_();return;
  }
#endif
  for(unsigned adc=0;adc<board::BOARD_MAX_EXTERNAL_ADCS;++adc) {
    const auto& dev=s_ads[adc];
    if(!dev.present || !dev.initialized || dev.activeChannels!=1 || !dev.channelUsed[0] || dev.dataRateSps!=1000 || dev.cfg.drdy_pin<0 || s_effectiveHz!=500) {
      s_continuousHealthy=false;AIN_LOGE("continuous bench requires two ADCs, channel0,1000SPS,500Hz and DRDY\n");return;
    }
  }
  for(unsigned adc=0;adc<board::BOARD_MAX_EXTERNAL_ADCS;++adc) {
    auto& dev=s_ads[adc];auto& stats=s_timingStats.adc[adc];s_continuousChannels[adc]=0;
    uint8_t regs[4];adsChannelRegisters_(dev,0,regs);regs[1]|=0x04;
    const uint32_t beginUs=micros();
    // Explicit START once, retaining full configuration; WREG-only was not reliable.
    if(!adsWriteRegistersAndStart_(dev,0,regs,4)) {++stats.continuousReadFailures;s_continuousHealthy=false;return;}
    stats.continuousRunning=true;TimingStats_record(stats.configUs,micros()-beginUs);
    if(!adsWaitReady_(dev,conversionTimeoutUs_(dev))) {++stats.waitTimeouts;s_continuousHealthy=false;return;}
    s_continuousLastDataUs[adc]=micros();
    if(!continuousPoll_(adc)) {s_continuousHealthy=false;return;}
  }
}
void continuousStop_() {
  // Row producer is stopped/guarded before this call; no continuous worker exists.
  for(unsigned adc=0;adc<board::BOARD_MAX_EXTERNAL_ADCS;++adc) {
    auto& stats=s_timingStats.adc[adc];
    if(stats.continuousRunning && !adsCommand_(s_ads[adc],0x02))++stats.continuousStopFailures;
    stats.continuousRunning=false;
  }
  s_continuousSession=false;s_continuousHealthy=false;
}
#endif

#if defined(ESP32)
void adcTaskFn_(void* arg) {
  const uint8_t adc = (uint8_t)(uintptr_t)arg;
  if (adc >= board::BOARD_MAX_EXTERNAL_ADCS) {
    vTaskDelete(nullptr);
    return;
  }

  AdsDevice& dev = s_ads[adc];
  if (dev.cfg.drdy_pin >= 0) {
    // The shared GPIO ISR may run on the other core. Protect its target
    // through registration and shutdown, before this worker deletes itself.
    portENTER_CRITICAL(&s_drdyMux);
    dev.drdyTask = xTaskGetCurrentTaskHandle();
    portEXIT_CRITICAL(&s_drdyMux);
    attachInterruptArg((uint8_t)dev.cfg.drdy_pin, adsReadyIsr_, &dev,
                       dev.cfg.drdy_active_low ? FALLING : RISING);
  }
  dev.asyncRunning = true;
  if (adc < ExternalAdcTimingStats::kMaxAdcs) {
    s_timingStats.adc[adc].asyncRunning = true;
  }
  AIN_LOGI("ADS%u async scheduler started\n", (unsigned)adc);

  int64_t lastBlockUs = esp_timer_get_time();
#if BODAQS_ADC_ROW_PACING
  int64_t previousEpoch=-1;
#endif
  while (dev.asyncRun) {
    if (!dev.present || !dev.initialized || dev.activeChannels == 0) {
      vTaskDelay(pdMS_TO_TICKS(10));
      lastBlockUs = esp_timer_get_time();
      continue;
    }

#if BODAQS_ADC_ROW_PACING
    if(!rowGates[adc])break;
    (void)xSemaphoreTake(rowGates[adc],portMAX_DELAY);
    if(!dev.asyncRun)break;
    if(!rowActive.load(std::memory_order_acquire))continue;
    const auto appointment=AdcRowSchedule::claim(esp_timer_get_time(),rowOrigin,previousEpoch);
    auto& pacing=s_timingStats.adc[adc];
    if(appointment.observed)TimingStats_record(pacing.rowDispatchLagUs,appointment.startLagUs);
    pacing.rowPacingMissed+=appointment.missed;
    if(!appointment.acquire)continue;
    ++pacing.rowPacingStarts;
#endif
    const uint8_t ch = nextActiveChannel_(dev);
    if (ch == kInvalidChannel) {
      vTaskDelay(pdMS_TO_TICKS(10));
      lastBlockUs = esp_timer_get_time();
      continue;
    }

#if BODAQS_TIMING_INSTRUMENTATION
    const uint32_t loopT0 = micros();
#endif
    (void)acquireAndPublishChannel_(adc, ch);
#if BODAQS_ADC_ROW_PACING
    if(esp_timer_get_time()>appointment.deadline)++pacing.rowPacingOverruns;
#endif
#if BODAQS_TIMING_INSTRUMENTATION
    if (adc < ExternalAdcTimingStats::kMaxAdcs) {
      TimingStats_record(s_timingStats.adc[adc].asyncLoopUs,
                         (uint32_t)(micros() - loopT0));
    }
#endif

    const int64_t nowUs = esp_timer_get_time();
    if ((nowUs - lastBlockUs) >= kAsyncMaxNoBlockUs) {
      vTaskDelay(1);
      lastBlockUs = esp_timer_get_time();
    }
  }

  if (dev.drdyTask) {
    portENTER_CRITICAL(&s_drdyMux);
    dev.drdyTask = nullptr;
    portEXIT_CRITICAL(&s_drdyMux);
    detachInterrupt((uint8_t)dev.cfg.drdy_pin);
  }
  dev.asyncRunning = false;
  dev.asyncTask = nullptr;
  if (adc < ExternalAdcTimingStats::kMaxAdcs) {
    s_timingStats.adc[adc].asyncRunning = false;
  }
  AIN_LOGI("ADS%u async scheduler stopped\n", (unsigned)adc);
  s_timingWorkers.fetch_and(static_cast<uint8_t>(~(1u << adc)), std::memory_order_release);
  vTaskDelete(nullptr);
}
#endif

} // namespace

namespace AnalogInputManager {

#if BODAQS_PRODUCTION_RECORDING
bool setRecordingPlan(const LocalAnalogRecordingPlan& plan, CountPublisher publisher) {
  if (!plan.rateHz() || s_scanSession || s_timingWorkers.load(std::memory_order_acquire)) return false;
  for (unsigned field = 0; field < plan.inputs(); ++field)
    if (!plan.column(field).external && digitalPinToAnalogChannel(uint8_t(plan.column(field).pin)) < 0) return false;
  for (unsigned adc = 0; adc < 2; ++adc) {
    if (plan.mask(adc) && (!s_ads[adc].present || !s_ads[adc].initialized || s_ads[adc].cfg.drdy_pin < 0)) return false;
  }
  if (!s_recordingScan) s_recordingScan = new (std::nothrow) RecordingScanState;
  if (!s_recordingScan) return false;
  s_recordingScan->plan = plan;
  s_recordingScan->row = {};
  s_recordingScan->publisher=publisher;
  for (unsigned adc = 0; adc < 2; ++adc) {
    auto& dev = s_ads[adc];
    for (unsigned channel = 0; channel < 4; ++channel) dev.channelUsed[channel] = (plan.mask(adc) & (1u << channel)) != 0;
    dev.activeChannels = plan.channels(adc);
    if (dev.activeChannels) {
      const auto rate = selectRate_(2000);
      dev.dataRateSps = rate.sps;
      dev.config1 = static_cast<uint8_t>((rate.drBits << 5) | (rate.modeBits << 3));
    }
  }
  return true;
}
unsigned rawRecordingColumns() { return s_recordingScan ? s_recordingScan->plan.columns() : 0; }
bool activateRecordingPlan() {
  if (!s_scanSession || !s_recordingScan || !s_scanTask || !s_scanRowCapture ||
      s_scanFault.load() || s_timingWorkers.load(std::memory_order_acquire)) return false;
  s_scanRun.store(true);
  s_timingWorkers.fetch_or(1u, std::memory_order_release);
  xTaskNotifyGive(s_scanTask);
  return true;
}
bool recordingRowTiming(uint32_t& sequence, uint32_t& missed, uint64_t& deadlineUs) {
  if (!s_recordingScan || !s_recordingScan->row.row) return false;
  sequence = s_recordingScan->row.sequence;
  missed = s_recordingScan->row.skippedRows;
  deadlineUs = s_recordingScan->row.rowDeadlineUs;
  return true;
}
#endif
#if BODAQS_ADC_COMBINED_CAPTURE
bool scanRowCaptureEligible() {return concentratedScope_();}
bool retireScanRowCapture() {
  if(!s_scanSession)return true;
  s_scanRun.store(false);
  if(s_scanTask)xTaskNotifyGive(s_scanTask);
  // Never release frames/storage while this owner may still publish a row.
  return s_timingWorkers.load(std::memory_order_acquire) == 0;
}
bool setScanRowCapture(bool (*capture)()) {
  if(s_timingWorkers.load(std::memory_order_acquire) || s_scanSession)return false;
  s_scanRowCapture=capture;return capture!=nullptr;
}
#endif

#if BODAQS_ADC_ROW_HANDOFF
bool rowHandoffActive() { return s_scanSession; }
bool captureRowSnapshot(LocalAdcSnapshot& snapshot) {
  if (!s_scanSession || !s_scanRun.load(std::memory_order_acquire) || s_scanFault.load()) return false;
  portENTER_CRITICAL(&s_cacheMux);
  snapshot.capturedUs = static_cast<uint64_t>(esp_timer_get_time());
  for (unsigned adc = 0; adc < scanAdcCount_(); ++adc)for(unsigned ch=0;ch<scanChannelCount_();++ch) {
    const unsigned slot=adc*LocalAdcSnapshot::kPerAdc+ch;
    snapshot.counts[slot] = s_ads[adc].cachedCounts[ch];
    snapshot.sequence[slot] = s_ads[adc].cachedSeq[ch];
    snapshot.acquiredUs[slot] = s_ads[adc].cachedAcquiredUs[ch];
    snapshot.valid[slot] = s_ads[adc].cachedValid[ch];
  }
  portEXIT_CRITICAL(&s_cacheMux);
  return true;
}
void useRowSnapshot(const LocalAdcSnapshot* snapshot) {
  portENTER_CRITICAL(&s_cacheMux);
  s_rowSnapshotOwner = snapshot ? xTaskGetCurrentTaskHandle() : nullptr;
  s_rowSnapshot = snapshot;
  portEXIT_CRITICAL(&s_cacheMux);
}
#if BODAQS_ADC_RAW_RECORDING_BENCH
bool captureRawPair(RawAdcRecord& record,uint64_t& capturedUs) {
#if BODAQS_PRODUCTION_RECORDING
  if (!s_recordingScan || !s_scanSession || !s_scanRun.load() || s_scanFault.load() ||
      xTaskGetCurrentTaskHandle() != s_scanTask) return false;
  const uint64_t now = static_cast<uint64_t>(esp_timer_get_time());
  capturedUs = now;
  record.tick = static_cast<uint32_t>(now); record.status = 0; record.reserved = 0;
  unsigned output=0;
  for (unsigned index = 0; index < s_recordingScan->plan.inputs(); ++index) {
    const auto& source = s_recordingScan->plan.column(index);
    int32_t value = 0;
    uint16_t fieldStatus=0;
    if (source.external) {
      auto& dev = s_ads[source.adc];
      if (!dev.cachedValid[source.channel]) fieldStatus |= RawAdcRecording::kSensorError;
      else value = dev.cachedCounts[source.channel];
      const bool fresh = dev.cachedSeq[source.channel] != dev.lastRowSeq[source.channel];
      if (!fresh) fieldStatus |= BdqV2Format::TimingDegraded;
      dev.lastRowSeq[source.channel] = dev.cachedSeq[source.channel];
      const uint32_t age = now >= dev.cachedAcquiredUs[source.channel] ? uint32_t(now - dev.cachedAcquiredUs[source.channel]) : 0;
      recordCachedRowUse_(source.adc, source.channel, dev.cachedValid[source.channel], fresh, age);
    } else value = analogRead(uint8_t(source.pin));
    const auto counts=RawAdcRecording::count(value, fieldStatus);
    if(source.primary) {record.counts[output++]=counts;record.status|=fieldStatus;}
    if(s_recordingScan->publisher)
      s_recordingScan->publisher(source.sensorIndex,counts,record.tick,fieldStatus,record.sequence);
  }
  return true;
#else

  if(!s_scanSession || !s_scanRun.load(std::memory_order_acquire) || s_scanFault.load() ||
     scanAdcCount_()!=2 || scanChannelCount_()!=RawAdcRecording::kChannelsPerAdc ||
     xTaskGetCurrentTaskHandle()!=s_scanTask)return false;
  // This task alone publishes these caches. Configuration/STOP cannot reset
  // them until it retires; preview readers never write the cache or row ledger.
  for(unsigned adc=0;adc<2;++adc)
    for(unsigned channel=0;channel<RawAdcRecording::kChannelsPerAdc;++channel)
      if(!s_ads[adc].cachedValid[channel])return false;
  const uint64_t now=static_cast<uint64_t>(esp_timer_get_time());
  capturedUs=now;
  record.tick=static_cast<uint32_t>(now);record.status=0;record.reserved=0;
  for(unsigned adc=0;adc<2;++adc) {
    auto& dev=s_ads[adc];
    for(unsigned channel=0;channel<RawAdcRecording::kChannelsPerAdc;++channel) {
      record.counts[2*channel+adc]=RawAdcRecording::count(dev.cachedCounts[channel],record.status);
      const bool fresh=dev.cachedSeq[channel]!=dev.lastRowSeq[channel];
      dev.lastRowSeq[channel]=dev.cachedSeq[channel];
      const uint32_t age=now>=dev.cachedAcquiredUs[channel]?uint32_t(now-dev.cachedAcquiredUs[channel]):0;
      recordCachedRowUse_(adc,channel,true,fresh,age);
    }
  }
  return true;
#endif
}
#endif
#endif

#if BODAQS_ADC_CONCENTRATED_SCAN_BENCH
bool reserveScanTask() {
  if(s_scanSession || s_timingWorkers.load(std::memory_order_acquire))return false;
#if !BODAQS_PRODUCTION_RECORDING
  if(!concentratedScope_())return true;
#endif
#if defined(ESP32)
  #if BODAQS_ADC_BOUNDARY_BENCH
  if(!s_scanAppointmentTimer) {
    esp_timer_create_args_t args={};args.callback=scanAppointmentWake_;args.name="adc_appointment";
    if(esp_timer_create(&args,&s_scanAppointmentTimer)!=ESP_OK){AIN_LOGE("scan reservation failed stage=timer_create\n");return false;}
  }
  #endif
  if(s_scanTask)return true;
  scanMemory_("before_worker_reserve");
  if(xTaskCreatePinnedToCore(concentratedTask_,"ADSScan",kAsyncTaskStackBytes,nullptr,
       BODAQS_ADC_TASK_PRIORITY,&s_scanTask,0)!=pdPASS) {
    s_scanTask=nullptr;AIN_LOGE("scan reservation failed stage=worker_create stack_bytes=%u\n",(unsigned)kAsyncTaskStackBytes);
    scanMemory_("worker_reserve_failed");return false;
  }
#if BODAQS_CPU_OCCUPANCY
  CpuOccupancy::bindTask(CpuOccupancy::Adc,reinterpret_cast<uintptr_t>(s_scanTask));
#endif
  scanMemory_("after_worker_reserve");return true;
#else
  return false;
#endif
}
#endif

void begin(const board::BoardProfile& board) {
#if BODAQS_PRODUCTION_RECORDING
  analogReadResolution(12);
#endif
  s_board = &board;
  s_spiReady = false;
  s_inSample = false;
  clearCachedSamples_();

  for (auto& dev : s_ads) {
    dev = AdsDevice{};
  }
  resetTimingStats_();

  if (!board.spi.present || board.external_adc_count == 0) {
    AIN_LOGI("External ADCs: none\n");
    return;
  }

  if (board.spi.sck < 0 || board.spi.miso < 0 || board.spi.mosi < 0) {
    AIN_LOGW("SPI pins incomplete; external ADCs disabled\n");
    return;
  }

  s_spiReady = SharedSpiBus::begin(board.spi);
  if (!s_spiReady) {
    AIN_LOGW("Shared SPI initialization failed; external ADCs disabled\n");
    return;
  }
  AIN_LOGI("SPI ready: sck=%d miso=%d mosi=%d\n",
           (int)board.spi.sck,
           (int)board.spi.miso,
           (int)board.spi.mosi);
  AIN_LOGI("ADS1220 setup=full_wreg_then_start_single_cs\n");

  const uint8_t count = (board.external_adc_count < board::BOARD_MAX_EXTERNAL_ADCS)
                          ? board.external_adc_count
                          : board::BOARD_MAX_EXTERNAL_ADCS;
  for (uint8_t i = 0; i < count; ++i) {
    const auto& cfg = board.external_adcs[i];
    if (!cfg.present || cfg.type != board::ExternalAdcType::ADS1220 || cfg.cs_pin < 0) continue;

    AdsDevice& dev = s_ads[i];
    dev.present = true;
    dev.cfg = cfg;
    dev.dataRateSps = 20;
    dev.config1 = 0x00;

    pinMode((uint8_t)cfg.cs_pin, OUTPUT);
    digitalWrite((uint8_t)cfg.cs_pin, HIGH);
    if (cfg.drdy_pin >= 0) {
      pinMode((uint8_t)cfg.drdy_pin, cfg.drdy_use_internal_pullup ? INPUT_PULLUP : INPUT);
    }

    (void)adsCommand_(dev, ADS1220_CMD_RESET);
    delay(2);

    dev.initialized = true;
    AIN_LOGI("ADS%u ready: cs=%d drdy=%d max_sps=%lu bits=%u\n",
             (unsigned)i,
             (int)cfg.cs_pin,
             (int)cfg.drdy_pin,
             (unsigned long)cfg.max_sps,
             (unsigned)cfg.effective_bits);
  }
  resetTimingStats_();
}

bool available(uint8_t ain) {
  const board::AnalogInputHW* input = inputForAin_(ain);
  return input && analogInputAvailable_(*input);
}

bool inputIsExternal(uint8_t ain) {
  const board::AnalogInputHW* input = inputForAin_(ain);
  return input && input->source == board::AnalogSourceType::ExternalAdc;
}

int8_t pinForAin(uint8_t ain) {
  const board::AnalogInputHW* input = inputForAin_(ain);
  if (!input || input->source != board::AnalogSourceType::InternalGpio) return -1;
  return input->pin;
}

static bool readCounts_(uint8_t ain, int32_t& outCounts, const LocalAdcSnapshot* row) {
  const board::AnalogInputHW* input = inputForAin_(ain);
  if (!input) return false;

  if (input->source == board::AnalogSourceType::InternalGpio) {
    if (input->pin < 0) return false;
    outCounts = analogRead((uint8_t)input->pin);
    return true;
  }

  if (input->source == board::AnalogSourceType::ExternalAdc) {
    const uint8_t adc = input->external_adc_index;
    const uint8_t channel = input->external_channel;
    if (!validAdcIndex_(adc) || !validChannel_(s_ads[adc], channel)) return false;

    if (
#if BODAQS_ADC_CONTINUOUS_LATEST
        s_continuousSession ||
#endif
        (s_asyncLoggingActive &&
#if defined(ESP32)
        (s_ads[adc].asyncTask || s_ads[adc].asyncRunning)
#else
        false
#endif
        )) {
      CachedAdcSample sample;
      bool supplied = false;
      uint64_t observedUs = 0;
#if BODAQS_ADC_ROW_HANDOFF
      const unsigned slot=adc*LocalAdcSnapshot::kPerAdc+channel;
      if (row && channel < LocalAdcSnapshot::kPerAdc && slot < LocalAdcSnapshot::kChannels) {
        sample.valid = row->valid[slot];
        sample.counts = row->counts[slot];
        sample.seq = row->sequence[slot];
        sample.acquiredUs = row->acquiredUs[slot];
        observedUs = row->capturedUs;
        supplied = true;
      } else {
        portENTER_CRITICAL(&s_cacheMux);
        if (s_rowSnapshot && s_rowSnapshotOwner == xTaskGetCurrentTaskHandle() && channel < LocalAdcSnapshot::kPerAdc && slot < LocalAdcSnapshot::kChannels) {
          sample.valid = s_rowSnapshot->valid[slot];
          sample.counts = s_rowSnapshot->counts[slot];
          sample.seq = s_rowSnapshot->sequence[slot];
          sample.acquiredUs = s_rowSnapshot->acquiredUs[slot];
          observedUs = s_rowSnapshot->capturedUs;
          supplied = true;
        }
        portEXIT_CRITICAL(&s_cacheMux);
      }
#endif
      const bool have = supplied ? sample.valid : copyCachedSample_(adc, channel, sample);
      bool fresh = false;
      bool countRowUse = true;
#if BODAQS_ADC_ROW_HANDOFF
      // Preview/live reads must not advance the assembled row's freshness ledger.
      if (s_scanSession && !supplied) countRowUse = false;
#endif
      uint32_t ageUs = 0;
      if (have) {
        fresh = countRowUse && sample.seq != s_ads[adc].lastRowSeq[channel];
        if (countRowUse) s_ads[adc].lastRowSeq[channel] = sample.seq;
        const uint64_t nowUs = supplied ? observedUs : static_cast<uint64_t>(esp_timer_get_time());
        if (nowUs >= sample.acquiredUs) {
          ageUs = (uint32_t)(nowUs - sample.acquiredUs);
        }
        outCounts = sample.counts;
      }
      #if BODAQS_ADC_SCAN_ROW_PHASE && BODAQS_ADC_ROW_PHASE_DIAGNOSTICS
      if(s_scanSession && s_scanRowAnchorValid.load(std::memory_order_acquire)) {
        const uint32_t phase=static_cast<uint32_t>((static_cast<uint64_t>(esp_timer_get_time())-s_scanRowAnchor)%2000);
        TimingStats_record(s_timingStats.adc[adc].scanRowPhaseUs,phase);
      }
#endif
      if (countRowUse) recordCachedRowUse_(adc, channel, have, fresh, ageUs);
      return have;
    }

    if (s_inSample && s_ads[adc].cachedValid[channel]) {
      outCounts = s_ads[adc].cachedCounts[channel];
      return true;
    }

    return readAdsChannelLive_(adc, channel, outCounts);
  }

  return false;
}

bool readCounts(uint8_t ain, int32_t& outCounts) {
  return readCounts_(ain, outCounts, nullptr);
}

#if BODAQS_ADC_ROW_HANDOFF
bool readSnapshotCounts(uint8_t ain, int32_t& outCounts, const LocalAdcSnapshot& snapshot) {
  return readCounts_(ain, outCounts, &snapshot);
}
#endif

uint16_t configureFromConfig(const LoggerConfig& cfg, uint16_t requestedHz) {
#if BODAQS_ADC_CONCENTRATED_SCAN_BENCH
  // A timed-out STOP must not let a new configuration/cache reset race the
  // old owner. Preserve its statistics and require retirement before retry.
  if(s_scanSession || s_timingWorkers.load(std::memory_order_acquire)) {
    s_scanFault.store(true);return s_effectiveHz;
  }
#endif
  s_requestedHz = requestedHz ? requestedHz : 1;
  const uint16_t loggerMaxHz = Rates::kList[Rates::kCount - 1];
  if (s_requestedHz > loggerMaxHz) {
    AIN_LOGW("Sample rate capped: requested=%u Hz logger_max=%u Hz\n",
             (unsigned)s_requestedHz,
             (unsigned)loggerMaxHz);
    s_requestedHz = loggerMaxHz;
  }

  for (auto& dev : s_ads) {
    memset(dev.channelUsed, 0, sizeof(dev.channelUsed));
    dev.activeChannels = 0;
  }

  for (uint8_t i = 0; i < cfg.sensorCount(); ++i) {
    SensorSpec sp;
    if (!cfg.getSensorSpec(i, sp)) continue;
    if (sp.mutedDefault || !sensorUsesAnalogInput_(sp.type)) continue;

    long ainLong = -1;
    if (!sp.params.getInt("ain", ainLong)) continue;
    if (ainLong < 0 || ainLong >= (long)board::BOARD_MAX_ANALOG_INPUTS) continue;

    const board::AnalogInputHW* input = inputForAin_((uint8_t)ainLong);
    if (!input || input->source != board::AnalogSourceType::ExternalAdc) continue;
    if (!validAdcIndex_(input->external_adc_index)) continue;

    AdsDevice& dev = s_ads[input->external_adc_index];
    if (!validChannel_(dev, input->external_channel)) continue;
    dev.channelUsed[input->external_channel] = true;
  }

  uint32_t maxHz = s_requestedHz;
  for (uint8_t adc = 0; adc < board::BOARD_MAX_EXTERNAL_ADCS; ++adc) {
    AdsDevice& dev = s_ads[adc];
    if (!dev.present) continue;

    uint8_t active = 0;
    for (uint8_t ch = 0; ch < 4; ++ch) {
      if (dev.channelUsed[ch]) ++active;
    }
    dev.activeChannels = active;
    if (active == 0) continue;

    const uint32_t adcMaxHz = usableLoggerHzForAdc_(dev, active);
    if (adcMaxHz < maxHz) maxHz = adcMaxHz;
  }

#if BODAQS_PRODUCTION_RECORDING
  s_effectiveHz = s_requestedHz;
#else
  s_effectiveHz = snapDownRate_(s_requestedHz, maxHz);
#endif
  if (s_effectiveHz < 1) s_effectiveHz = 1;

  for (uint8_t adc = 0; adc < board::BOARD_MAX_EXTERNAL_ADCS; ++adc) {
    AdsDevice& dev = s_ads[adc];
    if (!dev.present || dev.activeChannels == 0) continue;

    const uint32_t requiredSps = (uint32_t)s_effectiveHz * (uint32_t)dev.activeChannels;
    const uint32_t targetSps = targetDataRateSps_(s_effectiveHz, dev.activeChannels);
    const AdsRateSetting rate = selectRate_(targetSps);
    dev.dataRateSps = rate.sps;
    dev.config1 = (uint8_t)((rate.drBits << 5) | (rate.modeBits << 3));

    AIN_LOGI("ADS%u active_channels=%u required=%lu SPS target=%lu SPS configured=%u SPS\n",
             (unsigned)adc,
             (unsigned)dev.activeChannels,
             (unsigned long)requiredSps,
             (unsigned long)targetSps,
             (unsigned)dev.dataRateSps);
  }

  resetTimingStats_();

  if (s_effectiveHz != s_requestedHz) {
    AIN_LOGW("Sample rate throttled: requested=%u Hz effective=%u Hz\n",
             (unsigned)s_requestedHz,
             (unsigned)s_effectiveHz);
  }

  return s_effectiveHz;
}

uint16_t effectiveSampleRateHz() {
  return s_effectiveHz;
}

uint16_t requestedSampleRateHz() {
  return s_requestedHz;
}

uint8_t activeChannelCount(uint8_t externalAdcIndex) {
  if (!validAdcIndex_(externalAdcIndex)) return 0;
  return s_ads[externalAdcIndex].activeChannels;
}

uint16_t configuredDataRateSps(uint8_t externalAdcIndex) {
  if (!validAdcIndex_(externalAdcIndex)) return 0;
  return s_ads[externalAdcIndex].dataRateSps;
}

void resetTimingStats() {
  resetTimingStats_();
}

const ExternalAdcTimingStats& timingStats() {
  return s_timingStats;
}

const ExternalAdcTimingStats* stoppedTimingStats() {
#if BODAQS_ADC_CONTINUOUS_LATEST
  if(s_continuousSession.load(std::memory_order_acquire))return nullptr;
#endif
  return s_timingWorkers.load(std::memory_order_acquire) ? nullptr : &s_timingStats;
}

#if BODAQS_ADC_CONTINUOUS_LATEST
bool continuousHealthy(){return s_continuousSession && s_continuousHealthy
#if BODAQS_ADC_CONCENTRATED_SCAN_BENCH
  && !s_scanFault.load()
#endif
  ;}
#endif
#if BODAQS_ADC_SCAN_ROW_PHASE
bool scanRowPhaseActive(){return s_scanSession;}
bool scanRowDeadline(int64_t nowUs,int64_t& deadline) {
  if(!s_scanSession || !s_scanRun.load(std::memory_order_acquire) || s_scanFault.load() ||
     !s_scanRowAnchorValid.load(std::memory_order_acquire))return false;
  if(nowUs<static_cast<int64_t>(s_scanRowAnchor))return false;
  const int64_t anchor=static_cast<int64_t>(s_scanRowAnchor);
  deadline=anchor+250;
  if(deadline<=nowUs)deadline+=((nowUs-deadline)/2000+1)*2000;
  return true;
}
#endif
void onLoggingStart() {
#if BODAQS_ADC_CONCENTRATED_SCAN_BENCH
  if(s_scanSession || s_timingWorkers.load(std::memory_order_acquire)) {
    s_scanFault.store(true);s_continuousHealthy=false;return;
  }
#endif
#if BODAQS_ADC_CONTINUOUS_LATEST
  s_asyncLoggingActive=false;clearCachedSamples_();continuousStart_();return;
#endif
  s_asyncLoggingActive = false;
  clearCachedSamples_();

  if (!anyActiveExternalAdc_()) return;

  for (uint8_t adc = 0; adc < board::BOARD_MAX_EXTERNAL_ADCS; ++adc) {
    AdsDevice& dev = s_ads[adc];
    if (!dev.present || !dev.initialized || dev.activeChannels == 0) continue;
    dev.nextAsyncChannel = 0;

    for (uint8_t pass = 0; pass < 4; ++pass) {
      const uint8_t ch = nthActiveChannel_(dev, pass);
      if (ch == kInvalidChannel) continue;
      (void)acquireAndPublishChannel_(adc, ch);

    }
  }

#if defined(ESP32)
#if BODAQS_ADC_ROW_PACING
  rowActive.store(false,std::memory_order_release);
  if(rowTimer)(void)esp_timer_stop(rowTimer);
  for(auto& gate:rowGates){if(!gate)gate=xSemaphoreCreateBinary();if(gate)while(xSemaphoreTake(gate,0)==pdTRUE){}}
  if(!rowTimer){esp_timer_create_args_t args={};args.callback=rowTick;args.name="adc_rows";(void)esp_timer_create(&args,&rowTimer);}
#endif
  bool anyStarted = false;
  for (uint8_t adc = 0; adc < board::BOARD_MAX_EXTERNAL_ADCS; ++adc) {
    AdsDevice& dev = s_ads[adc];
    if (!dev.present || !dev.initialized || dev.activeChannels == 0) continue;
    if (dev.asyncTask) {
      anyStarted = true;
      continue;
    }

    dev.asyncRun = true;
    s_timingWorkers.fetch_or(static_cast<uint8_t>(1u << adc), std::memory_order_relaxed);
    const BaseType_t ok = xTaskCreatePinnedToCore(
      adcTaskFn_,
      "ADSAsync",
      kAsyncTaskStackBytes,
      (void*)(uintptr_t)adc,
      BODAQS_ADC_TASK_PRIORITY,
      &dev.asyncTask,
      0);

    if (ok == pdPASS) {
      anyStarted = true;
    } else {
      dev.asyncTask = nullptr;
      dev.asyncRun = false;
      s_timingWorkers.fetch_and(static_cast<uint8_t>(~(1u << adc)), std::memory_order_release);
      AIN_LOGW("ADS%u async scheduler failed to start; falling back to synchronous scan\n",
               (unsigned)adc);
    }
  }
  s_asyncLoggingActive = anyStarted;
#else
  s_asyncLoggingActive = false;
#endif
}

void onLoggingStop() {
#if BODAQS_ADC_SCAN_ROW_PHASE
  s_scanRowAnchorValid.store(false,std::memory_order_release);
#endif
#if BODAQS_ADC_CONCENTRATED_SCAN_BENCH
  if(s_scanSession){concentratedStop_();return;}
#endif
#if BODAQS_ADC_CONTINUOUS_LATEST
  if(s_continuousSession)continuousStop_();
#endif
#if BODAQS_ADC_ROW_PACING
  rowActive.store(false,std::memory_order_release);
  if(rowTimer)(void)esp_timer_stop(rowTimer);
#endif
  s_asyncLoggingActive = false;

#if defined(ESP32)
  for (uint8_t adc = 0; adc < board::BOARD_MAX_EXTERNAL_ADCS; ++adc) {
    s_ads[adc].asyncRun = false;
#if BODAQS_ADC_ROW_PACING
    if(rowGates[adc])xSemaphoreGive(rowGates[adc]);
#endif
  }

  const uint32_t t0 = millis();
  bool any = true;
  while (any && (uint32_t)(millis() - t0) < kAsyncStopWaitMs) {
    any = s_timingWorkers.load(std::memory_order_acquire) != 0;
    if (any) vTaskDelay(1);
  }
#endif
}

#if BODAQS_ADC_ROW_PACING
int64_t beginRowPacing() {
  if(s_effectiveHz!=500 || !rowTimer){AIN_LOGE("row pacing start rejected: hz=%u timer_ready=%u\n",s_effectiveHz,rowTimer?1u:0u);return 0;}
  for(unsigned i=0;i<board::BOARD_MAX_EXTERNAL_ADCS;++i)if(s_ads[i].activeChannels &&
      (s_ads[i].activeChannels!=1 || !s_ads[i].asyncTask || !rowGates[i])){AIN_LOGE("row pacing start rejected: adc=%u worker/gate/scope\n",i);return 0;}
  rowOrigin=esp_timer_get_time();
  rowActive.store(true,std::memory_order_release);
  const auto result=esp_timer_start_periodic(rowTimer,AdcRowSchedule::periodUs);
  if(result!=ESP_OK){AIN_LOGE("row pacing timer arm failed: %d\n",result);rowActive.store(false);return 0;}
  rowTick(nullptr);
  return rowOrigin+AdcRowSchedule::completionUs;
}
#endif

void beginSample() {
#if BODAQS_ADC_CONTINUOUS_LATEST
  if(s_continuousSession) {
#if BODAQS_ADC_CONCENTRATED_SCAN_BENCH
    if(s_scanSession){s_inSample=true;return;}
#endif
    for(unsigned adc=0;adc<board::BOARD_MAX_EXTERNAL_ADCS && s_continuousHealthy;++adc)(void)continuousPoll_(adc);
    s_inSample=true;return;
  }
#endif
  s_inSample = false;

  if (s_asyncLoggingActive) {
    s_inSample = true;
    return;
  }

  clearCachedSamples_();

  bool any = false;
  for (const auto& dev : s_ads) {
    if (dev.present && dev.activeChannels > 0) {
      any = true;
      break;
    }
  }
  if (!any) return;

#if BODAQS_TIMING_INSTRUMENTATION
  const uint32_t scanT0 = micros();
  bool scanRecorded[ExternalAdcTimingStats::kMaxAdcs] = {};
#endif

  for (uint8_t pass = 0; pass < 4; ++pass) {
    bool anyStarted = false;
    uint8_t startedChannel[board::BOARD_MAX_EXTERNAL_ADCS];
#if BODAQS_TIMING_INSTRUMENTATION
    uint32_t channelStartUs[board::BOARD_MAX_EXTERNAL_ADCS];
#endif
    for (uint8_t adc = 0; adc < board::BOARD_MAX_EXTERNAL_ADCS; ++adc) {
      startedChannel[adc] = kInvalidChannel;
#if BODAQS_TIMING_INSTRUMENTATION
      channelStartUs[adc] = 0;
#endif
    }

    for (uint8_t adc = 0; adc < board::BOARD_MAX_EXTERNAL_ADCS; ++adc) {
      AdsDevice& dev = s_ads[adc];
      if (!dev.present || !dev.initialized || dev.activeChannels == 0) continue;

      const uint8_t ch = nthActiveChannel_(dev, pass);
      if (ch == kInvalidChannel) continue;

      auto& adcStats = s_timingStats.adc[adc];
#if BODAQS_TIMING_INSTRUMENTATION
      channelStartUs[adc] = micros();

      uint32_t t0 = micros();
#endif
      if (!configureAndStartAdsChannel_(dev, ch)) continue;
#if BODAQS_TIMING_INSTRUMENTATION
      TimingStats_record(adcStats.configUs, (uint32_t)(micros() - t0));
#endif

      startedChannel[adc] = ch;
      anyStarted = true;
    }

    if (!anyStarted) break;

    for (uint8_t adc = 0; adc < board::BOARD_MAX_EXTERNAL_ADCS; ++adc) {
      AdsDevice& dev = s_ads[adc];
      const uint8_t ch = startedChannel[adc];
      if (ch == kInvalidChannel || !dev.present || !dev.initialized) continue;
      auto& adcStats = s_timingStats.adc[adc];
      uint32_t waitUs = 0;
      bool readyImmediately = false;
      if (!adsWaitReady_(dev, conversionTimeoutUs_(dev), &waitUs, &readyImmediately)) {
        startedChannel[adc] = kInvalidChannel;
#if BODAQS_TIMING_INSTRUMENTATION
        TimingStats_record(adcStats.waitUs, waitUs);
        TimingStats_record(adcStats.channel[ch].waitUs, waitUs);
        ++adcStats.waitTimeouts;
#endif
        AIN_LOGW("ADS%u channel%u DRDY timeout\n", (unsigned)adc, (unsigned)ch);
      } else {
#if BODAQS_TIMING_INSTRUMENTATION
        TimingStats_record(adcStats.waitUs, waitUs);
        TimingStats_record(adcStats.channel[ch].waitUs, waitUs);
        if (readyImmediately) ++adcStats.drdyAlreadyReady;
#endif
      }
    }

    for (uint8_t adc = 0; adc < board::BOARD_MAX_EXTERNAL_ADCS; ++adc) {
      AdsDevice& dev = s_ads[adc];
      const uint8_t ch = startedChannel[adc];
      if (ch == kInvalidChannel || !dev.present || !dev.initialized) continue;

      int32_t raw24 = 0;
      auto& adcStats = s_timingStats.adc[adc];
#if BODAQS_TIMING_INSTRUMENTATION
      const uint32_t t0 = micros();
#endif
      if (!adsReadData_(dev, raw24)) continue;
#if BODAQS_TIMING_INSTRUMENTATION
      TimingStats_record(adcStats.readUs, (uint32_t)(micros() - t0));
#endif
      dev.cachedCounts[ch] = scaleRaw24ToEffectiveBits_(raw24, dev.cfg.effective_bits);
      dev.cachedValid[ch] = true;
#if BODAQS_TIMING_INSTRUMENTATION
      if (ch < ExternalAdcTimingStats::kMaxChannels && channelStartUs[adc] != 0) {
        TimingStats_record(adcStats.channel[ch].totalUs, (uint32_t)(micros() - channelStartUs[adc]));
      }
      if (adc < ExternalAdcTimingStats::kMaxAdcs) scanRecorded[adc] = true;
#endif
    }
  }

#if BODAQS_TIMING_INSTRUMENTATION
  const uint32_t scanUs = (uint32_t)(micros() - scanT0);
  for (uint8_t adc = 0; adc < board::BOARD_MAX_EXTERNAL_ADCS && adc < ExternalAdcTimingStats::kMaxAdcs; ++adc) {
    if (scanRecorded[adc]) TimingStats_record(s_timingStats.adc[adc].scanUs, scanUs);
  }
#endif

  s_inSample = true;
}

void endSample() {
  s_inSample = false;
}

} // namespace AnalogInputManager
