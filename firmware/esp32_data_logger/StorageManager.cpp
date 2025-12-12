#include "StorageManager.h"
#include "RTCManager.h"
#include "ConfigManager.h"
#include "SensorManager.h"
#include "SPI.h"

extern LoggerConfig g_cfg;   // declared in your .ino

// For now: hard-coded. Later: move into ConfigManager.
enum class StorageBackendType {
    SPI_SDFAT,   // external SD over SPI (your current setup)
    SDIO_SDMMC   // onboard SD slot using SD_MMC
};

// TEMP: manual selection
constexpr StorageBackendType STORAGE_BACKEND = StorageBackendType::SDIO_SDMMC;
//constexpr StorageBackendType STORAGE_BACKEND = StorageBackendType::SPI_SDFAT;




static SdFat sd;
static FsFile logFile;
static File logFileMMC;

static char* buffer = nullptr;
static size_t bufferSize = 0;
static size_t bufferIndex = 0;

static unsigned int sampleRateHz = 1;
static unsigned long sampleIntervalMs = 1000;

static bool loggingActive = false;

static char s_customHeader[160] = {0};

static uint32_t s_flushCount    = 0;
static uint32_t s_flushMaxMs    = 0;
static uint64_t s_flushTotalMs  = 0;
static uint16_t s_qMax = 0;


// --- Sample row queue for non-blocking sampling ---
// Must match LoggingManager's float values[32] size.
constexpr uint16_t SM_MAX_DYNAMIC_COLS   = 32;
constexpr uint16_t SM_SAMPLE_QUEUE_DEPTH = 1024;

struct SampleRow {
    uint64_t ts_ms;
    uint16_t nValues;
    bool     mark;
    float    values[SM_MAX_DYNAMIC_COLS];
};

static SampleRow s_rows[SM_SAMPLE_QUEUE_DEPTH];
static uint16_t  s_qHead  = 0;
static uint16_t  s_qTail  = 0;
static uint16_t  s_qCount = 0;
static uint16_t  s_qMax   = 0;
static uint32_t  s_samplesDropped = 0;

static inline bool queueEmpty() { return s_qCount == 0; }
static inline bool queueFull()  { return s_qCount >= SM_SAMPLE_QUEUE_DEPTH; }

static bool dequeueSample(SampleRow &out) {
    if (queueEmpty()) return false;
    out = s_rows[s_qTail];
    s_qTail = (s_qTail + 1) % SM_SAMPLE_QUEUE_DEPTH;
    --s_qCount;
    return true;
}

//Debug
volatile bool g_sdWriteSinceLastSample = false;  // true if any SD flush since last logged row
bool g_sdTrackEnabled = true;                    // can be toggled off if desired

static bool isSpiBackend()  { return STORAGE_BACKEND == StorageBackendType::SPI_SDFAT; }
static bool isSdioBackend() { return STORAGE_BACKEND == StorageBackendType::SDIO_SDMMC; }

SdFat* StorageManager_getSd() {
    return isSpiBackend() ? &sd : nullptr;
}


static bool logIsOpen() {
    if (isSpiBackend()) {
        return (bool)logFile;
    } else {
        return (bool)logFileMMC;
    }
}

static void logCloseInternal() {
    if (isSpiBackend()) {
        logFile.close();
    } else {
        logFileMMC.close();
    }
}

static size_t logWriteInternal(const void* data, size_t len) {
    if (isSpiBackend()) {
        return logFile.write(data, len);
    } else {
        return logFileMMC.write((const uint8_t*)data, len);
    }
}

static void logPrintlnInternal(const char* s) {
    if (isSpiBackend()) {
        logFile.println(s);
    } else {
        logFileMMC.println(s);
    }
}

static void logFlushInternal() {
    if (isSpiBackend()) {
        logFile.flush();
    } else {
        logFileMMC.flush();
    }
}

