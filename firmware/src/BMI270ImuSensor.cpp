#include "BMI270ImuSensor.h"

#include <Arduino.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "BMI270Profile.h"
#include "BMI270SparseRow.h"
#include "ConfigManager.h"
#include "DebugLog.h"
#include "I2CManager.h"
#include "I2CBusScheduler.h"
#include "RTCManager.h"
#include "SensorRegistry.h"
#include "StorageManager.h"
#include "esp_timer.h"

#define BMI270_SENSOR_LOGI(...) LOGI_TAG("BMI270", __VA_ARGS__)
#define BMI270_SENSOR_LOGW(...) LOGW_TAG("BMI270", __VA_ARGS__)

namespace {

static_assert(BMI270ImuSensor::kBaseColumnCount == BMI270SparseRow::kColumnCount);

const char* const kColumnSuffix[BMI270ImuSensor::kMaximumColumnCount] = {
  "accel_x_raw",
  "accel_y_raw",
  "accel_z_raw",
  "gyro_x_raw",
  "gyro_y_raw",
  "gyro_z_raw",
  "sensor_time_u24",
  "seq_u24",
  "temperature_raw",
  "sample_age_us",
  "status_flags",
  "sample_valid",
  "gyro_ioc_offset_x",
  "gyro_ioc_offset_y",
  "gyro_ioc_offset_z",
  "gyro_ioc_offset_valid",
};

void copyField_(char* destination, size_t capacity, const char* source) {
  if (!destination || capacity == 0) return;
  if (!source) source = "";
  size_t length = strlen(source);
  if (length >= capacity) length = capacity - 1;
  memcpy(destination, source, length);
  destination[length] = '\0';
}

SensorRuntimeFailureStage runtimeFailureStage_(BMI270I2CFailureStage stage) {
  switch (stage) {
    case BMI270I2CFailureStage::None: return SensorRuntimeFailureStage::None;
    case BMI270I2CFailureStage::InvalidArgument:
      return SensorRuntimeFailureStage::InvalidArgument;
    case BMI270I2CFailureStage::BusUnavailable:
      return SensorRuntimeFailureStage::BusUnavailable;
    case BMI270I2CFailureStage::BusLockTimeout:
      return SensorRuntimeFailureStage::BusLock;
    case BMI270I2CFailureStage::RegisterAddress:
      return SensorRuntimeFailureStage::RegisterAddress;
    case BMI270I2CFailureStage::WritePayload:
      return SensorRuntimeFailureStage::WritePayload;
    case BMI270I2CFailureStage::EndTransmission:
      return SensorRuntimeFailureStage::EndTransmission;
    case BMI270I2CFailureStage::RequestBytes:
      return SensorRuntimeFailureStage::RequestBytes;
    case BMI270I2CFailureStage::ReadBytes:
      return SensorRuntimeFailureStage::ReadByte;
    default: return SensorRuntimeFailureStage::None;
  }
}

SensorRuntimeFailure runtimeFailure_(const BMI270I2CFailure& failure) {
  SensorRuntimeFailure out;
  out.stage = runtimeFailureStage_(failure.stage);
  out.resultCode = failure.resultCode;
  out.registerAddress = failure.registerAddress;
  out.expectedBytes = failure.expectedBytes;
  out.receivedBytes = failure.receivedBytes;
  return out;
}

bool fail_(char* error, size_t capacity, const char* format, ...) {
  if (error && capacity) {
    va_list args;
    va_start(args, format);
    vsnprintf(error, capacity, format, args);
    va_end(args);
  }
  return false;
}

bool readString_(const ParamPack& params, const char* key, char* out, size_t capacity) {
  String value;
  if (!params.get(key, value)) return false;
  copyField_(out, capacity, value.c_str());
  return true;
}

bool orientationsEqual_(
    const ImuOrientationCalibration& left,
    const ImuOrientationCalibration& right) {
  if (left.accepted != right.accepted) return false;
  if (!left.accepted) return true;
  if (left.plane != right.plane || left.normalSign != right.normalSign) return false;
  for (uint8_t row = 0; row < 3; ++row) {
    for (uint8_t column = 0; column < 3; ++column) {
      if (fabsf(left.matrix[row][column] - right.matrix[row][column]) > 0.00001f) {
        return false;
      }
    }
  }
  return true;
}

void loadOrientation_(ImuOrientationCalibration& out, const ParamPack& params) {
  out = ImuOrientationCalibration{};
  bool valid = false;
  (void)params.getBool("orient_valid", valid);
  out.accepted = valid;

  String plane;
  if (params.get("orient_plane", plane)) {
    (void)ImuOrientation::parsePlane(plane.c_str(), out.plane);
  }
  long integer = 0;
  if (params.getInt("orient_normal_sign", integer) && (integer == 1 || integer == -1)) {
    out.normalSign = static_cast<int8_t>(integer);
  }
  if (params.getInt("orient_samples", integer) && integer >= 0) {
    out.sampleCount = static_cast<uint32_t>(integer);
  }
  String epoch;
  if (params.get("orient_epoch_ms", epoch)) {
    out.capturedAtUnixMs = strtoull(epoch.c_str(), nullptr, 10);
  }

  static const char* const quaternionKeys[4] = {
      "orient_qw", "orient_qx", "orient_qy", "orient_qz"};
  for (uint8_t i = 0; i < 4; ++i) {
    double value = i == 0 ? 1.0 : 0.0;
    (void)params.getFloat(quaternionKeys[i], value);
    out.quaternionWxyz[i] = static_cast<float>(value);
  }
  static const char* const meanKeys[3] = {
      "orient_mean_ax", "orient_mean_ay", "orient_mean_az"};
  for (uint8_t i = 0; i < 3; ++i) {
    double value = 0.0;
    (void)params.getFloat(meanKeys[i], value);
    out.meanAccelRaw[i] = static_cast<float>(value);
  }
  struct FloatField {
    const char* key;
    float* destination;
  };
  FloatField fields[] = {
      {"orient_accel_mean_g", &out.accelMagnitudeMeanG},
      {"orient_accel_std_g", &out.accelMagnitudeStdG},
      {"orient_gyro_std_dps", &out.gyroStdMaximumDps},
      {"orient_gyro_max_dps", &out.maximumGyroMagnitudeDps},
      {"orient_roll_deg", &out.rollDeviationDeg},
  };
  for (FloatField& field : fields) {
    double value = 0.0;
    (void)params.getFloat(field.key, value);
    *field.destination = static_cast<float>(value);
  }

  if (out.accepted &&
      !ImuOrientation::quaternionToMatrix(out.quaternionWxyz, out.matrix)) {
    out.accepted = false;
  }
}

void canonicalizeToken_(char* value, size_t capacity) {
  if (!value || capacity == 0) return;
  String canonical(value);
  canonical.trim();
  canonical.toLowerCase();
  canonical.toCharArray(value, capacity);
}

bool validMountSemantics_(const BMI270ImuSensor::Params& params) {
  const bool front = strcmp(params.end, "front") == 0;
  const bool rear = strcmp(params.end, "rear") == 0;
  if (strcmp(params.domain, "unsprung") == 0) return front || rear;
  if (strcmp(params.domain, "steering") == 0) return front;
  if (strcmp(params.domain, "frame") == 0) return !params.end[0] || front || rear;
  return false;
}

bool parseGyroBiasMode_(const char* value, BMI270GyroBiasMode& out) {
  if (!value || !*value || strcmp(value, "off") == 0) {
    out = BMI270GyroBiasMode::Off;
    return true;
  }
  if (strcmp(value, "ioc") == 0) {
    out = BMI270GyroBiasMode::InUseOffsetCorrection;
    return true;
  }
  return false;
}

const char* gyroBiasModeName_(BMI270GyroBiasMode mode) {
  return mode == BMI270GyroBiasMode::InUseOffsetCorrection ? "bmi270_ioc" : "disabled";
}

const char* quantityFor_(uint8_t index) {
  if (index <= 2) return "linear_acceleration_raw";
  if (index <= 5) return "angular_velocity_raw";
  switch (index) {
    case 6: return "sensor_time";
    case 7: return "sample_sequence";
    case 8: return "temperature_raw";
    case 9: return "sample_age";
    case 10: return "status";
    case 11: return "sample_valid";
    case 12:
    case 13:
    case 14: return "gyro_offset_register";
    case 15: return "gyro_offset_valid";
    default: return "";
  }
}

const char* unitFor_(uint8_t index) {
  if (index <= 5 || index == 7 || index == 8) return "count";
  if (index == 6) return "tick";
  if (index == 9) return "us";
  if (index == 10) return "bitfield";
  if (index == 11) return "boolean";
  if (index >= 12 && index <= 14) return "register_step";
  if (index == 15) return "boolean";
  return "";
}

const char* sourceFor_(uint8_t index) {
  if (index <= 5 || index == 11) return "async_fifo_once";
  if (index == 6) return "bmi270_sensor_time";
  if (index == 7) return "firmware_sequence";
  if (index == 8) return "bmi270_temperature";
  if (index == 9) return "native_to_row_timing";
  if (index == 10) return "imu_status";
  if (index >= 12 && index <= 15) return "bmi270_ioc";
  return "";
}

SensorColumnStorageType storageFor_(uint8_t index) {
  if (index <= 5 || index == 8) return SensorColumnStorageType::Int16;
  if (index == 6 || index == 7) return SensorColumnStorageType::UInt32;
  if (index == 9) return SensorColumnStorageType::Float32;
  if (index >= 12 && index <= 14) return SensorColumnStorageType::Int16;
  return SensorColumnStorageType::UInt16;
}

} // namespace

