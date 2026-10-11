#include "StartupLog.h"
#include "I2CManager.h"
#include "DebugLog.h"
#include "esp32-hal-i2c.h"
#include "I2CBusScheduler.h"
#include <atomic>
#if defined(ESP32)
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#endif

#define I2C_LOGI(...) LOGI_TAG("I2C", __VA_ARGS__)
#define I2C_LOGW(...) LOGW_TAG("I2C", __VA_ARGS__)

namespace {
  TwoWire s_wire1(1);
  TwoWire* s_buses[board::BOARD_MAX_I2C_BUSES] = { &Wire, &s_wire1 };
  const board::I2CProfile* s_profiles[board::BOARD_MAX_I2C_BUSES] = { nullptr, nullptr };
  bool s_available[board::BOARD_MAX_I2C_BUSES] = { false, false };
  uint32_t s_startupClockOverride[board::BOARD_MAX_I2C_BUSES] {};
  size_t s_bufferCapacity[board::BOARD_MAX_I2C_BUSES] = {
    I2C_BUFFER_LENGTH,
    I2C_BUFFER_LENGTH
  };
  uint16_t s_transactionTimeoutMs[board::BOARD_MAX_I2C_BUSES] = {50, 50};
  I2CManager::BusRecoveryStatus s_recovery[board::BOARD_MAX_I2C_BUSES];
  std::atomic<uint32_t> s_recoveryGeneration[board::BOARD_MAX_I2C_BUSES];
  bool s_recoveryAttemptKnown[board::BOARD_MAX_I2C_BUSES] {};
  bool s_lastRecoveryOk[board::BOARD_MAX_I2C_BUSES] {};
  constexpr uint32_t kRecoveryCooldownMs = 2000;
#if defined(ESP32)
  SemaphoreHandle_t s_mutexes[board::BOARD_MAX_I2C_BUSES] = { nullptr, nullptr };
#endif

  int busIndexFor_(TwoWire* wire) {
    if (!wire) return -1;
    for (uint8_t i = 0; i < board::BOARD_MAX_I2C_BUSES; ++i) {
      if (s_buses[i] == wire) return (int)i;
    }
    return -1;
  }
}

void I2CManager::begin(const board::BoardProfile& bp) {
  for (uint8_t i = 0; i < board::BOARD_MAX_I2C_BUSES; ++i) {
    s_profiles[i] = nullptr;
    s_available[i] = false;
    s_startupClockOverride[i] = 0;
  }

  const uint8_t count = (bp.i2c_count < board::BOARD_MAX_I2C_BUSES)
    ? bp.i2c_count
    : board::BOARD_MAX_I2C_BUSES;

  for (uint8_t i = 0; i < count; ++i) {
    const board::I2CProfile& cfg = bp.i2c[i];
    s_profiles[i] = &cfg;
#if defined(ESP32)
    if (!s_mutexes[i]) s_mutexes[i] = xSemaphoreCreateMutex();
    if (!s_mutexes[i]) {
      I2C_LOGW("bus%u unavailable: mutex allocation failed\n", (unsigned)i);
      continue;
    }
#endif

    if (!cfg.present) {
      I2C_LOGI("bus%u disabled in board profile\n", (unsigned)i);
      continue;
    }
    if (cfg.sda < 0 || cfg.scl < 0) {
      I2C_LOGW("bus%u invalid pins: SDA=%d SCL=%d\n",
               (unsigned)i,
               (int)cfg.sda,
               (int)cfg.scl);
      continue;
    }

    TwoWire* w = s_buses[i];
    if (!w) {
      I2C_LOGW("bus%u has no runtime TwoWire instance\n", (unsigned)i);
      continue;
    }

    const uint32_t hz = cfg.hz ? cfg.hz : 100000UL;
    const bool started = w->begin(cfg.sda, cfg.scl, hz);
    const bool clockOk = started && w->setClock(hz) && w->getClock() == hz;
    if (!clockOk) {
      w->end();
      I2C_LOGW("bus%u unavailable: controller=%u clock=%u\n",
               (unsigned)i, started ? 1u : 0u, clockOk ? 1u : 0u);
      continue;
    }
    s_available[i] = true;

    I2C_LOGI("bus%u ready: SDA=%d SCL=%d hz=%lu\n",
             (unsigned)i,
             (int)cfg.sda,
             (int)cfg.scl,
             (unsigned long)hz);
  }
}

