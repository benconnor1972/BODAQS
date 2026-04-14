#include "MenuSystem.h"
#include "UI.h"
#include "ConfigManager.h"
#include "SensorManager.h"
#include "WebServerManager.h"
#include "DisplayManager.h"
#include "PowerManager.h"
#include "LoggingManager.h"
#include "Rates.h"
#include "AnalogPotSensor.h"
#include "Sensor.h"
#include "Calibration.h"
#include "CalCapture.h"
#include "ButtonActions.h"
#include "WiFiManager.h"
#include "DebugLog.h"
#include <WiFi.h>
#include "RTCManager.h"

#include <esp_system.h>   // esp_restart()


// ---- Menu debug toggle ----
#define MLOG(...) LOGD_TAG("MENU", __VA_ARGS__)

// Pretty names for states/dirs
static const char* stateName(MenuSystem::State s) {
  switch (s) {
    case MenuSystem::State::Inactive:    return "Inactive";
    case MenuSystem::State::Main:        return "Main";
    case MenuSystem::State::SensorsList: return "SensorsList";
    case MenuSystem::State::RatePicker:  return "RatePicker";
    case MenuSystem::State::CalibSensors:return "CalibSensors";
    case MenuSystem::State::CalibDetail: return "CalibDetail";
    default: return "?";
  }
}

static const char* dirName(MenuSystem::Dir d) {
  switch (d) {
    case MenuSystem::Dir::Up:    return "Up";
    case MenuSystem::Dir::Down:  return "Down";
    case MenuSystem::Dir::Left:  return "Left";
    case MenuSystem::Dir::Right: return "Right";
    case MenuSystem::Dir::Enter: return "Enter";
    default: return "?";
  }
}

static uint8_t s_mainTop = 0;   // first visible item in main menu (scroll window)
static constexpr uint8_t MAIN_VISIBLE_ROWS = 5;

namespace {
  using State = MenuSystem::State;
  using Dir   = MenuSystem::Dir;

  const LoggerConfig* s_cfg = nullptr;

  enum class MainItem : uint8_t {
    WebServerToggle = 0,
    SensorsToggle,
    SampleRate,
    Calibration,
    Sleep,
    Restart
  };
  static inline uint8_t mainItemCount_() { return 6; }

  static State   s_state       = State::Inactive;
  static uint8_t s_mainSel     = 0;
  static uint8_t s_sensorSel   = 0;

  // ---- Calibration UI state (per detail screen) ----
  enum class CalUiPhase : uint8_t {
    Idle,          // shows: Zero / Start RANGE (Enter/Right inert)
    RangeActive,   // shows: Finish RANGE / Cancel (Enter/Right inert)
    ZeroCaptured,  // shows: Save / Cancel (Enter/Right act)
    RangeFinished  // shows: Save / Cancel (Enter/Right act)
  };

  static uint8_t    s_calSel     = 0;              // selected sensor index
  static uint8_t    s_calOptSel  = 0;              // selected row within screen
  static CalUiPhase s_calUiPhase = CalUiPhase::Idle;
  static unsigned long s_lastRangeTrackMs = 0;

  static unsigned long s_deferUiUntilMs = 0;
  static bool          s_deferRedraw    = false;

  // Web server start choreography
  static bool     s_wsPending = false;       // waiting for Wi-Fi to start server
  static uint32_t s_wsDeadlineMs = 0;        // give up time


  static inline void deferUiFor(uint16_t ms) {
    const unsigned long until = millis() + ms;
    if (until > s_deferUiUntilMs) s_deferUiUntilMs = until;
    s_deferRedraw = true; // when the deferral ends, we’ll do one redraw
  }


  static unsigned long s_lastInputMs = 0;
  static unsigned long s_idleCloseMs = 120000;
  static bool s_swallowEnterRelease = false;  // eat next Enter/Right RELEASED after drill-down
  // Block Enter/Right PRESSED for a short time after state transitions
  static unsigned long s_enterGuardUntilMs = 0;
  static inline void guardEnterRight(uint16_t ms = 180) {
    s_enterGuardUntilMs = millis() + ms;
  }

