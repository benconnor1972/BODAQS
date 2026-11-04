#pragma once

#include <stdint.h>

enum class SensorProviderKind : uint8_t {
  Local = 0,
  CanNode = 1,
};

struct SensorProviderId {
  SensorProviderKind kind = SensorProviderKind::Local;
  uint8_t index = 0;

  bool operator==(const SensorProviderId& other) const {
    return kind == other.kind && index == other.index;
  }
  bool operator!=(const SensorProviderId& other) const { return !(*this == other); }
};

static constexpr uint8_t MAX_CAN_SENSOR_NODES = 4;