BMI270ImuSensor::BMI270ImuSensor(const Params& params)
    : params_(params),
      acquisition_(params.busIndex, params.address, params.name) {
  (void)acquisition_.setOutputRateHz(params_.maximumOutputRateHz);
  (void)acquisition_.setGyroBiasMode(params_.gyroBiasMode);
  acquisition_.setIocDiagnosticsEnabled(params_.iocDiagnostics);
}

void BMI270ImuSensor::begin() {
  (void)ensureInitialized_(nullptr, 0);
}

bool BMI270ImuSensor::reconfigureFromSpec(const SensorSpec& spec) {
  if (spec.type != SensorType::BMI270ImuI2C || acquisition_.sessionActive() ||
      !validateSpec(spec, nullptr, 0)) {
    return false;
  }

  Params updated;
  loadParams_(updated, spec.name, spec.params);

  // The acquisition object owns its physical I2C endpoint and the logger's
  // column layout is fixed when a session starts.  Those changes still need a
  // reboot; output selection and IOC mode do not.
  if (updated.busIndex != params_.busIndex ||
      updated.address != params_.address ||
      strcmp(updated.profile, params_.profile) != 0 ||
      updated.iocDiagnostics != params_.iocDiagnostics) {
    return false;
  }

  const bool reinitialize = updated.gyroBiasMode != params_.gyroBiasMode;
  if (!reinitialize) {
    params_ = updated;
    return true;
  }

  acquisition_.shutdown();
  initialized_ = false;
  if (!acquisition_.setGyroBiasMode(updated.gyroBiasMode)) {
    return false;
  }
  acquisition_.setIocDiagnosticsEnabled(updated.iocDiagnostics);
  params_ = updated;
  const bool initialized = ensureInitialized_(nullptr, 0);
  if (initialized) {
    BMI270_SENSOR_LOGI(
        "reconfigured sensor=%s max_output_rate_hz=%u gyro_bias_mode=%s\n",
        params_.name,
        (unsigned)params_.maximumOutputRateHz,
        gyroBiasModeName_(params_.gyroBiasMode));
  }
  return initialized;
}

bool BMI270ImuSensor::ensureInitialized_(char* error, size_t errorCapacity) {
  if (initialized_) return true;
  lastInitializationAttemptUptimeMs_ = millis();
  initialized_ = acquisition_.begin();
  if (initialized_) {
    BMI270_SENSOR_LOGI(
        "initialization ready sensor=%s bus=%u address=0x%02X\n",
        params_.name,
        (unsigned)params_.busIndex,
        (unsigned)params_.address);
    return true;
  }

  const BMI270DeviceDiagnostics& diagnostics = acquisition_.device().diagnostics();
  BMI270_SENSOR_LOGW(
      "initialization failed sensor=%s bus=%u address=0x%02X state=%u step=%u api=%d chip_read=%u chip=0x%02X attempts=%lu failures=%lu\n",
      params_.name,
      (unsigned)params_.busIndex,
      (unsigned)params_.address,
      (unsigned)diagnostics.state,
      (unsigned)diagnostics.failureStep,
      (int)diagnostics.lastApiResult,
      diagnostics.chipIdRead ? 1u : 0u,
      (unsigned)diagnostics.chipId,
      (unsigned long)diagnostics.initializationAttempts,
      (unsigned long)diagnostics.initializationFailures);
  return fail_(
      error,
      errorCapacity,
      "%s init failed step=%u api=%d chip=0x%02X",
      params_.name,
      (unsigned)diagnostics.failureStep,
      (int)diagnostics.lastApiResult,
      (unsigned)diagnostics.chipId);
}

void BMI270ImuSensor::getColumnName(uint8_t index, char* out, size_t capacity) const {
  if (!out || capacity == 0) return;
  out[0] = '\0';
  if (index >= columnCount()) return;
  snprintf(out, capacity, "%s_%s", params_.name, kColumnSuffix[index]);
}

void BMI270ImuSensor::sampleValues(float* out, uint8_t maximum) {
  if (!out || maximum == 0) return;

  float values[kMaximumColumnCount] {};
  float baseValues[BMI270SparseRow::kColumnCount];
  BMI270ImuSample sample;
  const bool haveSample = acquisition_.pop(sample);
  uint32_t ageUs = 0;
  bool ageValid = false;
  BMI270SparseRow::encode(
      haveSample ? &sample : nullptr,
      static_cast<uint64_t>(esp_timer_get_time()),
      baseValues,
      ageUs,
      ageValid);
  memcpy(values, baseValues, sizeof(baseValues));

  if (params_.iocDiagnostics) {
    BMI270IocOffsetSnapshot snapshot;
    if (acquisition_.popIocOffsetSnapshot(snapshot)) {
      values[12] = static_cast<float>(snapshot.x);
      values[13] = static_cast<float>(snapshot.y);
      values[14] = static_cast<float>(snapshot.z);
      values[15] = 1.0f;
    }
  }

  const uint8_t configuredCount = columnCount();
  const uint8_t count = maximum < configuredCount ? maximum : configuredCount;
  memcpy(out, values, count * sizeof(float));
  I2CBusScheduler::recordRowUse(&acquisition_, ageUs, ageValid, haveSample);
  if (haveSample) acquisition_.recordRowEmission(ageUs, ageValid);
}

