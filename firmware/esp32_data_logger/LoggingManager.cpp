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

namespace {
  // Live config (not owned)
  const LoggerConfig* s_cfg = nullptr;

  // Run-state
  bool          s_running       = false;
  unsigned long s_intervalMs    = 1000;
  unsigned long s_lastSample    = 0;
  uint64_t      s_t0_ms         = 0;
  uint32_t      s_sampleCount   = 0;

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

  // Primary pot instance (for pot1 + optional "pot1_raw" column)
  AnalogPotSensor* s_pot1 = nullptr;
} // anon

void LoggingManager::attachPrimaryPot(AnalogPotSensor* pot) {
  s_pot1 = pot;
}

void LoggingManager::begin(const LoggerConfig* cfg) {
  s_cfg = cfg;
  s_intervalMs = StorageManager_getSampleIntervalMs();
  s_lastSample = 0;
  s_t0_ms      = 0;
  s_sampleCount = 0;
  s_markHead = s_markTail = 0;
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
  s_lastSample = (now / s_intervalMs) * s_intervalMs;
  s_sampleCount = 0;

  // Open/create log file (your function returns void)
  StorageManager_startLog();

  s_running = true;

  UI::println("Logging started.", "", UI::TARGET_SERIAL, UI::LVL_INFO, 1200);
  unsigned hz = s_intervalMs ? (1000UL / s_intervalMs) : 0;
  char st[24]; snprintf(st, sizeof(st), "Logging %uHz", hz);
  UI::status(String(st));
  return true;
}

static inline uint32_t clampDiv_(uint32_t num, uint16_t den) {
  return (den == 0) ? 1000 : (num / den);
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
  s_running = false;
  StorageManager_stopLog();
  PowerManager::restoreCpuFreqAfterLogging();
}

bool LoggingManager::isRunning() {
  return s_running;
}

void LoggingManager::loop() {
  if (!s_running) return;

  unsigned long now = millis();
  if (now - s_lastSample < s_intervalMs) return;
  s_lastSample += s_intervalMs;

  // Deterministic timestamp for THIS sample
  uint64_t ts_ms = s_t0_ms + (uint64_t)s_sampleCount * s_intervalMs;
  s_sampleCount++;

  // Collect dynamic values from all sensors (+ sample_id first)
  const uint16_t cap = 1 + SensorManager::dynamicColumnCount();
  float values[32];                        // plenty for current setup; bump if needed
  uint16_t maxOut = (cap < 32) ? cap : 32; // avoid overrun
  uint16_t nWritten = 0;
  SensorManager::sampleValues(values, maxOut, nWritten);

  // One mark per sample
  uint64_t _markTime = 0;
  bool _markNow = dequeue(&_markTime);

  // NEW: enqueue into StorageManager's sample queue; SD writes happen in background.
  bool ok = StorageManager_enqueueSample(ts_ms, values, nWritten, _markNow);
  if (!ok) {
    // Optional: count or occasionally log dropped samples
    // (left silent in hot path for now).
  }
}



void LoggingManager::mark() {
  enqueueNow();
}
