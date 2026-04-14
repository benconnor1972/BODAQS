#include "DisplayManager.h"
#include "ConfigManager.h"
#include "MenuSystem.h"
#include "UI.h"
#include "SensorManager.h"
#include "LoggingManager.h"
#include "I2CManager.h"
#include "DebugLog.h"

#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// 128x64 0.96" common panel
static constexpr uint8_t  OLED_W = 128;
static constexpr uint8_t  OLED_H = 64;
static constexpr int8_t   OLED_RST_PIN = -1; // no reset pin

// Hardware defaults for SparkFun ESP32 Thing Plus:
//static constexpr int    OLED_SDA  = 21; // Thing Plus 
//static constexpr int    OLED_SCL  = 22; // Thing Plus

static Adafruit_SSD1306* s_oled = nullptr;
static TwoWire*          s_wire = nullptr;

static bool     s_present      = false;
static String   s_status       = "";
static String   s_footer       = "";      // <-- new: bottom row text
static String   s_toast        = "";
static uint8_t  s_toastSize    = 2;
static uint32_t s_toastUntilMs = 0;
static uint32_t s_lastActivity = 0;
static uint16_t s_idleDimMs    = 30000;
static uint8_t  s_brightness   = 200; // 0..255
static uint8_t  s_nominal      = 200;
static bool     s_dimmed       = false;



namespace {
  const LoggerConfig* s_cfg = nullptr;

  // Idle HUD throttling + caching so we don’t spam the OLED
  unsigned long s_lastHudMs = 0;
  uint16_t      s_lastRate  = 0;
  uint8_t       s_lastActive= 0;
  static uint8_t       s_lastBlinkPhase= 255;     // force first draw

  static constexpr uint16_t BLINK_MS = 1000;       // 500ms on/off = 1 Hz


  static void renderStatus_() {
    if (!s_oled) return;
    const int lineH = 10;
    // Top strip
    s_oled->fillRect(0, 0, OLED_W, lineH, BLACK);
    s_oled->setTextSize(1);
    s_oled->setTextColor(SSD1306_WHITE);
    s_oled->setTextWrap(false);
    s_oled->setCursor(0, 0);
    s_oled->print(s_status);
  }

  // New: bottom strip for footer (clock)
  static void renderFooter_() {
    if (!s_oled) return;
    const int lineH = 8;
    const int y = OLED_H - lineH;
    s_oled->fillRect(0, y, OLED_W, lineH, BLACK);
    s_oled->setTextSize(1);
    s_oled->setTextColor(SSD1306_WHITE);
    s_oled->setTextWrap(false);
    s_oled->setCursor(0, y);
    s_oled->print(s_footer);
  }

  void drawIdleHud_() {
    if (!s_cfg) return;
    if (UI::isModal() || MenuSystem::isActive()) return;  // <- extra belt-and-braces

    const uint16_t hz  = ConfigManager::get().sampleRateHz;   // ← live read
    const uint8_t  act= SensorManager::activeCount();      // live active count
    const bool logging = LoggingManager::isRunning();          


    // Throttle to ~5 Hz and avoid redraws if nothing changed
    unsigned long now = millis();
    const uint8_t blinkPhase = logging ? ((now / BLINK_MS) & 0x1) : 0;  // 0/1
    if (now - s_lastHudMs < 200 && hz == s_lastRate && act == s_lastActive && blinkPhase == s_lastBlinkPhase) return;
    s_lastHudMs  = now;
    s_lastRate   = hz;
    s_lastActive = act;
    s_lastBlinkPhase = blinkPhase;

    // Full redraw of the idle view
    DisplayManager::clear();
    renderStatus_();
    renderFooter_();
    const bool showMain = !logging || (blinkPhase == 0);

    if (showMain) {
      DisplayManager::drawText(0, 16, String(hz) + " Hz", 2);
      DisplayManager::drawText(
        0, 34,
        String(act) + " Channel" + (act == 1 ? "" : "s"),
        2
      );
    }
    DisplayManager::present();
  }
}

