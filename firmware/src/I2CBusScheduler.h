#pragma once

#include <Arduino.h>
#include <stdint.h>
#include "TimingStats.h"

class I2CAsyncClient {
public:
  virtual ~I2CAsyncClient() = default;

  virtual const char* asyncClientName() const = 0;
  virtual const char* asyncClientKind() const = 0;
  virtual uint8_t asyncI2CBusIndex() const = 0;
  virtual uint8_t asyncI2CAddress() const = 0;
  virtual uint16_t asyncTargetRateHz() const = 0;
  virtual bool asyncMuted() const = 0;
  virtual bool asyncAcquire() = 0;

  // Latency-sensitive clients have no device-side FIFO and benefit from being
  // sampled immediately before a long, non-preemptible buffered transfer.
  virtual bool asyncLatencySensitive() const { return false; }

  // Conservative scheduler estimate for one acquisition. It is used only for
  // bounded look-ahead arbitration, not for timing or data timestamps.
  virtual uint32_t asyncEstimatedAcquireUs() const { return 0; }

  // Opt-in bound used to admit long, low-priority transfers on a shared bus.
  // Zero means this client does not participate in admission control.
  virtual uint32_t asyncMaximumLowPriorityGapUs() const { return 0; }

  // Maximum number of latency-sensitive acquisitions which may be admitted
  // before one pending service of this buffered client. Zero disables yields.
  virtual uint8_t asyncMaximumLatencySensitiveYields() const { return 0; }

  virtual void asyncSchedulerStarting() {}
  virtual void asyncSchedulerStopped() {}
};

namespace I2CBusScheduler {
  struct LiveBusLoad {
    bool valid = false;
    bool running = false;
    uint16_t loadPermille = 0;
    uint16_t maximumLoadPermille = 0;
    uint32_t windowSequence = 0;
    uint32_t recentMissAgeUs = UINT32_MAX;
  };

  bool registerClient(I2CAsyncClient* client);
  void unregisterClient(I2CAsyncClient* client);

  void resetTimingStats();
  const I2CBusSchedulerTimingStats& timingStats();

  void start();
  void stop();
  bool isRunning();
  bool liveBusLoad(uint8_t busIndex, LiveBusLoad& out);

  // True when every participating active client on the bus was serviced
  // recently enough to tolerate the proposed non-preemptible transfer.
  bool lowPriorityWindowAvailable(
      uint8_t busIndex,
      uint32_t transferDurationUs,
      uint32_t guardUs = 5000);

  void recordRowUse(I2CAsyncClient* client, uint32_t ageUs, bool fresh, bool haveSample);
}
