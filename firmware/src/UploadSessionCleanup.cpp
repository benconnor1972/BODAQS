#include "UploadSessionCleanup.h"

#include "SD_MMC.h"

namespace UploadSessionCleanup {
namespace {

const char* kUploadedDir = "/uploaded";

static String baseName_(const String& path) {
  const int slash = path.lastIndexOf('/');
  if (slash >= 0 && slash + 1 < (int)path.length()) {
    return path.substring(slash + 1);
  }
  return path;
}

static void setCommonResult_(const UploadSessionScanner::SessionInfo& session,
                             CleanupMode mode,
                             CleanupResult& result) {
  result = CleanupResult{};
  result.mode = modeKey(mode);
  result.csvPath = session.csvPath;
  result.jsonPath = session.jsonPath;
  result.archivePath = session.archivePath;

  if (mode == CleanupMode::MoveToUploaded) {
    if (session.csvPath.length()) {
      result.csvTargetPath = String(kUploadedDir) + "/" + baseName_(session.csvPath);
    }
    if (session.jsonPath.length()) {
      result.jsonTargetPath = String(kUploadedDir) + "/" + baseName_(session.jsonPath);
    }
    result.archiveTargetPath = String(kUploadedDir) + "/" + baseName_(session.archivePath);
  }
}

static bool fileExists_(const String& path) {
  if (!path.length()) return false;
  File f = SD_MMC.open(path.c_str(), FILE_READ);
  if (!f) return false;
  const bool ok = !f.isDirectory();
  f.close();
  return ok;
}

static bool preflightSources_(const UploadSessionScanner::SessionInfo& session,
                              CleanupResult& result) {
  if (!fileExists_(session.archivePath)) {
    result.error = String(F("missing archive: ")) + session.archivePath;
    return false;
  }
  return true;
}

static bool preflightMoveTargets_(CleanupResult& result) {
  if (!SD_MMC.exists(kUploadedDir)) {
    if (!SD_MMC.mkdir(kUploadedDir)) {
      result.error = String(F("could not create uploaded directory: ")) + kUploadedDir;
      return false;
    }
  }

  File dir = SD_MMC.open(kUploadedDir);
  if (!dir || !dir.isDirectory()) {
    if (dir) dir.close();
    result.error = String(F("uploaded path is not a directory: ")) + kUploadedDir;
    return false;
  }
  dir.close();

  if (result.csvTargetPath.length() && SD_MMC.exists(result.csvTargetPath.c_str())) {
    result.error = String(F("target exists: ")) + result.csvTargetPath;
    return false;
  }
  if (result.jsonTargetPath.length() && SD_MMC.exists(result.jsonTargetPath.c_str())) {
    result.error = String(F("target exists: ")) + result.jsonTargetPath;
    return false;
  }
  if (SD_MMC.exists(result.archiveTargetPath.c_str())) {
    result.error = String(F("target exists: ")) + result.archiveTargetPath;
    return false;
  }

  return true;
}

static bool moveOne_(const String& from, const String& to, bool& flag, CleanupResult& result) {
  flag = SD_MMC.rename(from.c_str(), to.c_str());
  if (!flag && !result.error.length()) {
    result.error = String(F("move failed: ")) + from + F(" -> ") + to;
  }
  return flag;
}

static bool moveOptional_(const String& from, const String& to, bool& flag, CleanupResult& result) {
  if (!fileExists_(from)) {
    flag = true;
    return true;
  }
  return moveOne_(from, to, flag, result);
}

static bool deleteOne_(const String& path, bool& flag, CleanupResult& result) {
  flag = SD_MMC.remove(path.c_str());
  if (!flag && !result.error.length()) {
    result.error = String(F("delete failed: ")) + path;
  }
  return flag;
}

static bool deleteOptional_(const String& path, bool& flag, CleanupResult& result) {
  if (!fileExists_(path)) {
    flag = true;
    return true;
  }
  return deleteOne_(path, flag, result);
}

} // namespace

bool parseMode(const char* text, CleanupMode& out) {
  if (!text || !*text) return false;
  String s(text);
  s.trim();
  s.toLowerCase();

  if (s == "move_to_uploaded" || s == "archive" || s == "move") {
    out = CleanupMode::MoveToUploaded;
    return true;
  }
  if (s == "delete") {
    out = CleanupMode::Delete;
    return true;
  }
  return false;
}

const char* modeKey(CleanupMode mode) {
  switch (mode) {
    case CleanupMode::Delete: return "delete";
    case CleanupMode::MoveToUploaded:
    default: return "move_to_uploaded";
  }
}

bool cleanupSession(const UploadSessionScanner::SessionInfo& session,
                    CleanupMode mode,
                    CleanupResult& result) {
  setCommonResult_(session, mode, result);

  if (SD_MMC.cardType() == CARD_NONE) {
    result.error = F("SD storage unavailable");
    return false;
  }
  if (!preflightSources_(session, result)) {
    return false;
  }
  if (mode == CleanupMode::MoveToUploaded && !preflightMoveTargets_(result)) {
    return false;
  }

  if (mode == CleanupMode::MoveToUploaded) {
    moveOptional_(session.csvPath, result.csvTargetPath, result.csvOk, result);
    moveOptional_(session.jsonPath, result.jsonTargetPath, result.jsonOk, result);
    moveOne_(session.archivePath, result.archiveTargetPath, result.archiveOk, result);
  } else {
    deleteOptional_(session.csvPath, result.csvOk, result);
    deleteOptional_(session.jsonPath, result.jsonOk, result);
    deleteOne_(session.archivePath, result.archiveOk, result);
  }

  result.ok = result.csvOk && result.jsonOk && result.archiveOk;
  return result.ok;
}

} // namespace UploadSessionCleanup