  static void drawMain_();
  static void drawSensors_();
  static void drawRatePicker_();
  static void enterRatePicker_();
  static void applyRate_();
  static void redraw_();
  static void drawCalibSensors_();
  static void drawCalibDetail_();
  static void toggleSelectedSensor_();
  static void showCalibrationCaptureToast_(const char* label, int32_t counts);
  static RangeCapture s_rangeCap;   // <--- ADD THIS LINE
  static void tickActiveRangeCalibration_();
  static bool activateCurrentSelection_();

  inline void touch() { s_lastInputMs = millis(); }

  // -------- drawing helpers (OLED only) --------
  static void drawHeader_(const char* title) {
    if ((long)(s_deferUiUntilMs - millis()) > 0) return;  // toast visible, skip repaint
    UI::clear(UI::TARGET_OLED);
    UI::oledText(0,0,String(title));
    //UI::println("", String(title), UI::TARGET_OLED, UI::LVL_INFO);
  }

  static void drawFooterHint_(const char* hint) {
    if ((long)(s_deferUiUntilMs - millis()) > 0) return;  // toast visible, skip repaint
    UI::println("", String(hint), UI::TARGET_OLED, UI::LVL_INFO, 2000, 1);
  }

  static String mainItemLabel_(MainItem mi) {
    switch (mi) {
      case MainItem::WebServerToggle: {
        if (s_wsPending) {
          return "WiFi: CONNECTING";
        }
        bool on = WebServerManager::isRunning();
        return String("WiFi: ") + (on ? "ON" : "OFF");
      }
      case MainItem::SensorsToggle:
        return "Mute sensors";
      case MainItem::SampleRate: {
        uint16_t hz = ConfigManager::get().sampleRateHz;
        return String("Sample rate: ") + hz + " Hz";
      }
      case MainItem::Calibration:
        return "Calibration";
      case MainItem::Sleep:
        return "Sleep";
      case MainItem::Restart:
        return "Restart";
      default:
        return "?";
    }
  }

  static void drawMain_() {
    if ((long)(s_deferUiUntilMs - millis()) > 0) return;  // toast visible, skip repaint
    drawHeader_("Menu");

    const uint8_t N = mainItemCount_();

    // Clamp top in case N changed
    if (N <= MAIN_VISIBLE_ROWS) {
      s_mainTop = 0;
    } else {
      const uint8_t maxTop = (uint8_t)(N - MAIN_VISIBLE_ROWS);
      if (s_mainTop > maxTop) s_mainTop = maxTop;
    }

    // Draw a 5-line window starting at s_mainTop
    for (uint8_t row = 0; row < MAIN_VISIBLE_ROWS; ++row) {
      const uint8_t i = (uint8_t)(s_mainTop + row);
      if (i >= N) break;

      const String label = mainItemLabel_(static_cast<MainItem>(i));
      String line = (i == s_mainSel) ? "> " : "  ";
      line += label;

      const int y = 12 + row * 10;   // note: row, not i
      UI::oledText(0, y, line);
    }

    DisplayManager::present();
  }


  static void openMainSelection_() {
    switch (static_cast<MainItem>(s_mainSel)) {

      case MainItem::WebServerToggle: {
        s_swallowEnterRelease = true;
        guardEnterRight();

        if (WebServerManager::isRunning()) {
          WebServerManager::stop();
          WiFiManager::disable();   // optional: if you want Wi-Fi off when server off
          s_wsPending = false;      // cancel any pending start
          drawMain_();
          break;
        }

        if (!WebServerManager::canStart()) {
          UI::toastModal("Busy/logging", 1200, 1);
          deferUiFor(1200);
          drawMain_();
          break;
        }

        s_wsPending    = true;
        s_wsDeadlineMs = millis() + 20000;   // 20s budget max
        drawMain_();

        // Kick Wi-Fi once and let the loop finish the start later.
        // Draw first so "CONNECTING" is visible before the blocking scan starts.
        WiFiManager::enable();
        WiFiManager::connectNow();
        WiFiManager::noteUserActivity();
        break;
      }

      case MainItem::SensorsToggle:
        s_swallowEnterRelease = true;   // <--- ADD
        guardEnterRight();              // <--- add
        s_state = State::SensorsList;
        s_sensorSel = 0;
        redraw_();
        break;

      case MainItem::Sleep:
        //DisplayManager::setStatusLine("Sleeping in 2s...");
        delay(2000);
        PowerManager::sleepOnEnterEXT0();
        break;

      case MainItem::SampleRate: {
        s_swallowEnterRelease = true;   // <--- ADD
        guardEnterRight();              // <--- add
        enterRatePicker_();
        break;
      }


      case MainItem::Calibration: {
        s_swallowEnterRelease = true;   // <--- ADD
        guardEnterRight();              // <--- add
        s_state      = State::CalibSensors;
        s_calSel     = 0;
        s_calUiPhase = CalUiPhase::Idle;
        drawCalibSensors_();
        break;
      }

      case MainItem::Restart: {
        s_swallowEnterRelease = true;
        guardEnterRight();

        // Guard: no restart while logging
        if (LoggingManager::isRunning()) {
          UI::toastModal("Stop logging first", 1200, 1);
          deferUiFor(1200);
          drawMain_();
          break;
        }

        UI::toastModal("Restarting...", 800, 1);
        deferUiFor(800);
        DisplayManager::present(); // ensure OLED pushes immediately (if applicable)

        LOGI_TAG("Menu", "Restarting via esp_restart()\n");
        Serial.flush();
        delay(150);
        RTCManager_invalidateInternalTime();
        esp_restart(); // does not return
        break;
      }
    }
  }