bool BMI270ImuSensor::describeColumn(uint8_t index, SensorColumnDescriptor& out) const {
  if (index >= columnCount()) return false;
  out = SensorColumnDescriptor{};
  getColumnName(index, out.csvHeader, sizeof(out.csvHeader));
  copyField_(out.columnId, sizeof(out.columnId), out.csvHeader);
  copyField_(out.sensorName, sizeof(out.sensorName), params_.name);
  copyField_(out.end, sizeof(out.end), params_.end);
  copyField_(out.domain, sizeof(out.domain), params_.domain);
  copyField_(out.mountPoint, sizeof(out.mountPoint), params_.mountPoint);
  copyField_(out.quantity, sizeof(out.quantity), quantityFor_(index));
  const bool gyroHardwareCompensated =
      index >= 3 && index <= 5 &&
      params_.gyroBiasMode == BMI270GyroBiasMode::InUseOffsetCorrection;
  if (index <= 5 || (index >= 12 && index <= 14)) {
    static const char* const components[] = {"x", "y", "z"};
    copyField_(out.component, sizeof(out.component), components[index % 3]);
    if (index <= 5) {
      copyField_(out.coordinateFrame, sizeof(out.coordinateFrame), "sensor_native");
      copyField_(out.vectorGroup, sizeof(out.vectorGroup), index <= 2 ? "accel_raw" : "gyro_raw");
    } else {
      copyField_(out.vectorGroup, sizeof(out.vectorGroup), "gyro_ioc_offset");
    }
  }
  copyField_(out.unit, sizeof(out.unit), unitFor_(index));
  copyField_(out.source, sizeof(out.source),
             gyroHardwareCompensated ? "bmi270_ioc_output" : sourceFor_(index));
  copyField_(out.processingRole, sizeof(out.processingRole),
             gyroHardwareCompensated ? "hardware_compensated" :
             (index <= 5 ? "raw_evidence" : "qc_metric"));
  out.storageType = storageFor_(index);
  out.raw = (index <= 5 && !gyroHardwareCompensated) || index == 8;
  out.primary = index <= 5;
  out.diagnostic = index >= 6;
  out.semanticSelectionExcluded = out.diagnostic;
  out.allowNaN = index == 9;
  if (out.raw) copyField_(out.kind, sizeof(out.kind), "raw");
  else if (out.diagnostic) copyField_(out.kind, sizeof(out.kind), "qc");
  copyField_(out.notes, sizeof(out.notes),
             index == 11 ? "1 only when this row contains a new native sample" :
             index == 15 ? "1 only when IOC offset-register values are present" :
             index >= 12 ? "Interpret only when gyro_ioc_offset_valid is 1" :
             gyroHardwareCompensated ? "BMI270 IOC hardware offset applied" :
             "Interpret only when the sensor sample_valid field is 1");
  return true;
}

bool BMI270ImuSensor::describeSensorMetadata(SensorMetadataDescriptor& out) const {
  out = SensorMetadataDescriptor{};
  copyField_(out.sensorId, sizeof(out.sensorId), params_.name);
  copyField_(out.name, sizeof(out.name), params_.name);
  copyField_(out.type, sizeof(out.type), "bmi270_imu_i2c");
  copyField_(out.domain, sizeof(out.domain), params_.domain);
  copyField_(out.rawUnit, sizeof(out.rawUnit), "counts");
  out.hasImuConfig = true;

  SensorImuConfigDescriptor& imu = out.imuConfig;
  copyField_(imu.contractId, sizeof(imu.contractId), BMI270Profile::kContractId);
  copyField_(imu.imuId, sizeof(imu.imuId), params_.imuId);
  copyField_(imu.location, sizeof(imu.location), params_.domain);
  copyField_(imu.domain, sizeof(imu.domain), params_.domain);
  copyField_(imu.end, sizeof(imu.end), params_.end);
  copyField_(imu.mountPoint, sizeof(imu.mountPoint), params_.mountPoint);
  copyField_(imu.profile, sizeof(imu.profile), params_.profile);
  copyField_(imu.driverRevision, sizeof(imu.driverRevision), BMI270Profile::kDriverRevision);
  copyField_(imu.calibrationRef, sizeof(imu.calibrationRef), params_.calibrationRef);
  imu.orientationValid = params_.orientation.accepted;
  copyField_(imu.orientationPlane, sizeof(imu.orientationPlane),
             ImuOrientation::planeKey(params_.orientation.plane));
  imu.orientationNormalSign = params_.orientation.normalSign;
  imu.orientationSampleCount = params_.orientation.sampleCount;
  imu.orientationCapturedAtUnixMs = params_.orientation.capturedAtUnixMs;
  imu.orientationAccelMagnitudeMeanG = params_.orientation.accelMagnitudeMeanG;
  imu.orientationAccelMagnitudeStdG = params_.orientation.accelMagnitudeStdG;
  imu.orientationGyroStdMaximumDps = params_.orientation.gyroStdMaximumDps;
  imu.orientationMaximumGyroMagnitudeDps = params_.orientation.maximumGyroMagnitudeDps;
  imu.orientationRollDeviationDeg = params_.orientation.rollDeviationDeg;
  for (uint8_t axis = 0; axis < 3; ++axis) {
    imu.orientationMeanAccelRaw[axis] = params_.orientation.meanAccelRaw[axis];
    for (uint8_t component = 0; component < 3; ++component) {
      imu.orientationMatrix[axis][component] = params_.orientation.matrix[axis][component];
    }
  }
  imu.busIndex = params_.busIndex;
  imu.address = params_.address;
  const board::I2CProfile* busProfile = I2CManager::profile(params_.busIndex);
  imu.i2cClockHz = busProfile ? busProfile->hz : 0;
  imu.loggerRateHz = StorageManager_getSampleRateHz();
  imu.imuRateHz = BMI270Profile::kOdrHz;
  imu.maximumOutputRateHz = params_.maximumOutputRateHz;
  imu.outputRateHz = acquisition_.outputRateHz();
  imu.outputDecimationFactor = acquisition_.outputDecimationFactor();
  copyField_(imu.outputSelection, sizeof(imu.outputSelection),
             acquisition_.outputRateHz() == BMI270Profile::kOdrHz
                 ? "all_native_samples"
                 : "every_nth_native_sample");
  copyField_(imu.gyroBiasMode, sizeof(imu.gyroBiasMode),
             gyroBiasModeName_(params_.gyroBiasMode));
  imu.gyroHardwareOffsetApplied =
      params_.gyroBiasMode == BMI270GyroBiasMode::InUseOffsetCorrection;
  imu.iocDiagnosticsEnabled = params_.iocDiagnostics;
  imu.fifoPollRateHz = BMI270FifoAcquisition::kTargetRateHz;
  imu.temperatureRateHz = BMI270FifoAcquisition::kTemperatureRateHz;
  imu.temperatureFreshnessUs = BMI270FifoAcquisition::kTemperatureFreshnessUs;
  imu.startupBiasCaptureSeconds = params_.startupBiasCaptureSeconds;

  const BMI270DeviceDiagnostics& device = acquisition_.device().diagnostics();
  const BMI270FifoDiagnostics& fifo = acquisition_.diagnostics();
  const BMI270Profile::EffectiveConfig& effective = acquisition_.device().effectiveConfig();
  imu.initializationOk = initialized_;
  imu.chipId = device.chipId;
  imu.configFileMajor = device.configFileMajor;
  imu.configFileMinor = device.configFileMinor;
  imu.effectiveConfigMatched = device.configurationMatched;
  imu.accelOdr = effective.accelOdr;
  imu.accelRange = effective.accelRange;
  imu.accelBandwidth = effective.accelBandwidth;
  imu.accelFilterPerformance = effective.accelFilterPerformance;
  imu.gyroOdr = effective.gyroOdr;
  imu.gyroRange = effective.gyroRange;
  imu.gyroBandwidth = effective.gyroBandwidth;
  imu.gyroNoisePerformance = effective.gyroNoisePerformance;
  imu.gyroFilterPerformance = effective.gyroFilterPerformance;
  imu.fifoConfig = fifo.effectiveFifoConfig;
  imu.fifoWatermark = fifo.effectiveFifoWatermark;
  return true;
}

