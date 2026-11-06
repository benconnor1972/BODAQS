#pragma once
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
#include "BoardProfile.h"
namespace SpiMeasurementProbe {
// Bench entry: owns RAM config, ADC workers and serial, never normal managers.
void begin(const board::BoardProfile& board);
void loop();
// Same public command seam as newline serial input; input need not be mutable.
void command(const char* line);
}
#endif
