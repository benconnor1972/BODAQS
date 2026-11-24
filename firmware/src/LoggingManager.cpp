#include "CpuOccupancy.h"
#include <Arduino.h>
#include "LoggingManager.h"
#include "CanMasterManager.h"
#include "RemoteImuRecording.h"
#if defined(ESP32) && defined(BODAQS_PACKED_SEGMENTED_RECEIVER) && BODAQS_PACKED_SEGMENTED_RECEIVER
#include "AcquisitionControl.h"
#endif
#include "ButtonManager.h"
#include "StorageManager.h"
#include "RTCManager.h"
#include "WebServerManager.h"
#include "UI.h"
#include "DisplayManager.h"
#include "AnalogPotSensor.h"
#include "SensorManager.h"
#include "I2CManager.h"
#include "I2CBusScheduler.h"
#include "Rates.h"
#include "PowerManager.h"
#include "IndicatorManager.h"
#include "WiFiManager.h"
#include "UploadModeManager.h"
#include "AnalogInputManager.h"
#include "LocalRowHandoff.h"
#include <new>
#include "DebugTrace.h"
#include "esp_timer.h"
#include "DebugLog.h"
#include "LoggerLimits.h"
#include "FirmwareInfo.h"
#if BODAQS_ADC_RAW_RECORDING_BENCH && (!BODAQS_ADC_ROW_HANDOFF || !BODAQS_ADC_COMBINED_CAPTURE || !BODAQS_ADC_INLINE_ROW || !BODAQS_ADC_DUAL_SCAN_BENCH || !BODAQS_ADC_BOUNDARY_BENCH)
#error "Raw ADC trial requires the verified dual-scan inline owner"
#endif
#include <atomic>
#include <string.h>

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

  RecordingLifecycle s_lifecycle;
  using LifecycleState = RecordingLifecycle::State;
  bool phaseIs_(LifecycleState state) { return s_lifecycle.state() == state; }
#if defined(ESP32)
  TaskHandle_t s_lifecycleOwner = nullptr;
  bool isLifecycleOwner_() { return xTaskGetCurrentTaskHandle() == s_lifecycleOwner; }
#else
  bool isLifecycleOwner_() { return true; }
#endif
  bool s_localStopPending = false;
  bool retireLocalAcquisition_();
  bool s_remotePreparing = false;
  bool s_remoteFaultShown = false;
  unsigned stopPriority_(LoggingManager::StopReason reason) {
    using Reason = LoggingManager::StopReason;
    switch (reason) {
      case Reason::StorageUnresponsive: return 8;
      case Reason::StorageFailure: return 7;
      case Reason::SdCardRemoved: return 6;
      case Reason::AnalogRailFault: return 5;
      case Reason::StartFailure: return 4;
      case Reason::Unspecified: return 3;
      case Reason::SleepRequest: return 2;
      case Reason::UserRequest: return 1;
      default: return 0;
    }
  }
  // Run-state

  LoggingManager::StartFailureHint s_startFailureHint =
      LoggingManager::StartFailureHint::None;
  LoggingManager::StopContext s_stopContext;
#if defined(ESP32)
  portMUX_TYPE s_stopContextMux = portMUX_INITIALIZER_UNLOCKED;
#endif

  void captureStopContext_(
      LoggingManager::StopReason reason,
      const char* triggerEvent) {
    LoggingManager::StopContext context;
    context.reason = reason;
    context.uptimeMs = millis();
    context.triggerEvent = triggerEvent ? triggerEvent : "";
    context.sdDetectAvailable = StorageManager_cardDetectAvailable();
    context.sdCardDetected = StorageManager_cardDetectedCached();
    context.analogRailFault = PowerManager::analogRailFaultActive();
#if defined(ESP32)
    portENTER_CRITICAL(&s_stopContextMux);
#endif
    s_stopContext = context;
#if defined(ESP32)
    portEXIT_CRITICAL(&s_stopContextMux);
#endif
  }

  LoggingConfigIssue s_configurationIssue = LoggingConfigIssue::None;
  char s_configurationDetail[160] = {};
  uint32_t        s_intervalUs    = 1000000;
  uint64_t        s_t0UnixUs      = 0;
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
    s_markTimes[s_markHead] = static_cast<uint64_t>(esp_timer_get_time());
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
  static bool s_storageStartPending = false;
  static bool s_storageStopRequested = false;
  static std::atomic<bool> s_sampleInProgress{false};

  // Stats: how often the sampler task woke up "late"
  static uint32_t s_lateTicks    = 0;
  static uint32_t s_lateMaxLagMs = 0;
  static uint32_t s_lateMaxLagUs = 0;
  static uint32_t s_schedulerWakeups = 0;
  static uint32_t s_lateOverTenPercent = 0;
  static uint32_t s_missedSampleSlots = 0;
  static TimingSummary s_wakeLagUs;
  static TimingSummary s_sampleOnceUs;
  static TimingSummary s_sensorSampleUs;
  static TimingSummary s_enqueueUs;

  static constexpr int64_t kSamplerCoarseSleepThresholdUs = 500;
  static constexpr int64_t kSamplerFineWaitThresholdUs = 200;
  static constexpr int64_t kSamplerFineWaitGuardUs = 100;
  static constexpr int64_t kSamplerFineWaitMaxUs = 500;
  static constexpr int64_t kSamplerMaxNoBlockUs = 50000;

  static inline void resetLateStats_() {
    s_lateTicks = 0;
    s_lateMaxLagMs = 0;
    s_lateMaxLagUs = 0;
    s_schedulerWakeups = 0;
    s_lateOverTenPercent = 0;
    s_missedSampleSlots = 0;
#if BODAQS_TIMING_INSTRUMENTATION
    TimingStats_reset(s_wakeLagUs);
    TimingStats_reset(s_sampleOnceUs);
    TimingStats_reset(s_sensorSampleUs);
    TimingStats_reset(s_enqueueUs);
#endif
  }

  // One sample, no scheduling logic (task provides cadence)
