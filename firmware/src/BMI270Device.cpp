#include "BMI270Device.h"

#include <Arduino.h>

#include "DebugLog.h"
#include "I2CManager.h"

#define BMI270_LOGI(...) LOGI_TAG("BMI270", __VA_ARGS__)
#define BMI270_LOGW(...) LOGW_TAG("BMI270", __VA_ARGS__)

namespace {

constexpr uint32_t kRetryDelayMs = 50;
constexpr uint8_t kEnabledSensors[] = { BMI2_ACCEL, BMI2_GYRO, BMI2_TEMP };
constexpr uint8_t kEnabledSensorCount =
    static_cast<uint8_t>(sizeof(kEnabledSensors) / sizeof(kEnabledSensors[0]));
constexpr uint8_t kRequiredPowerControl =
    BMI2_ACC_EN_MASK | BMI2_GYR_EN_MASK | BMI2_TEMP_EN_MASK;

static_assert(BMI2_ACC_ODR_200HZ == BMI270Profile::kOdrCode);
static_assert(BMI2_GYR_ODR_200HZ == BMI270Profile::kOdrCode);
static_assert(BMI2_ACC_RANGE_16G == BMI270Profile::kAccelRange16GCode);
static_assert(BMI2_ACC_NORMAL_AVG4 == BMI270Profile::kAccelNormalAvg4Code);
static_assert(BMI2_GYR_RANGE_2000 == BMI270Profile::kGyroRange2000DpsCode);
static_assert(BMI2_GYR_NORMAL_MODE == BMI270Profile::kGyroNormalModeCode);
static_assert(BMI2_POWER_OPT_MODE == BMI270Profile::kPowerOptimizedCode);
static_assert(BMI2_PERF_OPT_MODE == BMI270Profile::kPerformanceOptimizedCode);

void copyEffectiveConfig_(
    const struct bmi2_sens_config (&config)[2],
    BMI270Profile::EffectiveConfig& out) {
  out = BMI270Profile::EffectiveConfig{};
  out.accelOdr = config[0].cfg.acc.odr;
  out.accelRange = config[0].cfg.acc.range;
  out.accelBandwidth = config[0].cfg.acc.bwp;
  out.accelFilterPerformance = config[0].cfg.acc.filter_perf;
  out.gyroOdr = config[1].cfg.gyr.odr;
  out.gyroRange = config[1].cfg.gyr.range;
  out.gyroBandwidth = config[1].cfg.gyr.bwp;
  out.gyroNoisePerformance = config[1].cfg.gyr.noise_perf;
  out.gyroFilterPerformance = config[1].cfg.gyr.filter_perf;
}

} // namespace

BMI270Device::BMI270Device(uint8_t busIndex, uint8_t address)
    : transport_(busIndex, address) {
}

BMI270Device::~BMI270Device() {
  shutdown();
}

bool BMI270Device::setGyroBiasMode(BMI270GyroBiasMode mode) {
  if (diagnostics_.state != BMI270DeviceState::Uninitialized) return false;
  gyroBiasMode_ = mode;
  return true;
}

bool BMI270Device::begin() {
  ++diagnostics_.beginCalls;
  if (ready()) return true;
  if (diagnostics_.state == BMI270DeviceState::Suspended) return resume();

  setState_(BMI270DeviceState::Initializing);
  diagnostics_.failureStep = BMI270DeviceStep::None;
  diagnostics_.lastApiResult = BMI2_OK;
  diagnostics_.failureCleanupAttempted = false;
  diagnostics_.failureCleanupOk = false;

  for (uint8_t attempt = 0; attempt < BMI270Profile::kInitializationAttempts; ++attempt) {
    ++diagnostics_.initializationAttempts;
    if (initializeOnce_()) {
      setState_(BMI270DeviceState::Ready);
      BMI270_LOGI(
          "ready bus=%u addr=0x%02X chip=0x%02X profile=%s\n",
          (unsigned)busIndex(),
          (unsigned)address(),
          (unsigned)diagnostics_.chipId,
          BMI270Profile::kProfileName);
      return true;
    }

    ++diagnostics_.initializationFailures;
    quiesceAfterFailedInitialization_();
    if (diagnostics_.failureStep == BMI270DeviceStep::ValidateParameters) {
      break;
    }
    if (attempt + 1 < BMI270Profile::kInitializationAttempts) {
      delay(kRetryDelayMs);
    }
  }

  setState_(BMI270DeviceState::Fault);
  BMI270_LOGW(
      "initialization failed bus=%u addr=0x%02X step=%u result=%d attempts=%lu\n",
      (unsigned)busIndex(),
      (unsigned)address(),
      (unsigned)diagnostics_.failureStep,
      (int)diagnostics_.lastApiResult,
      (unsigned long)diagnostics_.initializationAttempts);
  return false;
}

