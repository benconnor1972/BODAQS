#include "StorageManager.h"
#include "RTCManager.h"
#include "ConfigManager.h"
#include "SensorManager.h"

#include "BoardProfile.h"   // <-- whatever you called it after the namespace rename
#include "SPI.h"

// If you use SD_MMC and SdFat, include the right headers here as you already do elsewhere:
// #include "SD_MMC.h"
// #include "SdFat.h"

extern LoggerConfig g_cfg;   // declared in your .ino

// Storage backend selection now comes from the active board profile.
// No more hard-coded enum/constexpr.
static const board::StorageProfile* s_storage = nullptr;
static const board::SPIProfile*     s_spi     = nullptr;
static const board::LoggerPerfProfile* s_perf = nullptr;

static inline bool isSpiBackend() {
  return s_storage && (s_storage->type == board::StorageType::SPI_SdFat);
}

static inline bool isSdmmcBackend() {
  return s_storage && (s_storage->type == board::StorageType::SDMMC);
}


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


// --- Sample row queue for non-blocking sampling ---
// Must match LoggingManager's float values[32] size.
constexpr uint16_t SM_MAX_DYNAMIC_COLS   = 32;

struct SampleRow {
    uint64_t ts_ms;
    uint16_t nValues;
    bool     mark;
    float    values[SM_MAX_DYNAMIC_COLS];
};

static uint16_t  s_qHead  = 0;
static uint16_t  s_qTail  = 0;
static uint16_t  s_qCount = 0;
static uint16_t  s_qMax   = 0;
static uint32_t  s_samplesDropped = 0;

static SampleRow* s_rows = nullptr;
static uint16_t   s_qCap = 0;

static inline bool queueEmpty() { return s_qCount == 0; }
static inline bool queueFull()  { return (s_qCap != 0) && (s_qCount >= s_qCap); }

static void allocQueue(uint16_t depth) {
  if (depth < 4) depth = 4;
  // cap it to something sane for uint16 math
  if (depth > 4096) depth = 4096;

  delete[] s_rows;
  s_rows = new SampleRow[depth];

  if (!s_rows) {
    Serial.println("[Storage] ERROR: allocQueue failed (OOM)");
    s_qCap = 0;
    s_qHead = s_qTail = s_qCount = 0;
    s_qMax = 0;
    return;
  }

  s_qCap = s_rows ? depth : 0;

  s_qHead = s_qTail = s_qCount = 0;
  s_qMax = 0;
}


static bool dequeueSample(SampleRow &out) {
    if (queueEmpty()) return false;
    if (s_qCap == 0) return false;
    out = s_rows[s_qTail];
    s_qTail = (s_qTail + 1) % s_qCap;
    --s_qCount;
    return true;
}

//Debug
volatile bool g_sdWriteSinceLastSample = false;  // true if any SD flush since last logged row
bool g_sdTrackEnabled = true;                    // can be toggled off if desired

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

    if (s_qCap == 0) {
      ++s_samplesDropped;
      return false;
    }

    SampleRow &row = s_rows[s_qHead];
    row.ts_ms   = ts_ms;
    row.nValues = nValues;
    row.mark    = mark;
    memcpy(row.values, values, nValues * sizeof(float));

    s_qHead = (s_qHead + 1) % s_qCap;
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
        String absPath = (path[0] == '/') ? String(path) : (String("/") + path);
        File f = SD_MMC.open(absPath.c_str(), FILE_READ);
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
  if (!path || !*path) return false;

  const char* cstr = data.c_str();
  const size_t len = data.length();

  if (isSpiBackend()) {
    // -------- SPI / SdFat backend --------
    FsFile f = sd.open(path, O_WRONLY | O_CREAT | O_TRUNC);
    if (!f) {
      Serial.print("[Storage] saveTextFile: SPI open failed for ");
      Serial.println(path);
      return false;
    }

    size_t written = f.write((const uint8_t*)cstr, len);
    f.flush();
    f.close();

    if (written != len) {
      Serial.printf("[Storage] saveTextFile: SPI short write (%u/%u)\n",
                    (unsigned)written, (unsigned)len);
      return false;
    }
    return true;
  }

  // -------- SDMMC backend (SD_MMC / FS) --------
  // Normalize to absolute path (SD_MMC expects paths like "/config.txt")
  String absPath = (path[0] == '/') ? String(path) : (String("/") + path);

  // StorageManager_begin() already did SD_MMC.begin() on this backend.
  // But we still guard against "no card".
  if (SD_MMC.cardType() == CARD_NONE) {
    Serial.println("[Storage] saveTextFile: SD_MMC not mounted / no card");
    return false;
  }

  // Best-effort remove to simulate truncate (FILE_WRITE appends on ESP32)
  // Only attempt remove if it exists, to avoid edge-case FS bugs.
  if (SD_MMC.exists(absPath.c_str())) {
    SD_MMC.remove(absPath.c_str());
  }

  File f = SD_MMC.open(absPath.c_str(), FILE_WRITE);
  if (!f) {
    Serial.print("[Storage] saveTextFile: SD_MMC open failed for ");
    Serial.println(absPath);
    return false;
  }

  size_t written = f.write((const uint8_t*)cstr, len);
  f.flush();
  f.close();

  if (written != len) {
    Serial.printf("[Storage] saveTextFile: SD_MMC short write (%u/%u)\n",
                  (unsigned)written, (unsigned)len);
    return false;
  }

  return true;
}


