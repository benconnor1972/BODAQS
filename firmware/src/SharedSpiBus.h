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

#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
struct ProbeOperation {
  uint16_t bytes=0;
  uint8_t tx0=0;
  bool hasTx=false,hasRx=false;
};
struct ProbeContext {
  uint32_t sequence=0;
  int8_t cs=-1,previousCs=-1;
  bool previousValid=false;
  uint32_t previousReleaseUs=0,csAssertUs=0,csReleaseUs=0;
  ProbeOperation operation,previousOperation;
};
// Four unselected mode1 bytes, under the same production mutex. No conversions.
bool probeUnselectedClocks(const board::SPIProfile& profile);
#endif

// Performs one complete, mutually exclusive CS-bounded transaction.
bool transfer(
    int8_t csPin,
    const SPISettings& settings,
    const uint8_t* tx,
    uint8_t* rx,
    size_t length,
    uint32_t lockTimeoutMs = 50
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
    // Runs after CS release while still owning the bus. Must be bounded/no I/O.
    , void (*probeAfterCsRelease)(void*) = nullptr, void* probeContext = nullptr, ProbeContext* transactionContext = nullptr,
    bool probeUnselected = false
#endif
    );

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
