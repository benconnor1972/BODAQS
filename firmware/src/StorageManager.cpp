#include "StorageManager.h"
#include "RTCManager.h"
#include "ConfigManager.h"
#include "SensorManager.h"
#include "LogMetadataWriter.h"
#include "ZipArchiveWriter.h"

#include "BoardProfile.h"   // <-- whatever you called it after the namespace rename
#include "BoardSelect.h"
#include "DebugTrace.h"
#include "DebugLog.h"
#include <math.h>
#include <time.h>

#define STOR_LOGE(...) LOGE_TAG("Storage", __VA_ARGS__)
#define STOR_LOGW(...) LOGW_TAG("Storage", __VA_ARGS__)
#define STOR_LOGI(...) LOGI_TAG("Storage", __VA_ARGS__)
#define STOR_LOGD(...) LOGD_TAG("Storage", __VA_ARGS__)
#define SD_LOGD(...)   LOGD_TAG("SD", __VA_ARGS__)
#define ROW_LOGD(...)  LOGD_TAG("ROW", __VA_ARGS__)
#define DRAIN_LOGD(...) LOGD_TAG("DRAIN", __VA_ARGS__)

extern LoggerConfig g_cfg;   // declared in your .ino

static const board::StorageProfile* s_storage = nullptr;
static const board::LoggerPerfProfile* s_perf = nullptr;

static inline bool isSdmmcBackend() {
  return s_storage && (s_storage->type == board::StorageType::SDMMC);
}

static File logFileMMC;

static char* buffer = nullptr;
static size_t bufferSize = 0;
static size_t bufferIndex = 0;

static unsigned int sampleRateHz = 1;
static unsigned long sampleIntervalMs = 1000;

static bool loggingActive = false;

static char s_customHeader[160] = {0};
static String s_currentLogPath;
static String s_currentSessionId;
static String s_logStartedAtUtc;
static String s_logStartedAtLocal;
static uint32_t s_rowsWritten = 0;
static LogFormat s_activeLogFormat = LogFormat::BodaqsStandard;
static SensorManager::SynBikeRawBindings s_synBikeRawBindings;

static uint32_t s_flushCount    = 0;
static uint32_t s_flushMaxMs    = 0;
static uint64_t s_flushTotalMs  = 0;


// --- Sample row queue for non-blocking sampling ---
// Must match LoggingManager's float values[32] size.
constexpr uint16_t SM_MAX_DYNAMIC_COLS   = 32;
static bool s_valueColumnIsRaw[SM_MAX_DYNAMIC_COLS] = {false};

struct SampleRow {
  uint32_t sample_id = 0;
  uint64_t ts_ms = 0;
  uint16_t nValues = 0;
  bool     mark = false;
  volatile uint8_t ready = 0;          // NEW
  float    values[SM_MAX_DYNAMIC_COLS];
};


#if defined(ESP32)
static portMUX_TYPE s_qMux = portMUX_INITIALIZER_UNLOCKED;
#endif

static uint16_t  s_qHead  = 0;
static uint16_t  s_qTail  = 0;
static uint16_t  s_qCount = 0;
static uint16_t  s_qMax   = 0;
static uint32_t  s_samplesDropped = 0;

static SampleRow* s_rows = nullptr;
static uint16_t   s_qCap = 0;

static inline bool queueEmpty() { return s_qCount == 0; }
static inline bool queueFull()  { return (s_qCap != 0) && (s_qCount >= s_qCap); }
static void refreshValueColumnTypes_();

static bool isSynBikeRawFormat_() {
  return s_activeLogFormat == LogFormat::SynBikeRaw;
}

static String isoLocalFromFilenameTimestamp_(const String& s) {
  if (s.length() < 19) return String();
  String out = s.substring(0, 19);
  out.replace("_", "T");
  out.setCharAt(13, ':');
  out.setCharAt(16, ':');
  return out;
}

static String isoUtcFromEpoch_(time_t epoch) {
  if (epoch < 1577836800) return String();

  struct tm utcInfo;
  gmtime_r(&epoch, &utcInfo);
  if ((utcInfo.tm_year + 1900) < 2020) return String();

  char buf[32];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &utcInfo);
  return String(buf);
}

static String stemFromPath_(const String& path) {
  const int slash = path.lastIndexOf('/');
  const int dot = path.lastIndexOf('.');
  const int start = slash >= 0 ? slash + 1 : 0;
  const int end = (dot > start) ? dot : path.length();
  return path.substring(start, end);
}

static String baseNameFromPath_(const String& path) {
  const int slash = path.lastIndexOf('/');
  if (slash >= 0 && slash + 1 < (int)path.length()) {
    return path.substring(slash + 1);
  }
  return path;
}

