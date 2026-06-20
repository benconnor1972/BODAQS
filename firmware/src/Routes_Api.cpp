#include "Routes_Api.h"

#include <Arduino.h>
#include <ArduinoJson.h>
#include <WiFi.h>
#include "SD_MMC.h"

#include "ConfigManager.h"
#include "FirmwareInfo.h"
#include "LoggingManager.h"
#include "PowerManager.h"
#include "RTCManager.h"
#include "StorageManager.h"
#include "AnalogInputManager.h"
#include "BoardSelect.h"
#include "SensorRegistry.h"
#include "UploadAckIndex.h"
#include "UploadModeManager.h"
#include "UploadSessionCleanup.h"
#include "UploadSessionScanner.h"
#include "WiFiManager.h"
#include "HttpFileSender.h"

namespace {

constexpr uint16_t kSessionListLimit = 24;
const char* kSessionScanDir = "/";

static void noteHttpActivity_() {
  WiFiManager::noteUserActivity();
  PowerManager::noteActivity();
}

static String jsonString_(JsonDocument& doc) {
  String out;
  serializeJson(doc, out);
  return out;
}

static void sendJson_(WebServer& srv, int statusCode, JsonDocument& doc) {
  srv.sendHeader(F("Cache-Control"), F("no-store"));
  srv.send(statusCode, F("application/json"), jsonString_(doc));
}

static void sendError_(WebServer& srv, int statusCode, const char* error, const char* message) {
  JsonDocument doc;
  doc["schema"] = "bodaqs.logger.error";
  doc["api_version"] = 1;
  doc["error"] = error ? error : "error";
  doc["message"] = message ? message : "";
  sendJson_(srv, statusCode, doc);
}

static bool requireUploadMode_(WebServer& srv) {
  if (UploadModeManager::isActive()) return true;
  sendError_(srv, 409, "upload_mode_required", "Upload mode is required for this endpoint.");
  return false;
}

static void addEnvelope_(JsonDocument& doc, const char* schema) {
  doc["schema"] = schema;
  doc["api_version"] = 1;
}

static void addLoggerIdentity_(JsonDocument& doc) {
  doc["logger_id"] = ConfigManager::loggerId();
  doc["display_name"] = ConfigManager::get().loggerName;
}

static void sendUploadModeState_(WebServer& srv) {
  JsonDocument doc;
  addEnvelope_(doc, "bodaqs.logger.upload_mode");
  addLoggerIdentity_(doc);
  doc["upload_mode"] = UploadModeManager::isActive();
  sendJson_(srv, 200, doc);
}

static void handleDevice_(WebServer& srv) {
  JsonDocument doc;
  addEnvelope_(doc, "bodaqs.logger.device");
  addLoggerIdentity_(doc);

  const WiFiStatus st = WiFiManager::status();
  doc["firmware_name"] = FirmwareInfo::name();
  doc["firmware_version"] = FirmwareInfo::version();
  doc["firmware_build"] = FirmwareInfo::buildDateTime();
  doc["board"] = FirmwareInfo::boardName();
  doc["hostname"] = WiFiManager::hostname();
  doc["wifi_mode"] = ConfigManager::wifiModeKey(st.mode);
  doc["network_up"] = st.networkUp;
  doc["ip"] = st.ip;
  doc["sta_mac"] = WiFi.macAddress();
  doc["ap_mac"] = WiFi.softAPmacAddress();

  JsonArray caps = doc["capabilities"].to<JsonArray>();
  caps.add("upload_mode");
  caps.add("session_discovery");
  caps.add("session_archive_zip");
  caps.add("session_data");
  caps.add("session_ack");
  caps.add("session_delete");
  caps.add("mdns_discovery");

  sendJson_(srv, 200, doc);
}

static void handleStatus_(WebServer& srv) {
  UploadSessionScanner::ScanSummary scanSummary;
  (void)UploadSessionScanner::scan(kSessionScanDir, nullptr, 0, &scanSummary);

  const WiFiStatus st = WiFiManager::status();
  JsonDocument doc;
  addEnvelope_(doc, "bodaqs.logger.status");
  addLoggerIdentity_(doc);
  doc["upload_mode"] = UploadModeManager::isActive();
  doc["logging_active"] = LoggingManager::isRunning();
  doc["storage_available"] = scanSummary.storageAvailable;
  doc["storage_directory_opened"] = scanSummary.directoryOpened;
  JsonObject storage = doc["storage"].to<JsonObject>();
  storage["card_detected"] = StorageManager_cardDetected();
  storage["mounted"] = StorageManager_isMounted();
  storage["status"] = StorageManager_lastStatus();

  JsonObject battery = doc["battery"].to<JsonObject>();
  battery["gauge_ok"] = PowerManager::fuelGaugeOk();
  battery["voltage_v"] = PowerManager::batteryVoltage();
  battery["soc_percent"] = PowerManager::batterySocPercent();
  battery["low"] = PowerManager::batteryLow();
  battery["alert_active"] = PowerManager::fuelAlertActive();
  battery["alert_cause"] = PowerManager::fuelAlertCause();
  battery["alert_status_raw"] = PowerManager::fuelAlertStatusRaw();

  JsonObject analog = doc["analog"].to<JsonObject>();
  analog["rail_enabled"] = PowerManager::analogRailEnabled();
  analog["fault_active"] = PowerManager::analogRailFaultActive();
  analog["fault_latched"] = PowerManager::analogRailFaultLatched();
  analog["fault_text"] = PowerManager::analogRailFaultText();
  analog["requested_rate_hz"] = ConfigManager::get().sampleRateHz;
  analog["effective_rate_hz"] = AnalogInputManager::effectiveSampleRateHz();
  JsonArray adcs = analog["external_adcs"].to<JsonArray>();
  if (board::gBoard) {
    for (uint8_t i = 0; i < board::gBoard->external_adc_count && i < board::BOARD_MAX_EXTERNAL_ADCS; ++i) {
      JsonObject adc = adcs.add<JsonObject>();
      adc["index"] = i;
      adc["active_channels"] = AnalogInputManager::activeChannelCount(i);
      adc["data_rate_sps"] = AnalogInputManager::configuredDataRateSps(i);
    }
  }

  JsonObject rtc = doc["rtc"].to<JsonObject>();
  rtc["source"] = RTCManager_sourceLabel();
  rtc["external"] = RTCManager_usingExternalRtc();
  rtc["valid"] = RTCManager_hasValidTime();
  rtc["external_last_read_ok"] = RTCManager_externalRtcLastReadOk();
  rtc["external_porf"] = RTCManager_externalRtcPorf();
  doc["wifi_mode"] = ConfigManager::wifiModeKey(st.mode);
  doc["network_up"] = st.networkUp;
  doc["ip"] = st.ip;
  doc["hostname"] = st.hostname;
  doc["session_count"] = scanSummary.candidateCount;
  doc["importable_session_count"] = scanSummary.completeCount;
  doc["incomplete_session_count"] = scanSummary.incompleteCount;
  doc["temp_archive_count"] = scanSummary.tempArchiveCount;
  doc["scan_truncated"] = scanSummary.truncatedCandidates || scanSummary.truncatedOutput;
  sendJson_(srv, 200, doc);
}

static void handleSessions_(WebServer& srv) {
  if (!requireUploadMode_(srv)) return;

  if (SD_MMC.cardType() == CARD_NONE) {
    sendError_(srv, 503, "storage_unavailable", "SD storage is not available.");
    return;
  }

  UploadSessionScanner::SessionInfo sessions[kSessionListLimit];
  UploadSessionScanner::ScanSummary scanSummary;
  const uint16_t n = UploadSessionScanner::scan(kSessionScanDir, sessions, kSessionListLimit, &scanSummary);

  JsonDocument doc;
  addEnvelope_(doc, "bodaqs.logger.sessions");
  addLoggerIdentity_(doc);
  doc["session_count"] = scanSummary.candidateCount;
  doc["importable_session_count"] = scanSummary.completeCount;
  doc["incomplete_session_count"] = scanSummary.incompleteCount;
  doc["returned_session_count"] = n;
  doc["scan_truncated"] = scanSummary.truncatedCandidates || scanSummary.truncatedOutput;

  JsonArray arr = doc["sessions"].to<JsonArray>();
  for (uint16_t i = 0; i < n; ++i) {
    JsonObject item = arr.add<JsonObject>();
    item["session_id"] = sessions[i].sessionId;
    item["session_stem"] = sessions[i].sessionStem;
    item["csv_path"] = sessions[i].csvPath;
    item["json_path"] = sessions[i].jsonPath;
    item["archive_path"] = sessions[i].archivePath;
    item["data_format"] = sessions[i].dataFormat;
    item["data_path"] = sessions[i].dataPath;
    item["archive_ready"] = sessions[i].archiveReady;
    item["data_ready"] = sessions[i].dataReady;
    item["archive_size"] = sessions[i].archiveSize;
    item["data_size"] = sessions[i].dataSize;
    item["uploaded"] = sessions[i].uploaded;
    item["acknowledged"] = sessions[i].acknowledged;
  }

  sendJson_(srv, 200, doc);
}

static void handleArchive_(WebServer& srv) {
  if (!requireUploadMode_(srv)) return;

  if (!srv.hasArg("id") || srv.arg("id").length() == 0) {
    sendError_(srv, 400, "missing_session_id", "Missing required query argument: id.");
    return;
  }
  if (SD_MMC.cardType() == CARD_NONE) {
    sendError_(srv, 503, "storage_unavailable", "SD storage is not available.");
    return;
  }

  UploadSessionScanner::SessionInfo session;
  if (!UploadSessionScanner::findBySessionId(srv.arg("id").c_str(), session, kSessionScanDir)) {
    sendError_(srv, 404, "unknown_session", "No complete session matches the requested id.");
    return;
  }
  if (!session.archiveReady || !session.archivePath.length()) {
    sendError_(srv, 404, "archive_not_available", "The requested session does not have a CSV ZIP archive.");
    return;
  }

  const String filename = session.sessionId + F(".zip");
  if (!HttpFileSender::sendSdFile(srv, session.archivePath, F("application/zip"), filename, F("no-store"))) {
    sendError_(srv, 404, "archive_not_found", "The session archive is not available.");
  }
}

static void handleData_(WebServer& srv) {
  if (!requireUploadMode_(srv)) return;

  if (!srv.hasArg("id") || srv.arg("id").length() == 0) {
    sendError_(srv, 400, "missing_session_id", "Missing required query argument: id.");
    return;
  }
  if (SD_MMC.cardType() == CARD_NONE) {
    sendError_(srv, 503, "storage_unavailable", "SD storage is not available.");
    return;
  }

  UploadSessionScanner::SessionInfo session;
  if (!UploadSessionScanner::findBySessionId(srv.arg("id").c_str(), session, kSessionScanDir)) {
    sendError_(srv, 404, "unknown_session", "No complete session matches the requested id.");
    return;
  }
  if (session.dataFormat != "bdq" || !session.dataReady || !session.dataPath.length()) {
    sendError_(srv, 404, "data_not_available", "The requested session does not have a loose BDQ data file.");
    return;
  }

  const String filename = session.sessionId + F(".bdq");
  if (!HttpFileSender::sendSdFile(srv, session.dataPath, F("application/octet-stream"), filename, F("no-store"))) {
    sendError_(srv, 404, "data_not_found", "The session data file is not available.");
  }
}

static bool readJsonBody_(WebServer& srv, JsonDocument& doc) {
  const String body = srv.arg("plain");
  if (!body.length()) {
    sendError_(srv, 400, "missing_body", "Request body must be JSON.");
    return false;
  }

  DeserializationError err = deserializeJson(doc, body);
  if (err) {
    sendError_(srv, 400, "invalid_json", "Request body is not valid JSON.");
    return false;
  }

  return true;
}

static void handleAck_(WebServer& srv) {
  if (!requireUploadMode_(srv)) return;
  if (SD_MMC.cardType() == CARD_NONE) {
    sendError_(srv, 503, "storage_unavailable", "SD storage is not available.");
    return;
  }

  JsonDocument req;
  if (!readJsonBody_(srv, req)) return;

  UploadAckIndex::AckRecord record;
  record.sessionId = req["session_id"] | "";
  record.status = req["status"] | "imported";
  record.libraryId = req["library_id"] | "";
  record.runId = req["run_id"] | "";
  record.importedAt = req["imported_at"] | "";

  record.sessionId.trim();
  record.status.trim();
  if (!record.sessionId.length()) {
    sendError_(srv, 400, "missing_session_id", "Missing required field: session_id.");
    return;
  }
  if (!record.status.length()) {
    record.status = F("imported");
  }

  UploadSessionScanner::SessionInfo session;
  if (!UploadSessionScanner::findBySessionId(record.sessionId.c_str(), session, kSessionScanDir)) {
    sendError_(srv, 404, "unknown_session", "No complete session matches the requested id.");
    return;
  }

  String error;
  if (!UploadAckIndex::markSessionAcknowledged(record, &error)) {
    sendError_(srv, 500, "ack_failed", error.c_str());
    return;
  }

  JsonDocument resp;
  addEnvelope_(resp, "bodaqs.logger.session_ack");
  addLoggerIdentity_(resp);
  resp["session_id"] = record.sessionId;
  resp["status"] = record.status;
  resp["library_id"] = record.libraryId;
  resp["run_id"] = record.runId;
  resp["imported_at"] = record.importedAt;
  resp["acknowledged"] = true;
  resp["index_path"] = UploadAckIndex::indexPath();
  sendJson_(srv, 200, resp);
}

static void addCleanupResult_(JsonDocument& doc, const UploadSessionCleanup::CleanupResult& result) {
  doc["mode"] = result.mode;
  doc["ok"] = result.ok;
  doc["error"] = result.error;

  JsonObject files = doc["files"].to<JsonObject>();
  JsonObject csv = files["csv"].to<JsonObject>();
  csv["ok"] = result.csvOk;
  csv["path"] = result.csvPath;
  if (result.csvTargetPath.length()) csv["target_path"] = result.csvTargetPath;

  JsonObject json = files["json"].to<JsonObject>();
  json["ok"] = result.jsonOk;
  json["path"] = result.jsonPath;
  if (result.jsonTargetPath.length()) json["target_path"] = result.jsonTargetPath;

  JsonObject archive = files["archive"].to<JsonObject>();
  archive["ok"] = result.archiveOk;
  archive["path"] = result.archivePath;
  if (result.archiveTargetPath.length()) archive["target_path"] = result.archiveTargetPath;

  JsonObject data = files["data"].to<JsonObject>();
  data["ok"] = result.dataOk;
  data["path"] = result.dataPath;
  if (result.dataTargetPath.length()) data["target_path"] = result.dataTargetPath;
}

static void handleDelete_(WebServer& srv) {
  if (!requireUploadMode_(srv)) return;
  if (SD_MMC.cardType() == CARD_NONE) {
    sendError_(srv, 503, "storage_unavailable", "SD storage is not available.");
    return;
  }

  JsonDocument req;
  if (!readJsonBody_(srv, req)) return;

  String sessionId = req["session_id"] | "";
  String modeText = req["mode"] | "";
  sessionId.trim();
  modeText.trim();

  if (!sessionId.length()) {
    sendError_(srv, 400, "missing_session_id", "Missing required field: session_id.");
    return;
  }
  if (!modeText.length()) {
    sendError_(srv, 400, "missing_mode", "Missing required field: mode.");
    return;
  }

  UploadSessionCleanup::CleanupMode mode;
  if (!UploadSessionCleanup::parseMode(modeText.c_str(), mode)) {
    sendError_(srv, 400, "invalid_mode", "Mode must be 'move_to_uploaded' or 'delete'.");
    return;
  }

  UploadSessionScanner::SessionInfo session;
  if (!UploadSessionScanner::findBySessionId(sessionId.c_str(), session, kSessionScanDir)) {
    sendError_(srv, 404, "unknown_session", "No complete session matches the requested id.");
    return;
  }

  if (!UploadAckIndex::isSessionAcknowledged(sessionId.c_str())) {
    sendError_(srv, 409, "session_not_acknowledged", "Session must be acknowledged before cleanup.");
    return;
  }

  UploadSessionCleanup::CleanupResult result;
  const bool ok = UploadSessionCleanup::cleanupSession(session, mode, result);

  JsonDocument doc;
  addEnvelope_(doc, "bodaqs.logger.session_delete");
  addLoggerIdentity_(doc);
  doc["session_id"] = sessionId;
  doc["acknowledged"] = true;
  addCleanupResult_(doc, result);
  sendJson_(srv, ok ? 200 : 500, doc);
}

static bool configEditLocked_() {
  return LoggingManager::isRunning() || UploadModeManager::isActive();
}

static bool rejectConfigEditLocked_(WebServer& srv) {
  if (!configEditLocked_()) return false;
  sendError_(srv, 423, "config_locked", "Configuration is locked while logging or upload mode is active.");
  return true;
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

static const char* paramTypeName_(ParamType type) {
  switch (type) {
    case ParamType::Bool: return "bool";
    case ParamType::Int: return "int";
    case ParamType::Float: return "float";
    case ParamType::Enum: return "enum";
    default: return "string";
  }
}

static const char* loggerOutputModeName_(long value) {
  return value == 0 ? "RAW" : "LINEAR";
}

static long parseLoggerOutputMode_(String text, long fallback = 1) {
  text.trim();
  text.toUpperCase();
  if (text == "RAW" || text == "0") return 0;
  if (text == "LINEAR" || text == "1") return 1;
  return fallback == 0 ? 0 : 1;
}

static void addSensorParamsJson_(JsonObject obj, const SensorSpec& sp) {
  JsonObject params = obj["params"].to<JsonObject>();
  const SensorTypeInfo* ti = SensorRegistry::lookup(sp.type);
  size_t defCount = 0;
  const ParamDef* defs = ti ? ti->paramDefs(defCount) : nullptr;
  for (size_t i = 0; defs && i < defCount; ++i) {
    const ParamDef& pd = defs[i];
    if (!pd.key || !*pd.key) continue;
    if (strcasecmp(pd.key, "output_id") == 0) continue;
    if (strcasecmp(pd.key, "output_mode") == 0) {
      long mode = 0;
      sp.params.getInt(pd.key, mode);
      params[pd.key] = loggerOutputModeName_(mode);
      continue;
    }

    if (pd.type == ParamType::Bool) {
      bool b = false;
      if (sp.params.getBool(pd.key, b)) params[pd.key] = b;
      else if (pd.def) params[pd.key] = pd.def;
    } else if (pd.type == ParamType::Int) {
      long v = 0;
      if (sp.params.getInt(pd.key, v)) params[pd.key] = v;
      else if (pd.def) params[pd.key] = pd.def;
    } else if (pd.type == ParamType::Float) {
      double f = 0.0;
      if (sp.params.getFloat(pd.key, f)) params[pd.key] = f;
      else if (pd.def) params[pd.key] = pd.def;
    } else {
      String s;
      if (sp.params.get(pd.key, s)) params[pd.key] = s;
      else if (pd.def) params[pd.key] = pd.def;
    }
  }
}

static void addSensorJson_(JsonObject obj, uint8_t index, const SensorSpec& sp, bool includeParams) {
  obj["index"] = index;
  obj["name"] = sp.name;
  obj["type"] = SensorRegistry::typeKey(sp.type);
  obj["type_label"] = SensorRegistry::typeLabel(sp.type);
  obj["muted"] = sp.mutedDefault;
  const CalModeMask supported = SensorRegistry::supportedCalMask(sp.type);
  const CalModeMask allowed = ConfigManager::calAllowedMaskByIndex(index);
  const CalModeMask effective = (allowed == 0xFF) ? supported : (supported & allowed);
  String calMethods;
  if (effective & CAL_ZERO) { if (calMethods.length()) calMethods += ","; calMethods += "ZERO"; }
  if (effective & CAL_RANGE) { if (calMethods.length()) calMethods += ","; calMethods += "RANGE"; }
  if (!calMethods.length()) calMethods = "NONE";
  obj["calibration_methods"] = calMethods;
  obj["calibration_methods_read_only"] = true;
  if (includeParams) addSensorParamsJson_(obj, sp);
}

static void addConfigGlobalsJson_(JsonObject obj, const LoggerConfig& cfg) {
  obj["logger_name"] = cfg.loggerName;
  obj["sample_rate_hz"] = cfg.sampleRateHz;
  obj["log_format"] = ConfigManager::logFormatKey(cfg.logFormat);
  obj["omit_metadata"] = cfg.omitMetadata;
  obj["timestamp_mode"] = cfg.timestampHuman ? "human" : "fast";
  obj["tz"] = cfg.tz;
  obj["auto_sleep_idle_ms"] = cfg.autoSleepIdleMs;
  obj["wifi_idle_timeout_ms"] = cfg.wifiIdleTimeoutMs;
  obj["wifi_mode"] = ConfigManager::wifiModeKey(cfg.wifiMode);
  obj["wifi_enabled_default"] = cfg.wifiEnabledDefault;
  obj["wifi_auto_time_on_rtc_invalid"] = cfg.wifiAutoTimeOnRtcInvalid;
  obj["wifi_ap_ssid"] = cfg.wifiApSsid;
  obj["ntp_servers"] = cfg.ntpServers;
  obj["time_check_url"] = cfg.timeCheckUrl;
  obj["sensor_count"] = cfg.sensorCount();
}

static void handleConfigGet_(WebServer& srv) {
  JsonDocument doc;
  addEnvelope_(doc, "bodaqs.logger.config");
  addLoggerIdentity_(doc);
  JsonObject config = doc["config"].to<JsonObject>();
  addConfigGlobalsJson_(config, ConfigManager::get());
  sendJson_(srv, 200, doc);
}

static void handleConfigPut_(WebServer& srv) {
  if (rejectConfigEditLocked_(srv)) return;

  JsonDocument req;
  if (!readJsonBody_(srv, req)) return;

  LoggerConfig tmp = ConfigManager::get();

  if (!req["logger_name"].isNull()) {
    String s = req["logger_name"] | "";
    s.trim();
    s.toCharArray(tmp.loggerName, sizeof(tmp.loggerName));
  }
  if (!req["sample_rate_hz"].isNull()) {
    long hz = req["sample_rate_hz"] | tmp.sampleRateHz;
    if (hz >= 1 && hz <= 2000) tmp.sampleRateHz = (uint16_t)hz;
  }
  if (!req["log_format"].isNull()) {
    String s = req["log_format"] | "";
    LogFormat f;
    if (ConfigManager::parseLogFormat(s.c_str(), f)) tmp.logFormat = f;
  }
  if (!req["omit_metadata"].isNull()) tmp.omitMetadata = req["omit_metadata"] | tmp.omitMetadata;
  if (!req["timestamp_mode"].isNull()) {
    String s = req["timestamp_mode"] | "";
    s.trim();
    s.toLowerCase();
    if (s == "human") tmp.timestampHuman = true;
    else if (s == "fast") tmp.timestampHuman = false;
  }
  if (!req["tz"].isNull()) {
    String s = req["tz"] | "";
    s.trim();
    s.toCharArray(tmp.tz, sizeof(tmp.tz));
  }
  if (!req["auto_sleep_idle_ms"].isNull()) tmp.autoSleepIdleMs = req["auto_sleep_idle_ms"] | tmp.autoSleepIdleMs;
  if (!req["wifi_idle_timeout_ms"].isNull()) tmp.wifiIdleTimeoutMs = req["wifi_idle_timeout_ms"] | tmp.wifiIdleTimeoutMs;
  if (!req["wifi_mode"].isNull()) {
    String s = req["wifi_mode"] | "";
    WiFiMode mode;
    if (ConfigManager::parseWifiMode(s.c_str(), mode)) tmp.wifiMode = mode;
  }
  if (!req["wifi_enabled_default"].isNull()) tmp.wifiEnabledDefault = req["wifi_enabled_default"] | tmp.wifiEnabledDefault;
  if (!req["wifi_auto_time_on_rtc_invalid"].isNull()) tmp.wifiAutoTimeOnRtcInvalid = req["wifi_auto_time_on_rtc_invalid"] | tmp.wifiAutoTimeOnRtcInvalid;
  if (!req["wifi_ap_ssid"].isNull()) {
    String s = req["wifi_ap_ssid"] | "";
    s.trim();
    s.toCharArray(tmp.wifiApSsid, sizeof(tmp.wifiApSsid));
  }
  if (!req["wifi_ap_password"].isNull()) {
    String s = req["wifi_ap_password"] | "";
    s.trim();
    s.toCharArray(tmp.wifiApPassword, sizeof(tmp.wifiApPassword));
  }
  if (!req["ntp_servers"].isNull()) {
    String s = req["ntp_servers"] | "";
    s.trim();
    s.toCharArray(tmp.ntpServers, sizeof(tmp.ntpServers));
  }
  if (!req["time_check_url"].isNull()) {
    String s = req["time_check_url"] | "";
    s.trim();
    s.toCharArray(tmp.timeCheckUrl, sizeof(tmp.timeCheckUrl));
  }

  if (!ConfigManager::save(tmp)) {
    sendError_(srv, 500, "save_failed", "Failed to save configuration.");
    return;
  }
  handleConfigGet_(srv);
}

static void handleSensorTypes_(WebServer& srv) {
  JsonDocument doc;
  addEnvelope_(doc, "bodaqs.logger.sensor_types");
  JsonArray arr = doc["sensor_types"].to<JsonArray>();

  const SensorType types[] = {
    SensorType::AnalogPot,
    SensorType::AS5600StringPotAnalog,
    SensorType::AS5600StringPotI2C,
    SensorType::AS5048BAngleI2C,
    SensorType::AS5600AngleI2C,
    SensorType::DANF10NGps,
  };
  for (const auto type : types) {
    const SensorTypeInfo* ti = SensorRegistry::lookup(type);
    if (!ti) continue;
    JsonObject item = arr.add<JsonObject>();
    item["type"] = SensorRegistry::typeKey(type);
    item["label"] = SensorRegistry::typeLabel(type);
    item["supports_calibration"] = SensorRegistry::supportedCalMask(type) != CAL_NONE;
    JsonArray params = item["params"].to<JsonArray>();
    size_t defCount = 0;
    const ParamDef* defs = ti->paramDefs(defCount);
    for (size_t i = 0; defs && i < defCount; ++i) {
      const ParamDef& pd = defs[i];
      if (!pd.key || strcasecmp(pd.key, "output_id") == 0) continue;
      JsonObject p = params.add<JsonObject>();
      p["key"] = pd.key;
      p["type"] = paramTypeName_(pd.type);
      if (pd.def) p["default"] = pd.def;
      if (pd.choices) p["choices"] = (strcasecmp(pd.key, "output_mode") == 0) ? "RAW,LINEAR" : pd.choices;
      if (pd.help) p["help"] = pd.help;
    }
  }
  sendJson_(srv, 200, doc);
}

static void handleSensorsGet_(WebServer& srv) {
  JsonDocument doc;
  addEnvelope_(doc, "bodaqs.logger.sensors");
  JsonArray arr = doc["sensors"].to<JsonArray>();
  const uint8_t n = ConfigManager::sensorCount();
  for (uint8_t i = 0; i < n; ++i) {
    SensorSpec sp;
    if (!ConfigManager::getSensorSpec(i, sp)) continue;
    JsonObject item = arr.add<JsonObject>();
    addSensorJson_(item, i, sp, false);
  }
  sendJson_(srv, 200, doc);
}

static bool readSensorIndexArg_(WebServer& srv, uint8_t& out) {
  if (!srv.hasArg("id")) {
    sendError_(srv, 400, "missing_sensor_id", "Missing required query argument: id.");
    return false;
  }
  const int id = srv.arg("id").toInt();
  if (id < 0 || id >= (int)ConfigManager::sensorCount()) {
    sendError_(srv, 404, "unknown_sensor", "Sensor index is not configured.");
    return false;
  }
  out = (uint8_t)id;
  return true;
}

static void handleSensorGet_(WebServer& srv) {
  uint8_t idx = 0;
  if (!readSensorIndexArg_(srv, idx)) return;
  SensorSpec sp;
  if (!ConfigManager::getSensorSpec(idx, sp)) {
    sendError_(srv, 404, "unknown_sensor", "Sensor index is not configured.");
    return;
  }
  JsonDocument doc;
  addEnvelope_(doc, "bodaqs.logger.sensor");
  JsonObject sensor = doc["sensor"].to<JsonObject>();
  addSensorJson_(sensor, idx, sp, true);
  sendJson_(srv, 200, doc);
}

static void seedSensorDefaults_(SensorSpec& sp) {
  sp.params.clear();
  const SensorTypeInfo* ti = SensorRegistry::lookup(sp.type);
  size_t defCount = 0;
  const ParamDef* defs = ti ? ti->paramDefs(defCount) : nullptr;
  for (size_t i = 0; defs && i < defCount; ++i) {
    const ParamDef& pd = defs[i];
    if (!pd.key || !pd.def) continue;
    if (strcasecmp(pd.key, "output_id") == 0) continue;
    if (strcasecmp(pd.key, "output_mode") == 0) sp.params.setInt(pd.key, parseLoggerOutputMode_(pd.def, 0));
    else sp.params.set(pd.key, String(pd.def));
  }
}

static void handleSensorPut_(WebServer& srv) {
  if (rejectConfigEditLocked_(srv)) return;

  uint8_t idx = 0;
  if (!readSensorIndexArg_(srv, idx)) return;

  JsonDocument req;
  if (!readJsonBody_(srv, req)) return;

  LoggerConfig tmp = ConfigManager::get();
  SensorSpec sp;
  if (!tmp.getSensorSpec(idx, sp)) {
    sendError_(srv, 404, "unknown_sensor", "Sensor index is not configured.");
    return;
  }

  bool restartRecommended = false;
  if (!req["type"].isNull()) {
    String typeText = req["type"] | "";
    SensorType newType = sp.type;
    if (!parseSensorTypeKey_(typeText, newType) || !SensorRegistry::lookup(newType)) {
      sendError_(srv, 400, "invalid_sensor_type", "Unknown sensor type.");
      return;
    }
    if (newType != sp.type) {
      sp.type = newType;
      seedSensorDefaults_(sp);
      restartRecommended = true;
    }
  }
  if (!req["name"].isNull()) {
    String name = req["name"] | "";
    name.trim();
    if (name.length()) name.toCharArray(sp.name, sizeof(sp.name));
  }
  if (!req["muted"].isNull()) sp.mutedDefault = req["muted"] | sp.mutedDefault;

  JsonObjectConst params = req["params"].as<JsonObjectConst>();
  for (JsonPairConst kv : params) {
    const char* key = kv.key().c_str();
    if (!key || !*key || strcasecmp(key, "output_id") == 0) continue;
    if (strcasecmp(key, "units_label") == 0 || strcasecmp(key, "i2c_hz") == 0) continue;
    if (strcasecmp(key, "output_mode") == 0) {
      String text;
      if (kv.value().is<const char*>()) text = kv.value().as<const char*>();
      else text = String((long)(kv.value() | 1));
      sp.params.setInt(key, parseLoggerOutputMode_(text));
    } else if (kv.value().is<bool>()) {
      sp.params.setBool(key, kv.value().as<bool>());
    } else if (kv.value().is<long>() || kv.value().is<int>()) {
      sp.params.setInt(key, kv.value().as<long>());
    } else if (kv.value().is<double>() || kv.value().is<float>()) {
      sp.params.setFloat(key, kv.value().as<double>());
    } else {
      String text = kv.value().as<String>();
      sp.params.set(key, text);
    }
  }
  sp.params.set("output_id", "identity");

  tmp.sensors[idx].type = sp.type;
  tmp.sensors[idx].mutedDefault = sp.mutedDefault;
  strncpy(tmp.sensors[idx].name, sp.name, sizeof(tmp.sensors[idx].name) - 1);
  tmp.sensors[idx].name[sizeof(tmp.sensors[idx].name) - 1] = '\0';
  tmp.sensors[idx].params = sp.params;
  ConfigManager::setSensorHeaderByIndex(idx, sp);

  if (!ConfigManager::save(tmp)) {
    sendError_(srv, 500, "save_failed", "Failed to save sensor configuration.");
    return;
  }

  JsonDocument doc;
  addEnvelope_(doc, "bodaqs.logger.sensor");
  doc["restart_recommended"] = restartRecommended;
  JsonObject sensor = doc["sensor"].to<JsonObject>();
  addSensorJson_(sensor, idx, sp, true);
  sendJson_(srv, 200, doc);
}

static void handleSensorPost_(WebServer& srv) {
  if (rejectConfigEditLocked_(srv)) return;

  JsonDocument req;
  if (!readJsonBody_(srv, req)) return;

  String typeText = req["type"] | "analog_pot";
  SensorType type = SensorType::AnalogPot;
  if (!parseSensorTypeKey_(typeText, type) || !SensorRegistry::lookup(type)) {
    sendError_(srv, 400, "invalid_sensor_type", "Unknown sensor type.");
    return;
  }

  String name = req["name"] | "";
  name.trim();
  if (!ConfigManager::appendSensor(type, name.length() ? name.c_str() : nullptr) ||
      !ConfigManager::save(ConfigManager::get())) {
    sendError_(srv, 500, "add_sensor_failed", "Failed to add sensor.");
    return;
  }

  const uint8_t idx = ConfigManager::sensorCount() - 1;
  SensorSpec sp;
  ConfigManager::getSensorSpec(idx, sp);
  JsonDocument doc;
  addEnvelope_(doc, "bodaqs.logger.sensor");
  doc["restart_recommended"] = true;
  JsonObject sensor = doc["sensor"].to<JsonObject>();
  addSensorJson_(sensor, idx, sp, true);
  sendJson_(srv, 201, doc);
}

static void handleSensorDelete_(WebServer& srv) {
  if (rejectConfigEditLocked_(srv)) return;

  uint8_t idx = 0;
  if (!readSensorIndexArg_(srv, idx)) return;
  if (!ConfigManager::deleteSensorByIndex(idx) || !ConfigManager::save(ConfigManager::get())) {
    sendError_(srv, 500, "delete_sensor_failed", "Failed to delete sensor.");
    return;
  }
  JsonDocument doc;
  addEnvelope_(doc, "bodaqs.logger.sensor_deleted");
  doc["deleted_index"] = idx;
  doc["restart_recommended"] = true;
  sendJson_(srv, 200, doc);
}

} // namespace

void registerApiRoutes(WebServer& srv) {
  WebServer* S = &srv;

  S->on("/api/v1/device", HTTP_GET, [S]() {
    noteHttpActivity_();
    handleDevice_(*S);
  });

  S->on("/api/v1/status", HTTP_GET, [S]() {
    noteHttpActivity_();
    handleStatus_(*S);
  });

  S->on("/api/v1/config", HTTP_GET, [S]() {
    noteHttpActivity_();
    handleConfigGet_(*S);
  });

  S->on("/api/v1/config", HTTP_PUT, [S]() {
    noteHttpActivity_();
    handleConfigPut_(*S);
  });

  S->on("/api/v1/sensor-types", HTTP_GET, [S]() {
    noteHttpActivity_();
    handleSensorTypes_(*S);
  });

  S->on("/api/v1/sensors", HTTP_GET, [S]() {
    noteHttpActivity_();
    handleSensorsGet_(*S);
  });

  S->on("/api/v1/sensors", HTTP_POST, [S]() {
    noteHttpActivity_();
    handleSensorPost_(*S);
  });

  S->on("/api/v1/sensor", HTTP_GET, [S]() {
    noteHttpActivity_();
    handleSensorGet_(*S);
  });

  S->on("/api/v1/sensor", HTTP_PUT, [S]() {
    noteHttpActivity_();
    handleSensorPut_(*S);
  });

  S->on("/api/v1/sensor", HTTP_DELETE, [S]() {
    noteHttpActivity_();
    handleSensorDelete_(*S);
  });

  S->on("/api/v1/upload-mode/enter", HTTP_POST, [S]() {
    noteHttpActivity_();
    if (!UploadModeManager::enter()) {
      sendError_(*S, 409, "logging_active", "Cannot enter upload mode while logging is active.");
      return;
    }
    sendUploadModeState_(*S);
  });

  S->on("/api/v1/upload-mode/exit", HTTP_POST, [S]() {
    noteHttpActivity_();
    UploadModeManager::exit();
    sendUploadModeState_(*S);
  });

  S->on("/api/v1/sessions", HTTP_GET, [S]() {
    noteHttpActivity_();
    handleSessions_(*S);
  });

  S->on("/api/v1/session/archive", HTTP_GET, [S]() {
    noteHttpActivity_();
    handleArchive_(*S);
  });
  S->on("/api/v1/session/data", HTTP_GET, [S]() {
    noteHttpActivity_();
    handleData_(*S);
  });

  S->on("/api/v1/session/ack", HTTP_POST, [S]() {
    noteHttpActivity_();
    handleAck_(*S);
  });

  S->on("/api/v1/session/delete", HTTP_POST, [S]() {
    noteHttpActivity_();
    handleDelete_(*S);
  });
}
