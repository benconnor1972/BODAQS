#include "Routes_Config.h"
#include <Arduino.h>
#include <ArduinoJson.h>
#include <ctype.h>
#include <stdlib.h>
#include <string.h>

#include "HtmlUtil.h"
#include "ConfigManager.h"
#include "SensorManager.h"
#include "SensorRegistry.h"
#include "OutputTransform.h"
#include "RTCManager.h"
#include "WiFiManager.h"
#include "PowerManager.h"
#include "WebServerManager.h"  // for canStart()
#include "UploadModeManager.h"
#include "StorageManager.h"
#include "ButtonManager.h"
#include "BoardSelect.h" 
#include "TransformRegistry.h"
#include "HttpFileSender.h"
#include "DebugLog.h"

#define WEB_LOGW(...) LOGW_TAG("WEB", __VA_ARGS__)

// ---- Helpers (file scope) ----
static String fmtIPv4(const uint8_t a[4]) {
  char buf[16];
  snprintf(buf, sizeof(buf), "%u.%u.%u.%u",
           a[0], a[1], a[2], a[3]);
  return String(buf);
}

static String minutesStringFromMs_(uint32_t ms) {
  if (ms == 0) return String("0");
  String s((double)ms / 60000.0, 3);
  while (s.endsWith("0")) s.remove(s.length() - 1);
  if (s.endsWith(".")) s.remove(s.length() - 1);
  return s;
}

static bool parseMinutesToMs_(const String& text, uint32_t& out) {
  String s = text;
  s.trim();
  if (!s.length()) return false;
  char* end = nullptr;
  const double minutes = strtod(s.c_str(), &end);
  if (end == s.c_str()) return false;
  while (end && *end && isspace((unsigned char)*end)) ++end;
  if (end && *end) return false;
  if (minutes < 0.0) return false;
  double ms = minutes * 60000.0;
  if (ms > 4294967295.0) ms = 4294967295.0;
  out = (uint32_t)(ms + 0.5);
  return true;
}

static void noteHttpActivity_() {
  WiFiManager::noteUserActivity();
  PowerManager::noteActivity();
}

static bool configEditLocked_(String* reason = nullptr) {
  if (!WebServerManager::canStart()) {
    if (reason) *reason = F("logging is active");
    return true;
  }
  if (UploadModeManager::isActive()) {
    if (reason) *reason = F("upload mode is active");
    return true;
  }
  return false;
}

static bool rejectConfigEditLocked_(WebServer& srv) {
  String reason;
  if (!configEditLocked_(&reason)) {
    return false;
  }
  srv.send(423, F("text/plain"), String(F("Configuration is locked while ")) + reason + F("."));
  return true;
}

static void applyLogSettingsLive_(const LoggerConfig& cfg) {
  Log_setEnabled(true);
  Log_resetLevel();
  if (cfg.logLevelOverride <= LOG_TRACE) {
    Log_setLevel((LogLevel)cfg.logLevelOverride);
  }
}

static void reloadTransformsForSensor_(const char* sensorName) {
  if (!sensorName || !*sensorName) return;

  if (SD_MMC.cardType() != CARD_NONE) {
    gTransforms.loadForSensor(sensorName, SD_MMC);
  }
}

static String transformLabelForSelected_(const char* sensorName, const String& selectedId) {
  if (!sensorName || !*sensorName) return String();

  String trimmed = selectedId;
  trimmed.trim();
  if (!trimmed.length()) return String();

  for (const auto& meta : gTransforms.list(sensorName)) {
    if (meta.id == trimmed) return String(meta.label);
  }
  return String();
}

static Sensor* findLiveSensorByName_(const char* name) {
  if (!name || !*name) return nullptr;

  for (uint8_t j = 0; j < SensorManager::count(); ++j) {
    Sensor* s = SensorManager::get(j);
    if (s && String(s->name()) == String(name)) return s;
  }
  return nullptr;
}