static String archivePathForCsv_(const String& csvPath) {
  const int slash = csvPath.lastIndexOf('/');
  const int dot = csvPath.lastIndexOf('.');
  String out = csvPath;
  if (dot > slash) {
    out = csvPath.substring(0, dot);
  }
  out += F(".zip");
  return out;
}

static void removeArchivedSourceFile_(const String& path, const __FlashStringHelper* label) {
  if (!path.length()) return;
  if (!SD_MMC.exists(path.c_str())) return;

  const String labelText(label);
  if (SD_MMC.remove(path.c_str())) {
    STOR_LOGI("%s removed after archive: %s\n", labelText.c_str(), path.c_str());
  } else {
    STOR_LOGW("%s left in place after archive: %s\n", labelText.c_str(), path.c_str());
  }
}

static void createSessionArchive_(const String& csvPath, const String& metadataPath) {
  if (!csvPath.length() || !metadataPath.length()) {
    STOR_LOGW("Session archive skipped: missing CSV or metadata path\n");
    return;
  }

  const String archivePath = archivePathForCsv_(csvPath);
  const String tempPath = archivePath + F(".tmp");

  if (SD_MMC.exists(archivePath.c_str())) {
    STOR_LOGW("Session archive skipped: final archive already exists: %s\n", archivePath.c_str());
    return;
  }
  if (SD_MMC.exists(tempPath.c_str()) && !SD_MMC.remove(tempPath.c_str())) {
    STOR_LOGW("Session archive skipped: could not remove stale temp archive: %s\n", tempPath.c_str());
    return;
  }

  const String csvName = baseNameFromPath_(csvPath);
  const String metadataName = baseNameFromPath_(metadataPath);
  const ZipArchiveEntry entries[] = {
    { csvPath.c_str(), csvName.c_str() },
    { metadataPath.c_str(), metadataName.c_str() },
  };

  String error;
  if (!ZipArchiveWriter_createStoreOnly(tempPath.c_str(), entries, 2, &error)) {
    STOR_LOGW("Session archive failed: %s (%s)\n", tempPath.c_str(), error.c_str());
    if (SD_MMC.exists(tempPath.c_str())) {
      SD_MMC.remove(tempPath.c_str());
    }
    return;
  }

  if (!SD_MMC.rename(tempPath.c_str(), archivePath.c_str())) {
    STOR_LOGW("Session archive rename failed: %s -> %s\n", tempPath.c_str(), archivePath.c_str());
    if (SD_MMC.exists(tempPath.c_str())) {
      SD_MMC.remove(tempPath.c_str());
    }
    return;
  }

  STOR_LOGI("Session archive written: %s\n", archivePath.c_str());
  removeArchivedSourceFile_(csvPath, F("CSV source"));
  removeArchivedSourceFile_(metadataPath, F("metadata source"));
}

static void allocQueue(uint16_t depth) {
  if (depth < 4) depth = 4;
  // cap it to something sane for uint16 math
  if (depth > 4096) depth = 4096;

  delete[] s_rows;
  s_rows = new SampleRow[depth];

  if (!s_rows) {
    STOR_LOGE("allocQueue failed (OOM)\n");
    s_qCap = 0;
    s_qHead = s_qTail = s_qCount = 0;
    s_qMax = 0;
    return;
  }

  s_qCap = s_rows ? depth : 0;

  s_qHead = s_qTail = s_qCount = 0;
  s_qMax = 0;
}


bool StorageManager_enqueueSample(uint32_t sample_id, uint64_t ts_ms,
                                  const float* values, uint16_t nValues, bool mark) {
  if (!loggingActive) return false;
  if (!values || nValues == 0) return false;
  if (nValues > SM_MAX_DYNAMIC_COLS) nValues = SM_MAX_DYNAMIC_COLS;

  uint16_t idx;

#if defined(ESP32)
  portENTER_CRITICAL(&s_qMux);
#endif

  if (s_qCap == 0 || s_rows == nullptr || s_qCount >= s_qCap) {
    ++s_samplesDropped;
#if defined(ESP32)
    portEXIT_CRITICAL(&s_qMux);
#endif
    return false;
  }

  idx = s_qHead;
  s_qHead = (uint16_t)((s_qHead + 1) % s_qCap);

  // Mark not-ready while we fill it
  s_rows[idx].ready = 0;

#if defined(ESP32)
  portEXIT_CRITICAL(&s_qMux);
#endif

  // Fill payload (outside lock)
  SampleRow &row = s_rows[idx];
  row.sample_id = sample_id;
  row.ts_ms     = ts_ms;
  row.nValues   = nValues;
  row.mark      = mark;
  memcpy(row.values, values, nValues * sizeof(float));
  // Optional hygiene:
  // for (uint16_t i=nValues; i<SM_MAX_DYNAMIC_COLS; ++i) row.values[i]=0;

  // Publish: set ready + increment count
#if defined(ESP32)
  portENTER_CRITICAL(&s_qMux);
#endif

  row.ready = 1;
  ++s_qCount;
  if (s_qCount > s_qMax) s_qMax = s_qCount;

#if defined(ESP32)
  portEXIT_CRITICAL(&s_qMux);
#endif

  return true;
}


