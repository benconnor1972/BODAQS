#include "UI.h"
#include "DisplayManager.h"
#include "ConfigManager.h"
#include "MenuSystem.h"
#include "WiFiManager.h"
#include "PowerManager.h"
#include <WiFi.h>   // for WiFi.SSID() and WiFi.localIP()
#include <time.h>



static uint8_t s_target       = UI::TARGET_SERIAL; // 1=serial,2=oled,3=both
static uint8_t s_serialLevel  = UI::LVL_INFO;      // only print if cfg level >= msg level
static uint8_t s_oledLevel    = UI::LVL_INFO;

static uint32_t s_nextWifiUiCheckMs = 0;
String   s_lastWifiSummary;

static String makeWifiSummary_() {
  auto st = WiFiManager::status();

  if (st.wl == WL_CONNECTED) {
    // Build the two strings we want to alternate between.
    String ssid = st.ssid.length() ? st.ssid : WiFi.SSID();
    if (!ssid.length()) ssid = "(connected)";

    String ip = WiFi.localIP().toString();
    if (!ip.length() || ip == "0.0.0.0") ip = "(no ip)";

    const String a = "WiFi: " + ssid;
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
  }
  return "WiFi: ?";
}

static uint32_t s_nextClockUiCheckMs = 0;

static bool makeClockString_(String& out) {
  // Try system time (NTP or RTC should have set it). 10 ms timeout.
  struct tm t;
  if (getLocalTime(&t, 10)) {
    // Format: 24h HH:MM:SS (change to taste)
    char buf[32];
    strftime(buf, sizeof(buf), "Time: %H:%M:%S", &t);
    out = buf;
    return true;
  }
  out = "Time: not set";
  return false;
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
    String now = makeWifiSummary_();
    DisplayManager::setStatusLine(now);
    s_lastWifiSummary = now;
  }

  // New: update footer clock once per second
  if ((int32_t)(millis() - s_nextClockUiCheckMs) >= 0) {
    s_nextClockUiCheckMs = millis() + 1000;

    // Left side: clock
    String left;
    makeClockString_(left);

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

    // Compose a single line with right-aligned battery (monospace assumption)
    constexpr int FOOTER_COLS = 21;  // 128px / 6px per char (GFX default font, size=1)

    // If right part is too long, truncate it
    if ((int)right.length() > FOOTER_COLS) right = right.substring(0, FOOTER_COLS);

    // Available space for left once we reserve the right-hand text
    int leftMax = FOOTER_COLS - (int)right.length();
    if (leftMax < 0) leftMax = 0;

    if ((int)left.length() > leftMax) {
      left = left.substring(0, leftMax);
    }

    // Pad with spaces so 'right' ends at the far right
    String footer = left;
    while ((int)footer.length() < leftMax) footer += ' ';
    footer += right;

    DisplayManager::setFooterLine(footer);
  }
  DisplayManager::loop();
}

void UI::println(const String& serialText, const String& oledText, uint8_t targets, uint8_t level, uint16_t oledToastMs) {
  uint8_t tgt = (targets == TARGET_DEFAULT) ? s_target : targets;

  if ((tgt & TARGET_SERIAL) && s_serialLevel >= level && serialText.length()) {
    Serial.println(serialText);
  }
  if ((tgt & TARGET_OLED) && s_oledLevel >= level && oledText.length() && DisplayManager::available()) {
    DisplayManager::toast(oledText, oledToastMs);
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
  // Optional: also mirror to Serial at debug level
  // Serial.println(String("[STATUS] ") + line);
}

void UI::toast(const String& oledText, uint16_t durationMs) {
  if (UI::isModal()) return; 
  if (DisplayManager::available() && oledText.length()) {
    DisplayManager::toast(oledText, durationMs);
  }
}

void UI::toastModal(const String& text, uint16_t durationMs) {
  if (DisplayManager::available() && text.length()) {
    DisplayManager::toast(text, durationMs);
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
