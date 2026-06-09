#pragma once

#include <Arduino.h>

namespace UploadSessionScanner {

struct SessionInfo {
  String sessionId;
  String sessionStem;
  String csvPath;
  String jsonPath;
  String archivePath;
  String dataFormat;
  String dataPath;
  bool archiveReady = false;
  bool dataReady = false;
  bool uploaded = false;
  bool acknowledged = false;
  uint32_t archiveSize = 0;
  uint32_t dataSize = 0;
};

struct ScanSummary {
  bool storageAvailable = false;
  bool directoryOpened = false;
  bool truncatedCandidates = false;
  bool truncatedOutput = false;
  uint16_t filesSeen = 0;
  uint16_t candidateCount = 0;
  uint16_t completeCount = 0;
  uint16_t incompleteCount = 0;
  uint16_t tempArchiveCount = 0;
};

uint16_t scan(const char* directory,
              SessionInfo* out,
              uint16_t outCapacity,
              ScanSummary* summary = nullptr);

bool findBySessionId(const char* sessionId,
                     SessionInfo& out,
                     const char* directory = "/");

} // namespace UploadSessionScanner

