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

  // debug
  void debugDump(const char* tag);
};

#endif // SENSORS_SENSOR_MANAGER_H
