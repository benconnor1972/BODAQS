#include "StartupLog.h"
#include "I2CStartupDiagnostics.h"

#include <Arduino.h>
#include "I2CStartupRecovery.h"
#include "I2CManager.h"
#include "I2CBusScheduler.h"
#include "LoggingManager.h"
#include "SensorManager.h"
#include "esp_system.h"

namespace {
const char* phaseName(I2CStartupRecovery::Phase phase) {
  switch (phase) {
    case I2CStartupRecovery::Phase::Delayed: return "delayed";
    case I2CStartupRecovery::Phase::ControllerReset: return "controller_reset";
    case I2CStartupRecovery::Phase::SlowClock: return "100khz";
  }
  return "unknown";
}

struct StartupOps {
  uint8_t count() const { return SensorManager::count(); }
  bool safe() const { return !LoggingManager::isRunning() && !I2CBusScheduler::isRunning(); }
  void aborted() const { StartupLog::println("[I2C-STARTUP] ABORTED acquisition_active_or_too_many_sensors"); }
  bool describe(uint8_t index, I2CStartupStatus& status) const {
    Sensor* sensor = SensorManager::at(index);
    return sensor && sensor->describeI2CStartup(status);
  }
  void logStatus(uint8_t index, const char* stage, const I2CStartupStatus& status) const {
    StartupLog::printf("[I2C-STARTUP] %s uptime_ms=%lu sensor=%s kind=%s bus=%u addr=0x%02X ready=%u step=%u result=%d chip_read=%u chip=0x%02X\n",
                  stage, (unsigned long)millis(), SensorManager::at(index)->name(),
                  status.kind == I2CStartupKind::BMI270 ? "bmi270" : "as5600",
                  (unsigned)status.busIndex, (unsigned)status.address, status.ready ? 1u : 0u,
                  (unsigned)status.step, (int)status.result, status.chipRead ? 1u : 0u,
                  (unsigned)status.chip);
  }
  void snapshot(uint8_t index, const I2CStartupStatus& status) const {
    logStatus(index, "initial", status);
  }
  void wait(uint32_t ms) const { delay(ms); }
  bool restart(uint8_t bus) const {
    const bool ok = I2CManager::recoverBus(bus, true);
    StartupLog::printf("[I2C-STARTUP] controller_reset bus=%u controller_ok=%u uptime_ms=%lu\n",
                  (unsigned)bus, ok ? 1u : 0u, (unsigned long)millis());
    // Allow the released bus to settle without resetting any sensor.
    delay(10);
    return ok;
  }
  bool slowClock(uint8_t bus) const {
    const bool ok = I2CManager::setStartupClockOverride(bus, I2CStartupRecovery::kSlowClockHz);
    StartupLog::printf("[I2C-STARTUP] clock_override bus=%u requested_hz=100000 ok=%u\n",
                  (unsigned)bus, ok ? 1u : 0u);
    return ok;
  }
  void restoreClock(uint8_t bus) const {
    const bool ok = I2CManager::setStartupClockOverride(bus, 0);
    StartupLog::printf("[I2C-STARTUP] clock_restore bus=%u normal_hz=%lu ok=%u bus_available=%u\n",
                  (unsigned)bus, (unsigned long)I2CManager::clockHz(bus),
                  ok ? 1u : 0u, I2CManager::available(bus) ? 1u : 0u);
  }
  bool probe(uint8_t index, I2CStartupRecovery::Phase phase) const {
    I2CStartupStatus status;
    if (!describe(index, status)) return false;
    const bool imu = status.kind == I2CStartupKind::BMI270;
    const uint8_t reg = imu ? 0x00 : 0x0C;
    const uint8_t length = imu ? 1 : 2;
    bool anyValid = false;
    for (uint8_t attempt = 1; attempt <= 3; ++attempt) {
      const auto result = I2CManager::probeRegister(status.busIndex, status.address, reg, length);
      const bool valid = result.ok && (!imu || result.bytes[0] == 0x24);
      anyValid = anyValid || valid;
      StartupLog::printf("[I2C-STARTUP] register_probe phase=%s uptime_ms=%lu sensor=%s bus=%u addr=0x%02X hz=%lu attempt=%u reg=0x%02X esp=%ld(%s) received=%u byte0=0x%02X byte1=0x%02X valid=%u\n",
                    phaseName(phase), (unsigned long)millis(), SensorManager::at(index)->name(),
                    (unsigned)status.busIndex, (unsigned)status.address,
                    (unsigned long)I2CManager::clockHz(status.busIndex), (unsigned)attempt,
                    (unsigned)reg, (long)result.error, esp_err_to_name(result.error),
                    (unsigned)result.received, (unsigned)result.bytes[0],
                    (unsigned)result.bytes[1], valid ? 1u : 0u);
      if (attempt < 3) delay(5);
    }
    return anyValid;
  }
  bool retry(uint8_t index, I2CStartupRecovery::Phase phase, bool allowRecovery) const {
    I2CStartupStatus status;
    if (!describe(index, status)) return false;
    if (allowRecovery && !I2CManager::available(status.busIndex) &&
        !I2CManager::recoverBus(status.busIndex, true)) return false;
    StartupLog::printf("[I2C-STARTUP] retry phase=%s uptime_ms=%lu sensor=%s hz=%lu implicit_bus_recovery=%u\n",
                  phaseName(phase), (unsigned long)millis(), SensorManager::at(index)->name(),
                  (unsigned long)I2CManager::clockHz(status.busIndex), allowRecovery ? 1u : 0u);
    const bool ready = SensorManager::at(index)->retryI2CStartup(allowRecovery);
    describe(index, status);
    logStatus(index, phaseName(phase), status);
    return ready && status.ready;
  }
  void finished(uint8_t failures) const {
    unsigned checked = 0;
    for (uint8_t i = 0; i < count(); ++i) {
      I2CStartupStatus status;
      if (describe(i, status)) { ++checked; logStatus(i, "final", status); }
    }
    StartupLog::setFinalReadiness(checked, failures);
    StartupLog::printf("[I2C-STARTUP] DONE remaining_failed=%u normal_loop_resuming uptime_ms=%lu\n",
                  (unsigned)failures, (unsigned long)millis());
  }
};
} // namespace

void I2CStartupDiagnostics::run() {
  constexpr bool diagnostic =
#if defined(BODAQS_I2C_STARTUP_DIAGNOSTICS)
      true;
#else
      false;
#endif
  StartupLog::printf("[I2C-STARTUP] START reset_reason=%u uptime_ms=%lu diagnostic=%u delayed_ms=%lu phases=%s identity_path=%s\n",
                (unsigned)esp_reset_reason(), (unsigned long)millis(), diagnostic ? 1u : 0u,
                (unsigned long)I2CStartupRecovery::kDelayedRetryMs,
                diagnostic ? "delayed,controller_reset,100khz" : "delayed",
                diagnostic ? "arduino_hal" : "wire");
  StartupOps ops;
  I2CStartupRecovery::run(ops, diagnostic);
}
