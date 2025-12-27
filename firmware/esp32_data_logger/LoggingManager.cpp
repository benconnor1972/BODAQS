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

  static inline void resetLateStats_() {
    s_lateTicks = 0;
    s_lateMaxLagMs = 0;
  }

  // One sample, no scheduling logic (task provides cadence)
  static inline void sampleOnce_() {
    if (!s_running) return;

    // Deterministic timestamp for THIS sample (grid-aligned)
    uint64_t ts_ms = s_t0_ms + (uint64_t)s_sampleCount * s_intervalMs;
    s_sampleCount++;

    // Collect dynamic values from all sensors (+ sample_id first, per your SensorManager)
    const uint16_t cap = 1 + SensorManager::dynamicColumnCount();
    float values[32];
    uint16_t maxOut = (cap < 32) ? cap : 32;
    uint16_t nWritten = 0;
    SensorManager::sampleValues(values, maxOut, nWritten);

    // One mark per sample
    uint64_t _markTime = 0;
    bool _markNow = dequeue(&_markTime);

    // Non-blocking: enqueue row for StorageManager_loop() to consume/flush
    (void)StorageManager_enqueueSample(ts_ms, values, nWritten, _markNow);
  }

  static void sampleTaskFn_(void* arg) {
    // Ensure at least 1 tick
    TickType_t periodTicks = pdMS_TO_TICKS(s_intervalMs);
    if (periodTicks < 1) periodTicks = 1;

    TickType_t lastWake = xTaskGetTickCount();

    // Lag tracking in ms (coarse but useful)
    uint32_t expectedMs = millis();

    for (;;) {
      vTaskDelayUntil(&lastWake, periodTicks);

      // If stopped, park lightly rather than burning CPU.
      if (!s_running) {
        vTaskDelay(pdMS_TO_TICKS(10));
        expectedMs = millis();
        continue;
      }

      expectedMs += (uint32_t)s_intervalMs;
      uint32_t nowMs = millis();
      uint32_t lagMs = (nowMs >= expectedMs) ? (nowMs - expectedMs) : 0;

      // Count as "late" if we're >1 interval behind
      if (lagMs > s_intervalMs) {
        ++s_lateTicks;
        if (lagMs > s_lateMaxLagMs) s_lateMaxLagMs = lagMs;
      }

      sampleOnce_();
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

  // block if web server running (unchanged)
  if (WebServerManager::isRunning()) {
    UI::println("Refusing to start logging while web server is running.",
                "", UI::TARGET_SERIAL, UI::LVL_WARN);
    return false;
  }

  //PowerManager::setCpuFreqForLogging();

  SensorManager::debugDump("before-header");

  // sampling cadence
  s_intervalMs = StorageManager_getSampleIntervalMs();

  // sanity check RTC (unchanged)
  String ts;
  do { ts = RTCManager_getFastTimestamp(); delay(10); }
  while (ts.length() == 0 || ts.startsWith("0000-00-00"));

  // time anchors + grid align
  s_t0_ms = RTCManager_getEpochMs();
  unsigned long now = millis();
  s_lastSample = (s_intervalMs ? ((now / s_intervalMs) * s_intervalMs) : now);
  s_sampleCount = 0;

#if defined(ESP32)
  resetLateStats_();
#endif

  // Open/create log file
  StorageManager_startLog();

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
      1           // core 1 keeps WiFi (often core 0) from interfering as much
    );
  }
#endif
  // turn LED on
  IndicatorManager::ledOn();
  UI::println("Logging started.", "", UI::TARGET_SERIAL, UI::LVL_INFO, 1200);
  unsigned hz = s_intervalMs ? (1000UL / s_intervalMs) : 0;
  char st[24]; snprintf(st, sizeof(st), "Logging %uHz", hz);
  UI::status(String(st));
  return true;
}

void LoggingManager::setSampleRateHz(uint16_t hz) {
  // snap to allowed values for safety
  int idx = Rates::indexOf(hz);
  if (idx < 0) return;
  ConfigManager::setSampleRateHz(hz);        // update + persist
  s_intervalMs = clampDiv_(1000, hz);

  // realign to grid to avoid jitter: next sample at now + interval
  uint32_t now = millis();
  s_lastSample = now - s_intervalMs;
}

void LoggingManager::stop() {
  // Stop sampling first (prevents enqueues while we close files)
  s_running = false;
  // turn LED off
  IndicatorManager::ledOff();

  // Close log (and flush/drain in StorageManager if you implemented it)
  StorageManager_stopLog();

  PowerManager::restoreCpuFreqAfterLogging();

#if defined(ESP32)
  // Report task-lateness stats (these replace the old loop()-based lateTicks)
  Serial.printf("[Logging] lateTicks=%lu maxLagMs=%lu\n",
                (unsigned long)s_lateTicks,
                (unsigned long)s_lateMaxLagMs);
#endif
}

bool LoggingManager::isRunning() {
  return s_running;
}

// Legacy loop-based sampling (kept, but not used when the task is running)
void LoggingManager::loop() {
#if defined(ESP32)
  // If the sampler task exists, sampling is task-driven. Keep loop() light.
  if (s_sampleTask) return;
#endif

  if (!s_running) return;

  unsigned long now = millis();
  if (now - s_lastSample < s_intervalMs) return;
  s_lastSample += s_intervalMs;

  // Deterministic timestamp for THIS sample
  uint64_t ts_ms = s_t0_ms + (uint64_t)s_sampleCount * s_intervalMs;
  s_sampleCount++;

  // Collect dynamic values from all sensors
  const uint16_t cap = 1 + SensorManager::dynamicColumnCount();
  float values[32];
  uint16_t maxOut = (cap < 32) ? cap : 32;
  uint16_t nWritten = 0;
  SensorManager::sampleValues(values, maxOut, nWritten);

  // One mark per sample
  uint64_t _markTime = 0;
  bool _markNow = dequeue(&_markTime);

  // Non-blocking: enqueue for storage to consume
  (void)StorageManager_enqueueSample(ts_ms, values, nWritten, _markNow);
}

void LoggingManager::mark() {
  enqueueNow();
}