static bool parseSensorTypeKey_(String text, SensorType& out) {
  text.trim();
  if (text.equalsIgnoreCase("analog_pot") || text.equalsIgnoreCase("pot")) {
    out = SensorType::AnalogPot;
    return true;
  }
  if (text.equalsIgnoreCase("as5600_string_pot_analog") || text.equalsIgnoreCase("as5600_pot_analog")) {
    out = SensorType::AS5600StringPotAnalog;
    return true;
  }
  if (text.equalsIgnoreCase("as5600_string_pot_i2c") || text.equalsIgnoreCase("as5600_pot_i2c")) {
    out = SensorType::AS5600StringPotI2C;
    return true;
  }
  if (text.equalsIgnoreCase("as5600_angle_i2c") || text.equalsIgnoreCase("as5600_rotary_i2c") ||
      text.equalsIgnoreCase("as5600_rotary")) {
    out = SensorType::AS5600AngleI2C;
    return true;
  }
  if (text.equalsIgnoreCase("as5048b_angle_i2c") || text.equalsIgnoreCase("as5048b") ||
      text.equalsIgnoreCase("as5048_angle_i2c")) {
    out = SensorType::AS5048BAngleI2C;
    return true;
  }
  if (text.equalsIgnoreCase("dan_f10n_gps_uart") || text.equalsIgnoreCase("dan_f10n_gps") ||
      text.equalsIgnoreCase("gps_uart") || text.equalsIgnoreCase("gps")) {
    out = SensorType::DANF10NGps;
    return true;
  }
  return false;
}

static const char* defaultNamePrefix_(SensorType type) {
  switch (type) {
    case SensorType::AnalogPot: return "analog";
    case SensorType::AS5600StringPotAnalog: return "as5600a";
    case SensorType::AS5600StringPotI2C: return "as5600i";
    case SensorType::AS5048BAngleI2C: return "as5048";
    case SensorType::AS5600AngleI2C: return "as5600r";
    case SensorType::DANF10NGps: return "gps";
    default: return "sensor";
  }
}

static String uniqueSensorName_(SensorType type, String proposed) {
  proposed.trim();
  if (proposed.length() > 15) proposed = proposed.substring(0, 15);
  if (proposed.length() && ConfigManager::findSensorByName(proposed.c_str()) < 0) return proposed;

  const String prefix = defaultNamePrefix_(type);
  for (uint8_t i = 0; i < MAX_SENSORS; ++i) {
    String candidate = prefix + String((int)i);
    if (candidate.length() > 15) candidate = candidate.substring(0, 15);
    if (ConfigManager::findSensorByName(candidate.c_str()) < 0) return candidate;
  }
  return String("sensor");
}

static bool applyLiveSensorSpec_(uint8_t idx, const char* lookupName, const SensorSpec& sp) {
  Sensor* live = findLiveSensorByName_(lookupName);
  if (!live && lookupName && strcmp(lookupName, sp.name) != 0) {
    live = findLiveSensorByName_(sp.name);
  }
  if (!live) return false;
  if (!live->reconfigureFromSpec(sp)) return false;

  live->setMuted(sp.mutedDefault);

  long om = 0;
  sp.params.getInt("output_mode", om);
  const OutputMode mode = (OutputMode)om;
  live->setOutputMode(mode);

  bool inc = false;
  sp.params.getBool("include_raw", inc);
  live->setIncludeRaw(inc);

  String selId;
  sp.params.get("output_id", selId);
  selId.trim();

  reloadTransformsForSensor_(live->name());
  if (mode == OutputMode::RAW) {
    live->setSelectedTransformId("identity");
  } else {
    live->setSelectedTransformId(selId);
  }
  live->attachTransform(gTransforms);

  if (mode == OutputMode::RAW) {
    live->setOutputUnitsLabel("counts");
  } else if (mode == OutputMode::LINEAR) {
    String explicitLabel;
    sp.params.get("units_label", explicitLabel);
    live->setOutputUnitsLabel(explicitLabel.c_str());
  } else {
    const String label = transformLabelForSelected_(live->name(), live->selectedTransformId());
    live->setOutputUnitsLabel(label.c_str());
  }

  live->setAllowedCalMask(ConfigManager::calAllowedMaskByIndex(idx));
  return true;
}

