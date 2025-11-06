#pragma once
#include <Arduino.h>
struct LoggerConfig;
extern String s_lastWifiSummary;


namespace UI {
  enum Target : uint8_t {
    TARGET_DEFAULT = 0,   // use config
    TARGET_SERIAL  = 1,
    TARGET_OLED    = 2,
    TARGET_BOTH    = 3
  };
  enum Level : uint8_t {
    LVL_ERROR = 1, LVL_WARN = 2, LVL_INFO = 3, LVL_DEBUG = 4
  };

  void begin(const LoggerConfig& cfg);      // call after Config loaded + DisplayManager::begin()
  void configure(const LoggerConfig& cfg);  // re-apply if cfg changes
  void loop();                              // calls DisplayManager::loop()

  // Route one message. Provide verbose serial text + (optional) short OLED text.
  void println(const String& serialText, const String& oledText = "", uint8_t targets = TARGET_DEFAULT, uint8_t level   = LVL_INFO, uint16_t oledToastMs = 2000);

  void oledText(int16_t x, int16_t y, const String& text); //print at an x,y location

  // Sticky, single-line status on OLED top area
  void status(const String& line);

  // Quick toast on OLED bottom
  void toast(const String& oledText, uint16_t durationMs = 1500);
  void clear(uint8_t target = TARGET_OLED);
  void toastModal(const String& text, uint16_t durationMs = 1200);

    // Modal guards (menu owns the OLED while modal is true)
  void beginModal();
  void endModal();
  bool isModal();

}
