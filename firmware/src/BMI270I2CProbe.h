#pragma once

struct LoggerConfig;

namespace BMI270I2CProbe {
// Diagnostic builds only: read CHIP_ID after normal startup, without resetting
// devices or attempting recovery. Normal firmware does not call this module.
void run(const LoggerConfig& config);
}