bool StorageManager_enqueueSample(uint64_t ts_ms, const float* values, uint16_t nValues, bool mark) {
    if (!values || nValues == 0) return false;

    if (nValues > SM_MAX_DYNAMIC_COLS) {
        nValues = SM_MAX_DYNAMIC_COLS;
    }

    if (queueFull()) {
        // Drop newest; you can change policy later if needed
        ++s_samplesDropped;
        return false;
    }

    SampleRow &row = s_rows[s_qHead];
    row.ts_ms   = ts_ms;
    row.nValues = nValues;
    row.mark    = mark;
    memcpy(row.values, values, nValues * sizeof(float));

    s_qHead = (s_qHead + 1) % SM_SAMPLE_QUEUE_DEPTH;
    ++s_qCount;

    // --- track maximum queue depth ---
    if (s_qCount > s_qMax) {
        s_qMax = s_qCount;
    }

    return true;
}


bool StorageManager_loadTextFile(const char* path, String& out) {
    out = "";

    if (isSpiBackend()) {
        // SPI / SdFat backend
        FsFile f = sd.open(path, O_RDONLY);
        if (!f) {
            Serial.print("[Storage] loadTextFile: SPI open failed for ");
            Serial.println(path);
            return false;
        }

        while (f.available()) {
            int c = f.read();
            if (c < 0) break;
            out += (char)c;
        }
        f.close();
        Serial.print("[Storage] loadTextFile: SPI read OK, bytes=");
        Serial.println(out.length());
        return true;

    } else {
        // SDIO / SD_MMC backend
        File f = SD_MMC.open(path, FILE_READ);
        if (!f) {
            Serial.print("[Storage] loadTextFile: SD_MMC open failed for ");
            Serial.println(path);
            return false;
        }

        while (f.available()) {
            int c = f.read();
            if (c < 0) break;
            out += (char)c;
        }
        f.close();
        Serial.print("[Storage] loadTextFile: SD_MMC read OK, bytes=");
        Serial.println(out.length());
        return true;
    }
}

bool StorageManager_saveTextFile(const char* path, const String& data) {
    const char* cstr = data.c_str();
    size_t len = data.length();

    if (isSpiBackend()) {
        // SPI / SdFat backend
        FsFile f = sd.open(path, O_WRONLY | O_CREAT | O_TRUNC);
        if (!f) {
            Serial.print("[Storage] saveTextFile: SPI open failed for ");
            Serial.println(path);
            return false;
        }
        size_t written = f.write((const uint8_t*)cstr, len);
        f.close();
        Serial.print("[Storage] saveTextFile: SPI wrote bytes=");
        Serial.println(written);
        return (written == len);

    } else {
        // SDIO / SD_MMC backend
        File f = SD_MMC.open(path, FILE_WRITE);  // FILE_WRITE = create/truncate
        if (!f) {
            Serial.print("[Storage] saveTextFile: SD_MMC open failed for ");
            Serial.println(path);
            return false;
        }
        size_t written = f.write((const uint8_t*)cstr, len);
        f.close();
        Serial.print("[Storage] saveTextFile: SD_MMC wrote bytes=");
        Serial.println(written);
        return (written == len);
    }
}

