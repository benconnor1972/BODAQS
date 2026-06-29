#include <Arduino.h>
#include "LoggingManager.h"
#include "StorageManager.h"
#include "RTCManager.h"
#include "WebServerManager.h"
#include "UI.h"
#include "AnalogPotSensor.h"
#include "SensorManager.h"
#include "Rates.h"
#include "PowerManager.h"
#include "IndicatorManager.h"
#include "WiFiManager.h"
#include "UploadModeManager.h"
#include "AnalogInputManager.h"
#include "DebugTrace.h"
#include "esp_timer.h"
#include "DebugLog.h"
#include "LoggerLimits.h"

#define LOGGING_LOGE(...) LOGE_TAG("Logging", __VA_ARGS__)
#define LOGGING_LOGW(...) LOGW_TAG("Logging", __VA_ARGS__)
#define LOGGING_LOGI(...) LOGI_TAG("Logging", __VA_ARGS__)
#define LOGGING_LOGD(...) LOGD_TAG("Logging", __VA_ARGS__)
#define PROD_LOGD(...)    LOGD_TAG("PROD", __VA_ARGS__)
#define RTC_LOGW(...)     LOGW_TAG("RTC", __VA_ARGS__)


// FreeRTOS (ESP32 Arduino)
#if defined(ESP32)
  #include "freertos/FreeRTOS.h"
  #include "freertos/task.h"
#endif

namespace {
  // Live config (not owned)
  const LoggerConfig* s_cfg = nullptr;

  // Run-state
  volatile bool   s_running       = false;
  unsigned long   s_intervalMs    = 1000;
  unsigned long   s_lastSample    = 0;     // only used in legacy loop() mode
  uint64_t        s_t0_ms         = 0;
  uint32_t        s_sampleCount   = 0;

  // Mark queue (single-producer, single-consumer)
  constexpr uint8_t MAX_MARKS = 8;
  volatile uint8_t  s_markHead = 0, s_markTail = 0;
  uint64_t          s_markTimes[MAX_MARKS];

  inline bool qEmpty() { return s_markHead == s_markTail; }
  inline bool qFull()  { return (uint8_t)(s_markHead + 1) % MAX_MARKS == s_markTail; }

  void enqueueNow() {
    uint8_t next = (uint8_t)(s_markHead + 1) % MAX_MARKS;
    if (next == s_markTail) return; // drop if full
    s_markTimes[s_markHead] = millis(); // or RTCManager_getEpochMs()
    s_markHead = next;
  }

  bool dequeue(uint64_t* t) {
    if (qEmpty()) return false;
    if (t) *t = s_markTimes[s_markTail];
    s_markTail = (uint8_t)(s_markTail + 1) % MAX_MARKS;
    return true;
  }

  // Primary pot instance (currently unused here; kept to preserve API)
  AnalogPotSensor* s_pot1 = nullptr;

  // ---- Task-based sampling (ESP32) ----
#if defined(ESP32)
  static TaskHandle_t s_sampleTask = nullptr;

  // Stats: how often the sampler task woke up "late"
  static uint32_t s_lateTicks    = 0;
  static uint32_t s_lateMaxLagMs = 0;
  static uint32_t s_missedSampleSlots = 0;

  static inline void resetLateStats_() {
    s_lateTicks = 0;
    s_lateMaxLagMs = 0;
    s_missedSampleSlots = 0;
  }

