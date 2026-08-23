#include "StorageManager.h"
#include "RTCManager.h"
#include "ConfigManager.h"
#include "SensorManager.h"
#include "BdqLogWriter.h"
#include "LogMetadataWriter.h"
#include "ZipArchiveWriter.h"
#include "LoggingManager.h"
#include "UI.h"
#include <ArduinoJson.h>

#include "BoardProfile.h"   // <-- whatever you called it after the namespace rename
#include "BoardSelect.h"
#include "DebugTrace.h"
#include "DebugLog.h"
#include "LoggerLimits.h"
#include "AnalogInputManager.h"
#include "I2CBusScheduler.h"
#include <math.h>
#include <new>
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
static bool s_sdMounted = false;
static bool s_cardDetectedCached = true;
static bool s_haveDetectPin = false;
static uint32_t s_nextDetectPollMs = 0;
static char s_lastStatus[48] = "not initialized";
constexpr size_t kMinWriteBufferBytes = 1024;
constexpr uint32_t kDefaultBdqTargetChunkBytes = 16384UL;
constexpr uint32_t kStorageWriteStallThresholdUs = 10000UL;

static inline bool isSdmmcBackend() {
  return s_storage && (s_storage->type == board::StorageType::SDMMC);
}

static File logFileMMC;

static char* buffer = nullptr;
static size_t bufferSize = 0;
static size_t bufferIndex = 0;
static size_t s_configuredBufferSize = 0;

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
static StorageTimingStats s_storageTiming;


// --- Sample row queue for non-blocking sampling ---
// Must match LoggingManager's values buffer size.
constexpr uint16_t SM_MAX_DYNAMIC_COLS = LoggerLimits::kMaxDynamicColumns;
static bool s_valueColumnIsRaw[SM_MAX_DYNAMIC_COLS] = {false};