//Debug
volatile bool g_sdWriteSinceLastSample = false;  // true if any SD flush since last logged row
bool g_sdTrackEnabled = true;                    // can be toggled off if desired

static bool logIsOpen() {
    return (bool)logFileMMC;
}

static void logCloseInternal() {
    logFileMMC.close();
}

static size_t logWriteInternal(const void* data, size_t len) {
    uint32_t t0 = millis();
    size_t written = logFileMMC.write((const uint8_t*)data, len);
    uint32_t dt = millis() - t0;
    if (dt > 200) {
      SD_LOGD("logWriteInternal len=%u dt=%lu ms bufIndex=%u loggingActive=%d\n",
              (unsigned)len, (unsigned long)dt, (unsigned)bufferIndex, (int)loggingActive);
    }
    return written;
}

static void logPrintlnInternal(const char* s) {
    logFileMMC.println(s);
}

static void logFlushInternal() {
    logFileMMC.flush();
}

static bool dequeueSample(SampleRow &out) {
#if defined(ESP32)
  portENTER_CRITICAL(&s_qMux);
#endif

  if (s_qCap == 0 || s_rows == nullptr || s_qCount == 0) {
#if defined(ESP32)
    portEXIT_CRITICAL(&s_qMux);
#endif
    return false;
  }

  const uint16_t idx = s_qTail;

  // If producer reserved but hasn't finished filling, don't pop it yet
  if (s_rows[idx].ready == 0) {
#if defined(ESP32)
    portEXIT_CRITICAL(&s_qMux);
#endif
    return false;  // try again next loop iteration
  }

  s_qTail = (uint16_t)((s_qTail + 1) % s_qCap);
  --s_qCount;

#if defined(ESP32)
  portEXIT_CRITICAL(&s_qMux);
#endif

  out = s_rows[idx];
  // Optional: clear ready so stale reads are obvious in debug
  s_rows[idx].ready = 0;
  return true;
}



bool StorageManager_loadTextFile(const char* path, String& out) {
    out = "";
    if (!path || !*path) return false;

    String absPath = (path[0] == '/') ? String(path) : (String("/") + path);
    File f = SD_MMC.open(absPath.c_str(), FILE_READ);
    if (!f) {
        STOR_LOGW("loadTextFile: SD_MMC open failed for %s\n", path);
        return false;
    }

    while (f.available()) {
        int c = f.read();
        if (c < 0) break;
        out += (char)c;
    }
    f.close();
    STOR_LOGD("loadTextFile: SD_MMC read OK, bytes=%u\n", (unsigned)out.length());
    return true;
}

bool StorageManager_saveTextFile(const char* path, const String& data) {
  if (!path || !*path) return false;

  const char* cstr = data.c_str();
  const size_t len = data.length();

  // Normalize to absolute path (SD_MMC expects paths like "/config.txt")
  String absPath = (path[0] == '/') ? String(path) : (String("/") + path);

  // StorageManager_begin() already did SD_MMC.begin() on this backend.
  // But we still guard against "no card".
  if (SD_MMC.cardType() == CARD_NONE) {
    STOR_LOGW("saveTextFile: SD_MMC not mounted / no card\n");
    return false;
  }

  // Best-effort remove to simulate truncate (FILE_WRITE appends on ESP32)
  // Only attempt remove if it exists, to avoid edge-case FS bugs.
  if (SD_MMC.exists(absPath.c_str())) {
    SD_MMC.remove(absPath.c_str());
  }

  File f = SD_MMC.open(absPath.c_str(), FILE_WRITE);
  if (!f) {
    STOR_LOGW("saveTextFile: SD_MMC open failed for %s\n", absPath.c_str());
    return false;
  }

  size_t written = f.write((const uint8_t*)cstr, len);
  f.flush();
  f.close();

  if (written != len) {
    STOR_LOGW("saveTextFile: SD_MMC short write (%u/%u)\n",
              (unsigned)written, (unsigned)len);
    return false;
  }

  return true;
}