bool BMI270ImuSensor::describeRuntimeDiagnostics(SensorRuntimeDiagnostics& out) const {
  if (acquisition_.sessionActive()) return false;
  out = SensorRuntimeDiagnostics{};
  out.present = true;
  copyField_(out.sensorName, sizeof(out.sensorName), params_.name);
  copyField_(out.kind, sizeof(out.kind), "bmi270_imu_i2c");
  out.busIndex = params_.busIndex;
  out.address = params_.address;

  const BMI270DeviceDiagnostics& device = acquisition_.device().diagnostics();
  const BMI270I2CTransportDiagnostics& transport =
      acquisition_.device().transportDiagnostics();
  const BMI270FifoDiagnostics& fifo = acquisition_.diagnostics();
  out.beginCount = device.beginCalls;
  out.lastBeginUptimeMs = lastInitializationAttemptUptimeMs_;
  out.initialProbeOk = device.chipIdRead && device.chipIdMatched;
  out.configWriteAttempted = device.configurationWriteAttempted;
  out.configWriteOk = device.configurationWriteOk;
  out.configReadAttempted = device.configurationReadAttempted;
  out.configReadOk = device.configurationReadOk && device.configurationMatched;
  out.imuDeviceState = static_cast<uint8_t>(device.state);
  out.imuInitializationFailureStep = static_cast<uint8_t>(device.failureStep);
  out.imuInitializationApiResult = device.lastApiResult;
  out.imuInitializationChipId = device.chipId;
  out.imuInitializationAttempts = device.initializationAttempts;
  out.imuInitializationFailures = device.initializationFailures;
  out.imuInitializationChipIdRead = device.chipIdRead;
  out.imuInitializationChipIdMatched = device.chipIdMatched;
  out.imuInitializationCleanupAttempted = device.failureCleanupAttempted;
  out.imuInitializationCleanupOk = device.failureCleanupOk;
  out.rawReadFailures = static_cast<uint32_t>(fifo.drainFailures > UINT32_MAX ? UINT32_MAX : fifo.drainFailures);
  out.readFailureStreakMax = fifo.maximumDrainFailureStreak;
  out.readRecoveries = static_cast<uint32_t>(fifo.recoverySuccesses > UINT32_MAX ? UINT32_MAX : fifo.recoverySuccesses);
  out.lastReadOk = transport.lastOperationOk;
  out.initializationFailure = runtimeFailure_(transport.lastFailure);
  out.lastFailure = runtimeFailure_(transport.lastFailure);

  out.hasImuSession = true;
  out.imuDrainCalls = fifo.drainCalls;
  out.imuDrainPasses = fifo.drainPasses;
  out.imuEmptyPasses = fifo.emptyPasses;
  out.imuDrainPassLimitHits = fifo.drainPassLimitHits;
  out.imuFifoBytesRead = fifo.fifoBytesRead;
  out.imuFifoFramesParsed = fifo.fifoFramesParsed;
  out.imuSensorTimeFrames = fifo.sensorTimeFrames;
  out.imuMissingSensorTimeBatches = fifo.missingSensorTimeBatches;
  out.imuSkipControlFrames = fifo.skipControlFrames;
  out.imuFifoOverflowEvents = fifo.fifoOverflowEvents;
  out.imuFifoFullObservations = fifo.fifoFullObservations;
  out.imuHardwareSkippedFrames = fifo.hardwareSkippedFrames;
  out.imuUnpairedFrames = fifo.unpairedFrames;
  out.imuInputConfigFrames = fifo.inputConfigFrames;
  out.imuInvalidHeaders = fifo.invalidHeaders;
  out.imuPartialFrames = fifo.partialFrames;
  out.imuOverreadFrames = fifo.overreadFrames;
  out.imuParserOutputDrops = fifo.parserOutputDrops;
  out.imuSamplesEnqueued = fifo.samplesEnqueued;
  out.imuSamplesEmitted = fifo.samplesDequeued;
  out.imuSamplesIntentionallyDecimated = fifo.samplesIntentionallyDecimated;
  out.imuQueueDrops = fifo.queueDrops;
  out.imuPreSessionQueueDiscards = fifo.preSessionQueueDiscards;
  out.imuExplicitQueueDiscards = fifo.explicitQueueDiscards;
  out.imuTemperatureReads = fifo.temperatureReads;
  out.imuTemperatureReadFailures = fifo.temperatureReadFailures;
  out.imuIocOffsetReadAttempts = fifo.iocOffsetReadAttempts;
  out.imuIocOffsetReadFailures = fifo.iocOffsetReadFailures;
  out.imuIocOffsetSnapshotDrops = fifo.iocOffsetSnapshotDrops;
  out.imuOperationalValidationAttempts = fifo.operationalValidationAttempts;
  out.imuOperationalValidationFailures = fifo.operationalValidationFailures;
  out.imuSessionStartValidationAttempts = fifo.sessionStartValidationAttempts;
  out.imuSessionStartValidationFailures = fifo.sessionStartValidationFailures;
  out.imuNoProgressEvents = fifo.noProgressEvents;
  out.imuFifoFlushes = fifo.fifoFlushes;
  out.imuFifoFlushFailures = fifo.fifoFlushFailures;
  out.imuStopDrainAttempts = fifo.stopDrainAttempts;
  out.imuStopDrainFailures = fifo.stopDrainFailures;
  out.imuI2cOperations = transport.operations;
  out.imuI2cFailures = transport.failures;
  out.imuI2cRecoveries = transport.recoveries;
  out.imuI2cBusLockAttempts = transport.busLockAttempts;
  out.imuI2cBusLockTimeouts = transport.busLockTimeouts;
  out.imuI2cBusLockWaitTotalUs = transport.busLockWaitTotalUs;
  for (size_t i = 0; i < BMI270I2CTransportDiagnostics::kFailureStageCount; ++i) {
    out.imuI2cFailureStageCounts[i] = transport.failuresByStage[i];
  }
  out.imuRecoveryAttempts = fifo.recoveryAttempts;
  out.imuRecoverySuccesses = fifo.recoverySuccesses;
  out.imuRecoveryFailures = fifo.recoveryFailures;
  out.imuTerminalFaultEvents = fifo.terminalFaultEvents;
  for (uint8_t axis = 0; axis < 3; ++axis) {
    out.imuAccelNearRail[axis] = fifo.accelNearRail[axis];
    out.imuGyroNearRail[axis] = fifo.gyroNearRail[axis];
  }
  out.imuTimingDegradedSamples = fifo.timingDegradedSamples;
  out.imuSequenceDiscontinuityEvents = fifo.sequenceDiscontinuityEvents;
  out.imuNativeTimeDiscontinuityEvents = fifo.nativeTimeDiscontinuityEvents;
  out.imuQueueCapacity = fifo.queueCapacity;
  out.imuQueueHighWater = fifo.queueHighWater;
  out.imuFinalQueueDepth = static_cast<uint16_t>(acquisition_.queuedSamples());
  out.imuMaximumFifoBytesObserved = fifo.maximumFifoBytesObserved;
  out.imuMaximumDrainDurationUs = fifo.maximumDrainDurationUs;
  out.imuMaximumDrainFailureStreak = fifo.maximumDrainFailureStreak;
  out.imuNoProgressTimeoutUs = BMI270FifoAcquisition::kNoSampleProgressTimeoutUs;
  out.imuMaximumNoProgressUs = fifo.maximumNoProgressUs;
  out.imuLastValidationIssues = fifo.lastValidationIssues;
  out.imuI2cMaximumFailureStreak = transport.maximumFailureStreak;
  out.imuI2cBusLockWaitMaximumUs = transport.busLockWaitMaximumUs;
  const BMI270AgeSummary age = acquisition_.ageSummary();
  out.imuAgeSamples = age.count;
  out.imuAgeUnavailable = age.unavailable;
  out.imuAgeClipped = age.clipped;
  out.imuAgeMinimumUs = age.minimumUs;
  out.imuAgeMedianUs = age.medianUs;
  out.imuAgeP95Us = age.p95Us;
  out.imuAgeP99Us = age.p99Us;
  out.imuAgeMaximumUs = age.maximumUs;
  out.imuAgeResolutionUs = age.resolutionUs;
  const BMI270RunningStats& temperature = acquisition_.temperatureStats();
  out.imuTemperatureSamples = temperature.count();
  out.imuTemperatureMinimumC = static_cast<float>(temperature.minimum());
  out.imuTemperatureMaximumC = static_cast<float>(temperature.maximum());
  out.imuLastValidationFifoConfig = fifo.lastValidationFifoConfig;
  out.imuLastValidationFifoWatermark = fifo.lastValidationFifoWatermark;
  out.imuLastValidationChipId = fifo.lastValidationChipId;
  out.imuLastValidationInternalStatus = fifo.lastValidationInternalStatus;
  out.imuLastValidationPowerControl = fifo.lastValidationPowerControl;
  out.imuLastValidationAccelDownsample = fifo.lastValidationAccelDownsample;
  out.imuLastValidationGyroDownsample = fifo.lastValidationGyroDownsample;
  out.imuLastValidationAccelFiltered = fifo.lastValidationAccelFiltered;
  out.imuLastValidationGyroFiltered = fifo.lastValidationGyroFiltered;
  out.imuConsecutiveRecoveryFailures = fifo.consecutiveRecoveryFailures;
  out.imuRecoveryAttemptsWithoutProgress = fifo.recoveryAttemptsWithoutProgress;
  out.imuLastRecoveryReason = static_cast<uint8_t>(fifo.lastRecoveryReason);
  out.imuLastValidationApiResult = fifo.lastValidationApiResult;
  const BMI270StartupObservationResult& startup = acquisition_.startupObservation();
  out.imuStartupObservationState = static_cast<uint8_t>(startup.state);
  out.imuStartupRejectionMask = startup.rejectionMask;
  out.imuStartupConfiguredSeconds = startup.configuredSeconds;
  out.imuStartupNativeSampleRateHz = startup.nativeSampleRateHz;
  out.imuStartupMinimumValidFraction = startup.minimumValidFraction;
  out.imuStartupTargetSampleSlots = startup.targetSampleSlots;
  out.imuStartupMinimumValidSamples = startup.minimumValidSamples;
  out.imuStartupValidSamples = startup.validSamples;
  out.imuStartupSettlingSampleSlots = startup.settlingSampleSlots;
  out.imuStartupMeasurementStartSequence = startup.measurementStartSequence;
  out.imuStartupSettlingStatusMask = startup.settlingStatusMask;
  out.imuStartupTemperatureSamples = startup.temperatureSamples;
  for (uint8_t axis = 0; axis < 3; ++axis) {
    out.imuStartupGyroMeanRaw[axis] = static_cast<float>(startup.gyroMeanRaw[axis]);
    out.imuStartupGyroStdRaw[axis] = static_cast<float>(startup.gyroStdRaw[axis]);
  }
  out.imuStartupAccelMagnitudeMeanG = static_cast<float>(startup.accelMagnitudeMeanG);
  out.imuStartupAccelMagnitudeStdG = static_cast<float>(startup.accelMagnitudeStdG);
  out.imuStartupMaximumGyroMagnitudeDps =
      static_cast<float>(startup.maximumGyroMagnitudeDps);
  out.imuStartupTemperatureMeanC = static_cast<float>(startup.temperatureMeanC);
  out.imuStartupTemperatureMinimumC = static_cast<float>(startup.temperatureMinimumC);
  out.imuStartupTemperatureMaximumC = static_cast<float>(startup.temperatureMaximumC);
  out.imuTerminalFault = fifo.terminalFault;
  out.imuCounterSaturated = fifo.counterSaturated;
  return true;
}