#if BODAQS_ADC_ROW_HANDOFF
#ifndef BODAQS_ADC_INLINE_ROW
#define BODAQS_ADC_INLINE_ROW 0
#endif
#if BODAQS_ADC_INLINE_ROW != 0 && BODAQS_ADC_INLINE_ROW != 1
#error "Inline row assembly must be 0 or 1"
#endif
#if BODAQS_ADC_INLINE_ROW && !BODAQS_ADC_COMBINED_CAPTURE
#error "Inline row assembly requires verified-pair capture"
#endif
struct RowHandoffState {
  TaskHandle_t worker = nullptr;
  #if !BODAQS_ADC_INLINE_ROW
  LocalRowQueue<8> queue;
  #endif
  portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
  bool busy = false;
  uint32_t captured=0, assembled=0, queueDrops=0, markDrops=0, enqueued=0, enqueueFailed=0;
  uint32_t queuePeak=0, delayMaxUs=0, captureMaxUs=0;
  uint64_t delayTotalUs=0;
#if BODAQS_ADC_COMBINED_CAPTURE
  uint64_t combinedNextUs=0;
#endif
  uint32_t prodCount=0, prodT0Ms=0, columnCacheT0Ms=0;
  uint16_t maxOutCached=0;
};
static RowHandoffState* s_rowHandoff = nullptr;
static void resetRowSessionCaches_() {
  s_rowHandoff->prodCount=0;s_rowHandoff->prodT0Ms=0;
  s_rowHandoff->columnCacheT0Ms=0;s_rowHandoff->maxOutCached=0;
}
static inline bool sampleOnce_ (bool allowStopped, const LocalRowFrame* frame);
static bool captureRow_() {
  if (!phaseIs_(LifecycleState::Recording)) return false;
  const uint32_t began = micros();
#if BODAQS_ADC_RAW_RECORDING_BENCH
  RawAdcRecord record;record.sequence=static_cast<uint32_t>(s_sampleCount++);
  uint64_t capturedUs=0;
  const uint32_t captureBegin=micros();
  if(!AnalogInputManager::captureRawPair(record,capturedUs))return false;
#if BODAQS_TIMING_INSTRUMENTATION
  TimingStats_record(s_sensorSampleUs,uint32_t(micros()-captureBegin));
#endif
  uint64_t markTime=0;const bool marked=dequeue(&markTime);
  ++s_rowHandoff->captured;
  const uint32_t enqueueBegin=micros();
  const bool accepted=StorageManager_enqueueRawAdc(record,marked,markTime,capturedUs);
#if BODAQS_TIMING_INSTRUMENTATION
  TimingStats_record(s_enqueueUs,uint32_t(micros()-enqueueBegin));
  TimingStats_record(s_sampleOnceUs,uint32_t(micros()-began));
#endif
  if(accepted)++s_rowHandoff->enqueued;
  else {++s_rowHandoff->enqueueFailed;if(marked)++s_rowHandoff->markDrops;}
  ++s_rowHandoff->assembled; // Compatibility counter: one raw record submitted.
#else
  LocalRowFrame frame;
  frame.sampleId = static_cast<uint32_t>(s_sampleCount++);
  frame.scheduledUnixUs = Rates::scheduledTimeUs(s_t0UnixUs,frame.sampleId,s_intervalUs);
  if (!AnalogInputManager::captureRowSnapshot(frame.adc)) return false;
  frame.marked = dequeue(&frame.markTime);
  ++s_rowHandoff->captured;
#if BODAQS_ADC_INLINE_ROW
  // Pair has been verified and next conversion started; no SPI/cache lock held.
  // The frame stays owned on this task's stack until storage enqueue returns.
  if (sampleOnce_(true,&frame)) ++s_rowHandoff->enqueued;
  else ++s_rowHandoff->enqueueFailed;
  ++s_rowHandoff->assembled;
#else
  portENTER_CRITICAL(&s_rowHandoff->mux);
  const bool accepted = s_rowHandoff->queue.push(frame);
  if (s_rowHandoff->queue.size() > s_rowHandoff->queuePeak) s_rowHandoff->queuePeak = s_rowHandoff->queue.size();
  portEXIT_CRITICAL(&s_rowHandoff->mux);
  if (accepted) xTaskNotifyGive(s_rowHandoff->worker);
  else { ++s_rowHandoff->queueDrops; if (frame.marked) ++s_rowHandoff->markDrops; }
  #endif
#endif
  const uint32_t elapsed = micros()-began;
  if(elapsed>s_rowHandoff->captureMaxUs)s_rowHandoff->captureMaxUs=elapsed;
  return true;
}
#endif
#if BODAQS_ADC_COMBINED_CAPTURE
static bool combinedCaptureRow_() {
  s_sampleInProgress.store(true);
  if(!phaseIs_(LifecycleState::Recording)) {s_sampleInProgress.store(false);return true;}
  const uint64_t now=static_cast<uint64_t>(esp_timer_get_time());
#if BODAQS_PRODUCTION_RECORDING
  uint32_t sequence = 0, missed = 0;
  uint64_t scheduled = 0;
  if (!AnalogInputManager::recordingRowTiming(sequence, missed, scheduled)) {
    s_sampleInProgress.store(false);
    return false;
  }
  s_sampleCount = sequence;
  s_missedSampleSlots += missed;
  const uint64_t lag = now > scheduled ? now - scheduled : 0;
#else
  if(!s_rowHandoff->combinedNextUs)s_rowHandoff->combinedNextUs=now;
  const uint64_t lag=now>s_rowHandoff->combinedNextUs?now-s_rowHandoff->combinedNextUs:0;
  const uint32_t missed=Rates::missedSlots(lag,s_intervalUs);
  s_sampleCount+=missed;s_missedSampleSlots+=missed;
  s_rowHandoff->combinedNextUs+=uint64_t(missed)*s_intervalUs;
#endif
  ++s_schedulerWakeups;
  const uint32_t bounded=lag>UINT32_MAX?UINT32_MAX:static_cast<uint32_t>(lag);
  if(bounded>s_lateMaxLagUs)s_lateMaxLagUs=bounded;
  if(lag>s_intervalUs/10u)++s_lateOverTenPercent;
  if(lag>=1000){++s_lateTicks;if((lag+999)/1000>s_lateMaxLagMs)s_lateMaxLagMs=(lag+999)/1000;}
  const bool ok=captureRow_();
  s_rowHandoff->combinedNextUs+=s_intervalUs;
  s_sampleInProgress.store(false);
  return ok;
}
#endif
static inline bool sampleOnce_(bool allowStopped = false, const LocalRowFrame* frame = nullptr) {
  if (!phaseIs_(LifecycleState::Recording) && !allowStopped) return false;
  if (s_intervalUs < 1 || s_intervalUs > 1000000UL) return false;


  // --------- 1 Hz production-rate diagnostic ---------
#if BODAQS_ADC_ROW_HANDOFF
  if (!s_rowHandoff) return false;
  auto& s_prodCount=s_rowHandoff->prodCount;
  auto& s_prodT0_ms=s_rowHandoff->prodT0Ms;
#else
  static uint32_t s_prodCount = 0;
  static uint32_t s_prodT0_ms = 0;
#endif
  if (s_prodT0_ms == 0) s_prodT0_ms = millis();
  ++s_prodCount;
  uint32_t now_ms = millis();
  if ((uint32_t)(now_ms - s_prodT0_ms) >= 1000) {
    PROD_LOGD("samples/s=%lu intervalUs=%lu running=%d\n",
              (unsigned long)s_prodCount,
              (unsigned long)s_intervalUs,
              (int)phaseIs_(LifecycleState::Recording));
    s_prodCount = 0;
    s_prodT0_ms = now_ms;
  }
#if BODAQS_TIMING_INSTRUMENTATION
  const uint32_t sampleT0 = micros();
#endif

  // --------- Deterministic timestamp for THIS sample (grid-aligned) ---------
  const uint64_t scheduledUnixUs =
      frame ? frame->scheduledUnixUs : Rates::scheduledTimeUs(s_t0UnixUs, s_sampleCount, s_intervalUs);
  const uint64_t ts_ms = scheduledUnixUs / 1000ULL;
  const uint32_t sample_id = frame ? frame->sampleId : (uint32_t)s_sampleCount;
  if (!frame) ++s_sampleCount;

  // --------- Cache dynamic column count (avoid doing it at 500 Hz) ---------
#if BODAQS_ADC_ROW_HANDOFF
  auto& s_maxOutCached=s_rowHandoff->maxOutCached;
  auto& s_cacheT0_ms=s_rowHandoff->columnCacheT0Ms;
#else
  static uint16_t s_maxOutCached = 0;
  static uint32_t s_cacheT0_ms = 0;
#endif

  // Refresh cache occasionally (every ~1s) in case sensors change mid-run
  const bool independentStreams =
      s_cfg && s_cfg->logFormat == LogFormat::BodaqsMultiStreamBinary;
  if (frame) {
    s_maxOutCached=SensorManager::recordingColumnCapacity(independentStreams);
    if(s_maxOutCached>LoggerLimits::kMaxDynamicColumns)s_maxOutCached=LoggerLimits::kMaxDynamicColumns;
  } else if (s_cacheT0_ms == 0 || (uint32_t)(now_ms - s_cacheT0_ms) >= 1000) {
    s_cacheT0_ms = now_ms;
    uint16_t cap = SensorManager::dynamicColumnCount(independentStreams);
    if (cap > LoggerLimits::kMaxDynamicColumns) cap = LoggerLimits::kMaxDynamicColumns;
    s_maxOutCached = cap;
  }

  float values[LoggerLimits::kMaxDynamicColumns];
  uint16_t nWritten = 0;
#if BODAQS_TIMING_INSTRUMENTATION
  const uint32_t sensorT0 = micros();
#endif
  const uint64_t hostMonotonicUs =
      frame ? frame->adc.capturedUs : static_cast<uint64_t>(esp_timer_get_time());
#if BODAQS_ADC_ROW_HANDOFF
  AnalogInputManager::useRowSnapshot(frame ? &frame->adc : nullptr);
#endif
  if(frame)SensorManager::sampleRowValues(values,s_maxOutCached,nWritten,independentStreams,frame->adc);
  else SensorManager::sampleValues(values,s_maxOutCached,nWritten,independentStreams);
#if BODAQS_ADC_ROW_HANDOFF
  AnalogInputManager::useRowSnapshot(nullptr);
#endif
#if BODAQS_TIMING_INSTRUMENTATION
  TimingStats_record(s_sensorSampleUs, (uint32_t)(micros() - sensorT0));
#endif

  // --------- One mark per sample ---------
  uint64_t markTime = frame ? frame->markTime : 0;
  bool markNow = frame ? frame->marked : dequeue(&markTime);

#if BODAQS_ADC_CONTINUOUS_LATEST
  if (!frame) {
    if(!AnalogInputManager::continuousHealthy())return false;
  }
#endif
  // --------- Enqueue for StorageManager_loop() ---------
#if BODAQS_TIMING_INSTRUMENTATION
  const uint32_t enqueueT0 = micros();
#endif
  const bool enqueued = StorageManager_enqueueSample(
      sample_id,
      ts_ms,
      values,
      nWritten,
      markNow,
      hostMonotonicUs,
      markNow ? markTime : 0);
#if BODAQS_TIMING_INSTRUMENTATION
  TimingStats_record(s_enqueueUs, (uint32_t)(micros() - enqueueT0));
  TimingStats_record(s_sampleOnceUs, (uint32_t)(micros() - sampleT0));
#endif
  return enqueued;
}


