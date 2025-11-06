// SensorWarnings.h (or similar)
#pragma once
#include <stdint.h>
static constexpr uint32_t WARN_INPUT_UNITS_MISMATCH  = 1u << 0;
static constexpr uint32_t WARN_OUTPUT_UNITS_MISMATCH = 1u << 1;
static constexpr uint32_t WARN_SCALE_INVALID         = 1u << 2;