bool BMI270ImuSensor::validateLoggingStart(
    const LoggerConfig& config,
    uint16_t effectiveRateHz,
    char* error,
    size_t errorCapacity) const {
  if (muted_) return true;
  const int8_t specIndex = config.findSensorByName(params_.name);
  SensorSpec spec;
  Params configured;
  if (specIndex < 0 || !config.getSensorSpec(static_cast<uint8_t>(specIndex), spec) ||
      spec.type != SensorType::BMI270ImuI2C) {
    return fail_(error, errorCapacity,
                 "%s live BMI270 does not match configuration; restart required",
                 params_.name);
  }
  loadParams_(configured, spec.name, spec.params);
  if (configured.busIndex != params_.busIndex || configured.address != params_.address ||
      strcmp(configured.imuId, params_.imuId) != 0 ||
      strcmp(configured.domain, params_.domain) != 0 ||
      strcmp(configured.end, params_.end) != 0 ||
      strcmp(configured.mountPoint, params_.mountPoint) != 0 ||
      strcmp(configured.profile, params_.profile) != 0 ||
      !orientationsEqual_(configured.orientation, params_.orientation) ||
      configured.startupBiasCaptureSeconds != params_.startupBiasCaptureSeconds ||
      configured.maximumOutputRateHz != params_.maximumOutputRateHz ||
      configured.gyroBiasMode != params_.gyroBiasMode ||
      configured.iocDiagnostics != params_.iocDiagnostics ||
      strcmp(configured.calibrationRef, params_.calibrationRef) != 0) {
    return fail_(error, errorCapacity,
                 "%s BMI270 configuration changed; restart required",
                 params_.name);
  }
  const uint16_t resolvedOutputRate = BMI270Profile::resolveSparseRowOutputRateHz(
      params_.maximumOutputRateHz, effectiveRateHz);
  if (resolvedOutputRate == 0 || acquisition_.outputRateHz() != resolvedOutputRate) {
    return fail_(error, errorCapacity,
                 "%s could not resolve a safe IMU output rate for effective logger rate %u Hz",
                 params_.name, (unsigned)effectiveRateHz);
  }
  if (!I2CManager::available(params_.busIndex)) {
    return fail_(error, errorCapacity, "%s uses unavailable I2C bus %u",
                 params_.name, (unsigned)params_.busIndex);
  }
  const board::I2CProfile* busProfile = I2CManager::profile(params_.busIndex);
  if (!busProfile || busProfile->hz != 400000u) {
    return fail_(error, errorCapacity, "%s requires a 400 kHz I2C bus", params_.name);
  }
  return true;
}

bool BMI270ImuSensor::prepareLoggingStart(
    const LoggerConfig&,
    uint16_t effectiveRateHz,
    char* error,
    size_t errorCapacity) {
  if (muted_) return true;
  sessionAvailable_ = false;
  const uint16_t resolvedOutputRate = BMI270Profile::resolveSparseRowOutputRateHz(
      params_.maximumOutputRateHz, effectiveRateHz);
  if (resolvedOutputRate == 0) {
    return fail_(error, errorCapacity,
                 "%s has no safe sparse-row IMU output at logger rate %u Hz",
                 params_.name, (unsigned)effectiveRateHz);
  }
  if (!acquisition_.setOutputRateHz(resolvedOutputRate)) {
    return fail_(error, errorCapacity,
                 "%s could not select %u Hz IMU output",
                 params_.name, (unsigned)resolvedOutputRate);
  }
  if (!ensureInitialized_(error, errorCapacity)) {
    BMI270_SENSOR_LOGW(
        "sensor unavailable at logging start; continuing without IMU data sensor=%s bus=%u address=0x%02X\n",
        params_.name,
        (unsigned)params_.busIndex,
        (unsigned)params_.address);
    if (error && errorCapacity) error[0] = '\0';
    return true;
  }
  sessionAvailable_ = true;
  BMI270_SENSOR_LOGI(
      "logging rate plan sensor=%s max_output_rate_hz=%u effective_output_rate_hz=%u logger_rate_hz=%u\n",
      params_.name,
      (unsigned)params_.maximumOutputRateHz,
      (unsigned)resolvedOutputRate,
      (unsigned)effectiveRateHz);
  return true;
}

bool BMI270ImuSensor::startLoggingSession(char* error, size_t errorCapacity) {
  if (muted_) return true;
  if (!sessionAvailable_ || !initialized_) return true;
  if (!acquisition_.startSession(params_.startupBiasCaptureSeconds)) {
    initialized_ = false;
    sessionAvailable_ = false;
    BMI270_SENSOR_LOGW(
        "session start failed; continuing without IMU data sensor=%s bus=%u address=0x%02X\n",
        params_.name,
        (unsigned)params_.busIndex,
        (unsigned)params_.address);
    if (error && errorCapacity) error[0] = '\0';
    return true;
  }
  return true;
}