void StorageManager_begin(const board::BoardProfile& bp) {
  s_storage = &bp.storage;
  s_perf    = &bp.perf;

  // 1) Apply perf knobs early
  if (s_perf) {
    allocQueue(s_perf->queue_depth);
    StorageManager_setBufferSize(s_perf->ring_buffer_bytes);
  }

  if (isSdmmcBackend()) {
    STOR_LOGI("begin(): backend = SDMMC (SD_MMC)\n");
    STOR_LOGI("begin (SDMMC): starting SD_MMC\n");

    // Pins must come from the board profile now
    const int clk = s_storage->sdmmc_clk;
    const int cmd = s_storage->sdmmc_cmd;
    const int d0  = s_storage->sdmmc_d0;

    if (clk < 0 || cmd < 0 || d0 < 0) {
      STOR_LOGE("SDMMC backend selected but sdmmc_clk/cmd/d0 not set\n");
      return;
    }

    if (s_storage->sdmmc_1bit) {
      SD_MMC.setPins(clk, cmd, d0);   // CLK, CMD, D0 (1-bit)
    } else {
      // 4-bit requires d1..d3
      const int d1 = s_storage->sdmmc_d1;
      const int d2 = s_storage->sdmmc_d2;
      const int d3 = s_storage->sdmmc_d3;
      if (d1 < 0 || d2 < 0 || d3 < 0) {
        STOR_LOGE("SDMMC 4-bit selected but d1/d2/d3 not set\n");
        return;
      }
      SD_MMC.setPins(clk, cmd, d0, d1, d2, d3);
    }

    const bool ok = SD_MMC.begin("/sdcard", s_storage->sdmmc_1bit);
    STOR_LOGI("SD_MMC.begin result: %s\n", ok ? "OK (true)" : "FAILED (false)");

    if (!ok) {
      STOR_LOGE("SD_MMC.begin FAILED, returning\n");
      return;
    }

    uint8_t cardType = SD_MMC.cardType();
    if (cardType == CARD_NONE) {
      STOR_LOGW("No SD card attached (cardType=CARD_NONE)\n");
      SD_MMC.end();
      return;
    }

    STOR_LOGI("SD_MMC cardType = %u\n", (unsigned)cardType);

    uint64_t sizeMB = SD_MMC.cardSize() / (1024ULL * 1024ULL);
    STOR_LOGI("SD card size: %llu MB\n", (unsigned long long)sizeMB);

    STOR_LOGI("SD_MMC.begin OK.\n");
    return;
  }


  STOR_LOGW("begin(): storage backend = None\n");
}


// Set sample rate
void StorageManager_setSampleRate(unsigned int hz) {
    if (hz == 0) hz = 1;
    sampleRateHz = hz;
    sampleIntervalMs = 1000UL / sampleRateHz;
}

unsigned long StorageManager_getSampleIntervalMs() {
    return sampleIntervalMs;
}

// Set buffer size
void StorageManager_setBufferSize(size_t bytes) {
    if (buffer) delete[] buffer;
    buffer = new char[bytes];
    bufferSize = bytes;
    bufferIndex = 0;
}

// Utility: truncate to 8.3 filename
static String make83Name(const String &dtString) {
    // Example: "2025-08-17_12-34-56" → "L20250817.CSV"
    String name = "L";

    // keep only digits
    for (char c : dtString) {
        if (isdigit(c)) name += c;
        if (name.length() >= 8) break;  // enforce 8 chars max
    }

    name += ".CSV";  // extension
    return name;
}

static bool openNewLogFile_SDMMC(const String& longName) {
  logFileMMC.close();
  s_currentLogPath = "";

  // Helper lambda for "exclusive" create style.
  auto tryCreate = [](const String& name, File& out) -> bool {
    String abs = name;
    if (!abs.startsWith("/")) abs = "/" + abs;

    if (SD_MMC.exists(abs)) return false;

    out = SD_MMC.open(abs, FILE_WRITE);
    if (!out) return false;

    // Ensure we start from an empty file even if FILE_WRITE appends on this FS
    out.seek(0);

    return true;
  };


  // 1) Long name
  if (tryCreate(longName, logFileMMC)) {
    STOR_LOGI("SD_MMC: Using long filename: %s\n", longName.c_str());
    s_currentLogPath = longName;
    return true;
  }

  // 2) 8.3 short name
  STOR_LOGW("SD_MMC: long name failed, trying 8.3...\n");
  String shortName = make83Name(longName);
  STOR_LOGI("SD_MMC: 8.3 candidate: %s\n", shortName.c_str());

  if (tryCreate(shortName, logFileMMC)) {
    STOR_LOGI("SD_MMC: Using 8.3: %s\n", shortName.c_str());
    s_currentLogPath = shortName;
    return true;
  }

  // 3) Fallback numbered files
  STOR_LOGW("SD_MMC: 8.3 failed, trying LOGnnnn.CSV...\n");
  char fallback[20];
  for (int i = 1; i < 10000; i++) {
    snprintf(fallback, sizeof(fallback), "LOG%04d.CSV", i);
    if (tryCreate(String(fallback), logFileMMC)) {
      STOR_LOGI("SD_MMC: Using fallback: %s\n", fallback);
      s_currentLogPath = fallback;
      return true;
    }
  }

  return false;
}

