#pragma once
#include "SensorInventory.h"

namespace CanMasterDiscovery {
// Fitted endpoint types are presence evidence. Streaming/SYNC support must come
// from implemented capability descriptors, never from a fitted endpoint mask.
inline uint32_t endpointTypeCapabilities(uint8_t endpoint) {
  switch (endpoint) {
    case 0: return SENSOR_CAP_IMU;
    case 1:
    case 2: return SENSOR_CAP_ANALOG;
    case 3:
    case 4: return SENSOR_CAP_I2C;
    default: return SENSOR_CAP_NONE;
  }
}
inline uint32_t providerTypeCapabilities(uint16_t endpointMask) {
  uint32_t capabilities = SENSOR_CAP_NONE;
  for (uint8_t endpoint = 0; endpoint < 6; ++endpoint) {
    if (endpointMask & (1U << endpoint)) {
      capabilities |= endpointTypeCapabilities(endpoint);
    }
  }
  return capabilities;
}
}  // namespace CanMasterDiscovery
