#include "Routes_Config.h"
#include <Arduino.h>
#include <ArduinoJson.h>

#include "HtmlUtil.h"
#include "ConfigManager.h"
#include "SensorManager.h"
#include "SensorRegistry.h"
#include "OutputTransform.h"
#include "WiFiManager.h"
#include "WebServerManager.h"  // for canStart()
#include "BoardSelect.h" 
#include "TransformRegistry.h"
#include "DebugLog.h"

#define WEB_LOGW(...) LOGW_TAG("WEB", __VA_ARGS__)

// ---- Helpers (file scope) ----
static String fmtIPv4(const uint8_t a[4]) {
  char buf[16];
  snprintf(buf, sizeof(buf), "%u.%u.%u.%u",
           a[0], a[1], a[2], a[3]);
  return String(buf);
}

static void appendTopNav(String& html, const char* active) {
  auto a = [&](const char* href, const char* label, bool bold=false){
    html += "<a href='"; html += href; html += "' style='margin-right:12px;";
    if (bold) html += "font-weight:700;";
    html += "'>";
    html += label;
    html += "</a>";
  };

  html += "<div style='margin:10px 0 14px 0; padding:8px 10px; background:#f3f3f3; border-radius:8px;'>";

  // Home / Files
  a("/", "Home");
  a("/files", "Files");  // change if your files route differs

  html += "<span style='margin:0 10px; color:#888;'>|</span>";

  // Config pages
  a("/config",         "General",  strcmp(active, "/config")==0);
  a("/config/sensors", "Sensors",  strcmp(active, "/config/sensors")==0);
  a("/config/buttons", "Buttons",  strcmp(active, "/config/buttons")==0);

  html += "</div>";
}


using namespace HtmlUtil;

