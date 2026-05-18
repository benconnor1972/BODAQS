#pragma once

#include <Arduino.h>

namespace UploadAckIndex {

struct AckRecord {
  String sessionId;
  String status;
  String libraryId;
  String runId;
  String importedAt;
  bool found = false;
};

struct AckStatusLookup {
  const char* sessionId = nullptr;
  bool acknowledged = false;
};

const char* indexPath();

bool markSessionAcknowledged(const AckRecord& record, String* error = nullptr);
bool findSessionAcknowledgement(const char* sessionId, AckRecord& out, String* error = nullptr);
bool applyAcknowledgementStatuses(AckStatusLookup* lookups, uint16_t count, String* error = nullptr);
bool isSessionAcknowledged(const char* sessionId);

} // namespace UploadAckIndex

