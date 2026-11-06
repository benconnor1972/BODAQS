#pragma once

#include <Arduino.h>
#include <SPI.h>
#include <stddef.h>
#include <stdint.h>

#include "BoardProfile.h"
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
#include "TimingStats.h"
#endif

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

#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
struct ProbeParticipant {
  int8_t csPin = -1;
  uint32_t transfers = 0;
  uint64_t bytes = 0;
  uint32_t lockFailures = 0;
  TimingSummary lockWait;
  TimingSummary ownership;
};
struct ProbeStats { ProbeParticipant participant[8]; };
// Reset only while every participant is stopped. Snapshot is independently locked.
void probeReset();
ProbeStats probeSnapshot();
#endif

}  // namespace SharedSpiBus
