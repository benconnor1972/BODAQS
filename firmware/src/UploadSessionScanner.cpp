#include "UploadSessionScanner.h"

#include <ctype.h>
#include "ConfigManager.h"
#include "SD_MMC.h"
#include "UploadAckIndex.h"

namespace UploadSessionScanner {
namespace {

constexpr uint16_t kMaxCandidates = 64;

enum class FileKind : uint8_t {
  Unknown = 0,
  Csv,
  Json,
  Zip,
  ZipTemp,
};

struct Candidate {
  String stem;
  String csvPath;
  String jsonPath;
  String archivePath;
  bool hasCsv = false;
  bool hasJson = false;
  bool hasZip = false;
  bool hasZipTemp = false;
  uint32_t archiveSize = 0;

  void clear() {
    stem = "";
    csvPath = "";
    jsonPath = "";
    archivePath = "";
    hasCsv = false;
    hasJson = false;
    hasZip = false;
    hasZipTemp = false;
    archiveSize = 0;
  }
};

static Candidate s_candidates[kMaxCandidates];

static String normalizeDir_(const char* directory) {
  String out = (directory && *directory) ? String(directory) : String("/");
  out.replace("\\", "/");
  if (!out.startsWith("/")) out = "/" + out;
  if (out.length() > 1 && !out.endsWith("/")) out += "/";
  return out;
}

static String dirOpenPath_(const String& dir) {
  if (dir.length() > 1 && dir.endsWith("/")) {
    return dir.substring(0, dir.length() - 1);
  }
  return dir;
}

static String baseName_(const String& path) {
  const int slash = path.lastIndexOf('/');
  if (slash >= 0 && slash + 1 < (int)path.length()) {
    return path.substring(slash + 1);
  }
  return path;
}

static bool endsWithIgnoreCase_(const String& text, const char* suffix) {
  if (!suffix) return false;
  const int textLen = text.length();
  const int suffixLen = strlen(suffix);
  if (suffixLen <= 0 || textLen < suffixLen) return false;

  const int offset = textLen - suffixLen;
  for (int i = 0; i < suffixLen; ++i) {
    const char a = (char)tolower((unsigned char)text[offset + i]);
    const char b = (char)tolower((unsigned char)suffix[i]);
    if (a != b) return false;
  }
  return true;
}

static bool splitSessionFileName_(const String& fileName, String& stem, FileKind& kind) {
  stem = "";
  kind = FileKind::Unknown;

  if (fileName.length() == 0) return false;

  if (endsWithIgnoreCase_(fileName, ".zip.tmp")) {
    stem = fileName.substring(0, fileName.length() - 8);
    kind = FileKind::ZipTemp;
    return stem.length() > 0;
  }
  if (endsWithIgnoreCase_(fileName, ".csv")) {
    stem = fileName.substring(0, fileName.length() - 4);
    kind = FileKind::Csv;
    return stem.length() > 0;
  }
  if (endsWithIgnoreCase_(fileName, ".json")) {
    stem = fileName.substring(0, fileName.length() - 5);
    kind = FileKind::Json;
    return stem.length() > 0;
  }
  if (endsWithIgnoreCase_(fileName, ".zip")) {
    stem = fileName.substring(0, fileName.length() - 4);
    kind = FileKind::Zip;
    return stem.length() > 0;
  }

  return false;
}

static Candidate* findOrAddCandidate_(const String& stem,
                                      uint16_t& count,
                                      ScanSummary* summary) {
  for (uint16_t i = 0; i < count; ++i) {
    if (s_candidates[i].stem == stem) return &s_candidates[i];
  }

  if (count >= kMaxCandidates) {
    if (summary) summary->truncatedCandidates = true;
    return nullptr;
  }

  Candidate& candidate = s_candidates[count++];
  candidate.clear();
  candidate.stem = stem;
  return &candidate;
}

static bool isComplete_(const Candidate& candidate) {
  return candidate.hasZip;
}

static void sortCandidatesNewestFirst_(uint16_t count) {
  for (uint16_t i = 0; i < count; ++i) {
    uint16_t best = i;
    for (uint16_t j = i + 1; j < count; ++j) {
      if (s_candidates[j].stem > s_candidates[best].stem) best = j;
    }
    if (best != i) {
      Candidate tmp = s_candidates[i];
      s_candidates[i] = s_candidates[best];
      s_candidates[best] = tmp;
    }
  }
}

static void clearOutput_(SessionInfo* out, uint16_t outCapacity) {
  if (!out) return;
  for (uint16_t i = 0; i < outCapacity; ++i) {
    out[i] = SessionInfo{};
  }
}

static void fillSessionInfo_(const Candidate& candidate, SessionInfo& out) {
  const String loggerId = ConfigManager::loggerId();
  out.sessionStem = candidate.stem;
  out.sessionId = loggerId + F("__") + candidate.stem;
  out.csvPath = candidate.csvPath;
  out.jsonPath = candidate.jsonPath;
  out.archivePath = candidate.archivePath;
  out.archiveReady = true;
  out.acknowledged = false;
  out.uploaded = false;
  out.archiveSize = candidate.archiveSize;
}

static void applyAcknowledgements_(SessionInfo* out, uint16_t count) {
  if (!out || count == 0) return;

  UploadAckIndex::AckStatusLookup lookups[kMaxCandidates];
  const uint16_t lookupCount = count > kMaxCandidates ? kMaxCandidates : count;
  for (uint16_t i = 0; i < lookupCount; ++i) {
    lookups[i].sessionId = out[i].sessionId.c_str();
    lookups[i].acknowledged = false;
  }

  String error;
  if (!UploadAckIndex::applyAcknowledgementStatuses(lookups, lookupCount, &error)) {
    return;
  }

  for (uint16_t i = 0; i < lookupCount; ++i) {
    out[i].acknowledged = lookups[i].acknowledged;
    out[i].uploaded = lookups[i].acknowledged;
  }
}

} // namespace

uint16_t scan(const char* directory,
              SessionInfo* out,
              uint16_t outCapacity,
              ScanSummary* summary) {
  if (summary) *summary = ScanSummary{};
  clearOutput_(out, outCapacity);

  for (uint16_t i = 0; i < kMaxCandidates; ++i) {
    s_candidates[i].clear();
  }

  if (summary) summary->storageAvailable = (SD_MMC.cardType() != CARD_NONE);
  if (SD_MMC.cardType() == CARD_NONE) return 0;

  const String dir = normalizeDir_(directory);
  const String openDir = dirOpenPath_(dir);
  File d = SD_MMC.open(openDir.c_str());
  if (!d || !d.isDirectory()) {
    if (d) d.close();
    return 0;
  }
  if (summary) summary->directoryOpened = true;

  uint16_t candidateCount = 0;
  File entry = d.openNextFile();
  while (entry) {
    if (!entry.isDirectory()) {
      if (summary) summary->filesSeen++;

      const String fileName = baseName_(String(entry.name()));
      String stem;
      FileKind kind = FileKind::Unknown;
      if (splitSessionFileName_(fileName, stem, kind)) {
        Candidate* candidate = findOrAddCandidate_(stem, candidateCount, summary);
        if (candidate) {
          const String fullPath = dir + fileName;
          switch (kind) {
            case FileKind::Csv:
              candidate->hasCsv = true;
              candidate->csvPath = fullPath;
              break;
            case FileKind::Json:
              candidate->hasJson = true;
              candidate->jsonPath = fullPath;
              break;
            case FileKind::Zip:
              candidate->hasZip = true;
              candidate->archivePath = fullPath;
              candidate->archiveSize = static_cast<uint32_t>(entry.size());
              break;
            case FileKind::ZipTemp:
              candidate->hasZipTemp = true;
              if (summary) summary->tempArchiveCount++;
              break;
            case FileKind::Unknown:
              break;
          }
        }
      }
    }

    entry.close();
    delay(0);
    entry = d.openNextFile();
  }
  d.close();

  sortCandidatesNewestFirst_(candidateCount);

  uint16_t written = 0;
  uint16_t complete = 0;
  uint16_t incomplete = 0;

  for (uint16_t i = 0; i < candidateCount; ++i) {
    const Candidate& candidate = s_candidates[i];
    if (isComplete_(candidate)) {
      complete++;
      if (out && written < outCapacity) {
        fillSessionInfo_(candidate, out[written]);
        written++;
      } else if (out && summary) {
        summary->truncatedOutput = true;
      }
    } else {
      incomplete++;
    }
  }

  if (summary) {
    summary->candidateCount = candidateCount;
    summary->completeCount = complete;
    summary->incompleteCount = incomplete;
  }

  applyAcknowledgements_(out, written);

  return written;
}

bool findBySessionId(const char* sessionId,
                     SessionInfo& out,
                     const char* directory) {
  out = SessionInfo{};
  if (!sessionId || !*sessionId) return false;

  SessionInfo sessions[24];
  ScanSummary summary;
  const uint16_t n = scan(directory, sessions, 24, &summary);
  for (uint16_t i = 0; i < n; ++i) {
    if (sessions[i].sessionId == sessionId) {
      out = sessions[i];
      return true;
    }
  }
  return false;
}

} // namespace UploadSessionScanner