bool I2CManager::available(uint8_t busIndex) {
  return (busIndex < board::BOARD_MAX_I2C_BUSES) ? s_available[busIndex] : false;
}

TwoWire* I2CManager::bus(uint8_t busIndex) {
  if (busIndex >= board::BOARD_MAX_I2C_BUSES) return nullptr;
  return s_available[busIndex] ? s_buses[busIndex] : nullptr;
}

const board::I2CProfile* I2CManager::profile(uint8_t busIndex) {
  if (busIndex >= board::BOARD_MAX_I2C_BUSES) return nullptr;
  return s_profiles[busIndex];
}

bool I2CManager::ensureBufferCapacity(uint8_t busIndex, size_t bytes) {
  if (busIndex >= board::BOARD_MAX_I2C_BUSES || !s_available[busIndex]) return false;
  if (bytes <= s_bufferCapacity[busIndex]) return true;
  TwoWire* wire = s_buses[busIndex];
  if (!wire) return false;
  const size_t allocated = wire->setBufferSize(bytes);
  if (allocated < bytes) {
    I2C_LOGW("bus%u buffer allocation failed: requested=%u allocated=%u\n",
             (unsigned)busIndex,
             (unsigned)bytes,
             (unsigned)allocated);
    return false;
  }
  s_bufferCapacity[busIndex] = allocated;
  I2C_LOGI("bus%u buffer capacity=%u bytes\n",
           (unsigned)busIndex,
           (unsigned)allocated);
  return true;
}

bool I2CManager::setTransactionTimeout(uint8_t busIndex, uint16_t timeoutMs) {
  if (busIndex >= board::BOARD_MAX_I2C_BUSES || !s_available[busIndex]) return false;
  TwoWire* wire = s_buses[busIndex];
  if (!wire) return false;
  wire->setTimeOut(timeoutMs);
  s_transactionTimeoutMs[busIndex] = timeoutMs;
  return true;
}

uint32_t I2CManager::clockHz(uint8_t busIndex) {
  if (busIndex >= board::BOARD_MAX_I2C_BUSES) return 0;
  if (s_startupClockOverride[busIndex]) return s_startupClockOverride[busIndex];
  const auto* cfg = s_profiles[busIndex];
  return cfg ? (cfg->hz ? cfg->hz : 100000UL) : 0;
}

bool I2CManager::setStartupClockOverride(uint8_t busIndex, uint32_t hz) {
  if (busIndex >= board::BOARD_MAX_I2C_BUSES || !s_available[busIndex] ||
      I2CBusScheduler::isRunning()) return false;
  TwoWire* wire = s_buses[busIndex];
  if (!lock(wire, 200)) {
    if (hz == 0) {
      s_startupClockOverride[busIndex] = 0;
      s_available[busIndex] = false;
    }
    return false;
  }
  const uint32_t previous = s_startupClockOverride[busIndex];
  s_startupClockOverride[busIndex] = hz;
  const uint32_t effective = clockHz(busIndex);
  const bool ok = wire->setClock(effective) && wire->getClock() == effective;
  if (!ok) {
    s_startupClockOverride[busIndex] = hz == 0 ? 0 : previous;
    // Never resume acquisition at an unintended diagnostic speed.
    if (hz == 0) s_available[busIndex] = false;
  }
  unlock(wire);
  return ok;
}

I2CManager::RegisterProbeResult I2CManager::probeRegister(
    uint8_t busIndex, uint8_t address, uint8_t reg, uint8_t length) {
  RegisterProbeResult out;
  out.error = ESP_ERR_INVALID_ARG;
  if (address == 0 || address > 0x7F || length == 0 || length > sizeof(out.bytes)) return out;
  TwoWire* wire = bus(busIndex);
  out.error = ESP_ERR_INVALID_STATE;
  if (!wire) return out;
  out.error = ESP_ERR_TIMEOUT;
  if (!lock(wire, 200)) return out;
  size_t received = 0;
  const uint32_t hz = clockHz(busIndex);
  out.error = ESP_FAIL;
  if (wire->setClock(hz) && wire->getClock() == hz) {
    out.error = i2cWriteReadNonStop(busIndex, address, &reg, 1, out.bytes,
                                   length, wire->getTimeOut(), &received);
  }
  out.received = static_cast<uint16_t>(received);
  out.ok = out.error == ESP_OK && received == length;
  unlock(wire);
  return out;
}

