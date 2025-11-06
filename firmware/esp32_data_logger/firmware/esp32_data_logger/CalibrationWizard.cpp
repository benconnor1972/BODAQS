// CalibrationWizard.cpp
#include "CalibrationWizard.h"
#include "Calibration.h"
#include "CaptureUtils.h"
#include "Sensor.h"
#include <Arduino.h>  // for millis(), delay(0)

static inline bool nearZero(float x) { return fabsf(x) < 1e-6f; }

CalibrationWizard::CalibrationWizard(Sensor* sensor,
                                     float u0_units,
                                     float u1_units,
                                     const char* sensorUnitsLabel,
                                     CaptureFn captureFn)
: sensor_(sensor),
  units_(sensorUnitsLabel ? sensorUnitsLabel : ""),
  capture_(captureFn),
  u0_(u0_units),
  u1_(u1_units) {
  pending_.enabled = false;
  pending_.mode    = CalMode::NONE;
  pending_.r0_raw  = 0.0f;
  pending_.r1_raw  = 1.0f;
  pending_.capture_avg_ms = 300;
  pending_.capture_n = 0;
  pending_.ts_epoch_ms = 0;
  pending_.k_gain = 1.0f;
  pending_.k_offset = 0.0f;
}

void CalibrationWizard::toast_(const char* msg) {
  // Optional hook into your UI layer. Safe no-op here.
  (void)msg;
}

void CalibrationWizard::fail_(const char* msg) {
  result_.error = true;
  result_.message = msg;
  step_ = CalStep::IDLE;
  toast_(msg);
}

void CalibrationWizard::computeSpanRefIfNeeded_() {
  // ZERO mode preserves span from current (if any) user calibration;
  // otherwise fall back to a nominal default span in RAW space.
  float defaultSpan = 1000.0f; // TODO: If you have a sensor-specific default, replace this.
  span_ref_ = defaultSpan;

  // Try to read current overlay (if sensor implements it)
  auto cal = sensor_ ? sensor_->userCalibration() : Calibration{};
  if (cal.enabled && cal.mode != CalMode::NONE) {
    float dr = cal.r1_raw - cal.r0_raw;
    if (!nearZero(dr)) span_ref_ = dr;
  }
}

void CalibrationWizard::startZero() {
  clearResult();
  computeSpanRefIfNeeded_();
  step_ = CalStep::ZERO_READY;
  toast_("Set Zero: Hold position, press Mark to capture");
}

void CalibrationWizard::startRange() {
  clearResult();
  step_ = CalStep::RANGE_CAPTURE_R0;
  toast_("Set Range: Move to first point, press Mark");
}

void CalibrationWizard::cancel() {
  clearResult();
  result_.cancelled = true;
  step_ = CalStep::IDLE;
  toast_("Calibration cancelled");
}

void CalibrationWizard::onMark() {
  if (!capture_) { fail_("No capture function"); return; }

  uint16_t count = 0;
  float r = capture_(pending_.capture_avg_ms, &count);
  if (count == 0) { fail_("No samples captured"); return; }

  switch (step_) {
    case CalStep::ZERO_READY: {
      pending_.mode    = CalMode::ZERO;
      pending_.enabled = true;
      pending_.r0_raw  = r;
      pending_.r1_raw  = r + span_ref_;
      pending_.capture_n = count;
      pending_.ts_epoch_ms = millis(); // monotonic; replace with RTC epoch if available

      if (!pending_.recompute(u0_, u1_)) {
        fail_("Zero: degenerate span");
        return;
      }
      updatePreview_();
      step_ = CalStep::PREVIEW;
      toast_("Zero captured. Apply?");
    } break;

    case CalStep::RANGE_CAPTURE_R0: {
      pending_.mode    = CalMode::RANGE;
      pending_.enabled = true;
      pending_.r0_raw  = r;
      pending_.capture_n = count;
      pending_.ts_epoch_ms = millis();
      step_ = CalStep::RANGE_CAPTURE_R1;
      toast_("Move to second point, press Mark");
    } break;

    case CalStep::RANGE_CAPTURE_R1: {
      pending_.r1_raw  = r;
      pending_.capture_n += count; // total samples across both captures (informational)

      if (!pending_.recompute(u0_, u1_)) {
        // If user did max then min, offer soft recovery by swapping:
        float dr = (pending_.r1_raw - pending_.r0_raw);
        if (nearZero(dr)) { fail_("Range: zero span"); return; }
        // Allow inverted as-is (descending mapping). If you prefer “swap”, do it here.
      }

      updatePreview_();
      step_ = CalStep::PREVIEW;
      toast_("Range captured. Apply?");
    } break;

    default:
      // Ignore marks in other states
      break;
  }
}

void CalibrationWizard::tick() {
  // Keep UI responsive / allow periodic preview refresh if desired
  delay(0);
}

float CalibrationWizard::previewUnitsFromRaw(float rawLive) const {
  if (step_ != CalStep::PREVIEW || !pending_.enabled) {
    // Pre-cal preview: Units using current (pre-wizard) mapping if needed.
    // We return post-cal preview here only in PREVIEW, else 0.
    return 0.0f;
  }
  // y_cal = k_gain*raw + k_offset (normalized against anchors with u0/u1)
  return (pending_.k_gain * rawLive + pending_.k_offset);
}

void CalibrationWizard::updatePreview_() {
  // Nothing to compute here beyond pending_.recompute(u0,u1).
  // UI layer can query previewUnitsFromRaw(rawLive) each frame.
}

void CalibrationWizard::apply() {
  if (step_ != CalStep::PREVIEW || !pending_.enabled) {
    fail_("Nothing to apply");
    return;
  }
  result_.applied = true;
  result_.message = "Calibration applied";
  step_ = CalStep::IDLE;
  toast_("Applied");
}
