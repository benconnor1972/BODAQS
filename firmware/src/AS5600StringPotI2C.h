#pragma once

#include "AS5600StringPotSensorBase.h"
#include "I2CBusScheduler.h"
#include "SensorTypes.h"

class TwoWire;

class AS5600StringPotI2C : public AS5600StringPotSensorBase, public I2CAsyncClient {
public:
  struct Params : public BaseParams {
    uint8_t  busIndex = 0;
    uint8_t  i2cAddr = 0x36;
    int8_t slowFilterCode = 3; // AS5600 CONF.SF 3 = 2x; -1 leaves it unchanged
    uint16_t asyncRateHz = 0; // 0 = follow logger sample rate
    bool includeAngleColumn = false;
    bool includeDiagColumns = false;
    uint32_t diagnosticIntervalMs = 250;
  };

  explicit AS5600StringPotI2C(const Params& p);

  void begin() override;
  void onLoggingStart() override;
  void onLoggingStop() override;
  void onLoggingFinalized() override;
  SensorSampleMode sampleMode() const override { return SensorSampleMode::Asynchronous; }
  bool reconfigureFromSpec(const SensorSpec& spec) override;
  uint8_t columnCount() const override;
  void getColumnName(uint8_t idx, char* out, size_t cap) const override;
  void sampleValues(float* out, uint8_t max) override;
  bool describeColumn(uint8_t idx, SensorColumnDescriptor& out) const override;
  bool describeSensorMetadata(SensorMetadataDescriptor& out) const override;
  bool describeRuntimeDiagnostics(SensorRuntimeDiagnostics& out) const override;

  const char* asyncClientName() const override { return name(); }
  const char* asyncClientKind() const override { return "as5600_string_pot_i2c"; }
  uint8_t asyncI2CBusIndex() const override { return m_busIndex; }
  uint8_t asyncI2CAddress() const override { return m_i2cAddr; }
  uint16_t asyncTargetRateHz() const override;
  bool asyncMuted() const override { return muted(); }
  bool asyncAcquire() override;
  void asyncSchedulerStarting() override;
  void asyncSchedulerStopped() override;

  static const ParamDef* paramDefs(size_t& count);
  static Sensor* create(const char* instanceName, const ParamPack& params, bool mutedDefault);

protected:
  int readWrappedCountsOnce() const override;

private:
  struct OutputSample {
    uint8_t status = 0;
    uint8_t agc = 0;
    uint16_t magnitude = 0;
  };

  struct AsyncSnapshot {
    bool have = false;
    bool haveAngle = false;
    bool haveDiagnostics = false;
    bool readOk = false;
    bool reused = false;
    int wrapped = 0;
    uint16_t angle = 0;
    uint8_t status = 0;
    uint8_t agc = 0;
    uint16_t magnitude = 0;
    uint32_t readFailures = 0;
    uint32_t diagnosticReadFailures = 0;
    uint32_t seq = 0;
    uint64_t acquiredUs = 0;
  };

  bool probe_() const;
  bool readRegBytesLocked_(uint8_t reg, uint8_t* out, uint8_t len) const;
  bool writeRegBytesLocked_(uint8_t reg, const uint8_t* data, uint8_t len) const;
  bool readReg16_(uint8_t reg, uint16_t& value) const;
  bool readAngleRegister_(uint16_t& value) const;
  bool readDiagnostics_(OutputSample& out) const;
  bool applyVolatileConfig_() const;
  bool maybeApplyVolatileConfig_() const;
  bool readDeviceConfig_() const;
  bool maybeRefreshDeviceConfig_() const;
  bool refreshDiagnostics_(bool force) const;
  void maybeWarnDiagnostics_() const;
  void logFailureProbe_() const;
  void setRuntimeFailure_(SensorRuntimeFailureStage stage,
                          int16_t resultCode = 0,
                          uint8_t expectedBytes = 0,
                          uint8_t receivedBytes = 0) const;
  void resetRuntimeDiagnostics_();
  void resetSessionRuntimeDiagnostics_() const;
  void recordRuntimeEvent_(SensorRuntimeEventType type) const;
  void updateReadTransition_(bool readOk) const;
  bool readWrappedCounts_(int& wrapped) const;
  bool readWrappedCountsDirectOnce_(int& wrapped) const;
  bool acquireAsyncSample_() const;
  void resetAsyncSnapshot_() const;
  void publishAsyncSnapshot_(const AsyncSnapshot& snapshot) const;
  bool copyAsyncSnapshot_(AsyncSnapshot& snapshot) const;

private:
  uint8_t  m_busIndex = 0;
  uint8_t  m_i2cAddr = 0x36;
  int8_t m_slowFilterCode = -1;
  uint16_t m_asyncRateHz = 0;
  uint32_t m_diagnosticIntervalMs = 250;
  bool m_includeAngleColumn = false;
  bool m_includeDiagColumns = false;
  mutable TwoWire* m_wire = nullptr;
  mutable bool m_warnedNoBus = false;
  mutable bool m_warnedRead = false;
  mutable bool m_warnedDiagnostics = false;
  mutable bool m_warnedDiagnosticRead = false;
  mutable bool m_warnedFailureProbe = false;
  mutable int  m_lastGoodWrapped = 0;
  mutable bool m_haveLastGoodWrapped = false;
  mutable bool m_haveDiagnostics = false;
  mutable uint8_t m_lastStatus = 0;
  mutable uint8_t m_lastAgc = 0;
  mutable uint16_t m_lastMagnitude = 0;
  mutable bool m_lastReadOk = false;
  mutable bool m_lastReadReused = false;
  mutable uint32_t m_readFailures = 0;
  mutable uint32_t m_diagnosticReadFailures = 0;
  mutable uint32_t m_nextReadAttemptMs = 0;
  mutable uint32_t m_nextDiagnosticReadMs = 0;
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
  mutable SensorRuntimeFailure m_lastRuntimeFailure;
  mutable SensorRuntimeFailure m_lastRawRuntimeFailure;
  mutable SensorRuntimeDiagnostics m_runtimeDiagnostics;
  mutable uint32_t m_runtimeSessionReadFailureBase = 0;
  mutable uint32_t m_runtimeSessionDiagnosticFailureBase = 0;
  mutable uint32_t m_runtimeReadFailureStreak = 0;
  mutable bool m_runtimeReadFailureActive = false;
  mutable bool m_runtimeConfigFailureActive = false;
  bool m_deferredRecoveryPending = false;
  mutable bool m_asyncLoggingActive = false;
  mutable uint32_t m_asyncNextSeq = 0;
  mutable uint32_t m_asyncLastLoggedSeq = 0;
  mutable AsyncSnapshot m_asyncSnapshot;
#if defined(ESP32)
  mutable portMUX_TYPE m_asyncMux = portMUX_INITIALIZER_UNLOCKED;
#endif
};