// Start new log file
static void startLog() {
  if (loggingActive) return;
  const uint32_t totalT0 = millis();
  const char* backendName = "SD_MMC";

  // Reset non-blocking sample queue
  s_qHead = s_qTail = s_qCount = 0;
  s_samplesDropped = 0;
  s_flushCount = 0;
  s_flushMaxMs = 0;
  s_flushTotalMs = 0;
  s_rowsWritten = 0;
  s_currentLogPath = "";
  s_currentSessionId = "";
  s_logStartedAtUtc = "";
  s_logStartedAtLocal = "";
  s_activeLogFormat = ConfigManager::get().logFormat;
  s_synBikeRawBindings = SensorManager::SynBikeRawBindings{};

  const bool rtcValid = RTCManager_hasValidTime();
  const time_t startEpoch = RTCManager_getEpoch();
  const uint32_t filenameT0 = millis();
  String filename = RTCManager_getDateTimeString();
  s_logStartedAtUtc = isoUtcFromEpoch_(startEpoch);
  s_logStartedAtLocal = isoLocalFromFilenameTimestamp_(filename);
  const uint32_t filenameMs = millis() - filenameT0;
  filename.replace(":", "-");
  filename.replace(" ", "_");
  filename += ".CSV";
  s_currentSessionId = filename.substring(0, filename.length() - 4);

  if (!rtcValid) {
    STOR_LOGW("startLog: RTC invalid, using fallback filename '%s'\n", filename.c_str());
  }

  TRACE("[Storage] Trying to open log: ");
  STOR_LOGI("Trying to open log: %s\n", filename.c_str());

  bool ok = false;
  uint32_t openMs = 0;
  const uint32_t openT0 = millis();

  String path = "/";
  path += filename;

  STOR_LOGI("SD_MMC path = %s\n", path.c_str());

  ok = openNewLogFile_SDMMC(path);
  openMs = millis() - openT0;
  if (!ok) {
    TRACE("[Storage] startLog: SD_MMC open failed");
    STOR_LOGE("startLog: SD_MMC open failed. filenameMs=%lu openMs=%lu totalMs=%lu backend=%s rtcValid=%d\n",
              (unsigned long)filenameMs,
              (unsigned long)openMs,
              (unsigned long)(millis() - totalT0),
              backendName,
              rtcValid ? 1 : 0);
    return;
  }

  TRACE("openNewLogFile_SDMMC success");

  if (s_currentLogPath.length()) {
    s_currentSessionId = stemFromPath_(s_currentLogPath);
  }

  const uint32_t headerT0 = millis();
  uint32_t flushMs = 0;
  uint32_t headerMs = 0;

  if (isSynBikeRawFormat_()) {
    (void)SensorManager::resolveSynBikeRawBindings(s_synBikeRawBindings);
    if (!s_synBikeRawBindings.front.available) {
      STOR_LOGW("syn.bike raw format: no front wheel/suspension raw column found; emitting blank front column\n");
    }
    if (!s_synBikeRawBindings.rear.available) {
      STOR_LOGW("syn.bike raw format: no rear wheel/suspension raw column found; emitting blank rear column\n");
    }
    headerMs = millis() - headerT0;
  } else {
    // --- Build header (shared for both backends) ---
    //SensorManager::debugDump("startLog-beforeHeader");

    char header[256];
    TRACE("Entering sensormanager::buildheader");
    SensorManager::buildHeader(header, sizeof(header), RTCManager_isHumanReadable());
    TRACE("Finished sensormanager::buildheader");
    headerMs = millis() - headerT0;

    // ---- NEW: prepend sample_id column ----
    const char* idPrefix = "sample_id,";
    const size_t idLen   = strlen(idPrefix);
    const size_t hLen    = strlen(header);

    if (idLen + hLen + 1 < sizeof(header)) {   // +1 for terminating '\0'
      // Move existing header forward to make room for "sample_id,"
      memmove(header + idLen, header, hLen + 1);  // include '\0'
      // Copy the prefix at the start
      memcpy(header, idPrefix, idLen);
    } else {
      // If this ever happens, we ran out of header buffer space
      STOR_LOGW("Warning: header buffer too small for sample_id prefix\n");
    }

    STOR_LOGI("Header: %s\n", header);
    refreshValueColumnTypes_();

    const uint32_t flushT0 = millis();
    logFileMMC.println(header);
    logFileMMC.flush();
    flushMs = millis() - flushT0;
  }
  loggingActive = true;
  TRACE("[Storage] Log file opened successfully.");
  STOR_LOGI("startLog timing: filename=%lu ms open=%lu ms header=%lu ms firstFlush=%lu ms total=%lu ms backend=%s rtcValid=%d\n",
            (unsigned long)filenameMs,
            (unsigned long)openMs,
            (unsigned long)headerMs,
            (unsigned long)flushMs,
            (unsigned long)(millis() - totalT0),
            backendName,
            rtcValid ? 1 : 0);

}


