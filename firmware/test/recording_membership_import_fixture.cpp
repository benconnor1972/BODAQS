#include "Arduino.h"
#include "Sensor.h"
#include "SensorTypes.h"
#include "RecordingReadiness.h"
#include <ArduinoJson.h>
#include <cstdio>
#include <string>

// Model configuration and control state only. Both JSON serializers below are
// extracted unchanged from production; no hardware acquisition runs on the host.
class JsonOutput {
public:
  std::string text;
  JsonOutput& operator+=(const char* value) { text += value; return *this; }
  JsonOutput& operator+=(char value) { text += value; return *this; }
};
struct LoggerConfig {
  bool recordingBestEffort = true;
  SensorSpec sensors[3];
  uint8_t sensorCount() const { return 3; }
  bool getSensorSpec(uint8_t index, SensorSpec& out) const { out = sensors[index]; return true; }
};
struct ConfigManager {
  inline static LoggerConfig config;
  static const LoggerConfig& get() { return config; }
};
namespace SensorRegistry {
  const char* typeKey(SensorType type) {
    return type == SensorType::AnalogPot ? "analog_pot" : "lsm6dso32x_imu";
  }
}
namespace LoggingManager {
  bool running = false;
  bool isRunning() { return running; }
  bool configurationLocked() { return running; }
}
namespace RecordingReadiness {
  Observation declared;
  const Observation& session() { return declared; }
  const char* reason(const Observation& value) { return RecordingAdmission::blockerText(value.decision.blocker); }
}
// PRODUCTION_JSON
// PRODUCTION_API

int main() {
  auto& config = ConfigManager::config;
  std::snprintf(config.sensors[0].name, sizeof config.sensors[0].name, "travel");
  std::snprintf(config.sensors[1].name, sizeof config.sensors[1].name, "imu_late_loss");
  std::snprintf(config.sensors[2].name, sizeof config.sensors[2].name, "imu\"absent");
  config.sensors[0].type = SensorType::AnalogPot;
  config.sensors[1].type = SensorType::LSM6DSO32XImu;
  config.sensors[2].type = SensorType::LSM6DSO32XImu;
  RecordingAdmission::Inputs inputs;
  inputs.requested = 7; inputs.available = 3;
  inputs.bestEffort = true; inputs.candidateBuild = true;
  auto& observation = RecordingReadiness::declared;
  observation.unavailable = 4;
  observation.decision = RecordingAdmission::decide(inputs);
  JsonOutput header;
  header += '{';
  appendRecordingMembership_(header, config);
  header += "\"fixture_end\":true}";
  std::puts(header.text.c_str());

  JsonDocument status;
  auto cases = status["cases"].to<JsonArray>();
  addRecordingReadinessJson_(cases.add<JsonObject>(), observation); // idle
  LoggingManager::running = true;
  addRecordingReadinessJson_(cases.add<JsonObject>(), observation); // running alone
  inputs.reservation = RecordingAdmission::Reservation::Acquired;
  observation.reservation = inputs.reservation;
  observation.decision = RecordingAdmission::decide(inputs);
  LoggingManager::running = false;
  addRecordingReadinessJson_(cases.add<JsonObject>(), observation); // reserved alone
  LoggingManager::running = true;
  addRecordingReadinessJson_(cases.add<JsonObject>(), observation); // acquisition ready
  std::string serialized;
  serializeJson(status, serialized);
  std::puts(serialized.c_str());
}
