#include "AnalogInputManager.h"

#include <Arduino.h>
#include <SPI.h>
#include <string.h>

#include "ConfigManager.h"
#include "Rates.h"
#include "SensorTypes.h"
#include "DebugLog.h"
#include "esp_timer.h"

#if defined(ESP32)
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#endif

#define AIN_LOGE(...) LOGE_TAG("AIN", __VA_ARGS__)
#define AIN_LOGW(...) LOGW_TAG("AIN", __VA_ARGS__)
#define AIN_LOGI(...) LOGI_TAG("AIN", __VA_ARGS__)
#define AIN_LOGD(...) LOGD_TAG("AIN", __VA_ARGS__)

namespace {

constexpr uint8_t ADS1220_CMD_RESET = 0x06;
constexpr uint8_t ADS1220_CMD_START = 0x08;
constexpr uint8_t ADS1220_CMD_RDATA = 0x10;
constexpr uint8_t ADS1220_CMD_WREG  = 0x40;
constexpr uint8_t kInvalidChannel = 0xFF;
constexpr uint16_t kExternalAdcGlobalCapHz = 500;
constexpr uint32_t kExternalAdcUtilizationPermille = 550;
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
  volatile bool asyncRun = false;
  volatile bool asyncRunning = false;
#endif
};

const board::BoardProfile* s_board = nullptr;
AdsDevice s_ads[board::BOARD_MAX_EXTERNAL_ADCS];
SPIClass* s_spi = &SPI;
bool s_spiReady = false;
bool s_inSample = false;
volatile bool s_asyncLoggingActive = false;
uint16_t s_requestedHz = 100;
uint16_t s_effectiveHz = 100;
ExternalAdcTimingStats s_timingStats;

#if defined(ESP32)
SemaphoreHandle_t s_spiMutex = nullptr;
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

bool lockSpi_() {
#if defined(ESP32)
  if (!s_spiMutex) s_spiMutex = xSemaphoreCreateMutex();
  if (!s_spiMutex) return true;
  return xSemaphoreTake(s_spiMutex, pdMS_TO_TICKS(50)) == pdTRUE;
#else
  return true;
#endif
}

void unlockSpi_() {
#if defined(ESP32)
  if (s_spiMutex) xSemaphoreGive(s_spiMutex);
#endif
}

SPISettings spiSettings_(const AdsDevice& dev) {
  const uint32_t boardDefaultHz = (s_board && s_board->spi.hz_default)
    ? s_board->spi.hz_default
    : 1000000UL;
  const uint32_t hz = dev.cfg.spi_hz ? dev.cfg.spi_hz : boardDefaultHz;
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
  const uint32_t usableSps = (adsMaxSps_(dev) * kExternalAdcUtilizationPermille) / 1000UL;
  return (usableSps ? usableSps : 1UL) / activeChannels;
}

uint32_t targetDataRateSps_(uint16_t loggerHz, uint8_t activeChannels) {
  const uint32_t requiredSps = (uint32_t)loggerHz * (uint32_t)activeChannels;
  return ceilDivU32_(requiredSps * 1000UL, kExternalAdcUtilizationPermille);
}

void adsTransfer_(AdsDevice& dev, const uint8_t* tx, uint8_t* rx, size_t len) {
  if (!s_spi || !tx || len == 0) return;
  s_spi->beginTransaction(spiSettings_(dev));
  digitalWrite((uint8_t)dev.cfg.cs_pin, LOW);
  for (size_t i = 0; i < len; ++i) {
    const uint8_t r = s_spi->transfer(tx[i]);
    if (rx) rx[i] = r;
  }
  digitalWrite((uint8_t)dev.cfg.cs_pin, HIGH);
  s_spi->endTransaction();
}

bool adsCommand_(AdsDevice& dev, uint8_t cmd) {
  if (!dev.present || dev.cfg.cs_pin < 0 || !s_spiReady) return false;
  if (!lockSpi_()) return false;
  adsTransfer_(dev, &cmd, nullptr, 1);
  unlockSpi_();
  return true;
}

