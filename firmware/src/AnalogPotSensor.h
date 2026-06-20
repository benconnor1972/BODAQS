#pragma once
#include "Sensor.h"
#include "SensorParams.h"   // ParamDef, ParamType, ParamPack
#include "SensorTypes.h"    // SensorType
#include <stdint.h>
#include <stddef.h>
#include <limits.h>         // for INT32_MAX / INT32_MIN

class AnalogPotSensor : public Sensor {
public:
  // ---------- Construction helpers ----------
  struct Params {
    const char* name = nullptr;

    // Wiring
    int8_t   ain = -1;
    uint8_t  pin = -1;

    // Geometry / anchors (counts)
    int32_t  sensorZeroCount  = 0;
    int32_t  sensorFullCount  = 4095;
    int32_t  installedZeroCount  = 0;

    // Real-world span; if 1.0 => normalized output (0..1)
    float    sensorFullTravelMm = 0.0f;    // 0 => no scaling, 1 => normalized, >1 => mm

    bool     includeRawColumn = false;

    // Optional signal semantics for generated log metadata. These do not affect
    // CSV output; they describe the primary engineered column when present.
    char     semanticEnd[16] = "";
    char     primaryDomain[24] = "";
    char     primaryQuantity[24] = "";
  };

  explicit AnalogPotSensor(const Params& p);
  AnalogPotSensor(const char* name, const Params& p);

  // ---------- Sensor interface ----------
  void begin() override;
  void loop() override {}

  void applyConfig(const LoggerConfig&) override; // currently no-op

  bool muted() const override { return m_muted; }
  void setMuted(bool m) override { m_muted = m; }

  uint8_t columnCount() const override;
  void getColumnName(uint8_t idx, char* out, size_t cap) const override;
  void sampleValues(float* out, uint8_t max) override;
  bool describeColumn(uint8_t idx, SensorColumnDescriptor& out) const override;
  bool describeSensorMetadata(SensorMetadataDescriptor& out) const override;
  int32_t installedZeroCount() const { return installed_zero_count_; }

  const char* name() const { return m_name; }

  // Output policy
  OutputConfig outputConfig() const override;
  void setOutputConfig(const OutputConfig& cfg) override;
  OutputMode   outputMode() const override;
  void         setOutputMode(OutputMode m) override;

  // ===== Sensor-agnostic calibration capability (implements base) =====
  CalMask   allowedCalMask() const override { return m_allowedMask; }
  void      setAllowedCalMask(CalMask m) { m_allowedMask = m; }

  bool      beginCalibration(CalMode mode) override;
  bool      updateCalibration(int32_t latestCounts) override;
  bool      finishCalibration(bool persist) override;
  CalPhase  currentCalPhase() const override { return cal_.phase; }

  bool      hasRawCounts() const override { return true; }
  int32_t   currentRawCounts() const;      // pre-EMA preferred for calibration

  void      applyLinearScalePrecompute();  // recompute slope/intercept for LINEAR

  // Calibration carrier (expose current linear mapping)
  CalibrationState calibration() const override;
  bool setCalibration(const CalibrationState& s) override;
  bool supportsCalibration() const override { return true; }

  // Live UI hooks
  void setIncludeRaw(bool b) override;
  void setOutputUnitsLabel(const char* u) override;
  bool reconfigureFromSpec(const SensorSpec& spec) override;

  // ---------- Schema & factory for registry ----------
  static const ParamDef* paramDefs(size_t& count);
  static Sensor*         create(const char* instanceName, const ParamPack& params, bool mutedDefault);

private:
  void  applyParams(const Params& p);
  int   readOnce() const;
  void  sample(float& selectedOut, int& rawOut);
  float normalize_(int counts) const;   // 0..1 after zero/full + invert + clamp
  float applyTransform_(float xNorm) const; // identity / LUT / POLY (all expect 0..1)


  struct CalState {
    CalMode  mode = CalMode::NONE;
    CalPhase phase = CalPhase::IDLE;
    int32_t  min_counts = INT32_MAX;
    int32_t  max_counts = INT32_MIN;
    uint32_t started_ms = 0;
    uint32_t samples = 0;
  };

  CalState  cal_;

  // Existing calibration parameters (persist via ConfigManager saveSensorParamByName)
  int32_t sensor_zero_count_ = 0;         // counts at mechanical zero
  int32_t sensor_full_count_ = 4095;      // counts at mechanical full
  float   sensor_full_travel_mm_ = 1.0f;  // 1.0 => normalized; >1 => mm
  int32_t installed_zero_count_ = 0;
  double counts_per_mm_ = 0.0;



  // Identity / presentation
  char   m_name[16] = "pot";
  char   m_unitsLabel[48] = "mm";
  char   m_semanticEnd[16] = "";
  char   m_primaryDomain[24] = "";
  char   m_primaryQuantity[24] = "";
  char   m_rawDomain[24] = "";

  // Wiring / behavior
  int8_t   m_ain = -1;
  uint8_t  m_pin = 36;
  bool     m_invert = false;

  // Geometry (legacy, used by existing code paths)
  int32_t  m_zero = 0;
  int32_t  m_full = 4095;
  float    m_fullMm = 0.0f;     // 0 => just counts; 1 => normalized; >1 => mm
  float    m_invSpan = 1.0f;    // cached 1/(full-zero) if non-zero

  // Output
  //OutputMode m_mode = OutputMode::RAW; // RAW or LINEAR
  //bool       m_includeRaw = false;

  // Calibration capability
  CalMask    m_allowedMask = (CalMask)(CAL_ZERO | CAL_RANGE);

  // Other
  bool       m_muted = false;
};
