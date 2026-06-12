#pragma once

#include "Sensor.h"
#include "SensorParams.h"
#include "SensorTypes.h"
#include <limits.h>

class TwoWire;

class AS5600AngleSensor : public Sensor {
public:
  enum class I2CReadMode : uint8_t {
    StopThenRead = 0,
    RepeatedStart = 1,
  };

  struct Params {
    const char* name = nullptr;
    uint8_t busIndex = 0;
    uint8_t i2cAddr = 0x36;
    I2CReadMode readMode = I2CReadMode::RepeatedStart;
    int32_t zeroCount = 0;
    bool includeRawColumn = true;
    bool includeDiagColumns = false;
    uint32_t diagnosticIntervalMs = 250;
    char unitsLabel[48] = "deg";
    char semanticEnd[16] = "";
    char primaryDomain[24] = "";
    char primaryQuantity[24] = "ang_disp";
  };

  explicit AS5600AngleSensor(const Params& p);

  void begin() override;
  void loop() override {}
  void applyConfig(const LoggerConfig&) override {}

  bool muted() const override { return m_muted; }
  void setMuted(bool m) override { m_muted = m; }

  uint8_t columnCount() const override;
  void getColumnName(uint8_t idx, char* out, size_t cap) const override;
  void sampleValues(float* out, uint8_t max) override;
  bool describeColumn(uint8_t idx, SensorColumnDescriptor& out) const override;
  bool describeSensorMetadata(SensorMetadataDescriptor& out) const override;

  const char* label() const override { return "AS5600 Angle"; }
  const char* name() const override { return m_name; }

  OutputConfig outputConfig() const override;
  void setOutputConfig(const OutputConfig& cfg) override;
  OutputMode outputMode() const override { return m_mode; }
  void setOutputMode(OutputMode m) override { m_mode = m; }

  CalMask allowedCalMask() const override { return m_allowedMask; }
  void setAllowedCalMask(CalMask m) override { m_allowedMask = m; }

  bool beginCalibration(CalMode mode) override;
  bool updateCalibration(int32_t latestCounts) override;
  bool finishCalibration(bool persist) override;
  CalPhase currentCalPhase() const override { return cal_.phase; }

  bool supportsCalibration() const override { return true; }
  bool hasRawCounts() const override { return true; }
  int32_t currentRawCounts() const override;

  CalibrationState calibration() const override;
  bool setCalibration(const CalibrationState& s) override;

  void setIncludeRaw(bool b) override;
  void setOutputUnitsLabel(const char* u) override;
  bool reconfigureFromSpec(const SensorSpec& spec) override;

  static const ParamDef* paramDefs(size_t& count);
  static Sensor* create(const char* instanceName, const ParamPack& params, bool mutedDefault);

private:
  struct OutputSample {
    uint8_t agc = 0;
    uint8_t status = 0;
    uint16_t magnitude = 0;
    uint16_t angle = 0;
  };

  struct CalState {
    CalMode mode = CalMode::NONE;
    CalPhase phase = CalPhase::IDLE;
    int32_t first_counts = INT32_MAX;
    uint32_t started_ms = 0;
    uint32_t samples = 0;
  };

  void applyParams(const Params& p);
  bool probe_() const;
  bool readRegBytesLocked_(uint8_t reg, uint8_t* out, uint8_t len) const;
  bool readOutputBlock_(OutputSample& out) const;
  bool readDiagnostics_(OutputSample& out) const;
  bool refreshDiagnostics_(bool force) const;
  void maybeWarnDiagnostics_() const;
  void logFailureProbe_() const;
  bool readRawAngle_(uint16_t& out) const;
  int readRawAngleOnce_() const;
  int32_t calibrationCountsFromRaw_(int raw) const;
  float degreesFromRaw_(int raw) const;
  void sample(float& primaryOut, int& rawOut) const;

  static int32_t normalizeCount_(int32_t count);
  static int32_t signedDeltaCounts_(int32_t raw, int32_t zero);

private:
  CalState cal_;

  char m_name[16] = "as5600";
  char m_unitsLabel[48] = "deg";
  char m_semanticEnd[16] = "";
  char m_primaryDomain[24] = "";
  char m_primaryQuantity[24] = "ang_disp";
  char m_rawDomain[24] = "";

  uint8_t m_busIndex = 0;
  uint8_t m_i2cAddr = 0x36;
  I2CReadMode m_readMode = I2CReadMode::RepeatedStart;
  int32_t m_zeroCount = 0;
  uint32_t m_diagnosticIntervalMs = 250;
  bool m_muted = false;
  CalMask m_allowedMask = CAL_ZERO;
  bool m_includeDiagColumns = false;

  mutable TwoWire* m_wire = nullptr;
  mutable bool m_warnedNoBus = false;
  mutable bool m_warnedRead = false;
  mutable bool m_warnedDiagnostics = false;
  mutable bool m_warnedDiagnosticRead = false;
  mutable bool m_warnedFailureProbe = false;
  mutable uint32_t m_nextReadAttemptMs = 0;
  mutable uint32_t m_nextDiagnosticReadMs = 0;
  mutable bool m_haveLastGoodRaw = false;
  mutable bool m_haveDiagnostics = false;
  mutable int m_lastGoodRaw = 0;
  mutable uint8_t m_lastStatus = 0;
  mutable uint8_t m_lastAgc = 0;
  mutable uint16_t m_lastMagnitude = 0;
  mutable uint32_t m_diagnosticReadFailures = 0;

  mutable bool m_calUnwrapInit = false;
  mutable int32_t m_calLastUnwrapped = 0;
};
