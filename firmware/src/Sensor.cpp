#include "Sensor.h"
#include "TransformRegistry.h"
#include "OutputTransform.h"
#include "DebugLog.h"
#include <string.h>

#define XFORM_LOGD(...) LOGD_TAG("XFORM", __VA_ARGS__)

namespace {

void copyField_(char* dst, size_t cap, const char* src) {
  if (!dst || cap == 0) return;
  if (!src) src = "";
  size_t n = strlen(src);
  if (n >= cap) n = cap - 1;
  memcpy(dst, src, n);
  dst[n] = '\0';
}

const char* outputModeName_(OutputMode m) {
  switch (m) {
    case OutputMode::RAW:    return "raw";
    case OutputMode::LINEAR: return "linear";
    case OutputMode::POLY:   return "poly";
    case OutputMode::LUT:    return "lut";
    default:                 return "unknown";
  }
}

} // namespace

void Sensor::attachTransform(const TransformRegistry& reg) {
  const String sensorId = String(name()); // folder key: /cal/<name>/
  const bool selectedIsIdentity = (m_selectedTransformId == "identity");

  XFORM_LOGD("attach begin sensor='%s' selected='%s'\n",
             sensorId.c_str(),
             m_selectedTransformId.c_str());

  // 1) Try the selected transform via registry (unless empty)
  const OutputTransform* t = nullptr;
  bool triedSelected = false;

  if (m_selectedTransformId.length() && !selectedIsIdentity) {
    triedSelected = true;
    XFORM_LOGD("lookup: reg.get(sensor='%s', id='%s')\n",
               sensorId.c_str(),
               m_selectedTransformId.c_str());

    t = reg.get(sensorId, m_selectedTransformId);

    if (t) {
      XFORM_LOGD("lookup OK: id='%s' label='%s'\n",
                 t->meta.id.c_str(),
                 t->meta.label.c_str());
    } else {
      XFORM_LOGD("lookup FAIL: sensor='%s' id='%s'\n",
                 sensorId.c_str(),
                 m_selectedTransformId.c_str());
      XFORM_LOGD("NOT FOUND sensor='%s' id='%s' -> will use identity fallback\n",
                 sensorId.c_str(),
                 m_selectedTransformId.c_str());
    }
  } else if (selectedIsIdentity) {
    XFORM_LOGD("selected id is identity -> using built-in no-op transform\n");
  } else {
    XFORM_LOGD("no selected id (empty) -> will use identity fallback\n");
  }

  // 2) Fallback: identity
  bool usedIdentityFallback = false;
  if (!t) {
    usedIdentityFallback = true;
    static IdentityTransform s_identity("identity", "Linear");
    t = &s_identity;
  }

  m_transform = t;

  // 3) Summary
  XFORM_LOGD("attach end sensor='%s' triedSelected=%d usedIdentity=%d result='%s'\n",
             sensorId.c_str(),
             (int)triedSelected,
             (int)usedIdentityFallback,
             (m_transform ? m_transform->meta.id.c_str() : "(null)"));
}


void Sensor::setIncludeRaw(bool b) {
  m_includeRaw = b;
}

void Sensor::setOutputMode(OutputMode m) {
  if (m_mode == m) return;
  m_mode = m;
  onOutputModeChanged();   // allow derived classes to react if needed
}

void Sensor::setOutputUnitsLabel(const char* u) {
  if (!u) u = "";
  size_t n = strlen(u);
  if (n >= sizeof(m_outputUnitsLabel)) n = sizeof(m_outputUnitsLabel) - 1;
  memcpy(m_outputUnitsLabel, u, n);
  m_outputUnitsLabel[n] = '\0';
  onUnitsLabelChanged();   // optional hook
}

bool Sensor::describeColumn(uint8_t idx, SensorColumnDescriptor& out) const {
  if (idx >= columnCount()) return false;

  out = SensorColumnDescriptor{};
  getColumnName(idx, out.csvHeader, sizeof(out.csvHeader));
  copyField_(out.sensorName, sizeof(out.sensorName), name());
  copyField_(out.columnId, sizeof(out.columnId), out.csvHeader);
  copyField_(out.unit, sizeof(out.unit), unitsLabel());
  copyField_(out.source, sizeof(out.source), idx == 0 ? "primary" : "secondary");
  copyField_(out.notes, sizeof(out.notes), "semantic metadata not configured");
  out.outputMode = outputMode();
  out.primary = (idx == 0);
  out.raw = (outputMode() == OutputMode::RAW && idx == 0);
  out.calibrated = (outputMode() != OutputMode::RAW);
  out.transformed = (outputMode() == OutputMode::POLY || outputMode() == OutputMode::LUT);

  if (out.raw) {
    copyField_(out.quantity, sizeof(out.quantity), "raw");
    copyField_(out.unit, sizeof(out.unit), "counts");
    copyField_(out.source, sizeof(out.source), "raw_counts");
    copyField_(out.kind, sizeof(out.kind), "raw");
  }

  if (out.transformed && selectedTransformId().length()) {
    selectedTransformId().toCharArray(out.transformChain, sizeof(out.transformChain));
  }

  if (!out.unit[0]) {
    copyField_(out.unit, sizeof(out.unit), outputModeName_(out.outputMode));
  }

  return true;
}

bool Sensor::describeSensorMetadata(SensorMetadataDescriptor& out) const {
  out = SensorMetadataDescriptor{};
  copyField_(out.sensorId, sizeof(out.sensorId), name());
  copyField_(out.name, sizeof(out.name), name());
  copyField_(out.type, sizeof(out.type), label());
  copyField_(out.rawUnit, sizeof(out.rawUnit), "counts");
  copyField_(out.calibrationOutputUnit, sizeof(out.calibrationOutputUnit), unitsLabel());
  out.hasCalibration = supportsCalibration();
  return true;
}

bool Sensor::readPreviewValue(OutputMode mode, float& value, char* unit, size_t unitCap) {
  if (mode != OutputMode::RAW || !hasRawCounts() || muted()) return false;
  value = static_cast<float>(currentRawCounts());
  copyField_(unit, unitCap, "counts");
  return true;
}