static void drawAll() {
  if (!s_present || !s_oled) return;
  s_oled->clearDisplay(); 
  renderStatus_();
  renderFooter_();
 
  // Toast (middle of screen)
  if (s_toast.length()) {
    String line1 = s_toast;
    String line2 = "";
    const int newline = s_toast.indexOf('\n');
    if (newline >= 0) {
      line1 = s_toast.substring(0, newline);
      line2 = s_toast.substring(newline + 1);
      const int nextNewline = line2.indexOf('\n');
      if (nextNewline >= 0) {
        line2 = line2.substring(0, nextNewline);
      }
    }

    const uint8_t size = s_toastSize ? s_toastSize : 1;
    const int16_t lineHeight = (int16_t)(8 * size + 2);
    s_oled->setTextColor(SSD1306_WHITE);
    s_oled->setTextWrap(false);
    s_oled->setTextSize(size);

    if (line2.length()) {
      const int16_t totalHeight = (int16_t)(lineHeight * 2 - 2);
      const int16_t y1 = (OLED_H - totalHeight) / 2;
      const int16_t y2 = y1 + lineHeight;
      s_oled->setCursor(0, y1);
      s_oled->print(line1);
      s_oled->setCursor(0, y2);
      s_oled->print(line2);
    } else {
      const int16_t y = (OLED_H - (8 * size)) / 2;
      s_oled->setCursor(0, y);
      s_oled->print(line1);
    }
  }
  if (!I2CManager::lock(s_wire)) return;
  s_oled->display();
  I2CManager::unlock(s_wire);
}

static void setContrast(uint8_t c) {
  if (!s_oled) return;
  if (!I2CManager::lock(s_wire)) return;
  // Adafruit_SSD1306 exposes this via command
  s_oled->ssd1306_command(SSD1306_SETCONTRAST);
  s_oled->ssd1306_command(c);
  I2CManager::unlock(s_wire);
}

bool DisplayManager::begin(const LoggerConfig& cfg,
                           const board::DisplayProfile& disp,
                           TwoWire* wire) {
  s_cfg = &cfg;
  s_wire = wire;

  // If no display on this board, disable cleanly.
  if (disp.type == board::DisplayType::None) {
    s_present = false;
    s_status  = "";
    LOGI_TAG("DISP", "No display (BoardProfile).\n");
    return false;
  }

  if (!s_wire) {
    s_present = false;
    s_status  = "OLED unavailable";
    LOGW_TAG("DISP", "No I2C bus supplied; display disabled.\n");
    return false;
  }

  if (s_oled) {
    delete s_oled;
    s_oled = nullptr;
  }
  s_oled = new Adafruit_SSD1306(OLED_W, OLED_H, s_wire, OLED_RST_PIN);
  if (!s_oled) {
    s_present = false;
    s_status  = "OLED alloc fail";
    LOGE_TAG("DISP", "Failed to allocate OLED object.\n");
    return false;
  }

  LOGI_TAG("DISP", "begin: probing OLED on configured I2C bus\n");

  // --- Quick bus probe before touching the SSD1306 lib ---
  uint8_t addrToUse = 0;
  {
    if (!I2CManager::lock(s_wire)) {
      LOGW_TAG("DISP", "I2C bus lock failed during OLED probe\n");
      return false;
    }
    s_wire->beginTransmission(disp.addr_primary);
    uint8_t err = s_wire->endTransmission(true);
    if (err == 0) {
      addrToUse = disp.addr_primary;
      LOGI_TAG("DISP", "I2C: found OLED at primary address\n");
    } else {
      s_wire->beginTransmission(disp.addr_alt);
      err = s_wire->endTransmission(true);
      if (err == 0) {
        addrToUse = disp.addr_alt;
        LOGI_TAG("DISP", "I2C: found OLED at alternate address\n");
      } else {
        LOGW_TAG("DISP", "I2C: no OLED found, err=%u\n", (unsigned)err);
      }
    }
    I2CManager::unlock(s_wire);
  }

  if (addrToUse == 0) {
    s_present = false;
    s_status  = "OLED not detected";
    LOGW_TAG("DISP", "OLED not detected; display disabled.\n");
    return false;
  }

  // --- Initialise the SSD1306 ---
  LOGI_TAG("DISP", "Initialising SSD1306 at 0x%02X\n", (unsigned)addrToUse);

  if (!I2CManager::lock(s_wire)) {
    LOGE_TAG("DISP", "I2C bus lock failed during oled.begin().\n");
    s_present = false;
    return false;
  }
  bool ok = s_oled->begin(SSD1306_SWITCHCAPVCC,
                          addrToUse,
                          /*reset=*/false,
                          /*periphBegin=*/false);
  I2CManager::unlock(s_wire);
  if (!ok) {
    LOGE_TAG("DISP", "oled.begin() failed; display disabled.\n");
    s_present = false;
    return false;
  }

  LOGI_TAG("DISP", "oled.begin() OK\n");

  // Brightness & idle dim from cfg (unchanged)
  s_nominal    = (cfg.oledBrightness == 0) ? 200 : cfg.oledBrightness;
  s_brightness = s_nominal;
  s_idleDimMs  = (cfg.oledIdleDimMs == 0) ? 30000 : cfg.oledIdleDimMs;

  s_oled->setRotation(0);

  s_present = true;
  setContrast(s_nominal);

  // Reset UI state (unchanged)
  s_status        = "OLED ready";
  s_toast.clear();
  s_toastSize     = 2;
  s_toastUntilMs  = 0;
  s_lastActivity  = millis();
  s_dimmed        = false;

  // Force first HUD draw
  s_lastHudMs   = 0;
  s_lastRate    = 0;
  s_lastActive  = 255;

  drawAll();
  LOGI_TAG("DISP", "begin: complete\n");
  return true;
}

