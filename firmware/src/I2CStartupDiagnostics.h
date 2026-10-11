#pragma once

namespace I2CStartupDiagnostics {
// Called once at the end of setup, before UI callbacks or acquisition run.
// Ordinary builds perform one delayed retry; diagnostic builds also probe,
// reset affected controllers and test 100 kHz, restoring normal clocks.
void run();
}