void BMI270ImuSensor::onLoggingStop() {
  if (acquisition_.sessionActive() && !acquisition_.stopSession()) {
    BMI270_SENSOR_LOGW("final FIFO drain failed sensor=%s\n", params_.name);
  }
  sessionAvailable_ = false;
}

size_t BMI270ImuSensor::pendingLoggingRows() const {
  return (muted_ || !sessionAvailable_) ? 0 : acquisition_.queuedSamples();
}

bool BMI270ImuSensor::captureImuOrientation(
    ImuInstallationPlane plane,
    int8_t normalSign,
    ImuOrientationCalibration& out,
    char* error,
    size_t errorCapacity) {
  out = ImuOrientationCalibration{};
  out.plane = plane;
  out.normalSign = normalSign;
  if (normalSign != 1 && normalSign != -1) {
    return fail_(error, errorCapacity, "%s orientation normal is invalid", params_.name);
  }
  if (I2CBusScheduler::isRunning() || acquisition_.sessionActive()) {
    return fail_(error, errorCapacity, "%s orientation capture requires an idle logger", params_.name);
  }
  if (!ensureInitialized_(error, errorCapacity)) return false;

  constexpr uint32_t kTargetSamples = 800;
  constexpr uint32_t kCaptureTimeoutMs = 7000;
  constexpr uint32_t kSettlingCleanSamples = 20;
  constexpr uint32_t kMaximumSettlingSamples = 200;
  constexpr uint16_t kRejectedStatus =
      BMI270ImuStatus::kFifoDiscontinuityBefore |
      BMI270ImuStatus::kQueueDropBefore |
      BMI270ImuStatus::kSensorRecoveryBefore |
      BMI270ImuStatus::kTimingDegraded |
      BMI270ImuStatus::kAccelNearRail |
      BMI270ImuStatus::kGyroNearRail;
  BMI270RunningStats accel[3];
  BMI270RunningStats gyro[3];
  BMI270RunningStats accelMagnitude;
  float maximumGyroMagnitudeRaw = 0.0f;
  bool qualityIncident = false;
  bool measurementStarted = false;
  uint32_t consecutiveCleanSamples = 0;

  if (!acquisition_.startSession(0)) {
    return fail_(error, errorCapacity, "%s orientation acquisition failed to start", params_.name);
  }
  I2CBusScheduler::start();
  const uint32_t startedMs = millis();
  while (out.sampleCount < kTargetSamples &&
         static_cast<uint32_t>(millis() - startedMs) < kCaptureTimeoutMs) {
    BMI270ImuSample sample;
    bool consumed = false;
    while (out.sampleCount < kTargetSamples && acquisition_.pop(sample)) {
      consumed = true;
      const uint16_t rejectedStatus =
          sample.measurementStatusFlags() & kRejectedStatus;
      if (!measurementStarted) {
        ++out.settlingSampleCount;
        out.settlingStatusMask |= rejectedStatus;
        if (rejectedStatus) {
          consecutiveCleanSamples = 0;
        } else {
          ++consecutiveCleanSamples;
        }
        if (consecutiveCleanSamples >= kSettlingCleanSamples) {
          measurementStarted = true;
        } else if (out.settlingSampleCount >= kMaximumSettlingSamples) {
          qualityIncident = true;
          out.qualityStatusMask = out.settlingStatusMask;
          break;
        }
        continue;
      }
      const double accelRaw[3] = {
          static_cast<double>(sample.accelX),
          static_cast<double>(sample.accelY),
          static_cast<double>(sample.accelZ)};
      const double gyroRaw[3] = {
          static_cast<double>(sample.gyroX),
          static_cast<double>(sample.gyroY),
          static_cast<double>(sample.gyroZ)};
      for (uint8_t axis = 0; axis < 3; ++axis) {
        accel[axis].add(accelRaw[axis]);
        gyro[axis].add(gyroRaw[axis]);
      }
      accelMagnitude.add(sqrt(
          accelRaw[0] * accelRaw[0] +
          accelRaw[1] * accelRaw[1] +
          accelRaw[2] * accelRaw[2]));
      const float gyroMagnitudeRaw = static_cast<float>(sqrt(
          gyroRaw[0] * gyroRaw[0] +
          gyroRaw[1] * gyroRaw[1] +
          gyroRaw[2] * gyroRaw[2]));
      if (gyroMagnitudeRaw > maximumGyroMagnitudeRaw) {
        maximumGyroMagnitudeRaw = gyroMagnitudeRaw;
      }
      if (rejectedStatus) {
        qualityIncident = true;
        out.qualityStatusMask |= rejectedStatus;
      }
      ++out.sampleCount;
    }
    if (qualityIncident && !measurementStarted) break;
    if (!consumed) delay(2);
  }
  I2CBusScheduler::stop();
  const bool stopped = acquisition_.stopSession();
  (void)acquisition_.discardQueuedSamples();
  if (!stopped) {
    return fail_(error, errorCapacity, "%s orientation acquisition failed to stop cleanly", params_.name);
  }

  for (uint8_t axis = 0; axis < 3; ++axis) {
    out.meanAccelRaw[axis] = static_cast<float>(accel[axis].mean());
  }
  out.accelMagnitudeMeanG =
      static_cast<float>(accelMagnitude.mean() / BMI270StartupObservation::kAccelCountsPerG);
  out.accelMagnitudeStdG = static_cast<float>(
      accelMagnitude.standardDeviation() / BMI270StartupObservation::kAccelCountsPerG);
  for (uint8_t axis = 0; axis < 3; ++axis) {
    const float stdDps = static_cast<float>(
        gyro[axis].standardDeviation() / BMI270StartupObservation::kGyroCountsPerDps);
    if (stdDps > out.gyroStdMaximumDps) out.gyroStdMaximumDps = stdDps;
  }
  out.maximumGyroMagnitudeDps =
      maximumGyroMagnitudeRaw / static_cast<float>(BMI270StartupObservation::kGyroCountsPerDps);
  if (RTCManager_hasValidTime()) out.capturedAtUnixMs = RTCManager_getEpochMs();

  uint16_t rejection = 0;
  if (out.sampleCount < kTargetSamples) rejection |= ImuOrientationRejection::kInsufficientSamples;
  if (qualityIncident) rejection |= ImuOrientationRejection::kQualityIncident;
  if (fabsf(out.accelMagnitudeMeanG - 1.0f) >
      static_cast<float>(BMI270StartupObservation::kAccelMeanToleranceG)) {
    rejection |= ImuOrientationRejection::kAccelMeanOutsideGravityBand;
  }
  if (out.accelMagnitudeStdG >
      static_cast<float>(BMI270StartupObservation::kAccelStdMaximumG)) {
    rejection |= ImuOrientationRejection::kAccelMagnitudeUnstable;
  }
  if (out.gyroStdMaximumDps >
      static_cast<float>(BMI270StartupObservation::kGyroStdMaximumDps)) {
    rejection |= ImuOrientationRejection::kGyroUnstable;
  }
  if (out.maximumGyroMagnitudeDps >
      static_cast<float>(BMI270StartupObservation::kGyroMagnitudeMaximumDps)) {
    rejection |= ImuOrientationRejection::kGyroMotionDetected;
  }
  if (!ImuOrientation::solve(
          plane, normalSign, out.meanAccelRaw, out.matrix, out.rollDeviationDeg)) {
    rejection |= ImuOrientationRejection::kInvalidGeometry;
  }
  if (out.rollDeviationDeg > ImuOrientation::kMaximumRollDeviationDeg) {
    rejection |= ImuOrientationRejection::kRollOutsideLimit;
  }
  out.rejectionMask = rejection;
  out.accepted = rejection == 0;
  if (out.accepted) ImuOrientation::matrixToQuaternion(out.matrix, out.quaternionWxyz);
  BMI270_SENSOR_LOGI(
      "orientation capture sensor=%s accepted=%u reject=0x%04X status=0x%04X settle_status=0x%04X settle_samples=%lu samples=%lu accel_mean=%.5f accel_std=%.5f gyro_std=%.5f gyro_max=%.5f roll=%.3f\n",
      params_.name,
      out.accepted ? 1u : 0u,
      (unsigned)out.rejectionMask,
      (unsigned)out.qualityStatusMask,
      (unsigned)out.settlingStatusMask,
      (unsigned long)out.settlingSampleCount,
      (unsigned long)out.sampleCount,
      (double)out.accelMagnitudeMeanG,
      (double)out.accelMagnitudeStdG,
      (double)out.gyroStdMaximumDps,
      (double)out.maximumGyroMagnitudeDps,
      (double)out.rollDeviationDeg);
  return true;
}

