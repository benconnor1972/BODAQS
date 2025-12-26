#include "Routes_Config.h"
#include <Arduino.h>

#include "HtmlUtil.h"
#include "ConfigManager.h"
#include "SensorManager.h"
#include "SensorRegistry.h"
#include "WiFiManager.h"
#include "WebServerManager.h"
#include "BoardSelect.h"

using namespace HtmlUtil;

// -------------------- Streaming helpers --------------------

static inline void outP(WebServer& srv, const char* p) { srv.sendContent_P(p); }
static inline void outS(WebServer& srv, const String& s) { srv.sendContent(s); }

static inline void outU32(WebServer& srv, uint32_t v) {
  char buf[16];
  ultoa(v, buf, 10);
  srv.sendContent(buf);
}

static inline void outI32(WebServer& srv, int32_t v) {
  char buf[16];
  ltoa(v, buf, 10);
  srv.sendContent(buf);
}

static inline void outAttrEsc(WebServer& srv, const String& s) {
  // attribute-safe escaping
  srv.sendContent(HtmlUtil::htmlEscape(s));
}

static inline void outTextEsc(WebServer& srv, const String& s) {
  // text-safe escaping (same escaping is fine here)
  srv.sendContent(HtmlUtil::htmlEscape(s));
}

static inline void outBoolAttrP(WebServer& srv, bool cond, const char* attrPSTR) {
  if (cond) srv.sendContent_P(attrPSTR);
}

static inline void outIPv4(WebServer& srv, const uint8_t a[4]) {
  char buf[16];
  snprintf(buf, sizeof(buf), "%u.%u.%u.%u", a[0], a[1], a[2], a[3]);
  srv.sendContent(buf);
}

static void sendPageStart(WebServer& srv, const __FlashStringHelper* title) {
  srv.setContentLength(CONTENT_LENGTH_UNKNOWN);
  srv.send(200, F("text/html"), "");

  // Small, self-contained header (no big String build)
  outP(srv, PSTR("<!DOCTYPE html><html><head><meta charset='utf-8'>"
                 "<meta name='viewport' content='width=device-width, initial-scale=1'>"
                 "<title>"));
  outS(srv, String(title));
  outP(srv, PSTR("</title>"
                 "<style>"
                 "body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;"
                 "font-size:14px;line-height:1.35;color:#333;margin:20px}"
                 "h2{margin-top:1.4em;padding-bottom:.2em;border-bottom:1px solid #ccc;font-size:1.1em}"
                 "fieldset{margin:1.2em 0;padding:1em 1.2em;border:1px solid #ddd;border-radius:6px;background:#fafafa}"
                 "legend{font-weight:700;padding:0 6px}"
                 ".row{margin:.4em 0}"
                 "label{display:inline-block;min-width:160px;margin:.2em 0;font-weight:500}"
                 "input,select{margin:.2em 0;padding:.3em .4em;border:1px solid #bbb;border-radius:4px;font-size:.95em}"
                 ".row input[type='checkbox']{margin-left:.5em}"
                 "small{color:#666;margin-left:.3em}"
                 "button{padding:.45em .9em;border:1px solid #999;border-radius:5px;background:#f5f5f5;cursor:pointer}"
                 "button:disabled{opacity:.6;cursor:not-allowed}"
                 "hr{border:none;border-top:1px solid #eee;margin:12px 0}"
                 "</style>"
                 "</head><body>"));
}

static void sendPageEnd(WebServer& srv) {
  outP(srv, PSTR("</body></html>"));
  srv.sendContent(""); // final chunk
}

static void emitEnumOptionsStream(WebServer& srv, const char* choicesCsv, const String& current) {
  String choices(choicesCsv ? choicesCsv : "");
  int start = 0;
  while (true) {
    int comma = choices.indexOf(',', start);
    String opt = (comma >= 0) ? choices.substring(start, comma) : choices.substring(start);
    opt.trim();
    if (opt.length()) {
      outP(srv, PSTR("<option value='"));
      outAttrEsc(srv, opt);
      outP(srv, PSTR("'"));
      if (opt.equalsIgnoreCase(current)) outP(srv, PSTR(" selected"));
      outP(srv, PSTR(">"));
      outTextEsc(srv, opt);
      outP(srv, PSTR("</option>"));
    }
    if (comma < 0) break;
    start = comma + 1;
  }
}

// -------------------- Routes --------------------

