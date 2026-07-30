#include "I2CBusScheduler.h"

#include <string.h>

#include "BoardProfile.h"
#include "I2CManager.h"
#include "DebugLog.h"
#include "esp_timer.h"

#if defined(ESP32)
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#endif

#define I2CSCHED_LOGI(...) LOGI_TAG("I2CSched", __VA_ARGS__)
#define I2CSCHED_LOGW(...) LOGW_TAG("I2CSched", __VA_ARGS__)

namespace {

static constexpr uint8_t kMaxBuses = I2CBusSchedulerTimingStats::kMaxBuses;
static constexpr uint8_t kMaxClients = I2CBusSchedulerTimingStats::kMaxClients;
static constexpr uint16_t kDefaultTargetRateHz = 100;
static constexpr uint16_t kMaxTargetRateHz = 1000;
static constexpr uint32_t kMutedClientBackoffUs = 250000UL;
static constexpr int64_t kCoarseSleepThresholdUs = 1500;
static constexpr int64_t kFineSleepThresholdUs = 250;
static constexpr int64_t kFineSleepGuardUs = 100;
static constexpr int64_t kFineSleepMaxUs = 500;
static constexpr uint32_t kStopWaitMs = 1500;
static constexpr uint32_t kTaskStackBytes = 4096;
static constexpr UBaseType_t kTaskPriority = 2;
static constexpr BaseType_t kTaskCore = 1;

struct ClientSlot {
  I2CAsyncClient* client = nullptr;
  bool registered = false;
  uint64_t nextDueUs = 0;

