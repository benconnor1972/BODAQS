#include "I2CManager.h"
#include "DebugLog.h"
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
  }

  const uint8_t count = (bp.i2c_count < board::BOARD_MAX_I2C_BUSES)
    ? bp.i2c_count
    : board::BOARD_MAX_I2C_BUSES;

  for (uint8_t i = 0; i < count; ++i) {
    const board::I2CProfile& cfg = bp.i2c[i];
    s_profiles[i] = &cfg;
#if defined(ESP32)
    if (!s_mutexes[i]) s_mutexes[i] = xSemaphoreCreateMutex();
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
    w->begin(cfg.sda, cfg.scl);
    w->setClock(hz);
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

bool I2CManager::lock(TwoWire* wire, uint32_t timeoutMs) {
#if defined(ESP32)
  const int idx = busIndexFor_(wire);
  if (idx < 0) return false;
  SemaphoreHandle_t m = s_mutexes[idx];
  if (!m) return true;
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
