#pragma once

#include <stddef.h>
#include <stdint.h>

#include "BMI270FifoAcquisition.h"
#include "Sensor.h"
#include "SensorParams.h"

class BMI270ImuSensor final : public Sensor {
public:
  static constexpr uint8_t kBaseColumnCount = 12;
  static constexpr uint8_t kIocDiagnosticColumnCount = 4;
  static constexpr uint8_t kMaximumColumnCount =
      kBaseColumnCount + kIocDiagnosticColumnCount;

  struct Params {
    char name[16] = "frame_imu";
    char imuId[32] = "frame_imu_001";
    char domain[24] = "frame";
    char end[8] = "";
    char mountPoint[32] = "";
    uint8_t busIndex = 1;
    uint8_t address = 0x68;
    char profile[24] = "orientation_200";
    uint16_t startupBiasCaptureSeconds = 5;
    uint16_t outputRateHz = 200;
    BMI270GyroBiasMode gyroBiasMode = BMI270GyroBiasMode::Off;
    bool iocDiagnostics = false;
    char calibrationRef[32] = "";
    ImuOrientationCalibration orientation;
  };

  explicit BMI270ImuSensor(const Params& params);

  void begin() override;
  bool muted() const override { return muted_; }
  void setMuted(bool muted) override { muted_ = muted; }
  SensorSampleMode sampleMode() const override { return SensorSampleMode::Asynchronous; }
  uint8_t columnCount() const override {
    return params_.iocDiagnostics ? kMaximumColumnCount : kBaseColumnCount;
  }
  void getColumnName(uint8_t index, char* out, size_t capacity) const override;
  void sampleValues(float* out, uint8_t maximum) override;
  bool describeColumn(uint8_t index, SensorColumnDescriptor& out) const override;
  bool describeSensorMetadata(SensorMetadataDescriptor& out) const override;
  bool describeRuntimeDiagnostics(SensorRuntimeDiagnostics& out) const override;
  const char* label() const override { return "BMI270 IMU (I2C)"; }
  const char* name() const override { return params_.name; }
  bool reconfigureFromSpec(const SensorSpec& spec) override;

  bool prepareLoggingStart(char* error, size_t errorCapacity) override;
  bool validateLoggingStart(
      const LoggerConfig& config,
      uint16_t effectiveRateHz,
      char* error,
      size_t errorCapacity) const override;
  bool startLoggingSession(char* error, size_t errorCapacity) override;
  void onLoggingStop() override;
  size_t pendingLoggingRows() const override;
  bool supportsImuOrientationCalibration() const override { return true; }
  bool captureImuOrientation(
      ImuInstallationPlane plane,
      int8_t normalSign,
      ImuOrientationCalibration& out,
      char* error,
      size_t errorCapacity) override;
  bool saveImuOrientation(
      const ImuOrientationCalibration& calibration,
      char* error,
      size_t errorCapacity) override;

  static bool validateSpec(const SensorSpec& spec, char* error, size_t errorCapacity);
  static const ParamDef* paramDefs(size_t& count);
  static Sensor* create(const char* instanceName, const ParamPack& params, bool mutedDefault);

private:
  static bool loadParams_(Params& out, const char* instanceName, const ParamPack& params);
  bool ensureInitialized_(char* error, size_t errorCapacity);

  Params params_;
  BMI270FifoAcquisition acquisition_;
  bool muted_ = false;
  bool initialized_ = false;
  uint32_t lastInitializationAttemptUptimeMs_ = 0;
};