bool BMI270ImuSensor::saveImuOrientation(
    const ImuOrientationCalibration& calibration,
    char* error,
    size_t errorCapacity) {
  if (!calibration.accepted || calibration.rejectionMask != 0 ||
      !ImuOrientation::validateMatrix(calibration.matrix)) {
    return fail_(error, errorCapacity, "%s has no accepted orientation to save", params_.name);
  }
  const int8_t index = ConfigManager::findSensorByName(params_.name);
  SensorSpec spec;
  if (index < 0 || !ConfigManager::getSensorSpec(static_cast<uint8_t>(index), spec)) {
    return fail_(error, errorCapacity, "%s configuration was not found", params_.name);
  }

  static const char* const keys[] = {
      "orient_valid", "orient_plane", "orient_normal_sign",
      "orient_qw", "orient_qx", "orient_qy", "orient_qz",
      "orient_samples", "orient_epoch_ms",
      "orient_mean_ax", "orient_mean_ay", "orient_mean_az",
      "orient_accel_mean_g", "orient_accel_std_g",
      "orient_gyro_std_dps", "orient_gyro_max_dps", "orient_roll_deg",
  };
  String previous[sizeof(keys) / sizeof(keys[0])];
  bool hadPrevious[sizeof(keys) / sizeof(keys[0])] {};
  for (size_t i = 0; i < sizeof(keys) / sizeof(keys[0]); ++i) {
    hadPrevious[i] = spec.params.get(keys[i], previous[i]);
  }
  auto restorePrevious = [&]() {
    for (size_t i = 0; i < sizeof(keys) / sizeof(keys[0]); ++i) {
      if (hadPrevious[i]) (void)spec.params.set(keys[i], previous[i]);
    }
  };

  char epoch[24];
  snprintf(epoch, sizeof(epoch), "%llu",
           static_cast<unsigned long long>(calibration.capturedAtUnixMs));
  bool stored =
      spec.params.setBool("orient_valid", true) &&
      spec.params.set("orient_plane", ImuOrientation::planeKey(calibration.plane)) &&
      spec.params.setInt("orient_normal_sign", calibration.normalSign) &&
      spec.params.setFloat("orient_qw", calibration.quaternionWxyz[0]) &&
      spec.params.setFloat("orient_qx", calibration.quaternionWxyz[1]) &&
      spec.params.setFloat("orient_qy", calibration.quaternionWxyz[2]) &&
      spec.params.setFloat("orient_qz", calibration.quaternionWxyz[3]) &&
      spec.params.setInt("orient_samples", static_cast<long>(calibration.sampleCount)) &&
      spec.params.set("orient_epoch_ms", epoch) &&
      spec.params.setFloat("orient_mean_ax", calibration.meanAccelRaw[0]) &&
      spec.params.setFloat("orient_mean_ay", calibration.meanAccelRaw[1]) &&
      spec.params.setFloat("orient_mean_az", calibration.meanAccelRaw[2]) &&
      spec.params.setFloat("orient_accel_mean_g", calibration.accelMagnitudeMeanG) &&
      spec.params.setFloat("orient_accel_std_g", calibration.accelMagnitudeStdG) &&
      spec.params.setFloat("orient_gyro_std_dps", calibration.gyroStdMaximumDps) &&
      spec.params.setFloat("orient_gyro_max_dps", calibration.maximumGyroMagnitudeDps) &&
      spec.params.setFloat("orient_roll_deg", calibration.rollDeviationDeg);
  if (!stored) {
    restorePrevious();
    return fail_(error, errorCapacity, "%s orientation configuration is full", params_.name);
  }
  if (!ConfigManager::save(ConfigManager::get())) {
    restorePrevious();
    return fail_(error, errorCapacity, "%s orientation could not be persisted", params_.name);
  }
  params_.orientation = calibration;
  return true;
}

bool BMI270ImuSensor::loadParams_(
    Params& out,
    const char* instanceName,
    const ParamPack& params) {
  out = Params{};
  copyField_(out.name, sizeof(out.name), instanceName && *instanceName ? instanceName : "frame_imu");
  snprintf(out.imuId, sizeof(out.imuId), "%s_001", out.name);
  readString_(params, "imu_id", out.imuId, sizeof(out.imuId));
  if (!readString_(params, "domain", out.domain, sizeof(out.domain))) {
    (void)readString_(params, "location", out.domain, sizeof(out.domain));
  }
  readString_(params, "end", out.end, sizeof(out.end));
  readString_(params, "mount_point", out.mountPoint, sizeof(out.mountPoint));
  canonicalizeToken_(out.domain, sizeof(out.domain));
  canonicalizeToken_(out.end, sizeof(out.end));
  if (strcmp(out.end, "none") == 0) out.end[0] = '\0';
  readString_(params, "profile", out.profile, sizeof(out.profile));
  readString_(params, "calibration_ref", out.calibrationRef, sizeof(out.calibrationRef));
  loadOrientation_(out.orientation, params);

  long value = 0;
  if (params.getInt("i2c_bus", value) && value >= 0 && value <= 255) {
    out.busIndex = static_cast<uint8_t>(value);
  }
  if (params.getInt("i2c_addr", value) && value >= 0 && value <= 255) {
    out.address = static_cast<uint8_t>(value);
  }
  if (params.getInt("startup_bias_capture_s", value) && value >= 0 && value <= 65535) {
    out.startupBiasCaptureSeconds = static_cast<uint16_t>(value);
  }
  // max_output_rate_hz is the production setting. output_rate_hz is accepted
  // only as a migration alias for configurations written by the MVP firmware.
  if (params.getInt("max_output_rate_hz", value) && value >= 0 && value <= 65535) {
    out.maximumOutputRateHz = static_cast<uint16_t>(value);
  } else if (params.getInt("output_rate_hz", value) && value >= 0 && value <= 65535) {
    out.maximumOutputRateHz = static_cast<uint16_t>(value);
  }
  String gyroBiasMode;
  if (params.get("gyro_bias_mode", gyroBiasMode)) {
    gyroBiasMode.trim();
    gyroBiasMode.toLowerCase();
    (void)parseGyroBiasMode_(gyroBiasMode.c_str(), out.gyroBiasMode);
  }
  (void)params.getBool("ioc_diagnostics", out.iocDiagnostics);
  return true;
}