void StorageManager_begin(uint8_t csPin) {
  if (isSpiBackend()) {
    Serial.println("[Storage] begin: starting SPI (SdFat)");

    pinMode(csPin, OUTPUT);
    digitalWrite(csPin, HIGH);
    SPI.end();
    delay(1);

    // VSPI default pins on ESP32: SCK=18, MISO=19, MOSI=23
    SPI.begin(18, 19, 23, csPin);

    SdSpiConfig cfg(csPin, DEDICATED_SPI, SD_SCK_MHZ(25));

    if (!sd.begin(cfg)) {
      Serial.printf("[Storage] sd.begin failed, err=0x%02X data=0x%02X\n",
                    sd.sdErrorCode(), sd.sdErrorData());

      SdSpiConfig slowCfg(csPin, SHARED_SPI, SD_SCK_MHZ(4));
      if (!sd.begin(slowCfg)) {
        Serial.printf("[Storage] retry slow failed, err=0x%02X data=0x%02X\n",
                      sd.sdErrorCode(), sd.sdErrorData());
        return;
      }
    }

    Serial.println("[Storage] SD init OK (SPI_SDFAT).");
  } else {
    Serial.println("[Storage] begin(): backend = SDIO_SDMMC (onboard S3 slot)");
    Serial.println("[Storage] begin (SDIO_SDMMC): starting SD_MMC");

    // SparkFun Thing Plus S3 SDIO pins
    SD_MMC.setPins(38, 34, 39);   // CLK, CMD, D0
    bool ok = SD_MMC.begin("/sdcard", true);  // 1-bit mode

    Serial.print("[Storage] SD_MMC.begin result: ");
    Serial.println(ok ? "OK (true)" : "FAILED (false)");

    if (!ok) {
      Serial.println("[Storage] SD_MMC.begin FAILED, returning");
      return;
    }

    uint8_t cardType = SD_MMC.cardType();
    if (cardType == CARD_NONE) {
      Serial.println("[Storage] No SD card attached (cardType=CARD_NONE)");
      SD_MMC.end();
      return;
    }

    Serial.print("[Storage] SD_MMC cardType = ");
    Serial.println(cardType);

    uint64_t sizeMB = SD_MMC.cardSize() / (1024ULL * 1024ULL);
    Serial.print("[Storage] SD card size: ");
    Serial.print(sizeMB);
    Serial.println(" MB");

    Serial.println("[Storage] SD_MMC.begin OK.");
  }
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

// Reserve e.g. 64 MiB as a single contiguous extent
// (tune via config; must be multiple of 32 KiB for FAT32 cluster alignment)
static bool preallocate(FsFile& f, uint32_t mib) {
  uint64_t bytes = (uint64_t)mib * 1024ULL * 1024ULL;
  // Round up to 32 KiB multiple (common FAT32 cluster)
  const uint32_t cluster = 32 * 1024;
  bytes = ((bytes + cluster - 1) / cluster) * cluster;

  if (!f.preAllocate(bytes)) {
    Serial.println("[Storage] preAllocate failed; continuing without it.");
    return false;
  }
  // Start logical length at 0 but keep space reserved
  if (!f.truncate(0)) {
    Serial.println("[Storage] truncate(0) after preAllocate failed.");
    return false;
  }
  Serial.printf("[Storage] Pre-allocated %lu MiB contiguous.\n", (unsigned long)mib);
  return true;
}

static bool openNewLogFile_SPI(const String& longName) {
  logFile.close();

  // 1) Long name
  logFile = sd.open(longName.c_str(), O_WRONLY | O_CREAT | O_EXCL);
  if (!logFile) {
    Serial.println("[Storage] SPI: long name failed, trying 8.3...");

    // 2) 8.3 short name
    String shortName = make83Name(longName);
    Serial.print("[Storage] SPI: 8.3 candidate: ");
    Serial.println(shortName);

    logFile = sd.open(shortName.c_str(), O_WRONLY | O_CREAT | O_EXCL);
    if (!logFile) {
      Serial.println("[Storage] SPI: 8.3 failed, trying LOGnnnn.CSV...");

      char fallback[20];
      for (int i = 1; i < 10000; i++) {
        snprintf(fallback, sizeof(fallback), "LOG%04d.CSV", i);
        if (!sd.exists(fallback)) {
          logFile = sd.open(fallback, O_WRONLY | O_CREAT | O_EXCL);
          if (logFile) {
            Serial.print("[Storage] SPI: Using fallback: ");
            Serial.println(fallback);
            break;
          }
        }
      }
      if (!logFile) {
        Serial.println("[Storage] SPI: No available filename; giving up.");
        return false;
      }
    } else {
      Serial.print("[Storage] SPI: Using 8.3: ");
      Serial.println(shortName);
    }
  }

  // Preallocate only on SdFat backend
  preallocate(logFile, /*mib=*/64);
  return true;
}

static bool openNewLogFile_SDMMC(const String& longName) {
  logFileMMC.close();

  // Helper lambda for "exclusive" create style.
  auto tryCreate = [](const String& name, File& out) -> bool {
    if (SD_MMC.exists(name)) return false;
    out = SD_MMC.open(name, FILE_WRITE);  // creates new, truncates if existed
    return (bool)out;
  };

  // 1) Long name
  if (tryCreate(longName, logFileMMC)) {
    Serial.print("[Storage] SD_MMC: Using long filename: ");
    Serial.println(longName);
    return true;
  }

  // 2) 8.3 short name
  Serial.println("[Storage] SD_MMC: long name failed, trying 8.3...");
  String shortName = make83Name(longName);
  Serial.print("[Storage] SD_MMC: 8.3 candidate: ");
  Serial.println(shortName);

  if (tryCreate(shortName, logFileMMC)) {
    Serial.print("[Storage] SD_MMC: Using 8.3: ");
    Serial.println(shortName);
    return true;
  }

  // 3) Fallback numbered files
  Serial.println("[Storage] SD_MMC: 8.3 failed, trying LOGnnnn.CSV...");
  char fallback[20];
  for (int i = 1; i < 10000; i++) {
    snprintf(fallback, sizeof(fallback), "LOG%04d.CSV", i);
    if (tryCreate(String(fallback), logFileMMC)) {
      Serial.print("[Storage] SD_MMC: Using fallback: ");
      Serial.println(fallback);
      return true;
    }
  }

  Serial.println("[Storage] SD_MMC: No available filename; giving up.");
  return false;
}

// Start new log file
static void startLog() {
  if (loggingActive) return;

  // Reset non-blocking sample queue
  s_qHead = s_qTail = s_qCount = 0;
  s_samplesDropped = 0;
  s_flushCount = 0;
  s_flushMaxMs = 0;
  s_flushTotalMs = 0;

  String filename = RTCManager_getDateTimeString();
  filename.replace(":", "-");
  filename.replace(" ", "_");
  filename += ".CSV";

  Serial.print("[Storage] Trying to open log: ");
  Serial.println(filename);

  if (isSpiBackend()) {
    // -------- SPI + SdFat path (existing behaviour) --------
    logFile.close();  // harmless if not open

    // 1) Long name
    logFile = sd.open(filename.c_str(), O_WRONLY | O_CREAT | O_EXCL);
    if (!logFile) {
      Serial.println("[Storage] long name failed, trying 8.3...");
      String shortName = make83Name(filename);
      Serial.print("[Storage] 8.3 candidate: ");
      Serial.println(shortName);

      logFile = sd.open(shortName.c_str(), O_WRONLY | O_CREAT | O_EXCL);
      if (!logFile) {
        Serial.println("[Storage] 8.3 failed, trying LOGnnnn.CSV...");
        char fallback[20];
        for (int i = 1; i < 10000; i++) {
          snprintf(fallback, sizeof(fallback), "LOG%04d.CSV", i);
          if (!sd.exists(fallback)) {
            logFile = sd.open(fallback, O_WRONLY | O_CREAT | O_EXCL);
            if (logFile) {
              Serial.print("[Storage] Using fallback: ");
              Serial.println(fallback);
              break;
            }
          }
        }
        if (!logFile) {
          Serial.println("[Storage] No available filename; giving up.");
          return;
        }
      } else {
        Serial.print("[Storage] Using 8.3: ");
        Serial.println(shortName);
      }
    }

    preallocate(logFile, /*mib=*/64);   // optional; SPI only
  } else {
    // -------- SDIO + SD_MMC path (Thing Plus S3 onboard slot) --------
    // StorageManager_begin() already did SD_MMC.begin(), so we *shouldn't*
    // need to call it again. If you really want a safety check, you can
    // leave this block in, but it's usually not necessary.
    /*
    if (!SD_MMC.begin("/sdcard", true)) {
      Serial.println("[Storage] startLog: SD_MMC.begin failed (unexpected)");
      return;
    }
    */

    // Build an ABSOLUTE path: "/YYYY-MM-DD_HH-MM-SS.CSV"
    String path = "/";
    path += filename;   // filename is e.g. "2025-11-30_13-40-54.CSV"

    Serial.print("[Storage] SD_MMC path = ");
    Serial.println(path);

    logFileMMC = SD_MMC.open(path.c_str(), FILE_WRITE);
    if (!logFileMMC) {
      Serial.println("[Storage] startLog: SD_MMC.open failed");
      return;
    }

    // Ensure we start from an empty file
    logFileMMC.seek(0);
  }

  loggingActive = true;

  // --- Build header (shared for both backends) ---
  SensorManager::debugDump("startLog-beforeHeader");

  char header[256];
  SensorManager::buildHeader(header, sizeof(header), RTCManager_isHumanReadable());

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
    Serial.println("[Storage] Warning: header buffer too small for sample_id prefix");
  }

  // Append sd_busy tracking column if space
  const char* extra = ",sd_busy";
  if (strlen(header) + strlen(extra) < sizeof(header)) {
    strcat(header, extra);
  }

  Serial.print("[Storage] Header: ");
  Serial.println(header);

  if (isSpiBackend()) {
    logFile.println(header);
    logFile.flush();
  } else {
    logFileMMC.println(header);
    logFileMMC.flush();
  }

  Serial.println("[Storage] Log file opened successfully.");
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
      StorageManager_logCsvDynamic(row.ts_ms,
                                   row.values,
                                   row.nValues,
                                   row.mark);
  }

  if (bufferIndex > 0) {
    if (isSpiBackend()) {
      logFile.write(buffer, bufferIndex);
    } else {
      logFileMMC.write((const uint8_t*)buffer, bufferIndex);
    }
    bufferIndex = 0;
  }


  // --- append footer line with samplesDropped ---
  // --- NEW: append run stats footer (backend-safe) ---
  if (logIsOpen()) {
      char line[160];

      // Ensure any staged data is on disk before the footer
      logFlushInternal();

      int n;

      n = snprintf(line, sizeof(line), "# run_stats_begin\n");
      if (n > 0) { logWriteInternal(line, (size_t)n); }

      n = snprintf(line, sizeof(line), "# samples_dropped=%lu\n",
                   (unsigned long)s_samplesDropped);
      if (n > 0) { logWriteInternal(line, (size_t)n); }

      n = snprintf(line, sizeof(line), "# queue_max=%u\n", (unsigned)s_qMax);
      if (n > 0) { logWriteInternal(line, (size_t)n); }

      n = snprintf(line, sizeof(line), "# queue_depth=%u\n", (unsigned)SM_SAMPLE_QUEUE_DEPTH);
      if (n > 0) { logWriteInternal(line, (size_t)n); }

      n = snprintf(line, sizeof(line), "# flush_count=%lu\n",
                   (unsigned long)s_flushCount);
      if (n > 0) { logWriteInternal(line, (size_t)n); }

      n = snprintf(line, sizeof(line), "# flush_max_ms=%lu\n",
                   (unsigned long)s_flushMaxMs);
      if (n > 0) { logWriteInternal(line, (size_t)n); }

      double avgFlush = s_flushCount ? (double)s_flushTotalMs / (double)s_flushCount : 0.0;
      n = snprintf(line, sizeof(line), "# flush_avg_ms=%.2f\n", avgFlush);
      if (n > 0) { logWriteInternal(line, (size_t)n); }

      n = snprintf(line, sizeof(line), "# flush_total_ms=%llu\n",
                   (unsigned long long)s_flushTotalMs);
      if (n > 0) { logWriteInternal(line, (size_t)n); }

      n = snprintf(line, sizeof(line), "# buffer_size=%u\n", (unsigned)bufferSize);
      if (n > 0) { logWriteInternal(line, (size_t)n); }

      n = snprintf(line, sizeof(line), "# run_stats_end\n");
      if (n > 0) { logWriteInternal(line, (size_t)n); }

      logFlushInternal();
  }


    
  if (isSpiBackend()) {
    logFile.close();
  } else {
    logFileMMC.close();
  }

  loggingActive = false;
  Serial.printf("[Storage] samplesDropped=%lu\n", (unsigned long)s_samplesDropped);
  Serial.printf("[Storage] flushCount=%lu maxFlushMs=%lu avgFlushMs=%.2f\n", (unsigned long)s_flushCount, (unsigned long)s_flushMaxMs, s_flushCount ? (double)s_flushTotalMs / s_flushCount : 0.0);
  Serial.printf("[Storage] qMax=%u/%u\n", s_qMax, SM_SAMPLE_QUEUE_DEPTH);

  Serial.println("Log file closed.");
  
  // Clear any leftover queued samples (we're no longer logging)
  s_qHead = s_qTail = s_qCount = 0;
}