  // Acquisition fields are written only by the bus scheduler task. Row-use
  // fields are written only by the sampler task. They are copied into the
  // public snapshot after the scheduler has stopped.
  TimingSummary acquireUs;
  TimingSummary rowAgeUs;
  uint32_t acquireOk = 0;
  uint32_t acquireFail = 0;
  uint32_t rowUses = 0;
  uint32_t rowFresh = 0;
  uint32_t rowReused = 0;
  uint32_t rowNoSample = 0;
  uint32_t acquireFailStreak = 0;
  uint32_t acquireFailStreakMax = 0;
  uint32_t rowReuseStreak = 0;
  uint32_t rowReuseStreakMax = 0;
  uint32_t rowNoSampleStreak = 0;
  uint32_t rowNoSampleStreakMax = 0;
};

ClientSlot s_clients[kMaxClients];
TimingSummary s_busAcquireUs[kMaxBuses];
I2CBusSchedulerTimingStats s_timingSnapshot;

#if defined(ESP32)
TaskHandle_t s_tasks[kMaxBuses] = { nullptr, nullptr };
volatile bool s_run[kMaxBuses] = { false, false };

bool schedulerTasksActive_() {
  for (uint8_t bus = 0; bus < kMaxBuses; ++bus) {
    if (s_tasks[bus] != nullptr) return true;
  }
  return false;
}
#endif

void copyText_(char* dst, size_t cap, const char* src) {
  if (!dst || cap == 0) return;
  if (!src) src = "";
  size_t n = strlen(src);
  if (n >= cap) n = cap - 1;
  memcpy(dst, src, n);
  dst[n] = '\0';
}

uint16_t targetRateHz_(I2CAsyncClient* client) {
  if (!client) return kDefaultTargetRateHz;
  uint16_t hz = client->asyncTargetRateHz();
  if (hz == 0) hz = kDefaultTargetRateHz;
  if (hz > kMaxTargetRateHz) hz = kMaxTargetRateHz;
  return hz;
}

uint32_t periodUsFor_(I2CAsyncClient* client) {
  const uint16_t hz = targetRateHz_(client);
  return hz ? (1000000UL / hz) : (1000000UL / kDefaultTargetRateHz);
}

int findClient_(I2CAsyncClient* client) {
  if (!client) return -1;
  for (uint8_t i = 0; i < kMaxClients; ++i) {
    if (s_clients[i].registered && s_clients[i].client == client) return (int)i;
  }
  return -1;
}

int firstFreeClient_() {
  for (uint8_t i = 0; i < kMaxClients; ++i) {
    if (!s_clients[i].registered) return (int)i;
  }
  return -1;
}

void buildTimingSnapshot_() {
  // This object is about 3 KB. Build it in its existing static storage rather
  // than on loopTask's stack: this function is also reached from the sensor
  // configuration HTTP handler, whose stack frame is already comparatively
  // large. Callers only invoke it while scheduler tasks are inactive.
  memset(&s_timingSnapshot, 0, sizeof(s_timingSnapshot));
  I2CBusSchedulerTimingStats& snapshot = s_timingSnapshot;
  for (uint8_t bus = 0; bus < kMaxBuses; ++bus) {
    auto& b = snapshot.bus[bus];
    const board::I2CProfile* profile = I2CManager::profile(bus);
    b.present = I2CManager::available(bus);
    b.hz = (profile && profile->hz) ? profile->hz : 0;
    b.acquireLoopUs = s_busAcquireUs[bus];
#if defined(ESP32)
    b.running = (s_tasks[bus] != nullptr) && s_run[bus];
#endif
  }

  uint8_t total = 0;
  for (uint8_t i = 0; i < kMaxClients; ++i) {
    if (!s_clients[i].registered || !s_clients[i].client) continue;
    ++total;
    const ClientSlot& slot = s_clients[i];
    I2CAsyncClient* client = slot.client;
    auto& stats = snapshot.client[i];
    stats.present = true;
    stats.active = !client->asyncMuted();
    stats.busIndex = client->asyncI2CBusIndex();
    stats.address = client->asyncI2CAddress();
    stats.targetRateHz = targetRateHz_(client);
    stats.periodUs = periodUsFor_(client);
    copyText_(stats.name, sizeof(stats.name), client->asyncClientName());
    copyText_(stats.kind, sizeof(stats.kind), client->asyncClientKind());
    stats.acquireUs = slot.acquireUs;
    stats.rowAgeUs = slot.rowAgeUs;
    stats.acquireOk = slot.acquireOk;
    stats.acquireFail = slot.acquireFail;
    stats.rowUses = slot.rowUses;
    stats.rowFresh = slot.rowFresh;
    stats.rowReused = slot.rowReused;
    stats.rowNoSample = slot.rowNoSample;
    stats.acquireFailStreakMax = slot.acquireFailStreakMax;
    stats.rowReuseStreakMax = slot.rowReuseStreakMax;
    stats.rowNoSampleStreakMax = slot.rowNoSampleStreakMax;
    if (stats.busIndex < kMaxBuses) ++snapshot.bus[stats.busIndex].clientCount;
  }
  snapshot.clientCount = total;
}

void resetRuntimeStats_() {
  for (uint8_t bus = 0; bus < kMaxBuses; ++bus) {
    s_busAcquireUs[bus] = TimingSummary{};
  }
  for (uint8_t i = 0; i < kMaxClients; ++i) {
    ClientSlot& slot = s_clients[i];
    slot.acquireUs = TimingSummary{};
    slot.rowAgeUs = TimingSummary{};
    slot.acquireOk = 0;
    slot.acquireFail = 0;
    slot.rowUses = 0;
    slot.rowFresh = 0;
    slot.rowReused = 0;
    slot.rowNoSample = 0;
    slot.acquireFailStreak = 0;
    slot.acquireFailStreakMax = 0;
    slot.rowReuseStreak = 0;
    slot.rowReuseStreakMax = 0;
    slot.rowNoSampleStreak = 0;
    slot.rowNoSampleStreakMax = 0;
  }
  s_timingSnapshot = I2CBusSchedulerTimingStats{};
}

bool busHasActiveClients_(uint8_t bus) {
  if (bus >= kMaxBuses || !I2CManager::available(bus)) return false;
  for (uint8_t i = 0; i < kMaxClients; ++i) {
    I2CAsyncClient* client = s_clients[i].registered ? s_clients[i].client : nullptr;
    if (!client) continue;
    if (client->asyncI2CBusIndex() != bus) continue;
    if (client->asyncMuted()) continue;
    return true;
  }
  return false;
}

ClientSlot* nextDueClient_(uint8_t bus, uint64_t nowUs, uint64_t& earliestDueUs) {
  ClientSlot* due = nullptr;
  earliestDueUs = nowUs + kMutedClientBackoffUs;

  for (uint8_t i = 0; i < kMaxClients; ++i) {
    ClientSlot& slot = s_clients[i];
    I2CAsyncClient* client = slot.registered ? slot.client : nullptr;
    if (!client || client->asyncI2CBusIndex() != bus) continue;

    if (client->asyncMuted()) {
      slot.nextDueUs = nowUs + kMutedClientBackoffUs;
      continue;
    }

    if (slot.nextDueUs == 0) slot.nextDueUs = nowUs;
    if (slot.nextDueUs <= nowUs) {
      if (!due || slot.nextDueUs < due->nextDueUs) due = &slot;
    }
    if (slot.nextDueUs < earliestDueUs) earliestDueUs = slot.nextDueUs;
  }

  return due;
}

void waitUntil_(uint64_t targetUs) {
  for (;;) {
    const int64_t remaining = (int64_t)targetUs - (int64_t)esp_timer_get_time();
    if (remaining <= 0) return;

    if (remaining > kCoarseSleepThresholdUs) {
      vTaskDelay(1);
    } else if (remaining > kFineSleepThresholdUs) {
      int64_t delayUs = remaining - kFineSleepGuardUs;
      if (delayUs > kFineSleepMaxUs) delayUs = kFineSleepMaxUs;
      if (delayUs > 0) delayMicroseconds((uint32_t)delayUs);
    } else {
      return;
    }
  }
}

#if defined(ESP32)
void taskFn_(void* arg) {
  const uint8_t bus = (uint8_t)(uintptr_t)arg;
  I2CSCHED_LOGI("bus%u scheduler started\n", (unsigned)bus);

  uint64_t nowUs = (uint64_t)esp_timer_get_time();
  for (uint8_t i = 0; i < kMaxClients; ++i) {
    ClientSlot& slot = s_clients[i];
    if (!slot.registered || !slot.client) continue;
    if (slot.client->asyncI2CBusIndex() == bus) {
      slot.client->asyncSchedulerStarting();
      slot.nextDueUs = nowUs;
    }
  }

  while (bus < kMaxBuses && s_run[bus]) {
    nowUs = (uint64_t)esp_timer_get_time();
    uint64_t earliestDueUs = nowUs + kMutedClientBackoffUs;
    ClientSlot* slot = nextDueClient_(bus, nowUs, earliestDueUs);
    if (!slot || !slot->client) {
      waitUntil_(earliestDueUs);
      continue;
    }

    I2CAsyncClient* client = slot->client;
    const uint32_t periodUs = periodUsFor_(client);
    const uint32_t t0 = micros();
    const bool ok = client->asyncAcquire();
    const uint32_t acquireUs = (uint32_t)(micros() - t0);

#if BODAQS_TIMING_INSTRUMENTATION
    TimingStats_record(slot->acquireUs, acquireUs);
    if (ok) {
      ++slot->acquireOk;
      slot->acquireFailStreak = 0;
    } else {
      ++slot->acquireFail;
      ++slot->acquireFailStreak;
      if (slot->acquireFailStreak > slot->acquireFailStreakMax) {
        slot->acquireFailStreakMax = slot->acquireFailStreak;
      }
    }
    if (bus < kMaxBuses) {
      TimingStats_record(s_busAcquireUs[bus], acquireUs);
    }
#endif

    uint64_t nextDue = slot->nextDueUs + periodUs;
    const uint64_t afterUs = (uint64_t)esp_timer_get_time();
    if (periodUs > 0 && nextDue <= afterUs) {
      const uint64_t missed = ((afterUs - nextDue) / periodUs) + 1ULL;
      nextDue += missed * (uint64_t)periodUs;
    }
    slot->nextDueUs = nextDue;
  }

  for (uint8_t i = 0; i < kMaxClients; ++i) {
    ClientSlot& slot = s_clients[i];
    if (!slot.registered || !slot.client) continue;
    if (slot.client->asyncI2CBusIndex() == bus) {
      slot.client->asyncSchedulerStopped();
    }
  }

  if (bus < kMaxBuses) {
    s_run[bus] = false;
    s_tasks[bus] = nullptr;
  }
  I2CSCHED_LOGI("bus%u scheduler stopped\n", (unsigned)bus);
  vTaskDelete(nullptr);
}
#endif

} // namespace