#if BODAQS_ADC_ROW_HANDOFF && !BODAQS_ADC_INLINE_ROW
static void rowAssemblyTaskFn_(void*) {
  for (;;) {
    (void)ulTaskNotifyTake(pdTRUE,portMAX_DELAY);
    unsigned burst = 0;
    for (;;) {
      LocalRowFrame frame;
      portENTER_CRITICAL(&s_rowHandoff->mux);
      const bool have = s_rowHandoff->queue.pop(frame);
      s_rowHandoff->busy = have;
      portEXIT_CRITICAL(&s_rowHandoff->mux);
      if (!have) break;
      const uint64_t delay = static_cast<uint64_t>(esp_timer_get_time())-frame.adc.capturedUs;
      s_rowHandoff->delayTotalUs += delay;
      if (delay>s_rowHandoff->delayMaxUs) s_rowHandoff->delayMaxUs = delay>UINT32_MAX ? UINT32_MAX : delay;
      if (sampleOnce_(true,&frame)) ++s_rowHandoff->enqueued;
      else ++s_rowHandoff->enqueueFailed; // Storage failure is accounted separately from upstream drops.
      ++s_rowHandoff->assembled;
      portENTER_CRITICAL(&s_rowHandoff->mux);
      s_rowHandoff->busy = false;
      portEXIT_CRITICAL(&s_rowHandoff->mux);
      if (++burst == 4) {burst = 0;vTaskDelay(1);} // Bound P3 bursts; let storage/idle run under overload.
    }
  }
}
#endif

#ifndef BODAQS_ADC_ROW_COOPERATIVE_WAIT
#define BODAQS_ADC_ROW_COOPERATIVE_WAIT 0
#endif
#if BODAQS_ADC_ROW_COOPERATIVE_WAIT != 0 && BODAQS_ADC_ROW_COOPERATIVE_WAIT != 1
#error "ADC row cooperative wait must be 0 or 1"
#endif
#if BODAQS_ADC_ROW_COOPERATIVE_WAIT && !BODAQS_ADC_ROW_PACING
#error "ADC row cooperative wait requires row pacing"
#endif
#ifndef BODAQS_ADC_ROW_BLOCKED_WAIT
#define BODAQS_ADC_ROW_BLOCKED_WAIT 0
#endif
#if BODAQS_ADC_ROW_BLOCKED_WAIT != 0 && BODAQS_ADC_ROW_BLOCKED_WAIT != 1
#error "ADC row blocked wait must be 0 or 1"
#endif
#if BODAQS_ADC_ROW_BLOCKED_WAIT && !BODAQS_ADC_ROW_PACING && !BODAQS_ADC_CONTINUOUS_LATEST
#error "ADC blocked wait requires row pacing or continuous latest"
#endif
#if BODAQS_ADC_ROW_BLOCKED_WAIT
static esp_timer_handle_t s_rowSampleTimer=nullptr;
static void rowSampleTick_(void* argument) {
  // The sampler task persists across recordings. No callback rearms the timer.
  xTaskNotifyGive(static_cast<TaskHandle_t>(argument));
}
static bool sampleWaitAppointment_(int64_t deadline,bool* blocked=nullptr) {
  if(blocked)*blocked=false;
  if(!phaseIs_(LifecycleState::Recording) || esp_timer_get_time()>=deadline)return true;
  if(!s_rowSampleTimer) {
    esp_timer_create_args_t args={};args.callback=rowSampleTick_;
    args.arg=xTaskGetCurrentTaskHandle();args.name="row_sample";
    if(esp_timer_create(&args,&s_rowSampleTimer)!=ESP_OK) {
      LOGGING_LOGE("row sample timer creation failed\n");return false;
    }
  }
  (void)esp_timer_stop(s_rowSampleTimer);
  (void)ulTaskNotifyTake(pdTRUE,0); // discard a previous appointment's pulse
  while(phaseIs_(LifecycleState::Recording)) {
    const int64_t remaining=deadline-esp_timer_get_time();
    if(remaining<=0)return true;
    if(esp_timer_start_once(s_rowSampleTimer,static_cast<uint64_t>(remaining))!=ESP_OK) {
      LOGGING_LOGE("row sample timer arm failed\n");return false;
    }
    // STOP also notifies this task. A bounded timeout exposes timer failure;
    // it is not a polling interval or a substitute sampling schedule.
    if(blocked)*blocked=true;
    const auto notified=ulTaskNotifyTake(pdTRUE,pdMS_TO_TICKS(10)+1);
    (void)esp_timer_stop(s_rowSampleTimer);
    if(!phaseIs_(LifecycleState::Recording))return true;
    if(!notified){LOGGING_LOGE("row sample timer notification timeout\n");return false;}
    // A stale/early notification cannot move the row before its deadline.
  }
  return true;
}
#endif
static int64_t sampleWaitNow_(int64_t deadline) {
  int64_t now=esp_timer_get_time();
#if BODAQS_ADC_ROW_COOPERATIVE_WAIT
  // Equal-priority ADC workers cannot preempt this sampler's fine waits.
  // Let ready peers run; reread time because yielding may cross the deadline.
  if(now<deadline){taskYIELD();now=esp_timer_get_time();}
#else
  (void)deadline;
#endif
  return now;
}

static void sampleTaskFn_(void* arg) {
  int64_t next_us = esp_timer_get_time();
  int64_t lastBlockUs = next_us;
  bool wasRunning = false;

  for (;;) {
    if (!phaseIs_(LifecycleState::Recording)
#if BODAQS_ADC_COMBINED_CAPTURE
        || AnalogInputManager::rowHandoffActive()
#endif
        ) {
      wasRunning = false;
      vTaskDelay(pdMS_TO_TICKS(10));
      lastBlockUs = esp_timer_get_time();
      continue;
    }

    if (!wasRunning) {
      wasRunning = true;
      next_us = esp_timer_get_time();
#if BODAQS_ADC_SCAN_ROW_PHASE
      s_sampleInProgress.store(true);
      const bool phaseActive=phaseIs_(LifecycleState::Recording) && AnalogInputManager::scanRowPhaseActive();
      s_sampleInProgress.store(false);
      if(!phaseIs_(LifecycleState::Recording))continue;
      if(phaseActive) {
        const int64_t limit=next_us+100000;
        bool ready=false;
        while(phaseIs_(LifecycleState::Recording) && esp_timer_get_time()<limit) {
          s_sampleInProgress.store(true);
          ready=phaseIs_(LifecycleState::Recording) && AnalogInputManager::scanRowDeadline(esp_timer_get_time(),next_us);
          s_sampleInProgress.store(false);
          if(ready || !phaseIs_(LifecycleState::Recording))break;
          vTaskDelay(1);
        }
        if(!phaseIs_(LifecycleState::Recording))continue;
        if(!ready){LoggingManager::stop(LoggingManager::StopReason::StartFailure,"adc_phase_handshake");continue;}
      }
#endif
#if BODAQS_ADC_ROW_PACING
      s_sampleInProgress.store(true);
      next_us=phaseIs_(LifecycleState::Recording)?AnalogInputManager::beginRowPacing():0;
      s_sampleInProgress.store(false);
      if(!next_us){if(phaseIs_(LifecycleState::Recording))LoggingManager::stop(LoggingManager::StopReason::StartFailure,"adc_row_pacing");continue;}
#endif
      lastBlockUs = next_us;
    }

    uint32_t intervalUs = s_intervalUs;
    if (intervalUs == 0) intervalUs = 1;
    const int64_t interval_us = static_cast<int64_t>(intervalUs);

#if BODAQS_ADC_ROW_BLOCKED_WAIT
    // STOP wakes this wait before waiting on the same startup/row guard.
    s_sampleInProgress.store(true);
    bool blockedForRow=false;
    const bool appointmentReady=sampleWaitAppointment_(next_us,&blockedForRow);
    s_sampleInProgress.store(false);
    if(!appointmentReady) {
      if(phaseIs_(LifecycleState::Recording))LoggingManager::stop(LoggingManager::StopReason::StartFailure,"adc_row_wait");
      continue;
    }
    if(!phaseIs_(LifecycleState::Recording))continue;
    if(blockedForRow)lastBlockUs=esp_timer_get_time(); // preserve overdue-row watchdog safeguard
#endif

    // Wait for the next scheduled slot. If we are already late, skip missed
    // slots instead of trying to catch up with a no-yield burst of samples.
    for (;;) {
      int64_t now_us = sampleWaitNow_(next_us);
      int64_t remaining_us = next_us - now_us;

      if (remaining_us <= 0) {
        const int64_t lag_us = -remaining_us;
        const uint32_t boundedLagUs = lag_us > UINT32_MAX
            ? UINT32_MAX
            : static_cast<uint32_t>(lag_us);
        ++s_schedulerWakeups;
        if (boundedLagUs > s_lateMaxLagUs) s_lateMaxLagUs = boundedLagUs;
#if BODAQS_TIMING_INSTRUMENTATION
        TimingStats_record(s_wakeLagUs, boundedLagUs);
#endif
        const uint32_t tenPercentUs = intervalUs >= 10 ? intervalUs / 10u : 1u;
        if (boundedLagUs > tenPercentUs) ++s_lateOverTenPercent;
        if (lag_us >= 1000) {
          ++s_lateTicks;
          const uint32_t lag_ms = (uint32_t)((lag_us + 999LL) / 1000LL);
          if (lag_ms > s_lateMaxLagMs) s_lateMaxLagMs = lag_ms;
        }
        if (lag_us >= interval_us) {
          const uint32_t missed = Rates::missedSlots(
              static_cast<uint64_t>(lag_us), intervalUs);
          s_missedSampleSlots += missed;
          s_sampleCount += missed;
          next_us += (int64_t)missed * interval_us;
        }
        break;
      }

      if (remaining_us > kSamplerCoarseSleepThresholdUs) {
        vTaskDelay(1);
        lastBlockUs = esp_timer_get_time();
      } else if ((now_us - lastBlockUs) >= kSamplerMaxNoBlockUs &&
                 remaining_us > kSamplerFineWaitThresholdUs) {
        // At high sample rates the task can spend long stretches in sub-tick
        // waits. Take a real RTOS sleep periodically so CPU0's idle task can
        // feed the watchdog, even if that costs a little sampling lateness.
        vTaskDelay(1);
        lastBlockUs = esp_timer_get_time();
      } else if (remaining_us > kSamplerFineWaitThresholdUs) {
        int64_t delay_us = remaining_us - kSamplerFineWaitGuardUs;
        if (delay_us > kSamplerFineWaitMaxUs) delay_us = kSamplerFineWaitMaxUs;
        if (delay_us > 0) delayMicroseconds((uint32_t)delay_us);
      } else {
        // Close to the deadline: stay on-core rather than risking a full RTOS
        // tick of oversleep. Logging mode has Wi-Fi down, so this short spin is
        // preferable to drifting a 2 ms sampling cadence.
      }
    }

    s_sampleInProgress.store(true);
#if BODAQS_ADC_ROW_HANDOFF
    const bool handoffActive = AnalogInputManager::rowHandoffActive();
    const bool captured = handoffActive ? captureRow_() : (sampleOnce_(),true);
#else
    (void)sampleOnce_();
#endif
    s_sampleInProgress.store(false);
#if BODAQS_ADC_ROW_HANDOFF
    if (phaseIs_(LifecycleState::Recording) && !captured) {LoggingManager::stop(LoggingManager::StopReason::StartFailure,"row_capture");continue;}
#endif
#if BODAQS_ADC_CONTINUOUS_LATEST
    if(phaseIs_(LifecycleState::Recording) && !AnalogInputManager::continuousHealthy()) {
      LoggingManager::stop(LoggingManager::StopReason::Unspecified,"adc_continuous_fault");continue;
    }
#endif

    const int64_t afterSampleUs = esp_timer_get_time();
    if ((afterSampleUs - lastBlockUs) >= kSamplerMaxNoBlockUs) {
      vTaskDelay(1);
      lastBlockUs = esp_timer_get_time();
    }

    next_us += interval_us;
  }
}


