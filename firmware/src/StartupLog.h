#pragma once

namespace StartupLog {
// Capture begins after configuration load and ends after startup recovery.
// Disabled capture allocates nothing. All SD work is deferred until finish().
bool begin(bool enabled);
bool active();
void recordf(const char* format, ...) __attribute__((format(printf, 1, 2)));
void printf(const char* format, ...) __attribute__((format(printf, 1, 2)));
void println(const char* text);
void setFinalReadiness(unsigned checked, unsigned failed);
void finish();
}
