#pragma once
#include <stdint.h>
#include "SensorParams.h"   // for ParamPack

constexpr uint8_t MAX_SENSORS = 16;   // must be visible to ConfigManager.h

// Extend as you add new sensors (keep 0 = Unknown).
enum class SensorType : uint8_t {
  Unknown                = 0,
  AnalogPot              = 1,
  AS5600StringPotAnalog  = 2,
  AS5600StringPotI2C     = 3,
  // StrainGauge = 2,
  // Accelerometer = 3,
};

// One configured sensor entry (loaded from sensors.cfg).
// Note: ParamPack is a read-only view into ConfigManager-owned storage.
struct SensorSpec {
  SensorType type         = SensorType::Unknown;
  char       name[16]     = "sensor";
  bool       mutedDefault = false;
  ParamPack  params;     // key/value parameters for this sensor
};