  static void showCalibrationCaptureToast_(const char* label, int32_t counts) {
    char countLine[24];
    snprintf(countLine, sizeof(countLine), "Count: %ld", (long)counts);
    UI::toastModal(String(label) + "\n" + String(countLine), 2000, 1);
  }

  static void drawSensors_() {
    if ((long)(s_deferUiUntilMs - millis()) > 0) return;  // toast visible, skip repaint
    UI::clear(UI::TARGET_OLED);
    UI::oledText(0, 0, "Sensors on/off");

    const uint8_t n = ConfigManager::sensorCount();
    for (uint8_t i = 0; i < n; ++i) {
      SensorSpec sp; if (!ConfigManager::getSensorSpec(i, sp)) continue;
      bool muted = false; SensorManager::getMuted(i, muted);

      String line;
      line.reserve(24);
      line += (i == s_sensorSel) ? ">" : " ";
      line += " ";
      line += sp.name;
      if (muted) line += " [M]";

      const int y = 12 + i * 10;
      UI::oledText(0, y, line);
    }
    DisplayManager::present();
  }

  // --- Calibration: Sensors list ---
  static void drawCalibSensors_() {
    if ((long)(s_deferUiUntilMs - millis()) > 0) return;  // toast visible, skip repaint
    UI::clear(UI::TARGET_OLED);
    UI::oledText(0, 0, "Calibration");

    const uint8_t n = ConfigManager::sensorCount();
    for (uint8_t i = 0; i < n; ++i) {
      SensorSpec sp; if (!ConfigManager::getSensorSpec(i, sp)) continue;
      Sensor* s = SensorManager::at(i);
      CalModeMask mask = s ? s->allowedCalMask() : 0;

      String line;
      line.reserve(28);
      line += (i == s_calSel) ? ">" : " ";
      line += " ";
      line += sp.name;

      if (mask == 0) {
        line += " [none]";
      } else {
        line += " [";
        if (mask & CAL_ZERO)  line += "Z";
        if (mask & CAL_RANGE) line += ((mask & CAL_ZERO) ? "|R" : "R");
        line += "]";
      }
      const int y = 12 + i * 10;
      UI::oledText(0, y, line);
    }
    DisplayManager::present();
  }

  // --- Calibration: Detail for one sensor (phased UI) ---
  static void drawCalibDetail_() {
    if ((long)(s_deferUiUntilMs - millis()) > 0) return;  // toast visible, skip repaint
    UI::clear(UI::TARGET_OLED);

    const uint8_t idx = s_calSel;
    SensorSpec sp; (void)ConfigManager::getSensorSpec(idx, sp);
    Sensor* s = SensorManager::at(idx);
    if (!s) { UI::oledText(0, 0, "No sensor"); DisplayManager::present(); return; }

    String title = String("Cal: ") + sp.name;
    UI::oledText(0, 0, title);

    CalModeMask mask = s->allowedCalMask();

    String rows[2];
    uint8_t rowCount = 0;

    switch (s_calUiPhase) {
      case CalUiPhase::Idle:
        if (mask & CAL_ZERO)  rows[rowCount++] = "Zero";
        if (mask & CAL_RANGE) rows[rowCount++] = "Start RANGE";
        if (rowCount == 0)    rows[rowCount++] = "No actions";
        break;

      case CalUiPhase::RangeActive:
        rows[rowCount++] = "Finish RANGE";
        rows[rowCount++] = "Cancel";
        break;

      case CalUiPhase::ZeroCaptured:
      case CalUiPhase::RangeFinished:
        rows[rowCount++] = "Save";
        rows[rowCount++] = "Cancel";
        break;
    }

    if (s_calOptSel >= rowCount) s_calOptSel = rowCount - 1;

    int y = 12;
    for (uint8_t i = 0; i < rowCount; ++i, y += 10) {
      String line = (i == s_calOptSel) ? "> " : "  ";
      line += rows[i];
      UI::oledText(0, y, line);
    }

    // Live counts only while RANGE is active
    if (s_calUiPhase == CalUiPhase::RangeActive && s->hasRawCounts()) {
      String hint = String("counts: ") + s->currentRawCounts();
      UI::oledText(0, 54, hint);
    }

    DisplayManager::present();
  }