void DisplayManager::loop() {
  if (UI::isModal() || MenuSystem::isActive()) return;   // <- do nothing while menu owns the OLED
  if (!s_present) return;
  if (s_toast.length() == 0) {
    drawIdleHud_();
  }

  uint32_t now = millis();

  // Toast expiry
  if (s_toast.length() && now >= s_toastUntilMs) {
    s_toast = "";
    s_toastSize = 2;
    drawAll();
  }

  // Idle dim/power-save
  if (s_idleDimMs > 0) {
    uint32_t idle = now - s_lastActivity;
    if (!s_dimmed && idle >= s_idleDimMs) {
      s_dimmed = true;
      setContrast(0); // dim to minimum
    } else if (s_dimmed && idle < s_idleDimMs) {
      s_dimmed = false;
      setContrast(s_nominal);
    }
  }
}

void DisplayManager::setStatusLine(const String& line) {
  if (!s_present) return;
  s_status = line;
  s_lastActivity = millis();
  if (s_dimmed) { s_dimmed = false; setContrast(s_nominal); }
  s_lastHudMs = 0;           // force next HUD redraw soon
  // no immediate drawAll(); let drawIdleHud_ own the frame
}

void DisplayManager::setFooterLine(const String& line) {
  if (!s_present) return;
  s_footer = line;
  s_lastActivity = millis();
  if (s_dimmed) { s_dimmed = false; setContrast(s_nominal); }
  s_lastHudMs = 0;   // force redraw soon
}

void DisplayManager::toast(const String& text, uint16_t durationMs, uint8_t textSize) {
  if (!s_present) return;
  s_toast = text;
  s_toastSize = textSize ? textSize : 1;
  s_lastActivity = millis();
  s_toastUntilMs = s_lastActivity + durationMs;
  if (s_dimmed) { s_dimmed = false; setContrast(s_nominal); }
  drawAll();
}

bool DisplayManager::available() { return s_present; }

void DisplayManager::clear()     { 
  if (!available()) return;
  if (s_present && s_oled) { 
    s_oled->clearDisplay(); 
  } 
}

void DisplayManager::drawText(int16_t x, int16_t y, const String& s, uint8_t size) {
  if (!available()) return;
  s_oled->setCursor(x, y);   // (x,y) with y = baseline
  s_oled->setTextColor(SSD1306_WHITE);
  s_oled->setTextSize(size);
  s_oled->print(s);
}

void DisplayManager::setBrightness(uint8_t b) {
  s_nominal = b;
  if (!s_dimmed) setContrast(s_nominal);
}

void DisplayManager::present() {
  if (!available()) return;
  if (!I2CManager::lock(s_wire)) return;
  s_oled->display();
  I2CManager::unlock(s_wire);
}
