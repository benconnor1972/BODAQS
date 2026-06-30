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
static constexpr uint32_t kStopWaitMs = 100;
static constexpr uint32_t kTaskStackBytes = 4096;
static constexpr UBaseType_t kTaskPriority = 2;
static constexpr BaseType_t kTaskCore = 1;

struct ClientSlot {
  I2CAsyncClient* client = nullptr;
  bool registered = false;
  uint8_t statsIndex = 0;
  uint64_t nextDueUs = 0;
};

ClientSlot s_clients[kMaxClients];
I2CBusSchedulerTimingStats s_timing;

#if defined(ESP32)
TaskHandle_t s_tasks[kMaxBuses] = { nullptr, nullptr };
volatile bool s_run[kMaxBuses] = { false, false };
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

void refreshClientStats_(uint8_t idx) {
  if (idx >= kMaxClients) return;
  auto& slot = s_clients[idx];
  auto& stats = s_timing.client[idx];
  const TimingSummary acquireUs = stats.acquireUs;
  const TimingSummary rowAgeUs = stats.rowAgeUs;
  const uint32_t acquireOk = stats.acquireOk;
  const uint32_t acquireFail = stats.acquireFail;
  const uint32_t rowUses = stats.rowUses;
  const uint32_t rowFresh = stats.rowFresh;
  const uint32_t rowReused = stats.rowReused;
  const uint32_t rowNoSample = stats.rowNoSample;

  stats = I2CBusSchedulerTimingStats::ClientStats{};
  if (!slot.registered || !slot.client) return;

  stats.present = true;
  stats.active = !slot.client->asyncMuted();
  stats.busIndex = slot.client->asyncI2CBusIndex();
  stats.address = slot.client->asyncI2CAddress();
  stats.targetRateHz = targetRateHz_(slot.client);
  stats.periodUs = periodUsFor_(slot.client);
  copyText_(stats.name, sizeof(stats.name), slot.client->asyncClientName());
  copyText_(stats.kind, sizeof(stats.kind), slot.client->asyncClientKind());
  stats.acquireUs = acquireUs;
  stats.rowAgeUs = rowAgeUs;
  stats.acquireOk = acquireOk;
  stats.acquireFail = acquireFail;
  stats.rowUses = rowUses;
  stats.rowFresh = rowFresh;
  stats.rowReused = rowReused;
  stats.rowNoSample = rowNoSample;
}

void refreshBusStats_() {
  for (uint8_t bus = 0; bus < kMaxBuses; ++bus) {
    auto& b = s_timing.bus[bus];
    const TimingSummary loopUs = b.acquireLoopUs;
    const board::I2CProfile* profile = I2CManager::profile(bus);
    b = I2CBusSchedulerTimingStats::BusStats{};
    b.present = I2CManager::available(bus);
    b.hz = (profile && profile->hz) ? profile->hz : 0;
    b.acquireLoopUs = loopUs;
#if defined(ESP32)
    b.running = (s_tasks[bus] != nullptr) && s_run[bus];
#endif
  }

  uint8_t total = 0;
  for (uint8_t i = 0; i < kMaxClients; ++i) {
    if (!s_clients[i].registered || !s_clients[i].client) continue;
    ++total;
    refreshClientStats_(i);
    const uint8_t bus = s_clients[i].client->asyncI2CBusIndex();
    if (bus < kMaxBuses) ++s_timing.bus[bus].clientCount;
  }
  s_timing.clientCount = total;
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
    const uint8_t statsIndex = slot->statsIndex;
    if (statsIndex < kMaxClients) {
      auto& c = s_timing.client[statsIndex];
      refreshClientStats_(statsIndex);
      TimingStats_record(c.acquireUs, acquireUs);
      if (ok) ++c.acquireOk;
      else ++c.acquireFail;
    }
    if (bus < kMaxBuses) {
      TimingStats_record(s_timing.bus[bus].acquireLoopUs, acquireUs);
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
    s_timing.bus[bus].running = false;
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
  s_clients[idx].statsIndex = (uint8_t)idx;
  s_clients[idx].nextDueUs = 0;
  refreshBusStats_();
  refreshClientStats_((uint8_t)idx);
  return true;
}

void unregisterClient(I2CAsyncClient* client) {
  const int idx = findClient_(client);
  if (idx < 0) return;
  s_clients[idx] = ClientSlot{};
  refreshBusStats_();
}

void resetTimingStats() {
#if BODAQS_TIMING_INSTRUMENTATION
  s_timing = I2CBusSchedulerTimingStats{};
  refreshBusStats_();
#endif
}

const I2CBusSchedulerTimingStats& timingStats() {
  refreshBusStats_();
  return s_timing;
}

void start() {
#if defined(ESP32)
  refreshBusStats_();
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
    } else {
      s_timing.bus[bus].running = true;
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

  refreshBusStats_();
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
  auto& c = s_timing.client[idx];
  refreshClientStats_((uint8_t)idx);
  ++c.rowUses;
  if (!haveSample) {
    ++c.rowNoSample;
    return;
  }
  if (fresh) ++c.rowFresh;
  else ++c.rowReused;
  TimingStats_record(c.rowAgeUs, ageUs);
#else
  (void)client;
  (void)ageUs;
  (void)fresh;
  (void)haveSample;
#endif
}

} // namespace I2CBusScheduler
