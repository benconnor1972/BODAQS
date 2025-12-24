#pragma once
#include <Arduino.h>
#include "BoardProfile.h" 

struct LoggerConfig; // fwd declare

namespace DisplayManager {
  // Initializes I2C + OLED using cfg; safe to call even if no OLED present.
  bool begin(const LoggerConfig& cfg, const board::DisplayProfile& disp, const board::I2CProfile& i2c);

  // Call in loop() (non-blocking)
  void loop();

  // Quick, single-line status (sticky, top of screen)
  void setStatusLine(const String& line);

  void setFooterLine(const String& line);   // bottom row (e.g., clock)

  // Transient message (bottom of screen), auto-expires
  void toast(const String& text, uint16_t durationMs = 1500);

  // Optional helpers
  bool available();
  void clear();
  void drawText(int16_t x, int16_t y, const String& s, uint8_t size = 1);
  void setBrightness(uint8_t b); // 0..255 (mapped to contrast)
  void present();

}
