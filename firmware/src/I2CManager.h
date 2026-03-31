#pragma once

#include <stdint.h>
#include <Wire.h>
#include "BoardProfile.h"

namespace I2CManager {

void begin(const board::BoardProfile& bp);
bool available(uint8_t busIndex);
TwoWire* bus(uint8_t busIndex);
const board::I2CProfile* profile(uint8_t busIndex);
bool lock(TwoWire* wire, uint32_t timeoutMs = 50);
void unlock(TwoWire* wire);

} // namespace I2CManager
