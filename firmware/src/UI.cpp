#include "UI.h"
#include "DisplayManager.h"
#include "ConfigManager.h"
#include "MenuSystem.h"
#include "WiFiManager.h"
#include "PowerManager.h"
#include "StorageManager.h"
#include "SensorManager.h"
#include "DebugLog.h"
#include <WiFi.h>   // for WiFi.SSID() and WiFi.localIP()
#include <time.h>

static LogLevel uiLevelToLogLevel_(uint8_t level) {
  switch (level) {
    case UI::LVL_ERROR: return LOG_ERROR;
    case UI::LVL_WARN:  return LOG_WARN;
    case UI::LVL_INFO:  return LOG_INFO;
    case UI::LVL_DEBUG: return LOG_DEBUG;
    default:            return LOG_INFO;
  }
}

static uint8_t s_target       = UI::TARGET_SERIAL; // 1=serial,2=oled,3=both
static uint8_t s_serialLevel  = UI::LVL_INFO;      // only print if cfg level >= msg level
static uint8_t s_oledLevel    = UI::LVL_INFO;

static uint32_t s_nextWifiUiCheckMs = 0;
String   s_lastWifiSummary;

static String makeWifiSummary_() {
  auto st = WiFiManager::status();

  if (st.networkUp) {
    // Build the two strings we want to alternate between.
    String ssid = st.ssid.length() ? st.ssid : WiFiManager::networkName();
    if (!ssid.length()) ssid = "(connected)";

    String ip = st.ip.length() ? st.ip : WiFiManager::localAddress().toString();
    if (!ip.length() || ip == "0.0.0.0") ip = "(no ip)";

    const String a = (st.mode == WiFiMode::AccessPoint) ? ("AP: " + ssid) : ("WiFi: " + ssid);
    const String b = "IP: "   + ip;

    // Alternate once per second. Since UI::loop() already runs at 1 Hz,
    // this will flip each time UI::loop() refreshes the status.
    const bool showIp = ((millis() / 1000) & 0x1) != 0;
    return showIp ? b : a;
  }

  // Otherwise reflect state machine
  switch (st.state) {
    case WiFiMgrState::OFF:        return "WiFi: off";
    case WiFiMgrState::IDLE:       return "WiFi: idle";
    case WiFiMgrState::SCANNING:
    case WiFiMgrState::CONNECTING: return "WiFi: connecting";
    case WiFiMgrState::ONLINE:     return "WiFi: (up)";
    case WiFiMgrState::AP_ONLINE:  return "AP: (up)";
  }
  return "WiFi: ?";
}

static bool makeLowBatteryWarning_(String& out) {
  if (!PowerManager::fuelGaugeOk()) {
    out = "";
    return false;
  }

  if (!PowerManager::batteryLow()) {
    out = "";
    return false;
  }

  const float vbat = PowerManager::batteryVoltage();
  char buf[24];
  snprintf(buf, sizeof(buf), "LOW BAT: %.2fV", (double)vbat);
  out = buf;
  return true;
}

static bool makeBoardWarning_(String& out) {
  if (PowerManager::analogRailFaultLatched() || PowerManager::analogRailFaultActive()) {
    out = "Analog fault";
    return true;
  }
  if (!StorageManager_cardDetected()) {
    out = "SD: missing";
    return true;
  }
  if (!StorageManager_isMounted()) {
    out = "SD: not ready";
    return true;
  }
  if (PowerManager::fuelAlertActive()) {
    out = "Batt alert";
    return true;
  }
  return false;
}

static uint32_t s_nextClockUiCheckMs = 0;

static bool makeClockString_(String& out) {
  // Try system time (NTP or RTC should have set it). 10 ms timeout.
  struct tm t;
  if (getLocalTime(&t, 10)) {
    // Format: 24h HH:MM:SS (change to taste)
    char buf[32];
    strftime(buf, sizeof(buf), "%H:%M:%S", &t);
    out = buf;
    return true;
  }
  out = "--:--:--";
  return false;
}

static String makeGpsFooterString_() {
  SensorGpsStatus gps;
  if (!SensorManager::gpsStatus(gps)) return "";

  switch (gps.state) {
    case SensorGpsState::Fixed: return "GPS";
    case SensorGpsState::Acquiring: return ".....";
    case SensorGpsState::Error:
    default: return "NOGPS";
  }
}

static String composeFooterLine_(const String& left, const String& middle, const String& right) {
  constexpr int FOOTER_COLS = 21;  // 128px / 6px per char (GFX default font, size=1)
  char buf[FOOTER_COLS + 1];
  for (int i = 0; i < FOOTER_COLS; ++i) buf[i] = ' ';
  buf[FOOTER_COLS] = '\0';

  auto put = [&](int pos, const String& text) {
    if (pos < 0) pos = 0;
    for (int i = 0; i < (int)text.length() && (pos + i) < FOOTER_COLS; ++i) {
      buf[pos + i] = text[i];
    }
  };

  const int leftLen = min((int)left.length(), FOOTER_COLS);
  put(0, left.substring(0, leftLen));

  String rightTrimmed = right;
  if ((int)rightTrimmed.length() > FOOTER_COLS) {
    rightTrimmed = rightTrimmed.substring(0, FOOTER_COLS);
  }
  const int rightPos = FOOTER_COLS - (int)rightTrimmed.length();
  put(rightPos, rightTrimmed);

  if (middle.length()) {
    int middlePos = (FOOTER_COLS - (int)middle.length()) / 2;
    const int minPos = leftLen + 1;
    const int maxPos = rightPos - (int)middle.length() - 1;
    if (maxPos >= minPos) {
      if (middlePos < minPos) middlePos = minPos;
      if (middlePos > maxPos) middlePos = maxPos;
      put(middlePos, middle);
    }
  }

  return String(buf);
}