void StorageManager_startLog() {
  startLog();
}


// Stop log
void StorageManager_stopLog() {
  if (!loggingActive) return;

  // Drain any remaining queued samples into the staging buffer
  SampleRow row;
  while (dequeueSample(row)) {
      StorageManager_logCsvDynamic(row.sample_id, row.ts_ms, row.values, row.nValues, row.mark);
  }

  if (bufferIndex > 0) {
    logFileMMC.write((const uint8_t*)buffer, bufferIndex);
    bufferIndex = 0;
  }


  logFileMMC.close();

  if (s_currentLogPath.length() && !ConfigManager::get().omitMetadata) {
    const String generatedAtLocal = isoLocalFromFilenameTimestamp_(RTCManager_getDateTimeString());
    LogMetadataContext metaCtx;
    metaCtx.csvPath = s_currentLogPath.c_str();
    metaCtx.sessionId = s_currentSessionId.c_str();
    metaCtx.startedAtUtc = s_logStartedAtUtc.c_str();
    metaCtx.startedAtLocal = s_logStartedAtLocal.c_str();
    metaCtx.timezone = RTCManager_getTimezone();
    metaCtx.generatedAtLocal = generatedAtLocal.c_str();
    metaCtx.rowCount = s_rowsWritten;
    metaCtx.sampleRateHz = (uint16_t)sampleRateHz;
    metaCtx.humanReadableTime = RTCManager_isHumanReadable();
    metaCtx.logFormat = s_activeLogFormat;
    metaCtx.samplesDropped = s_samplesDropped;
    metaCtx.queueMax = s_qMax;
    metaCtx.queueDepth = s_qCap;
    metaCtx.flushCount = s_flushCount;
    metaCtx.flushMaxMs = s_flushMaxMs;
    metaCtx.flushTotalMs = s_flushTotalMs;
    metaCtx.bufferSize = bufferSize;

    String metadata;
    if (LogMetadataWriter_build(metaCtx, metadata)) {
      const String metadataPath = LogMetadataWriter_metadataPathForCsv(s_currentLogPath.c_str());
      if (StorageManager_saveTextFile(metadataPath.c_str(), metadata)) {
        STOR_LOGI("Log metadata written: %s\n", metadataPath.c_str());
        createSessionArchive_(s_currentLogPath, metadataPath);
      } else {
        STOR_LOGW("Failed to write log metadata: %s\n", metadataPath.c_str());
      }
    } else {
      STOR_LOGW("Failed to build log metadata for %s\n", s_currentLogPath.c_str());
    }
  } else if (s_currentLogPath.length()) {
    STOR_LOGI("Log metadata omitted by config\n");
  }

  loggingActive = false;
  STOR_LOGI("samplesDropped=%lu\n", (unsigned long)s_samplesDropped);
  STOR_LOGI("flushCount=%lu maxFlushMs=%lu avgFlushMs=%.2f\n",
            (unsigned long)s_flushCount,
            (unsigned long)s_flushMaxMs,
            s_flushCount ? (double)s_flushTotalMs / s_flushCount : 0.0);
  STOR_LOGI("qMax=%u/%u\n", s_qMax, s_qCap);

  STOR_LOGI("Log file closed.\n");
  
  // Clear any leftover queued samples (we're no longer logging)
  s_qHead = s_qTail = s_qCount = 0;
}



void StorageManager_setCustomHeader(const char* csv) {
    if (!csv || !csv[0]) {
        s_customHeader[0] = '\0';
        return;
    }
    strncpy(s_customHeader, csv, sizeof(s_customHeader) - 1);
    s_customHeader[sizeof(s_customHeader) - 1] = '\0';
}

