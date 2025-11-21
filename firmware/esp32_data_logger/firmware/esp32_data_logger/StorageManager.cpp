#include "StorageManager.h"
#include "RTCManager.h"
#include "ConfigManager.h"
#include "SensorManager.h"
#include "SPI.h"

extern LoggerConfig g_cfg;   // declared in your .ino

static SdFat sd;
SdFat* StorageManager_getSd() {
  return &sd;
}

static FsFile logFile;

static char* buffer = nullptr;
static size_t bufferSize = 0;
static size_t bufferIndex = 0;

static unsigned int sampleRateHz = 1;
static unsigned long sampleIntervalMs = 1000;

static bool loggingActive = false;

static char s_customHeader[160] = {0};


// Begin SD
void StorageManager_begin(uint8_t csPin) {
  Serial.println("[Storage] begin: starting SPI");

  // Make CS sane and release any old SPI state
  pinMode(csPin, OUTPUT);
  digitalWrite(csPin, HIGH);
  SPI.end();
  delay(1);

  // VSPI default pins on ESP32: SCK=18, MISO=19, MOSI=23
  SPI.begin(18, 19, 23, csPin);

  // If anything else may share the bus (display, etc.), use SHARED.
  // Also start conservative at 10 MHz; drop to 4 MHz if needed.
  SdSpiConfig cfg(csPin, DEDICATED_SPI, SD_SCK_MHZ(25));

  if (!sd.begin(cfg)) {
    Serial.printf("[Storage] sd.begin failed, err=0x%02X data=0x%02X\n",
                  sd.sdErrorCode(), sd.sdErrorData());

    // Try a second attempt slower (sometimes helps marginal cards/wiring)
    SdSpiConfig slowCfg(csPin, SHARED_SPI, SD_SCK_MHZ(4));
    if (!sd.begin(slowCfg)) {
      Serial.printf("[Storage] retry slow failed, err=0x%02X data=0x%02X\n",
                    sd.sdErrorCode(), sd.sdErrorData());
      return;
    }
  }

  Serial.println("[Storage] SD init OK.");
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

// Start new log file
static void startLog() {
  if (loggingActive) return;

  String filename = RTCManager_getDateTimeString();
  filename.replace(":", "-");
  filename.replace(" ", "_");
  filename += ".CSV";

  Serial.print("[Storage] Trying to open (long): ");
  Serial.println(filename);

  // 1) Long name
  logFile.close();  // harmless if not open
  logFile = sd.open(filename.c_str(), O_WRONLY | O_CREAT | O_EXCL);
  if (!logFile) {
    Serial.println("[Storage] long name failed, trying 8.3...");

    // 2) 8.3 short name
    String shortName = make83Name(filename);
    Serial.print("[Storage] 8.3 candidate: ");
    Serial.println(shortName);

    logFile = sd.open(shortName.c_str(), O_WRONLY | O_CREAT | O_EXCL);
    if (!logFile) {
      Serial.println("[Storage] 8.3 failed, trying LOGnnnn.CSV...");

      // 3) Fallback numbered files
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

  preallocate(logFile, /*mib=*/64);   // or from config (32–256 MiB typical)

  loggingActive = true;

  // (extra visibility)
  SensorManager::debugDump("startLog-beforeHeader");

  char header[256];
  SensorManager::buildHeader(header, sizeof(header), RTCManager_isHumanReadable());
  Serial.print("[Storage] Header: ");
  Serial.println(header);

  logFile.println(header);
  logFile.flush();
  Serial.println("[Storage] Log file opened successfully.");
}

void StorageManager_startLog() {
  startLog();
}


// Stop log
void StorageManager_stopLog() {
    if (!loggingActive) return;

    if (bufferIndex > 0) {
        logFile.write(buffer, bufferIndex);
        bufferIndex = 0;
    }
    logFile.close();
    loggingActive = false;
    Serial.println("Log file closed.");
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

void StorageManager_logRecordWithTs(uint64_t epochMs,
    float pot1, float pot2,
    float strain, float accelX, float accelY, float accelZ, float accelTemp,
    bool mark)
{
    if (!loggingActive) startLog();
;

    char line[160];

    if (RTCManager_isHumanReadable()) {
        char ts[40];
        formatEpochMs(ts, sizeof(ts), epochMs);
        snprintf(line, sizeof(line),
            "%s,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%d\n",
            ts, pot1, pot2, strain, accelX, accelY, accelZ, accelTemp,
            mark ? 1 : 0);
    } else {
        // raw epoch ms, safe 64-bit print
        snprintf(line, sizeof(line),
            "%llu,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%d\n",
            (unsigned long long)epochMs,
            pot1, pot2, strain, accelX, accelY, accelZ, accelTemp,
            mark ? 1 : 0);
    }

    size_t len = strlen(line);

    // If the line will not fit in the remaining staging buffer space,
    // flush the buffer first, then re-stage the entire line.
    if (buffer && (bufferIndex + len > bufferSize)) {
        if (bufferIndex) {
            logFile.write(buffer, bufferIndex);
            bufferIndex = 0;
        }
    }

    // If the line is larger than the staging buffer, write it directly (rare)
    if (!buffer || len > bufferSize) {
        logFile.write(line, len);
        return;
    }

    // Copy the whole line into the staging buffer; periodic flush is handled
    // in StorageManager_loop().
    memcpy(&buffer[bufferIndex], line, len);
    bufferIndex += len;
}


// Add record //**I think this is now redundant
void StorageManager_logRecord(float pot1, float pot2, float strain,
                              float accelX, float accelY, float accelZ,
                              float accelTemp, bool mark) {
    if (!loggingActive) startLog();

    char line[160];

    if (RTCManager_isHumanReadable()) {
        // human-readable with milliseconds
        String ts = RTCManager_getFastTimestamp(); // your formatted string
        snprintf(line, sizeof(line),
            "%s,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%d\n",
            ts.c_str(),
            pot1, pot2, strain, accelX, accelY, accelZ, accelTemp,
            mark ? 1 : 0);
    } else {
        // raw epoch ms, printed safely as 64-bit
        uint64_t ms = RTCManager_getEpochMs();
        snprintf(line, sizeof(line),
            "%llu,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%d\n",
            (unsigned long long)ms,
            pot1, pot2, strain, accelX, accelY, accelZ, accelTemp,
            mark ? 1 : 0);
    }

    size_t len = strlen(line);

    // If the line will not fit in the remaining staging buffer space,
    // flush the buffer first, then re-stage the entire line.
    if (buffer && (bufferIndex + len > bufferSize)) {
        if (bufferIndex) {
            logFile.write(buffer, bufferIndex);
            bufferIndex = 0;
        }
    }

    // If the line is larger than the staging buffer, write it directly (rare)
    if (!buffer || len > bufferSize) {
        logFile.write(line, len);
        return;
    }

    // Copy the whole line into the staging buffer; periodic flush is handled
    // in StorageManager_loop().
    memcpy(&buffer[bufferIndex], line, len);
    bufferIndex += len;
}

void StorageManager_setCustomHeader(const char* csv) {
    if (!csv || !csv[0]) {
        s_customHeader[0] = '\0';
        return;
    }
    strncpy(s_customHeader, csv, sizeof(s_customHeader) - 1);
    s_customHeader[sizeof(s_customHeader) - 1] = '\0';
}

void StorageManager_logCsvDynamic(uint64_t ts_ms, const float* values, uint16_t nValues, bool mark) {
  // Ensure the log is started/open (creates file + header)
  if (!loggingActive) startLog();
  if (!logFile) {
    Serial.println("[Storage] logCsvDynamic: file not open");
    return;
  }

  // 1) Format ONE complete CSV line into a local stack buffer.
  //    Size generously: timestamp + commas + up to ~32 floats + mark + \n
  char line[512];
  int off = 0;

  // Timestamp (human: HH:MM:SS.mmm ; else raw epoch ms)
  if (RTCManager_isHumanReadable()) {
    unsigned long long ms  = ts_ms;
    unsigned hh      = (unsigned)((ms / 3600000ULL) % 24ULL);
    unsigned mm      = (unsigned)((ms / 60000ULL)   % 60ULL);
    unsigned ss      = (unsigned)((ms / 1000ULL)    % 60ULL);
    unsigned msecs   = (unsigned)(ms % 1000ULL);
    off = snprintf(line, sizeof(line), "%02u:%02u:%02u.%03u", hh, mm, ss, msecs);
  } else {
    off = snprintf(line, sizeof(line), "%llu", (unsigned long long)ts_ms);
  }
  if (off <= 0 || off >= (int)sizeof(line)) return; // format error/overflow

  // Values (comma-separated, fixed precision)
  for (uint16_t i = 0; i < nValues; ++i) {
    int n = snprintf(line + off, sizeof(line) - (size_t)off, ",%.6f", (double)values[i]);
    if (n <= 0 || off + n >= (int)sizeof(line)) return; // overflow guard
    off += n;
  }

  // Mark and newline
  {
    int n = snprintf(line + off, sizeof(line) - (size_t)off, ",%d\n", mark ? 1 : 0);
    if (n <= 0 || off + n >= (int)sizeof(line)) return;
    off += n;
  }

  // 2) Stage the FULL line atomically into the RAM buffer.
  const size_t len = (size_t)off;

  // If the line won't fit, flush the staging buffer first (write between lines)
  if (buffer && (bufferIndex + len > bufferSize)) {
    if (bufferIndex > 0) {
      logFile.write(buffer, bufferIndex);   // writes only whole, previously staged lines
      bufferIndex = 0;
    }
  }

  // If the line is larger than the staging buffer, write it directly (rare)
  if (!buffer || len > bufferSize) {
    logFile.write(line, len);
    return;
  }

  // 3) Copy the whole line into the staging buffer
  memcpy(&buffer[bufferIndex], line, len);
  bufferIndex += len;

  // 4) (No per-line flush; periodic flush handled in StorageManager_loop)
}




// Background flush
void StorageManager_loop() {
    static unsigned long lastFlush = 0;
    unsigned long now = millis();

    // Flush only if a second has passed, or if buffer is almost full
    if (loggingActive && bufferIndex > 0) {
        if ((now - lastFlush >= 1000) || (bufferIndex > bufferSize * 3 / 4)) {
            logFile.write(buffer, bufferIndex);
            bufferIndex = 0;
            lastFlush = now;
            Serial.println("Buffer flushed to SD");
        }
    }
}
