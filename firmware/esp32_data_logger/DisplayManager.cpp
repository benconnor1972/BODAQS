#include "DisplayManager.h"
#include "ConfigManager.h"
#include "MenuSystem.h"
#include "UI.h"
#include "SensorManager.h"
#include "LoggingManager.h"

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// 128x64 0.96" common panel
static constexpr uint8_t  OLED_W = 128;
static constexpr uint8_t  OLED_H = 64;
static constexpr int8_t   OLED_RST_PIN = -1; // no reset pin

// Hardware defaults for SparkFun ESP32 Thing Plus:
static constexpr int    OLED_SDA  = 21; // Thing Plus 
static constexpr int    OLED_SCL  = 22; // Thing Plus

//static constexpr int    OLED_SDA  = 8; // Thing Plus S3
//static constexpr int    OLED_SCL  = 9; // Thing Plus S3

static constexpr uint8_t OLED_ADDR_PRIMARY   = 0x3C; // most 0.96" SSD1306
static constexpr uint8_t OLED_ADDR_ALTERNATE = 0x3D; // some boards

static Adafruit_SSD1306 oled(OLED_W, OLED_H, &Wire, OLED_RST_PIN);

static bool     s_present      = false;
static String   s_status       = "";
static String   s_footer       = "";      // <-- new: bottom row text
static String   s_toast        = "";
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
    const int lineH = 10;
    // Top strip
    oled.fillRect(0, 0, OLED_W, lineH, BLACK);
    oled.setTextSize(1);
    oled.setTextColor(SSD1306_WHITE);
    oled.setTextWrap(false);
    oled.setCursor(0, 0);
    oled.print(s_status);
  }

  // New: bottom strip for footer (clock)
  static void renderFooter_() {
    const int lineH = 8;
    const int y = OLED_H - lineH;
    oled.fillRect(0, y, OLED_W, lineH, BLACK);
    oled.setTextSize(1);
    oled.setTextColor(SSD1306_WHITE);
    oled.setTextWrap(false);
    oled.setCursor(0, y);
    oled.print(s_footer);
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
  if (!s_present) return;
  oled.clearDisplay(); 
  renderStatus_();
  renderFooter_();
 
  // Toast (middle of screen)
  if (s_toast.length()) {
    int16_t x = 0;
    int16_t y = (OLED_H / 2 - 8); // 8px font height
    oled.setCursor(x, y);
    oled.setTextSize(2);
    oled.print(s_toast);
  }
  oled.display();
}

static void setContrast(uint8_t c) {
  // Adafruit_SSD1306 exposes this via command
  oled.ssd1306_command(SSD1306_SETCONTRAST);
  oled.ssd1306_command(c);
}

bool DisplayManager::begin(const LoggerConfig& cfg) {
  s_cfg = &cfg;

  Serial.println(F("[DISP] begin: starting I2C"));

  // I2C bring-up
  Wire.begin(OLED_SDA, OLED_SCL);
  Wire.setClock(100000);   // 100k while debugging; you can go 400k later

  // --- Quick bus probe before touching the SSD1306 lib ---
  // This avoids hanging inside oled.begin() if the bus is wedged.
  uint8_t addrToUse = 0;
  {
    // Try primary address
    Wire.beginTransmission(OLED_ADDR_PRIMARY);
    uint8_t err = Wire.endTransmission(true);
    if (err == 0) {
      addrToUse = OLED_ADDR_PRIMARY;
      Serial.println(F("[DISP] I2C: found OLED at primary address"));
    } else {
      // Try alternate address
      Wire.beginTransmission(OLED_ADDR_ALTERNATE);
      err = Wire.endTransmission(true);
      if (err == 0) {
        addrToUse = OLED_ADDR_ALTERNATE;
        Serial.println(F("[DISP] I2C: found OLED at alternate address"));
      } else {
        Serial.print(F("[DISP] I2C: no OLED found, err="));
        Serial.println(err);
      }
    }
  }

  if (addrToUse == 0) {
    // No response on either address → fail fast, don't hang.
    s_present = false;
    s_status  = "OLED not detected";
    Serial.println(F("[DISP] OLED not detected; display disabled."));
    return false;
  }

  // --- Initialise the SSD1306 ---
  Serial.print(F("[DISP] Initialising SSD1306 at 0x"));
  Serial.println(addrToUse, HEX);

  bool ok = oled.begin(SSD1306_SWITCHCAPVCC,
                       addrToUse,
                       /*reset=*/false,
                       /*periphBegin=*/false);
  if (!ok) {
    Serial.println(F("[DISP] oled.begin() failed; display disabled."));
    s_present = false;
    return false;
  }

  Serial.println(F("[DISP] oled.begin() OK"));

  // Brightness & idle dim from cfg
  s_nominal    = (cfg.oledBrightness == 0) ? 200 : cfg.oledBrightness;
  s_brightness = s_nominal;
  s_idleDimMs  = (cfg.oledIdleDimMs == 0) ? 30000 : cfg.oledIdleDimMs;

  // Rotation (0/90/180/270) — adjust once you add cfg.oledRotate
  uint8_t rotIdx = 0; // 0°
  oled.setRotation(rotIdx);

  s_present = true;
  setContrast(s_nominal);

  // Reset UI state
  s_status        = "OLED ready";
  s_toast.clear();
  s_toastUntilMs  = 0;
  s_lastActivity  = millis();
  s_dimmed        = false;

  // Force first HUD draw
  s_lastHudMs   = 0;
  s_lastRate    = 0;
  s_lastActive  = 255;

  Serial.println(F("[DISP] calling drawAll()"));
  drawAll();
  Serial.println(F("[DISP] begin: complete"));
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

void DisplayManager::toast(const String& text, uint16_t durationMs) {
  if (!s_present) return;
  s_toast = text;
  s_lastActivity = millis();
  s_toastUntilMs = s_lastActivity + durationMs;
  if (s_dimmed) { s_dimmed = false; setContrast(s_nominal); }
  drawAll();
}

bool DisplayManager::available() { return s_present; }

void DisplayManager::clear()     { 
  if (!available()) return;
  if (s_present) { 
    oled.clearDisplay(); 
  } 
}

void DisplayManager::drawText(int16_t x, int16_t y, const String& s, uint8_t size) {
  if (!available()) return;
  oled.setCursor(x, y);   // (x,y) with y = baseline
  oled.setTextColor(SSD1306_WHITE);
  oled.setTextSize(size);
  oled.print(s);
}

void DisplayManager::setBrightness(uint8_t b) {
  s_nominal = b;
  if (!s_dimmed) setContrast(s_nominal);
}

void DisplayManager::present() {
  if (!available()) return;
  oled.display();
}