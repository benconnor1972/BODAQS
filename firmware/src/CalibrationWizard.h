#ifndef CALIBRATION_WIZARD_H
#define CALIBRATION_WIZARD_H

#include <stdint.h>
#include "Calibration.h"

class Sensor; // forward
//class UI;     // your abstraction (for toasts/text), forward

enum class CalStep : uint8_t {
  IDLE = 0,
  ZERO_READY,           // waiting for mark at zero
  RANGE_CAPTURE_R0,     // waiting for first mark
  RANGE_CAPTURE_R1,     // waiting for second mark
  PREVIEW,              // show preview & confirm
};

struct CalWizardResult {
  bool   applied   = false;
  bool   cancelled = false;
  bool   error     = false;
  const char* message = nullptr;
};

// Stateless helpers for capture (you can implement elsewhere if preferred)
using CaptureFn = float (*)(uint16_t avg_ms, uint16_t* out_n); // returns averaged RAW

class CalibrationWizard {
public:
  // sensorUnitsLabel is for display only (e.g., "mm"); u0/u1 come from config.
  CalibrationWizard(Sensor* sensor,
                    float u0_units,
                    float u1_units,
                    const char* sensorUnitsLabel,
                    CaptureFn captureFn);

  // Entry points
  void startZero();   // ZERO mode (preserve prior span)
  void startRange();  // RANGE mode (capture both ends)
  void cancel();

  // Hook your Mark button short-press here during wizard
  void onMark();

  // Call periodically from your menu tick to refresh previews / timeouts
  void tick();

  // Accessors
  CalStep step() const { return step_; }
  const Calibration& pendingCalibration() const { return pending_; }
  CalWizardResult result() const { return result_; }

  // Optional helpers for UI presentation (live preview values)
  // rawLive is current RAW sensor reading (you provide it)
  float previewUnitsFromRaw(float rawLive) const;

  // After PREVIEW, call apply() if the user selects "Apply".
  void apply();

  // Reset result flags after UI consumption
  void clearResult() { result_ = {}; }

private:
  // Internal helpers
  void computeSpanRefIfNeeded_();  // for ZERO mode span preservation
  void updatePreview_();
  void fail_(const char* msg);
  void toast_(const char* msg);    // delegate to UI if you want

private:
  Sensor* sensor_ = nullptr;
  const char* units_ = nullptr;
  CaptureFn capture_ = nullptr;

  float u0_ = 0.0f;   // from config
  float u1_ = 1.0f;   // from config

  CalStep step_ = CalStep::IDLE;

  Calibration pending_{};  // modified during wizard, applied to sensor on apply()
  float span_ref_ = 1.0f;  // ZERO mode: preserved (r1 - r0)

  CalWizardResult result_{};
};

#endif // CALIBRATION_WIZARD_H