void StorageManager_begin(const board::BoardProfile& bp) {
  s_storage = &bp.storage;
  s_spi     = &bp.spi;
  s_perf    = &bp.perf;

  // 1) Apply perf knobs early
  if (s_perf) {
    allocQueue(s_perf->queue_depth);
    StorageManager_setBufferSize(s_perf->ring_buffer_bytes);
  }

  if (isSpiBackend()) {
    Serial.println("[Storage] begin: starting SPI (SdFat)");

    const int csPin = s_storage->cs;
    if (csPin < 0) {
      Serial.println("[Storage] SPI backend selected but storage.cs is not set");
      return;
    }

    pinMode(csPin, OUTPUT);
    digitalWrite(csPin, HIGH);
    SPI.end();
    delay(1);

    // Use SPIProfile pins if present, else fall back to common defaults
    const int sck  = (s_spi && s_spi->sck  >= 0) ? s_spi->sck  : 18;
    const int miso = (s_spi && s_spi->miso >= 0) ? s_spi->miso : 19;
    const int mosi = (s_spi && s_spi->mosi >= 0) ? s_spi->mosi : 23;

    SPI.begin(sck, miso, mosi, csPin);

    // Use storage.spi_hz if set
    const uint32_t hz = (s_storage->spi_hz != 0) ? s_storage->spi_hz : 20000000;
    SdSpiConfig cfg(csPin, DEDICATED_SPI, hz);

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
    return;
  }

  if (isSdmmcBackend()) {
    Serial.println("[Storage] begin(): backend = SDMMC (SD_MMC)");
    Serial.println("[Storage] begin (SDMMC): starting SD_MMC");

    // Pins must come from the board profile now
    const int clk = s_storage->sdmmc_clk;
    const int cmd = s_storage->sdmmc_cmd;
    const int d0  = s_storage->sdmmc_d0;

    if (clk < 0 || cmd < 0 || d0 < 0) {
      Serial.println("[Storage] SDMMC backend selected but sdmmc_clk/cmd/d0 not set");
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
        Serial.println("[Storage] SDMMC 4-bit selected but d1/d2/d3 not set");
        return;
      }
      SD_MMC.setPins(clk, cmd, d0, d1, d2, d3);
    }

    const bool ok = SD_MMC.begin("/sdcard", s_storage->sdmmc_1bit);
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
    return;
  }

  Serial.println("[Storage] begin(): storage backend = None");
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

  bool ok = false;

  if (isSpiBackend()) {
    // -------- SPI + SdFat path --------
    logFile.close();  // harmless if not open

    ok = openNewLogFile_SPI(filename);  // handles long name, 8.3, fallback
    if (!ok) {
      Serial.println("[Storage] No available filename; giving up.");
      return;
    }

  } else {
    // -------- SDMMC (SD_MMC) path --------
    // openNewLogFile_SDMMC expects an absolute path
    String path = "/";
    path += filename;

    Serial.print("[Storage] SD_MMC path = ");
    Serial.println(path);

    ok = openNewLogFile_SDMMC(path);
    if (!ok) {
      Serial.println("[Storage] startLog: SD_MMC open failed");
      return;
    }

    // NOTE: openNewLogFile_SDMMC already truncates/creates appropriately.
    // No need for logFileMMC.seek(0) here unless you specifically want it.
  }

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
  loggingActive = true;

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

      n = snprintf(line, sizeof(line), "# queue_depth=%u\n", (unsigned)s_qCap);
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
  Serial.printf("[Storage] qMax=%u/%u\n", s_qMax, s_qCap);

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



