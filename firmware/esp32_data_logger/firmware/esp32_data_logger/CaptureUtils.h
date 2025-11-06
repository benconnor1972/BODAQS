// CaptureUtils.h
#pragma once
#include <stdint.h>

// Called by the wizard when user presses Mark.
// Should sample the target sensor for avg_ms and return the averaged RAW.
// If you’re logging, you may read the latest RAWs from a ring buffer;
// or temporarily poll readRaw() in a tight loop with delay(0) yielding.
// Set *out_n to the number of samples included in the average.
float captureAverageRAW(uint16_t avg_ms, uint16_t* out_n);
