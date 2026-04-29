#pragma once
#include <Arduino.h>
#include <map>
#include <memory>
#include "OutputTransform.h"
#include <FS.h>   // for fs::FS

namespace fs { class FS; }   // FS-style interface

class TransformRegistry {
public:
  // Scan /cal/<sensorId>/ and load transforms
  bool loadForSensor(const String& sensorId, fs::FS& fs);

  // Force reload
  bool reload(const String& sensorId, fs::FS& fs) { return loadForSensor(sensorId, fs); }

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

  bool loadPoly_fs (const String& sensorId, const String& path, fs::FS& fs);
  bool loadPoly_cfg_fs (const String& sensorId, const String& path, fs::FS& fs);
  bool loadLUT_fs  (const String& sensorId, const String& path, fs::FS& fs);
};

extern TransformRegistry gTransforms;
