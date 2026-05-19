#include "Routes_Api.h"

#include <Arduino.h>
#include <ArduinoJson.h>
#include <WiFi.h>
#include "SD_MMC.h"

#include "ConfigManager.h"
#include "FirmwareInfo.h"
#include "LoggingManager.h"
#include "PowerManager.h"
#include "UploadAckIndex.h"
#include "UploadModeManager.h"
#include "UploadSessionCleanup.h"
#include "UploadSessionScanner.h"
#include "WiFiManager.h"

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
    item["archive_ready"] = sessions[i].archiveReady;
    item["archive_size"] = sessions[i].archiveSize;
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

  File f = SD_MMC.open(session.archivePath.c_str(), FILE_READ);
  if (!f || f.isDirectory()) {
    if (f) f.close();
    sendError_(srv, 404, "archive_not_found", "The session archive is not available.");
    return;
  }

  const String filename = session.sessionId + F(".zip");
  srv.sendHeader(F("Cache-Control"), F("no-store"));
  srv.sendHeader(F("Content-Disposition"), String(F("attachment; filename=\"")) + filename + F("\""));
  srv.setContentLength(CONTENT_LENGTH_UNKNOWN);
  srv.send(200, F("application/zip"), "");

  static uint8_t buf[2048];
  int n = 0;
  while ((n = f.read(buf, sizeof(buf))) > 0) {
    srv.sendContent_P(reinterpret_cast<const char*>(buf), n);
    delay(0);
  }
  f.close();
  srv.sendContent("");
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

  S->on("/api/v1/session/ack", HTTP_POST, [S]() {
    noteHttpActivity_();
    handleAck_(*S);
  });

  S->on("/api/v1/session/delete", HTTP_POST, [S]() {
    noteHttpActivity_();
    handleDelete_(*S);
  });
}
