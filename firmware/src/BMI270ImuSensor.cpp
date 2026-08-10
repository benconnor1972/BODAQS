#include "BMI270ImuSensor.h"

#include <Arduino.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "BMI270Profile.h"
#include "BMI270SparseRow.h"
#include "ConfigManager.h"
#include "DebugLog.h"
#include "I2CManager.h"
#include "SensorRegistry.h"
#include "esp_timer.h"

#define BMI270_SENSOR_LOGI(...) LOGI_TAG("BMI270", __VA_ARGS__)
#define BMI270_SENSOR_LOGW(...) LOGW_TAG("BMI270", __VA_ARGS__)

namespace {

static_assert(BMI270ImuSensor::kColumnCount == BMI270SparseRow::kColumnCount);

const char* const kColumnSuffix[BMI270ImuSensor::kColumnCount] = {
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
    default: return "";
  }
}

const char* unitFor_(uint8_t index) {
  if (index <= 5 || index == 7 || index == 8) return "count";
  if (index == 6) return "tick";
  if (index == 9) return "us";
  if (index == 10) return "bitfield";
  if (index == 11) return "boolean";
  return "";
}

const char* sourceFor_(uint8_t index) {
  if (index <= 5 || index == 11) return "async_fifo_once";
  if (index == 6) return "bmi270_sensor_time";
  if (index == 7) return "firmware_sequence";
  if (index == 8) return "bmi270_temperature";
  if (index == 9) return "native_to_row_timing";
  if (index == 10) return "imu_status";
  return "";
}

SensorColumnStorageType storageFor_(uint8_t index) {
  if (index <= 5 || index == 8) return SensorColumnStorageType::Int16;
  if (index == 6 || index == 7) return SensorColumnStorageType::UInt32;
  if (index == 9) return SensorColumnStorageType::Float32;
  return SensorColumnStorageType::UInt16;
}

} // namespace

BMI270ImuSensor::BMI270ImuSensor(const Params& params)
    : params_(params),
      acquisition_(params.busIndex, params.address, params.name) {
  (void)BMI270Mount::parseTransform(
      params_.mountAxis[0], params_.mountAxis[1], params_.mountAxis[2], mount_);
}

void BMI270ImuSensor::begin() {
  initialized_ = acquisition_.begin();
  if (!initialized_) {
    BMI270_SENSOR_LOGW(
        "initialization failed sensor=%s bus=%u address=0x%02X\n",
        params_.name,
        (unsigned)params_.busIndex,
        (unsigned)params_.address);
  }
}

void BMI270ImuSensor::getColumnName(uint8_t index, char* out, size_t capacity) const {
  if (!out || capacity == 0) return;
  out[0] = '\0';
  if (index >= kColumnCount) return;
  snprintf(out, capacity, "%s_%s", params_.name, kColumnSuffix[index]);
}

void BMI270ImuSensor::sampleValues(float* out, uint8_t maximum) {
  if (!out || maximum == 0) return;

  float values[BMI270SparseRow::kColumnCount];
  BMI270ImuSample sample;
  const bool haveSample = acquisition_.pop(sample);
  uint32_t ageUs = 0;
  bool ageValid = false;
  BMI270SparseRow::encode(
      haveSample ? &sample : nullptr,
      static_cast<uint64_t>(esp_timer_get_time()),
      values,
      ageUs,
      ageValid);

  const uint8_t count = maximum < kColumnCount ? maximum : kColumnCount;
  memcpy(out, values, count * sizeof(float));
  I2CBusScheduler::recordRowUse(&acquisition_, ageUs, ageValid, haveSample);
  if (haveSample) acquisition_.recordRowEmission(ageUs, ageValid);
}