using namespace HtmlUtil;

void registerConfigRoutes(WebServer& srv) {
  WebServer* S = &srv;

  // -------------------- GET /config --------------------
  S->on("/config", HTTP_GET, [S](){
    auto& srv = *S;
    noteHttpActivity_();

    // Read the active config for display
    const LoggerConfig& cfg = ConfigManager::get();

    String lockedReason;
    const bool locked = configEditLocked_(&lockedReason);
    const String dis  = locked ? F(" disabled") : F("");

    String html = htmlHeader(F("Config"));

    if (srv.hasArg("ok")) {
      html += F("<p style='background:#e7ffe7;border:1px solid #8bc34a;padding:8px;border-radius:6px'>Saved.</p>");
    }
    if (locked) {
      html += F("<p style='background:#fff3cd;border:1px solid #ffe08a;padding:8px;border-radius:6px'>"
                "Editing is disabled while ");
      html += htmlEscape(lockedReason);
      html += F(". Exit upload mode or stop logging to make changes.</p>");
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
    html += F("<label>Logger name: </label><input type='text' name='logger_name' maxlength='31' value='");
    html += htmlEscape(String(cfg.loggerName));
    html += F("'"); html += dis; html += F("><br>");

    html += F("<label>Sample rate (Hz): </label><input type='number' name='sample_rate_hz' min='1' max='2000' value='");
    html += String(cfg.sampleRateHz);
    html += F("'"); html += dis; html += F("><br>");

    html += F("<label>Log format: </label>");
    html += F("<label><input type='radio' name='log_format' value='bodaqs_standard'");
    if (cfg.logFormat == LogFormat::BodaqsStandard) html += F(" checked");
    html += dis; html += F("> BODAQS CSV</label> ");
    html += F("<label><input type='radio' name='log_format' value='syn_bike_raw'");
    if (cfg.logFormat == LogFormat::SynBikeRaw) html += F(" checked");
    html += dis; html += F("> syn.bike CSV</label> ");
    html += F("<label><input type='radio' name='log_format' value='bodaqs_compact_binary'");
    if (cfg.logFormat == LogFormat::BodaqsCompactBinary) html += F(" checked");
    html += dis; html += F("> BODAQS compact binary</label><br>");

    html += F("<label><input type='checkbox' name='omit_metadata' value='true'");
    if (cfg.omitMetadata) html += F(" checked");
    html += dis; html += F("> Omit log metadata JSON</label><br>");

    html += F("<label>Timestamp mode: </label><select name='timestamp_mode'");
    html += dis; html += F("><option value='human'");
    if (cfg.timestampHuman) html += F(" selected");
    html += F(">human</option><option value='fast'");
    if (!cfg.timestampHuman) html += F(" selected");
    html += F(">fast</option></select><br>");

    html += F("<label>Timezone (tz rule): </label><input type='text' name='tz' value='");
    html += htmlEscape(String(cfg.tz));
    html += F("'"); html += dis; html += F("><br>");
    
    html += F("<label>Auto-sleep idle (min): </label><input type='number' name='auto_sleep_idle_min' min='0' step='0.1' value='");
    html += minutesStringFromMs_(cfg.autoSleepIdleMs);
    html += F("'"); html += dis; html += F("><small>0 = disabled</small><br>");

    html += F("<label>Wi-Fi idle timeout (min): </label><input type='number' name='wifi_idle_timeout_min' min='0' step='0.1' value='");
    html += minutesStringFromMs_(cfg.wifiIdleTimeoutMs);
    html += F("'"); html += dis; html += F("><small>0 = disabled</small><br>");

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

    html += F("<div class='row'><label>Wi-Fi mode</label><select name='wifi_mode'");
    if (locked) html += F(" disabled");
    html += F("><option value='station'");
    if (cfg.wifiMode == WiFiMode::Station) html += F(" selected");
    html += F(">Station</option><option value='access_point'");
    if (cfg.wifiMode == WiFiMode::AccessPoint) html += F(" selected");
    html += F(">Access point</option></select></div>");

    html += F("<div class='row'><label>AP SSID</label><input type='text' name='wifi_ap_ssid' maxlength='31' value='");
    html += htmlEscape(String(cfg.wifiApSsid));
    html += F("'");
    if (locked) html += F(" disabled");
    html += F("></div>");

    html += F("<div class='row'><label>AP password</label><input type='password' name='wifi_ap_password' minlength='8' maxlength='63' value='");
    html += htmlEscape(String(cfg.wifiApPassword));
    html += F("'");
    if (locked) html += F(" disabled");
    html += F("><small>8-63 characters</small></div>");

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

      html += F("</fieldset>");
    }

    html += F("<p><button type='submit'"); html += dis; html += F(">Save</button></p>");
    html += F("</form>");

    html += htmlFooter();
    HttpFileSender::sendText(srv, 200, F("text/html"), html, F("no-store"));
  });

  // -------------------- GET /config/sensors --------------------
  S->on("/config/sensors", HTTP_GET, [S](){
    auto& srv = *S;
    noteHttpActivity_();

    const LoggerConfig& cfg = ConfigManager::get();
    String lockedReason;
    const bool locked = configEditLocked_(&lockedReason);
    const String dis  = locked ? F(" disabled") : F("");

    String html = htmlHeader(F("Sensors"));

    if (srv.hasArg("ok")) {
      html += F("<p style='background:#e7ffe7;border:1px solid #8bc34a;padding:8px;border-radius:6px'>Saved.</p>");
    }
    if (srv.hasArg("reboot")) {
      html += F("<p style='background:#fff3cd;border:1px solid #ffe08a;padding:8px;border-radius:6px'>"
                "Sensor add/delete changes are saved. Restart the logger to rebuild the live sensor set."
                "</p>");
    }
    if (locked) {
      html += F("<p style='background:#fff3cd;border:1px solid #ffe08a;padding:8px;border-radius:6px'>"
                "Editing is disabled while ");
      html += htmlEscape(lockedReason);
      html += F(". Exit upload mode or stop logging to make changes.</p>");
    }

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
          SensorType::AS5048BAngleI2C,
          SensorType::AS5600AngleI2C,
          SensorType::DANF10NGps,
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

        emitParamRow("i2c_bus", "I2C bus");
        emitParamRow("i2c_addr", "I2C address");

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

        // ---- Usage ----
        html += F("<h4>Usage</h4>");
        emitParamRow("end", "End");
        emitParamRow("primary_domain", "Primary domain");
        emitParamRow("primary_quantity", "Primary quantity");

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
        emitParamRow("installed_zero_count", "Installed zero count");
        emitParamRow("zero_count", "Zero count");

        // ---- Wrapping ----
        if (findDef("counts_per_turn") || findDef("wrap_threshold_counts") || findDef("assume_turn0_at_start")) {
          html += F("<h4>Wrapping</h4>");
          emitParamRow("counts_per_turn", "Counts per turn");
          emitParamRow("wrap_threshold_counts", "Wrap threshold (counts)");
          emitParamRow("assume_turn0_at_start", "Assume turn 0 at log start");
        }

        // (Optional) render remaining params under "Other"
        const char* shown[] = {
          "ain","muted","i2c_bus","i2c_addr",
          "output_mode","include_raw","sensor_full_travel_mm","units_label",
          "end","primary_domain","primary_quantity","raw_domain",
          "cal_allowed","sensor_zero_count","sensor_full_count","installed_zero_count","zero_count",
          "counts_per_turn","wrap_threshold_counts","assume_turn0_at_start"
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

        html += "<div class='row'><label>Remove</label><button type='submit' name='delete_sensor_idx' value='";
        html += String(i);
        html += "'";
        if (locked) html += " disabled";
        html += ">Delete this sensor</button>";
        html += "<small>Removes the sensor from logger config only; transform files are left in place.</small></div>";

        html += F("</fieldset>");
        delay(0);
      }

    html += F("<fieldset><legend>New sensor</legend>");
    html += F("<div class='row'><label>Type</label><select name='add_sensor_type'");
    html += dis;
    html += F(">");
    const SensorType addTypeChoices[] = {
      SensorType::AnalogPot,
      SensorType::AS5600StringPotAnalog,
      SensorType::AS5600StringPotI2C,
      SensorType::AS5048BAngleI2C,
      SensorType::AS5600AngleI2C,
      SensorType::DANF10NGps,
    };
    for (const auto typeChoice : addTypeChoices) {
      const SensorTypeInfo* tiChoice = SensorRegistry::lookup(typeChoice);
      if (!tiChoice) continue;
      const char* key = SensorRegistry::typeKey(typeChoice);
      const char* label = SensorRegistry::typeLabel(typeChoice);
      html += F("<option value='");
      html += htmlEscape(String(key ? key : "unknown"));
      html += F("'>");
      html += htmlEscape(String(label ? label : "Unknown Sensor"));
      html += F("</option>");
    }
    html += F("</select></div>");
    html += F("<div class='row'><label>Name</label><input type='text' name='add_sensor_name' maxlength='15' placeholder='optional'");
    html += dis;
    html += F("><small>Leave blank to auto-name.</small></div>");
    html += F("<p><button type='submit' name='add_sensor' value='1'");
    html += dis;
    html += F(">Add Sensor</button></p>");
    html += F("</fieldset>");

    

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
    HttpFileSender::sendText(srv, 200, F("text/html"), html, F("no-store"));
  });

  // -------------------- POST /config/sensors --------------------
  S->on("/config/sensors", HTTP_POST, [S](){
    auto& srv = *S;
    noteHttpActivity_();

    if (rejectConfigEditLocked_(srv)) return;

    LoggerConfig tmp = ConfigManager::get();

    if (srv.hasArg("delete_sensor_idx")) {
      const int idx = srv.arg("delete_sensor_idx").toInt();
      if (idx < 0 || idx >= (int)ConfigManager::sensorCount()) {
        srv.send(400, F("text/plain"), F("Invalid sensor index"));
        return;
      }
      if (!ConfigManager::deleteSensorByIndex((uint8_t)idx) || !ConfigManager::save(ConfigManager::get())) {
        srv.send(500, F("text/plain"), F("Failed to delete sensor"));
        return;
      }
      srv.sendHeader("Location", "/config/sensors?ok=1&reboot=1");
      srv.send(303, F("text/plain"), F("Sensor deleted"));
      return;
    }

    if (srv.hasArg("add_sensor")) {
      SensorType newType = SensorType::AnalogPot;
      if (srv.hasArg("add_sensor_type")) {
        (void)parseSensorTypeKey_(srv.arg("add_sensor_type"), newType);
      }
      const String uniqueName = uniqueSensorName_(newType, srv.hasArg("add_sensor_name") ? srv.arg("add_sensor_name") : String());
      if (!ConfigManager::appendSensor(newType, uniqueName.c_str()) || !ConfigManager::save(ConfigManager::get())) {
        srv.send(500, F("text/plain"), F("Failed to add sensor"));
        return;
      }
      const int newIdx = (int)ConfigManager::sensorCount() - 1;
      srv.sendHeader("Location", "/config/sensors?ok=1&reboot=1#sensor-" + String(newIdx));
      srv.send(303, F("text/plain"), F("Sensor added"));
      return;
    }

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
      char lookupName[sizeof(sp.name)] = {0};
      strncpy(lookupName, sp.name, sizeof(lookupName) - 1);

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
            (void)parseSensorTypeKey_(v, sp.type);
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
        if (getArgLast("i2c_bus", v)) {
          v.trim();
          sp.params.setInt("i2c_bus", v.toInt());
        }
        if (getArgLast("i2c_addr", v)) {
          v.trim();
          sp.params.setInt("i2c_addr", v.toInt());
        }
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
        if (getArgLast("end", v)) { v.trim(); sp.params.set("end", v); }
        if (getArgLast("primary_domain", v)) { v.trim(); sp.params.set("primary_domain", v); }
        if (getArgLast("primary_quantity", v)) { v.trim(); sp.params.set("primary_quantity", v); }

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
        if (getArgLast("installed_zero_count", v)) { long vi = v.toInt(); sp.params.setInt("installed_zero_count", vi); }
        if (getArgLast("zero_count", v)) { long vi = v.toInt(); sp.params.setInt("zero_count", vi); }
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
            pkey.equalsIgnoreCase("end") || pkey.equalsIgnoreCase("primary_domain") ||
            pkey.equalsIgnoreCase("primary_quantity") || pkey.equalsIgnoreCase("raw_domain") ||
            pkey.equalsIgnoreCase("cal_allowed") || pkey.equalsIgnoreCase("sensor_zero_count") ||
            pkey.equalsIgnoreCase("sensor_full_count") || pkey.equalsIgnoreCase("installed_zero_count") ||
            pkey.equalsIgnoreCase("zero_count") ||
            pkey.equalsIgnoreCase("counts_per_turn") || pkey.equalsIgnoreCase("wrap_threshold_counts") ||
            pkey.equalsIgnoreCase("assume_turn0_at_start") ||
            pkey.equalsIgnoreCase("ain") || pkey.equalsIgnoreCase("i2c_bus") ||
            pkey.equalsIgnoreCase("i2c_addr")) {
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
      if (!typeChanged && !applyLiveSensorSpec_(idx, lookupName, sp)) {
        WEB_LOGW("live apply skipped for sensor %u ('%s')\n",
                 (unsigned)idx,
                 lookupName[0] ? lookupName : sp.name);
            // POLY/LUT: leave label to transform’s metadata (set via Transforms route)
      }
    }

    if (!ConfigManager::save(tmp)) {
      srv.send(500, F("text/plain"), F("Failed to save config"));
      return;
    }
    String location = "/config/sensors?ok=1";
    if (applyTypeIdx >= 0) {
      location += "#sensor-";
      location += String(applyTypeIdx);
    }
    srv.sendHeader("Location", location);
    srv.send(303, F("text/plain"), F("Saved"));
  });

  // -------------------- POST /config --------------------
  S->on("/config", HTTP_POST, [S](){
    auto& srv = *S;
    noteHttpActivity_();

    if (rejectConfigEditLocked_(srv)) return;

    String submit = srv.hasArg("submit") ? srv.arg("submit") : "";
    submit.toLowerCase();

    if (submit != "globals" && submit != "sensors") {
      srv.send(400, F("text/plain"), F("Unknown submit section"));
      return;
    }

    // Working copy we will persist at the end
    LoggerConfig tmp = ConfigManager::get();

    // ---------- GLOBALS ----------
    if (srv.hasArg("logger_name")) {
      String loggerName = srv.arg("logger_name");
      loggerName.trim();
      loggerName.toCharArray(tmp.loggerName, sizeof(tmp.loggerName));
    }

    if (srv.hasArg("sample_rate_hz")) {
      uint16_t hz = (uint16_t)srv.arg("sample_rate_hz").toInt();
      tmp.sampleRateHz = hz;
    }

    if (srv.hasArg("timestamp_mode")) {
      const String tsm = srv.arg("timestamp_mode");
      if      (tsm == "human") tmp.timestampHuman = true;
      else if (tsm == "fast")  tmp.timestampHuman = false;
    }

    if (srv.hasArg("log_format")) {
      LogFormat fmt;
      String v = srv.arg("log_format");
      v.trim();
      if (ConfigManager::parseLogFormat(v.c_str(), fmt)) {
        tmp.logFormat = fmt;
      }
    }

    tmp.omitMetadata = srv.hasArg("omit_metadata");

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

      if (srv.hasArg("wifi_mode")) {
        WiFiMode mode;
        String modeText = srv.arg("wifi_mode");
        modeText.trim();
        if (ConfigManager::parseWifiMode(modeText.c_str(), mode)) {
          tmp.wifiMode = mode;
        }
      }

      if (srv.hasArg("wifi_ap_ssid")) {
        String apSsid = srv.arg("wifi_ap_ssid");
        apSsid.trim();
        if (!apSsid.length()) apSsid = F("BODAQS");
        if (apSsid.length() > 31) apSsid = apSsid.substring(0, 31);
        apSsid.toCharArray(tmp.wifiApSsid, sizeof(tmp.wifiApSsid));
      }

      if (srv.hasArg("wifi_ap_password")) {
        String apPassword = srv.arg("wifi_ap_password");
        apPassword.trim();
        if (!apPassword.length()) apPassword = F("bodaqslogger");
        if (apPassword.length() < 8 || apPassword.length() > 63) {
          srv.sendHeader("Location", "/config?err=wifi_ap_password_length");
          srv.send(303, F("text/plain"), F("AP password must be 8-63 characters"));
          return;
        }
        apPassword.toCharArray(tmp.wifiApPassword, sizeof(tmp.wifiApPassword));
      }

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

        // ip/gateway/subnet/dns1
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
      auto setU32 = [&](const char* name, uint32_t& field){
        if (!srv.hasArg(name)) return;
        unsigned long long v = strtoull(srv.arg(name).c_str(), nullptr, 10);
        if (v > 0xFFFFFFFFULL) v = 0xFFFFFFFFULL;
        field = (uint32_t)v;
      };
      auto setBool= [&](const char* name, bool& field){ if (!srv.hasArg(name)) return; String s=srv.arg(name); s.trim(); s.toLowerCase(); field=(s=="1"||s=="true"||s=="on"||s=="yes"); };

      setU16("debounce_ms",    tmp.debounceMs);
      uint32_t timeoutMs = 0;
      if (srv.hasArg("auto_sleep_idle_min") && parseMinutesToMs_(srv.arg("auto_sleep_idle_min"), timeoutMs)) {
        tmp.autoSleepIdleMs = timeoutMs;
      } else {
        setU32("auto_sleep_idle_ms", tmp.autoSleepIdleMs);
      }
      if (srv.hasArg("wifi_idle_timeout_min") && parseMinutesToMs_(srv.arg("wifi_idle_timeout_min"), timeoutMs)) {
        tmp.wifiIdleTimeoutMs = timeoutMs;
      } else {
        setU32("wifi_idle_timeout_ms", tmp.wifiIdleTimeoutMs);
      }
    }

    // ---------- Persist full config ----------
    // Debug aid for saving tmp bindings count if needed later.
              
    if (!ConfigManager::save(tmp)) {
      srv.send(500, F("text/plain"), F("Failed to save config"));
      return;
    }

    const LoggerConfig& liveCfg = ConfigManager::get();
    StorageManager_setSampleRate(liveCfg.sampleRateHz);
    RTCManager_setHumanReadable(liveCfg.timestampHuman);
    RTCManager_setTimezone(liveCfg.tz);
    applyLogSettingsLive_(liveCfg);
    ButtonManager_setDebounceAll(liveCfg.debounceMs);
    //ConfigManager::debugDumpConfigFile();

    // Redirect back to GET with ok=1
    srv.sendHeader("Location", "/config?ok=1&tab=" + submit);
    srv.send(303, F("text/plain"), F("Saved"));
    
  });
}
