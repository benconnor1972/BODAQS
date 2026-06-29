#ifndef SENSORS_SENSOR_MANAGER_H
#define SENSORS_SENSOR_MANAGER_H

#include <Arduino.h>
#include "Sensor.h"

struct LoggerConfig;

namespace SensorManager {
  struct SynBikeRawColumnBinding {
    bool available = false;
    uint16_t valueIndex = 0;
    bool invert = false;
    char sensorName[16] = {0};
    char csvHeader[96] = {0};
    char end[16] = {0};
    char domain[24] = {0};
    char source[24] = {0};
  };

  struct SynBikeRawBindings {
    SynBikeRawColumnBinding front;
    SynBikeRawColumnBinding rear;
  };

  struct PreviewValue {
    char sensorName[16] = {0};
    char unit[24] = {0};
    float value = 0.0f;
  };

  enum class PreviewMode : uint8_t {
    Raw,
    Linear,
    SagPercent
  };

  // lifecycle
  void begin(const LoggerConfig* cfg);
  void buildSensorsFromConfig(const LoggerConfig& cfg);
  void finalizeBegin();
  void applyConfig(const LoggerConfig& cfg);
  void loop();
  void onLoggingStart();
  void onLoggingStop();

  // registry / access
  void    registerSensor(Sensor* s);
  uint8_t count();
  uint8_t activeCount();
  Sensor* at(uint8_t i);     // alias to get(i)
  Sensor* get(uint8_t i);

  // per-sensor state
  bool getMuted(uint8_t index, bool& outMuted); // false if out of range
  bool setMuted(uint8_t index, bool muted);     // false if out of range

  // CSV / sampling
  uint16_t dynamicColumnCount();
  uint16_t synchronousMaxSampleRateHz();
  void buildHeader(char* out, size_t n, bool humanTs);
  String buildHeaderString(bool humanTs);
  void sampleValues(float* out, uint16_t maxOut, uint16_t& written);
  uint16_t describeSensorColumns(SensorColumnDescriptor* out, uint16_t maxOut);
  bool describeSensorColumnAt(uint16_t columnIndex, SensorColumnDescriptor& out);
  uint16_t describeSensors(SensorMetadataDescriptor* out, uint16_t maxOut);
  uint16_t describeSensorColumnRawFlags(bool* out, uint16_t maxOut);
  uint16_t readSuspensionPreview(PreviewMode mode, PreviewValue* out, uint16_t maxOut);
  bool resolveSynBikeRawBindings(SynBikeRawBindings& out);
  bool gpsStatus(SensorGpsStatus& out);

  // debug
  void debugDump(const char* tag);
  void debugDumpColumnMetadata(const char* tag);
};

#endif // SENSORS_SENSOR_MANAGER_H
