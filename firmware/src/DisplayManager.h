#pragma once
#include <Arduino.h>
#include <Wire.h>
#include "BoardProfile.h" 

struct LoggerConfig; // fwd declare
enum class OledLoggingPolicy : uint8_t;

namespace DisplayManager {
  struct Diagnostics {
    uint32_t deferredPresentRequests = 0;
    uint32_t mutexDeferrals = 0;
    uint32_t schedulerWindowDeferrals = 0;
    uint32_t deferredRefreshesScheduled = 0;
    uint32_t loggingTransfersCompleted = 0;
    uint32_t loggingSuppressionsWarmup = 0;
    uint32_t loggingSuppressionsPolicy = 0;
    uint32_t loggingSuppressionsLoad = 0;
    uint32_t loggingSuppressionsRecentMiss = 0;
    uint32_t loggingSuppressionsInterval = 0;
    uint32_t loggingSuppressionsWindow = 0;
    uint32_t loggingNormalMs = 0;
    uint32_t loggingThrottledMs = 0;
    uint32_t loggingFrozenMs = 0;
    uint32_t loggingLoadSamples = 0;
    uint32_t loggingLoadTotalPermille = 0;
    uint16_t loggingLoadMaximumPermille = 0;
    uint8_t loggingPolicy = 0;
    uint8_t loggingState = 0;
    uint8_t transferDeferralDepth = 0;
  };

  // Initializes I2C + OLED using cfg; safe to call even if no OLED present.
  bool begin(const LoggerConfig& cfg, const board::DisplayProfile& disp, TwoWire* wire);

  // Call in loop() (non-blocking)
  void loop();

  // Quick, single-line status (sticky, top of screen)
  void setStatusLine(const String& line);

  void setFooterLine(const String& line);   // bottom row (e.g., clock)

  // Transient message (bottom of screen), auto-expires
  void toast(const String& text, uint16_t durationMs = 1500, uint8_t textSize = 2);
  void toastSequence(const String& first, const String& second,
                     uint16_t durationMs = 1500, uint8_t firstSize = 2,
                     uint8_t secondSize = 1);
  void prepareLoggingScreen(uint16_t loggerRateHz, uint8_t activeSensors);

  // Optional helpers
  bool available();
  void clear();
  void drawText(int16_t x, int16_t y, const String& s, uint8_t size = 1);
  void setBrightness(uint8_t b); // 0..255 (mapped to contrast)
  void setLoggingPolicy(OledLoggingPolicy policy);
  void present();

  // Temporarily defer physical OLED transfers while another device performs a
  // bus-intensive operation. Drawing may continue into the framebuffer; the
  // next complete frame is sent from the normal UI loop after the matching
  // resume call. Returns true only when this display shares busIndex.
  bool deferTransfersForBus(uint8_t busIndex);
  void resumeTransfersForBus(uint8_t busIndex);
  Diagnostics diagnostics();

}
