#include "Sensor.h"
#include "TransformRegistry.h"
#include "OutputTransform.h"
#include "DebugLog.h"
#include <string.h>

#define XFORM_LOGD(...) LOGD_TAG("XFORM", __VA_ARGS__)

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
