#pragma once

#include <Arduino.h>
#include <SPI.h>
#include <stddef.h>
#include <stdint.h>

#include "BoardProfile.h"

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
bool transfer(
    int8_t csPin,
    const SPISettings& settings,
    const uint8_t* tx,
    uint8_t* rx,
    size_t length,
    uint32_t lockTimeoutMs = 50);

const Diagnostics& diagnostics();

}  // namespace SharedSpiBus