namespace {
  // true = suspend background OLED writes (telemetry, status, toasts)
  bool s_modal = false;
}

bool UI::isModal()   { return s_modal; }
void UI::beginModal(){ s_modal = true; }
void UI::endModal()  { s_modal = false; }

void UI::configure(const LoggerConfig& cfg) {
  s_target      = (cfg.uiTarget == 0 ? UI::TARGET_SERIAL : cfg.uiTarget); // default serial
  s_serialLevel = (cfg.uiSerialLevel >= 1 && cfg.uiSerialLevel <= 4) ? cfg.uiSerialLevel : UI::LVL_INFO;
  s_oledLevel   = (cfg.uiOledLevel   >= 1 && cfg.uiOledLevel   <= 4) ? cfg.uiOledLevel   : UI::LVL_INFO;
}

void UI::begin(const LoggerConfig& cfg) {
  configure(cfg);
}

void UI::loop() {
  if ((int32_t)(millis() - s_nextWifiUiCheckMs) >= 0) {
    s_nextWifiUiCheckMs = millis() + 1000;  // 1 Hz is plenty
    String now;
    String boardWarn;
    String lowBattery;
    if (makeBoardWarning_(boardWarn) && ((millis() / 1000UL) & 0x1UL) == 0) {
      now = boardWarn;
    } else if (makeLowBatteryWarning_(lowBattery) && ((millis() / 1000UL) & 0x1UL) == 0) {
      now = lowBattery;
    } else {
      now = makeWifiSummary_();
    }
    DisplayManager::setStatusLine(now);
    s_lastWifiSummary = now;
  }

  // New: update footer clock once per second
  if ((int32_t)(millis() - s_nextClockUiCheckMs) >= 0) {
    s_nextClockUiCheckMs = millis() + 1000;

    // Left side: clock
    String left;
    makeClockString_(left);

    // Middle: GPS state, only when a GPS sensor is configured.
    String middle = makeGpsFooterString_();

    // Right side: battery
    String right;
    if (PowerManager::fuelGaugeOk()) {
      int pct = (int)lroundf(PowerManager::batterySocPercent());
      if (pct < 0) pct = 0;
      if (pct > 100) pct = 100;
      right = String(pct) + "%";
    } else {
      right = "";   // or "--%" if you prefer a placeholder
    }

    DisplayManager::setFooterLine(composeFooterLine_(left, middle, right));
  }
  DisplayManager::loop();
}

void UI::println(const String& serialText, const String& oledText, uint8_t targets, uint8_t level, uint16_t oledToastMs, uint8_t oledToastSize) {
  uint8_t tgt = (targets == TARGET_DEFAULT) ? s_target : targets;

  if ((tgt & TARGET_SERIAL) && s_serialLevel >= level && serialText.length()) {
    Log_println(uiLevelToLogLevel_(level), serialText.c_str());
  }
  if ((tgt & TARGET_OLED) && s_oledLevel >= level && oledText.length() && DisplayManager::available()) {
    DisplayManager::toast(oledText, oledToastMs, oledToastSize);
  }
}

void UI::oledText(int16_t x, int16_t y, const String& text) {
  if (!DisplayManager::available()) return;     // or your guard
    DisplayManager::drawText(x, y, text);

}

void UI::status(const String& line) {
  if (UI::isModal()) return; 
  if (DisplayManager::available()) {
    DisplayManager::setStatusLine(line);
  }
  // Optional: also mirror to the logger at debug level.
}

void UI::toast(const String& oledText, uint16_t durationMs, uint8_t textSize) {
  if (UI::isModal()) return; 
  if (DisplayManager::available() && oledText.length()) {
    DisplayManager::toast(oledText, durationMs, textSize);
  }
}

void UI::toastModal(const String& text, uint16_t durationMs, uint8_t textSize) {
  if (DisplayManager::available() && text.length()) {
    DisplayManager::toast(text, durationMs, textSize);
  }
}


void UI::clear(uint8_t target) {
  // Clear Serial (ANSI-capable terminals). Safe no-op if user’s monitor ignores it.
  if (target & TARGET_SERIAL) {
    Serial.write("\033[2J");  // clear screen
    Serial.write("\033[H");   // move cursor to home
    Serial.flush();
  }

  // Clear OLED
  if ((target & TARGET_OLED) && DisplayManager::available()) {
    DisplayManager::clear();
  }
}