#endif

} // anon

void LoggingManager::begin(const LoggerConfig* cfg) {
#if defined(ESP32)
  s_lifecycleOwner = xTaskGetCurrentTaskHandle();
#endif
  s_cfg = cfg;
  s_intervalUs  = StorageManager_getSampleIntervalUs();
  s_t0UnixUs    = 0;
  s_sampleCount = 0;
  s_markHead = s_markTail = 0;
  refreshConfigurationStatus();

#if defined(ESP32)
  resetLateStats_();
#endif
}

void LoggingManager::refreshConfigurationStatus() {
  if (!s_cfg || phaseIs_(LifecycleState::Recording)) return;
  if(ConfigManager::migrationPending()) {
    s_configurationIssue=LoggingConfigIssue::InvalidConfig;
    snprintf(s_configurationDetail,sizeof(s_configurationDetail),"Review and accept production configuration migration in Settings / Log format or web config");
    return;
  }
  const String blocker=ConfigManager::configurationBlocker();
  if(blocker.length()) {s_configurationIssue=LoggingConfigIssue::InvalidConfig;snprintf(s_configurationDetail,sizeof(s_configurationDetail),"%s",blocker.c_str());return;}
  char detail[sizeof(s_configurationDetail)] = {};
  const auto issue = SensorManager::configurationIssue(*s_cfg, detail, sizeof(detail));
  if (issue != s_configurationIssue || strcmp(detail, s_configurationDetail) != 0) {
    LOGGING_LOGI("configuration status=%u detail=%s\n", (unsigned)issue, detail);
    s_configurationIssue = issue;
    snprintf(s_configurationDetail, sizeof(s_configurationDetail), "%s", detail);
  }
}

LoggingConfigIssue LoggingManager::configurationIssue() { return s_configurationIssue; }
const char* LoggingManager::configurationDetail() { return s_configurationDetail; }

bool LoggingManager::isStarting() { return phaseIs_(LifecycleState::Preparing); }
void LoggingManager::cancelStart() {
  if (!isLifecycleOwner_()) {
    s_lifecycle.requestStop(static_cast<uint8_t>(StopReason::UserRequest));
    return;
  }
  if(phaseIs_(LifecycleState::Preparing) && RemoteImuRecording::configured()) {
    s_lifecycle.publish(LifecycleState::Stopping);s_remotePreparing=false;
    RemoteImuRecording::stop();
    s_localStopPending = true;
    UI::status("Finalizing recording");
    return;
  }
#if defined(ESP32)
  if (phaseIs_(LifecycleState::Preparing) && (s_storageStartPending || StorageManager_recordingIoPending())) {
    s_storageStartPending = false;
    s_lifecycle.publish(LifecycleState::Stopping);
    s_localStopPending = true;
    // The initialized native sensors may produce a final FIFO tail at STOP.
    // Retire them before allowing the worker to freeze footer diagnostics.
    s_storageStopRequested = false;
    return;
  }
#endif
  if (!phaseIs_(LifecycleState::Preparing)) return;
  CanMasterManager::endRecordingHandoff();
  s_lifecycle.publish(CanMasterManager::recordingHandoffActive()
      ? LifecycleState::Uncertain : LifecycleState::Completed);
}
LoggingManager::LifecycleState LoggingManager::lifecycleState() { return s_lifecycle.state(); }
const char* LoggingManager::lifecycleStateName() { return RecordingLifecycle::name(lifecycleState()); }
bool LoggingManager::configurationLocked() {
  return s_lifecycle.busy() || CanMasterManager::recordingHandoffActive()
#if defined(ESP32)
      || StorageManager_recordingIoPending()
#endif
      ;
}

LoggingManager::StartResult LoggingManager::requestStart() {
  if (!isLifecycleOwner_()) return StartResult::Failed;
  if(ConfigManager::configurationBlocker().length()) { UI::status(ConfigManager::configurationBlocker()); refreshConfigurationStatus(); return StartResult::Failed; }
  if (phaseIs_(LifecycleState::Recording)) return StartResult::Started;
  if ((phaseIs_(LifecycleState::Stopping) || phaseIs_(LifecycleState::Finalizing))) return StartResult::Failed;
  // A completed file must not turn a failed ownership handoff into an
  // indefinitely pending START. Ordinary in-progress starts retain their fence.
  if (!phaseIs_(LifecycleState::Preparing) && configurationLocked()) return StartResult::Failed;
  if (!phaseIs_(LifecycleState::Preparing)) {
    s_lifecycle.publish(LifecycleState::Preparing);
    CanMasterManager::beginRecordingHandoff();
  }
  if (!CanMasterManager::recordingHandoffReady()) {
    UI::status("Preparing logging");
    return StartResult::Pending;
  }
  if (start()) return StartResult::Started;
  return phaseIs_(LifecycleState::Preparing) ? StartResult::Pending : StartResult::Failed;
}