bool I2CManager::recoverBus(uint8_t busIndex, bool force) {
  if (busIndex >= board::BOARD_MAX_I2C_BUSES) return false;
  if (force && I2CBusScheduler::isRunning()) return false;
  TwoWire* wire = s_buses[busIndex];
  const board::I2CProfile* cfg = s_profiles[busIndex];
  if (!wire || !cfg || !cfg->present || cfg->sda < 0 || cfg->scl < 0) return false;
  if (!lock(wire, 200)) {
    I2C_LOGW("bus%u recovery deferred: mutex busy\n", (unsigned)busIndex);
    return false;
  }

  const uint32_t nowMs = millis();
  if (!force && s_recoveryAttemptKnown[busIndex] &&
      (uint32_t)(nowMs - s_recovery[busIndex].lastAttemptMs) < kRecoveryCooldownMs) {
    const bool previousOk = s_lastRecoveryOk[busIndex];
    I2C_LOGW("bus%u recovery skipped: cooldown previous_controller_ok=%u\n",
             (unsigned)busIndex, previousOk ? 1u : 0u);
    unlock(wire);
    return previousOk;
  }

  BusRecoveryStatus& status = s_recovery[busIndex];
  s_recoveryAttemptKnown[busIndex] = true;
  status.lastAttemptMs = nowMs;
  ++status.attempts;
  status.clockPulses = 0;
  // The controller is detached before GPIO bus-clear pulses. The external
  // pull-ups provide the released level; never drive either line high.
  wire->end();
  pinMode((uint8_t)cfg->sda, INPUT_PULLUP);
  pinMode((uint8_t)cfg->scl, INPUT_PULLUP);
  delayMicroseconds(5);
  status.sdaLowBefore = digitalRead((uint8_t)cfg->sda) == LOW;
  status.sclLowBefore = digitalRead((uint8_t)cfg->scl) == LOW;

  if (status.sdaLowBefore && !status.sclLowBefore) {
    digitalWrite((uint8_t)cfg->scl, HIGH);
    pinMode((uint8_t)cfg->scl, OUTPUT_OPEN_DRAIN);
    for (uint8_t pulse = 0; pulse < 9 && digitalRead((uint8_t)cfg->sda) == LOW; ++pulse) {
      digitalWrite((uint8_t)cfg->scl, LOW);
      delayMicroseconds(5);
      digitalWrite((uint8_t)cfg->scl, HIGH);
      for (uint8_t wait = 0; wait < 20 && digitalRead((uint8_t)cfg->scl) == LOW; ++wait) {
        delayMicroseconds(5);
      }
      ++status.clockPulses;
      if (digitalRead((uint8_t)cfg->scl) == LOW) break;
      delayMicroseconds(5);
    }
    // Generate STOP only if the clock has been released. A permanently low
    // SCL cannot be cleared by the controller and needs physical attention.
    if (digitalRead((uint8_t)cfg->scl) == HIGH) {
      digitalWrite((uint8_t)cfg->sda, LOW);
      pinMode((uint8_t)cfg->sda, OUTPUT_OPEN_DRAIN);
      delayMicroseconds(5);
      digitalWrite((uint8_t)cfg->sda, HIGH);
      delayMicroseconds(5);
    }
  }

  pinMode((uint8_t)cfg->sda, INPUT_PULLUP);
  pinMode((uint8_t)cfg->scl, INPUT_PULLUP);
  delayMicroseconds(5);
  status.sdaLowAfter = digitalRead((uint8_t)cfg->sda) == LOW;
  status.sclLowAfter = digitalRead((uint8_t)cfg->scl) == LOW;
  const uint32_t hz = clockHz(busIndex);
  const bool started = wire->begin(cfg->sda, cfg->scl, hz);
  const bool clockOk = started && wire->setClock(hz) && wire->getClock() == hz;
  bool bufferOk = false;
  if (started) {
    wire->setTimeOut(s_transactionTimeoutMs[busIndex]);
    bufferOk = wire->setBufferSize(s_bufferCapacity[busIndex]) >=
        s_bufferCapacity[busIndex];
  }
  const bool ok = clockOk && bufferOk && !status.sdaLowAfter && !status.sclLowAfter;
  s_available[busIndex] = ok;
  if (!ok) wire->end();
  s_lastRecoveryOk[busIndex] = ok;
  if (ok) {
    ++status.successes;
    status.generation = s_recoveryGeneration[busIndex].fetch_add(
        1, std::memory_order_acq_rel) + 1;
  } else {
    ++status.failures;
  }
  I2C_LOGW("bus%u recovery %s pre_sda_low=%u pre_scl_low=%u post_sda_low=%u post_scl_low=%u pulses=%u controller=%u buffer=%u clock=%u hz=%lu device_response=unchecked\n",
           (unsigned)busIndex, ok ? "controller_ready" : "failed",
           status.sdaLowBefore ? 1u : 0u, status.sclLowBefore ? 1u : 0u,
           status.sdaLowAfter ? 1u : 0u, status.sclLowAfter ? 1u : 0u,
           (unsigned)status.clockPulses, started ? 1u : 0u, bufferOk ? 1u : 0u,
           clockOk ? 1u : 0u, (unsigned long)hz);
  StartupLog::recordf("[I2C] bus%u recovery %s pre_sda_low=%u pre_scl_low=%u post_sda_low=%u post_scl_low=%u pulses=%u controller=%u buffer=%u clock=%u hz=%lu device_response=unchecked\n",
           (unsigned)busIndex, ok ? "controller_ready" : "failed",
           status.sdaLowBefore ? 1u : 0u, status.sclLowBefore ? 1u : 0u,
           status.sdaLowAfter ? 1u : 0u, status.sclLowAfter ? 1u : 0u,
           (unsigned)status.clockPulses, started ? 1u : 0u, bufferOk ? 1u : 0u,
           clockOk ? 1u : 0u, (unsigned long)hz);
  unlock(wire);
  return ok;
}