  static void redraw_() {
    switch (s_state) {
      case State::Main:         drawMain_();         break;
      case State::SensorsList:  drawSensors_();      break;
      case State::RatePicker:   drawRatePicker_();   break;
      case State::CalibSensors: drawCalibSensors_(); break;
      case State::CalibDetail:  drawCalibDetail_();  break;
      default: break;
    }
  }

  static void tickActiveRangeCalibration_() {
    if (s_state != State::CalibDetail || s_calUiPhase != CalUiPhase::RangeActive) return;

    Sensor* s = SensorManager::at(s_calSel);
    if (!s || !s->hasRawCounts()) return;

    const unsigned long now = millis();
    if (s_lastRangeTrackMs != 0 && (now - s_lastRangeTrackMs) < 2) return;
    s_lastRangeTrackMs = now;

    // Keep calibration-space counts advancing while the operator moves the sensor.
    // Wrapped sensors use this to accumulate turn crossings between the start and finish marks.
    (void)s->currentRawCounts();
  }

  static bool activateCurrentSelection_() {
    switch (s_state) {
      case State::Main:
        openMainSelection_();
        return true;

      case State::SensorsList:
        toggleSelectedSensor_();
        return true;

      case State::RatePicker:
        applyRate_();
        return true;

      case State::CalibSensors:
        s_calOptSel  = 0;
        s_calUiPhase = CalUiPhase::Idle;
        s_state      = State::CalibDetail;
        s_swallowEnterRelease = true;
        guardEnterRight();
        drawCalibDetail_();
        return true;

      case State::CalibDetail: {
        Sensor* s = SensorManager::at(s_calSel);
        if (!s) {
          s_state = State::CalibSensors;
          s_calUiPhase = CalUiPhase::Idle;
          drawCalibSensors_();
          return true;
        }

        switch (s_calUiPhase) {
          case CalUiPhase::Idle: {
            CalModeMask mask = s->allowedCalMask();
            const bool zeroAllowed  = (mask & CAL_ZERO);
            const bool rangeAllowed = (mask & CAL_RANGE);

            if (s_calOptSel == 0 && zeroAllowed) {
              if (!s->beginCalibration(CalMode::ZERO)) {
                UI::toastModal("Zero fail", 2000, 1);
                deferUiFor(2000);
                return true;
              }

              const int32_t avg = sampleAverageCounts(s, 100);
              s->updateCalibration(avg);
              showCalibrationCaptureToast_("Zero", avg);
              deferUiFor(2000);
              s_calUiPhase = CalUiPhase::ZeroCaptured;
              s_calOptSel  = 0;
              drawCalibDetail_();
              return true;
            }

            const bool startRangeSelected =
              (rangeAllowed && ((zeroAllowed && s_calOptSel == 1) || (!zeroAllowed && s_calOptSel == 0)));
            if (startRangeSelected) {
              if (s->beginCalibration(CalMode::RANGE)) {
                s_rangeCap.reset();
                s_rangeCap.captureStart(s, 100);
                s->updateCalibration(s_rangeCap.start);
                showCalibrationCaptureToast_("Range start", s_rangeCap.start);
                deferUiFor(2000);
                s_calUiPhase = CalUiPhase::RangeActive;
                s_lastRangeTrackMs = 0;
                s_calOptSel  = 0;
                drawCalibDetail_();
              } else {
                UI::toastModal("Range fail", 2000, 1);
                deferUiFor(2000);
              }
              return true;
            }

            return true;
          }

          case CalUiPhase::RangeActive:
            if (s_calOptSel == 0) {
              s_rangeCap.captureFinish(s, 100);
              s->updateCalibration(s_rangeCap.finish);
              showCalibrationCaptureToast_("Range finish", s_rangeCap.finish);
              deferUiFor(2000);
              s_calUiPhase = CalUiPhase::RangeFinished;
              s_lastRangeTrackMs = 0;
              s_calOptSel  = 0;
              drawCalibDetail_();
            } else {
              s->finishCalibration(false);
              s_calUiPhase = CalUiPhase::Idle;
              s_lastRangeTrackMs = 0;
              s_calOptSel  = 0;
              drawCalibDetail_();
            }
            return true;

          case CalUiPhase::ZeroCaptured:
            if (s_calOptSel == 0) {
              if (s->finishCalibration(true)) {
                UI::toastModal("Zero saved", 2000, 1);
                deferUiFor(2000);
                s_calUiPhase = CalUiPhase::Idle;
                s_calOptSel  = 0;
                s_state      = State::CalibSensors;
                guardEnterRight();
                drawCalibSensors_();
              } else {
                UI::toastModal("Save failed", 2000, 1);
                deferUiFor(2000);
                drawCalibDetail_();
              }
            } else {
              s->finishCalibration(false);
              s_calUiPhase = CalUiPhase::Idle;
              s_calOptSel  = 0;
              drawCalibDetail_();
            }
            return true;

          case CalUiPhase::RangeFinished:
            if (s_calOptSel == 0) {
              const bool invert = (s_rangeCap.finish < s_rangeCap.start);
              if (s->finishCalibration(true)) {
                SensorSpec sp;
                if (ConfigManager::getSensorSpec(s_calSel, sp)) {
                  ConfigManager::saveSensorParamByName(sp.name, "invert", invert ? "true" : "false");
                }

                UI::toastModal("Range saved", 2000, 1);
                deferUiFor(2000);
                s_calUiPhase = CalUiPhase::Idle;
                s_calOptSel  = 0;
                s_state      = State::CalibSensors;
                guardEnterRight();
                drawCalibSensors_();
              } else {
                UI::toastModal("Save fail", 2000, 1);
                deferUiFor(2000);
                drawCalibDetail_();
              }
            } else {
              s->finishCalibration(false);
              s_calUiPhase = CalUiPhase::Idle;
              s_lastRangeTrackMs = 0;
              s_calOptSel  = 0;
              drawCalibDetail_();
            }
            return true;
        }
        return true;
      }

      case State::Inactive:
      default:
        return false;
    }
  }

