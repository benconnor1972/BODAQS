#pragma once

#include "Sensor.h"
#include "SensorParams.h"
#include "SensorTypes.h"
#include "I2CBusScheduler.h"
#include <limits.h>

class TwoWire;

class AS5600AngleSensor : public Sensor, public I2CAsyncClient {
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
    int8_t directionSign = 1;
    float installedRange = 0.0f;
    int8_t slowFilterCode = -1; // -1 = leave AS5600 CONF.SF unchanged
    uint16_t asyncRateHz = 0; // 0 = follow logger sample rate
    bool includeRawColumn = true;
    bool includeAngleColumn = false;
    bool includeDiagColumns = false;
    uint32_t diagnosticIntervalMs = 250;
    char semanticEnd[16] = "";
    char primaryDomain[24] = "";
    char primaryQuantity[24] = "ang_disp";
  };

  explicit AS5600AngleSensor(const Params& p);

  void begin() override;
  void loop() override {}
  void applyConfig(const LoggerConfig&) override {}
  void onLoggingStart() override;
  void onLoggingStop() override;

  bool muted() const override { return m_muted; }
  void setMuted(bool m) override { m_muted = m; }

  SensorSampleMode sampleMode() const override { return SensorSampleMode::Asynchronous; }
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
  bool calibrationNeedsPositiveMovement(CalMode mode) const override { return mode == CalMode::ZERO; }

  bool supportsCalibration() const override { return true; }
  bool hasRawCounts() const override { return true; }
  int32_t currentRawCounts() const override;
  bool readPreviewValue(OutputMode mode, float& value, char* unit, size_t unitCap) override;
  float installedRange() const override { return m_installedRange; }

  CalibrationState calibration() const override;
  bool setCalibration(const CalibrationState& s) override;

  void setIncludeRaw(bool b) override;
  void setOutputUnitsLabel(const char* u) override;
  bool reconfigureFromSpec(const SensorSpec& spec) override;

  const char* asyncClientName() const override { return name(); }
  const char* asyncClientKind() const override { return "as5600_angle_i2c"; }
  uint8_t asyncI2CBusIndex() const override { return m_busIndex; }
  uint8_t asyncI2CAddress() const override { return m_i2cAddr; }
  uint16_t asyncTargetRateHz() const override;
  bool asyncMuted() const override { return m_muted; }
  bool asyncAcquire() override;

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
    int32_t second_counts = INT32_MIN;
    uint32_t started_ms = 0;
    uint32_t samples = 0;
  };

  struct AsyncSnapshot {
    bool have = false;
    bool haveAngle = false;
    bool haveDiagnostics = false;
    bool readOk = false;
    bool reused = false;
    uint16_t raw = 0;
    uint16_t angle = 0;
    uint8_t status = 0;
    uint8_t agc = 0;
    uint16_t magnitude = 0;
    uint32_t rawReadFailures = 0;
    uint32_t diagnosticReadFailures = 0;
    uint32_t seq = 0;
    uint64_t acquiredUs = 0;
  };

  void applyParams(const Params& p);
  bool probe_() const;
  bool readRegBytesLocked_(uint8_t reg, uint8_t* out, uint8_t len) const;
  bool writeRegBytesLocked_(uint8_t reg, const uint8_t* data, uint8_t len) const;
  bool readOutputBlock_(OutputSample& out) const;
  bool readAngleRegister_(uint16_t& out) const;
  bool readDiagnostics_(OutputSample& out) const;
  bool applyVolatileConfig_() const;
  bool maybeApplyVolatileConfig_() const;
  bool readDeviceConfig_() const;
  bool maybeRefreshDeviceConfig_() const;
  bool refreshDiagnostics_(bool force) const;
  void maybeWarnDiagnostics_() const;
  void logFailureProbe_() const;
  bool readRawAngle_(uint16_t& out) const;
  int readRawAngleOnce_() const;
  int32_t calibrationCountsFromRaw_(int raw) const;
  float degreesFromRaw_(int raw) const;
  float primaryFromRaw_(int raw) const;
  void sample(float& primaryOut, int& rawOut) const;
  bool acquireAsyncSample_() const;
  void resetAsyncSnapshot_() const;
  void publishAsyncSnapshot_(const AsyncSnapshot& snapshot) const;
  bool copyAsyncSnapshot_(AsyncSnapshot& snapshot) const;
  void sampleValuesFromAsync_(float* out, uint8_t max);

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
  int8_t m_directionSign = 1;
  float m_installedRange = 0.0f;
  int8_t m_slowFilterCode = -1;
  uint16_t m_asyncRateHz = 0;
  uint32_t m_diagnosticIntervalMs = 250;
  bool m_muted = false;
  CalMask m_allowedMask = CAL_ZERO;
  bool m_includeAngleColumn = false;
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
  mutable bool m_lastReadOk = false;
  mutable bool m_lastReadReused = false;
  mutable uint32_t m_rawReadFailures = 0;
  mutable uint32_t m_diagnosticReadFailures = 0;
  mutable bool m_configWriteAttempted = false;
  mutable bool m_configWriteOk = false;
  mutable uint32_t m_nextConfigWriteMs = 0;
  mutable bool m_deviceConfigReadAttempted = false;
  mutable bool m_deviceConfigReadOk = false;
  mutable uint32_t m_nextDeviceConfigReadMs = 0;
  mutable uint16_t m_configRawAngle = 0;
  mutable uint16_t m_configAngle = 0;
  mutable uint16_t m_configZpos = 0;
  mutable uint16_t m_configMpos = 0;
  mutable uint16_t m_configMang = 0;
  mutable uint16_t m_configConf = 0;
  mutable uint8_t m_configStatus = 0;
  mutable uint8_t m_configAgc = 0;
  mutable uint16_t m_configMagnitude = 0;

  mutable bool m_calUnwrapInit = false;
  mutable int32_t m_calLastUnwrapped = 0;
  mutable bool m_asyncLoggingActive = false;
  mutable uint32_t m_asyncNextSeq = 0;
  mutable uint32_t m_asyncLastLoggedSeq = 0;
  mutable AsyncSnapshot m_asyncSnapshot;
#if defined(ESP32)
  mutable portMUX_TYPE m_asyncMux = portMUX_INITIALIZER_UNLOCKED;
#endif
};
