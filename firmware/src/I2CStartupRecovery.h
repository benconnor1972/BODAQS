#pragma once

#include <stdint.h>

enum class I2CStartupKind : uint8_t { BMI270, AS5600 };

// Startup health is transport/configuration health; a missing AS5600 magnet
// is deliberately not an initialization failure.
struct I2CStartupStatus {
  I2CStartupKind kind = I2CStartupKind::BMI270;
  uint8_t busIndex = 0;
  uint8_t address = 0;
  bool ready = false;
  uint8_t step = 0;
  int16_t result = 0;
  bool chipRead = false;
  uint8_t chip = 0;
};

namespace I2CStartupRecovery {
enum class Phase : uint8_t { Delayed, ControllerReset, SlowClock };
constexpr uint8_t kMaximumSensors = 32;
constexpr uint8_t kMaximumBuses = 2;
constexpr uint32_t kDelayedRetryMs = 250;
constexpr uint32_t kSlowClockHz = 100000;

// Address-only probes retry without turning a temporary NACK into a permanent
// startup decision. Each invocation has at most one controller recovery.
template <class Probe, class Recover, class Wait>
bool probeWithRetries(Probe probe, Recover recover, Wait wait, bool allowRecovery) {
  for (uint8_t round = 0; round < 2; ++round) {
    for (uint8_t attempt = 0; attempt < 3; ++attempt) {
      if (probe()) return true;
      if (attempt < 2) wait(10);
    }
    if (round != 0 || !allowRecovery || !recover()) break;
  }
  return false;
}

// Ops owns hardware access and logging. The same coordinator is exercised by
// the host fault-injection tests. A successful peer is never reinitialized.
template <class Ops>
void run(Ops& ops, bool diagnostic) {
  const uint8_t count = ops.count();
  if (count > kMaximumSensors || !ops.safe()) {
    ops.aborted();
    return;
  }
  bool failed[kMaximumSensors] {};
  uint8_t failures = 0;
  for (uint8_t i = 0; i < count; ++i) {
    I2CStartupStatus status;
    if (!ops.describe(i, status)) continue;
    ops.snapshot(i, status);
    failed[i] = !status.ready;
    if (failed[i]) ++failures;
  }
  if (failures) ops.wait(kDelayedRetryMs);
  const uint8_t phases = diagnostic ? 3 : 1;
  for (uint8_t phase = 0; failures && phase < phases; ++phase) {
    bool busAttempted[kMaximumBuses] {};
    bool busReady[kMaximumBuses] {};
    for (uint8_t i = 0; i < count; ++i) {
      if (!failed[i]) continue;
      I2CStartupStatus status;
      if (!ops.describe(i, status) || status.busIndex >= kMaximumBuses) continue;
      if (status.ready) { failed[i] = false; --failures; continue; }
      const auto stage = static_cast<Phase>(phase);
      const uint8_t bus = status.busIndex;
      if (phase != 0 && !busAttempted[bus]) {
        busAttempted[bus] = true;
        busReady[bus] = phase == 1 ? ops.restart(bus) : ops.slowClock(bus);
      }
      if (phase != 0 && !busReady[bus]) continue;
      // Diagnostic stages must not reset the controller implicitly: this
      // preserves the distinction between elapsed time, reset and bus speed.
      if (diagnostic && !ops.probe(i, stage)) continue;
      if (ops.retry(i, stage, !diagnostic)) {
        failed[i] = false;
        --failures;
      }
    }
    if (phase == 2) {
      for (uint8_t bus = 0; bus < kMaximumBuses; ++bus) {
        if (busAttempted[bus]) ops.restoreClock(bus);
      }
    }
  }
  // Clock restoration can fail after a successful slow-speed retry. Recheck
  // health, including peers on a controller which was disabled on failure.
  failures = 0;
  for (uint8_t i = 0; i < count; ++i) {
    I2CStartupStatus status;
    if (ops.describe(i, status) && !status.ready) ++failures;
  }
  ops.finished(failures);
}
} // namespace I2CStartupRecovery
