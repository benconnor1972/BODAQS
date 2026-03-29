#pragma once
#include <stdint.h>
#include <stddef.h>
#include "Calibration.h"
#include "OutputTransform.h"   // keep lightweight; transform interface only

class TransformRegistry;

using CalMask = CalModeMask;

enum class CalPhase : uint8_t { IDLE=0, ACTIVE=1, COMPLETE=2 };

// -------- Output transform selection (post-smoothing) --------
enum class OutputMode : uint8_t {
  RAW   = 0,   // pass-through (ADC counts etc.)
  LINEAR,
  POLY,
  LUT
};

// -------- Calibration/transform carrier (type-agnostic) --------
struct CalibrationState {
  OutputMode mode = OutputMode::RAW;

  // LINEAR
  float offset = 0.0f;
  float scale  = 1.0f;

  // POLY
  static constexpr uint8_t MAX_POLY_DEG = 4;
  uint8_t polyDegree = 1;
  float   polyCoeff[MAX_POLY_DEG + 1] = {0.0f};

  // LUT (external)
  char     lutPath[32] = {0};
  uint16_t lutCount    = 0;
};

// -------- Output policy --------
struct OutputConfig {
  OutputMode primary    = OutputMode::RAW;
  bool       includeRaw = false;

  constexpr OutputConfig() = default;
  constexpr OutputConfig(OutputMode m, bool include) : primary(m), includeRaw(include) {}
};

// -------- RAW smoothing config (pre-transform) --------
struct SmoothingConfig {
  float emaAlpha    = 1.0f;  // 1.0 => disabled
  float deadband    = 0.0f;
  bool  emaWarmStart = true;
};

struct LoggerConfig;
struct Calibration;

class Sensor {
public:
  virtual ~Sensor() = default;

  // ----- Lifecycle -----
  virtual void begin() = 0;
  virtual void loop() {}
  virtual void applyConfig(const LoggerConfig&) {}
  virtual void onLoggingStart() {}
  virtual void onLoggingStop() {}

  // ----- Runtime muting -----
  virtual bool muted() const = 0;
  virtual void setMuted(bool m) = 0;

  // Include a raw counts column alongside the primary one (runtime)
  virtual void setIncludeRaw(bool b);

  // Units label for the PRIMARY column (used by CSV/header)
  virtual void setOutputUnitsLabel(const char* u);

  // ----- CSV / sampling -----
  virtual uint8_t columnCount() const = 0;
  virtual void getColumnName(uint8_t idx, char* out, size_t cap) const = 0;
  virtual void sampleValues(float* out, uint8_t max) = 0;

  // UI labels
  virtual const char* label() const { return "Sensor"; }
  virtual const char* name()  const { return "Sensor"; }

  // ----- Output policy -----
  virtual OutputConfig outputConfig() const { return OutputConfig{m_mode, m_includeRaw}; }
  virtual void setOutputConfig(const OutputConfig& oc) { setOutputMode(oc.primary); setIncludeRaw(oc.includeRaw); }

  virtual OutputMode outputMode() const { return m_mode; }
  virtual void setOutputMode(OutputMode);  // implemented in .cpp, calls hook

  // ----- Calibration / transform (generic) -----
  virtual CalibrationState calibration() const { return CalibrationState{}; }
  virtual bool setCalibration(const CalibrationState&) { return false; }
  virtual bool supportsCalibration() const { return false; }

  // ----- RAW smoothing (pre-transform) -----
  virtual SmoothingConfig smoothing() const { return SmoothingConfig{}; }
  virtual void setSmoothing(const SmoothingConfig&) {}

  // ----- User calibration overlay (ZERO / RANGE) -----
  virtual bool        userCalibrationEnabled() const { return false; }
  virtual Calibration userCalibration()        const { return Calibration{}; }
  virtual bool        setUserCalibration(const Calibration&) { return false; }

  // Allowed calibration mask (type-supported ∧ config-allowed)
  virtual CalMask allowedCalMask() const { return CAL_NONE; }
  virtual void    setAllowedCalMask(CalMask) {}

  // Calibration session lifecycle
  virtual bool     beginCalibration(CalMode) { return false; }
  virtual bool     updateCalibration(int32_t) { return false; }
  virtual bool     finishCalibration(bool) { return false; }
  virtual CalPhase currentCalPhase() const { return CalPhase::IDLE; }

  // Live raw access
  virtual bool    hasRawCounts()   const { return false; }
  virtual int32_t currentRawCounts() const { return 0; }

  // -------- Output Transform integration --------
  void setSelectedTransformId(const String& id) {
    String s = id;
    s.trim();
    int dot = s.lastIndexOf('.');
    if (dot > 0) s = s.substring(0, dot); // "wheel_mm.lut" -> "wheel_mm"
    m_selectedTransformId = s;
  }

  const String& selectedTransformId() const     { return m_selectedTransformId; }

  // Attach a transform from the registry; safe to call anytime
  void attachTransform(const TransformRegistry& reg);

  // For HUD/CSV headings
  const char* unitsLabel() const { return m_outputUnitsLabel; }

protected:
  // Derived classes call this right before publishing/logging (normalized space ok)
  float applyTransform(float x) const {
    return m_transform ? m_transform->apply(x) : x;
  }

  // Hook points for derived classes
  virtual void onOutputModeChanged() {}
  virtual void onUnitsLabelChanged() {}

  // If a derived class wants to validate transform input units
  virtual const char* inputUnitsForTransform() const { return "raw"; }

protected:
  // Selected shape id (persisted via ConfigManager)
  String m_selectedTransformId{"identity"};
  // Non-owning pointer to current transform (identity if none)
  const OutputTransform* m_transform{nullptr};
  // Units label for PRIMARY column
  char m_outputUnitsLabel[48]{"raw"};
  // Runtime toggles (base storage for convenience)
  OutputMode m_mode{OutputMode::RAW};
  bool       m_includeRaw{false};
};