bool BMI270Device::suspend() {
  if (diagnostics_.state == BMI270DeviceState::Suspended) return true;
  if (!ready()) return false;
  if (!disableSensors_(BMI270DeviceStep::DisableSensors)) {
    setState_(BMI270DeviceState::Fault);
    return false;
  }
  setState_(BMI270DeviceState::Suspended);
  return true;
}

bool BMI270Device::resume() {
  if (ready()) return true;
  if (diagnostics_.state != BMI270DeviceState::Suspended) return false;
  if (!enableSensors_(BMI270DeviceStep::ResumeSensors)) {
    setState_(BMI270DeviceState::Fault);
    return false;
  }
  setState_(BMI270DeviceState::Ready);
  return true;
}

bool BMI270Device::recover() {
  ++diagnostics_.recoveryAttempts;
  shutdown();
  const bool ok = begin();
  if (ok) ++diagnostics_.recoverySuccesses;
  return ok;
}

bool BMI270Device::validateOperationalState(
    bool sensorsExpected,
    BMI270OperationalState& out) {
  out = BMI270OperationalState{};
  const BMI270DeviceState expectedState = sensorsExpected
      ? BMI270DeviceState::Ready
      : BMI270DeviceState::Suspended;
  if (diagnostics_.state != expectedState) {
    out.issues |= BMI270OperationalIssue::kUnexpectedSoftwareState;
  }

  if (!transport_.probeChipId(out.chipId)) {
    out.issues |= BMI270OperationalIssue::kChipIdReadFailed;
    out.lastApiResult = BMI2_E_COM_FAIL;
  } else if (out.chipId != BMI270_CHIP_ID) {
    out.issues |= BMI270OperationalIssue::kChipIdMismatch;
    out.lastApiResult = BMI2_E_DEV_NOT_FOUND;
  }

  int8_t result = bmi2_get_internal_status(&out.internalStatus, &device_);
  if (result != BMI2_OK) {
    out.issues |= BMI270OperationalIssue::kInternalStatusReadFailed;
    out.lastApiResult = result;
  } else if (out.internalStatus != BMI2_CONFIG_LOAD_SUCCESS) {
    out.issues |= BMI270OperationalIssue::kInternalStatusMismatch;
    out.lastApiResult = BMI2_E_CONFIG_LOAD;
  }

  struct bmi2_sens_config config[2] {};
  config[0].type = BMI2_ACCEL;
  config[1].type = BMI2_GYRO;
  result = bmi270_get_sensor_config(config, 2, &device_);
  if (result != BMI2_OK) {
    out.issues |= BMI270OperationalIssue::kProfileReadFailed;
    out.lastApiResult = result;
  } else {
    copyEffectiveConfig_(config, out.effectiveConfig);
    if (!BMI270Profile::matchesOrientation200(out.effectiveConfig)) {
      out.issues |= BMI270OperationalIssue::kProfileMismatch;
      out.lastApiResult = BMI2_E_INVALID_STATUS;
    }
  }

  result = bmi2_get_regs(BMI2_PWR_CTRL_ADDR, &out.powerControl, 1, &device_);
  if (result != BMI2_OK) {
    out.issues |= BMI270OperationalIssue::kPowerControlReadFailed;
    out.lastApiResult = result;
  } else {
    const uint8_t enabled = out.powerControl & kRequiredPowerControl;
    const uint8_t expected = sensorsExpected ? kRequiredPowerControl : 0;
    if (enabled != expected) {
      out.issues |= BMI270OperationalIssue::kPowerControlMismatch;
      out.lastApiResult = BMI2_E_INVALID_STATUS;
    }
  }

  return out.valid();
}

void BMI270Device::shutdown() {
  if (diagnostics_.driverInitialized && diagnostics_.sensorsEnabled) {
    if (!disableSensors_(BMI270DeviceStep::DisableSensors)) {
      setState_(BMI270DeviceState::Fault);
      return;
    }
  }
  diagnostics_.sensorsEnabled = false;
  if (diagnostics_.state != BMI270DeviceState::Fault) {
    setState_(BMI270DeviceState::Uninitialized);
  }
}

