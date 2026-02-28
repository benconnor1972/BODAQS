#pragma once
#include <Arduino.h>

class Sensor;        // fwd
#include "Calibration.h"  // for CalMode in case you want to extend later

// Average RAW counts over a small time window.
// Returns the average (int32), or 0 if sensor can't provide raw counts.
int32_t sampleAverageCounts(Sensor* s, uint16_t windowMs = 100, uint16_t minSamples = 5);

// Two-point RANGE helper: capture start & finish snapshots (with averaging).
struct RangeCapture {
  int32_t start = 0;
  int32_t finish = 0;
  bool    haveStart = false;
  bool    haveFinish = false;

  void    reset() { start = finish = 0; haveStart = haveFinish = false; }

  // Captures averaged start (returns true if captured)
  bool captureStart(Sensor* s, uint16_t windowMs = 100, uint16_t minSamples = 5);

  // Captures averaged finish (returns true if captured)
  bool captureFinish(Sensor* s, uint16_t windowMs = 100, uint16_t minSamples = 5);

  bool valid()     const { return haveStart && haveFinish && (finish != start); }
  bool inverted()  const { return haveStart && haveFinish && (finish < start); }
};
