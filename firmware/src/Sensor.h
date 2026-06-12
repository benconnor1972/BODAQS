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

enum class SensorSampleMode : uint8_t {
  Synchronous = 0,
  Asynchronous = 1,
};

enum class SensorGpsState : uint8_t {
  Error = 0,
  Acquiring,
  Fixed,
};

struct SensorGpsStatus {
  SensorGpsState state = SensorGpsState::Error;
  bool valid = false;
  uint8_t satellites = 0;
  uint8_t fixType = 0;
  uint32_t ageMs = 0;
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

// -------- Runtime description of an emitted CSV column --------
//
// This is deliberately a small fixed-size carrier so firmware can describe the
// exact columns it is already emitting without heap-heavy metadata machinery.
struct SensorColumnDescriptor {
  char csvHeader[96] = {0};
  char columnId[64] = {0};
  char sensorName[16] = {0};
  char end[16] = {0};       // e.g. "front", "rear"; empty when not configured
  char domain[24] = {0};    // e.g. "wheel", "suspension"; empty when unknown
  char quantity[24] = {0};  // e.g. "raw", "disp", "ang_disp"; empty when unknown
  char unit[24] = {0};      // e.g. "counts", "mm", "deg"
  char source[24] = {0};    // e.g. "primary", "raw_counts", "linearized"
  char kind[8] = {0};       // "", "raw", or "qc" for analysis signal registry
  char processingRole[24] = {0};
  char calibrationId[32] = {0};
  char transformChain[64] = {0};
  char notes[64] = {0};
  OutputMode outputMode = OutputMode::RAW;
  bool required = true;
  bool primary = false;
  bool raw = false;
  bool calibrated = false;
  bool transformed = false;
  bool semanticSelectionExcluded = false;
};

struct SensorMetadataDescriptor {
  char sensorId[16] = {0};
  char name[32] = {0};
  char type[32] = {0};
  char domain[24] = {0};
  char rawUnit[16] = {"counts"};
  char calibrationType[24] = {0};
  char calibrationInputUnit[16] = {"counts"};
  char calibrationOutputUnit[24] = {0};
  int32_t installedZeroCount = 0;
  int32_t sensorZeroCount = 0;
  int32_t sensorFullCount = 0;
  float sensorFullTravel = 0.0f;
  bool invert = false;
  bool hasCalibration = false;
  bool hasTracking = false;
  uint16_t countsPerTurn = 0;
  uint16_t wrapThresholdCounts = 0;
  bool assumeTurn0AtStart = false;
};

struct LoggerConfig;
struct Calibration;
struct SensorSpec;

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
  virtual SensorSampleMode sampleMode() const { return SensorSampleMode::Synchronous; }
  virtual uint16_t maxSampleRateHz() const { return 0; } // 0 = no sensor-imposed cap
  virtual uint8_t columnCount() const = 0;
  virtual void getColumnName(uint8_t idx, char* out, size_t cap) const = 0;
  virtual void sampleValues(float* out, uint8_t max) = 0;
  virtual bool describeColumn(uint8_t idx, SensorColumnDescriptor& out) const;
  virtual bool describeSensorMetadata(SensorMetadataDescriptor& out) const;
  virtual bool gpsStatus(SensorGpsStatus& out) const { (void)out; return false; }

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

  // Re-apply a saved sensor spec to the live instance when the concrete type
  // is unchanged.
  virtual bool reconfigureFromSpec(const SensorSpec&) { return false; }

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