// Dynamic CSV logging: one FULL row per call, matching header
// Columns: [timestamp, sensor values..., mark]
static uint32_t formatRawForExport_(float raw, bool invert) {
    const uint32_t rawInt = (raw <= 0.0f) ? 0UL : (uint32_t)lroundf(raw);
    if (!invert) return rawInt;

    const uint32_t maxRaw = (board::gBoard && board::gBoard->analog.adc_max)
                              ? (uint32_t)board::gBoard->analog.adc_max
                              : 4095UL;
    return (rawInt >= maxRaw) ? 0UL : (maxRaw - rawInt);
}

static void appendSynBikeRawValue_(char* line,
                                   size_t lineSize,
                                   int& off,
                                   const float* values,
                                   uint16_t nValues,
                                   const SensorManager::SynBikeRawColumnBinding& binding) {
    if (!binding.available || binding.valueIndex >= nValues || !values) {
        int n = snprintf(line + off, lineSize - (size_t)off, ",");
        if (n > 0 && off + n < (int)lineSize) off += n;
        return;
    }

    const uint32_t raw = formatRawForExport_(values[binding.valueIndex], binding.invert);
    int n = snprintf(line + off, lineSize - (size_t)off, ",%lu", (unsigned long)raw);
    if (n > 0 && off + n < (int)lineSize) off += n;
}

static void StorageManager_logCsvSynBikeRaw_(uint32_t sample_id, const float* values, uint16_t nValues) {
    if (!logIsOpen()) {
        STOR_LOGW("logCsvSynBikeRaw: file not open\n");
        return;
    }

    char line[128];
    int off = snprintf(line, sizeof(line), "%lu", (unsigned long)sample_id);
    if (off <= 0 || off >= (int)sizeof(line)) return;

    appendSynBikeRawValue_(line, sizeof(line), off, values, nValues, s_synBikeRawBindings.front);
    appendSynBikeRawValue_(line, sizeof(line), off, values, nValues, s_synBikeRawBindings.rear);

    int n = snprintf(line + off, sizeof(line) - (size_t)off, ",,,\n");
    if (n <= 0 || off + n >= (int)sizeof(line)) return;
    off += n;

    const size_t len = (size_t)off;
    if (buffer && (bufferIndex + len > bufferSize)) {
        if (bufferIndex > 0) {
            logWriteInternal(buffer, bufferIndex);
            bufferIndex = 0;
        }
    }

    if (!buffer || len > bufferSize) {
        logWriteInternal(line, len);
        ++s_rowsWritten;
        return;
    }

    memcpy(&buffer[bufferIndex], line, len);
    bufferIndex += len;
    ++s_rowsWritten;
}

void StorageManager_logCsvDynamic(uint32_t sample_id, uint64_t ts_ms, const float* values, uint16_t nValues, bool mark)
{
    if (!logIsOpen()) {
        STOR_LOGW("logCsvDynamic: file not open\n");
        return;
    }
    if (isSynBikeRawFormat_()) {
        StorageManager_logCsvSynBikeRaw_(sample_id, values, nValues);
        return;
    }
    if (nValues == 0 || !values) return;

    // 1) Format ONE complete CSV line into a local stack buffer.
    //    Size generously: timestamp + commas + up to ~32 floats + mark + sd_busy + \n
    char line[512];
    int off = 0;
    
    // sample_id first
    off = snprintf(line, sizeof(line), "%lu", (unsigned long)sample_id);
    if (off <= 0 || off >= (int)sizeof(line)) return;

    // then timestamp (human: local HH:MM:SS.mmm ; else raw epoch ms)
    if (RTCManager_isHumanReadable()) {
        const time_t sec = (time_t)(ts_ms / 1000ULL);
        struct tm tm;
        localtime_r(&sec, &tm);
        const unsigned msecs = (unsigned)(ts_ms % 1000ULL);

        int n = snprintf(line + off, sizeof(line) - (size_t)off,
                         ",%02d:%02d:%02d.%03u",
                         tm.tm_hour, tm.tm_min, tm.tm_sec, msecs);
        if (n <= 0 || off + n >= (int)sizeof(line)) return;
        off += n;
    } else {
        int n = snprintf(line + off, sizeof(line) - (size_t)off,
                         ",%llu",
                         (unsigned long long)ts_ms);
        if (n <= 0 || off + n >= (int)sizeof(line)) return;
        off += n;
    }

    // Sensor values (comma-separated, fixed precision)
    for (uint16_t i = 0; i < nValues; ++i) {
        int n = 0;
        if (i < SM_MAX_DYNAMIC_COLS && s_valueColumnIsRaw[i]) {
            const uint32_t rawInt = formatRawForExport_(values[i], false);
            n = snprintf(line + off,
                         sizeof(line) - (size_t)off,
                         ",%lu",
                         (unsigned long)rawInt);
        } else {
            n = snprintf(line + off,
                         sizeof(line) - (size_t)off,
                         ",%.6f",
                         (double)values[i]);
        }
        if (n <= 0 || off + n >= (int)sizeof(line)) {
            return; // overflow guard
        }
        off += n;
    }

    // Mark, then newline
    {
        int n = snprintf(line + off,
                         sizeof(line) - (size_t)off,
                         ",%d\n",
                         mark ? 1 : 0);
        if (n <= 0 || off + n >= (int)sizeof(line)) {
            return; // overflow guard
        }
        off += n;
    }

    const size_t len = (size_t)off;

    // 2) Stage the FULL line atomically into the RAM buffer.

    // If the line won't fit in remaining space, flush the staging buffer first
    // (we only ever flush BETWEEN lines, never mid-row).
    if (buffer && (bufferIndex + len > bufferSize)) {
        if (bufferIndex > 0) {
            logWriteInternal(buffer, bufferIndex);
            bufferIndex = 0;
        }
    }

    // If the line is larger than the staging buffer, write it directly (rare)
    if (!buffer || len > bufferSize) {
        logWriteInternal(line, len);
        ++s_rowsWritten;
        return;
    }

    // 3) Copy the whole line into the staging buffer
    memcpy(&buffer[bufferIndex], line, len);
    bufferIndex += len;
    ++s_rowsWritten;

    // 4) No per-line flush here; periodic flush handled in StorageManager_loop()
}

