#include "CalCapture.h"
#include "Sensor.h"

int32_t sampleAverageCounts(Sensor* s, uint16_t windowMs, uint16_t minSamples) {
  if (!s || !s->hasRawCounts()) return 0;

  const unsigned long until = millis() + windowMs;
  int64_t sum = 0;
  uint32_t n = 0;

  while ((long)(until - millis()) > 0) {
    sum += (int32_t)s->currentRawCounts();
    ++n;
    delay(1); // yield
  }
  if (n < minSamples) {
    // take a few extra samples to meet minSamples
    while (n < minSamples) {
      sum += (int32_t)s->currentRawCounts();
      ++n;
      delay(1);
    }
  }
  return (int32_t)(sum / (int64_t)n);
}

bool RangeCapture::captureStart(Sensor* s, uint16_t windowMs, uint16_t minSamples) {
  if (!s || !s->hasRawCounts()) return false;
  start = sampleAverageCounts(s, windowMs, minSamples);
  haveStart = true;
  return true;
}

bool RangeCapture::captureFinish(Sensor* s, uint16_t windowMs, uint16_t minSamples) {
  if (!s || !s->hasRawCounts()) return false;
  finish = sampleAverageCounts(s, windowMs, minSamples);
  haveFinish = true;
  return true;
}