  static void toggleSelectedSensor_() {
    const uint8_t sel = s_sensorSel;
    bool m = false;
    if (!SensorManager::getMuted(sel, m)) return;
    SensorManager::setMuted(sel, !m);

    MLOG("[MENU] toggle sensor %u -> %s\n", (unsigned)sel, (!m ? "Muted" : "Unmuted"));

    UI::toastModal(!m ? "Muted" : "Unmuted", 2000, 1);
    touch();
    drawSensors_();
  }

  static uint8_t  s_rateIdx = 0;   // selection within Rates::kList

  static void drawRatePicker_() {
    if ((long)(s_deferUiUntilMs - millis()) > 0) return;  // toast visible, skip repaint
    UI::clear(UI::TARGET_OLED);
    drawHeader_("Sample Rate");

    const uint16_t activeHz = ConfigManager::get().sampleRateHz;

    const int kLineH = 10;
    const int kTopY  = 12;
    const int maxLines = 5;

    int total = (int)Rates::kCount;
    int first = s_rateIdx - 2;
    if (first < 0) first = 0;
    if (first > total - maxLines) first = max(0, total - maxLines);

    int y = kTopY;
    for (int i = first; i < first + maxLines && i < total; ++i) {
      const bool isSel    = (i == (int)s_rateIdx);
      const bool isActive = (Rates::kList[i] == activeHz);

      String line;
      line.reserve(24);
      line += isSel ? ">" : " ";
      line += " ";
      line += isActive ? "[*] " : "[ ] ";
      line += String(Rates::kList[i]) + " Hz";

      UI::oledText(0, y, line);
      y += kLineH;
    }

    if (first > 0)                UI::oledText(118, 0,  "^");
    if (first + maxLines < total) UI::oledText(118, 54, "v");

    DisplayManager::present();
  }

