#pragma once
#include "BoardProfile.h"
#include "SensorTypes.h"

// Normalized physical assignment; logical AIN aliases resolve to GPIO or ADC.
struct SensorAssignment {
  enum class Kind : uint8_t { None, I2C, Gpio, ExternalAdc, Uart };
  Kind kind = Kind::None;
  int16_t bus = -1;
  int16_t input = -1;
  int16_t negativeInput = -1;
  bool operator==(const SensorAssignment& other) const {
    return kind == other.kind && bus == other.bus && input == other.input &&
           negativeInput == other.negativeInput;
  }
};

SensorAssignment sensorAssignment(const SensorSpec& spec, const board::BoardProfile* board);
bool assignmentsConflict(const SensorAssignment& a, const SensorAssignment& b);
const char* assignmentOwner(const SensorAssignment& assignment, const board::BoardProfile* board);