void registerConfigRoutes(WebServer& srv) {
  WebServer* S = &srv;

  // -------------------- GET /config --------------------
  S->on("/config", HTTP_GET, [S](){
    auto& srv = *S;
    WiFiManager::noteUserActivity();

    // Read the active config for display
    const LoggerConfig& cfg = ConfigManager::get();

    const bool locked = !WebServerManager::canStart();   // disable edits while logging
    const String dis  = locked ? F(" disabled") : F("");

    String html = htmlHeader(F("Config"));

    appendTopNav(html, "/config");
    html += F("<hr>");

    if (srv.hasArg("ok")) {
      html += F("<p style='background:#e7ffe7;border:1px solid #8bc34a;padding:8px;border-radius:6px'>Saved.</p>");
    }
    if (locked) {
      html += F("<p style='background:#fff3cd;border:1px solid #ffe08a;padding:8px;border-radius:6px'>"
                "Logging is active (or not allowed). Editing is disabled. Stop logging to make changes."
                "</p>");
    }

    // Status banner
    if (srv.hasArg("ok")) {
      html += "<p class='ok'>Configuration saved</p>";
    }

    // ---- ERROR banner (board-aware validation) ----
    if (srv.hasArg("err")) {
      String err = srv.arg("err");
      String s   = srv.hasArg("sensor") ? srv.arg("sensor") : "";
      String ain = srv.hasArg("ain")    ? srv.arg("ain")    : "";

      html += "<p style='background:#ffe7e7;border:1px solid #e57373;";
      html += "padding:8px;border-radius:6px'>";
      html += "Error: " + htmlEscape(err);

      if (s.length()) {
        html += " (sensor ";
        html += htmlEscape(s);
        html += ")";
      }
      if (ain.length()) {
        html += ", ain=";
        html += htmlEscape(ain);
      }
      html += "</p>";
    }


    // ---------- GLOBALS ----------
    html += F("<h2>Configuration</h2><form method='POST' action='/config'>");
    html += F("<input type='hidden' name='submit' value='globals'>"); //Hidden input

    html += F("<fieldset><legend>General</legend>");
    html += F("<label>Sample rate (Hz): </label><input type='number' name='sample_rate_hz' min='1' max='2000' value='");
    html += String(cfg.sampleRateHz);
    html += F("'"); html += dis; html += F("><br>");

    html += F("<label>Timestamp mode: </label><select name='timestamp_mode'");
    html += dis; html += F("><option value='human'");
    if (cfg.timestampHuman) html += F(" selected");
    html += F(">human</option><option value='fast'");
    if (!cfg.timestampHuman) html += F(" selected");
    html += F(">fast</option></select><br>");

    html += F("<label>Timezone (tz rule): </label><input type='text' name='tz' value='");
    html += htmlEscape(String(cfg.tz));
    html += F("'"); html += dis; html += F("><br>");
    
    html += F("<label>Debounce (ms): </label><input type='number' name='debounce_ms' min='0' max='1000' value='");
    html += String(cfg.debounceMs);
    html += F("'"); html += dis; html += F("><br>");

    html += F("<label>Log level: </label><select name='log_level'");
    html += dis; html += F(">");
    {
      const char* selectedLevel = (cfg.logLevelOverride == 0xFF)
                                    ? "default"
                                    : Log_levelName((LogLevel)cfg.logLevelOverride);
      const char* levelOptions[] = {"default", "error", "warn", "info", "debug", "trace"};
      for (const char* option : levelOptions) {
        html += F("<option value='");
        html += option;
        html += F("'");
        if (String(selectedLevel) == option) html += F(" selected");
        html += F(">");
        html += option;
        html += F("</option>");
      }
    }
    html += F("</select><br>");
    html += F("</fieldset>");

    // ---------- Wi-Fi (multi-network) ----------
    html += F("<fieldset><legend>Network & NTP</legend>");

    // toggles
    html += F("<div class='row'><label>Enable Wi-Fi by default</label>");
    html += F("<input type='hidden' name='wifi_enabled_default' value='false'>");
    html += F("<input type='checkbox' name='wifi_enabled_default' value='true'");
    if (cfg.wifiEnabledDefault) html += F(" checked");
    if (locked) html += F(" disabled");
    html += F("></div>");

    html += F("<div class='row'><label>Auto-enable for NTP if RTC invalid</label>");
    html += F("<input type='hidden' name='wifi_auto_time_on_rtc_invalid' value='false'>");
    html += F("<input type='checkbox' name='wifi_auto_time_on_rtc_invalid' value='true'");
    if (cfg.wifiAutoTimeOnRtcInvalid) html += F(" checked");
    if (locked) html += F(" disabled");
    html += F("></div>");

    html += F("<div class='row'><label>NTP servers (CSV)</label><input type='text' name='ntp_servers' value='");
    html += htmlEscape(String(cfg.ntpServers));
    html += F("'");
    if (locked) html += F(" disabled");
    html += F("></div>");

    html += F("<div class='row'><label>HTTP time check URL</label><input type='text' name='time_check_url' value='");
    html += htmlEscape(String(cfg.timeCheckUrl));
    html += F("'");
    if (locked) html += F(" disabled");
    html += F("></div>");

    html += F("<h4>Wi-Fi (multi-network)</h4>");

    // advisory count (display only)
    html += F("<div class='row'><label>Configured networks</label>");
    html += "<input type='text' value='"; html += String(cfg.wifiNetworkCount);
    html += F("' disabled></div>");

    // five editable slots; order = priority
    for (int i = 0; i < 5; ++i) {
      const auto& w = cfg.wifi[i];
      html += F("<fieldset><legend>Wi-Fi ");
      html += String(i);
      html += F(" (priority "); html += String(i+1); html += F(")</legend>");

      // SSID
      html += F("<div class='row'><label>SSID</label><input type='text' name='wifi");
      html += String(i);
      html += F(".ssid' value='");
      html += htmlEscape(String(w.ssid));
      html += F("'"); if (locked) html += F(" disabled"); html += F("></div>");

      // Password (write-only feel; still show current to match legacy)
      html += F("<div class='row'><label>Password</label><input type='password' name='wifi");
      html += String(i);
      html += F(".password' value='");
      html += htmlEscape(String(w.password));
      html += F("' placeholder='(unchanged)'");
      if (locked) html += F(" disabled");
      html += F("></div>");

      // min_rssi
      html += F("<div class='row'><label>Min RSSI (dBm)</label>"
                "<input type='number' step='1' min='-100' max='0' name='wifi");
      html += String(i);
      html += F(".min_rssi' value='");
      if (w.minRssi >= -100 && w.minRssi <= -10) html += String((int)w.minRssi);
      html += F("' oninput=\"this.setCustomValidity('');"
                "if(this.value!=='' && this.value!=='0' && Number(this.value)>-10)"
                " this.setCustomValidity('Value must be ≤ -10 (or 0/blank to ignore)');\"");
      if (locked) html += F(" disabled");
      html += F(" placeholder='0 or blank = ignore'>"
                "<small>≤ -10, or 0/blank to ignore</small></div>");

      // BSSID
      String bssidStr;
      if (w.bssidSet) {
        char buf[24];
        snprintf(buf, sizeof(buf), "%02X:%02X:%02X:%02X:%02X:%02X",
                 w.bssid[0],w.bssid[1],w.bssid[2],w.bssid[3],w.bssid[4],w.bssid[5]);
        bssidStr = buf;
      }
      html += F("<div class='row'><label>BSSID (optional)</label><input type='text' pattern='^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$' name='wifi");
      html += String(i);
      html += F(".bssid' value='");
      html += htmlEscape(bssidStr);
      html += F("'"); if (locked) html += F(" disabled"); html += F("><small>AA:BB:CC:DD:EE:FF</small></div>");

      // Hidden
      html += F("<div class='row'><label>Hidden SSID</label>"
                "<input type='hidden' name='wifi");
      html += String(i);
      html += F(".hidden' value='false'>"
                "<input type='checkbox' name='wifi");
      html += String(i);
      html += F(".hidden' value='true'");
      if (w.hidden) html += F(" checked");
      if (locked)   html += F(" disabled");
      html += F("></div>");

      // Static IP enable
      {
        String key = String("wifi")+i+".static_ip";
        html += "<div class='row'><label>Static IP</label>";
        html += "<input type='hidden' name='" + key + "' value='false'>";
        html += "<input type='checkbox' name='" + key + "' value='true' ";
        if (cfg.wifi[i].staticIp) html += "checked";
        if (locked) html += " disabled";
        html += "></div>";
      }

      // IP fields (always shown is simplest; later you can hide via JS)
      auto addIpField = [&](const char* suffix, const uint8_t ip[4], const char* label){
        String key = String("wifi")+i+"."+suffix;
        html += "<div class='row'><label>";
        html += label;
        html += "</label><input type='text' size='16' name='";
        html += key;
        html += "' value='";
        html += htmlEscape(fmtIPv4(ip));
        html += "'";
        if (locked) html += " disabled";
        html += "></div>";
      };

      addIpField("ip",      cfg.wifi[i].ip,      "Local IP");
      addIpField("gateway", cfg.wifi[i].gateway, "Gateway");
      addIpField("subnet",  cfg.wifi[i].subnet,  "Subnet");
      addIpField("dns1",    cfg.wifi[i].dns1,    "DNS 1");
      addIpField("dns2",    cfg.wifi[i].dns2,    "DNS 2");

      html += F("</fieldset>");
    }

    html += F("<p><button type='submit'"); html += dis; html += F(">Save</button></p>");
    html += F("</form>");

    html += htmlFooter();
    srv.send(200, F("text/html"), html);
  });

  // -------------------- GET /config/sensors --------------------
  S->on("/config/sensors", HTTP_GET, [S](){
    auto& srv = *S;
    WiFiManager::noteUserActivity();

    const LoggerConfig& cfg = ConfigManager::get();
    const bool locked = !WebServerManager::canStart();
    const String dis  = locked ? F(" disabled") : F("");

    String html = htmlHeader(F("Sensors"));

    appendTopNav(html, "/config/sensors");
    html += F("<hr>");

    html += F("<form method='POST' action='/config/sensors'>");

    // ---------- SENSORS ----------
    html += F("<h2>Sensors</h2>");

    const uint8_t n = cfg.sensorCount();
    if (n == 0) {
      html += F("<p><em>No sensors configured.</em></p>");
    }

      for (uint8_t i = 0; i < n; ++i) {
        SensorSpec sp; 
        if (!cfg.getSensorSpec(i, sp)) continue;
        const SensorTypeInfo* ti = SensorRegistry::lookup(sp.type);

        // Type label
        const char* typeLbl = SensorRegistry::typeLabel(sp.type);
        const String typeLabelStr = htmlEscape(String(typeLbl ? typeLbl : "Unknown Sensor"));

        // ParamDefs lookup helper
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
          if (!pd) return; // only render if defined by this sensor type
          String label = labelOverride ? String(labelOverride) : String(pd->key);
          html += "<div class='row'><label>";
          html += htmlEscape(label);
          html += "</label>";
          String field = String("s") + i + "." + key;

          if (pd->type == ParamType::Bool) {
            String val = currentValAsString(pd);
            html += "<input type='hidden' name='" + field + "' value='false'>";
            html += "<input type='checkbox' name='" + field + "' value='true' ";
            if (val == "true") html += "checked";
            if (locked) html += " disabled";
            html += ">";
          } else if (pd->type == ParamType::Enum && pd->choices) {
            String val = currentValAsString(pd);
            html += "<select name='" + field + "'";
            if (locked) html += " disabled";
            html += ">";
            emitEnumOptions(html, pd->choices, val);
            html += "</select>";
          } else {
            String val = currentValAsString(pd);
            html += "<input type='text' name='" + field + "' value='";
            html += htmlEscape(val);
            html += "'";
            if (locked) html += " disabled";
            html += ">";
          }
          if (pd->help) { html += "<small>"; html += pd->help; html += "</small>"; }
          html += "</div>";
        };

        // --- Fieldset / legend
        html += F("<fieldset id='sensor-");
        html += String(i);
        html += F("'><legend>");
        const char* dispName = (sp.name && sp.name[0]) ? sp.name : "sensor";
        html += htmlEscape(String(dispName));
        html += F(" — ");
        html += typeLabelStr;
        html += F("</legend>");

        // ---- Basic ----
        html += F("<h4>Basic</h4>");
        html += F("<div class='row'><label>Name</label>");
        html += "<input type='text' name='s"; html += String(i); html += ".name' value='";
        html += htmlEscape(String(sp.name)); html += "'"; html += dis; html += "></div>";

        html += "<div class='row'><label>Type</label><select name='s";
        html += String(i);
        html += ".type'";
        if (locked) html += " disabled";
        html += ">";
        const SensorType typeChoices[] = {
          SensorType::AnalogPot,
          SensorType::AS5600StringPotAnalog,
          SensorType::AS5600StringPotI2C,
        };
        for (const auto typeChoice : typeChoices) {
          const SensorTypeInfo* tiChoice = SensorRegistry::lookup(typeChoice);
          if (!tiChoice) continue; // only show implemented/registered types
          const char* key = SensorRegistry::typeKey(typeChoice);
          const char* label = SensorRegistry::typeLabel(typeChoice);
          html += "<option value='";
          html += htmlEscape(String(key ? key : "unknown"));
          html += "'";
          if (sp.type == typeChoice) html += " selected";
          html += ">";
          html += htmlEscape(String(label ? label : "Unknown Sensor"));
          html += "</option>";
        }
        html += "</select> ";
        html += "<button type='submit' name='apply_type_idx' value='";
        html += String(i);
        html += "'";
        if (locked) html += " disabled";
        html += ">Apply Type</button>";
        html += "<small>Reloads fields for the selected type, prunes incompatible params, and takes effect after reboot.</small></div>";

        // Board-aware Analog Input selector (AIN ordinal)
        {
          const ParamDef* pd = findDef("ain");
          if (pd) {
            String field = String("s") + i + ".ain";
            long curAin = -1;
            sp.params.getInt("ain", curAin);

            html += "<div class='row'><label>Analog input</label>";

            if (!board::gBoard) {
              html += "<em>No active board profile</em>";
            } else {
              const auto& bp = *board::gBoard;
              if (bp.analog.count == 0) {
                html += "<em>No analog inputs on this board</em>";
              } else {
                html += "<select name='" + field + "'";
                if (locked) html += " disabled";
                html += ">";

                // Optional: allow “unset” (forces validation failure on save if required)
                html += "<option value='-1'";
                if (curAin < 0) html += " selected";
                html += ">-- select --</option>";

                for (uint8_t ai = 0; ai < bp.analog.count; ++ai) {
                  const int pin = bp.analog.pins[ai];
                  // Only show valid entries
                  if (pin < 0) continue;

                  html += "<option value='"; html += String((int)ai); html += "'";
                  if ((long)ai == curAin) html += " selected";
                  html += ">";
                  html += "AIN"; html += String((int)ai);
                  html += " (GPIO"; html += String(pin); html += ")";
                  html += "</option>";
                }

                html += "</select>";
              }
            }

            html += "</div>";
          }
        }

        // Muted by default
        {
          String field = String("s") + i + ".muted";
          html += "<div class='row'><label>Muted by default</label>";
          html += "<input type='hidden' name='" + field + "' value='false'>";
          html += "<input type='checkbox' name='" + field + "' value='true' ";
          if (sp.mutedDefault) html += "checked";
          if (locked) html += " disabled";
          html += "></div>";
        }

        // ---- Output ----
        html += F("<h4>Output</h4>");

        // Output mode (RAW/LINEAR/POLY/LUT)
        {
          const ParamDef* pdOM = findDef("output_mode");
          if (pdOM) {
            int om = (int)OutputMode::RAW;
            long vi;
            if (sp.params.getInt("output_mode", vi)) om = (int)vi;

            const String field = String("s") + i + ".output_mode";

            html += "<div class='row'><label>Output mode</label><select name='";
            html += field;
            html += "' onchange=\"window.__xf_onModeChange('";
            html += sp.name;
            html += "', this.value)\"";
            if (locked) html += " disabled";
            html += ">";

            auto addOpt = [&](OutputMode val, const char* label) {
              html += "<option value='"; html += String((int)val); html += "'";
              if (om == (int)val) html += " selected";
              html += ">"; html += label; html += "</option>";
            };
            addOpt(OutputMode::RAW,    "RAW");
            addOpt(OutputMode::LINEAR, "LINEAR");
            addOpt(OutputMode::POLY,   "POLY");
            addOpt(OutputMode::LUT,    "LUT");

            html += "</select></div>";
          }
        }

        emitParamRow("include_raw", "Include raw column");
        emitParamRow("sensor_full_travel_mm", "Sensor full travel (mm)");
        emitParamRow("units_label", "Units label");

        // Transform picker (per sensor)
        {
          // use live sensor to preselect
          const uint8_t liveN = SensorManager::count();
          String currentId;
          for (uint8_t j = 0; j < liveN; ++j) {
            Sensor* ss = SensorManager::get(j);
            if (ss && String(ss->name()) == String(dispName)) { currentId = ss->selectedTransformId(); break; }
          }

          html += F("<div class='row tr-block' data-sensor='");
          html += htmlEscape(String(dispName));
          html += F("' data-current='");
          html += htmlEscape(currentId);
          html += F("'>");
          html += F("<label>Output transform</label>");
          html += F("<select name='s"); html += i; html += F(".output_id'>");
          html += F("</select> ");
          html += F("<button class='apply'");  if (locked) html += F(" disabled"); html += F(">Apply</button> ");
          html += F("<button class='reload'"); if (locked) html += F(" disabled"); html += F(">Reload</button> ");
          html += F("<span class='status' style='margin-left:8px;color:#060'></span></div>");
        }

        // ---- Calibration ----
        html += F("<h4>Calibration</h4>");
        {
          String field = String("s") + i + ".cal_allowed";
          html += "<div class='row'><label>Calibration methods</label>";
          html += "<input type='text' name='" + field + "' placeholder='ZERO,RANGE' value='";
          CalModeMask allowMask2 = ConfigManager::calAllowedMaskByIndex(i);
          String calCsv;
          if (allowMask2 != 0xFF) {
            if (allowMask2 & CAL_ZERO)  { if (calCsv.length()) calCsv += ","; calCsv += "ZERO"; }
            if (allowMask2 & CAL_RANGE) { if (calCsv.length()) calCsv += ","; calCsv += "RANGE"; }
            if (!calCsv.length()) calCsv = "NONE";
          }
          html += htmlEscape(calCsv);
          html += "'";
          if (locked) html += " disabled";
          html += ">";
          html += "<small>Leave blank to inherit type-supported methods.</small>";
          html += "</div>";
        }
        emitParamRow("sensor_zero_count", "Sensor count at zero travel");
        emitParamRow("sensor_full_count", "Sensor count at full travel");
        emitParamRow("invert", "Invert measurement direction");

        // ---- Wrapping ----
        html += F("<h4>Wrapping</h4>");
        emitParamRow("counts_per_turn", "Counts per turn");
        emitParamRow("wrap_threshold_counts", "Wrap threshold (counts)");
        emitParamRow("assume_turn0_at_start", "Assume turn 0 at log start");

        // ---- Smoothing ----
        html += F("<h4>Smoothing</h4>");
        emitParamRow("ema_alpha", "EMA alpha");
        emitParamRow("deadband",  "Deadband");

        // (Optional) render remaining params under "Other"
        const char* shown[] = {
          "ain","muted",
          "output_mode","include_raw","sensor_full_travel_mm","units_label",
          "cal_allowed","sensor_zero_count","sensor_full_count","invert",
          "counts_per_turn","wrap_threshold_counts","assume_turn0_at_start",
          "ema_alpha","deadband"
        };
        auto isShown = [&](const char* key)->bool{
          for (size_t k=0;k<sizeof(shown)/sizeof(shown[0]);++k){
            if (strcasecmp(shown[k], key)==0) return true;
          }
          return false;
        };
        bool printedOther = false;
        size_t defCount2 = 0;
        const ParamDef* defs2 = ti ? ti->paramDefs(defCount2) : nullptr;
        for (size_t d = 0; d < defCount2; ++d) {
          const ParamDef& pd = defs2[d];
          if (isShown(pd.key)) continue;
          if (strcasecmp(pd.key, "name")==0 || strcasecmp(pd.key,"type")==0) continue;
          if (!printedOther) { html += F("<h4>Other</h4>"); printedOther = true; }

          // inline emit for this key
          {
            const ParamDef* pd2 = findDef(pd.key);
            if (pd2) {
              String label = String(pd2->key);
              html += "<div class='row'><label>";
              html += htmlEscape(label);
              html += "</label>";
              String field = String("s") + i + "." + pd.key;
              if (pd2->type == ParamType::Bool) {
                String val = currentValAsString(pd2);
                html += "<input type='hidden' name='" + field + "' value='false'>";
                html += "<input type='checkbox' name='" + field + "' value='true' ";
                if (val == "true") html += "checked";
                if (locked) html += " disabled";
                html += ">";
              } else if (pd2->type == ParamType::Enum && pd2->choices) {
                String val = currentValAsString(pd2);
                html += "<select name='" + field + "'";
                if (locked) html += " disabled";
                html += ">";
                emitEnumOptions(html, pd2->choices, val);
                html += "</select>";
              } else {
                String val = currentValAsString(pd2);
                html += "<input type='text' name='" + field + "' value='";
                html += htmlEscape(val);
                html += "'";
                if (locked) html += " disabled";
                html += ">";
              }
              if (pd2->help) { html += "<small>"; html += pd2->help; html += "</small>"; }
              html += "</div>";
            }
          }
          delay(0);
        }

        html += F("</fieldset>");
        delay(0);
      }

    

    // --- per-sensor transform UI script (unchanged) ---
    html += F(
      "<script>\n"
      "document.addEventListener('DOMContentLoaded',function(){\n"
      "  function pickListShape(j){ var a=j.transforms||j.items||j.options||j.results||j.choices||j; if(Array.isArray(a)) return a; return []; }\n"
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
      "    btn.addEventListener('click', function(){\n"
      "      var block = btn.closest('.tr-block'); var sensor = block && block.dataset ? block.dataset.sensor : '';\n"
      "      var status = block ? block.querySelector('.status') : null;\n"
      "      fetch('/api/transforms/reload',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'sensor='+encodeURIComponent(sensor)})\n"
      "        .then(function(r){return r.json();}).then(function(j){ if(j && j.ok){ var mode = getCurrentModeForSensor(sensor); block.dataset.current='identity'; populate(block, mode); if(status){ status.style.color='#060'; status.textContent='Reloaded ✔'; } setTimeout(function(){ if(status) status.textContent=''; },1200); } else { if(status){ status.style.color='#900'; status.textContent='Error'; } } })\n"
      "        .catch(function(){ if(status){ status.style.color='#900'; status.textContent='Error'; } });\n"
      "    });\n"
      "  });\n"
      "  Array.prototype.forEach.call(document.querySelectorAll('.tr-block'), function(b){ populate(b); });\n"
      "  document.addEventListener('change',function(ev){ var n=(ev.target&&ev.target.name)||''; var m=n.match(/^s(\\d+)\\.output_mode$/); if(!m) return; var idx=m[1]; var newMode=ev.target.value; var nameEl=document.querySelector('input[name=\"s'+idx+'.name\"]'); if(!nameEl) return; var sensor=nameEl.value||''; var block=Array.prototype.find.call(document.querySelectorAll('.tr-block'),function(el){return el.dataset&&el.dataset.sensor===sensor;}); if(block){ block.dataset.current='identity'; populate(block, newMode); } });\n"
      "});\n"
      "</script>\n"
    );

    html += F("<p><button type='submit'");
    html += dis;
    html += F(">Save Sensors</button></p>");
    html += F("</form>");

    html += htmlFooter();
    srv.send(200, F("text/html"), html);
  });

  // -------------------- GET /config/buttons --------------------
  S->on("/config/buttons", HTTP_GET, [S](){
    auto& srv = *S;
    WiFiManager::noteUserActivity();

    const LoggerConfig& cfg = ConfigManager::get();
    const bool locked = !WebServerManager::canStart();
    const String dis  = locked ? F(" disabled") : F("");

    String html = htmlHeader(F("Buttons"));

    appendTopNav(html, "/config/buttons");
    html += F("<hr>");


    html += F("<form method='POST' action='/config/buttons'>");

    // ---------- Button bindings (new) ----------
    html += F("<fieldset><legend>Button bindings (new)</legend>");
    html += F("<p><small>Each row maps a (button ID, event) pair to an action. "
              "Events: pressed, released, click, double_click, held. "
              "Actions: logging_toggle, mark_event, web_toggle, menu_nav_up/down/left/right/enter, menu_select, sleep.</small></p>");

    for (uint8_t i = 0; i < MAX_BUTTON_BINDINGS; ++i) {
      const ButtonBindingDef& bd = (i < cfg.buttonBindingCount) ? cfg.buttonBindings[i] : ButtonBindingDef{};

      html += F("<div class='row'>");
      html += F("<label>Binding ");
      html += String(i);
      html += F("</label>");

      // buttonId
      html += F("<input type='text' size='10' placeholder='button id' name='binding");
      html += String(i);
      html += F(".button' value='");
      html += htmlEscape(String(bd.buttonId));
      html += F("'");
      html += dis;
      html += F("> ");

      // event
      html += F("<input type='text' size='10' placeholder='event' name='binding");
      html += String(i);
      html += F(".event' value='");
      html += htmlEscape(String(bd.event));
      html += F("'");
      html += dis;
      html += F("> ");

      // action
      html += F("<input type='text' size='20' placeholder='action' name='binding");
      html += String(i);
      html += F(".action' value='");
      html += htmlEscape(String(bd.action));
      html += F("'");
      html += dis;
      html += F(">");

      html += F("</div>");
    }
    html += F("</fieldset>");


    html += F("<p><button type='submit'"); html += dis; html += F(">Save</button></p>");
    html += F("</form>");

    html += htmlFooter();
    srv.send(200, F("text/html"), html);
  });
  

  // -------------------- POST /config/sensors --------------------
  S->on("/config/sensors", HTTP_POST, [S](){
    auto& srv = *S;
    WiFiManager::noteUserActivity();

    if (!WebServerManager::canStart()) {
      srv.send(423, F("text/plain"), F("Locked while logging"));
      return;
    }

    LoggerConfig tmp = ConfigManager::get();
    int applyTypeIdx = -1;
    if (srv.hasArg("apply_type_idx")) {
      applyTypeIdx = srv.arg("apply_type_idx").toInt();
    }

    // ---------- SENSORS ----------
    // enumerate current specs, mutate copies, and persist via ConfigManager helpers
    const LoggerConfig& current = ConfigManager::get();  // read-only view for enumeration
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

      bool typeChanged = false;

      // Basic
      {
        String v;
        SensorType oldType = sp.type;
        if (getArgLast("type", v)) {
          v.trim();
          if (v.length()) {
            if (v.equalsIgnoreCase("analog_pot") || v.equalsIgnoreCase("pot")) {
              sp.type = SensorType::AnalogPot;
            } else if (v.equalsIgnoreCase("as5600_string_pot_analog") || v.equalsIgnoreCase("as5600_pot_analog")) {
              sp.type = SensorType::AS5600StringPotAnalog;
            } else if (v.equalsIgnoreCase("as5600_string_pot_i2c") || v.equalsIgnoreCase("as5600_pot_i2c")) {
              sp.type = SensorType::AS5600StringPotI2C;
            }
          }
        }
        typeChanged = (sp.type != oldType);
        tmp.sensors[idx].type = sp.type;
        if (typeChanged) {
          const SensorTypeInfo* newTi = SensorRegistry::lookup(sp.type);
          size_t newDefCount = 0;
          const ParamDef* newDefs = newTi ? newTi->paramDefs(newDefCount) : nullptr;
          String keepVals[ParamStore::MAX];
          bool   haveVals[ParamStore::MAX] = {false};

          if (newDefs) {
            const size_t keepCount = (newDefCount < ParamStore::MAX) ? newDefCount : ParamStore::MAX;
            for (size_t d = 0; d < keepCount; ++d) {
              haveVals[d] = sp.params.get(newDefs[d].key, keepVals[d]);
            }
          }

          sp.params.clear();

          if (newDefs) {
            const size_t seedCount = (newDefCount < ParamStore::MAX) ? newDefCount : ParamStore::MAX;
            for (size_t d = 0; d < seedCount; ++d) {
              if (haveVals[d]) {
                sp.params.set(newDefs[d].key, keepVals[d]);
              } else if (newDefs[d].def) {
                sp.params.set(newDefs[d].key, String(newDefs[d].def));
              }
            }
          }
        }
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

      // ---- Board-aware analog input binding (AIN ordinal) ----
      {
        String v;
        if (getArgLast("ain", v)) {
          v.trim();
          long ain = v.toInt();

          // Validate against active board
          bool ok = true;
          if (!board::gBoard) ok = false;
          else {
            const auto& bp = *board::gBoard;
            if (ain < 0 || ain >= (long)bp.analog.count) ok = false;
            else if (bp.analog.pins[(uint8_t)ain] < 0) ok = false;
          }

          if (!ok) {
            // Redirect back with error details
            srv.sendHeader("Location",
              "/config?err=invalid_ain&sensor=" + String((int)idx) + "&ain=" + String((int)ain));
            srv.send(303, F("text/plain"), F("Invalid analog input"));
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
          v.trim(); 
          v.toUpperCase(); 
          long vi = v.toInt(); 
          if (v=="RAW"||vi==0) newOm=0; 
          else if (v=="LINEAR"||vi==1) newOm=1; 
          else if (v=="POLY"||vi==2) newOm=2; 
          else if (v=="LUT"||vi==3) newOm=3;
          if (newOm != oldOm) omChanged = true;
          sp.params.setInt("output_mode", newOm);
        }

        bool idChanged = false;
        String oldId; sp.params.get("output_id", oldId); oldId.trim();

        if (getArgLast("output_id", v)) {
          v.trim();
          if (v != oldId) idChanged = true;
          sp.params.set("output_id", v);
        }

        { bool inc = false; if (getBoolLast("include_raw", inc)) sp.params.setBool("include_raw", inc); }
        if (getArgLast("sensor_full_travel_mm", v)) { double f = v.toFloat(); sp.params.setFloat("sensor_full_travel_mm", (float)f); }
        if (getArgLast("units_label", v)) { sp.params.set("units_label", v); }

        sp.params.setBool("__om_changed", omChanged);
        sp.params.setBool("__id_changed", idChanged);
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

      // Wrapping
      {
        String v;
        if (getArgLast("counts_per_turn", v))       { long vi = v.toInt(); sp.params.setInt("counts_per_turn", vi); }
        if (getArgLast("wrap_threshold_counts", v)) { long vi = v.toInt(); sp.params.setInt("wrap_threshold_counts", vi); }
        { bool assume = false; if (getBoolLast("assume_turn0_at_start", assume)) sp.params.setBool("assume_turn0_at_start", assume); }
      }

      // Generic ParamDefs pass (remaining keys defined by the sensor)
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
            pkey.equalsIgnoreCase("counts_per_turn") || pkey.equalsIgnoreCase("wrap_threshold_counts") ||
            pkey.equalsIgnoreCase("assume_turn0_at_start") ||
            pkey.equalsIgnoreCase("ema_alpha")  || pkey.equalsIgnoreCase("deadband") ||
            pkey.equalsIgnoreCase("ain")) {
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
        if (!ok) WEB_LOGW("set param failed: s%u.%s\n", (unsigned)idx, pkey.c_str());
      }

      // Commit all param changes into tmp so ConfigManager::save(tmp) persists them
      tmp.sensors[idx].params = sp.params;

      // Persist header/spec
      ConfigManager::setSensorHeaderByIndex(idx, sp);

      // Push changes into the live sensor (so they take effect immediately)
      Sensor* live = nullptr;
      for (uint8_t j = 0; j < SensorManager::count(); ++j) {
        Sensor* s = SensorManager::get(j);
        if (s && String(s->name()) == String(sp.name)) { live = s; break; }
      }
      if (live && !typeChanged) {
        // muted
        live->setMuted(sp.mutedDefault);

        // output mode / include_raw
        long om = 0; sp.params.getInt("output_mode", om);
        live->setOutputMode((OutputMode)om);

        bool inc = false; sp.params.getBool("include_raw", inc);
        live->setIncludeRaw(inc);

        // units label for the primary column
        String u; sp.params.get("units_label", u);
        if ((OutputMode)om == OutputMode::RAW) u = "counts";
        live->setOutputUnitsLabel(u.c_str());

        // If output_mode changed, re-attach transform + units label policy
        bool omChanged = false, idChanged = false;
        sp.params.getBool("__om_changed", omChanged);
        sp.params.getBool("__id_changed", idChanged);
        if (omChanged || idChanged) {
          // NOTE: Transform reload and selection are handled in the Transforms routes.
          // Here we just refresh units label according to current selection stored in params.
          String selId; 
          sp.params.get("output_id", selId); 
          selId.trim();
          live->setSelectedTransformId(selId);
          live->attachTransform(gTransforms);

          if ((OutputMode)om == OutputMode::RAW) {
            live->setOutputUnitsLabel("counts");
          } else if ((OutputMode)om == OutputMode::LINEAR) {
            String explicitLabel; sp.params.get("units_label", explicitLabel);
            live->setOutputUnitsLabel(explicitLabel.c_str());
          } else {
            // POLY/LUT: leave label to transform’s metadata (set via Transforms route)
          }
        }
      }
    }
  

    ConfigManager::save(tmp);
    String location = "/config/sensors?ok=1";
    if (applyTypeIdx >= 0) {
      location += "#sensor-";
      location += String(applyTypeIdx);
    }
    srv.sendHeader("Location", location);
    srv.send(303, F("text/plain"), F("Saved"));
  });

  // -------------------- POST /config/buttons --------------------
  S->on("/config/buttons", HTTP_POST, [S](){
    auto& srv = *S;
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
    srv.sendHeader("Location", "/config/buttons?ok=1");
    srv.send(303, F("text/plain"), F("Saved"));
  });


  // -------------------- POST /config --------------------
  S->on("/config", HTTP_POST, [S](){
    auto& srv = *S;
    WiFiManager::noteUserActivity();

    if (!WebServerManager::canStart()) {
      srv.send(423, F("text/plain"), F("Locked while logging"));
      return;
    }

    String submit = srv.hasArg("submit") ? srv.arg("submit") : "";
    submit.toLowerCase();

    if (submit != "globals" && submit != "sensors") {
      srv.send(400, F("text/plain"), F("Unknown submit section"));
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

    if (srv.hasArg("ntp_servers")) {
      String ntpServers = srv.arg("ntp_servers"); ntpServers.trim();
      if (ntpServers.length() < (int)sizeof(tmp.ntpServers)) {
        ntpServers.toCharArray(tmp.ntpServers, sizeof(tmp.ntpServers));
      }
    }

    if (srv.hasArg("time_check_url")) {
      String timeCheckUrl = srv.arg("time_check_url"); timeCheckUrl.trim();
      if (timeCheckUrl.length() < (int)sizeof(tmp.timeCheckUrl)) {
        timeCheckUrl.toCharArray(tmp.timeCheckUrl, sizeof(tmp.timeCheckUrl));
      }
    }

    if (srv.hasArg("log_level")) {
      String levelText = srv.arg("log_level");
      levelText.trim();
      if (!levelText.length() || levelText.equalsIgnoreCase("default")) {
        tmp.logLevelOverride = 0xFF;
      } else {
        LogLevel level;
        if (Log_parseLevel(levelText.c_str(), level)) {
          tmp.logLevelOverride = (uint8_t)level;
        }
      }
    }

    // ---- Wi-Fi globals + 5 slots ----
    {
      auto getArgLast = [&](const char* key, String& out) -> bool {
        bool found = false; const int ac = srv.args();
        for (int ai = 0; ai < ac; ++ai) { if (srv.argName(ai) == key) { out = srv.arg(ai); found = true; } }
        return found;
      };
      auto parseBool = [&](const String& s)->bool{
        String v = s; v.trim(); v.toLowerCase();
        return (v=="true"||v=="1"||v=="on"||v=="yes");
      };
      auto setBoolIfPresent = [&](const char* key, bool& field){
        String v; if (!getArgLast(key, v)) return; field = parseBool(v);
      };

      setBoolIfPresent("wifi_enabled_default",          tmp.wifiEnabledDefault);
      setBoolIfPresent("wifi_auto_time_on_rtc_invalid", tmp.wifiAutoTimeOnRtcInvalid);

      auto parseMacInline = [](const String& s, uint8_t out[6])->bool{
        int b[6];
        if (sscanf(s.c_str(), "%x:%x:%x:%x:%x:%x", &b[0],&b[1],&b[2],&b[3],&b[4],&b[5]) != 6) return false;
        for (int i=0;i<6;++i){ if (b[i] < 0 || b[i] > 255) return false; out[i] = (uint8_t)b[i]; }
        return true;
      };
      auto validRssiInline = [](int v)->bool{ return v >= -100 && v <= -10; };

      uint8_t newCount = 0;
      for (int i = 0; i < 5; ++i) {
        // SSID
        { String key = String("wifi")+i+".ssid"; if (srv.hasArg(key)) { String v = srv.arg(key); v.trim(); v.toCharArray(tmp.wifi[i].ssid, sizeof(tmp.wifi[i].ssid)); } }
        // Password
        { String key = String("wifi")+i+".password"; if (srv.hasArg(key)) { String v = srv.arg(key); v.toCharArray(tmp.wifi[i].password, sizeof(tmp.wifi[i].password)); } }
        // min_rssi
        { String key = String("wifi")+i+".min_rssi"; if (srv.hasArg(key)) { String v = srv.arg(key); v.trim(); if (!v.length()) tmp.wifi[i].minRssi = -127; else { int vi=v.toInt(); tmp.wifi[i].minRssi = validRssiInline(vi)?(int16_t)vi:(int16_t)-127; } } }
        // bssid
        { String key = String("wifi")+i+".bssid"; if (srv.hasArg(key)) { String v = srv.arg(key); v.trim(); if (v.length()) { uint8_t mac[6]; if (parseMacInline(v, mac)) { memcpy(tmp.wifi[i].bssid, mac, 6); tmp.wifi[i].bssidSet = true; } else { memset(tmp.wifi[i].bssid,0,6); tmp.wifi[i].bssidSet=false; } } else { memset(tmp.wifi[i].bssid,0,6); tmp.wifi[i].bssidSet=false; } } }
        // hidden
        { String key = String("wifi")+i+".hidden"; if (srv.hasArg(key)) { String v = srv.arg(key); v.trim(); v.toLowerCase(); tmp.wifi[i].hidden = (v=="true" || v=="1" || v=="on"); } }

        // static_ip (must take the LAST value: hidden=false then checkbox=true)
        {
          String key = String("wifi")+i+".static_ip";
          String v;
          // Get last occurrence so checkbox overrides hidden input
          bool found = false;
          const int ac = srv.args();
          for (int ai = 0; ai < ac; ++ai) {
            if (srv.argName(ai) == key) { v = srv.arg(ai); found = true; }
          }
          if (found) {
            v.trim(); v.toLowerCase();
            tmp.wifi[i].staticIp = (v=="true" || v=="1" || v=="on" || v=="yes");
          }
        }

        // ip/gateway/subnet/dns1/dns2
        auto parseIpInline = [](const String& s, uint8_t out[4])->bool{
          int a,b,c,d;
          if (sscanf(s.c_str(), "%d.%d.%d.%d", &a,&b,&c,&d) != 4) return false;
          if ((unsigned)a>255 || (unsigned)b>255 || (unsigned)c>255 || (unsigned)d>255) return false;
          out[0]=(uint8_t)a; out[1]=(uint8_t)b; out[2]=(uint8_t)c; out[3]=(uint8_t)d;
          return true;
        };

        auto setIpIfPresent = [&](const String& key, uint8_t out[4]){
          if (!srv.hasArg(key)) return;
          String v = srv.arg(key); v.trim();
          if (!v.length()) { out[0]=out[1]=out[2]=out[3]=0; return; }
          uint8_t ip[4];
          if (parseIpInline(v, ip)) memcpy(out, ip, 4);
          // else: ignore or clear; your call
        };

        setIpIfPresent(String("wifi")+i+".ip",      tmp.wifi[i].ip);
        setIpIfPresent(String("wifi")+i+".gateway", tmp.wifi[i].gateway);
        setIpIfPresent(String("wifi")+i+".subnet",  tmp.wifi[i].subnet);
        setIpIfPresent(String("wifi")+i+".dns1",    tmp.wifi[i].dns1);
        setIpIfPresent(String("wifi")+i+".dns2",    tmp.wifi[i].dns2);

        // ---- static IP validation (only if enabled) ----
        auto isZero4 = [](const uint8_t a[4])->bool{
          return a[0]==0 && a[1]==0 && a[2]==0 && a[3]==0;
        };

        if (tmp.wifi[i].staticIp) {
          // Require these three at minimum
          if (isZero4(tmp.wifi[i].ip) || isZero4(tmp.wifi[i].gateway) || isZero4(tmp.wifi[i].subnet)) {
            srv.sendHeader("Location", "/config?err=wifi_static_ip_incomplete&net=" + String(i));
            srv.send(303, F("text/plain"), F("Static IP requires ip/gateway/subnet"));
            return;
          }

          // DNS1: if not provided, default to gateway (common sensible default)
          if (isZero4(tmp.wifi[i].dns1)) {
            memcpy(tmp.wifi[i].dns1, tmp.wifi[i].gateway, 4);
          }
        }

        if (tmp.wifi[i].ssid[0]) ++newCount;
      }
      tmp.wifiNetworkCount = newCount;

      // Buttons / debounce / external RTC
      auto setU8  = [&](const char* name, uint8_t&  field){ if (!srv.hasArg(name)) return; long v=srv.arg(name).toInt(); if (v<0) v=0; if (v>255) v=255; field=(uint8_t)v; };
      auto setU16 = [&](const char* name, uint16_t& field){ if (!srv.hasArg(name)) return; long v=srv.arg(name).toInt(); if (v<0) v=0; if (v>65535) v=65535; field=(uint16_t)v; };
      auto setBool= [&](const char* name, bool& field){ if (!srv.hasArg(name)) return; String s=srv.arg(name); s.trim(); s.toLowerCase(); field=(s=="1"||s=="true"||s=="on"||s=="yes"); };

      setU16("debounce_ms",    tmp.debounceMs);
    }

    // ---------- Persist full config ----------
    // Debug aid for saving tmp bindings count if needed later.
              
    ConfigManager::save(tmp);           // writes file and updates active config
    //ConfigManager::debugDumpConfigFile();

    // Redirect back to GET with ok=1
    srv.sendHeader("Location", "/config?ok=1&tab=" + submit);
    srv.send(303, F("text/plain"), F("Saved"));
    
  });
}
