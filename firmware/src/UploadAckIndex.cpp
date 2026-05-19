#include "UploadAckIndex.h"

#include <ArduinoJson.h>
#include "SD_MMC.h"

#ifndef FILE_APPEND
#define FILE_APPEND FILE_WRITE
#endif

namespace UploadAckIndex {
namespace {

const char* kIndexPath = "/upload_index.ndjson";
constexpr uint32_t kMaxIndexScanBytes = 1024UL * 1024UL;

static void setError_(String* error, const __FlashStringHelper* msg) {
  if (error) *error = String(msg);
}

static void setError_(String* error, const String& msg) {
  if (error) *error = msg;
}

static bool textEqualsIgnoreCase_(const String& a, const char* b) {
  if (!b) return false;
  String left = a;
  String right = String(b);
  left.toLowerCase();
  right.toLowerCase();
  return left == right;
}

static bool isAcknowledgedStatus_(const String& status) {
  return textEqualsIgnoreCase_(status, "imported") ||
         textEqualsIgnoreCase_(status, "acknowledged");
}

static bool appendLine_(const String& line, String* error) {
  File f = SD_MMC.open(kIndexPath, FILE_APPEND);
  if (!f) {
    f = SD_MMC.open(kIndexPath, FILE_WRITE);
  }
  if (!f) {
    setError_(error, String(F("open failed: ")) + kIndexPath);
    return false;
  }

  f.seek(f.size());
  const size_t expected = line.length() + 1;
  const size_t written = f.print(line) + f.print('\n');
  f.flush();
  f.close();

  if (written != expected) {
    setError_(error, F("short write"));
    return false;
  }

  return true;
}

static bool openReadableIndex_(File& f, String* error) {
  if (!SD_MMC.exists(kIndexPath)) {
    return false;
  }

  f = SD_MMC.open(kIndexPath, FILE_READ);
  if (!f) {
    setError_(error, String(F("open failed: ")) + kIndexPath);
    return false;
  }

  if (f.size() > kMaxIndexScanBytes) {
    setError_(
      error,
      String(F("ack index too large to scan: ")) + kIndexPath +
        F(" (delete or compact this file on the SD card)")
    );
    f.close();
    return false;
  }

  return true;
}

static void applyRecordFromJson_(JsonDocument& doc, AckRecord& out) {
  out.found = true;
  out.sessionId = doc["session_id"] | "";
  out.status = doc["status"] | "";
  out.libraryId = doc["library_id"] | "";
  out.runId = doc["run_id"] | "";
  out.importedAt = doc["imported_at"] | "";
}

} // namespace

const char* indexPath() {
  return kIndexPath;
}

bool markSessionAcknowledged(const AckRecord& record, String* error) {
  if (error) *error = "";

  if (SD_MMC.cardType() == CARD_NONE) {
    setError_(error, F("SD storage unavailable"));
    return false;
  }
  if (!record.sessionId.length()) {
    setError_(error, F("missing session_id"));
    return false;
  }

  AckRecord existing;
  String findError;
  if (findSessionAcknowledgement(record.sessionId.c_str(), existing, &findError)) {
    if (isAcknowledgedStatus_(existing.status)) {
      return true;
    }
  } else if (findError.length()) {
    setError_(error, findError);
    return false;
  }

  JsonDocument doc;
  doc["schema"] = "bodaqs.logger.upload_ack";
  doc["api_version"] = 1;
  doc["session_id"] = record.sessionId;
  doc["status"] = record.status.length() ? record.status : String(F("imported"));
  doc["library_id"] = record.libraryId;
  doc["run_id"] = record.runId;
  doc["imported_at"] = record.importedAt;

  String line;
  serializeJson(doc, line);
  return appendLine_(line, error);
}

bool findSessionAcknowledgement(const char* sessionId, AckRecord& out, String* error) {
  out = AckRecord{};
  if (error) *error = "";

  if (!sessionId || !*sessionId) {
    setError_(error, F("missing session_id"));
    return false;
  }
  if (SD_MMC.cardType() == CARD_NONE) {
    setError_(error, F("SD storage unavailable"));
    return false;
  }

  File f;
  if (!openReadableIndex_(f, error)) {
    return false;
  }

  while (f.available()) {
    String line = f.readStringUntil('\n');
    line.trim();
    if (!line.length()) {
      delay(0);
      continue;
    }

    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, line);
    if (!err) {
      const char* sid = doc["session_id"] | "";
      if (strcmp(sid, sessionId) == 0) {
        applyRecordFromJson_(doc, out);
      }
    }

    delay(0);
  }

  f.close();
  return out.found;
}

bool applyAcknowledgementStatuses(AckStatusLookup* lookups, uint16_t count, String* error) {
  if (error) *error = "";
  if (!lookups || count == 0) return true;

  for (uint16_t i = 0; i < count; ++i) {
    lookups[i].acknowledged = false;
  }

  if (SD_MMC.cardType() == CARD_NONE) {
    setError_(error, F("SD storage unavailable"));
    return false;
  }

  File f;
  if (!openReadableIndex_(f, error)) {
    return !(error && error->length());
  }

  while (f.available()) {
    String line = f.readStringUntil('\n');
    line.trim();
    if (!line.length()) {
      delay(0);
      continue;
    }

    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, line);
    if (!err) {
      const char* sid = doc["session_id"] | "";
      const String status = doc["status"] | "";
      for (uint16_t i = 0; i < count; ++i) {
        if (lookups[i].sessionId && strcmp(sid, lookups[i].sessionId) == 0) {
          lookups[i].acknowledged = isAcknowledgedStatus_(status);
          break;
        }
      }
    }

    delay(0);
  }

  f.close();
  return true;
}

bool isSessionAcknowledged(const char* sessionId) {
  AckRecord record;
  String error;
  if (!findSessionAcknowledgement(sessionId, record, &error)) return false;
  return isAcknowledgedStatus_(record.status);
}

} // namespace UploadAckIndex