  static void enterRatePicker_() {
    uint16_t cur = s_cfg ? s_cfg->sampleRateHz : Rates::kList[0];
    int idx = Rates::indexOf(cur);
    s_rateIdx = (idx >= 0) ? (uint8_t)idx : 0;
    s_state = State::RatePicker;
    drawRatePicker_();
  }

  static void applyRate_() {
    if (LoggingManager::isRunning()) {
      UI::toastModal("Stop log", 2000, 1);
      deferUiFor(2000);
      return;
    }

    uint16_t hz = Rates::kList[s_rateIdx];
    LoggingManager::setSampleRateHz(hz);
    UI::toastModal(String("Rate: ") + hz + " Hz", 2000, 1);
    deferUiFor(2000);
    s_state = State::Main;
    drawMain_();
  }

} // anon

// -------- public API --------
void MenuSystem::begin(const LoggerConfig* cfg) { s_cfg = cfg; }

bool MenuSystem::isActive() { return s_state != State::Inactive; }

void MenuSystem::setIdleCloseMs(uint32_t ms) {
  if (ms < 500) ms = 500;
  s_idleCloseMs = ms;
}

bool MenuSystem::handleAction(ButtonActions::ActionId action, ButtonEvent ev) {
  if (!isActive()) return false;

  switch (action) {
    case ButtonActions::ACT_MENU_NAV_UP:
      if (ev == BUTTON_PRESSED) onNav(Dir::Up, BUTTON_PRESSED);
      return true;

    case ButtonActions::ACT_MENU_NAV_DOWN:
      if (ev == BUTTON_PRESSED) onNav(Dir::Down, BUTTON_PRESSED);
      return true;

    case ButtonActions::ACT_MENU_NAV_LEFT:
      if (ev == BUTTON_PRESSED) onNav(Dir::Left, BUTTON_PRESSED);
      return true;

    case ButtonActions::ACT_MENU_NAV_RIGHT:
      if (ev == BUTTON_PRESSED) onNav(Dir::Right, BUTTON_PRESSED);
      return true;

    case ButtonActions::ACT_MENU_NAV_ENTER:
      if (ev == BUTTON_PRESSED || ev == BUTTON_RELEASED) onNav(Dir::Enter, BUTTON_PRESSED);
      return true;

    case ButtonActions::ACT_MENU_SELECT:
      if (ev == BUTTON_PRESSED || ev == BUTTON_RELEASED) onNav(Dir::Enter, BUTTON_PRESSED);
      return true;

    case ButtonActions::ACT_MARK_EVENT:
      if (ev == BUTTON_PRESSED || ev == BUTTON_RELEASED) onNav(Dir::Enter, BUTTON_PRESSED);
      return true;

    case ButtonActions::ACT_LOGGING_TOGGLE:
    case ButtonActions::ACT_WEB_TOGGLE:
      touch();
      return true;

    case ButtonActions::ACT_NONE:
    default:
      return false;
  }
}

void MenuSystem::requestOpen() {
  UI::beginModal();
  if (s_state == State::Inactive) {
    MLOG("[MENU] requestOpen -> Inactive -> Main (sel=%u)\n", (unsigned)s_mainSel);
    s_state = State::Main;
    s_mainSel   = 0;
    s_sensorSel = 0;
    s_calUiPhase= CalUiPhase::Idle;
    touch();
    guardEnterRight();          // <-- ADD THIS LINE
    redraw_();
  } else {
    MLOG("[MENU] requestOpen -> already open (%s), bump idle timer\n", stateName(s_state));
    touch();
  }
}

void MenuSystem::requestClose() {
  UI::endModal();
  s_wsPending = false;
  s_lastRangeTrackMs = 0;
  if (s_state != State::Inactive) {
    MLOG("[MENU] requestClose from %s\n", stateName(s_state));
    s_state = State::Inactive;
    UI::clear(UI::TARGET_OLED);

    s_lastWifiSummary = "";

    
    // Query current Wi-Fi status
   // auto st = WiFiManager::status();
    //if (st.wl == WL_CONNECTED) {
    //  String line = "WiFi: " + WiFi.SSID();
     // UI::status(line);
     // } else {
      //   UI::status("Ready");
     // }
  }
}

