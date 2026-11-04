#pragma once

#include <stdint.h>

#include "SensorAssignment.h"
#include "SensorTopology.h"

enum SensorCapability : uint32_t {
  SENSOR_CAP_NONE = 0,
  SENSOR_CAP_IMU = 1u << 0,
  SENSOR_CAP_ANALOG = 1u << 1,
  SENSOR_CAP_I2C = 1u << 2,
  SENSOR_CAP_NATIVE_STREAM = 1u << 3,
  SENSOR_CAP_SYNC_CAPTURE = 1u << 4,
};

struct SensorProviderObservation {
  SensorProviderId id;
  bool present = false;
  bool healthy = false;
  uint64_t hardwareUid = 0;
  uint32_t capabilities = SENSOR_CAP_NONE;
  uint16_t protocolVersion = 0;
  uint32_t configurationRevision = 0;
};

struct SensorEndpointObservation {
  SensorAssignment endpoint;
  bool present = false;
  bool healthy = false;
  uint32_t capabilities = SENSOR_CAP_NONE;
  uint32_t deviceIdentity = 0;
};

class SensorInventory {
public:
  static constexpr uint8_t MAX_PROVIDERS = 1 + MAX_CAN_SENSOR_NODES;
  static constexpr uint8_t MAX_ENDPOINTS = 32;

  void clear();
  bool observeProvider(const SensorProviderObservation& observation);
  bool observeEndpoint(const SensorEndpointObservation& observation);
  const SensorProviderObservation* provider(const SensorProviderId& id) const;
  const SensorEndpointObservation* endpoint(const SensorAssignment& id) const;
  const SensorProviderObservation* providerAt(uint8_t index) const;
  const SensorEndpointObservation* endpointAt(uint8_t index) const;
  uint8_t providerCount() const { return providerCount_; }
  uint8_t endpointCount() const { return endpointCount_; }

private:
  SensorProviderObservation providers_[MAX_PROVIDERS];
  SensorEndpointObservation endpoints_[MAX_ENDPOINTS];
  uint8_t providerCount_ = 0;
  uint8_t endpointCount_ = 0;
};