struct SampleRow {
  uint32_t sample_id = 0;
  uint64_t ts_ms = 0;
  uint16_t nValues = 0;
  bool     mark = false;
  // 0 = unavailable/free or producer-owned, 1 = ready, 2 = consumer-owned.
  volatile uint8_t ready = 0;
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
static bool mountSdmmc_();

static void setStatus_(const char* status) {
  if (!status) status = "";
  snprintf(s_lastStatus, sizeof(s_lastStatus), "%s", status);
}

static bool readCardDetectPin_() {
  if (!s_storage || s_storage->detect_pin < 0) return true;
  const int level = digitalRead((uint8_t)s_storage->detect_pin);
  return s_storage->detect_active_low ? (level == LOW) : (level == HIGH);
}

static void setupCardDetectPin_() {
  s_haveDetectPin = s_storage && s_storage->detect_pin >= 0;
  if (!s_haveDetectPin) {
    s_cardDetectedCached = true;
    return;
  }

  pinMode((uint8_t)s_storage->detect_pin,
          s_storage->detect_use_internal_pullup ? INPUT_PULLUP : INPUT);
  s_cardDetectedCached = readCardDetectPin_();
  STOR_LOGI("SD detect GPIO%d active_%s initial=%s\n",
            (int)s_storage->detect_pin,
            s_storage->detect_active_low ? "low" : "high",
            s_cardDetectedCached ? "present" : "absent");
}

static bool isSynBikeRawFormat_() {
  return s_activeLogFormat == LogFormat::SynBikeRaw;
}

static bool isCompactBinaryFormat_() {
  return s_activeLogFormat == LogFormat::BodaqsCompactBinary;
}

static const char* activeLogExtension_() {
  return isCompactBinaryFormat_() ? ".bdq" : ".CSV";
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

static String isoLocalFromEpoch_(time_t epoch) {
  if (epoch < 1577836800) return String();

  struct tm localInfo;
  localtime_r(&epoch, &localInfo);
  if ((localInfo.tm_year + 1900) < 2020) return String();

  char buf[32];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S", &localInfo);
  return String(buf);
}

static String compactLocalStemFromEpoch_(time_t epoch) {
  if (epoch < 1577836800) return String();

  struct tm localInfo;
  localtime_r(&epoch, &localInfo);
  if ((localInfo.tm_year + 1900) < 2020) return String();

  char buf[16];
  strftime(buf, sizeof(buf), "%y%m%d_%H%M%S", &localInfo);
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

static String csvPathForArchive_(const String& archivePath) {
  if (!archivePath.endsWith(".zip")) return String();
  String out = archivePath.substring(0, archivePath.length() - 4);
  out += F(".CSV");
  return out;
}

static String metadataPathForArchive_(const String& archivePath) {
  if (!archivePath.endsWith(".zip")) return String();
  String out = archivePath.substring(0, archivePath.length() - 4);
  out += F(".json");
  return out;
}

static bool metadataSidecarLooksComplete_(const String& path);

static bool fileSize_(const String& path, uint32_t& sizeOut) {
  sizeOut = 0;
  if (!path.length()) return false;

  File f = SD_MMC.open(path.c_str(), FILE_READ);
  if (!f || f.isDirectory()) {
    if (f) f.close();
    return false;
  }

  sizeOut = static_cast<uint32_t>(f.size());
  f.close();
  return true;
}

static bool completedZipFile_(const String& path) {
  File f = SD_MMC.open(path.c_str(), FILE_READ);
  if (!f || f.isDirectory()) {
    if (f) f.close();
    return false;
  }

  const uint32_t size = static_cast<uint32_t>(f.size());
  if (size < 22 || !f.seek(size - 22)) {
    f.close();
    return false;
  }

  uint8_t sig[4] = {0, 0, 0, 0};
  const int n = f.read(sig, sizeof(sig));
  f.close();

  return n == 4 &&
         sig[0] == 0x50 &&
         sig[1] == 0x4B &&
         sig[2] == 0x05 &&
         sig[3] == 0x06;
}

static bool copyFile_(const String& srcPath, const String& dstPath, String* error = nullptr) {
  if (error) *error = "";
  if (!srcPath.length() || !dstPath.length()) {
    if (error) *error = F("missing source or destination");
    return false;
  }
  if (SD_MMC.exists(dstPath.c_str())) {
    if (error) *error = String(F("destination exists: ")) + dstPath;
    return false;
  }

  File in = SD_MMC.open(srcPath.c_str(), FILE_READ);
  if (!in || in.isDirectory()) {
    if (in) in.close();
    if (error) *error = String(F("source open failed: ")) + srcPath;
    return false;
  }

  File out = SD_MMC.open(dstPath.c_str(), FILE_WRITE);
  if (!out) {
    in.close();
    if (error) *error = String(F("destination open failed: ")) + dstPath;
    return false;
  }
  out.seek(0);

  static uint8_t buf[2048];
  bool ok = true;
  while (true) {
    const int n = in.read(buf, sizeof(buf));
    if (n < 0) {
      ok = false;
      if (error) *error = String(F("read failed: ")) + srcPath;
      break;
    }
    if (n == 0) break;

    const size_t written = out.write(buf, static_cast<size_t>(n));
    if (written != static_cast<size_t>(n)) {
      ok = false;
      if (error) *error = String(F("short write: ")) + dstPath;
      break;
    }
    delay(0);
  }

  out.flush();
  out.close();
  in.close();

  uint32_t srcSize = 0;
  uint32_t dstSize = 0;
  if (ok && (!fileSize_(srcPath, srcSize) || !fileSize_(dstPath, dstSize) || srcSize != dstSize)) {
    ok = false;
    if (error) *error = F("copy size verification failed");
  }

  if (!ok) {
    SD_MMC.remove(dstPath.c_str());
  }
  return ok;
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

static bool commitArchiveTemp_(const String& tempPath, const String& archivePath) {
  if (!tempPath.length() || !archivePath.length()) return false;

  if (SD_MMC.exists(archivePath.c_str())) {
    if (completedZipFile_(archivePath)) {
      if (SD_MMC.exists(tempPath.c_str())) {
        SD_MMC.remove(tempPath.c_str());
      }
      return true;
    }

    STOR_LOGW("Session archive final path exists but is not a complete ZIP: %s\n", archivePath.c_str());
    return false;
  }

  if (!completedZipFile_(tempPath)) {
    STOR_LOGW("Session archive temp is not a complete ZIP: %s\n", tempPath.c_str());
    return false;
  }

  if (SD_MMC.rename(tempPath.c_str(), archivePath.c_str())) {
    if (completedZipFile_(archivePath)) {
      return true;
    }
    STOR_LOGW("Session archive rename produced incomplete final archive: %s\n", archivePath.c_str());
    SD_MMC.remove(archivePath.c_str());
    return false;
  }

  STOR_LOGW("Session archive rename failed, trying copy fallback: %s -> %s\n",
            tempPath.c_str(),
            archivePath.c_str());

  String error;
  if (!copyFile_(tempPath, archivePath, &error)) {
    STOR_LOGW("Session archive copy fallback failed: %s\n", error.c_str());
    return false;
  }

  if (!completedZipFile_(archivePath)) {
    STOR_LOGW("Session archive copy fallback produced incomplete final archive: %s\n", archivePath.c_str());
    SD_MMC.remove(archivePath.c_str());
    return false;
  }

  if (!SD_MMC.remove(tempPath.c_str())) {
    STOR_LOGW("Session archive temp left after copy fallback: %s\n", tempPath.c_str());
  }
  return true;
}

static void removeArchivedSourceFilesForArchive_(const String& archivePath) {
  removeArchivedSourceFile_(csvPathForArchive_(archivePath), F("CSV source"));
  removeArchivedSourceFile_(metadataPathForArchive_(archivePath), F("metadata source"));
}

static void promoteStaleSessionArchives_() {
  File root = SD_MMC.open("/");
  if (!root || !root.isDirectory()) {
    if (root) root.close();
    return;
  }

  uint8_t promoted = 0;
  File entry = root.openNextFile();
  while (entry) {
    if (!entry.isDirectory()) {
      String name(entry.name());
      String lower = name;
      lower.toLowerCase();

      if (lower.endsWith(".zip.tmp")) {
        if (!name.startsWith("/")) name = "/" + name;
        const String tempPath = name;
        const String archivePath = tempPath.substring(0, tempPath.length() - 4);

        if (!metadataSidecarLooksComplete_(metadataPathForArchive_(archivePath))) {
          STOR_LOGW("Stale session archive not promoted; metadata sidecar is incomplete: %s\n",
                    archivePath.c_str());
          entry.close();
          delay(0);
          entry = root.openNextFile();
          continue;
        }

        if (commitArchiveTemp_(tempPath, archivePath)) {
          STOR_LOGI("Recovered session archive: %s\n", archivePath.c_str());
          removeArchivedSourceFilesForArchive_(archivePath);
          ++promoted;
        }
      }
    }

    entry.close();
    delay(0);
    entry = root.openNextFile();
  }
  root.close();

  if (promoted) {
    STOR_LOGI("Recovered %u stale session archive(s)\n", (unsigned)promoted);
  }
}

static void createSessionArchive_(const String& csvPath, const String& metadataPath) {
  if (!csvPath.length() || !metadataPath.length()) {
    STOR_LOGW("Session archive skipped: missing CSV or metadata path\n");
    return;
  }
  if (!metadataSidecarLooksComplete_(metadataPath)) {
    STOR_LOGW("Session archive skipped: metadata sidecar is incomplete: %s\n", metadataPath.c_str());
    return;
  }

  const String archivePath = archivePathForCsv_(csvPath);
  const String tempPath = archivePath + F(".tmp");

  if (SD_MMC.exists(archivePath.c_str())) {
    STOR_LOGW("Session archive skipped: final archive already exists: %s\n", archivePath.c_str());
    if (completedZipFile_(archivePath)) {
      removeArchivedSourceFile_(csvPath, F("CSV source"));
      removeArchivedSourceFile_(metadataPath, F("metadata source"));
    }
    return;
  }
  if (SD_MMC.exists(tempPath.c_str())) {
    if (commitArchiveTemp_(tempPath, archivePath)) {
      STOR_LOGI("Session archive recovered before rewrite: %s\n", archivePath.c_str());
      removeArchivedSourceFile_(csvPath, F("CSV source"));
      removeArchivedSourceFile_(metadataPath, F("metadata source"));
      return;
    }
    if (!SD_MMC.remove(tempPath.c_str())) {
      STOR_LOGW("Session archive skipped: could not remove stale temp archive: %s\n", tempPath.c_str());
      return;
    }
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

  if (!commitArchiveTemp_(tempPath, archivePath)) {
    STOR_LOGW("Session archive commit failed: %s -> %s\n", tempPath.c_str(), archivePath.c_str());
    return;
  }

  STOR_LOGI("Session archive written: %s\n", archivePath.c_str());
  removeArchivedSourceFile_(csvPath, F("CSV source"));
  removeArchivedSourceFile_(metadataPath, F("metadata source"));
}

static void resetQueueState_() {
  s_qHead = s_qTail = s_qCount = 0;
  s_qMax = 0;
}

static void releaseQueue_() {
  SampleRow* rows = s_rows;
  s_rows = nullptr;
  s_qCap = 0;
  resetQueueState_();
  delete[] rows;
}

static bool allocQueue_(uint16_t depth) {
  if (depth < 4) depth = 4;
  // cap it to something sane for uint16 math
  if (depth > 4096) depth = 4096;

  releaseQueue_();
  s_rows = new (std::nothrow) SampleRow[depth];

  if (!s_rows) {
    STOR_LOGE("allocQueue failed depth=%u bytes=%u\n",
              (unsigned)depth,
              (unsigned)(depth * sizeof(SampleRow)));
    s_qCap = 0;
    resetQueueState_();
    return false;
  }

  s_qCap = depth;
  resetQueueState_();
  return true;
}

static void releaseWriteBuffer_() {
  char* old = buffer;
  buffer = nullptr;
  bufferSize = 0;
  bufferIndex = 0;
  delete[] old;
}

static bool allocWriteBuffer_(size_t bytes) {
  releaseWriteBuffer_();
  if (bytes == 0) {
    return true;
  }

  if (bytes < kMinWriteBufferBytes) bytes = kMinWriteBufferBytes;
  for (size_t attempt = bytes; attempt >= kMinWriteBufferBytes; attempt /= 2) {
    buffer = new (std::nothrow) char[attempt];
    if (buffer) {
      bufferSize = attempt;
      bufferIndex = 0;
      if (attempt != bytes) {
        STOR_LOGW("write buffer reduced to %u bytes after allocation fallback\n",
                  (unsigned)attempt);
      }
      return true;
    }
  }

  STOR_LOGW("write buffer allocation failed; using direct SD writes\n");
  return true;
}

static void releaseLogSessionBuffers_() {
  releaseWriteBuffer_();
  releaseQueue_();
}

static bool prepareLogSessionBuffers_() {
  const uint16_t queueDepth = s_perf ? s_perf->queue_depth : 64;
  if (!allocQueue_(queueDepth)) {
    setStatus_("sample queue OOM");
    return false;
  }

  if (isCompactBinaryFormat_()) {
    releaseWriteBuffer_();
    return true;
  }

  const size_t desiredBufferSize = s_configuredBufferSize
                                     ? s_configuredBufferSize
                                     : (s_perf ? s_perf->ring_buffer_bytes : 4096);
  if (!allocWriteBuffer_(desiredBufferSize)) {
    releaseQueue_();
    setStatus_("write buffer OOM");
    return false;
  }
  return true;
}

static bool mountSdmmc_() {
  if (!isSdmmcBackend()) {
    setStatus_("storage disabled");
    return false;
  }

  if (s_haveDetectPin && !s_cardDetectedCached) {
    if (s_sdMounted) {
      SD_MMC.end();
      s_sdMounted = false;
    }
    setStatus_("card not detected");
    STOR_LOGW("SD mount skipped: card detect says absent\n");
    return false;
  }

  if (s_sdMounted && SD_MMC.cardType() != CARD_NONE) {
    setStatus_("mounted");
    return true;
  }

  if (s_sdMounted) {
    SD_MMC.end();
    s_sdMounted = false;
  }

  STOR_LOGI("begin(): backend = SDMMC (SD_MMC)\n");
  STOR_LOGI("begin (SDMMC): starting SD_MMC\n");

  const int clk = s_storage->sdmmc_clk;
  const int cmd = s_storage->sdmmc_cmd;
  const int d0  = s_storage->sdmmc_d0;

  if (clk < 0 || cmd < 0 || d0 < 0) {
    setStatus_("SDMMC pins invalid");
    STOR_LOGE("SDMMC backend selected but sdmmc_clk/cmd/d0 not set\n");
    return false;
  }

  if (s_storage->sdmmc_1bit) {
    SD_MMC.setPins(clk, cmd, d0);
  } else {
    const int d1 = s_storage->sdmmc_d1;
    const int d2 = s_storage->sdmmc_d2;
    const int d3 = s_storage->sdmmc_d3;
    if (d1 < 0 || d2 < 0 || d3 < 0) {
      setStatus_("SDMMC 4-bit pins invalid");
      STOR_LOGE("SDMMC 4-bit selected but d1/d2/d3 not set\n");
      return false;
    }
    SD_MMC.setPins(clk, cmd, d0, d1, d2, d3);
  }

  const bool ok = SD_MMC.begin("/sdcard", s_storage->sdmmc_1bit);
  STOR_LOGI("SD_MMC.begin result: %s\n", ok ? "OK (true)" : "FAILED (false)");

  if (!ok) {
    setStatus_("mount failed");
    STOR_LOGE("SD_MMC.begin FAILED, returning\n");
    return false;
  }

  uint8_t cardType = SD_MMC.cardType();
  if (cardType == CARD_NONE) {
    setStatus_("no card");
    STOR_LOGW("No SD card attached (cardType=CARD_NONE)\n");
    SD_MMC.end();
    s_sdMounted = false;
    return false;
  }

  s_sdMounted = true;
  setStatus_("mounted");
  STOR_LOGI("SD_MMC cardType = %u\n", (unsigned)cardType);

  uint64_t sizeMB = SD_MMC.cardSize() / (1024ULL * 1024ULL);
  STOR_LOGI("SD card size: %llu MB\n", (unsigned long long)sizeMB);

  promoteStaleSessionArchives_();

  STOR_LOGI("SD_MMC.begin OK.\n");
  return true;
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

  // If the producer reserved this slot but has not published it, do not pop it.
  if (s_rows[idx].ready != 1) {
#if defined(ESP32)
    portEXIT_CRITICAL(&s_qMux);
#endif
    return false;  // try again next loop iteration
  }

  // Keep the row counted as occupied while it is copied. This prevents the
  // producer from wrapping around and reusing the slot during the copy.
  s_rows[idx].ready = 2;

#if defined(ESP32)
  portEXIT_CRITICAL(&s_qMux);
#endif

  out = s_rows[idx];

#if defined(ESP32)
  portENTER_CRITICAL(&s_qMux);
#endif

  s_rows[idx].ready = 0;
  s_qTail = (uint16_t)((s_qTail + 1) % s_qCap);
  --s_qCount;

#if defined(ESP32)
  portEXIT_CRITICAL(&s_qMux);
#endif

  return true;
}

static uint16_t queueDepthSnapshot_() {
#if defined(ESP32)
  portENTER_CRITICAL(&s_qMux);
#endif
  const uint16_t depth = s_qCount;
#if defined(ESP32)
  portEXIT_CRITICAL(&s_qMux);
#endif
  return depth;
}

static void recordStorageWriteStall_(
    uint8_t operation,
    uint32_t sampleId,
    uint32_t durationUs,
    uint32_t bytesAttempted,
    uint16_t dataFrameCount) {
  if (durationUs < kStorageWriteStallThresholdUs) return;

  ++s_storageTiming.writeStallCount;
  if (s_storageTiming.writeStallStoredCount >= StorageTimingStats::kMaxWriteStallEvents) {
    s_storageTiming.writeStallEventsTruncated = true;
    return;
  }

  auto& event = s_storageTiming.writeStallEvents[s_storageTiming.writeStallStoredCount++];
  event.sampleId = sampleId;
  event.durationUs = durationUs;
  event.bytesAttempted = bytesAttempted;
  event.queueDepthRows = queueDepthSnapshot_();
  event.dataFrameCount = dataFrameCount;
  event.operation = operation;
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

static bool ensureParentDirs_(const String& absPath) {
  const int lastSlash = absPath.lastIndexOf('/');
  if (lastSlash <= 0) return true;

  int slash = absPath.indexOf('/', 1);
  while (slash > 0 && slash <= lastSlash) {
    String dir = absPath.substring(0, slash);
    if (dir.length() && !SD_MMC.exists(dir.c_str())) {
      if (!SD_MMC.mkdir(dir.c_str())) {
        STOR_LOGW("saveTextFile: mkdir failed for %s\n", dir.c_str());
        return false;
      }
    }
    slash = absPath.indexOf('/', slash + 1);
  }

  String parent = absPath.substring(0, lastSlash);
  if (parent.length() && !SD_MMC.exists(parent.c_str())) {
    if (!SD_MMC.mkdir(parent.c_str())) {
      STOR_LOGW("saveTextFile: mkdir failed for %s\n", parent.c_str());
      return false;
    }
  }

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

  if (!ensureParentDirs_(absPath)) {
    return false;
  }

  String tmpPath = absPath + F(".tmp");
  String bakPath = absPath + F(".bak");

  if (SD_MMC.exists(tmpPath.c_str()) && !SD_MMC.remove(tmpPath.c_str())) {
    STOR_LOGW("saveTextFile: remove stale temp failed for %s\n", tmpPath.c_str());
    return false;
  }

  File f = SD_MMC.open(tmpPath.c_str(), FILE_WRITE);
  if (!f) {
    STOR_LOGW("saveTextFile: SD_MMC open failed for %s\n", tmpPath.c_str());
    return false;
  }

  size_t written = f.write((const uint8_t*)cstr, len);
  f.flush();
  f.close();

  if (written != len) {
    STOR_LOGW("saveTextFile: SD_MMC short write (%u/%u)\n",
              (unsigned)written, (unsigned)len);
    SD_MMC.remove(tmpPath.c_str());
    return false;
  }

  if (SD_MMC.exists(bakPath.c_str()) && !SD_MMC.remove(bakPath.c_str())) {
    STOR_LOGW("saveTextFile: remove stale backup failed for %s\n", bakPath.c_str());
    SD_MMC.remove(tmpPath.c_str());
    return false;
  }

  const bool hadExisting = SD_MMC.exists(absPath.c_str());
  if (hadExisting && !SD_MMC.rename(absPath.c_str(), bakPath.c_str())) {
    STOR_LOGW("saveTextFile: backup rename failed for %s\n", absPath.c_str());
    SD_MMC.remove(tmpPath.c_str());
    return false;
  }

  if (!SD_MMC.rename(tmpPath.c_str(), absPath.c_str())) {
    STOR_LOGW("saveTextFile: final rename failed for %s\n", absPath.c_str());
    if (hadExisting && SD_MMC.exists(bakPath.c_str())) {
      SD_MMC.rename(bakPath.c_str(), absPath.c_str());
    }
    SD_MMC.remove(tmpPath.c_str());
    return false;
  }

  if (hadExisting && SD_MMC.exists(bakPath.c_str())) {
    SD_MMC.remove(bakPath.c_str());
  }

  return true;
}

StorageTimingStats StorageManager_timingStats() {
  return s_storageTiming;
}


void StorageManager_begin(const board::BoardProfile& bp) {
  s_storage = &bp.storage;
  s_perf    = &bp.perf;
  s_sdMounted = false;
  setStatus_("not mounted");

  // 1) Capture perf knobs early. Large logging buffers are allocated only
  // when a logging session starts, so web/config modes keep that RAM free.
  if (s_perf) {
    StorageManager_setBufferSize(s_perf->ring_buffer_bytes);
  }

  setupCardDetectPin_();

  if (isSdmmcBackend()) {
    (void)mountSdmmc_();
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

unsigned int StorageManager_getSampleRateHz() {
    return sampleRateHz;
}

// Set buffer size
void StorageManager_setBufferSize(size_t bytes) {
    s_configuredBufferSize = bytes;
    if (!loggingActive) {
      releaseWriteBuffer_();
    }
}

static bool tryCreateLogFile_SDMMC_(const String& name, File& out) {
  String abs = name;
  if (!abs.startsWith("/")) abs = "/" + abs;

  if (SD_MMC.exists(abs)) return false;

  out = SD_MMC.open(abs, FILE_WRITE);
  if (!out) return false;

  // Ensure we start from an empty file even if FILE_WRITE appends on this FS.
  out.seek(0);
  return true;
}

static bool openNumberedLogFile_SDMMC_(const char* extension) {
  STOR_LOGW("SD_MMC: trying LOGnnnn%s filename fallback...\n", extension ? extension : "");
  char fallback[24];
  for (int i = 1; i < 10000; i++) {
    snprintf(fallback, sizeof(fallback), "LOG%04d%s", i, extension ? extension : ".CSV");
    if (tryCreateLogFile_SDMMC_(String(fallback), logFileMMC)) {
      STOR_LOGI("SD_MMC: Using fallback: %s\n", fallback);
      s_currentLogPath = fallback;
      return true;
    }
  }

  return false;
}

// Utility: truncate to 8.3 filename
static String make83Name(const String &dtString, const char* extension) {
    // Example: "260219_094331.CSV" -> "L2602190.CSV"
    String name = "L";

    // keep only digits
    for (char c : dtString) {
        if (isdigit(c)) name += c;
        if (name.length() >= 8) break;  // enforce 8 chars max
    }

    name += extension ? extension : ".CSV";
    return name;
}

static bool openNewLogFile_SDMMC(const String& longName, const char* extension, bool numberedOnly = false) {
  logFileMMC.close();
  s_currentLogPath = "";

  if (numberedOnly) {
    return openNumberedLogFile_SDMMC_(extension);
  }

  // 1) Long name
  if (tryCreateLogFile_SDMMC_(longName, logFileMMC)) {
    STOR_LOGI("SD_MMC: Using long filename: %s\n", longName.c_str());
    s_currentLogPath = longName;
    return true;
  }

  // 2) 8.3 short name
  STOR_LOGW("SD_MMC: long name failed, trying 8.3...\n");
  String shortName = make83Name(longName, extension);
  STOR_LOGI("SD_MMC: 8.3 candidate: %s\n", shortName.c_str());

  if (tryCreateLogFile_SDMMC_(shortName, logFileMMC)) {
    STOR_LOGI("SD_MMC: Using 8.3: %s\n", shortName.c_str());
    s_currentLogPath = shortName;
    return true;
  }

  // 3) Fallback numbered files
  STOR_LOGW("SD_MMC: 8.3 failed\n");
  return openNumberedLogFile_SDMMC_(extension);
}

// Start new log file
static void startLog() {
  if (loggingActive) return;
  const uint32_t totalT0 = millis();
  const char* backendName = "SD_MMC";

  resetQueueState_();
  s_samplesDropped = 0;
  s_flushCount = 0;
  s_flushMaxMs = 0;
  s_flushTotalMs = 0;
  s_storageTiming = StorageTimingStats{};
  s_storageTiming.writeStallThresholdUs = kStorageWriteStallThresholdUs;
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
  const String compactStem = rtcValid ? compactLocalStemFromEpoch_(startEpoch) : String();
  const char* logExtension = activeLogExtension_();
  String filename;
  if (compactStem.length()) {
    filename = compactStem + logExtension;
  } else {
    filename = String(F("LOGnnnn")) + logExtension;
  }
  s_logStartedAtUtc = compactStem.length() ? isoUtcFromEpoch_(startEpoch) : String();
  s_logStartedAtLocal = compactStem.length() ? isoLocalFromEpoch_(startEpoch) : String();
  const uint32_t filenameMs = millis() - filenameT0;
  s_currentSessionId = compactStem;

  if (!compactStem.length()) {
    STOR_LOGW("startLog: RTC timestamp unavailable, using LOGnnnn%s filename fallback\n", logExtension);
  }

  TRACE("[Storage] Trying to open log: ");
  STOR_LOGI("Trying to open log: %s\n", filename.c_str());

  if (!StorageManager_readyForLogging()) {
    STOR_LOGE("startLog: storage not ready (%s)\n", StorageManager_lastStatus());
    UI::status("SD missing");
    UI::toast("SD missing", 1500, 1);
    return;
  }

  if (!prepareLogSessionBuffers_()) {
    STOR_LOGE("startLog: failed to allocate logging buffers (%s)\n", StorageManager_lastStatus());
    UI::status("Log memory");
    UI::toast("Log memory", 1500, 1);
    return;
  }

  bool ok = false;
  uint32_t openMs = 0;
  const uint32_t openT0 = millis();

  String path = "/";
  path += filename;

  STOR_LOGI("SD_MMC path = %s\n", path.c_str());

  ok = openNewLogFile_SDMMC(path, logExtension, !compactStem.length());
  openMs = millis() - openT0;
  if (!ok) {
    TRACE("[Storage] startLog: SD_MMC open failed");
    STOR_LOGE("startLog: SD_MMC open failed. filenameMs=%lu openMs=%lu totalMs=%lu backend=%s rtcValid=%d\n",
              (unsigned long)filenameMs,
              (unsigned long)openMs,
              (unsigned long)(millis() - totalT0),
              backendName,
              rtcValid ? 1 : 0);
    releaseLogSessionBuffers_();
    return;
  }

  TRACE("openNewLogFile_SDMMC success");

  if (s_currentLogPath.length()) {
    s_currentSessionId = stemFromPath_(s_currentLogPath);
  }

  const uint32_t headerT0 = millis();
  uint32_t flushMs = 0;
  uint32_t headerMs = 0;

  if (isCompactBinaryFormat_()) {
    BdqLogSessionInfo info;
    info.config = &ConfigManager::get();
    info.logPath = s_currentLogPath.c_str();
    info.sessionId = s_currentSessionId.c_str();
    info.startedAtUtc = s_logStartedAtUtc.c_str();
    info.startedAtLocal = s_logStartedAtLocal.c_str();
    info.timezone = RTCManager_getTimezone();
    info.createdUnixUs = rtcValid ? ((uint64_t)startEpoch * 1000000ULL) : 0;
    info.sampleRateHz = (uint16_t)sampleRateHz;
    info.samplePeriodUs = sampleRateHz ? (1000000UL / sampleRateHz) : 0;
    info.targetChunkBytes = (s_perf && s_perf->bdq_chunk_bytes)
                              ? s_perf->bdq_chunk_bytes
                              : kDefaultBdqTargetChunkBytes;

    if (!BdqLogWriter::begin(logFileMMC, info)) {
      STOR_LOGE("BDQ writer begin failed\n");
      logFileMMC.close();
      s_currentLogPath = "";
      releaseLogSessionBuffers_();
      return;
    }
    headerMs = millis() - headerT0;
    flushMs = 0;
  } else if (isSynBikeRawFormat_()) {
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

    TRACE("Entering sensormanager::buildheader");
    String header = SensorManager::buildHeaderString(RTCManager_isHumanReadable());
    TRACE("Finished sensormanager::buildheader");
    headerMs = millis() - headerT0;

    header = String(F("sample_id,")) + header;

    STOR_LOGI("Header: %s\n", header.c_str());
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


bool StorageManager_startLog() {
  const bool wasActive = loggingActive;
  startLog();
  return loggingActive || wasActive;
}

static void StorageManager_logSampleRow_(const SampleRow& row) {
#if BODAQS_TIMING_INSTRUMENTATION
  const uint32_t t0 = micros();
#endif
  if (isCompactBinaryFormat_()) {
    const bool wrote = BdqLogWriter::writeSample(
        row.sample_id, row.ts_ms, row.values, row.nValues, row.mark);
    if (wrote) {
      ++s_rowsWritten;
    }
#if BODAQS_TIMING_INSTRUMENTATION
    const uint32_t durationUs = (uint32_t)(micros() - t0);
    TimingStats_record(s_storageTiming.rowWriteUs, durationUs);
    const uint32_t bytesAttempted = BdqLogWriter::lastDataChunkBytes();
    recordStorageWriteStall_(
        bytesAttempted ? 1u : 0u,
        row.sample_id,
        durationUs,
        bytesAttempted,
        BdqLogWriter::lastDataChunkFrameCount());
#endif
    return;
  }

  StorageManager_logCsvDynamic(row.sample_id, row.ts_ms, row.values, row.nValues, row.mark);
#if BODAQS_TIMING_INSTRUMENTATION
  const uint32_t durationUs = (uint32_t)(micros() - t0);
  TimingStats_record(s_storageTiming.rowWriteUs, durationUs);
  recordStorageWriteStall_(0u, row.sample_id, durationUs, 0u, 0u);
#endif
}

void StorageManager_drainQueuedSamples() {
  if (!loggingActive) return;
  SampleRow row;
  while (dequeueSample(row)) {
    StorageManager_logSampleRow_(row);
  }
}

static bool metadataSidecarLooksComplete_(const String& path) {
  File file = SD_MMC.open(path.c_str(), FILE_READ);
  if (!file || file.isDirectory()) {
    if (file) file.close();
    return false;
  }

  // Filtered parsing validates the whole document while retaining only a
  // tiny contract fragment, so validation does not recreate the large JSON
  // allocation that streaming is intended to avoid.
  JsonDocument filter;
  filter["contract"]["name"] = true;
  JsonDocument document;
  const DeserializationError error = deserializeJson(
      document, file, DeserializationOption::Filter(filter));
  file.close();
  return !error && document["contract"]["name"] == "mtb_logger_timeseries";
}

static bool writeLogMetadataSidecar_(const String& path, const LogMetadataContext& ctx) {
  if (!path.length() || SD_MMC.cardType() == CARD_NONE) return false;
  if (!ensureParentDirs_(path)) return false;

  const String tempPath = path + F(".tmp");
  const String backupPath = path + F(".bak");
  if (SD_MMC.exists(tempPath.c_str()) && !SD_MMC.remove(tempPath.c_str())) {
    STOR_LOGW("Metadata sidecar: could not remove stale temp file: %s\n", tempPath.c_str());
    return false;
  }

  File file = SD_MMC.open(tempPath.c_str(), FILE_WRITE);
  if (!file) {
    STOR_LOGW("Metadata sidecar: open failed: %s\n", tempPath.c_str());
    return false;
  }

  const bool writeOk = LogMetadataWriter_write(ctx, file);
  file.flush();
  file.close();
  if (!writeOk || !metadataSidecarLooksComplete_(tempPath)) {
    STOR_LOGW("Metadata sidecar: generation or validation failed: %s\n", tempPath.c_str());
    SD_MMC.remove(tempPath.c_str());
    return false;
  }

  if (SD_MMC.exists(backupPath.c_str()) && !SD_MMC.remove(backupPath.c_str())) {
    STOR_LOGW("Metadata sidecar: could not remove stale backup: %s\n", backupPath.c_str());
    SD_MMC.remove(tempPath.c_str());
    return false;
  }

  const bool hadExisting = SD_MMC.exists(path.c_str());
  if (hadExisting && !SD_MMC.rename(path.c_str(), backupPath.c_str())) {
    STOR_LOGW("Metadata sidecar: backup rename failed: %s\n", path.c_str());
    SD_MMC.remove(tempPath.c_str());
    return false;
  }
  if (!SD_MMC.rename(tempPath.c_str(), path.c_str())) {
    STOR_LOGW("Metadata sidecar: final rename failed: %s\n", path.c_str());
    if (hadExisting && SD_MMC.exists(backupPath.c_str())) {
      SD_MMC.rename(backupPath.c_str(), path.c_str());
    }
    SD_MMC.remove(tempPath.c_str());
    return false;
  }
  if (hadExisting && SD_MMC.exists(backupPath.c_str())) {
    SD_MMC.remove(backupPath.c_str());
  }
  return true;
}


// Stop log
void StorageManager_stopLog() {
  if (!loggingActive) return;

  // Drain any remaining queued samples into the staging buffer
  StorageManager_drainQueuedSamples();

  if (!isCompactBinaryFormat_() && bufferIndex > 0) {
    logFileMMC.write((const uint8_t*)buffer, bufferIndex);
    bufferIndex = 0;
  }

  if (isCompactBinaryFormat_()) {
    const LoggingManager::RuntimeStats stats = LoggingManager::runtimeStats();
    BdqLogEndInfo endInfo;
    endInfo.samplesDropped = s_samplesDropped;
    endInfo.queueMax = s_qMax;
    endInfo.queueDepth = s_qCap;
    endInfo.flushCount = s_flushCount;
    endInfo.flushMaxMs = s_flushMaxMs;
    endInfo.flushTotalMs = s_flushTotalMs;
    endInfo.samplerLateTicks = stats.samplerLateTicks;
    endInfo.samplerLateMaxLagMs = stats.samplerLateMaxLagMs;
    endInfo.missedSampleSlots = stats.missedSampleSlots;
    endInfo.sampleOnceUs = &stats.sampleOnceUs;
    endInfo.sensorSampleUs = &stats.sensorSampleUs;
    endInfo.enqueueUs = &stats.enqueueUs;
    endInfo.storageTiming = &s_storageTiming;
    endInfo.externalAdcTiming = &AnalogInputManager::timingStats();
    endInfo.sensorTiming = &SensorManager::timingStats();
    endInfo.i2cSchedulerTiming = &I2CBusScheduler::timingStats();
    endInfo.boardProfile = board::gBoard;
    if (!BdqLogWriter::end(endInfo)) {
      STOR_LOGW("BDQ writer end failed for %s\n", s_currentLogPath.c_str());
    }
  }

  logFileMMC.close();

  if (!isCompactBinaryFormat_() && s_currentLogPath.length() && !ConfigManager::get().omitMetadata) {
    const String generatedAtLocal = isoLocalFromEpoch_(RTCManager_getEpoch());
    const LoggingManager::RuntimeStats stats = LoggingManager::runtimeStats();
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
    metaCtx.samplerLateTicks = stats.samplerLateTicks;
    metaCtx.samplerLateMaxLagMs = stats.samplerLateMaxLagMs;
    metaCtx.missedSampleSlots = stats.missedSampleSlots;
    metaCtx.sampleOnceUs = &stats.sampleOnceUs;
    metaCtx.sensorSampleUs = &stats.sensorSampleUs;
    metaCtx.enqueueUs = &stats.enqueueUs;
    metaCtx.storageTiming = &s_storageTiming;
    metaCtx.externalAdcTiming = &AnalogInputManager::timingStats();
    metaCtx.sensorTiming = &SensorManager::timingStats();
    metaCtx.i2cSchedulerTiming = &I2CBusScheduler::timingStats();
    metaCtx.boardProfile = board::gBoard;

    const String metadataPath = LogMetadataWriter_metadataPathForCsv(s_currentLogPath.c_str());
    if (writeLogMetadataSidecar_(metadataPath, metaCtx)) {
      STOR_LOGI("Log metadata written: %s\n", metadataPath.c_str());
      createSessionArchive_(s_currentLogPath, metadataPath);
    } else {
      STOR_LOGW("Failed to write complete log metadata for %s\n", s_currentLogPath.c_str());
    }
  } else if (!isCompactBinaryFormat_() && s_currentLogPath.length()) {
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

  // Logging owns these buffers; give them back before returning to web/config mode.
  releaseLogSessionBuffers_();
}



void StorageManager_setCustomHeader(const char* csv) {
    if (!csv || !csv[0]) {
        s_customHeader[0] = '\0';
        return;
    }
    strncpy(s_customHeader, csv, sizeof(s_customHeader) - 1);
    s_customHeader[sizeof(s_customHeader) - 1] = '\0';
}

bool StorageManager_cardDetected() {
  if (!s_storage) return true;
  if (s_haveDetectPin) {
    s_cardDetectedCached = readCardDetectPin_();
    return s_cardDetectedCached;
  }
  if (!isSdmmcBackend()) return false;
  return s_sdMounted && SD_MMC.cardType() != CARD_NONE;
}

bool StorageManager_isMounted() {
  if (!s_storage) return true;
  return s_sdMounted && SD_MMC.cardType() != CARD_NONE;
}

bool StorageManager_remountIfPresent() {
  if (!s_storage || !isSdmmcBackend()) return false;
  if (s_haveDetectPin) {
    s_cardDetectedCached = readCardDetectPin_();
  }
  return mountSdmmc_();
}

bool StorageManager_readyForLogging() {
  if (StorageManager_isMounted()) return true;
  return StorageManager_remountIfPresent();
}

const char* StorageManager_lastStatus() {
  return s_lastStatus;
}

// Dynamic CSV logging: one FULL row per call, matching header
// Columns: [timestamp, sensor values..., mark]
static uint32_t formatRawForExport_(float raw, bool invert) {
    if (!isfinite(raw)) return 0UL;
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
    //    Size generously: sample id + timestamp + commas + sensor values + mark + newline.
    char line[1280];
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

  if (s_haveDetectPin && (int32_t)(now - s_nextDetectPollMs) >= 0) {
    s_nextDetectPollMs = now + 500;
    const bool present = readCardDetectPin_();
    if (present != s_cardDetectedCached) {
      s_cardDetectedCached = present;
      if (!present) {
        setStatus_("card removed");
        STOR_LOGW("SD card removed\n");
        UI::status("SD removed");
        UI::toast("SD removed", 1800, 1);

        if (LoggingManager::isRunning()) {
          STOR_LOGW("Stopping logging because SD card detect went absent\n");
          LoggingManager::stop();
          SD_MMC.end();
          s_sdMounted = false;
        } else if (s_sdMounted) {
          SD_MMC.end();
          s_sdMounted = false;
        }
      } else {
        setStatus_("card inserted");
        STOR_LOGI("SD card inserted; attempting mount\n");
        UI::toast("SD inserted", 1200, 1);
        if (!LoggingManager::isRunning() && mountSdmmc_()) {
          UI::status("SD ready");
        }
      }
    }
  }

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

      StorageManager_logSampleRow_(row);

      if (t_row0) {
        uint32_t us = micros() - t_row0;
        ROW_LOGD("us=%lu nValues=%u\n", (unsigned long)us, (unsigned)row.nValues);
      }

      // Stop draining if we've exceeded our loop time budget
      if ((uint32_t)(micros() - t0_us) >= DRAIN_BUDGET_US) break;
    }

    // Occasional drain diagnostics if this loop took a noticeable chunk of time
    uint32_t dt_us = micros() - t0_us;
    if (processed > 0) {
#if BODAQS_TIMING_INSTRUMENTATION
      ++s_storageTiming.drainLoops;
      s_storageTiming.drainRows += processed;
      TimingStats_record(s_storageTiming.drainLoopUs, dt_us);
#endif
    }
    if (dt_us > 50000) { // >50ms spent draining (should be rare)
      DRAIN_LOGD("processed=%u dt=%lu ms bufIndex=%u qMax=%u/%u\n",
                 (unsigned)processed, (unsigned long)(dt_us / 1000UL),
                 (unsigned)bufferIndex,
                 (unsigned)s_qMax, (unsigned)s_qCap);
    }
  }

  // 2) Periodic / threshold-based flush of the staging buffer to SD
  if (loggingActive && isCompactBinaryFormat_()) {
    if ((now - lastFlush >= 5000) && BdqLogWriter::pendingFrameCount() > 0) {
      uint32_t t0 = millis();
#if BODAQS_TIMING_INSTRUMENTATION
      const uint32_t t0Us = micros();
#endif

      if (g_sdTrackEnabled) {
        g_sdWriteSinceLastSample = true;
      }

      if (BdqLogWriter::flushDataChunk()) {
        BdqLogWriter::flushFile();

        uint32_t dt = millis() - t0;
        ++s_flushCount;
        s_flushTotalMs += dt;
        if (dt > s_flushMaxMs) s_flushMaxMs = dt;
      }
#if BODAQS_TIMING_INSTRUMENTATION
      recordStorageWriteStall_(
          2u,
          0u,
          (uint32_t)(micros() - t0Us),
          BdqLogWriter::lastDataChunkBytes(),
          BdqLogWriter::lastDataChunkFrameCount());
#endif
      lastFlush = now;
    }
    return;
  }

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




