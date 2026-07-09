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

  virtual void asyncSchedulerStarting() {}
  virtual void asyncSchedulerStopped() {}
};

namespace I2CBusScheduler {
  bool registerClient(I2CAsyncClient* client);
  void unregisterClient(I2CAsyncClient* client);

  void resetTimingStats();
  const I2CBusSchedulerTimingStats& timingStats();

  void start();
  void stop();
  bool isRunning();

  void recordRowUse(I2CAsyncClient* client, uint32_t ageUs, bool fresh, bool haveSample);
}