bool BMI270ImuSensor::describeColumn(uint8_t index, SensorColumnDescriptor& out) const {
  if (index >= kColumnCount) return false;
  out = SensorColumnDescriptor{};
  getColumnName(index, out.csvHeader, sizeof(out.csvHeader));
  copyField_(out.columnId, sizeof(out.columnId), out.csvHeader);
  copyField_(out.sensorName, sizeof(out.sensorName), params_.name);
  copyField_(out.end, sizeof(out.end), params_.end);
  copyField_(out.domain, sizeof(out.domain), params_.domain);
  copyField_(out.mountPoint, sizeof(out.mountPoint), params_.mountPoint);
  copyField_(out.quantity, sizeof(out.quantity), quantityFor_(index));
  if (index <= 5) {
    static const char* const components[] = {"x", "y", "z"};
    copyField_(out.component, sizeof(out.component), components[index % 3]);
    copyField_(out.coordinateFrame, sizeof(out.coordinateFrame), "sensor_native");
    copyField_(out.vectorGroup, sizeof(out.vectorGroup), index <= 2 ? "accel_raw" : "gyro_raw");
  }
  copyField_(out.unit, sizeof(out.unit), unitFor_(index));
  copyField_(out.source, sizeof(out.source), sourceFor_(index));
  copyField_(out.processingRole, sizeof(out.processingRole), index <= 5 ? "raw_evidence" : "qc_metric");
  out.storageType = storageFor_(index);
  out.raw = index <= 5 || index == 8;
  out.primary = index <= 5;
  out.diagnostic = index >= 6;
  out.semanticSelectionExcluded = out.diagnostic;
  out.allowNaN = index == 9;
  if (out.raw) copyField_(out.kind, sizeof(out.kind), "raw");
  else if (out.diagnostic) copyField_(out.kind, sizeof(out.kind), "qc");
  copyField_(out.notes, sizeof(out.notes),
             index == 11 ? "1 only when this row contains a new native sample" :
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
  for (uint8_t axis = 0; axis < 3; ++axis) {
    copyField_(imu.mountAxis[axis], sizeof(imu.mountAxis[axis]), params_.mountAxis[axis]);
  }
  imu.busIndex = params_.busIndex;
  imu.address = params_.address;
  const board::I2CProfile* busProfile = I2CManager::profile(params_.busIndex);
  imu.i2cClockHz = busProfile ? busProfile->hz : 0;
  imu.loggerRateHz = BMI270Profile::kLoggerRateHz;
  imu.imuRateHz = BMI270Profile::kOdrHz;
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
  out.initialProbeOk = device.chipIdRead && device.chipIdMatched;
  out.configWriteAttempted = device.configurationWriteAttempted;
  out.configWriteOk = device.configurationWriteOk;
  out.configReadAttempted = device.configurationReadAttempted;
  out.configReadOk = device.configurationReadOk && device.configurationMatched;
  out.rawReadFailures = static_cast<uint32_t>(fifo.drainFailures > UINT32_MAX ? UINT32_MAX : fifo.drainFailures);
  out.readFailureStreakMax = fifo.maximumDrainFailureStreak;
  out.readRecoveries = static_cast<uint32_t>(fifo.recoverySuccesses > UINT32_MAX ? UINT32_MAX : fifo.recoverySuccesses);
  out.lastReadOk = transport.lastOperationOk;
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
  out.imuQueueDrops = fifo.queueDrops;
  out.imuPreSessionQueueDiscards = fifo.preSessionQueueDiscards;
  out.imuExplicitQueueDiscards = fifo.explicitQueueDiscards;
  out.imuTemperatureReads = fifo.temperatureReads;
  out.imuTemperatureReadFailures = fifo.temperatureReadFailures;
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
  out.imuStartupTargetSampleSlots = startup.targetSampleSlots;
  out.imuStartupValidSamples = startup.validSamples;
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
      strcmp(configured.mountAxis[0], params_.mountAxis[0]) != 0 ||
      strcmp(configured.mountAxis[1], params_.mountAxis[1]) != 0 ||
      strcmp(configured.mountAxis[2], params_.mountAxis[2]) != 0 ||
      configured.startupBiasCaptureSeconds != params_.startupBiasCaptureSeconds ||
      strcmp(configured.calibrationRef, params_.calibrationRef) != 0) {
    return fail_(error, errorCapacity,
                 "%s BMI270 configuration changed; restart required",
                 params_.name);
  }
  if (effectiveRateHz != BMI270Profile::kLoggerRateHz) {
    return fail_(error, errorCapacity,
                 "%s requires a 500 Hz logger rate (effective %u Hz)",
                 params_.name,
                 (unsigned)effectiveRateHz);
  }
  if (!I2CManager::available(params_.busIndex)) {
    return fail_(error, errorCapacity, "%s uses unavailable I2C bus %u",
                 params_.name, (unsigned)params_.busIndex);
  }
  const board::I2CProfile* busProfile = I2CManager::profile(params_.busIndex);
  if (!busProfile || busProfile->hz != 400000u) {
    return fail_(error, errorCapacity, "%s requires a 400 kHz I2C bus", params_.name);
  }
  if (!initialized_) {
    return fail_(error, errorCapacity, "%s BMI270 initialization failed", params_.name);
  }
  return true;
}

