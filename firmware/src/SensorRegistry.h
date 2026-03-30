#ifndef SENSOR_REGISTRY_H
#define SENSOR_REGISTRY_H

#include "SensorTypes.h"
#include "SensorParams.h"
#include "Calibration.h"
#include <stdint.h>

class Sensor;  // forward

// Function signatures each sensor type exposes to the registry
using ParamDefsFn = const ParamDef* (*)(size_t& count);
using CreateFn    = Sensor*         (*)(const char* name, const ParamPack& params, bool mutedDefault);


struct SensorTypeInfo {
  SensorType type;
  const char* key;    // "analog_pot"
  const char* label;  // "Analog Potentiometer"
  const ParamDef* (*paramDefs)(size_t& count);
  Sensor* (*create)(const char* instanceName, const ParamPack& params, bool mutedDefault);
  CalModeMask supportedCalMask = CAL_NONE; // <-- NEW: type capability
};

namespace SensorRegistry {
  // existing APIs you already have...
  bool registerType(SensorType t, const char* key, const char* label, const ParamDef* (*defs)(size_t&), Sensor* (*create)(const char*, const ParamPack&, bool));

  // NEW: overload that accepts a supported-calibration mask
  bool registerType(SensorType t, const char* key, const char* label, const ParamDef* (*defs)(size_t&),
                    Sensor* (*create)(const char*, const ParamPack&, bool), CalModeMask supportedMask);

  const SensorTypeInfo* lookup(SensorType t);
  const char*           typeKey(SensorType t);
  const char*           typeLabel(SensorType t);

  // NEW: query helper
  CalModeMask supportedCalMask(SensorType t);

  /*
  inline CalMask supportedCalMask(SensorType t) {
    switch (t) {
      case SensorType::AnalogPot:
        return (CalMask)(CAL_ZERO | CAL_RANGE);
      // case SensorType::Accelerometer: return CAL_NONE; // example
      // case SensorType::StrainGauge:   return CAL_ZERO; // example
      default:
        return CAL_NONE;
    }
  }
  */
}

#endif // SENSOR_REGISTRY_H