bool BMI270Device::initializeOnce_() {
  diagnostics_.chipIdRead = false;
  diagnostics_.chipIdMatched = false;
  diagnostics_.driverInitialized = false;
  diagnostics_.configurationWriteAttempted = false;
  diagnostics_.configurationWriteOk = false;
  diagnostics_.configurationReadAttempted = false;
  diagnostics_.configurationReadOk = false;
  diagnostics_.configurationMatched = false;
  diagnostics_.offsetCompensationDisabled = false;
  diagnostics_.sensorsEnabled = false;
  diagnostics_.configFileMajor = 0;
  diagnostics_.configFileMinor = 0;
  diagnostics_.internalStatus = 0;
  effectiveConfig_ = BMI270Profile::EffectiveConfig{};

  if (!BMI270Profile::isSupportedAddress(address()) || !I2CManager::available(busIndex())) {
    fail_(BMI270DeviceStep::ValidateParameters, BMI2_E_INVALID_INPUT);
    return false;
  }

  device_ = bmi2_dev{};
  transport_.attach(device_);

  uint8_t chipId = 0;
  diagnostics_.chipIdRead = transport_.probeChipId(chipId);
  diagnostics_.chipId = chipId;
  diagnostics_.chipIdMatched = diagnostics_.chipIdRead && chipId == BMI270_CHIP_ID;
  if (!diagnostics_.chipIdRead) {
    fail_(BMI270DeviceStep::ProbeChipId, BMI2_E_COM_FAIL);
    return false;
  }
  if (!diagnostics_.chipIdMatched) {
    fail_(BMI270DeviceStep::ProbeChipId, BMI2_E_DEV_NOT_FOUND);
    return false;
  }
  diagnostics_.lastSuccessfulStep = BMI270DeviceStep::ProbeChipId;

  if (!apiStepOk_(BMI270DeviceStep::DriverInitialize, bmi270_init(&device_))) return false;
  diagnostics_.driverInitialized = true;

  if (!apiStepOk_(
          BMI270DeviceStep::ReadConfigVersion,
          bmi2_get_config_file_version(
              &diagnostics_.configFileMajor,
              &diagnostics_.configFileMinor,
              &device_))) {
    return false;
  }

  if (!apiStepOk_(
          BMI270DeviceStep::ReadInternalStatus,
          bmi2_get_internal_status(&diagnostics_.internalStatus, &device_))) {
    return false;
  }
  if (diagnostics_.internalStatus != BMI2_CONFIG_LOAD_SUCCESS) {
    fail_(BMI270DeviceStep::ReadInternalStatus, BMI2_E_CONFIG_LOAD);
    return false;
  }

  return configureOrientation200_();
}

bool BMI270Device::configureOrientation200_() {
  struct bmi2_sens_config config[2] {};
  config[0].type = BMI2_ACCEL;
  config[1].type = BMI2_GYRO;

  diagnostics_.configurationReadAttempted = true;
  if (!apiStepOk_(
          BMI270DeviceStep::ReadConfiguration,
          bmi270_get_sensor_config(config, 2, &device_))) {
    return false;
  }

  config[0].cfg.acc.odr = BMI2_ACC_ODR_200HZ;
  config[0].cfg.acc.range = BMI2_ACC_RANGE_16G;
  config[0].cfg.acc.bwp = BMI2_ACC_NORMAL_AVG4;
  config[0].cfg.acc.filter_perf = BMI2_PERF_OPT_MODE;

  config[1].cfg.gyr.odr = BMI2_GYR_ODR_200HZ;
  config[1].cfg.gyr.range = BMI2_GYR_RANGE_2000;
  config[1].cfg.gyr.bwp = BMI2_GYR_NORMAL_MODE;
  config[1].cfg.gyr.noise_perf = BMI2_POWER_OPT_MODE;
  config[1].cfg.gyr.filter_perf = BMI2_PERF_OPT_MODE;

  diagnostics_.configurationWriteAttempted = true;
  if (!apiStepOk_(
          BMI270DeviceStep::WriteConfiguration,
          bmi270_set_sensor_config(config, 2, &device_))) {
    return false;
  }
  diagnostics_.configurationWriteOk = true;

  int8_t result = bmi2_set_accel_offset_comp(BMI2_DISABLE, &device_);
  if (result == BMI2_OK) result = bmi2_set_gyro_offset_comp(BMI2_DISABLE, &device_);
  if (!apiStepOk_(BMI270DeviceStep::DisableOffsetCompensation, result)) return false;
  diagnostics_.offsetCompensationDisabled = true;

  if (!enableSensors_(BMI270DeviceStep::EnableSensors)) return false;
  if (!configureGyroBiasCorrection_()) return false;

  struct bmi2_sens_config effective[2] {};
  effective[0].type = BMI2_ACCEL;
  effective[1].type = BMI2_GYRO;
  if (!apiStepOk_(
          BMI270DeviceStep::VerifyConfiguration,
          bmi270_get_sensor_config(effective, 2, &device_))) {
    return false;
  }
  diagnostics_.configurationReadOk = true;
  copyEffectiveConfig_(effective, effectiveConfig_);
  diagnostics_.configurationMatched =
      BMI270Profile::matchesOrientation200(effectiveConfig_);
  if (!diagnostics_.configurationMatched) {
    fail_(BMI270DeviceStep::VerifyConfiguration, BMI2_E_INVALID_STATUS);
    return false;
  }

  diagnostics_.lastSuccessfulStep = BMI270DeviceStep::VerifyConfiguration;
  diagnostics_.failureStep = BMI270DeviceStep::None;
  diagnostics_.lastApiResult = BMI2_OK;
  return true;
}

