#pragma once
#include <stdint.h>
#include <stddef.h>
#include "Calibration.h"
#include "ImuOrientation.h"
#include "OutputTransform.h"   // keep lightweight; transform interface only
#include "SensorRuntimeDiagnostics.h"

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

// Explicit BDQ representation for a sensor column. Automatic preserves the
// legacy inference from raw/source metadata so existing sensors remain
// byte-for-byte compatible.
enum class SensorColumnStorageType : uint8_t {
  Automatic = 0,
  UInt16,
  Int16,
  Int32,
  UInt32,
  Float32,
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
  char domain[24] = {0};    // e.g. "wheel", "unsprung", "frame"; empty when unknown
  char mountPoint[32] = {0}; // Optional descriptive physical mounting point
  char quantity[24] = {0};  // e.g. "raw", "disp", "ang_disp"; empty when unknown
  char component[8] = {0};  // Vector component, e.g. "x", "y", or "z"
  char coordinateFrame[24] = {0}; // Basis in which vector components are expressed
  char vectorGroup[32] = {0}; // Sensor-local identifier tying vector components together
  char unit[24] = {0};      // e.g. "counts", "mm", "deg"
  char source[24] = {0};    // e.g. "primary", "raw_counts", "linearized"
  char kind[8] = {0};       // "", "raw", or "qc" for analysis signal registry
  char processingRole[24] = {0};
  char calibrationId[32] = {0};
  char transformChain[64] = {0};
  char notes[64] = {0};
  OutputMode outputMode = OutputMode::RAW;
  SensorColumnStorageType storageType = SensorColumnStorageType::Automatic;
  bool required = true;
  bool primary = false;
  bool raw = false;
  bool diagnostic = false;
  bool calibrated = false;
  bool transformed = false;
  bool semanticSelectionExcluded = false;
  bool allowNaN = false;
};

struct SensorDeviceConfigDescriptor {
  char kind[32] = {0};
  char policy[24] = {0};
  char status[24] = {0};
  char requestedSlowFilter[12] = {0};
  char writeStatus[24] = {0};
  bool readOk = false;

  uint16_t rawAngle = 0;
  uint16_t angle = 0;
  uint16_t zpos = 0;
  uint16_t mpos = 0;
  uint16_t mang = 0;
  uint16_t conf = 0;
  uint8_t statusReg = 0;
  uint8_t agc = 0;
  uint16_t magnitude = 0;

  char confPowerMode[16] = {0};
  char confHysteresis[16] = {0};
  char confOutputStage[20] = {0};
  char confPwmFrequency[16] = {0};
  char confSlowFilter[12] = {0};
  char confFastFilterThreshold[12] = {0};
  bool confWatchdog = false;
};

struct SensorImuConfigDescriptor {
  char contractId[40] = {0};
  char imuId[32] = {0};
  char location[24] = {0}; // Deprecated compatibility alias for domain
  char domain[24] = {0};
  char end[8] = {0};
  char mountPoint[32] = {0};
  char profile[24] = {0};
  char driverRevision[48] = {0};
  char calibrationRef[32] = {0};
  bool orientationValid = false;
  char orientationPlane[3] = {0};
  int8_t orientationNormalSign = 0;
  float orientationMatrix[3][3] {};
  uint32_t orientationSampleCount = 0;
  uint64_t orientationCapturedAtUnixMs = 0;
  float orientationMeanAccelRaw[3] {};
  float orientationAccelMagnitudeMeanG = 0.0f;
  float orientationAccelMagnitudeStdG = 0.0f;
  float orientationGyroStdMaximumDps = 0.0f;
  float orientationMaximumGyroMagnitudeDps = 0.0f;
  float orientationRollDeviationDeg = 0.0f;
  uint8_t busIndex = 0;
  uint8_t address = 0;
  uint32_t i2cClockHz = 0;
  uint8_t chipId = 0;
  uint8_t configFileMajor = 0;
  uint8_t configFileMinor = 0;
  uint16_t loggerRateHz = 0;
  uint16_t imuRateHz = 0;
  uint16_t outputRateHz = 0;
  uint16_t outputDecimationFactor = 1;
  char outputSelection[32] = {0};
  char gyroBiasMode[24] = {0};
  bool gyroHardwareOffsetApplied = false;
  bool iocDiagnosticsEnabled = false;
  uint16_t fifoPollRateHz = 0;
  uint16_t temperatureRateHz = 0;
  uint32_t temperatureFreshnessUs = 0;
  uint16_t fifoConfig = 0;
  uint16_t fifoWatermark = 0;
  uint8_t accelOdr = 0;
  uint8_t accelRange = 0;
  uint8_t accelBandwidth = 0;
  uint8_t accelFilterPerformance = 0;
  uint8_t gyroOdr = 0;
  uint8_t gyroRange = 0;
  uint8_t gyroBandwidth = 0;
  uint8_t gyroNoisePerformance = 0;
  uint8_t gyroFilterPerformance = 0;
  uint16_t startupBiasCaptureSeconds = 0;
  bool initializationOk = false;
  bool effectiveConfigMatched = false;
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
  char direction[32] = {0};
  bool invert = false;
  bool hasCalibration = false;
  bool hasTracking = false;
  uint16_t countsPerTurn = 0;
  uint16_t wrapThresholdCounts = 0;
  bool assumeTurn0AtStart = false;
  bool hasDeviceConfig = false;
  SensorDeviceConfigDescriptor deviceConfig;
  bool hasImuConfig = false;
  SensorImuConfigDescriptor imuConfig;
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
  virtual bool prepareLoggingStart(char*, size_t) { return true; }
  virtual bool validateLoggingStart(
      const LoggerConfig&,
      uint16_t,
      char*,
      size_t) const { return true; }
  virtual bool startLoggingSession(char*, size_t) { onLoggingStart(); return true; }
  virtual size_t pendingLoggingRows() const { return 0; }

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
  virtual bool describeRuntimeDiagnostics(SensorRuntimeDiagnostics& out) const {
    (void)out;
    return false;
  }
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
  virtual bool     calibrationNeedsPositiveMovement(CalMode) const { return false; }

  // ----- Assisted IMU installation orientation -----
  virtual bool supportsImuOrientationCalibration() const { return false; }
  virtual bool captureImuOrientation(
      ImuInstallationPlane,
      int8_t,
      ImuOrientationCalibration&,
      char*,
      size_t) { return false; }
  virtual bool saveImuOrientation(
      const ImuOrientationCalibration&,
      char*,
      size_t) { return false; }

  // Live raw access
  virtual bool    hasRawCounts()   const { return false; }
  virtual int32_t currentRawCounts() const { return 0; }
  virtual bool    readPreviewValue(OutputMode mode, float& value, char* unit, size_t unitCap);
  virtual float   installedRange() const { return 0.0f; }

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