void LoggingManager::loop() {
  if (!isLifecycleOwner_()) return;
  // Consume a bounded set, including simultaneous faults. Storage faults win
  // over operator cancellation; no producer-owned string is retained.
  const uint32_t requests = s_lifecycle.takeStopRequests();
  auto selected = StopReason::None;
  for (int reason = static_cast<int>(StopReason::StorageUnresponsive); reason > 0; --reason) {
    const auto candidate = static_cast<StopReason>(reason);
    if ((requests & (uint32_t{1} << reason)) && stopPriority_(candidate) > stopPriority_(selected))
      selected = candidate;
  }
  if (selected != StopReason::None) stop(selected, "producer_stop_request");
#if BODAQS_ADC_COMBINED_CAPTURE
  if(phaseIs_(LifecycleState::Recording) && !AnalogInputManager::continuousHealthy()) {
    stop(StopReason::Unspecified,"combined_adc_capture_fault");
  }
#endif
  // Remote STOP/lease cleanup must progress even when a local callback has
  // not yet retired; neither owner may wait on the other's I/O.
  RemoteImuRecording::service();
  if (s_localStopPending) {
    if (!retireLocalAcquisition_()) return;
    s_localStopPending = false;
  }
  if ((phaseIs_(LifecycleState::Recording) || phaseIs_(LifecycleState::Preparing)) &&
      RemoteImuRecording::sharedIntegrityFault()) {
    stop(StopReason::Unspecified, "shared_recording_integrity_fault");
    return; // Local retirement precedes all footer/finalization work.
  }
  if (phaseIs_(LifecycleState::Uncertain)) {
    // The file and native diagnostics have already retired. Continue only the
    // retained control handoff; repeating finishStorageStop() would finalize
    // sensor queues and restore peripherals twice.
#if defined(ESP32)
    if (StorageManager_recordingIoPending()) return;
#endif
    if (!RemoteImuRecording::stopped()) return;
    RemoteImuRecording::release();
    CanMasterManager::endRecordingHandoff();
    if (CanMasterManager::recordingHandoffActive()) return;
    const auto reason = s_stopContext.reason;
    s_lifecycle.publish(reason == StopReason::UserRequest || reason == StopReason::SleepRequest || reason == StopReason::None
        ? LifecycleState::Completed : LifecycleState::Failed);
    UI::status(phaseIs_(LifecycleState::Failed) ? "Recording failed; cleanup complete" : "Recording finalized");
    return;
  }
  if(phaseIs_(LifecycleState::Recording) && RemoteImuRecording::failed() && !s_remoteFaultShown) {
    s_remoteFaultShown=true;UI::toast(RemoteImuRecording::failureReason(),1800,1);
  }
  if(phaseIs_(LifecycleState::Preparing) && s_remotePreparing) {
    if(RemoteImuRecording::failed() && !s_remoteFaultShown) {
      s_remoteFaultShown=true;UI::toast(RemoteImuRecording::failureReason(),1800,1);
    }
#if defined(ESP32)
    if(!StorageManager_recordingReady()) {
      if(!StorageManager_recordingIoPending()) stop(StopReason::StartFailure,"storage_start_failure");
      return;
    }
#endif
#if defined(ESP32)
    const auto allocation=StorageManager_recordingAllocation();
    const size_t storageBytes=allocation.primaryQueueBytes+allocation.workspaceBytes+
        allocation.outputBufferBytes+allocation.catalogPeakBytes+allocation.primaryColumnsPeakBytes+
        allocation.metadataPayloadBytes+allocation.staticStateBytes+allocation.storageTaskStackBytes;
    RemoteImuRecording::resourcesReady(storageBytes);
#else
    RemoteImuRecording::resourcesReady();
#endif
    if(!RemoteImuRecording::prepared()) return;
    s_remotePreparing=false;
#if defined(ESP32)
    s_storageStartPending=true;s_storageStopRequested=false;
#else
    RemoteImuRecording::start();
#endif
    return;
  }
#if defined(ESP32)
  if ((phaseIs_(LifecycleState::Stopping) || phaseIs_(LifecycleState::Finalizing))) {
    if(!RemoteImuRecording::tailDrained()) return;
    if(!RemoteImuRecording::readyForFileFinalization()) return;
    if (!StorageManager_recordingIoPending()) { finishStorageStop(); return; }
    if (s_storageStopRequested) return;
    s_lifecycle.publish(LifecycleState::Finalizing);
    if (!StorageManager_storageFault() && !StorageManager_usesIndependentStreams()) {
      for (unsigned i = 0; i < 8 && SensorManager::pendingLoggingRows(); ++i) {
        if (!StorageManager_canAcceptSample()) return;
        const size_t before = SensorManager::pendingLoggingRows();
        if (!sampleOnce_(true) || SensorManager::pendingLoggingRows() >= before) {
          s_storageStopRequested = true;
          StorageManager_stopLog();
          return;
        }
      }
      if (SensorManager::pendingLoggingRows()) return;
    }
    s_storageStopRequested = true;
    StorageManager_stopLog();
    if (!StorageManager_recordingIoPending()) finishStorageStop();
    return;
  }
  if (phaseIs_(LifecycleState::Preparing) && s_storageStartPending) {
    if (StorageManager_recordingReady()) {
      RemoteImuRecording::start();
      if(!RemoteImuRecording::recording()) return;
      s_storageStartPending = false;
      completeStorageStart();
    } else if (!StorageManager_recordingIoPending()) {
      stop(StopReason::StartFailure, "storage_start_failure");
    }
    return;
  }
#endif
  if (phaseIs_(LifecycleState::Preparing)) {
    if (CanMasterManager::recordingHandoffReady()) (void)start();
    return;
  }
  if (phaseIs_(LifecycleState::Recording)) return;
  static uint32_t lastCheckMs = 0;
  const uint32_t now = millis();
  if ((uint32_t)(now - lastCheckMs) < 250) return;
  lastCheckMs = now;
  refreshConfigurationStatus();
}