void MenuSystem::onNav(Dir d, ButtonEvent ev) {
  if (s_state == State::Inactive) return;

  MLOG("[MENU] onNav dir=%s ev=%d state=%s mainSel=%u sensorSel=%u\n",
       dirName(d), (int)ev, stateName(s_state),
       (unsigned)s_mainSel, (unsigned)s_sensorSel);

  if (ev != BUTTON_PRESSED && ev != BUTTON_RELEASED && ev != BUTTON_HELD) {
    touch();
    return;
  }

  touch();

  // If we just changed screens, ignore Enter/Right PRESSED for a brief window
  if ((d == Dir::Enter || d == Dir::Right) &&
      ev == BUTTON_PRESSED &&
      millis() < s_enterGuardUntilMs) {
    return;
  }

  // If we drilled down on PRESSED, ignore the matching RELEASED so it doesn't
  // trigger an action in the new state.
  if (s_swallowEnterRelease &&
      (d == Dir::Enter || d == Dir::Right) &&
      ev == BUTTON_RELEASED) {
    s_swallowEnterRelease = false;
    return;
  }


  switch (s_state) {
    case State::Main: {
      if (d == Dir::Left) { requestClose(); return; }

      const uint8_t N = mainItemCount_();
      if (d == Dir::Up) {
        if (N == 0) return;

        const uint8_t oldSel = s_mainSel;
        s_mainSel = (uint8_t)((s_mainSel + N - 1) % N);

        // Wrap case: 0 -> N-1
        if (oldSel == 0 && s_mainSel == (uint8_t)(N - 1)) {
          s_mainTop = (N > MAIN_VISIBLE_ROWS) ? (uint8_t)(N - MAIN_VISIBLE_ROWS) : 0;
          redraw_();
          return;
        }

        // Keep selection visible
        if (s_mainSel < s_mainTop) s_mainTop = s_mainSel;

        redraw_();
        return;
      }

      if (d == Dir::Down) {
        if (N == 0) return;

        const uint8_t oldSel = s_mainSel;
        s_mainSel = (uint8_t)((s_mainSel + 1) % N);

        // Wrap case: N-1 -> 0
        if (oldSel == (uint8_t)(N - 1) && s_mainSel == 0) {
          s_mainTop = 0;
          redraw_();
          return;
        }

        // Keep selection visible
        if (s_mainSel >= (uint8_t)(s_mainTop + MAIN_VISIBLE_ROWS)) {
          s_mainTop = (uint8_t)(s_mainSel - (MAIN_VISIBLE_ROWS - 1));
        }

        redraw_();
        return;
      }
      if ((d == Dir::Enter || d == Dir::Right) && ev == BUTTON_PRESSED) {
        if (activateCurrentSelection_()) return;
      }
      break;
    }

    case State::SensorsList: {
      const uint8_t n = ConfigManager::sensorCount();
      if (n == 0) { if (d == Dir::Left) { s_state = State::Main; redraw_(); } return; }

      if (d == Dir::Up)    { s_sensorSel = (uint8_t)((s_sensorSel + n - 1) % n); redraw_(); return; }
      if (d == Dir::Down)  { s_sensorSel = (uint8_t)((s_sensorSel + 1) % n);     redraw_(); return; }
      if (d == Dir::Left)  { s_state = State::Main; redraw_(); return; }
      if ((d == Dir::Enter || d == Dir::Right) && ev == BUTTON_PRESSED) {
        if (activateCurrentSelection_()) return;
      }
      break;
    }

    case State::RatePicker: {
      if (d == Dir::Left && (ev == BUTTON_PRESSED || ev == BUTTON_RELEASED)) {
        s_state = State::Main; drawMain_(); return;
      }

      if (ev == BUTTON_PRESSED) {
        if (d == Dir::Up)   { if (s_rateIdx > 0) --s_rateIdx; drawRatePicker_(); return; }
        if (d == Dir::Down) { if (s_rateIdx + 1 < (int)Rates::kCount) ++s_rateIdx; drawRatePicker_(); return; }

        // ✅ Commit on PRESSED (after the guard window), not RELEASED
        if ((d == Dir::Enter || d == Dir::Right) && millis() >= s_enterGuardUntilMs) {
          if (activateCurrentSelection_()) return;
        }
      }
      if ((d == Dir::Enter || d == Dir::Right) && ev == BUTTON_PRESSED) {
        if (activateCurrentSelection_()) return;
      }
      break;
    }


    case State::CalibSensors: {
      const uint8_t n = ConfigManager::sensorCount();
      if (n == 0) { if (d == Dir::Left) { s_state = State::Main; redraw_(); } return; }

      if (d == Dir::Up)    { s_calSel = (uint8_t)((s_calSel + n - 1) % n); drawCalibSensors_(); return; }
      if (d == Dir::Down)  { s_calSel = (uint8_t)((s_calSel + 1) % n);     drawCalibSensors_(); return; }
      if (d == Dir::Left)  { s_state = State::Main; drawMain_(); return; }
      if ((d == Dir::Enter || d == Dir::Right) && ev == BUTTON_PRESSED) {
        if (activateCurrentSelection_()) return;
      }
      break;
    }

    case State::CalibDetail: {
      Sensor* s = SensorManager::at(s_calSel);
      if (!s) { s_state = State::CalibSensors; s_calUiPhase = CalUiPhase::Idle; drawCalibSensors_(); return; }

      // Navigation across rows depends on what's drawn (two rows max)
      uint8_t rowCount = 2;
      if (s_calUiPhase == CalUiPhase::Idle) {
        CalModeMask mask = s->allowedCalMask();
        rowCount = 0;
        if (mask & CAL_ZERO)  ++rowCount;
        if (mask & CAL_RANGE) ++rowCount;
        if (rowCount == 0) rowCount = 1; // "No actions"
      }

      if (d == Dir::Left) {
        s_lastRangeTrackMs = 0;
        s_calUiPhase = CalUiPhase::Idle;   // reset when backing out
        s_state      = State::CalibSensors;
        drawCalibSensors_();
        return;
      }
      if (d == Dir::Up)   { if (s_calOptSel > 0) --s_calOptSel; drawCalibDetail_(); return; }
      if (d == Dir::Down) { if (s_calOptSel + 1 < rowCount) ++s_calOptSel; drawCalibDetail_(); return; }

      // Enter/Right activate the current row in all calibration phases.
      if ((d == Dir::Enter || d == Dir::Right) && ev == BUTTON_PRESSED) {
        if (activateCurrentSelection_()) return;
      }
      break;
    }

    default: break;
  }
}

