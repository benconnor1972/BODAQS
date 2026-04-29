#ifndef SENSORS_SENSOR_MANAGER_H
#define SENSORS_SENSOR_MANAGER_H

#include <Arduino.h>
#include "Sensor.h"

struct LoggerConfig;

namespace SensorManager {
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
  void buildHeader(char* out, size_t n, bool humanTs);
  void sampleValues(float* out, uint16_t maxOut, uint16_t& written);
  uint16_t describeSensorColumns(SensorColumnDescriptor* out, uint16_t maxOut);
  uint16_t describeSensors(SensorMetadataDescriptor* out, uint16_t maxOut);
  uint16_t describeSensorColumnRawFlags(bool* out, uint16_t maxOut);

  // debug
  void debugDump(const char* tag);
  void debugDumpColumnMetadata(const char* tag);
};

#endif // SENSORS_SENSOR_MANAGER_H