bool BMI270Device::configureGyroBiasCorrection_() {
  const uint8_t selfOffsetFeature[] = { BMI2_GYRO_SELF_OFF };
  const bool enable = gyroBiasMode_ == BMI270GyroBiasMode::InUseOffsetCorrection;
  int8_t result = bmi2_set_gyro_offset_comp(enable ? BMI2_ENABLE : BMI2_DISABLE, &device_);
  if (result == BMI2_OK) {
    result = enable
        ? bmi270_sensor_enable(selfOffsetFeature, 1, &device_)
        : bmi270_sensor_disable(selfOffsetFeature, 1, &device_);
  }
  if (!apiStepOk_(BMI270DeviceStep::ConfigureGyroBiasCorrection, result)) return false;
  diagnostics_.gyroOffsetCompensationEnabled = enable;
  diagnostics_.gyroSelfOffsetCorrectionEnabled = enable;
  return true;
}

bool BMI270Device::readGyroOffsetCompensationAxes(struct bmi2_sens_axes_data& out) {
  const int8_t result = bmi2_read_gyro_offset_comp_axes(&out, &device_);
  diagnostics_.lastApiResult = result;
  return result == BMI2_OK;
}

bool BMI270Device::disableSensors_(BMI270DeviceStep step) {
  const int8_t result =
      bmi270_sensor_disable(kEnabledSensors, kEnabledSensorCount, &device_);
  if (!apiStepOk_(step, result)) return false;
  diagnostics_.sensorsEnabled = false;
  return true;
}

bool BMI270Device::enableSensors_(BMI270DeviceStep step) {
  const int8_t result =
      bmi270_sensor_enable(kEnabledSensors, kEnabledSensorCount, &device_);
  if (!apiStepOk_(step, result)) return false;
  diagnostics_.sensorsEnabled = true;
  return true;
}

void BMI270Device::quiesceAfterFailedInitialization_() {
  if (!diagnostics_.driverInitialized) return;

  const BMI270DeviceStep originalFailureStep = diagnostics_.failureStep;
  const int8_t originalApiResult = diagnostics_.lastApiResult;
  diagnostics_.failureCleanupAttempted = true;

  const int8_t result =
      bmi270_sensor_disable(kEnabledSensors, kEnabledSensorCount, &device_);
  diagnostics_.failureCleanupOk = result == BMI2_OK;
  if (diagnostics_.failureCleanupOk) diagnostics_.sensorsEnabled = false;

  // Cleanup diagnostics are separate: preserve the operation that caused the
  // initialization failure so a later caller can diagnose the primary fault.
  diagnostics_.failureStep = originalFailureStep;
  diagnostics_.lastApiResult = originalApiResult;
}

bool BMI270Device::apiStepOk_(BMI270DeviceStep step, int8_t result) {
  if (result != BMI2_OK) {
    fail_(step, result);
    return false;
  }
  diagnostics_.lastSuccessfulStep = step;
  diagnostics_.lastApiResult = result;
  return true;
}

void BMI270Device::fail_(BMI270DeviceStep step, int8_t result) {
  diagnostics_.failureStep = step;
  diagnostics_.lastApiResult = result;
}

void BMI270Device::setState_(BMI270DeviceState state) {
  diagnostics_.state = state;
}