void registerConfigRoutes() {

  // -------------------- GET /config --------------------
g_server.on("/config", HTTP_GET, [](){
  auto& srv = g_server;
  WiFiManager::noteUserActivity();

  const LoggerConfig& cfg = ConfigManager::get();
  const bool locked  = !WebServerManager::canStart();
  const bool disAttr = locked;

  sendPageStart(srv, F("Config"));

  // Tabs
  outP(srv, PSTR(
    "<p>"
      "<b>General</b> | "
      "<a href='/config/sensors'>Sensors</a> | "
      "<a href='/config/buttons'>Buttons</a>"
    "</p><hr>"
  ));

  if (srv.hasArg("ok")) {
    outP(srv, PSTR("<p style='background:#e7ffe7;border:1px solid #8bc34a;padding:8px;border-radius:6px'>Saved.</p>"));
  }

  if (locked) {
    outP(srv, PSTR(
      "<p style='background:#fff3cd;border:1px solid #ffe08a;padding:8px;border-radius:6px'>"
      "Logging is active (or not allowed). Editing is disabled. Stop logging to make changes."
      "</p>"
    ));
  }

  if (srv.hasArg("err")) {
    String err = srv.arg("err");
    String net = srv.hasArg("net") ? srv.arg("net") : "";
    String s   = srv.hasArg("sensor") ? srv.arg("sensor") : "";
    String ain = srv.hasArg("ain") ? srv.arg("ain") : "";

    outP(srv, PSTR("<p style='background:#ffe7e7;border:1px solid #e57373;padding:8px;border-radius:6px'>"
                   "<b>Error:</b> "));
    outTextEsc(srv, err);
    if (net.length()) { outP(srv, PSTR(", net=")); outTextEsc(srv, net); }
    if (s.length())   { outP(srv, PSTR(", sensor=")); outTextEsc(srv, s); }
    if (ain.length()) { outP(srv, PSTR(", ain=")); outTextEsc(srv, ain); }
    outP(srv, PSTR("</p>"));
  }

  // ---------- GLOBALS ----------
  outP(srv, PSTR("<h2>Configuration</h2><form method='POST' action='/config'>"));
  outP(srv, PSTR("<input type='hidden' name='submit' value='globals'>"));

  outP(srv, PSTR("<fieldset><legend>General</legend>"));

  // Sample rate
  outP(srv, PSTR("<div class='row'><label>Sample rate (Hz)</label>"
                 "<input type='number' name='sample_rate_hz' min='1' max='2000' value='"));
  outU32(srv, (uint32_t)cfg.sampleRateHz);
  outP(srv, PSTR("'"));
  if (disAttr) outP(srv, PSTR(" disabled"));
  outP(srv, PSTR("></div>"));

  // Timestamp mode
  outP(srv, PSTR("<div class='row'><label>Timestamp mode</label><select name='timestamp_mode'"));
  if (disAttr) outP(srv, PSTR(" disabled"));
  outP(srv, PSTR(">"
                 "<option value='human'"));
  if (cfg.timestampHuman) outP(srv, PSTR(" selected"));
  outP(srv, PSTR(">human</option>"
                 "<option value='fast'"));
  if (!cfg.timestampHuman) outP(srv, PSTR(" selected"));
  outP(srv, PSTR(">fast</option>"
                 "</select></div>"));

  // TZ rule
  outP(srv, PSTR("<div class='row'><label>Timezone (tz rule)</label>"
                 "<input type='text' name='tz' value='"));
  outAttrEsc(srv, String(cfg.tz));
  outP(srv, PSTR("'"));
  if (disAttr) outP(srv, PSTR(" disabled"));
  outP(srv, PSTR("></div>"));

  // NTP server (General)
  outP(srv, PSTR("<div class='row'><label>NTP server</label>"
                 "<input type='text' name='ntp_server' value='"));
  outAttrEsc(srv, String(cfg.ntpServers));   // <-- uses your struct member name
  outP(srv, PSTR("'"));
  if (disAttr) outP(srv, PSTR(" disabled"));
  outP(srv, PSTR("></div>"));

  // Debounce
  outP(srv, PSTR("<div class='row'><label>Debounce (ms)</label>"
                 "<input type='number' name='debounce_ms' min='0' max='1000' value='"));
  outU32(srv, (uint32_t)cfg.debounceMs);
  outP(srv, PSTR("'"));
  if (disAttr) outP(srv, PSTR(" disabled"));
  outP(srv, PSTR("></div>"));

  outP(srv, PSTR("</fieldset>"));

  // ---------- Wi-Fi ----------
  outP(srv, PSTR("<fieldset><legend>Network</legend>"
                 "<h4>Wi-Fi (multi-network)</h4>"));

  // wifi_enabled_default
  outP(srv, PSTR("<div class='row'><label>Enable Wi-Fi by default</label>"
                 "<input type='hidden' name='wifi_enabled_default' value='false'>"
                 "<input type='checkbox' name='wifi_enabled_default' value='true'"));
  if (cfg.wifiEnabledDefault) outP(srv, PSTR(" checked"));
  if (disAttr) outP(srv, PSTR(" disabled"));
  outP(srv, PSTR("></div>"));

  // wifi_auto_time_on_rtc_invalid
  outP(srv, PSTR("<div class='row'><label>Auto-enable Wi-Fi if RTC invalid</label>"
                 "<input type='hidden' name='wifi_auto_time_on_rtc_invalid' value='false'>"
                 "<input type='checkbox' name='wifi_auto_time_on_rtc_invalid' value='true'"));
  if (cfg.wifiAutoTimeOnRtcInvalid) outP(srv, PSTR(" checked"));
  if (disAttr) outP(srv, PSTR(" disabled"));
  outP(srv, PSTR("></div>"));

  outP(srv, PSTR("<h4>Saved networks</h4>"));

  for (uint8_t i = 0; i < 5; ++i) {
    const auto& net = cfg.wifi[i];

    outP(srv, PSTR("<fieldset><legend>Wi-Fi slot "));
    outU32(srv, i + 1);
    outP(srv, PSTR("</legend>"));

    // SSID
    outP(srv, PSTR("<div class='row'><label>SSID</label><input type='text' name='wifi"));
    outU32(srv, i);
    outP(srv, PSTR(".ssid' value='"));
    outAttrEsc(srv, String(net.ssid));
    outP(srv, PSTR("'"));
    if (disAttr) outP(srv, PSTR(" disabled"));
    outP(srv, PSTR("></div>"));

    // Password
    outP(srv, PSTR("<div class='row'><label>Password</label><input type='password' name='wifi"));
    outU32(srv, i);
    outP(srv, PSTR(".password' value='"));
    outAttrEsc(srv, String(net.password));
    outP(srv, PSTR("'"));
    if (disAttr) outP(srv, PSTR(" disabled"));
    outP(srv, PSTR("></div>"));

    // ... keep the rest of your fields as-is ...

    outP(srv, PSTR("</fieldset>"));
    delay(0);
  }

  outP(srv, PSTR("</fieldset>"));

  outP(srv, PSTR("<p><button type='submit'"));
  if (disAttr) outP(srv, PSTR(" disabled"));
  outP(srv, PSTR(">Save</button></p></form>"));

  outP(srv, PSTR("<p><a href='/'>Home</a> &nbsp; <a href='/files'>Files</a></p>"));

  sendPageEnd(srv);
});


// -------------------- GET /config/buttons --------------------
g_server.on("/config/buttons", HTTP_GET, [](){
  auto& srv = g_server;
  WiFiManager::noteUserActivity();

  const LoggerConfig& cfg = ConfigManager::get();
  const bool locked = !WebServerManager::canStart();

  sendPageStart(srv, F("Buttons"));

  outP(srv, PSTR(
    "<p>"
      "<a href='/config'>General</a> | "
      "<a href='/config/sensors'>Sensors</a> | "
      "<b>Buttons</b>"
    "</p><hr>"
  ));

  if (srv.hasArg("ok")) {
    outP(srv, PSTR(
      "<p style='background:#e7ffe7;border:1px solid #8bc34a;padding:8px;border-radius:6px'>Saved.</p>"
    ));
  }
  if (locked) {
    outP(srv, PSTR(
      "<p style='background:#fff3cd;border:1px solid #ffe08a;padding:8px;border-radius:6px'>"
      "Editing is disabled while logging."
      "</p>"
    ));
  }

  outP(srv, PSTR("<form method='POST' action='/config/buttons'>"));

  outP(srv, PSTR(
    "<fieldset><legend>Button bindings</legend>"
    "<p><small>"
      "Each row maps a (button ID, event) pair to an action. "
      "Events: pressed, released, click, double_click, held. "
      "Actions: logging_toggle, mark_event, web_toggle, menu_nav_up/down/left/right/enter."
    "</small></p>"
  ));

  for (uint8_t i = 0; i < MAX_BUTTON_BINDINGS; ++i) {
    const ButtonBindingDef& bd =
      (i < cfg.buttonBindingCount) ? cfg.buttonBindings[i] : ButtonBindingDef{};

    outP(srv, PSTR("<div class='row'><label>Binding "));
    outU32(srv, i);
    outP(srv, PSTR("</label>"));

    // buttonId
    outP(srv, PSTR("<input type='text' size='10' placeholder='button id' name='binding"));
    outU32(srv, i);
    outP(srv, PSTR(".button' value='"));
    outAttrEsc(srv, bd.buttonId);
    outP(srv, PSTR("'"));
    if (locked) outP(srv, PSTR(" disabled"));
    outP(srv, PSTR("> "));

    // event
    outP(srv, PSTR("<input type='text' size='10' placeholder='event' name='binding"));
    outU32(srv, i);
    outP(srv, PSTR(".event' value='"));
    outAttrEsc(srv, bd.event);
    outP(srv, PSTR("'"));
    if (locked) outP(srv, PSTR(" disabled"));
    outP(srv, PSTR("> "));

    // action
    outP(srv, PSTR("<input type='text' size='20' placeholder='action' name='binding"));
    outU32(srv, i);
    outP(srv, PSTR(".action' value='"));
    outAttrEsc(srv, bd.action);
    outP(srv, PSTR("'"));
    if (locked) outP(srv, PSTR(" disabled"));
    outP(srv, PSTR("></div>"));

    delay(0);
  }

  outP(srv, PSTR("</fieldset>"));

  outP(srv, PSTR("<p><button type='submit'"));
  if (locked) outP(srv, PSTR(" disabled"));
  outP(srv, PSTR(">Save</button></p>"));

  outP(srv, PSTR("</form>"));

  outP(srv, PSTR("<p><a href='/'>Home</a> &nbsp; <a href='/files'>Files</a></p>"));

  sendPageEnd(srv);
});

  // -------------------- GET /config/sensors (STREAMING) --------------------
g_server.on("/config/sensors", HTTP_GET, [](){
  auto& srv = g_server;
  WiFiManager::noteUserActivity();

  const LoggerConfig& cfg = ConfigManager::get();
  const bool locked = !WebServerManager::canStart();

  sendPageStart(srv, F("Sensors"));

  outP(srv, PSTR("<p><a href='/config'>General</a> | <b>Sensors</b> | <a href='/config/buttons'>Buttons</a></p><hr>"));

  if (srv.hasArg("ok")) {
    outP(srv, PSTR("<p style='background:#e7ffe7;border:1px solid #8bc34a;padding:8px;border-radius:6px'>Saved.</p>"));
  }
  if (locked) {
    outP(srv, PSTR("<p style='background:#fff3cd;border:1px solid #ffe08a;padding:8px;border-radius:6px'>"
                   "Editing is disabled while logging.</p>"));
  }

  outP(srv, PSTR("<form method='POST' action='/config/sensors'>"));
  outP(srv, PSTR("<h2>Sensors</h2>"));

  const uint8_t n = cfg.sensorCount();
  if (n == 0) {
    outP(srv, PSTR("<p><em>No sensors configured.</em></p>"));
  } else {
    for (uint8_t i = 0; i < n; ++i) {
      SensorSpec sp;
      if (!cfg.getSensorSpec(i, sp)) continue;
      const SensorTypeInfo* ti = SensorRegistry::lookup(sp.type);

      const char* typeLbl = SensorRegistry::typeLabel(sp.type);
      // NOTE: we no longer pre-escape here; we stream-escape at write time.
      const String typeLabelStr = String(typeLbl ? typeLbl : "Unknown Sensor");

      // ParamDefs helpers
      size_t defCount = 0;
      const ParamDef* defs = ti ? ti->paramDefs(defCount) : nullptr;

      auto findDef = [&](const char* key)->const ParamDef* {
        if (!defs) return nullptr;
        for (size_t d = 0; d < defCount; ++d) {
          if (strcasecmp(defs[d].key, key) == 0) return &defs[d];
        }
        return nullptr;
      };

      auto currentValAsString = [&](const ParamDef* pd)->String {
        String val;
        if (!pd) return val;
        if      (pd->type == ParamType::Bool)  { bool b=false;  sp.params.getBool(pd->key, b);  val = b ? "true" : "false"; }
        else if (pd->type == ParamType::Int)   { long v=0;      sp.params.getInt(pd->key, v);   val = String(v); }
        else if (pd->type == ParamType::Float) { double f=0.0;  sp.params.getFloat(pd->key, f); val = String(f, 6); }
        else { String s; sp.params.get(pd->key, s); val = s; }
        return val;
      };

      auto emitParamRow = [&](const char* key, const char* labelOverride = nullptr) {
        const ParamDef* pd = findDef(key);
        if (!pd) return;

        const String label = labelOverride ? String(labelOverride) : String(pd->key);
        const String field = String("s") + i + "." + key;

        outP(srv, PSTR("<div class='row'><label>"));
        outTextEsc(srv, label);
        outP(srv, PSTR("</label>"));

        if (pd->type == ParamType::Bool) {
          String val = currentValAsString(pd);
          outP(srv, PSTR("<input type='hidden' name='"));
          outAttrEsc(srv, field);
          outP(srv, PSTR("' value='false'>"));
          outP(srv, PSTR("<input type='checkbox' name='"));
          outAttrEsc(srv, field);
          outP(srv, PSTR("' value='true'"));
          if (val.equalsIgnoreCase("true")) outP(srv, PSTR(" checked"));
          if (locked) outP(srv, PSTR(" disabled"));
          outP(srv, PSTR(">"));
        } else if (pd->type == ParamType::Enum && pd->choices) {
          String val = currentValAsString(pd);
          outP(srv, PSTR("<select name='"));
          outAttrEsc(srv, field);
          outP(srv, PSTR("'"));
          if (locked) outP(srv, PSTR(" disabled"));
          outP(srv, PSTR(">"));
          emitEnumOptionsStream(srv, pd->choices, val);
          outP(srv, PSTR("</select>"));
        } else {
          String val = currentValAsString(pd);
          outP(srv, PSTR("<input type='text' name='"));
          outAttrEsc(srv, field);
          outP(srv, PSTR("' value='"));
          outAttrEsc(srv, val);
          outP(srv, PSTR("'"));
          if (locked) outP(srv, PSTR(" disabled"));
          outP(srv, PSTR(">"));
        }

        if (pd->help) {
          outP(srv, PSTR(" <small>"));
          outP(srv, pd->help); // help is const char* from your registry; assumed safe
          outP(srv, PSTR("</small>"));
        }

        outP(srv, PSTR("</div>"));
      };

      // Fieldset
      const char* dispName = (sp.name && sp.name[0]) ? sp.name : "sensor";

      outP(srv, PSTR("<fieldset><legend>"));
      outTextEsc(srv, String(dispName));
      outP(srv, PSTR(" — "));
      // use streaming escape instead of pre-escaped String
      outTextEsc(srv, typeLabelStr);
      outP(srv, PSTR("</legend>"));

      // Basic
      outP(srv, PSTR("<h4>Basic</h4>"));

      // Name
      outP(srv, PSTR("<div class='row'><label>Name</label><input type='text' name='s"));
      outU32(srv, i);
      outP(srv, PSTR(".name' value='"));
      outAttrEsc(srv, String(sp.name));
      outP(srv, PSTR("'"));
      if (locked) outP(srv, PSTR(" disabled"));
      outP(srv, PSTR("></div>"));

      // Type display (read-only)
      outP(srv, PSTR("<div class='row'><label>Type</label><input type='text' value='"));
      outTextEsc(srv, typeLabelStr);
      outP(srv, PSTR("' disabled></div>"));

      // AIN selector if defined
      {
        const ParamDef* pd = findDef("ain");
        if (pd) {
          long curAin = -1;
          sp.params.getInt("ain", curAin);

          outP(srv, PSTR("<div class='row'><label>Analog input</label>"));

          if (!board::gBoard) {
            outP(srv, PSTR("<em>No active board profile</em>"));
          } else {
            const auto& bp = *board::gBoard;
            if (bp.analog.count == 0) {
              outP(srv, PSTR("<em>No analog inputs on this board</em>"));
            } else {
              outP(srv, PSTR("<select name='s"));
              outU32(srv, i);
              outP(srv, PSTR(".ain'"));
              if (locked) outP(srv, PSTR(" disabled"));
              outP(srv, PSTR(">"));

              outP(srv, PSTR("<option value='-1'"));
              if (curAin < 0) outP(srv, PSTR(" selected"));
              outP(srv, PSTR(">-- select --</option>"));

              for (uint8_t ai = 0; ai < bp.analog.count; ++ai) {
                const int pin = bp.analog.pins[ai];
                if (pin < 0) continue;

                outP(srv, PSTR("<option value='"));
                outU32(srv, ai);
                outP(srv, PSTR("'"));
                if ((long)ai == curAin) outP(srv, PSTR(" selected"));
                outP(srv, PSTR(">AIN"));
                outU32(srv, ai);
                outP(srv, PSTR(" (GPIO"));
                outI32(srv, pin);
                outP(srv, PSTR(")</option>"));
              }

              outP(srv, PSTR("</select>"));
            }
          }

          outP(srv, PSTR("</div>"));
        }
      }

      // muted
      {
        outP(srv, PSTR("<div class='row'><label>Muted by default</label>"
                       "<input type='hidden' name='s"));
        outU32(srv, i);
        outP(srv, PSTR(".muted' value='false'>"
                       "<input type='checkbox' name='s"));
        outU32(srv, i);
        outP(srv, PSTR(".muted' value='true'"));
        if (sp.mutedDefault) outP(srv, PSTR(" checked"));
        if (locked) outP(srv, PSTR(" disabled"));
        outP(srv, PSTR("></div>"));
      }

      // Output
      outP(srv, PSTR("<h4>Output</h4>"));

      // output_mode if defined
      {
        const ParamDef* pdOM = findDef("output_mode");
        if (pdOM) {
          int om = (int)OutputMode::RAW;
          long vi;
          if (sp.params.getInt("output_mode", vi)) om = (int)vi;

          outP(srv, PSTR("<div class='row'><label>Output mode</label><select name='s"));
          outU32(srv, i);
          outP(srv, PSTR(".output_mode'"));
          if (locked) outP(srv, PSTR(" disabled"));
          outP(srv, PSTR(">"));

          auto opt = [&](int v, const char* label){
            outP(srv, PSTR("<option value='"));
            outI32(srv, v);
            outP(srv, PSTR("'"));
            if (om == v) outP(srv, PSTR(" selected"));
            outP(srv, PSTR(">"));
            outP(srv, label);
            outP(srv, PSTR("</option>"));
          };
          opt((int)OutputMode::RAW,    "RAW");
          opt((int)OutputMode::LINEAR, "LINEAR");
          opt((int)OutputMode::POLY,   "POLY");
          opt((int)OutputMode::LUT,    "LUT");

          outP(srv, PSTR("</select></div>"));
        }
      }

      emitParamRow("include_raw", "Include raw column");
      emitParamRow("sensor_full_travel_mm", "Sensor full travel (mm)");
      emitParamRow("units_label", "Units label");

      // Transform picker block (JS will populate)
      {
        // preselect from live sensor if present
        const uint8_t liveN = SensorManager::count();
        String currentId;
        for (uint8_t j = 0; j < liveN; ++j) {
          Sensor* ss = SensorManager::get(j);
          if (ss && String(ss->name()) == String(dispName)) { currentId = ss->selectedTransformId(); break; }
        }

        outP(srv, PSTR("<div class='row tr-block' data-sensor='"));
        outAttrEsc(srv, String(dispName));
        outP(srv, PSTR("' data-current='"));
        outAttrEsc(srv, currentId);
        outP(srv, PSTR("'>"
                       "<label>Output transform</label>"
                       "<select name='s"));
        outU32(srv, i);
        outP(srv, PSTR(".output_id'></select> "
                       "<button class='apply'"));
        if (locked) outP(srv, PSTR(" disabled"));
        outP(srv, PSTR(">Apply</button> "
                       "<button class='reload'"));
        if (locked) outP(srv, PSTR(" disabled"));
        outP(srv, PSTR(">Reload</button> "
                       "<span class='status' style='margin-left:8px;color:#060'></span>"
                       "</div>"));
      }

      // Calibration
      outP(srv, PSTR("<h4>Calibration</h4>"));

      {
        CalModeMask allowMask2 = ConfigManager::calAllowedMaskByIndex(i);
        String calCsv;
        if (allowMask2 != 0xFF) {
          if (allowMask2 & CAL_ZERO)  { if (calCsv.length()) calCsv += ","; calCsv += "ZERO"; }
          if (allowMask2 & CAL_RANGE) { if (calCsv.length()) calCsv += ","; calCsv += "RANGE"; }
          if (!calCsv.length()) calCsv = "NONE";
        }

        outP(srv, PSTR("<div class='row'><label>Calibration methods</label>"
                       "<input type='text' name='s"));
        outU32(srv, i);
        outP(srv, PSTR(".cal_allowed' placeholder='ZERO,RANGE' value='"));
        outAttrEsc(srv, calCsv);
        outP(srv, PSTR("'"));
        if (locked) outP(srv, PSTR(" disabled"));
        outP(srv, PSTR(">"
                       "<small>Leave blank to inherit type-supported methods.</small>"
                       "</div>"));
      }

      emitParamRow("sensor_zero_count", "Sensor zero count");
      emitParamRow("sensor_full_count", "Sensor full count");
      emitParamRow("invert", "Invert direction");

      // Smoothing
      outP(srv, PSTR("<h4>Smoothing</h4>"));
      emitParamRow("ema_alpha", "EMA alpha");
      emitParamRow("deadband",  "Deadband");

      // Other params (defined by type but not already shown)
      const char* shown[] = {
        "ain","muted",
        "output_mode","include_raw","sensor_full_travel_mm","units_label",
        "cal_allowed","sensor_zero_count","sensor_full_count","invert",
        "ema_alpha","deadband"
      };
      auto isShown = [&](const char* key)->bool{
        for (size_t k=0;k<sizeof(shown)/sizeof(shown[0]);++k){
          if (strcasecmp(shown[k], key)==0) return true;
        }
        return false;
      };

      bool printedOther = false;
      if (defs) {
        for (size_t d = 0; d < defCount; ++d) {
          const ParamDef& pd = defs[d];
          if (isShown(pd.key)) continue;
          if (strcasecmp(pd.key, "name")==0 || strcasecmp(pd.key, "type")==0) continue;

          if (!printedOther) { outP(srv, PSTR("<h4>Other</h4>")); printedOther = true; }
          emitParamRow(pd.key, pd.key);
          delay(0);
        }
      }

      outP(srv, PSTR("</fieldset>"));
      delay(0);
    }

    // Transform UI script (as-is, streamed)
    outP(srv, PSTR(
      "<script>\n"
      "document.addEventListener('DOMContentLoaded',function(){\n"
      "  function pickListShape(j){ var a=j.transforms||j.items||j.options||j.results||j.choices||j; if(Array.isArray(a)) return a; return [];"
      " }\n"
      "  function populate(block, forcedMode){\n"
      "    var sensor = block.getAttribute('data-sensor')||'';\n"
      "    var current= block.getAttribute('data-current')||'';\n"
      "    var sel    = block.querySelector('select'); if(!sel) return;\n"
      "    var url = '/api/transforms/list?sensor='+encodeURIComponent(sensor)+'&_t='+Date.now();\n"
      "    if(forcedMode!=null && forcedMode!=='') url += '&mode='+encodeURIComponent(forcedMode);\n"
      "    fetch(url,{cache:'no-store'}).then(function(r){return r.json();}).then(function(j){\n"
      "      sel.innerHTML=''; pickListShape(j).forEach(function(t){\n"
      "        var id=t.id||t.value||''; var label=(t.label||t.name||t.text||id||'?');\n"
      "        if(t.type){ label+=' ('+t.type+(t.out_units?(', '+t.out_units):'')+')'; }\n"
      "        var o=document.createElement('option'); o.value=id; o.textContent=label; if(current===id) o.selected=true; sel.appendChild(o);\n"
      "      });\n"
      "    }).catch(function(e){ console.error('load list',e); });\n"
      "  }\n"
      "  window.__xf_onModeChange=function(sensor,mode){\n"
      "    var block=[].find.call(document.querySelectorAll('.tr-block'),function(el){return el.dataset&&el.dataset.sensor===sensor;});\n"
      "    if(!block) return; block.dataset.current='identity'; populate(block, mode);\n"
      "  };\n"
      "  function getCurrentModeForSensor(sensor){\n"
      "    var inputs = document.querySelectorAll('input[name$=\".name\"]');\n"
      "    for (var i=0;i<inputs.length;i++){\n"
      "      if ((inputs[i].value||'')===sensor){ var name = inputs[i].getAttribute('name'); var m = name && name.match(/^s(\\d+)\\.name$/);\n"
      "        if (!m) break; var idx = m[1]; var sel = document.querySelector('select[name=\"s'+idx+'.output_mode\"]'); if (sel) return sel.value;\n"
      "        var radios = document.querySelectorAll('input[type=radio][name=\"s'+idx+'.output_mode\"]');\n"
      "        for (var r=0;r<radios.length;r++){ if (radios[r].checked) return radios[r].value; }\n"
      "        var txt = document.querySelector('input[name=\"s'+idx+'.output_mode\"]'); if (txt) return txt.value; break; }\n"
      "    }\n"
      "    return '';\n"
      "  }\n"
      "  document.querySelectorAll('.reload').forEach(function(btn){\n"
      "    btn.addEventListener('click', function(ev){ ev.preventDefault();\n"
      "      var block = btn.closest('.tr-block'); var sensor = block && block.dataset ? block.dataset.sensor : '';\n"
      "      var status = block ? block.querySelector('.status') : null;\n"
      "      fetch('/api/transforms/reload',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'sensor='+encodeURIComponent(sensor)})\n"
      "        .then(function(r){return r.json();}).then(function(j){\n"
      "          if(j && j.ok){ var mode = getCurrentModeForSensor(sensor); block.dataset.current='identity'; populate(block, mode);\n"
      "            if(status){ status.style.color='#060'; status.textContent='Reloaded ✔'; }\n"
      "            setTimeout(function(){ if(status) status.textContent=''; },1200);\n"
      "          } else { if(status){ status.style.color='#900'; status.textContent='Error'; } }\n"
      "        })\n"
      "        .catch(function(){ if(status){ status.style.color='#900'; status.textContent='Error'; } });\n"
      "    });\n"
      "  });\n"
      "  Array.prototype.forEach.call(document.querySelectorAll('.tr-block'), function(b){ populate(b); });\n"
      "  document.addEventListener('change',function(ev){ var n=(ev.target&&ev.target.name)||''; var m=n.match(/^s(\\d+)\\.output_mode$/); if(!m) return;\n"
      "    var idx=m[1]; var newMode=ev.target.value; var nameEl=document.querySelector('input[name=\"s'+idx+'.name\"]'); if(!nameEl) return;\n"
      "    var sensor=nameEl.value||''; var block=Array.prototype.find.call(document.querySelectorAll('.tr-block'),function(el){return el.dataset&&el.dataset.sensor===sensor;});\n"
      "    if(block){ block.dataset.current='identity'; populate(block, newMode); }\n"
      "  });\n"
      "  document.querySelectorAll('button.apply').forEach(function(btn){\n"
      "    btn.addEventListener('click', function(ev){ ev.preventDefault();\n"
      "      var block = btn.closest('.tr-block'); if(!block) return;\n"
      "      var sensor = block.dataset ? block.dataset.sensor : '';\n"
      "      var sel = block.querySelector('select'); if(!sel) return;\n"
      "      var status = block.querySelector('.status');\n"
      "      var body = 'sensor='+encodeURIComponent(sensor)+'&id='+encodeURIComponent(sel.value||'');\n"
      "      fetch('/api/transforms/apply',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:body})\n"
      "        .then(function(r){return r.json();}).then(function(j){\n"
      "          if(j && j.ok){ block.dataset.current = sel.value||''; if(status){ status.style.color='#060'; status.textContent='Applied ✔'; }\n"
      "            setTimeout(function(){ if(status) status.textContent=''; },1200);\n"
      "          } else { if(status){ status.style.color='#900'; status.textContent='Error'; } }\n"
      "        }).catch(function(){ if(status){ status.style.color='#900'; status.textContent='Error'; } });\n"
      "    });\n"
      "  });\n"
      "});\n"
      "</script>\n"
    ));
  }

  outP(srv, PSTR("<p><button type='submit'"));
  if (locked) outP(srv, PSTR(" disabled"));
  outP(srv, PSTR(">Save Sensors</button></p></form>"));

  outP(srv, PSTR("<p><a href='/'>Home</a> &nbsp; <a href='/files'>Files</a></p>"));

  sendPageEnd(srv);
});


  // -------------------- POST /config/buttons --------------------
  g_server.on("/config/buttons", HTTP_POST, [](){
    auto& srv = g_server;
    WiFiManager::noteUserActivity();

    if (!WebServerManager::canStart()) {
      srv.send(423, F("text/plain"), F("Locked while logging"));
      return;
    }

    LoggerConfig tmp = ConfigManager::get();

    // Clear existing bindings
    tmp.buttonBindingCount = 0;
    for (uint8_t i = 0; i < MAX_BUTTON_BINDINGS; ++i) {
      tmp.buttonBindings[i].buttonId[0] = '\0';
      tmp.buttonBindings[i].event[0]    = '\0';
      tmp.buttonBindings[i].action[0]   = '\0';
    }

    auto getArgLast = [&](const char* key, String& out) -> bool {
      bool found = false;
      const int ac = srv.args();
      for (int ai = 0; ai < ac; ++ai) {
        if (srv.argName(ai) == key) { out = srv.arg(ai); found = true; }
      }
      return found;
    };

    uint8_t newBindingCount = 0;

    for (uint8_t i = 0; i < MAX_BUTTON_BINDINGS; ++i) {
      char keyBtn[28], keyEvt[28], keyAct[28];
      snprintf(keyBtn, sizeof(keyBtn), "binding%u.button", (unsigned)i);
      snprintf(keyEvt, sizeof(keyEvt), "binding%u.event",  (unsigned)i);
      snprintf(keyAct, sizeof(keyAct), "binding%u.action", (unsigned)i);

      String button, ev, act;

      bool hb = getArgLast(keyBtn, button);
      bool he = getArgLast(keyEvt, ev);
      bool ha = getArgLast(keyAct, act);
      if (!(hb || he || ha)) continue;

      button.trim(); ev.trim(); act.trim();

      if (!button.length() && !ev.length() && !act.length()) continue;

      ButtonBindingDef bd{};

      if (button.length() >= (int)sizeof(bd.buttonId))
        button = button.substring(0, sizeof(bd.buttonId) - 1);
      button.toCharArray(bd.buttonId, sizeof(bd.buttonId));

      if (ev.length() >= (int)sizeof(bd.event))
        ev = ev.substring(0, sizeof(bd.event) - 1);
      ev.toCharArray(bd.event, sizeof(bd.event));

      if (act.length() >= (int)sizeof(bd.action))
        act = act.substring(0, sizeof(bd.action) - 1);
      act.toCharArray(bd.action, sizeof(bd.action));

      if (newBindingCount < MAX_BUTTON_BINDINGS) {
        tmp.buttonBindings[newBindingCount++] = bd;
      }
    }

    tmp.buttonBindingCount = newBindingCount;

    ConfigManager::save(tmp);
    HtmlUtil::sendRedirect303(srv, String("/config/buttons?ok=1"));

  });

  // -------------------- POST /config/sensors --------------------
g_server.on("/config/sensors", HTTP_POST, [](){
  auto& srv = g_server;
  WiFiManager::noteUserActivity();

  if (!WebServerManager::canStart()) {
    srv.send(423, F("text/plain"), F("Locked while logging"));
    return;
  }

  LoggerConfig tmp = ConfigManager::get();

  const LoggerConfig& current = ConfigManager::get();
  const uint8_t count = current.sensorCount();

  for (uint8_t idx = 0; idx < count; ++idx) {
    SensorSpec sp;
    if (!current.getSensorSpec(idx, sp)) continue;

    const String pfx = String("s") + idx + ".";

    auto getArgLast = [&](const char* key, String& out) -> bool {
      const String full = pfx + key;
      bool found = false; const int ac = srv.args();
      for (int ai = 0; ai < ac; ++ai) {
        if (srv.argName(ai) == full) { out = srv.arg(ai); found = true; }
      }
      return found;
    };
    auto getBoolLast = [&](const char* key, bool& out)->bool{
      String v; if (!getArgLast(key, v)) return false; v.trim(); v.toLowerCase();
      out = (v=="true"||v=="1"||v=="on"); return true;
    };

    // Basic
    {
      String v;
      if (getArgLast("name", v)) {
        v.trim();
        if (v.length()) {
          v.toCharArray(sp.name, sizeof(sp.name));
          v.toCharArray(tmp.sensors[idx].name, sizeof(tmp.sensors[idx].name));
        }
      }
      bool mb=false;
      if (getBoolLast("muted", mb)) {
        sp.mutedDefault = mb;
        tmp.sensors[idx].mutedDefault = mb;
      }
    }

    // AIN
    {
      String v;
      if (getArgLast("ain", v)) {
        v.trim();
        long ain = v.toInt();

        bool ok = true;
        if (!board::gBoard) ok = false;
        else {
          const auto& bp = *board::gBoard;
          if (ain < 0 || ain >= (long)bp.analog.count) ok = false;
          else if (bp.analog.pins[(uint8_t)ain] < 0) ok = false;
        }

        if (!ok) {
          String url = "/config?err=invalid_ain&sensor=" + String((int)idx)
                     + "&ain=" + String((int)ain);
          HtmlUtil::sendRedirect303(srv, url);
          return;
        }

        sp.params.setInt("ain", ain);
        ConfigManager::saveSensorParamByIndex(idx, "ain", String((int)ain));
      }
    }

    // Output
    {
      String v;

      long oldOm = 0; sp.params.getInt("output_mode", oldOm);
      long newOm = oldOm; bool omChanged = false;

      if (getArgLast("output_mode", v)) {
        v.trim(); v.toUpperCase();
        long vi = v.toInt();
        if      (v=="RAW"||vi==0) newOm=0;
        else if (v=="LINEAR"||vi==1) newOm=1;
        else if (v=="POLY"||vi==2) newOm=2;
        else if (v=="LUT"||vi==3) newOm=3;
        if (newOm != oldOm) omChanged = true;
        sp.params.setInt("output_mode", newOm);
      }

      { bool inc=false; if (getBoolLast("include_raw", inc)) sp.params.setBool("include_raw", inc); }
      if (getArgLast("units_label", v))           sp.params.set("units_label", v);
      if (getArgLast("sensor_full_travel_mm", v)) sp.params.set("sensor_full_travel_mm", v);

      if (getArgLast("output_id", v)) {
        v.trim();
        sp.params.set("output_id", v);
        ConfigManager::saveSensorParamByIndex(idx, "output_id", v);
      }
      sp.params.setBool("__om_changed", omChanged);
    }

    // Calibration
    {
      String v;
      if (getArgLast("cal_allowed", v)) {
        CalModeMask m = 0xFF; v.trim();
        if (v.length()) {
          m = 0; int start=0;
          while (start < v.length()) {
            int comma = v.indexOf(',', start);
            String tok = (comma < 0) ? v.substring(start) : v.substring(start, comma);
            tok.trim(); tok.toUpperCase();
            if      (tok == "ZERO")  m |= CAL_ZERO;
            else if (tok == "RANGE") m |= CAL_RANGE;
            start = (comma < 0) ? v.length() : comma + 1;
          }
        }
        ConfigManager::setCalAllowedByIndex(idx, m);
      }
      if (getArgLast("sensor_zero_count", v)) { long vi = v.toInt(); sp.params.setInt("sensor_zero_count", vi); }
      if (getArgLast("sensor_full_count", v)) { long vi = v.toInt(); sp.params.setInt("sensor_full_count", vi); }
      { bool inv=false; if (getBoolLast("invert", inv)) sp.params.setBool("invert", inv); }
    }

    // Smoothing
    {
      String v;
      if (getArgLast("ema_alpha", v)) { double f = v.toFloat(); sp.params.setFloat("ema_alpha", (float)f); }
      if (getArgLast("deadband", v))  { long   i = v.toInt();  sp.params.setInt("deadband", (long)i); }
    }

    // Generic ParamDefs pass
    int ac = srv.args();
    for (int ai = 0; ai < ac; ++ai) {
      const String argName = srv.argName(ai);
      if (!argName.startsWith(pfx)) continue;
      const String pkey = argName.substring(pfx.length());
      const String val  = srv.arg(ai);

      if (pkey.equalsIgnoreCase("name") || pkey.equalsIgnoreCase("muted") ||
          pkey.equalsIgnoreCase("output_mode") || pkey.equalsIgnoreCase("include_raw") ||
          pkey.equalsIgnoreCase("sensor_full_travel_mm") || pkey.equalsIgnoreCase("units_label") ||
          pkey.equalsIgnoreCase("cal_allowed") || pkey.equalsIgnoreCase("sensor_zero_count") ||
          pkey.equalsIgnoreCase("sensor_full_count") || pkey.equalsIgnoreCase("invert") ||
          pkey.equalsIgnoreCase("ema_alpha")  || pkey.equalsIgnoreCase("deadband") ||
          pkey.equalsIgnoreCase("ain") || pkey.equalsIgnoreCase("output_id")) {
        continue;
      }

      const SensorTypeInfo* ti = SensorRegistry::lookup(sp.type);
      if (!ti) continue;
      size_t defCount = 0;
      const ParamDef* defs = ti->paramDefs(defCount);

      const ParamDef* def = nullptr;
      for (size_t d = 0; d < defCount; ++d) {
        if (pkey.equalsIgnoreCase(defs[d].key)) { def = &defs[d]; break; }
      }
      if (!def) continue;

      bool ok = true;
      switch (def->type) {
        case ParamType::Bool:  ok = sp.params.setBool (pkey.c_str(), (val=="true"||val=="on"||val=="1")); break;
        case ParamType::Int:   ok = sp.params.setInt  (pkey.c_str(), val.toInt());                         break;
        case ParamType::Float: ok = sp.params.setFloat(pkey.c_str(), (float)val.toFloat());               break;
        default:               ok = sp.params.set     (pkey.c_str(), val);                                break;
      }
      if (!ok) Serial.printf("[WEB] set param failed: s%u.%s\n", (unsigned)idx, pkey.c_str());
    }

    ConfigManager::setSensorHeaderByIndex(idx, sp);

    // Push into live sensor
    Sensor* live = nullptr;
    for (uint8_t j = 0; j < SensorManager::count(); ++j) {
      Sensor* s = SensorManager::get(j);
      if (s && String(s->name()) == String(sp.name)) { live = s; break; }
    }
    if (live) {
      live->setMuted(sp.mutedDefault);

      long om = 0; sp.params.getInt("output_mode", om);
      live->setOutputMode((OutputMode)om);

      bool inc = false; sp.params.getBool("include_raw", inc);
      live->setIncludeRaw(inc);

      String u; sp.params.get("units_label", u);
      if ((OutputMode)om == OutputMode::RAW) u = "counts";
      live->setOutputUnitsLabel(u.c_str());

      bool omChanged = false;
      sp.params.getBool("__om_changed", omChanged);
      if (omChanged) {
        if ((OutputMode)om == OutputMode::RAW) {
          live->setOutputUnitsLabel("counts");
        } else if ((OutputMode)om == OutputMode::LINEAR) {
          String explicitLabel; sp.params.get("units_label", explicitLabel);
          live->setOutputUnitsLabel(explicitLabel.c_str());
        } else {
          // POLY/LUT: label from transform metadata (handled elsewhere)
        }
      }
    }
  }

  ConfigManager::save(tmp);
  HtmlUtil::sendRedirect303(srv, F("/config/sensors?ok=1"));
});


// -------------------- POST /config --------------------
g_server.on("/config", HTTP_POST, [](){
  auto& srv = g_server;
  WiFiManager::noteUserActivity();

  // --- raw-response helpers (bypass WebServer::send) ---
  auto sendPlain = [&](int code,
                       const __FlashStringHelper* reason,
                       const __FlashStringHelper* body){
    WiFiClient client = srv.client();
    if (!client) return;

    client.print(F("HTTP/1.1 "));
    client.print(code);
    client.print(' ');
    client.print(reason);
    client.print(F("\r\n"
                   "Connection: close\r\n"
                   "Content-Type: text/plain\r\n"
                   "\r\n"));
    client.print(body);
  };

  auto sendRedirect303 = [&](const String& location,
                             const __FlashStringHelper* body){
    WiFiClient client = srv.client();
    if (!client) return;

    client.print(F("HTTP/1.1 303 See Other\r\n"
                   "Location: "));
    client.print(location);
    client.print(F("\r\n"
                   "Connection: close\r\n"
                   "Content-Type: text/plain\r\n"
                   "\r\n"));
    client.print(body);
  };

  // ----------------- lock / basic validation -----------------
  if (!WebServerManager::canStart()) {
    // was: srv.send(423, F("text/plain"), F("Locked while logging"));
    sendPlain(423, F("Locked"), F("Locked while logging"));
    return;
  }

  String submit = srv.hasArg("submit") ? srv.arg("submit") : "";
  submit.toLowerCase();
  if (submit != "globals" && submit != "sensors") {
    HtmlUtil::sendPlainText(
      srv,
      400,
      F("Bad Request"),
      F("Unknown submit section")
    );
    return;
  }

  // Working copy we will persist at the end
  LoggerConfig tmp = ConfigManager::get();

  // ---------- GLOBALS ----------
  if (srv.hasArg("sample_rate_hz")) {
    uint16_t hz = (uint16_t)srv.arg("sample_rate_hz").toInt();
    tmp.sampleRateHz = hz;
  }

  if (srv.hasArg("timestamp_mode")) {
    const String tsm = srv.arg("timestamp_mode");
    if      (tsm == "human") tmp.timestampHuman = true;
    else if (tsm == "fast")  tmp.timestampHuman = false;
  }

  if (srv.hasArg("tz")) {
    String tz = srv.arg("tz"); tz.trim();
    if (tz.length() < (int)sizeof(tmp.tz)) tz.toCharArray(tmp.tz, sizeof(tmp.tz));
  }

  // NTP server (now in tmp.ntpServers[])
  if (srv.hasArg("ntp_server")) {
    String ns = srv.arg("ntp_server");
    ns.trim();
    if (ns.length() < (int)sizeof(tmp.ntpServers)) {
      ns.toCharArray(tmp.ntpServers, sizeof(tmp.ntpServers));
    }
  }

  // ---------- Wi-Fi globals + 5 slots ----------
  {
    const int ac = srv.args();

    auto parseBool = [&](const String& s)->bool{
      String v = s; v.trim(); v.toLowerCase();
      return (v=="true"||v=="1"||v=="on"||v=="yes");
    };

    // "Last wins" helper: for checkbox + hidden inputs, or any duplicated keys
    auto getArgLast = [&](const String& key, String& out) -> bool {
      bool found = false;
      for (int ai = 0; ai < ac; ++ai) {
        if (srv.argName(ai) == key) { out = srv.arg(ai); found = true; }
      }
      return found;
    };

    // globals with potential duplicates
    {
      String v;
      if (getArgLast(F("wifi_enabled_default"), v))          tmp.wifiEnabledDefault = parseBool(v);
      if (getArgLast(F("wifi_auto_time_on_rtc_invalid"), v)) tmp.wifiAutoTimeOnRtcInvalid = parseBool(v);
    }

    auto parseMacInline = [](const String& s, uint8_t out[6])->bool{
      int b[6];
      if (sscanf(s.c_str(), "%x:%x:%x:%x:%x:%x", &b[0],&b[1],&b[2],&b[3],&b[4],&b[5]) != 6) return false;
      for (int i=0;i<6;++i){ if (b[i] < 0 || b[i] > 255) return false; out[i] = (uint8_t)b[i]; }
      return true;
    };
    auto validRssiInline = [](int v)->bool{ return v >= -100 && v <= -10; };

    auto parseIpInline = [](const String& s, uint8_t out[4])->bool{
      int a,b,c,d;
      if (sscanf(s.c_str(), "%d.%d.%d.%d", &a,&b,&c,&d) != 4) return false;
      if ((unsigned)a>255 || (unsigned)b>255 || (unsigned)c>255 || (unsigned)d>255) return false;
      out[0]=(uint8_t)a; out[1]=(uint8_t)b; out[2]=(uint8_t)c; out[3]=(uint8_t)d;
      return true;
    };
    auto isZero4 = [](const uint8_t a[4])->bool{
      return a[0]==0 && a[1]==0 && a[2]==0 && a[3]==0;
    };

    uint8_t newCount = 0;

    for (int i = 0; i < 5; ++i) {
      const String k_ssid     = String("wifi") + i + ".ssid";
      const String k_pass     = String("wifi") + i + ".password";
      const String k_minrssi  = String("wifi") + i + ".min_rssi";
      const String k_bssid    = String("wifi") + i + ".bssid";
      const String k_hidden   = String("wifi") + i + ".hidden";
      const String k_staticip = String("wifi") + i + ".static_ip";

      const String k_ip       = String("wifi") + i + ".ip";
      const String k_gw       = String("wifi") + i + ".gateway";
      const String k_sn       = String("wifi") + i + ".subnet";
      const String k_dns1     = String("wifi") + i + ".dns1";
      const String k_dns2     = String("wifi") + i + ".dns2";

      // SSID
      if (srv.hasArg(k_ssid)) {
        String v = srv.arg(k_ssid); v.trim();
        v.toCharArray(tmp.wifi[i].ssid, sizeof(tmp.wifi[i].ssid));
      }

      // Password
      if (srv.hasArg(k_pass)) {
        String v = srv.arg(k_pass);
        v.toCharArray(tmp.wifi[i].password, sizeof(tmp.wifi[i].password));
      }

      // min_rssi
      if (srv.hasArg(k_minrssi)) {
        String v = srv.arg(k_minrssi); v.trim();
        if (!v.length()) tmp.wifi[i].minRssi = -127;
        else {
          int vi = v.toInt();
          tmp.wifi[i].minRssi = validRssiInline(vi) ? (int16_t)vi : (int16_t)-127;
        }
      }

      // bssid
      if (srv.hasArg(k_bssid)) {
        String v = srv.arg(k_bssid); v.trim();
        if (v.length()) {
          uint8_t mac[6];
          if (parseMacInline(v, mac)) {
            memcpy(tmp.wifi[i].bssid, mac, 6);
            tmp.wifi[i].bssidSet = true;
          } else {
            memset(tmp.wifi[i].bssid, 0, 6);
            tmp.wifi[i].bssidSet = false;
          }
        } else {
          memset(tmp.wifi[i].bssid, 0, 6);
          tmp.wifi[i].bssidSet = false;
        }
      }

      // hidden
      if (srv.hasArg(k_hidden)) {
        String v = srv.arg(k_hidden);
        tmp.wifi[i].hidden = parseBool(v);
      }

      // static_ip needs LAST value
      {
        String v;
        if (getArgLast(k_staticip, v)) {
          tmp.wifi[i].staticIp = parseBool(v);
        }
      }

      // ip/gateway/subnet/dns1/dns2
      auto setIpIfPresent = [&](const String& key, uint8_t out[4]){
        if (!srv.hasArg(key)) return;
        String v = srv.arg(key); v.trim();
        if (!v.length()) { out[0]=out[1]=out[2]=out[3]=0; return; }
        uint8_t ip[4];
        if (parseIpInline(v, ip)) memcpy(out, ip, 4);
        // else: leave as-is
      };

      setIpIfPresent(k_ip,   tmp.wifi[i].ip);
      setIpIfPresent(k_gw,   tmp.wifi[i].gateway);
      setIpIfPresent(k_sn,   tmp.wifi[i].subnet);
      setIpIfPresent(k_dns1, tmp.wifi[i].dns1);
      setIpIfPresent(k_dns2, tmp.wifi[i].dns2);

      // ---- static IP validation (only if enabled) ----
      if (tmp.wifi[i].staticIp) {
        if (isZero4(tmp.wifi[i].ip) || isZero4(tmp.wifi[i].gateway) || isZero4(tmp.wifi[i].subnet)) {
          HtmlUtil::sendRedirect303(
            srv,
            "/config?err=wifi_static_ip_incomplete&net=" + String(i),
            F("Static IP requires ip/gateway/subnet")
          );
          return;
        }
        // DNS1 default to gateway
        if (isZero4(tmp.wifi[i].dns1)) {
          memcpy(tmp.wifi[i].dns1, tmp.wifi[i].gateway, 4);
        }
      }

      if (tmp.wifi[i].ssid[0]) ++newCount;
    }

    tmp.wifiNetworkCount = newCount;

    // Debounce etc.
    auto setU16 = [&](const char* name, uint16_t& field){
      if (!srv.hasArg(name)) return;
      long v = srv.arg(name).toInt();
      if (v < 0) v = 0;
      if (v > 65535) v = 65535;
      field = (uint16_t)v;
    };
    setU16("debounce_ms", tmp.debounceMs);
  }

  // ---------- Persist full config ----------
  ConfigManager::save(tmp);

  HtmlUtil::sendRedirect303(
    srv,
    "/config?ok=1&tab=" + submit,
    F("Saved")
  );
});

}