uint32_t I2CManager::recoveryGeneration(uint8_t busIndex) {
  return busIndex < board::BOARD_MAX_I2C_BUSES
      ? s_recoveryGeneration[busIndex].load(std::memory_order_acquire)
      : 0;
}

void I2CManager::resetRecoveryStats() {
  for (uint8_t busIndex = 0; busIndex < board::BOARD_MAX_I2C_BUSES; ++busIndex) {
    s_recovery[busIndex] = BusRecoveryStatus{};
    s_recoveryAttemptKnown[busIndex] = false;
    s_lastRecoveryOk[busIndex] = false;
    s_recoveryGeneration[busIndex].store(0, std::memory_order_release);
  }
}

const I2CManager::BusRecoveryStatus& I2CManager::recoveryStatus(uint8_t busIndex) {
  static const BusRecoveryStatus empty;
  return busIndex < board::BOARD_MAX_I2C_BUSES ? s_recovery[busIndex] : empty;
}

bool I2CManager::lock(TwoWire* wire, uint32_t timeoutMs) {
#if defined(ESP32)
  const int idx = busIndexFor_(wire);
  if (idx < 0) return false;
  SemaphoreHandle_t m = s_mutexes[idx];
  if (!m) return false;
  TickType_t ticks = pdMS_TO_TICKS(timeoutMs ? timeoutMs : 1);
  if (ticks == 0) ticks = 1;
  return xSemaphoreTake(m, ticks) == pdTRUE;
#else
  (void)wire;
  (void)timeoutMs;
  return true;
#endif
}

void I2CManager::unlock(TwoWire* wire) {
#if defined(ESP32)
  const int idx = busIndexFor_(wire);
  if (idx < 0) return;
  SemaphoreHandle_t m = s_mutexes[idx];
  if (m) xSemaphoreGive(m);
#else
  (void)wire;
#endif
}
