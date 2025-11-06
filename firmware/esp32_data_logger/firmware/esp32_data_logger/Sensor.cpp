#include "Sensor.h"
#include "TransformRegistry.h"
#include "OutputTransform.h"
#include <string.h>

void Sensor::attachTransform(const TransformRegistry& reg) {
  const String sensorId = String(name()); // folder key: /cal/<name>/

  // Try the selected transform (may be empty/missing)
  const OutputTransform* t = nullptr;
  if (m_selectedTransformId.length()) {
    t = reg.get(sensorId, m_selectedTransformId);
  }

  // Fallback: identity (0..1 -> 0..1). Keep units_label from config.
  if (!t) {
    static IdentityTransform s_identity("identity", "Linear");
    t = &s_identity;
  }

  m_transform = t;

  //Debug
  //Serial.printf("[XFORM] %s select='%s' -> '%s'\n",
  //              name(),
  //              m_selectedTransformId.c_str(),
  //              (m_transform ? m_transform->meta.id.c_str() : "(null)"));

  // IMPORTANT: do NOT overwrite m_outputUnitsLabel here anymore.
  // Units come from the per-sensor config field `units_label` for non-RAW outputs,
  // and from "counts" implicitly when RAW is selected.
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