  // One sample, no scheduling logic (task provides cadence)
static inline void sampleOnce_() {
  if (!s_running) return;
  if (s_intervalMs < 1) return;
  if (s_intervalMs > 1000) return; // sanity, optional


  // --------- 1 Hz production-rate diagnostic ---------
  static uint32_t s_prodCount = 0;
  static uint32_t s_prodT0_ms = 0;
  if (s_prodT0_ms == 0) s_prodT0_ms = millis();
  ++s_prodCount;
  uint32_t now_ms = millis();
  if ((uint32_t)(now_ms - s_prodT0_ms) >= 1000) {
    PROD_LOGD("samples/s=%lu intervalMs=%u running=%d\n",
              (unsigned long)s_prodCount,
              (unsigned)s_intervalMs,
              (int)s_running);
    s_prodCount = 0;
    s_prodT0_ms = now_ms;
  }

  // --------- Deterministic timestamp for THIS sample (grid-aligned) ---------
  uint32_t intervalMs = s_intervalMs;
  if (intervalMs == 0) intervalMs = 1; // safety

  uint64_t ts_ms = s_t0_ms + (uint64_t)s_sampleCount * (uint64_t)intervalMs;
  const uint32_t sample_id = (uint32_t)s_sampleCount;
  ++s_sampleCount;

  // --------- Cache dynamic column count (avoid doing it at 500 Hz) ---------
  static uint16_t s_maxOutCached = 0;
  static uint32_t s_cacheT0_ms = 0;

  // Refresh cache occasionally (every ~1s) in case sensors change mid-run
  if (s_maxOutCached == 0 || (uint32_t)(now_ms - s_cacheT0_ms) >= 1000) {
    s_cacheT0_ms = now_ms;
    uint16_t cap = SensorManager::dynamicColumnCount(); // number of sensor columns (not including sample_id)
    if (cap > LoggerLimits::kMaxDynamicColumns) cap = LoggerLimits::kMaxDynamicColumns;
    s_maxOutCached = cap;
  }

  float values[LoggerLimits::kMaxDynamicColumns];
  uint16_t nWritten = 0;
  SensorManager::sampleValues(values, s_maxOutCached, nWritten);

  // --------- One mark per sample ---------
  uint64_t markTime = 0;
  bool markNow = dequeue(&markTime);

  // --------- Enqueue for StorageManager_loop() ---------
  (void)StorageManager_enqueueSample(sample_id, ts_ms, values, nWritten, markNow);
}


static void sampleTaskFn_(void* arg) {
  int64_t next_us = esp_timer_get_time();
  bool wasRunning = false;
  bool blockedBeforeSample = false;

  for (;;) {
    if (!s_running) {
      wasRunning = false;
      vTaskDelay(pdMS_TO_TICKS(10));
      continue;
    }

    if (!wasRunning) {
      wasRunning = true;
      next_us = esp_timer_get_time();
    }

    uint32_t intervalMs = s_intervalMs;
    if (intervalMs == 0) intervalMs = 1;
    const int64_t interval_us = (int64_t)intervalMs * 1000LL;
    blockedBeforeSample = false;

    // Wait for the next scheduled slot. If we are already late, skip missed
    // slots instead of trying to catch up with a no-yield burst of samples.
    for (;;) {
      int64_t now_us = esp_timer_get_time();
      int64_t remaining_us = next_us - now_us;

      if (remaining_us <= 0) {
        const int64_t lag_us = -remaining_us;
        if (lag_us >= 1000) {
          ++s_lateTicks;
          const uint32_t lag_ms = (uint32_t)((lag_us + 999LL) / 1000LL);
          if (lag_ms > s_lateMaxLagMs) s_lateMaxLagMs = lag_ms;
        }
        if (lag_us >= interval_us) {
          const uint32_t missed = (uint32_t)(lag_us / interval_us);
          s_missedSampleSlots += missed;
          s_sampleCount += missed;
          next_us += (int64_t)missed * interval_us;
        }
        break;
      }

      vTaskDelay(1);
      blockedBeforeSample = true;
    }

    sampleOnce_();

    next_us += interval_us;

    if (!blockedBeforeSample) {
      vTaskDelay(1);
    }
  }
}


#endif

  static inline uint32_t clampDiv_(uint32_t num, uint16_t den) {
    return (den == 0) ? 1000 : (num / den);
  }

} // anon

void LoggingManager::begin(const LoggerConfig* cfg) {
  s_cfg = cfg;
  s_intervalMs  = StorageManager_getSampleIntervalMs();
  s_lastSample  = 0;
  s_t0_ms       = 0;
  s_sampleCount = 0;
  s_markHead = s_markTail = 0;

#if defined(ESP32)
  resetLateStats_();
#endif
}