bool LoggingManager::start() {
  if (!isLifecycleOwner_()) return false;
  if (!phaseIs_(LifecycleState::Preparing) && !phaseIs_(LifecycleState::Recording) && configurationLocked()) return false;
  if (phaseIs_(LifecycleState::Recording) || (phaseIs_(LifecycleState::Stopping) || phaseIs_(LifecycleState::Finalizing))) return false;
  if (!phaseIs_(LifecycleState::Preparing)) {
    s_lifecycle.publish(LifecycleState::Preparing);
    CanMasterManager::beginRecordingHandoff();
  }
  if (!CanMasterManager::recordingHandoffReady()) return false;
  // Every failure releases admission; successful start retains the fence until
  // finalization. This guard also covers early power/storage/preflight returns.
  struct StartAdmission {
    ~StartAdmission() {
      if(s_remotePreparing) return;
#if defined(ESP32)
      if (s_storageStartPending) return;
#endif
      if (phaseIs_(LifecycleState::Preparing)) {
        CanMasterManager::endRecordingHandoff();
        s_lifecycle.publish(CanMasterManager::recordingHandoffActive()
            ? LifecycleState::Uncertain : LifecycleState::Failed);
      }
    }
  } admission;
  s_startFailureHint = StartFailureHint::None;
  s_stopContext = StopContext{};
  if (!s_cfg) return false;
  if(ConfigManager::configurationBlocker().length()) { UI::status(ConfigManager::configurationBlocker()); return false; }
#if BODAQS_ADC_RAW_RECORDING_BENCH
  if(s_cfg->logFormat!=LogFormat::BodaqsMultiStreamBinary) {
    UI::toast("Select BDQ v2 in settings",1800,1);
    LOGGING_LOGW("start refused: raw ADC trial requires BDQ v2\n");
    return false;
  }
#if !BODAQS_PRODUCTION_RECORDING
  if(!RawAdcRecording::supportsGeometry(s_cfg->sampleRateHz,RawAdcRecording::kColumns)) {
    UI::toast("RAW trial rate mismatch",1800,1);
    LOGGING_LOGW("start refused: raw ADC trial rejects requested%uHz for %u channels/ADC\n",
                 s_cfg->sampleRateHz,RawAdcRecording::kChannelsPerAdc);
    return false;
  }
#endif
#endif
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

  refreshConfigurationStatus();
  if (s_configurationIssue != LoggingConfigIssue::None) {
    LOGGING_LOGW("sensor configuration issue; continuing with eligible sensors: %s\n",
                 s_configurationDetail);
  }
  if (SensorManager::requiresBdqV2(*s_cfg) && s_cfg->logFormat != LogFormat::BodaqsMultiStreamBinary) {
    if (!ConfigManager::setLogFormat(LogFormat::BodaqsMultiStreamBinary)) {
      UI::toast("Config save failed", 1800, 1);
      UI::status("SD error");
      LOGGING_LOGW("start refused: could not save automatic BDQ v2 selection\n");
      return false;
    }
    LOGGING_LOGI("log format automatically changed to BDQ v2 and saved\n");
    UI::toast("Format changed\nto BDQ v2", 1600, 1);
    UI::loop();
  }

  // Pick up any sample-rate changes that were applied while logging was idle.
  s_intervalUs = StorageManager_getSampleIntervalUs();

  // sampling cadence
  uint16_t requestedHz = s_cfg->sampleRateHz;
  const uint16_t syncCapHz = SensorManager::synchronousMaxSampleRateHz();
  if (syncCapHz != 0 && requestedHz > syncCapHz) {
    LOGGING_LOGW("Sample rate capped by synchronous sensor: requested=%u Hz cap=%u Hz\n",
                 (unsigned)requestedHz,
                 (unsigned)syncCapHz);
    requestedHz = syncCapHz;
  }
  const uint16_t effectiveRateHz = AnalogInputManager::configureFromConfig(*s_cfg, requestedHz);
  // Include recoveries during sensor initialization in this session's final
  // bus diagnostics, even when acquisition has not started yet.
  I2CManager::resetRecoveryStats();
  char sensorError[128] = {0};
  if (!SensorManager::validateLoggingStart(*s_cfg, effectiveRateHz, sensorError, sizeof(sensorError))) {
    UI::toast("Sensor config", 1800, 1);
    UI::status("Sensor config");
    LOGGING_LOGW("start refused: %s\n", sensorError[0] ? sensorError : "sensor validation failed");
    return false;
  }
  const uint8_t excludedSensors = SensorManager::sessionExcludedCount();
  if (excludedSensors) {
    char notice[32];
    snprintf(notice, sizeof(notice), "%u sensor%s skipped",
             (unsigned)excludedSensors, excludedSensors == 1 ? "" : "s");
    UI::toast(notice, 1800, 1);
    LOGGING_LOGW("best-effort session excludes %u configured sensor(s)\n",
                 (unsigned)excludedSensors);
  }
  StorageManager_setSampleRate(effectiveRateHz);
  s_intervalUs = StorageManager_getSampleIntervalUs();

  // Logging owns the device: take Wi-Fi (and therefore web server) down NOW.
  if (WebServerManager::isRunning()) {
    UI::println("Stopping web server for logging...", "", UI::TARGET_SERIAL, UI::LVL_INFO); // no delay
    WebServerManager::stop();
  }

  const uint32_t wifiOffT0 = millis();
  WiFiManager::suspendForLogging();   // synchronous OFF
  const uint32_t wifiOffMs = millis() - wifiOffT0;
  TRACE("stop webserver/wifi? (if any)");

#if BODAQS_ADC_CONCENTRATED_SCAN_BENCH
  // Reserve the parked owner while internal memory is still unfragmented.
  // SD/session/remote buffers must not consume its stack first. This does no
  // conversion work, and the normal split continuous control allocates nothing.
  if(!AnalogInputManager::reserveScanTask()) {
    SensorManager::onLoggingFinalized();WiFiManager::resumeAfterLogging();
    UI::status("ADC task memory");LOGGING_LOGW("start refused: ADC scan worker reservation failed\n");return false;
  }
#endif

  //PowerManager::setCpuFreqForLogging();

  //SensorManager::debugDump("before-header");

  TRACE("RTC sanity check begin");
  const bool rtcValid = RTCManager_hasValidTime();
  if (!rtcValid) {
    RTC_LOGW("start: RTC not valid; continuing with fallback filename/timestamps until resync\n");
  }
  TRACE("RTC sanity check done");

  // time anchors + grid align
  s_t0UnixUs = RTCManager_getEpochMs() * 1000ULL;
  s_sampleCount = 0;

#if defined(ESP32)
  resetLateStats_();
#endif

  const uint32_t sensorStartT0 = millis();
  if (!SensorManager::onLoggingStart(sensorError, sizeof(sensorError))) {
    SensorManager::onLoggingStop();
    SensorManager::onLoggingFinalized();
    WiFiManager::resumeAfterLogging();
    UI::toast("Sensor start", 1800, 1);
    UI::status("Sensor error");
    LOGGING_LOGW("start refused: %s\n", sensorError[0] ? sensorError : "sensor start failed");
    return false;
  }
  const uint32_t sensorStartMs = millis() - sensorStartT0;

  s_remoteFaultShown=false;
#if defined(ESP32) && defined(BODAQS_PACKED_SEGMENTED_RECEIVER) && BODAQS_PACKED_SEGMENTED_RECEIVER
  if(!StorageManager_prepareTask()) {
    LOGGING_LOGW("start refused: %s\n",StorageManager_lastStatus());
    SensorManager::onLoggingStop();SensorManager::onLoggingFinalized();
    WiFiManager::resumeAfterLogging();UI::status("Storage task memory");return false;
  }
  if(!AcquisitionControl::reserveTask()) {
    const auto d=AcquisitionControl::startupDiagnostics();
    LOGGING_LOGW("acquisition task reservation failed stack=6144 internal_free=%lu internal_largest=%lu\n",
        (unsigned long)d.afterTask.freeBytes,(unsigned long)d.afterTask.largestBlock);
    SensorManager::onLoggingStop();SensorManager::onLoggingFinalized();
    WiFiManager::resumeAfterLogging();UI::status("Acquisition task memory");return false;
  }
#if BODAQS_ADC_ROW_HANDOFF
  if (!s_rowHandoff) s_rowHandoff = new (std::nothrow) RowHandoffState();
  if (!s_rowHandoff
#if !BODAQS_ADC_INLINE_ROW
      || (!s_rowHandoff->worker && xTaskCreatePinnedToCore(rowAssemblyTaskFn_,"RowAssembly",4096,
      nullptr,2,&s_rowHandoff->worker,0)!=pdPASS)
#endif
      ) {
    LOGGING_LOGW("row assembly task reservation failed stack=4096\n");
    SensorManager::onLoggingStop();SensorManager::onLoggingFinalized();
    WiFiManager::resumeAfterLogging();UI::status("Row assembly memory");return false;
  }
#endif
#if BODAQS_ADC_COMBINED_CAPTURE
  if(!AnalogInputManager::scanRowCaptureEligible()) {
#endif
  if(!s_sampleTask && xTaskCreatePinnedToCore(sampleTaskFn_,"SampleTask",4096,
      nullptr,3,&s_sampleTask,0)!=pdPASS) {
    LOGGING_LOGW("sample task reservation failed stack=4096\n");
    SensorManager::onLoggingStop();SensorManager::onLoggingFinalized();
    WiFiManager::resumeAfterLogging();UI::status("Sampler task memory");return false;
  }
#if BODAQS_ADC_COMBINED_CAPTURE
  }
#endif
#endif
#if defined(ESP32)
  CpuOccupancy::bindTask(CpuOccupancy::Sampler,reinterpret_cast<uintptr_t>(s_sampleTask));
#endif
  if(!RemoteImuRecording::configure(*s_cfg)) {
    SensorManager::onLoggingStop();SensorManager::onLoggingFinalized();
    WiFiManager::resumeAfterLogging();UI::status("Remote IMU unavailable");
    return false;
  }
  if(RemoteImuRecording::configured()) {
    s_remotePreparing=true;UI::status("Preparing recording");
    if(!StorageManager_startLog()) {LOGGING_LOGW("storage start refused: %s\n",StorageManager_lastStatus());stop(StopReason::StartFailure,"storage_start_failure");return false;}
    return false;
  }

  // Open/create log file
  TRACE("Entering storagemanager_startlog");
  const uint32_t storageT0 = millis();
  if (!StorageManager_startLog()) {
    SensorManager::onLoggingStop();
    SensorManager::onLoggingFinalized();
    WiFiManager::resumeAfterLogging();
    UI::toast("SD open fail", 1500, 1);
    UI::status("SD error");
    LOGGING_LOGW("start refused: StorageManager_startLog failed (%s)\n", StorageManager_lastStatus());
    return false;
  }
  const uint32_t storageMs = millis() - storageT0;
  LOGGING_LOGI("start preparation timing: wifiOff=%lu ms storageCall=%lu ms sensors=%lu ms total=%lu ms rtcValid=%d\n",
               (unsigned long)wifiOffMs, (unsigned long)storageMs,
               (unsigned long)sensorStartMs, (unsigned long)(millis() - startT0),
               rtcValid ? 1 : 0);
  TRACE("storagemanager_startlog submitted");

#if defined(ESP32)
  s_storageStartPending = true;
  s_storageStopRequested = false;
  // Open/header/health I/O is outstanding on the storage task. The loop
  // observes completion before enabling acquisition; Stop can cancel it.
  return false;
#else
  completeStorageStart();
  return true;
#endif
}