bool BMI270ImuSensor::startLoggingSession(char* error, size_t errorCapacity) {
  if (muted_) return true;
  if (!acquisition_.startSession(params_.startupBiasCaptureSeconds)) {
    return fail_(error, errorCapacity, "%s BMI270 session start failed", params_.name);
  }
  return true;
}

void BMI270ImuSensor::onLoggingStop() {
  if (!acquisition_.sessionActive()) return;
  if (!acquisition_.stopSession()) {
    BMI270_SENSOR_LOGW("final FIFO drain failed sensor=%s\n", params_.name);
  }
}

size_t BMI270ImuSensor::pendingLoggingRows() const {
  return muted_ ? 0 : acquisition_.queuedSamples();
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
  readString_(params, "mount_x", out.mountAxis[0], sizeof(out.mountAxis[0]));
  readString_(params, "mount_y", out.mountAxis[1], sizeof(out.mountAxis[1]));
  readString_(params, "mount_z", out.mountAxis[2], sizeof(out.mountAxis[2]));
  readString_(params, "calibration_ref", out.calibrationRef, sizeof(out.calibrationRef));

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
  BMI270MountTransform transform;
  if (!BMI270Mount::parseTransform(
          params.mountAxis[0], params.mountAxis[1], params.mountAxis[2], transform)) {
    return fail_(error, errorCapacity,
                 "%s mounting map must be a right-handed signed axis permutation",
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
    {"mount_x", ParamType::Enum, "+x", nullptr, nullptr, "+x,-x,+y,-y,+z,-z", "Body-local X as a signed sensor-native axis"},
    {"mount_y", ParamType::Enum, "+y", nullptr, nullptr, "+x,-x,+y,-y,+z,-z", "Body-local Y as a signed sensor-native axis"},
    {"mount_z", ParamType::Enum, "+z", nullptr, nullptr, "+x,-x,+y,-y,+z,-z", "Body-local Z as a signed sensor-native axis"},
    {"startup_bias_capture_s", ParamType::Int, "5", "0", "60", nullptr, "Startup stationary-observation window; records bias evidence without modifying raw samples"},
    {"calibration_ref", ParamType::String, "", nullptr, nullptr, nullptr, "Optional host calibration reference"},
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
  BMI270MountTransform transform;
  if (!BMI270Profile::isSupportedAddress(parsed.address) ||
      strcmp(parsed.profile, BMI270Profile::kProfileName) != 0 ||
      !validMountSemantics_(parsed) ||
      !BMI270Mount::parseTransform(
          parsed.mountAxis[0], parsed.mountAxis[1], parsed.mountAxis[2], transform)) {
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
