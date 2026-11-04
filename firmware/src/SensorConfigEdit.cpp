#include "SensorConfigEdit.h"
#include "SensorManager.h"
#include "SensorRegistry.h"
#include "SensorAssignment.h"
#include "BMI270ImuSensor.h"
#include "Lsm6dso32xConfig.h"
#include "CanMasterManager.h"
#include "BoardSelect.h"
#include "LoggingManager.h"
#include "UploadModeManager.h"
#include "AnalogInputManager.h"
#include "StorageManager.h"
#include <cmath>
#include <stdlib.h>
#include <strings.h>

bool SensorConfigEdit::isLegacyRemoteImu(const SensorSpec& spec) {
  return spec.type == SensorType::BMI270ImuI2C &&
      sensorAssignment(spec, nullptr).provider.kind == SensorProviderKind::CanNode;
}

bool SensorConfigEdit::migrateLegacyRemoteImu(SensorSpec& spec, const char* type,
    const char* profile, char* error, size_t capacity) {
  if (!isLegacyRemoteImu(spec) || !type || strcmp(type, "lsm6dso32x_imu") ||
      !profile || strcmp(profile, Lsm6dso32xConfig::profile)) {
    snprintf(error, capacity, "Select lsm6dso32x_imu and its supported LSM profile for a legacy remote BMI270 assignment");
    return false;
  }
  // Keep saved identity, calibration, mounting and assignment data. Retained
  // legacy acquisition keys are opaque: only the selected LSM profile is used.
  if (!spec.params.set("profile", profile)) {
    snprintf(error, capacity, "Could not store migration profile");
    return false;
  }
  spec.type = SensorType::LSM6DSO32XImu;
  return Lsm6dso32xConfig::validateSpec(spec, error, capacity);
}

namespace {
bool validateSensorEdit_(const LoggerConfig& cfg, char* error, size_t capacity) {
  for (uint8_t i = 0; i < cfg.sensorCount(); ++i) {
    SensorSpec spec;
    if (!cfg.getSensorSpec(i, spec)) return false;
    const SensorTypeInfo* type = SensorRegistry::lookup(spec.type);
    if (!type || !spec.name[0] || strpbrk(spec.name, "\r\n")) {
      snprintf(error, capacity, "Invalid sensor type or name");
      return false;
    }
    for (uint8_t k = 0; k < spec.params.size(); ++k) {
      const char* key = spec.params.keyAt(k);
      const char* value = spec.params.valueAt(k);
      if (!key || !value || strpbrk(key, "\r\n=") || strpbrk(value, "\r\n")) {
        snprintf(error, capacity, "Invalid flat-file sensor parameter");
        return false;
      }
    }
    String provider;
    spec.params.get("provider", provider);
    const auto assignment = sensorAssignment(spec, board::gBoard);
    if (provider.length() && !provider.equalsIgnoreCase("local") &&
        (assignment.provider.kind != SensorProviderKind::CanNode ||
         assignment.kind == SensorAssignment::Kind::None)) {
      snprintf(error, capacity, "Invalid sensor provider or endpoint");
      return false;
    }
    if (spec.type == SensorType::BMI270ImuI2C &&
        assignment.provider.kind == SensorProviderKind::CanNode) continue;
    if (spec.type == SensorType::LSM6DSO32XImu &&
        !Lsm6dso32xConfig::validateSpec(spec,error,capacity)) return false;
    size_t count = 0;
    const ParamDef* defs = type->paramDefs(count);
    for (size_t d = 0; defs && d < count; ++d) {
      const ParamDef& def = defs[d];
      String value;
      if (!spec.params.get(def.key, value)) continue;
      if (!value.length() && def.def && !*def.def) continue;
      if (def.type == ParamType::Bool) {
        bool parsed;
        if (!ConfigManager::parseBool(value, parsed)) {
          snprintf(error, capacity, "Invalid %s for %s", def.key, spec.name);
          return false;
        }
      }
      if (def.type == ParamType::Enum && def.choices && strcasecmp(def.key, "output_mode")) {
        bool matched = false;
        const char* choice = def.choices;
        while (*choice) {
          const char* end = strchr(choice, ',');
          const size_t length = end ? size_t(end - choice) : strlen(choice);
          if (value.length() == length && !strncasecmp(choice, value.c_str(), length)) matched = true;
          if (!end) break;
          choice = end + 1;
        }
        if (!matched) {
          snprintf(error, capacity, "Invalid %s for %s", def.key, spec.name);
          return false;
        }
      }
      if (def.type == ParamType::Int || def.type == ParamType::Float) {
        char* end = nullptr;
        const double number = def.type == ParamType::Int
            ? double(strtol(value.c_str(), &end, 10)) : strtod(value.c_str(), &end);
        if (end == value.c_str() || *end || !std::isfinite(number) ||
            (def.minv && number < strtod(def.minv, nullptr)) ||
            (def.maxv && number > strtod(def.maxv, nullptr))) {
          snprintf(error, capacity, "Invalid %s for %s", def.key, spec.name);
          return false;
        }
      }
    }
    // Remote legacy BMI placeholders remain saved and unresolved. Their
    // profiles are not local BMI register settings.
    if (spec.type == SensorType::BMI270ImuI2C &&
        assignment.provider.kind == SensorProviderKind::Local &&
        !BMI270ImuSensor::validateSpec(spec, error, capacity)) return false;
  }
  return true;
}
}

SensorConfigEdit::Result SensorConfigEdit::commit(
    const LoggerConfig& config, char* error, size_t capacity) {
  if (error && capacity) error[0] = '\0';
  if (!ready() || LoggingManager::configurationLocked() || UploadModeManager::isActive()) {
    snprintf(error, capacity, "Configuration edit unavailable while recording/uploading or out of memory");
    return Result::Locked;
  }
  if (!validateSensorEdit_(config, error, capacity)) return Result::Invalid;
  if (!ConfigManager::save(config)) {
    snprintf(error, capacity, "Failed to save sensor configuration");
    return Result::SaveFailed;
  }
  saved_ = true;
  const LoggerConfig& saved = ConfigManager::get();
  if (!SensorManager::rebuildFromConfig(saved, error, capacity)) return Result::SavedNotApplied;
  restoreLocalRuntimeMutes_();
  CanMasterManager::scheduleConfigurationReconciliation();
  const uint16_t rate = AnalogInputManager::configureFromConfig(saved, saved.sampleRateHz);
  StorageManager_setSampleRate(rate);
  LoggingManager::refreshConfigurationStatus();
  return Result::Applied;
}