// helper to format human-readable from epochMs when needed
static void formatEpochMs(char* out, size_t outlen, uint64_t epochMs) {
    time_t sec = (time_t)(epochMs / 1000ULL);
    struct tm tm;
    localtime_r(&sec, &tm);
    unsigned ms = (unsigned)(epochMs % 1000ULL);
    snprintf(out, outlen, "%04d-%02d-%02d %02d:%02d:%02d.%03u",
             tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday,
             tm.tm_hour, tm.tm_min, tm.tm_sec, ms);
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
// Columns: [timestamp, sensor values..., mark, sd_busy]
void StorageManager_logCsvDynamic(uint64_t ts_ms,
                                  const float* values,
                                  uint16_t nValues,
                                  bool mark)
{

    if (!logIsOpen()) {
        Serial.println("[Storage] logCsvDynamic: file not open");
        return;
    }
    if (nValues == 0 || !values) return;

    // 1) Format ONE complete CSV line into a local stack buffer.
    //    Size generously: timestamp + commas + up to ~32 floats + mark + sd_busy + \n
    char line[512];
    int off = 0;

    // Timestamp (human: HH:MM:SS.mmm ; else raw epoch ms)
    if (RTCManager_isHumanReadable()) {
        unsigned long long ms = ts_ms;
        unsigned hh    = (unsigned)((ms / 3600000ULL) % 24ULL);
        unsigned mm    = (unsigned)((ms / 60000ULL)   % 60ULL);
        unsigned ss    = (unsigned)((ms / 1000ULL)    % 60ULL);
        unsigned msecs = (unsigned)(ms % 1000ULL);
        off = snprintf(line, sizeof(line),
                       "%02u:%02u:%02u.%03u",
                       hh, mm, ss, msecs);
    } else {
        off = snprintf(line, sizeof(line),
                       "%llu",
                       (unsigned long long)ts_ms);
    }
    if (off <= 0 || off >= (int)sizeof(line)) {
        return; // format error / overflow
    }

    // Sensor values (comma-separated, fixed precision)
    for (uint16_t i = 0; i < nValues; ++i) {
        int n = snprintf(line + off,
                         sizeof(line) - (size_t)off,
                         ",%.6f",
                         (double)values[i]);
        if (n <= 0 || off + n >= (int)sizeof(line)) {
            return; // overflow guard
        }
        off += n;
    }

    // Mark and sd_busy flag, then newline
    {
        int sdFlag = (g_sdTrackEnabled && g_sdWriteSinceLastSample) ? 1 : 0;
        g_sdWriteSinceLastSample = false;  // consume the flag for this row

        int n = snprintf(line + off,
                         sizeof(line) - (size_t)off,
                         ",%d,%d\n",
                         mark ? 1 : 0,
                         sdFlag);
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
            logWriteInternal(buffer, bufferIndex); // SPI or SD_MMC
            bufferIndex = 0;
        }
    }

    // If the line is larger than the staging buffer, write it directly (rare)
    if (!buffer || len > bufferSize) {
        logWriteInternal(line, len);
        return;
    }

    // 3) Copy the whole line into the staging buffer
    memcpy(&buffer[bufferIndex], line, len);
    bufferIndex += len;

    // 4) No per-line flush here; periodic flush handled in StorageManager_loop()
}


// Background flush
void StorageManager_loop() {
  static unsigned long lastFlush = 0;
  unsigned long now = millis();

  // 1) Drain some queued samples into the CSV staging buffer
  if (loggingActive) {
      const uint8_t MAX_ROWS_PER_LOOP = 8;   // tune as needed
      SampleRow row;
      uint8_t processed = 0;

      while (processed < MAX_ROWS_PER_LOOP && dequeueSample(row)) {
          StorageManager_logCsvDynamic(row.ts_ms,
                                        row.values,
                                        row.nValues,
                                        row.mark);
          ++processed;
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