bool LoggingManager::start() {
  if (!s_cfg) return false;
  TRACE("enter start()");
  const uint32_t startT0 = millis();

  if (UploadModeManager::isActive()) {
    UI::toast("Upload mode", 1500, 2);
    UI::status("Upload mode");
    LOGGING_LOGW("start refused: upload mode active\n");
    return false;
  }

  if (!PowerManager::canStartLogging()) {
    UI::toast("Batt Low", 1500, 2);
    UI::status("Batt Low");
    LOGGING_LOGW("start refused: battery low or analog rail unavailable\n");
    return false;
  }

  if (!StorageManager_readyForLogging()) {
    UI::toast("SD missing", 1500, 1);
    UI::status("SD missing");
    LOGGING_LOGW("start refused: storage unavailable (%s)\n", StorageManager_lastStatus());
    return false;
  }

  // Pick up any sample-rate changes that were applied while logging was idle.
  s_intervalMs = StorageManager_getSampleIntervalMs();
  s_lastSample = 0;

  // Logging owns the device: take Wi-Fi (and therefore web server) down NOW.
  if (WebServerManager::isRunning()) {
    UI::println("Stopping web server for logging...", "", UI::TARGET_SERIAL, UI::LVL_INFO); // no delay
    WebServerManager::stop();
  }

  const uint32_t wifiOffT0 = millis();
  WiFiManager::suspendForLogging();   // synchronous OFF
  const uint32_t wifiOffMs = millis() - wifiOffT0;
  TRACE("stop webserver/wifi? (if any)");


  //PowerManager::setCpuFreqForLogging();

  //SensorManager::debugDump("before-header");

  // sampling cadence
  uint16_t requestedHz = s_cfg->sampleRateHz;
  const uint16_t syncCapHz = SensorManager::synchronousMaxSampleRateHz();
  if (syncCapHz != 0 && requestedHz > syncCapHz) {
    LOGGING_LOGW("Sample rate capped by synchronous sensor: requested=%u Hz cap=%u Hz\n",
                 (unsigned)requestedHz,
                 (unsigned)syncCapHz);
    requestedHz = syncCapHz;
  }
  StorageManager_setSampleRate(AnalogInputManager::configureFromConfig(*s_cfg, requestedHz));
  s_intervalMs = StorageManager_getSampleIntervalMs();

  TRACE("RTC sanity check begin");
  const bool rtcValid = RTCManager_hasValidTime();
  if (!rtcValid) {
    RTC_LOGW("start: RTC not valid; continuing with fallback filename/timestamps until resync\n");
  }
  TRACE("RTC sanity check done");

  // time anchors + grid align
  s_t0_ms = RTCManager_getEpochMs();
  unsigned long now = millis();
  s_lastSample = (s_intervalMs ? ((now / s_intervalMs) * s_intervalMs) : now);
  s_sampleCount = 0;

#if defined(ESP32)
  resetLateStats_();
#endif

  // Open/create log file
  TRACE("Entering storagemanager_startlog");
  const uint32_t storageT0 = millis();
  if (!StorageManager_startLog()) {
    WiFiManager::resumeAfterLogging();
    UI::toast("SD open fail", 1500, 1);
    UI::status("SD error");
    LOGGING_LOGW("start refused: StorageManager_startLog failed (%s)\n", StorageManager_lastStatus());
    return false;
  }
  const uint32_t storageMs = millis() - storageT0;
  TRACE("storagemanager_startlog complete");

  const uint32_t sensorStartT0 = millis();
  SensorManager::onLoggingStart();
  const uint32_t sensorStartMs = millis() - sensorStartT0;
  s_running = true;

#if defined(ESP32)
  // Start sampler task once (it loops forever; it will idle when not running)
  if (!s_sampleTask) {
    // Stack: 4096 is usually fine; bump to 6144/8192 if you add work
    xTaskCreatePinnedToCore(
      sampleTaskFn_,
      "SampleTask",
      4096,
      nullptr,
      3,          // priority: higher than UI/web loops
      &s_sampleTask,
      0           // core 1 keeps WiFi (often core 0) from interfering as much
    );
  }
#endif
  // turn LED on
  IndicatorManager::ledOn();
  TRACE("LED turned on");

  //UI::toast("Logging started");
  unsigned hz = s_intervalMs ? (1000UL / s_intervalMs) : 0;
  char st[24]; snprintf(st, sizeof(st), "Logging %uHz", hz);
  UI::status(String(st));
  LOGGING_LOGI("start timing: wifiOff=%lu ms storage=%lu ms sensors=%lu ms total=%lu ms rtcValid=%d\n",
               (unsigned long)wifiOffMs,
               (unsigned long)storageMs,
               (unsigned long)sensorStartMs,
               (unsigned long)(millis() - startT0),
               rtcValid ? 1 : 0);
  TRACE("exit start()");

  return true;
}

void LoggingManager::setSampleRateHz(uint16_t hz) {
  // snap to allowed values for safety
  int idx = Rates::indexOf(hz);
  if (idx < 0) return;
  ConfigManager::setSampleRateHz(hz);        // update + persist
  const uint16_t effectiveHz = AnalogInputManager::configureFromConfig(ConfigManager::get(), hz);
  StorageManager_setSampleRate(effectiveHz); // apply to the live logging cadence
  s_intervalMs = StorageManager_getSampleIntervalMs();

  // realign to grid to avoid jitter: next sample at now + interval
  uint32_t now = millis();
  s_lastSample = now - s_intervalMs;
}

LoggingManager::RuntimeStats LoggingManager::runtimeStats() {
  RuntimeStats out;
#if defined(ESP32)
  out.samplerLateTicks = s_lateTicks;
  out.samplerLateMaxLagMs = s_lateMaxLagMs;
  out.missedSampleSlots = s_missedSampleSlots;
#endif
  return out;
}

void LoggingManager::stop() {
  s_running = false;
  SensorManager::onLoggingStop();
  IndicatorManager::ledOff();
  StorageManager_stopLog();
  PowerManager::restoreCpuFreqAfterLogging();
  WiFiManager::resumeAfterLogging();

#if defined(ESP32)
  // Report task-lateness stats (these replace the old loop()-based lateTicks)
  LOGGING_LOGI("lateTicks=%lu maxLagMs=%lu\n",
               (unsigned long)s_lateTicks,
               (unsigned long)s_lateMaxLagMs);
  LOGGING_LOGI("missedSampleSlots=%lu\n",
               (unsigned long)s_missedSampleSlots);
#endif
}

bool LoggingManager::isRunning() {
  return s_running;
}

void LoggingManager::mark() {
  enqueueNow();
}
