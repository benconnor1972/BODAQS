#include "SensorRegistry.h"
#include "Calibration.h"   // CalModeMask, CAL_*
#include <string.h>

namespace {
  struct Entry { SensorType t; SensorTypeInfo info; };
  constexpr uint8_t kMax = 8;
  Entry   table[kMax]{};
  uint8_t used = 0;

  // Defaults if a type registered via legacy API (no key/label/mask):
  inline const char* defaultKeyFor(SensorType t) {
    switch (t) {
      case SensorType::AnalogPot: return "analog_pot";
      case SensorType::Unknown:
      default:                    return "unknown";
    }
  }
  inline const char* defaultLabelFor(SensorType t) {
    switch (t) {
      case SensorType::AnalogPot: return "Analog Potentiometer";
      case SensorType::Unknown:
      default:                    return "Unknown Sensor";
    }
  }

  inline Entry* findSlot(SensorType t) {
    for (uint8_t i = 0; i < used; ++i) {
      if (table[i].t == t) return &table[i];
    }
    return nullptr;
  }
} // anonymous

namespace SensorRegistry {

  bool registerType(SensorType t, ParamDefsFn pd, CreateFn cf) {
    // Legacy path: key/label/mask default
    Entry* e = findSlot(t);
    if (!e) {
      if (used >= kMax) return false;
      e = &table[used++];
      e->t = t;
    }
    SensorTypeInfo info;
    // zero-init then fill
    info.key = nullptr;
    info.label = nullptr;
    info.paramDefs = pd;
    info.create = cf;
    //info.supportedCalMask = CAL_NONE;  // default for legacy
    e->info = info;
    return true;
  }

  bool registerType(SensorType t,
                    const char* key,
                    const char* label,
                    ParamDefsFn pd,
                    CreateFn cf) {
    // Back-compat: default mask = CAL_NONE
    return registerType(t, key, label, pd, cf, CAL_NONE);
  }

  bool registerType(SensorType t,
                    const char* key,
                    const char* label,
                    ParamDefsFn pd,
                    CreateFn cf,
                    CalModeMask supportedMask) {
    Entry* e = findSlot(t);
    if (!e) {
      if (used >= kMax) return false;
      e = &table[used++];
      e->t = t;
    }
    SensorTypeInfo info;
    info.key = key;
    info.label = label;
    info.paramDefs = pd;
    info.create = cf;
    info.supportedCalMask = supportedMask;
    e->info = info;
    return true;
  }

  const SensorTypeInfo* lookup(SensorType t) {
    for (uint8_t i = 0; i < used; ++i) if (table[i].t == t) return &table[i].info;
    return nullptr;
  }

  const char* typeKey(SensorType t) {
    const SensorTypeInfo* ti = lookup(t);
    if (ti && ti->key && ti->key[0]) return ti->key;
    return defaultKeyFor(t);
  }

  const char* typeLabel(SensorType t) {
    const SensorTypeInfo* ti = lookup(t);
    if (ti && ti->label && ti->label[0]) return ti->label;
    return defaultLabelFor(t);
  }

  CalModeMask supportedCalMask(SensorType t) {
    switch (t) {
      case SensorType::AnalogPot:
        return static_cast<CalModeMask>(CAL_ZERO | CAL_RANGE);
      // Add other types as you implement calibration support:
      // case SensorType::Accelerometer: return CAL_NONE;
      default:
        return CAL_NONE;
    }
  }
} // namespace SensorRegistry
