#pragma once

#include <stdint.h>

#include <bmi270.h>

#include "BMI270I2CTransport.h"
#include "BMI270Profile.h"

enum class BMI270DeviceState : uint8_t {
  Uninitialized = 0,
  Initializing,
  Ready,
  Suspended,
  Fault,
};

enum class BMI270DeviceStep : uint8_t {
  None = 0,
  ValidateParameters,
  ProbeChipId,
  DriverInitialize,
  ReadConfigVersion,
  ReadInternalStatus,
  ReadConfiguration,
  WriteConfiguration,
  DisableOffsetCompensation,
  EnableSensors,
  VerifyConfiguration,
  DisableSensors,
  ResumeSensors,
};

struct BMI270DeviceDiagnostics {
  BMI270DeviceState state = BMI270DeviceState::Uninitialized;
  BMI270DeviceStep lastSuccessfulStep = BMI270DeviceStep::None;
  BMI270DeviceStep failureStep = BMI270DeviceStep::None;
  int8_t lastApiResult = BMI2_OK;

  uint32_t beginCalls = 0;
  uint32_t initializationAttempts = 0;
  uint32_t initializationFailures = 0;
  uint32_t recoveryAttempts = 0;
  uint32_t recoverySuccesses = 0;

  bool chipIdRead = false;
  bool chipIdMatched = false;
  uint8_t chipId = 0;
  bool driverInitialized = false;
  bool configurationWriteAttempted = false;
  bool configurationWriteOk = false;
  bool configurationReadAttempted = false;
  bool configurationReadOk = false;
  bool configurationMatched = false;
  bool offsetCompensationDisabled = false;
  bool sensorsEnabled = false;
  bool failureCleanupAttempted = false;
  bool failureCleanupOk = false;

  uint8_t configFileMajor = 0;
  uint8_t configFileMinor = 0;
  uint8_t internalStatus = 0;
};

class BMI270Device {
public:
  BMI270Device(uint8_t busIndex, uint8_t address);
  ~BMI270Device();

  BMI270Device(const BMI270Device&) = delete;
  BMI270Device& operator=(const BMI270Device&) = delete;

  bool begin();
  bool suspend();
  bool resume();
  bool recover();
  void shutdown();

  BMI270DeviceState state() const { return diagnostics_.state; }
  bool ready() const { return diagnostics_.state == BMI270DeviceState::Ready; }
  uint8_t busIndex() const { return transport_.busIndex(); }
  uint8_t address() const { return transport_.address(); }

  const BMI270DeviceDiagnostics& diagnostics() const { return diagnostics_; }
  const BMI270I2CTransportDiagnostics& transportDiagnostics() const {
    return transport_.diagnostics();
  }
  void resetTransportDiagnostics() { transport_.resetDiagnostics(); }
  bool beginBusTransaction(uint8_t registerAddress, uint16_t expectedBytes) {
    return transport_.beginTransaction(registerAddress, expectedBytes);
  }
  void endBusTransaction() { transport_.endTransaction(); }
  const BMI270I2CReadTiming& lastReadTiming() const {
    return transport_.lastReadTiming();
  }
  const BMI270Profile::EffectiveConfig& effectiveConfig() const {
    return effectiveConfig_;
  }

  struct bmi2_dev& nativeDevice() { return device_; }
  const struct bmi2_dev& nativeDevice() const { return device_; }

private:
  bool initializeOnce_();
  bool configureOrientation200_();
  bool disableSensors_(BMI270DeviceStep step);
  bool enableSensors_(BMI270DeviceStep step);
  void quiesceAfterFailedInitialization_();
  bool apiStepOk_(BMI270DeviceStep step, int8_t result);
  void fail_(BMI270DeviceStep step, int8_t result);
  void setState_(BMI270DeviceState state);

  BMI270I2CTransport transport_;
  struct bmi2_dev device_ {};
  BMI270Profile::EffectiveConfig effectiveConfig_;
  BMI270DeviceDiagnostics diagnostics_;
};
