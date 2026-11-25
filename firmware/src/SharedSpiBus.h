#pragma once

#include <Arduino.h>
#include <SPI.h>
#include <stddef.h>
#include <stdint.h>

#include "BoardProfile.h"
#include "SpiTransactionContext.h"
#include "SpiTransferTiming.h"

namespace SharedSpiBus {

struct Diagnostics {
  bool initialized = false;
  uint32_t transactions = 0;
  uint64_t bytesTransferred = 0;
  uint32_t lockTimeouts = 0;
};

// Idempotently initializes the logger's shared hardware SPI bus.
bool begin(const board::SPIProfile& profile);
bool ready();

// Performs one complete, mutually exclusive CS-bounded transaction.
// Optional spacing is measured from the previous start on this same CS, even
// if that earlier call was unpaced. Waiting releases the mutex and SPI
// transaction; the deadline is rechecked under the mutex before starting.
// lockTimeoutMs bounds each mutex acquisition. A paced CS has one logical owner;
// concurrent same-CS traffic can extend the wait. Zero spacing stays unpaced.
// Optional CS setup runs after asserting CS and before clocking any bytes;
// it retains the bus mutex and SPI transaction. Existing callers default to0.
// Optional caller-owned timing splits successful calls into lock/pacing wait,
// prepare (beginTransaction/CS/setup/context), HAL transfer, and finish before
// unlock. Failed calls expose only any lock wait; output is cleared on entry.
bool transfer(
    int8_t csPin,
    const SPISettings& settings,
    const uint8_t* tx,
    uint8_t* rx,
    size_t length,
    uint32_t lockTimeoutMs = 50,
    uint32_t minimumStartSpacingUs = 0,
    uint32_t csSetupUs = 0,
    SpiTransactionContext* context = nullptr,
    SpiTransferTiming* timing = nullptr);

const Diagnostics& diagnostics();

}  // namespace SharedSpiBus
