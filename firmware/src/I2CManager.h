#pragma once

#include <stdint.h>
#include <Wire.h>
#include "BoardProfile.h"

namespace I2CManager {

struct BusRecoveryStatus {
  uint32_t attempts = 0;
  uint32_t successes = 0;
  uint32_t failures = 0;
  uint32_t generation = 0;
  uint32_t lastAttemptMs = 0;
  uint8_t clockPulses = 0;
  bool sdaLowBefore = false;
  bool sclLowBefore = false;
  bool sdaLowAfter = false;
  bool sclLowAfter = false;
};

void begin(const board::BoardProfile& bp);
bool available(uint8_t busIndex);
TwoWire* bus(uint8_t busIndex);
const board::I2CProfile* profile(uint8_t busIndex);
bool ensureBufferCapacity(uint8_t busIndex, size_t bytes);
bool setTransactionTimeout(uint8_t busIndex, uint16_t timeoutMs);
// Called after device-level recovery fails. Serializes against every normal
// user of this bus; never toggles pins while a transaction owns its mutex.
bool recoverBus(uint8_t busIndex, bool force = false);
// Startup only, with acquisition stopped. All BMI270 transactions use this
// effective clock rather than undoing a temporary diagnostic override.
uint32_t clockHz(uint8_t busIndex);
bool setStartupClockOverride(uint8_t busIndex, uint32_t hz);
struct RegisterProbeResult {
  int32_t error = 0;
  uint16_t received = 0;
  uint8_t bytes[2] {};
  bool ok = false;
};
// Same Arduino HAL transfer as Wire's repeated-START read, retaining ESP errors.
RegisterProbeResult probeRegister(uint8_t busIndex, uint8_t address,
                                 uint8_t reg, uint8_t length);
uint32_t recoveryGeneration(uint8_t busIndex);
void resetRecoveryStats();
// Read only while the bus scheduler is stopped.
const BusRecoveryStatus& recoveryStatus(uint8_t busIndex);
bool lock(TwoWire* wire, uint32_t timeoutMs = 50);
void unlock(TwoWire* wire);

} // namespace I2CManager
