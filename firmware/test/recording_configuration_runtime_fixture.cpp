#include "Arduino.h"
#include "Sensor.h"
#include "SensorAssignment.h"
#include "Calibration.h"
#include "RawAdcRecording.h"
#include <assert.h>
#include <string>
#include <stdio.h>
#include <math.h>

class JsonOutput {
public:
  std::string text;
  JsonOutput& operator+=(const char* value) { text += value; return *this; }
  JsonOutput& operator+=(char value) { text += value; return *this; }
};
struct LoggerConfig {
  uint16_t sampleRateHz = 1000;
  SensorSpec sensors[2];
  uint8_t sensorCount() const { return 2; }
  bool getSensorSpec(uint8_t index, SensorSpec& out) const { out = sensors[index]; return true; }
};
namespace board { const BoardProfile* gBoard = nullptr; }
SensorAssignment sensorAssignment(const SensorSpec&, const board::BoardProfile*) {
  SensorAssignment result;
  result.kind = SensorAssignment::Kind::ExternalAdc;
  result.bus = 1; result.input = 2;
  return result;
}
static bool stringMode=false;
namespace SensorRegistry { const char* typeKey(SensorType type) { return type==SensorType::AS5600StringPotAnalog?"as5600_string_pot_analog":"analog_pot"; } }
struct ConfigManager {
  static bool loadCalibrationByIndex(uint8_t, Calibration& out) {
    out.ts_epoch_ms = 123456789;
    out.r0_raw = NAN; // unavailable numeric evidence must remain valid JSON
    return true;
  }
};
namespace SensorManager {
uint16_t describeSensors(SensorMetadataDescriptor*, uint16_t) { return 2; }
bool describeSensorAt(uint16_t i, SensorMetadataDescriptor& out) {
  snprintf(out.name, sizeof(out.name), "%s", i ? "uncalibrated" : "pot\"one");
  out.hasCalibration = i == 0;
  snprintf(out.calibrationOutputUnit, sizeof(out.calibrationOutputUnit), "mm");
  out.installedZeroCount = 100;
  out.sensorZeroCount = 100; out.sensorFullCount = 1100; out.sensorFullTravel = 100;
  return true;
}
uint16_t describeSensorColumns(SensorColumnDescriptor*, uint16_t, bool) { return stringMode?0:1; }
bool describeSensorColumnAt(uint16_t, SensorColumnDescriptor& out, bool) {
  snprintf(out.sensorName, sizeof(out.sensorName), "pot\"one");
  snprintf(out.columnId, sizeof(out.columnId), "pot_raw");
  out.raw = true;
  return true;
}
}
// PRODUCTION_JSON
int main(int argc,char**) {
  stringMode=argc>1;
  uint16_t status = 0;
  assert(RawAdcRecording::count(-1, status) == 0 && (status & 0x20));
  status = 0;
  assert(RawAdcRecording::count(4095, status) == 4095 && !status);
  assert(RawAdcRecording::count(5000, status) == 4095 && (status & 0x20));
  LoggerConfig config;
  ParamStore parameters;
  parameters.set("note", "contains \"quotes\" and \\slashes");
  snprintf(config.sensors[0].name, sizeof(config.sensors[0].name), "pot\"one");
  snprintf(config.sensors[1].name, sizeof(config.sensors[1].name), "uncalibrated");
  config.sensors[0].type = config.sensors[1].type = SensorType::AnalogPot;
  if(stringMode) config.sensors[0].type=SensorType::AS5600StringPotAnalog;
  config.sensors[0].params.bind(&parameters);
  JsonOutput output;
  output += '{';
  appendRecordingConfiguration_(output, config, false);
  output += '}';
  puts(output.text.c_str());
}