void LoggingManager::completeStorageStart() {
  if (!isLifecycleOwner_()) return;
#if BODAQS_ADC_RAW_RECORDING_BENCH
  const auto raw=StorageManager_rawAdcStats();
  Serial.printf("{\"schema\":\"bodaqs.raw-adc.v1\",\"type\":\"selected\",\"recipe\":\"%s\",\"qualified\":%s,\"capacity\":%lu,\"record_bytes\":%u}\n",
    FirmwareInfo::buildRecipe(),raw.qualified?"true":"false",(unsigned long)raw.capacity,
    unsigned(sizeof(RawAdcRecord)));
#endif
#if BODAQS_ADC_ROW_HANDOFF
  // A new configuration may have a different row geometry on the same boot.
  resetRowSessionCaches_();
#endif
  // Paint the durable recording frame while the OLED is still allowed to
  // transfer. Auto/freeze policies may suppress every later refresh.
  DisplayManager::prepareLoggingScreen(
      StorageManager_getSampleRateHz(), SensorManager::activeCount());
#if BODAQS_ADC_ROW_HANDOFF
  // Previous producer and assembler have retired before any new START.
  portENTER_CRITICAL(&s_rowHandoff->mux);
#if !BODAQS_ADC_INLINE_ROW
  s_rowHandoff->queue.reset();
#endif
  s_rowHandoff->busy=false;
  portEXIT_CRITICAL(&s_rowHandoff->mux);
  s_rowHandoff->captured=s_rowHandoff->assembled=s_rowHandoff->queueDrops=s_rowHandoff->markDrops=0;
  s_rowHandoff->enqueued=s_rowHandoff->enqueueFailed=0;
  s_rowHandoff->queuePeak=s_rowHandoff->delayMaxUs=s_rowHandoff->captureMaxUs=0;s_rowHandoff->delayTotalUs=0;
#endif
#if BODAQS_ADC_COMBINED_CAPTURE
  s_rowHandoff->combinedNextUs=0;
  if(AnalogInputManager::scanRowCaptureEligible() && !AnalogInputManager::setScanRowCapture(combinedCaptureRow_)) {
    stop(StopReason::StartFailure,"combined_capture_registration");return;
  }
#endif
  AnalogInputManager::onLoggingStart();
  SensorManager::startLoggingAcquisition();
  s_lifecycle.publish(LifecycleState::Recording);
#if BODAQS_PRODUCTION_RECORDING
  if (!AnalogInputManager::activateRecordingPlan()) {
    stop(StopReason::StartFailure, "adc_acquisition_activation"); return;
  }
#endif
#if BODAQS_ADC_CONTINUOUS_LATEST
  if(!AnalogInputManager::continuousHealthy()) {stop(StopReason::StartFailure,"adc_continuous_start");return;}
#endif
  ButtonManager_setPollingEnabled(false);

#if defined(ESP32)
  // Start sampler task once (it loops forever; it will idle when not running)
  if (!s_sampleTask
#if BODAQS_ADC_COMBINED_CAPTURE
      && !AnalogInputManager::rowHandoffActive()
#endif
      ) {
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
  const unsigned hz = StorageManager_getSampleRateHz();
  char st[24]; snprintf(st, sizeof(st), "Recording %uHz", hz);
  UI::status(String(st));
  TRACE("exit start()");
}

LoggingManager::StartFailureHint LoggingManager::startFailureHint() {
  return s_startFailureHint;
}

void LoggingManager::setSampleRateHz(uint16_t hz) {
  if (configurationLocked()) return;
  // snap to allowed values for safety
  int idx = Rates::indexOf(hz);
  if (idx < 0) return;
  ConfigManager::setSampleRateHz(hz);        // update + persist
  if(ConfigManager::get().sampleRateHz!=hz) return; // save failed; retain applied cadence
  const uint16_t effectiveHz = AnalogInputManager::configureFromConfig(ConfigManager::get(), hz);
  StorageManager_setSampleRate(effectiveHz); // apply to the live logging cadence
  s_intervalUs = StorageManager_getSampleIntervalUs();
}

LoggingManager::RuntimeStats LoggingManager::runtimeStats() {
  RuntimeStats out;
#if defined(ESP32)
  out.samplerLateTicks = s_lateTicks;
  out.samplerLateMaxLagMs = s_lateMaxLagMs;
  out.samplerLateMaxLagUs = s_lateMaxLagUs;
  out.samplerWakeups = s_schedulerWakeups;
  out.samplerLateOverTenPercent = s_lateOverTenPercent;
  out.missedSampleSlots = s_missedSampleSlots;
#if BODAQS_TIMING_INSTRUMENTATION
  out.samplerWakeLagUs = s_wakeLagUs;
  out.sampleOnceUs = s_sampleOnceUs;
  out.sensorSampleUs = s_sensorSampleUs;
  out.enqueueUs = s_enqueueUs;
#endif
#endif
  return out;
}

const char* LoggingManager::stopReasonName(StopReason reason) {
  switch (reason) {
    case StopReason::None: return "none";
    case StopReason::UserRequest: return "user_request";
    case StopReason::AnalogRailFault: return "analog_rail_fault";
    case StopReason::SleepRequest: return "sleep_request";
    case StopReason::SdCardRemoved: return "sd_card_removed";
    case StopReason::StartFailure: return "start_failure";
    case StopReason::Unspecified: return "unspecified";
    case StopReason::StorageFailure: return "storage_failure";
    case StopReason::StorageUnresponsive: return "storage_unresponsive";
    default: return "unknown";
  }
}

LoggingManager::StopContext LoggingManager::stopContext() {
#if defined(ESP32)
  portENTER_CRITICAL(&s_stopContextMux);
#endif
  const StopContext context = s_stopContext;
#if defined(ESP32)
  portEXIT_CRITICAL(&s_stopContextMux);
#endif
  return context;
}

namespace {
bool retireLocalAcquisition_() {
#if defined(ESP32)
  // A sampler that already passed the run-state check may still be copying a
  // row into the storage queue. Let that bounded operation finish before
  // stopping sensors or draining/freeing the queue. If the sampler has not
  // entered sampleOnce_ yet, it observes the retired recording phase and
  // return without touching either subsystem.
  if (s_sampleInProgress.load(std::memory_order_acquire)) return false;
#endif
  // A bounded scheduler stop timeout is not producer retirement. Keep native
  // queues and session diagnostics owned until the final callback has returned.
  I2CBusScheduler::requestStop();
  if (!I2CBusScheduler::stopped()) return false;
#if BODAQS_ADC_ROW_HANDOFF
#if BODAQS_ADC_COMBINED_CAPTURE
  if (!AnalogInputManager::retireScanRowCapture()) return false;
#endif
  #if !BODAQS_ADC_INLINE_ROW
  // Producer is retired above. Pop+busy is atomic with this empty/busy check.
  xTaskNotifyGive(s_rowHandoff->worker);
  {
    portENTER_CRITICAL(&s_rowHandoff->mux);
    const bool drained = !s_rowHandoff->queue.size() && !s_rowHandoff->busy;
    portEXIT_CRITICAL(&s_rowHandoff->mux);
    if (!drained) return false;
  }
  #endif
  Serial.printf("{\"schema\":\"bodaqs.local-row-handoff.v1\",\"captured\":%lu,\"assembled\":%lu,\"enqueued\":%lu,\"enqueue_failed\":%lu,\"queue_dropped\":%lu,\"marks_dropped\":%lu,\"queue_peak\":%lu,\"capacity\":%u,\"capture_max_us\":%lu,\"assembly_delay_max_us\":%lu,\"assembly_delay_total_us\":%llu}\n",
      (unsigned long)s_rowHandoff->captured,(unsigned long)s_rowHandoff->assembled,(unsigned long)s_rowHandoff->enqueued,
      (unsigned long)s_rowHandoff->enqueueFailed,(unsigned long)s_rowHandoff->queueDrops,
      (unsigned long)s_rowHandoff->markDrops,(unsigned long)s_rowHandoff->queuePeak,BODAQS_ADC_INLINE_ROW?0u:8u,(unsigned long)s_rowHandoff->captureMaxUs,
      (unsigned long)s_rowHandoff->delayMaxUs,(unsigned long long)s_rowHandoff->delayTotalUs);
#if BODAQS_ADC_INLINE_ROW
  if(AnalogInputManager::rowHandoffActive())Serial.printf("{\"schema\":\"bodaqs.inline-row.v1\",\"owner\":\"adc\",\"assembly_task_exists\":%s,\"handoff_capacity\":0}\n",s_rowHandoff->worker?"true":"false");
#endif
#if BODAQS_ADC_COMBINED_CAPTURE
  if(AnalogInputManager::rowHandoffActive())Serial.printf("{\"schema\":\"bodaqs.combined-row-capture.v1\",\"trigger\":\"verified_pair\",\"nominal_interval_us\":%lu,\"sampler_task_exists\":%s,\"missed_row_slots\":%lu}\n",
      (unsigned long)s_intervalUs,s_sampleTask ? "true" : "false",(unsigned long)s_missedSampleSlots);
#endif
#endif
  AnalogInputManager::onLoggingStop();
  SensorManager::onLoggingStop();

  return true;
}
} // namespace

void LoggingManager::stop(StopReason reason, const char* triggerEvent) {
  if (!isLifecycleOwner_()) {
    s_lifecycle.requestStop(static_cast<uint8_t>(reason));
#if defined(ESP32)
    // A failing high-priority producer must let the control owner retire it.
    vTaskDelay(1);
#endif
    return;
  }
#if defined(ESP32)
  if ((phaseIs_(LifecycleState::Stopping) || phaseIs_(LifecycleState::Finalizing))) {
    if (stopPriority_(reason) > stopPriority_(s_stopContext.reason))
      captureStopContext_(reason, triggerEvent);
    return;
  }
#endif
  if (phaseIs_(LifecycleState::Preparing)) captureStopContext_(reason, triggerEvent);
  cancelStart();
  if (!phaseIs_(LifecycleState::Recording)) {
    LOGGING_LOGW("stop ignored because logging is not active reason=%s trigger=%s\n",
                 stopReasonName(reason), triggerEvent ? triggerEvent : "");
    return;
  }
  captureStopContext_(reason, triggerEvent);
  LOGGING_LOGI(
      "stop requested reason=%s uptime_ms=%lu trigger=%s sd_detect_available=%u sd_card_detected=%u analog_rail_fault=%u\n",
      stopReasonName(s_stopContext.reason),
      (unsigned long)s_stopContext.uptimeMs,
      s_stopContext.triggerEvent,
      s_stopContext.sdDetectAvailable ? 1u : 0u,
      s_stopContext.sdCardDetected ? 1u : 0u,
      s_stopContext.analogRailFault ? 1u : 0u);
  s_lifecycle.publish(LifecycleState::Stopping);
#if defined(ESP32) && BODAQS_ADC_ROW_BLOCKED_WAIT
  if(s_sampleTask)xTaskNotifyGive(s_sampleTask);
#endif
  RemoteImuRecording::stop();
#if defined(ESP32)
  s_localStopPending = true;
#else
  (void)retireLocalAcquisition_();
#endif

#if defined(ESP32)
  IndicatorManager::ledOff();
  // The loop feeds bounded final sensor rows as queue space becomes available,
  // then asks the owner to drain and finalize. It never waits for storage.
  UI::status("Finalizing recording");
  return;
#else
  // Existing logger rows are made durable first. The IMU driver has now
  // suspended production and completed its final FIFO drain, so one forced
  // sparse row per remaining queued sample closes the session boundary.
  StorageManager_drainQueuedSamples();
  size_t pendingRows = StorageManager_usesIndependentStreams()
      ? 0
      : SensorManager::pendingLoggingRows();
  const size_t initialPendingRows = pendingRows;
  size_t tailRowsWritten = 0;
  while (pendingRows > 0 && tailRowsWritten < initialPendingRows) {
    if (!sampleOnce_(true)) {
      LOGGING_LOGW("final sensor row enqueue failed with %u rows pending\n",
                   (unsigned)pendingRows);
      break;
    }
    StorageManager_drainQueuedSamples();
    ++tailRowsWritten;
    const size_t remaining = SensorManager::pendingLoggingRows();
    if (remaining >= pendingRows) {
      LOGGING_LOGW("final sensor queue made no progress (%u rows pending)\n",
                   (unsigned)remaining);
      break;
    }
    pendingRows = remaining;
  }
  if (initialPendingRows > 0) {
    LOGGING_LOGI("final sensor rows written=%u remaining=%u\n",
                 (unsigned)tailRowsWritten,
                 (unsigned)SensorManager::pendingLoggingRows());
  }
  IndicatorManager::ledOff();
  StorageManager_stopLog();
  finishStorageStop();
#endif
}

#if BODAQS_TIMING_INSTRUMENTATION && BODAQS_ADC_ROW_HANDOFF
static void printRetiredRowCosts_() {
  const auto stats=LoggingManager::runtimeStats();
#if BODAQS_ADC_RAW_RECORDING_BENCH
  const auto raw=StorageManager_rawAdcStats();
  Serial.printf("{\"schema\":\"bodaqs.raw-adc.v1\",\"type\":\"retired\",\"recipe\":\"%s\",\"qualified\":%s,\"capacity\":%lu,\"submitted\":%lu,\"enqueued\":%lu,\"encoded\":%lu,\"rejected\":%lu,\"generic_attempts\":%lu}\n",
    FirmwareInfo::buildRecipe(),raw.qualified?"true":"false",(unsigned long)raw.capacity,
    (unsigned long)raw.submitted,(unsigned long)raw.enqueued,(unsigned long)raw.encoded,
    (unsigned long)raw.rejected,(unsigned long)raw.genericAttempts);
#endif
  auto print=[](const TimingSummary& v) {
    Serial.printf("{\"count\":%lu,\"min_us\":%lu,\"max_us\":%lu,\"total_us\":%llu}",
      (unsigned long)v.count,(unsigned long)v.minUs,(unsigned long)v.maxUs,(unsigned long long)v.totalUs);
  };
  Serial.printf("{\"schema\":\"bodaqs.row-cost.v1\",\"type\":\"retired\",\"recipe\":\"%s\",\"scope\":\"nested_wall_time_not_exclusive_cpu\",\"sampling_plan\":%s,\"raw_acquisition\":%s,\"rows\":%lu,\"sample_once_us\":",
    FirmwareInfo::buildRecipe(),SensorManager::recordingSamplingPlanReady()?"true":"false",
    BODAQS_ADC_RAW_RECORDING_BENCH?"true":"false",(unsigned long)stats.samplerWakeups);
  print(stats.sampleOnceUs);Serial.print(",\"sensor_sample_us\":");print(stats.sensorSampleUs);
  Serial.print(",\"enqueue_us\":");print(stats.enqueueUs);Serial.print(",\"sensors\":[");
  bool comma=false;
  const auto& timing=SensorManager::timingStats();
  for(unsigned i=0;i<SensorTimingStats::kMaxSensors;++i) {
    const auto& slot=timing.sensor[i];if(!slot.present || !slot.sampleUs.count)continue;
    Serial.printf("%s{\"index\":%u,\"columns\":%u,\"sample_us\":",comma?",":"",i,unsigned(slot.columnCount));
    print(slot.sampleUs);Serial.print("}");comma=true;
  }
  Serial.println("]}");
}
#endif

void LoggingManager::finishStorageStop() {
  if (!isLifecycleOwner_()) return;
#if defined(ESP32)
  if (StorageManager_recordingIoPending()) return;
#endif
#if BODAQS_TIMING_INSTRUMENTATION && BODAQS_ADC_ROW_HANDOFF
  printRetiredRowCosts_();
#endif
#if defined(ESP32)
  s_storageStopRequested = false;
  if (StorageManager_storageFault()) {
    const bool stalled = StorageManager_storageUnresponsive();
    captureStopContext_(stalled ? StopReason::StorageUnresponsive : StopReason::StorageFailure,
                        stalled ? "storage_timeout" : "storage_failure");
    UI::status(stalled ? "Storage unresponsive" : "Storage failure");
  }
#endif
  // Recovery is deliberately later than StorageManager_stopLog(): the BDQ
  // final summary must observe the session's original sensor diagnostics.
  SensorManager::onLoggingFinalized();
  PowerManager::restoreCpuFreqAfterLogging();
  WiFiManager::resumeAfterLogging();

#if defined(ESP32)
  // Report task-lateness stats (these replace the old loop()-based lateTicks)
  LOGGING_LOGI("lateTicks=%lu maxLagMs=%lu\n",
               (unsigned long)s_lateTicks,
               (unsigned long)s_lateMaxLagMs);
  LOGGING_LOGI("missedSampleSlots=%lu\n",
               (unsigned long)s_missedSampleSlots);
  LOGGING_LOGI("schedulerWakeups=%lu lateOver10pct=%lu maxLagUs=%lu\n",
               (unsigned long)s_schedulerWakeups,
               (unsigned long)s_lateOverTenPercent,
               (unsigned long)s_lateMaxLagUs);
#endif
  RemoteImuRecording::release();
  CanMasterManager::endRecordingHandoff();
  const auto reason = s_stopContext.reason;
  s_lifecycle.publish(CanMasterManager::recordingHandoffActive()
      ? LifecycleState::Uncertain
      : (reason == StopReason::UserRequest || reason == StopReason::SleepRequest || reason == StopReason::None)
          ? LifecycleState::Completed : LifecycleState::Failed);
  // Automatic/error STOP must restore the same navigation as manual STOP.
  ButtonManager_setPollingEnabled(true);
#if defined(ESP32)
  if(!StorageManager_storageFault()) {
    if(CanMasterManager::recordingHandoffActive()) {
      UI::status("Control cleanup incomplete");
      LOGGING_LOGW("file finalized; control handoff still active\n");
    } else if (phaseIs_(LifecycleState::Failed)) {
      UI::status("Recording failed; file closed");
      LOGGING_LOGW("recording finalized with failure reason=%s\n", stopReasonName(s_stopContext.reason));
    } else {
      UI::status("Recording finalized");
      LOGGING_LOGI("recording finalized; control handoff released\n");
    }
  }
#endif
}

bool LoggingManager::isRunning() {
  return phaseIs_(LifecycleState::Recording);
}

void LoggingManager::mark() {
  enqueueNow();
}
