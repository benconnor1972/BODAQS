#pragma once
#include <Arduino.h>
#include <map>
#include <memory>
#include "OutputTransform.h"

namespace fs { class FS; }   // FS-style interface
class SdFs;                  // <- forward-declare (SdFat typedefs to this)

class TransformRegistry {
public:
  // Scan /cal/<sensorId>/ and load transforms
  bool loadForSensor(const String& sensorId, fs::FS& fs);  // FS backend
  bool loadForSensor(const String& sensorId, SdFs& sd);    // SdFat backend (SdFs)

  // Force reload
  bool reload(const String& sensorId, fs::FS& fs)  { return loadForSensor(sensorId, fs); }
  bool reload(const String& sensorId, SdFs& sd)    { return loadForSensor(sensorId, sd); }

  // Accessors
  const OutputTransform* get(const String& sensorId, const String& id) const;
  OutputTransform* identity();  // returns a static singleton

  std::vector<TransformMeta> list(const String& sensorId) const;

private:
  struct SensorBucket {
    std::map<String, std::unique_ptr<OutputTransform>> byId; // id -> transform
  };
  std::map<String, SensorBucket> sensors_; // sensorId -> bucket

  // helpers
  String calDirFor(const String& sensorId) const;

  // Backends
  bool loadPoly_fs (const String& sensorId, const String& path, fs::FS& fs);
  bool loadPoly_cfg_fs (const String& sensorId, const String& path, fs::FS& fs);  // <-- add this
  bool loadLUT_fs  (const String& sensorId, const String& path, fs::FS& fs);

  bool loadPoly_sd (const String& sensorId, const String& path, SdFs& sd);
  bool loadPoly_cfg_sd (const String& sensorId, const String& path, SdFs& sd);    // <-- add this
  bool loadLUT_sd  (const String& sensorId, const String& path, SdFs& sd);
};

extern TransformRegistry gTransforms;