namespace I2CBusScheduler {

bool registerClient(I2CAsyncClient* client) {
  if (!client) return false;

  int idx = findClient_(client);
  if (idx < 0) idx = firstFreeClient_();
  if (idx < 0) {
    I2CSCHED_LOGW("client table full; could not register '%s'\n",
                  client->asyncClientName());
    return false;
  }

  s_clients[idx].client = client;
  s_clients[idx].registered = true;
  s_clients[idx].nextDueUs = 0;
  buildTimingSnapshot_();
  return true;
}

void unregisterClient(I2CAsyncClient* client) {
  const int idx = findClient_(client);
  if (idx < 0) return;
  s_clients[idx] = ClientSlot{};
  buildTimingSnapshot_();
}

void resetTimingStats() {
#if BODAQS_TIMING_INSTRUMENTATION
  resetRuntimeStats_();
  buildTimingSnapshot_();
#endif
}

const I2CBusSchedulerTimingStats& timingStats() {
#if defined(ESP32)
  if (!schedulerTasksActive_()) buildTimingSnapshot_();
#else
  buildTimingSnapshot_();
#endif
  return s_timingSnapshot;
}

void start() {
#if defined(ESP32)
  for (uint8_t bus = 0; bus < kMaxBuses; ++bus) {
    if (s_tasks[bus]) continue;
    if (!busHasActiveClients_(bus)) continue;

    s_run[bus] = true;
    const BaseType_t ok = xTaskCreatePinnedToCore(
      taskFn_,
      "I2CBusSched",
      kTaskStackBytes,
      (void*)(uintptr_t)bus,
      kTaskPriority,
      &s_tasks[bus],
      kTaskCore);

    if (ok != pdPASS) {
      s_tasks[bus] = nullptr;
      s_run[bus] = false;
      I2CSCHED_LOGW("failed to start bus%u scheduler\n", (unsigned)bus);
    }
  }
#endif
}

void stop() {
#if defined(ESP32)
  for (uint8_t bus = 0; bus < kMaxBuses; ++bus) {
    s_run[bus] = false;
  }

  const uint32_t t0 = millis();
  bool any = true;
  while (any && (uint32_t)(millis() - t0) < kStopWaitMs) {
    any = false;
    for (uint8_t bus = 0; bus < kMaxBuses; ++bus) {
      if (s_tasks[bus]) {
        any = true;
        break;
      }
    }
    if (any) vTaskDelay(1);
  }

  if (!schedulerTasksActive_()) {
    buildTimingSnapshot_();
  } else {
    I2CSCHED_LOGW("scheduler task did not stop within %lu ms; retaining last coherent timing snapshot\n",
                  (unsigned long)kStopWaitMs);
  }
#endif
}

bool isRunning() {
#if defined(ESP32)
  for (uint8_t bus = 0; bus < kMaxBuses; ++bus) {
    if (s_tasks[bus] && s_run[bus]) return true;
  }
#endif
  return false;
}

void recordRowUse(I2CAsyncClient* client, uint32_t ageUs, bool fresh, bool haveSample) {
#if BODAQS_TIMING_INSTRUMENTATION
  const int idx = findClient_(client);
  if (idx < 0 || idx >= (int)kMaxClients) return;
  ClientSlot& slot = s_clients[idx];
  ++slot.rowUses;
  if (!haveSample) {
    ++slot.rowNoSample;
    ++slot.rowNoSampleStreak;
    if (slot.rowNoSampleStreak > slot.rowNoSampleStreakMax) {
      slot.rowNoSampleStreakMax = slot.rowNoSampleStreak;
    }
    slot.rowReuseStreak = 0;
    return;
  }
  slot.rowNoSampleStreak = 0;
  if (fresh) {
    ++slot.rowFresh;
    slot.rowReuseStreak = 0;
  } else {
    ++slot.rowReused;
    ++slot.rowReuseStreak;
    if (slot.rowReuseStreak > slot.rowReuseStreakMax) {
      slot.rowReuseStreakMax = slot.rowReuseStreak;
    }
  }
  TimingStats_record(slot.rowAgeUs, ageUs);
#else
  (void)client;
  (void)ageUs;
  (void)fresh;
  (void)haveSample;
#endif
}

} // namespace I2CBusScheduler