static void refreshValueColumnTypes_()
{
  for (uint16_t i = 0; i < SM_MAX_DYNAMIC_COLS; ++i) {
    s_valueColumnIsRaw[i] = false;
  }

  (void)SensorManager::describeSensorColumnRawFlags(s_valueColumnIsRaw, SM_MAX_DYNAMIC_COLS);
}


// Background flush
void StorageManager_loop() {
  static unsigned long lastFlush = 0;
  unsigned long now = millis();
  static uint32_t s_rowCount = 0;

  // 1) Drain queued samples into the CSV staging buffer (backlog-aware)
  if (loggingActive) {
    // Drain until queue empty OR we spend our time budget this loop.
    // This makes the consumer much more resilient if the main loop hiccups.
    const uint32_t DRAIN_BUDGET_US = 5000;   // 5 ms budget; try 10000 if still dropping
    uint32_t t0_us = micros();

    SampleRow row;
    uint16_t processed = 0;

    while (dequeueSample(row)) {
      ++processed;
      ++s_rowCount;

      // Sampled timing of per-row formatting
      uint32_t t_row0 = 0;
      if ((s_rowCount % 200) == 0) t_row0 = micros();

      StorageManager_logCsvDynamic(row.sample_id, row.ts_ms, row.values, row.nValues, row.mark);

      if (t_row0) {
        uint32_t us = micros() - t_row0;
        ROW_LOGD("us=%lu nValues=%u\n", (unsigned long)us, (unsigned)row.nValues);
      }

      // Stop draining if we've exceeded our loop time budget
      if ((uint32_t)(micros() - t0_us) >= DRAIN_BUDGET_US) break;
    }

    // Occasional drain diagnostics if this loop took a noticeable chunk of time
    uint32_t dt_us = micros() - t0_us;
    if (dt_us > 50000) { // >50ms spent draining (should be rare)
      DRAIN_LOGD("processed=%u dt=%lu ms bufIndex=%u qMax=%u/%u\n",
                 (unsigned)processed, (unsigned long)(dt_us / 1000UL),
                 (unsigned)bufferIndex,
                 (unsigned)s_qMax, (unsigned)s_qCap);
    }
  }

  // 2) Periodic / threshold-based flush of the staging buffer to SD
  if (loggingActive && bufferIndex > 0) {
    if ((now - lastFlush >= 5000) || (bufferIndex > bufferSize * 9 / 10)) {

      uint32_t t0 = millis();

      if (g_sdTrackEnabled) {
        g_sdWriteSinceLastSample = true;
      }

      logWriteInternal(buffer, bufferIndex);

      uint32_t dt = millis() - t0;
      ++s_flushCount;
      s_flushTotalMs += dt;
      if (dt > s_flushMaxMs) s_flushMaxMs = dt;

      bufferIndex = 0;
      lastFlush   = now;
    }
  }
}