bool adsWriteRegisters_(AdsDevice& dev, uint8_t startReg, const uint8_t* regs, size_t len) {
  if (!dev.present || !regs || len == 0 || len > 4 || !s_spiReady) return false;

  uint8_t tx[5] = {0};
  tx[0] = (uint8_t)(ADS1220_CMD_WREG | ((startReg & 0x03U) << 2) | ((len - 1U) & 0x03U));
  for (size_t i = 0; i < len; ++i) tx[i + 1] = regs[i];

  if (!lockSpi_()) return false;
  adsTransfer_(dev, tx, nullptr, len + 1);
  unlockSpi_();
  return true;
}

bool adsReadData_(AdsDevice& dev, int32_t& raw24) {
  if (!dev.present || !s_spiReady) return false;

  uint8_t tx[4] = { ADS1220_CMD_RDATA, 0x00, 0x00, 0x00 };
  uint8_t rx[4] = {0};

  if (!lockSpi_()) return false;
  adsTransfer_(dev, tx, rx, sizeof(tx));
  unlockSpi_();

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

bool configureAdsChannel_(AdsDevice& dev, uint8_t channel) {
  if (!validChannel_(dev, channel)) return false;

  const uint8_t reg0 =
      (uint8_t)((muxCodeForSingleEnded_(channel) << 4) |
                ((gainBits_(dev.cfg.gain) & 0x07U) << 1) |
                (dev.cfg.pga_bypass ? 0x01U : 0x00U));
  const uint8_t reg1 = dev.config1;
  const uint8_t reg2 = (uint8_t)((referenceBits_(dev.cfg.reference) & 0x03U) << 6);
  const uint8_t reg3 = 0x00;
  const uint8_t regs[4] = { reg0, reg1, reg2, reg3 };

  return adsWriteRegisters_(dev, 0, regs, sizeof(regs));
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
  if (!configureAdsChannel_(dev, channel)) return false;
#if BODAQS_TIMING_INSTRUMENTATION
  TimingStats_record(adcStats.configUs, (uint32_t)(micros() - t0));

  t0 = micros();
#endif
  if (!adsCommand_(dev, ADS1220_CMD_START)) return false;
#if BODAQS_TIMING_INSTRUMENTATION
  TimingStats_record(adcStats.startUs, (uint32_t)(micros() - t0));
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

#if defined(ESP32)
void adcTaskFn_(void* arg) {
  const uint8_t adc = (uint8_t)(uintptr_t)arg;
  if (adc >= board::BOARD_MAX_EXTERNAL_ADCS) {
    vTaskDelete(nullptr);
    return;
  }

  AdsDevice& dev = s_ads[adc];
  dev.asyncRunning = true;
  if (adc < ExternalAdcTimingStats::kMaxAdcs) {
    s_timingStats.adc[adc].asyncRunning = true;
  }
  AIN_LOGI("ADS%u async scheduler started\n", (unsigned)adc);

  int64_t lastBlockUs = esp_timer_get_time();
  while (dev.asyncRun) {
    if (!dev.present || !dev.initialized || dev.activeChannels == 0) {
      vTaskDelay(pdMS_TO_TICKS(10));
      lastBlockUs = esp_timer_get_time();
      continue;
    }

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

  dev.asyncRunning = false;
  dev.asyncTask = nullptr;
  if (adc < ExternalAdcTimingStats::kMaxAdcs) {
    s_timingStats.adc[adc].asyncRunning = false;
  }
  AIN_LOGI("ADS%u async scheduler stopped\n", (unsigned)adc);
  vTaskDelete(nullptr);
}
#endif

} // namespace

namespace AnalogInputManager {

void begin(const board::BoardProfile& board) {
  s_board = &board;
  s_spiReady = false;
  s_inSample = false;
  clearCachedSamples_();

  for (auto& dev : s_ads) {
    dev = AdsDevice{};
  }
  resetTimingStats_();

#if defined(ESP32)
  if (!s_spiMutex) s_spiMutex = xSemaphoreCreateMutex();
#endif

  if (!board.spi.present || board.external_adc_count == 0) {
    AIN_LOGI("External ADCs: none\n");
    return;
  }

  if (board.spi.sck < 0 || board.spi.miso < 0 || board.spi.mosi < 0) {
    AIN_LOGW("SPI pins incomplete; external ADCs disabled\n");
    return;
  }

  s_spi->begin(board.spi.sck, board.spi.miso, board.spi.mosi);
  s_spiReady = true;
  AIN_LOGI("SPI ready: sck=%d miso=%d mosi=%d\n",
           (int)board.spi.sck,
           (int)board.spi.miso,
           (int)board.spi.mosi);

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

bool readCounts(uint8_t ain, int32_t& outCounts) {
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

    if (s_asyncLoggingActive &&
#if defined(ESP32)
        (s_ads[adc].asyncTask || s_ads[adc].asyncRunning)
#else
        false
#endif
        ) {
      CachedAdcSample sample;
      const bool have = copyCachedSample_(adc, channel, sample);
      bool fresh = false;
      uint32_t ageUs = 0;
      if (have) {
        fresh = sample.seq != s_ads[adc].lastRowSeq[channel];
        s_ads[adc].lastRowSeq[channel] = sample.seq;
        const uint64_t nowUs = (uint64_t)esp_timer_get_time();
        if (nowUs >= sample.acquiredUs) {
          ageUs = (uint32_t)(nowUs - sample.acquiredUs);
        }
        outCounts = sample.counts;
      }
      recordCachedRowUse_(adc, channel, have, fresh, ageUs);
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

uint16_t configureFromConfig(const LoggerConfig& cfg, uint16_t requestedHz) {
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
  bool anyExternalActive = false;
  for (uint8_t adc = 0; adc < board::BOARD_MAX_EXTERNAL_ADCS; ++adc) {
    AdsDevice& dev = s_ads[adc];
    if (!dev.present) continue;

    uint8_t active = 0;
    for (uint8_t ch = 0; ch < 4; ++ch) {
      if (dev.channelUsed[ch]) ++active;
    }
    dev.activeChannels = active;
    if (active == 0) continue;
    anyExternalActive = true;

    const uint32_t adcMaxHz = usableLoggerHzForAdc_(dev, active);
    if (adcMaxHz < maxHz) maxHz = adcMaxHz;
  }

  if (anyExternalActive && maxHz > kExternalAdcGlobalCapHz) {
    maxHz = kExternalAdcGlobalCapHz;
  }

  s_effectiveHz = snapDownRate_(s_requestedHz, maxHz);
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

void onLoggingStart() {
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
  bool anyStarted = false;
  for (uint8_t adc = 0; adc < board::BOARD_MAX_EXTERNAL_ADCS; ++adc) {
    AdsDevice& dev = s_ads[adc];
    if (!dev.present || !dev.initialized || dev.activeChannels == 0) continue;
    if (dev.asyncTask) {
      anyStarted = true;
      continue;
    }

    dev.asyncRun = true;
    const BaseType_t ok = xTaskCreatePinnedToCore(
      adcTaskFn_,
      "ADSAsync",
      kAsyncTaskStackBytes,
      (void*)(uintptr_t)adc,
      2,
      &dev.asyncTask,
      0);

    if (ok == pdPASS) {
      anyStarted = true;
    } else {
      dev.asyncTask = nullptr;
      dev.asyncRun = false;
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
  s_asyncLoggingActive = false;

#if defined(ESP32)
  for (uint8_t adc = 0; adc < board::BOARD_MAX_EXTERNAL_ADCS; ++adc) {
    s_ads[adc].asyncRun = false;
  }

  const uint32_t t0 = millis();
  bool any = true;
  while (any && (uint32_t)(millis() - t0) < kAsyncStopWaitMs) {
    any = false;
    for (uint8_t adc = 0; adc < board::BOARD_MAX_EXTERNAL_ADCS; ++adc) {
      if (s_ads[adc].asyncTask) {
        any = true;
        break;
      }
    }
    if (any) vTaskDelay(1);
  }

  for (uint8_t adc = 0; adc < board::BOARD_MAX_EXTERNAL_ADCS; ++adc) {
    if (adc < ExternalAdcTimingStats::kMaxAdcs) {
      s_timingStats.adc[adc].asyncRunning = s_ads[adc].asyncRunning;
    }
  }
#endif
}

void beginSample() {
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
  bool scanRecorded[ExternalAdcTimingStats::kMaxAdcs] = {false, false, false, false};
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
      if (!configureAdsChannel_(dev, ch)) continue;
#if BODAQS_TIMING_INSTRUMENTATION
      TimingStats_record(adcStats.configUs, (uint32_t)(micros() - t0));

      t0 = micros();
#endif
      if (!adsCommand_(dev, ADS1220_CMD_START)) continue;
#if BODAQS_TIMING_INSTRUMENTATION
      TimingStats_record(adcStats.startUs, (uint32_t)(micros() - t0));
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
