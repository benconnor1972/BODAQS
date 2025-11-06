#include "CaptureUtils.h"
#include <Arduino.h>

// TEMP STUB: replace /* readRaw() */ with actual sensor access
float captureAverageRAW(uint16_t avg_ms, uint16_t* out_n) {
  uint32_t start = millis();
  uint32_t count = 0;
  double sum = 0.0;

  while (millis() - start < avg_ms) {
    // TODO: pull from your Sensor instance instead of returning 0
    float r = 0.0f;  // dummy raw sample
    sum += r;
    count++;
    delay(0); // yield to Wi-Fi/task watchdog
  }

  if (out_n) *out_n = count;
  return (count > 0) ? (float)(sum / count) : 0.0f;
}