// Convenience wrappers used by ButtonActions
void MenuSystem::navRight() { onNav(Dir::Right, BUTTON_PRESSED); }
void MenuSystem::navLeft()  { onNav(Dir::Left,  BUTTON_PRESSED); }
void MenuSystem::navUp()    { onNav(Dir::Up,    BUTTON_PRESSED); }
void MenuSystem::navDown()  { onNav(Dir::Down,  BUTTON_PRESSED); }
void MenuSystem::select()   { onNav(Dir::Enter, BUTTON_PRESSED); }

void MenuSystem::loop() {
  if (s_state == State::Inactive) return;

  tickActiveRangeCalibration_();

  if (s_deferRedraw && (long)(millis() - s_deferUiUntilMs) >= 0) {
    s_deferRedraw = false;
    redraw_();
  }

  // Finish web server start once Wi-Fi is ready (or time out)
  if (s_wsPending) {
    auto st = WiFiManager::status();

      if (st.wl == WL_CONNECTED && st.state == WiFiMgrState::ONLINE) {
        // We have a link: try to start the server once
        s_wsPending = false;

        if (WebServerManager::start()) {
          redraw_();            // update label to "WiFi: ON" immediately
        } else {
          UI::toastModal("WiFi fail", 1200, 1);
          // Optional: keep Wi-Fi up, or turn it off:
          // WiFiManager::disable();
          deferUiFor(1200);
          redraw_();
        }
      } else if ((int32_t)(millis() - s_wsDeadlineMs) >= 0) {
        // Timeout: give up cleanly
        s_wsPending = false;
        UI::toastModal("WiFi timeout", 1200, 1);
        deferUiFor(1200);
      redraw_();
    }
  }


  if (millis() - s_lastInputMs >= s_idleCloseMs) {
    MLOG("[MENU] idle-close after %lu ms\n", (unsigned long)s_idleCloseMs);
    requestClose();
  }
}

// Compatibility wrapper for older call sites.
void MenuSystem::onMark() {
  if (!isActive()) return;
  onNav(Dir::Enter, BUTTON_PRESSED);
}
