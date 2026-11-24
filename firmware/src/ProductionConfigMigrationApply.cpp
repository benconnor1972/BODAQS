#include "ProductionConfigMigrationApply.h"
#include "ConfigManager.h"
#include "SensorManager.h"
#include "AnalogInputManager.h"
#include "StorageManager.h"
#include "LoggingManager.h"
#include <stdio.h>

ProductionConfigMigrationApply::Result ProductionConfigMigrationApply::accept(
    const char* revision, char* error, size_t capacity) {
  const auto accepted=ConfigManager::acceptMigrationConfiguration(revision,error,capacity);
  if(accepted==ConfigManager::MigrationAcceptance::Rejected) return Result::Rejected;

  // A successful disk write is reported truthfully even if reload/application
  // fails or ownership changes before the runtime can be rebuilt.
  bool applied=false;
  if(accepted==ConfigManager::MigrationAcceptance::Loaded) {
    if(!ConfigManager::configurationMutable()) {
      if(error && capacity) snprintf(error,capacity,"Migration saved; configuration ownership changed before application");
    } else {
      applied=SensorManager::rebuildFromConfig(ConfigManager::get(),error,capacity);
      if(applied) {
        const auto& config=ConfigManager::get();
        StorageManager_setSampleRate(AnalogInputManager::configureFromConfig(config,config.sampleRateHz));
      }
    }
  }
  LoggingManager::refreshConfigurationStatus();
  return applied?Result::Applied:Result::SavedNotApplied;
}
