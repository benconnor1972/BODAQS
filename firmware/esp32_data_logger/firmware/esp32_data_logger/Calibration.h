#ifndef CALIBRATION_H
#define CALIBRATION_H

#include <stdint.h>

enum class CalMode : uint8_t { NONE = 0, ZERO = 1, RANGE = 2 };

using CalModeMask = uint8_t;             // generic bitmask, ok to live here
constexpr CalModeMask CAL_NONE  = 0;
constexpr CalModeMask CAL_ZERO  = 1u << 0;
constexpr CalModeMask CAL_RANGE = 1u << 1;

struct Calibration {
  // Persisted, per sensor (dynamic config)
  bool     enabled = false;
  CalMode  mode    = CalMode::NONE;

  // Raw anchors captured via the wizard
  float    r0_raw  = 0.0f;   // low/reference end
  float    r1_raw  = 1.0f;   // high end (must differ from r0)

  // Capture metadata (optional; persisted)
  uint16_t capture_avg_ms = 300;   // how long we average on Mark
  uint16_t capture_n      = 0;     // how many samples were averaged
  uint64_t ts_epoch_ms    = 0;     // when last applied/captured

  // Derived (not required to persist; recompute when config or anchors change)
  float    k_gain   = 1.0f;
  float    k_offset = 0.0f;

  // Recompute k_* from anchors + configured unit range (u0,u1).
  // Returns false if span is degenerate.
  bool recompute(float u0_units, float u1_units) {
    const float dr = (r1_raw - r0_raw);
    if (dr > -1e-9f && dr < 1e-9f) return false;
    k_gain   = (u1_units - u0_units) / dr;
    k_offset = u0_units - k_gain * r0_raw;
    return true;
  }

  // Apply overlay y_cal = k_gain * raw + k_offset
  inline float applyToRaw(float raw) const {
    return (k_gain * raw) + k_offset;
  }
};

#endif // CALIBRATION_H