bool BMI270ImuSensor::validateSpec(
    const SensorSpec& spec,
    char* error,
    size_t errorCapacity) {
  Params params;
  loadParams_(params, spec.name, spec.params);
  long configuredInteger = 0;
  if (spec.params.getInt("i2c_bus", configuredInteger) &&
      (configuredInteger < 0 || configuredInteger > 255)) {
    return fail_(error, errorCapacity, "%s has an invalid I2C bus value", params.name);
  }
  if (spec.params.getInt("i2c_addr", configuredInteger) &&
      (configuredInteger < 0 || configuredInteger > 255)) {
    return fail_(error, errorCapacity, "%s has an invalid I2C address value", params.name);
  }
  if (spec.params.getInt("startup_bias_capture_s", configuredInteger) &&
      (configuredInteger < 0 || configuredInteger > 60)) {
    return fail_(error, errorCapacity,
                 "%s startup_bias_capture_s must be between 0 and 60",
                 params.name);
  }
  if (!BMI270Profile::isSupportedOutputRate(params.maximumOutputRateHz)) {
    return fail_(error, errorCapacity,
                 "%s max_output_rate_hz must be one of 5, 10, 20, 25, 40, 50, 100, 200",
                 params.name);
  }
  String gyroBiasMode;
  if (spec.params.get("gyro_bias_mode", gyroBiasMode)) {
    gyroBiasMode.trim();
    gyroBiasMode.toLowerCase();
    if (!parseGyroBiasMode_(gyroBiasMode.c_str(), params.gyroBiasMode)) {
      return fail_(error, errorCapacity,
                   "%s gyro_bias_mode must be off or ioc", params.name);
    }
  }
  if (params.iocDiagnostics &&
      params.gyroBiasMode != BMI270GyroBiasMode::InUseOffsetCorrection) {
    return fail_(error, errorCapacity,
                 "%s ioc_diagnostics requires gyro_bias_mode=ioc", params.name);
  }
  if (!params.name[0]) return fail_(error, errorCapacity, "BMI270 sensor name is empty");
  if (!params.imuId[0]) return fail_(error, errorCapacity, "%s has an empty imu_id", params.name);
  if (!validMountSemantics_(params)) {
    return fail_(error, errorCapacity,
                 "%s requires domain=unsprung with front/rear, domain=steering with front, or domain=frame with none/front/rear",
                 params.name);
  }
  if (strcmp(params.profile, BMI270Profile::kProfileName) != 0) {
    return fail_(error, errorCapacity, "%s uses unsupported profile '%s'",
                 params.name, params.profile);
  }
  if (!BMI270Profile::isSupportedAddress(params.address)) {
    return fail_(error, errorCapacity, "%s uses unsupported BMI270 address 0x%02X",
                 params.name, (unsigned)params.address);
  }
  if (!I2CManager::available(params.busIndex)) {
    return fail_(error, errorCapacity, "%s uses unavailable I2C bus %u",
                 params.name, (unsigned)params.busIndex);
  }
  const board::I2CProfile* busProfile = I2CManager::profile(params.busIndex);
  if (!busProfile || busProfile->hz != 400000u) {
    return fail_(error, errorCapacity, "%s requires a 400 kHz I2C bus", params.name);
  }
  if (params.orientation.accepted &&
      !ImuOrientation::validateMatrix(params.orientation.matrix)) {
    return fail_(error, errorCapacity,
                 "%s orientation matrix must be a right-handed orthonormal rotation",
                 params.name);
  }
  return true;
}

const ParamDef* BMI270ImuSensor::paramDefs(size_t& count) {
  static const ParamDef definitions[] = {
    {"imu_id", ParamType::String, "frame_imu_001", nullptr, nullptr, nullptr, "Stable physical IMU identity"},
    {"domain", ParamType::Enum, "frame", nullptr, nullptr, "unsprung,frame,steering", "Mechanically co-moving bicycle domain"},
    {"end", ParamType::Enum, "none", nullptr, nullptr, "none,front,rear", "Bike end; none is valid only for frame"},
    {"mount_point", ParamType::String, "", nullptr, nullptr, nullptr, "Optional descriptive mounting point"},
    {"i2c_bus", ParamType::Enum, "1", nullptr, nullptr, "0,1", "Board I2C bus index"},
    {"i2c_addr", ParamType::Enum, "104", nullptr, nullptr, "104,105", "BMI270 I2C address (0x68 or 0x69)"},
    {"profile", ParamType::Enum, "orientation_200", nullptr, nullptr, "orientation_200", "Named acquisition profile"},
    {"startup_bias_capture_s", ParamType::Int, "5", "0", "60", nullptr, "Startup stationary-observation window; records bias evidence without modifying raw samples"},
    {"max_output_rate_hz", ParamType::Enum, "200", nullptr, nullptr, "5,10,20,25,40,50,100,200", "Maximum stored IMU rate; effective output is selected safely at log start while FIFO acquisition remains 200 Hz"},
    {"gyro_bias_mode", ParamType::Enum, "off", nullptr, nullptr, "off,ioc", "Gyro hardware bias mode; IOC makes logged gyro counts hardware-offset-compensated"},
    {"ioc_diagnostics", ParamType::Bool, "false", nullptr, nullptr, nullptr, "Experimental 1 Hz BMI270 IOC offset-register trace; requires gyro_bias_mode=ioc", true},
    {"calibration_ref", ParamType::String, "", nullptr, nullptr, nullptr, "Optional host calibration reference"},
    {"orient_valid", ParamType::Bool, "false", nullptr, nullptr, nullptr, "Internal assisted-orientation state", true},
    {"orient_plane", ParamType::String, "xz", nullptr, nullptr, nullptr, "Internal assisted-orientation plane", true},
    {"orient_normal_sign", ParamType::Int, "1", "-1", "1", nullptr, "Internal assisted-orientation normal", true},
    {"orient_qw", ParamType::Float, "1", nullptr, nullptr, nullptr, "Internal orientation quaternion W", true},
    {"orient_qx", ParamType::Float, "0", nullptr, nullptr, nullptr, "Internal orientation quaternion X", true},
    {"orient_qy", ParamType::Float, "0", nullptr, nullptr, nullptr, "Internal orientation quaternion Y", true},
    {"orient_qz", ParamType::Float, "0", nullptr, nullptr, nullptr, "Internal orientation quaternion Z", true},
    {"orient_samples", ParamType::Int, "0", "0", nullptr, nullptr, "Internal orientation sample count", true},
    {"orient_epoch_ms", ParamType::String, "0", nullptr, nullptr, nullptr, "Internal orientation capture time", true},
    {"orient_mean_ax", ParamType::Float, "0", nullptr, nullptr, nullptr, "Internal mean acceleration X", true},
    {"orient_mean_ay", ParamType::Float, "0", nullptr, nullptr, nullptr, "Internal mean acceleration Y", true},
    {"orient_mean_az", ParamType::Float, "0", nullptr, nullptr, nullptr, "Internal mean acceleration Z", true},
    {"orient_accel_mean_g", ParamType::Float, "0", nullptr, nullptr, nullptr, "Internal acceleration magnitude mean", true},
    {"orient_accel_std_g", ParamType::Float, "0", nullptr, nullptr, nullptr, "Internal acceleration magnitude deviation", true},
    {"orient_gyro_std_dps", ParamType::Float, "0", nullptr, nullptr, nullptr, "Internal gyroscope deviation", true},
    {"orient_gyro_max_dps", ParamType::Float, "0", nullptr, nullptr, nullptr, "Internal maximum gyroscope magnitude", true},
    {"orient_roll_deg", ParamType::Float, "0", nullptr, nullptr, nullptr, "Internal roll residual", true},
  };
  count = sizeof(definitions) / sizeof(definitions[0]);
  return definitions;
}

Sensor* BMI270ImuSensor::create(
    const char* instanceName,
    const ParamPack& params,
    bool mutedDefault) {
  Params parsed;
  loadParams_(parsed, instanceName, params);
  if (!BMI270Profile::isSupportedAddress(parsed.address) ||
      strcmp(parsed.profile, BMI270Profile::kProfileName) != 0 ||
      !validMountSemantics_(parsed) ||
      (parsed.orientation.accepted &&
       !ImuOrientation::validateMatrix(parsed.orientation.matrix))) {
    BMI270_SENSOR_LOGW("refusing invalid configuration for sensor=%s\n", parsed.name);
    return nullptr;
  }
  auto* sensor = new BMI270ImuSensor(parsed);
  sensor->setMuted(mutedDefault);
  return sensor;
}

static bool s_registeredBmi270Imu = SensorRegistry::registerType(
    SensorType::BMI270ImuI2C,
    "bmi270_imu_i2c",
    "BMI270 IMU (I2C)",
    &BMI270ImuSensor::paramDefs,
    &BMI270ImuSensor::create,
    CAL_NONE);
