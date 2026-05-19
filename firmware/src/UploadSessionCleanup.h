#pragma once

#include <Arduino.h>
#include "UploadSessionScanner.h"

namespace UploadSessionCleanup {

enum class CleanupMode : uint8_t {
  MoveToUploaded = 0,
  Delete = 1,
};

struct CleanupResult {
  bool ok = false;
  bool csvOk = false;
  bool jsonOk = false;
  bool archiveOk = false;
  String mode;
  String csvPath;
  String jsonPath;
  String archivePath;
  String csvTargetPath;
  String jsonTargetPath;
  String archiveTargetPath;
  String error;
};

bool parseMode(const char* text, CleanupMode& out);
const char* modeKey(CleanupMode mode);
bool cleanupSession(const UploadSessionScanner::SessionInfo& session,
                    CleanupMode mode,
                    CleanupResult& result);

} // namespace UploadSessionCleanup

