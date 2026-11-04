#pragma once
#include "ConfigManager.h"

// Synchronous idle editor. Existing ParamPacks alias shared storage; retain all
// saved sensor state until persistence succeeds. Never retain across loop turns.
class SensorConfigEdit {
public:
  enum class Result { Applied, Locked, Invalid, SaveFailed, SavedNotApplied };
  SensorConfigEdit();
  ~SensorConfigEdit();
  SensorConfigEdit(const SensorConfigEdit&) = delete;
  SensorConfigEdit& operator=(const SensorConfigEdit&) = delete;
  static bool isLegacyRemoteImu(const SensorSpec& spec);
  // Explicit selection only; caller owns this edit and commits through commit().
  static bool migrateLegacyRemoteImu(SensorSpec& spec, const char* type,
      const char* profile, char* error, size_t capacity);
  bool ready() const { return state_ != nullptr; }
  Result commit(const LoggerConfig& config, char* error, size_t capacity);
private:
  void restoreLocalRuntimeMutes_();
  struct State;
  State* state_ = nullptr;
  bool saved_ = false;
};
