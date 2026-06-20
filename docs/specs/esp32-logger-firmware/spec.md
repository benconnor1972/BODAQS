# Specification: ESP32 Logger Firmware

**Created**: 2026-05-11
**Status**: Draft (Backfilled)
**Design Docs**: `docs/design/esp32-logger-firmware.md`

> **Backfilled** — this spec documents an existing system as it currently
> behaves. It is not a forward specification. Code is the source of truth.

## Scope

**What part of the design is being implemented:**

This spec covers the entire ESP32 Logger Firmware sphere: all 109 C++ source
files in `firmware/src/`, the board profiles in `firmware/src/BoardProfile.cpp`,
the build configuration in `firmware/platformio.ini`, and the board variants in
`firmware/variants/`. This includes the sensor subsystem, storage & logging,
upload & Wi-Fi, UI & menu, and system & config components.

**Out of scope for this spec:**

- The desktop import agent (`import-manager/`) — separate sphere.
- The Python analysis package (`analysis/`) — separate sphere.
- Hardware design assets (`hardware/`, `mechanical/`) — not firmware.
- The `bodocs/` documentation site — not source code.
- USB serial download (parked, not in active code path).

## Design Context

### Relevant Invariants

- **INV-1**: Logging and web server are mutually exclusive.
- **INV-2**: Logging and upload mode are mutually exclusive.
- **INV-3**: Mark events only recorded while logging active.
- **INV-4**: `sample_id` first column, `mark` last column.
- **INV-5**: Filename `YYMMDD_HHMMSS.<ext>` or `LOGnnnn.<ext>` fallback.
- **INV-6**: Sensor construction order deterministic (UI indices match config).
- **INV-7**: Missing transforms fall back to identity.
- **INV-8**: Transform identity by `meta.id`, not filename.
- **INV-9**: Config writes blocked while logging or upload mode active.
- **INV-10**: ZIP archive generated after CSV+JSON closed; loose sources removed.
- **INV-11**: `.bdq` sessions are self-contained (no sidecar/ZIP).
- **INV-12**: Upload API session endpoints return 409 when upload mode inactive.
- **INV-13**: Session cleanup requires prior acknowledgement.
- **INV-14**: Sample task pinned to core 0 (`xCoreID=0`), priority 3. *(unverified intent — needs review: code comment claims core 1)*
- **INV-15**: Grid-aligned timestamps: `ts = t0 + count * interval`.
- **INV-16**: Queue overflow drops sample, increments `samplesDropped`.
- **INV-17**: `logger_id` sanitized from `logger_name`.
- **INV-18**: `session_id` = `<logger_id>__<session_stem>`.
- **INV-19**: mDNS station-only, port 80.
- **INV-20**: AP mode no mDNS; identity via `/api/v1/device`.
- **INV-21**: Menu modal ownership via `UI::setModal`.
- **INV-22**: Human timestamps `HH:MM:SS.mmm`; fast timestamps epoch ms. *(legacy behavior — may change)*
- **INV-23**: Atomic config save (`.tmp` → `.bak` → final).
- **INV-24**: SD removal stops logging.
- **INV-25**: Ack index at `/upload_index.ndjson`.
- **INV-26**: Battery/rail fault refuses logging.
- **INV-27**: Wi-Fi suspended on logging start, resumed on stop.
- **INV-28**: Sample rate capped by synchronous sensors and external ADCs.

### Relevant Contracts

- BDQ v1 binary format: `docs/firmware/BDQ_v1_format.md`
- Wi-Fi Upload API v1: `docs/firmware/WiFi_Upload_API_v1.md`
- SD Card Architecture: `docs/firmware/SD_Card_Architecture.md`
- Transform Framework v2: `docs/firmware/BODAQS_Transforms_Framework_v2.md`
- Firmware Versioning Policy: `docs/firmware/Firmware_Versioning_Policy.md`

### Relevant Failure Modes

See design doc Failure Modes table (35 modes). Key ones this spec must
document: SD missing/removed, queue overflow, RTC invalid, transform
missing/invalid, calibration degenerate span, I2C read failure, battery low,
config save failure, metadata/ZIP failure, BDQ writer failure, ack index
corrupt, partial cleanup failure, power loss mid-session.

---

## Component Specifications

### BoardProfile / BoardSelect — `firmware/src/BoardProfile.{h,cpp}`, `BoardSelect.{h,cpp}`

**Design doc reference:** Component Contracts → BoardProfile / BoardSelect
**Depends on:** None (foundational)

#### Interface Signatures

```cpp
namespace board {
  const BoardProfile& GetBoardProfile(BoardID id);
  const BoardProfile& GetBoardProfileByName(const char* name);
  extern const BoardProfile* gBoard;
  void SelectBoard(BoardID id);
  int FindButtonIndexById(const char* id);
  void DumpActiveBoardProfile();
  void DumpActiveBoardButtons();
}
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `BoardID` | Must be one of the enum values | Unknown → falls back to `ThingPlusS3_BODAQS_4_D` |
| `name` | Case-sensitive exact match to profile `.name` | No match → falls back to 4D |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| Null `gBoard` | `SelectBoard` not called or failed | None | `main.cpp` halts in infinite loop |

#### Acceptance Criteria

- **AC1:** Given a valid `BoardID`, when `SelectBoard` is called, then `gBoard` points to the matching static `BoardProfile`.
- **AC2:** Given `BODAQS_V1RC3`, when `GetBoardProfile` is called, then the returned profile has `RV3028` RTC, 2 external ADS1220 ADCs, and 4-bit SDMMC.
- **AC3:** Given an unknown board name, when `GetBoardProfileByName` is called, then the 4D profile is returned.

#### Integration Points

| Dependency | Call | Expected response | Error handling |
|------------|------|-------------------|----------------|
| All managers | `board::gBoard->*` | Read-only profile fields | None (gBoard is valid after boot) |

#### Performance Constraints

| Metric | Target | How verified |
|--------|--------|--------------|
| Boot selection | < 1 ms | Static struct lookup |

---

### ConfigManager — `firmware/src/ConfigManager.{h,cpp}`

**Design doc reference:** Component Contracts → ConfigManager
**Depends on:** BoardProfile, StorageManager (for file I/O)

#### Interface Signatures

```cpp
class ConfigManager {
public:
  static void begin(const char* filename);
  static bool load(LoggerConfig& cfg);
  static bool save(const LoggerConfig& cfg);
  static const LoggerConfig& get();
  static String loggerId();
  static String loggerId(const LoggerConfig& cfg);

  static uint8_t sensorCount();
  static bool getSensorSpec(uint8_t i, SensorSpec& out);
  static int8_t findSensorByName(const char* name);

  static bool getParam(uint8_t index, const char* key, String& out);
  static bool getIntParam(uint8_t index, const char* key, long& out);
  static bool getFloatParam(uint8_t index, const char* key, double& out);
  static bool getBoolParam(uint8_t index, const char* key, bool& out);
  static bool saveSensorParamByName(const char* sensorName, const char* key, const String& value);
  static bool saveSensorParamByIndex(uint8_t index, const char* key, const String& value);
  static bool appendSensor(SensorType type, const char* name);
  static bool deleteSensorByIndex(uint8_t index);

  static bool loadCalibration(const char* sensorName, Calibration& out);
  static bool saveCalibration(const char* sensorName, const Calibration& cal);
  static void setSampleRateHz(uint16_t hz, bool persist = true);
  static void setLogFormat(LogFormat format, bool persist = true);
  static void setWifiMode(WiFiMode mode, bool persist = true);
  static bool parseLogFormat(const char* text, LogFormat& out);
  static bool parseWifiMode(const char* text, WiFiMode& out);
  static bool parseLine(char* line, LoggerConfig& cfg);
};
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `filename` | Must be absolute path starting with `/` | Load fails |
| Sensor index | Must be < `sensorCount()` | Returns false |
| Param key | Case-insensitive match | Returns false if not found |
| `logger_name` | Sanitized to `logger_id`: trim, replace unsafe chars with `_` | Empty → `BODAQS` |
| `log_format` | One of `bodaqs_standard`, `syn_bike_raw`, `bodaqs_compact_binary` | Unknown → default |
| `wifi_mode` | `station` or `access_point` | Unknown → default |
| Sensor count | ≤ `MAX_SENSORS` (16) | Extra sensors dropped |
| ParamStore | ≤ 32 keys per sensor | Extra pairs dropped silently |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| Load failure | File missing or unreadable | None | Use defaults |
| Save failure | SD write error, short write | None | Retry or report |
| Sensor not found | Index out of range | None | Treat as empty |

#### Acceptance Criteria

- **AC1:** Given a valid `loggercfg.txt`, when `load` is called, then all globals and sensor specs are populated.
- **AC2:** Given `logger_name=Prototype F`, when `loggerId` is called, then returns `Prototype_F`.
- **AC3:** Given `logger_name=  ` (whitespace only), when `loggerId` is called, then returns `BODAQS`.
- **AC4:** Given logging is active, when a config save is attempted via web UI, then it is rejected.
- **AC5:** Given a config save, when SD write succeeds, then the file is written atomically (`.tmp` → rename).

#### Integration Points

| Dependency | Call | Expected response | Error handling |
|------------|------|-------------------|----------------|
| `StorageManager` | `loadTextFile`/`saveTextFile` | `bool` | Load failure → defaults |
| `SensorManager` | `sensorCount`/`getSensorSpec` | Spec copy | None |

---

### SensorManager — `firmware/src/SensorManager.{h,cpp}`

**Design doc reference:** Component Contracts → SensorManager
**Depends on:** ConfigManager, SensorRegistry, Sensor, TransformRegistry

#### Interface Signatures

```cpp
namespace SensorManager {
  void begin(const LoggerConfig* cfg);
  void buildSensorsFromConfig(const LoggerConfig& cfg);
  void finalizeBegin();
  void applyConfig(const LoggerConfig& cfg);
  void loop();
  void onLoggingStart();
  void onLoggingStop();

  void registerSensor(Sensor* s);
  uint8_t count();
  uint8_t activeCount();
  Sensor* at(uint8_t i);
  Sensor* get(uint8_t i);

  bool getMuted(uint8_t index, bool& outMuted);
  bool setMuted(uint8_t index, bool muted);

  uint16_t dynamicColumnCount();
  uint16_t synchronousMaxSampleRateHz();
  void buildHeader(char* out, size_t n, bool humanTs);
  void sampleValues(float* out, uint16_t maxOut, uint16_t& written);
  uint16_t describeSensorColumns(SensorColumnDescriptor* out, uint16_t maxOut);
  bool describeSensorColumnAt(uint16_t columnIndex, SensorColumnDescriptor& out);
  uint16_t describeSensors(SensorMetadataDescriptor* out, uint16_t maxOut);
  uint16_t describeSensorColumnRawFlags(bool* out, uint16_t maxOut);
  uint16_t readSuspensionPreview(PreviewMode mode, PreviewValue* out, uint16_t maxOut);
  bool resolveSynBikeRawBindings(SynBikeRawBindings& out);
  bool gpsStatus(SensorGpsStatus& out);
}
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| Sensor index | < `count()` | Returns false/nullptr |
| Column count | ≤ `LoggerLimits::kMaxDynamicColumns` (64) | Excess not described |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| Unknown sensor type | Config has unrecognized type | Warning logged | Skip sensor |
| Out of range | Index ≥ count | false/nullptr | Treat as absent |

#### Acceptance Criteria

- **AC1:** Given 2 configured sensors, when `buildSensorsFromConfig` is called, then `count()` returns 2 and indices match config order.
- **AC2:** Given a muted sensor, when `sampleValues` is called, then that sensor's columns are not included in output.
- **AC3:** Given a sensor with `maxSampleRateHz()=100`, when `synchronousMaxSampleRateHz` is called, then returns 100.

---

### Sensor (abstract) — `firmware/src/Sensor.{h,cpp}`

**Design doc reference:** Component Contracts → Sensor
**Depends on:** TransformRegistry, OutputTransform, Calibration

#### Interface Signatures

```cpp
class Sensor {
public:
  virtual void begin() = 0;
  virtual void loop() {}
  virtual void applyConfig(const LoggerConfig&) {}
  virtual void onLoggingStart() {}
  virtual void onLoggingStop() {}

  virtual bool muted() const = 0;
  virtual void setMuted(bool m) = 0;
  virtual void setIncludeRaw(bool b);
  virtual void setOutputUnitsLabel(const char* u);

  virtual SensorSampleMode sampleMode() const { return SensorSampleMode::Synchronous; }
  virtual uint16_t maxSampleRateHz() const { return 0; }
  virtual uint8_t columnCount() const = 0;
  virtual void getColumnName(uint8_t idx, char* out, size_t cap) const = 0;
  virtual void sampleValues(float* out, uint8_t max) = 0;
  virtual bool describeColumn(uint8_t idx, SensorColumnDescriptor& out) const;
  virtual bool describeSensorMetadata(SensorMetadataDescriptor& out) const;

  virtual OutputMode outputMode() const;
  virtual void setOutputMode(OutputMode);
  virtual OutputConfig outputConfig() const;
  virtual void setOutputConfig(const OutputConfig& oc);

  virtual bool beginCalibration(CalMode);
  virtual bool updateCalibration(int32_t);
  virtual bool finishCalibration(bool);
  virtual CalPhase currentCalPhase() const;
  virtual CalMask allowedCalMask() const;

  void setSelectedTransformId(const String& id);
  const String& selectedTransformId() const;
  void attachTransform(const TransformRegistry& reg);
  const char* unitsLabel() const;

protected:
  float applyTransform(float x) const;
};
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `OutputMode` | `RAW`, `LINEAR`, `POLY`, `LUT` | Default `RAW` |
| Transform ID | Trimmed; extension stripped (`wheel_mm.lut` → `wheel_mm`) | Identity fallback |
| Calibration span | `r1 != r0` | `recompute()` returns false |

#### Acceptance Criteria

- **AC1:** Given `OutputMode::RAW`, when `sampleValues` is called, then raw counts are emitted.
- **AC2:** Given no transform attached, when `applyTransform(x)` is called, then returns `x` (identity).
- **AC3:** Given `output_id` not matching any loaded transform, when `attachTransform` is called, then identity transform is used.

---

### SensorRegistry — `firmware/src/SensorRegistry.{h,cpp}`

**Design doc reference:** Component Contracts → SensorRegistry
**Depends on:** Sensor, SensorParams, SensorTypes

#### Interface Signatures

```cpp
namespace SensorRegistry {
  bool registerType(SensorType t, const char* key, const char* label,
                    const ParamDef* (*defs)(size_t&),
                    Sensor* (*create)(const char*, const ParamPack&, bool));
  bool registerType(SensorType t, const char* key, const char* label,
                    const ParamDef* (*defs)(size_t&),
                    Sensor* (*create)(const char*, const ParamPack&, bool),
                    CalModeMask supportedMask);
  const SensorTypeInfo* lookup(SensorType t);
  const char* typeKey(SensorType t);
  const char* typeLabel(SensorType t);
  CalModeMask supportedCalMask(SensorType t);
}
```

#### Acceptance Criteria

- **AC1:** Given `SensorType::AnalogPot`, when `lookup` is called, then returns info with key `analog_pot` and `CAL_ZERO | CAL_RANGE`.
- **AC2:** Given `SensorType::DANF10NGps`, when `lookup` is called, then returns info with `SensorSampleMode::Asynchronous`.

---

### TransformRegistry — `firmware/src/TransformRegistry.{h,cpp}`

**Design doc reference:** Component Contracts → TransformRegistry
**Depends on:** OutputTransform, FS (SD_MMC)

#### Interface Signatures

```cpp
class TransformRegistry {
public:
  bool loadForSensor(const String& sensorId, fs::FS& fs);
  bool reload(const String& sensorId, fs::FS& fs);
  const OutputTransform* get(const String& sensorId, const String& id) const;
  OutputTransform* identity();
  std::vector<TransformMeta> list(const String& sensorId) const;
};
extern TransformRegistry gTransforms;
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| Sensor directory | `/cal/<sensorId>/` must exist | Skip without error |
| File extensions | `.lut.csv`, `.poly.json`, `.poly.cfg`, `.poly.txt`, `.poly` | Unknown → skipped |
| `meta.id` | Must be non-empty | File not indexed |
| ID collision | Last-loaded wins | No warning |

#### Acceptance Criteria

- **AC1:** Given `/cal/front_shock/` does not exist, when `loadForSensor` is called, then returns true (skip) and no transforms indexed.
- **AC2:** Given two transform files with the same `meta.id`, when loaded, then the second overwrites the first.
- **AC3:** Given `output_id=wheel_mm` with no matching transform, when `get` is called, then returns nullptr; caller uses identity.

---

### StorageManager — `firmware/src/StorageManager.{h,cpp}`

**Design doc reference:** Component Contracts → StorageManager
**Depends on:** BoardProfile, ConfigManager, SensorManager, RTCManager, BdqLogWriter, LogMetadataWriter, ZipArchiveWriter, LoggingManager, UI

#### Interface Signatures

```cpp
void StorageManager_begin(const board::BoardProfile& bp);
void StorageManager_setSampleRate(unsigned int hz);
void StorageManager_setBufferSize(size_t bytes);
unsigned long StorageManager_getSampleIntervalMs();
bool StorageManager_startLog();
void StorageManager_stopLog();
void StorageManager_loop();
void StorageManager_setCustomHeader(const char* csv);
bool StorageManager_logCsvDynamic(uint32_t sample_id, uint64_t ts_ms,
                                   const float* values, uint16_t n, bool mark);
bool StorageManager_enqueueSample(uint32_t sample_id, uint64_t ts_ms,
                                   const float* values, uint16_t n, bool mark);
bool StorageManager_loadTextFile(const char* path, String& out);
bool StorageManager_saveTextFile(const char* path, const String& data);
bool StorageManager_cardDetected();
bool StorageManager_isMounted();
bool StorageManager_readyForLogging();
bool StorageManager_remountIfPresent();
const char* StorageManager_lastStatus();
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| Sample rate | > 0; clamped to 1 if 0 | None |
| Queue depth | 4–4096; from board perf profile | Alloc failure → status "sample queue OOM" |
| Write buffer | ≥ 1024 bytes; halved on alloc failure | Direct writes if alloc fails |
| Log filename | `YYMMDD_HHMMSS.<ext>` or `LOGnnnn.<ext>` | Numbered fallback 1–9999 |
| Drain budget | 5 ms per loop iteration | Remaining samples deferred |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| Mount failed | SD_MMC.begin returns false | `lastStatus="mount failed"` | Refuse logging |
| No card | `cardType == CARD_NONE` | `lastStatus="no card"` | Refuse logging |
| Queue full | `s_qCount >= s_qCap` | `samplesDropped++` | Sample dropped |
| Log open fail | File create fails | Toast "SD open fail" | Start returns false |
| Buffer OOM | `new (nothrow)` returns nullptr | Status "write buffer OOM" | Direct writes |

#### Acceptance Criteria

- **AC1:** Given SD card present, when `StorageManager_begin` is called, then `isMounted()` returns true.
- **AC2:** Given logging active and queue full, when `enqueueSample` is called, then returns false and `samplesDropped` increments.
- **AC3:** Given `bodaqs_standard` format and logging stopped, when `stopLog` is called, then JSON metadata is written, ZIP created, and loose CSV/JSON removed.
- **AC4:** Given `bodaqs_compact_binary` format and logging stopped, when `stopLog` is called, then `.bdq` final summary chunk is written and no sidecar/ZIP generated.
- **AC5:** Given card-detect pin wired and card removed during logging, when `loop` detects absence, then logging stops and SD unmounts.
- **AC6:** Given `saveTextFile` called, when write succeeds, then file is written atomically via `.tmp` → rename.

#### Performance Constraints

| Metric | Target | How verified |
|--------|--------|--------------|
| Drain budget | ≤ 5 ms per loop | `micros()` timing in loop |
| Flush interval | Every 5 s or 90% buffer full | `millis()` check in loop |
| Queue depth | 256 (4D/4F/V1RC3) | Board perf profile |

---

### LoggingManager — `firmware/src/LoggingManager.{h,cpp}`

**Design doc reference:** Component Contracts → LoggingManager
**Depends on:** ConfigManager, StorageManager, SensorManager, WebServerManager, WiFiManager, UploadModeManager, PowerManager, RTCManager, AnalogInputManager, IndicatorManager, UI

#### Interface Signatures

```cpp
namespace LoggingManager {
  void begin(const LoggerConfig* cfg);
  bool start();
  void stop();
  bool isRunning();
  void loop();
  void setSampleRateHz(uint16_t hz);
  void mark();
}
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| Start precondition | Upload mode off, battery OK, SD ready | Refuse with toast |
| Sample rate | Snapped to `Rates::kList`; capped by sync sensors | Capped rate applied |
| Mark queue | 8 slots; overflow drops | Mark lost |
| Task stack | 4096 bytes | Watchdog if exceeded |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| Upload mode active | `start` called | Toast "Upload mode" | Exit upload mode first |
| Battery low | `canStartLogging()` false | Toast "Batt Low" | Charge battery |
| SD missing | `readyForLogging()` false | Toast "SD missing" | Insert card |
| Log open fail | `StorageManager_startLog` false | Toast "SD open fail" | Check SD |

#### Acceptance Criteria

- **AC1:** Given upload mode active, when `start` is called, then returns false and toast "Upload mode" shown.
- **AC2:** Given logging starts, when web server was running, then web server stopped and Wi-Fi suspended.
- **AC3:** Given sample rate 500 Hz but sensor cap 100 Hz, when `start` is called, then effective rate is 100 Hz.
- **AC4:** Given `mark()` called while running, when next sample is taken, then mark flag is true for that sample.
- **AC5:** Given logging stopped, when `stop` is called, then Wi-Fi resumed and LED turned off.

#### Performance Constraints

| Metric | Target | How verified |
|--------|--------|--------------|
| Sample task priority | 3 (pinned to core 0) | `xTaskCreatePinnedToCore` |
| Grid alignment | `ts = t0 + count * interval` | `sampleOnce_` |
| Late tick detection | Lag ≥ 1 ms | `s_lateTicks++` |

---

### BdqLogWriter — `firmware/src/BdqLogWriter.{h,cpp}`

**Design doc reference:** Component Contracts → BdqLogWriter
**Depends on:** SensorManager, FirmwareInfo, FS

#### Interface Signatures

```cpp
namespace BdqLogWriter {
  bool begin(File& file, const BdqLogSessionInfo& info);
  bool writeSample(uint32_t sampleId, uint64_t tsMs,
                   const float* values, uint16_t nValues, bool mark);
  bool flushDataChunk();
  void flushFile();
  bool end(const BdqLogEndInfo& info);
  void reset();
  bool isActive();
  uint16_t frameSizeBytes();
  uint16_t pendingFrameCount();
  uint32_t samplesWritten();
  uint32_t dataChunksWritten();
}
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| File magic | `BDQLOG\0\1` | Parser rejects mismatch |
| Chunk magic | `BDQC` | Parser stops |
| Format major | 1 | Parser rejects other |
| CRC32 | IEEE reflected, poly `0xEDB88320` | Parser stops on mismatch |
| Column count | ≤ 32 emitted | Parsers trust schema |
| Frame size | Fixed per file | Mismatch = parse error |
| Storage type | `uint16`, `int32`, `uint32`, `float32` | Per column |

#### Acceptance Criteria

- **AC1:** Given `begin` called, when file is written, then starts with 32-byte file header (magic + format + timestamp).
- **AC2:** Given samples written, when `flushDataChunk` is called, then data chunk has 20-byte payload header + frames.
- **AC3:** Given NaN or infinity in a value, when frame is packed, then `SAMPLE_FLAG_SENSOR_ERR` bit set.
- **AC4:** Given `end` called on clean shutdown, then final summary chunk written with `samples_written`, `data_chunks_written`, `samples_dropped`.

---

### LogMetadataWriter — `firmware/src/LogMetadataWriter.{h,cpp}`

**Design doc reference:** Component Contracts → LogMetadataWriter
**Depends on:** SensorManager, ConfigManager

#### Interface Signatures

```cpp
bool LogMetadataWriter_build(const LogMetadataContext& ctx, String& out);
String LogMetadataWriter_metadataPathForCsv(const char* csvPath);
```

#### Acceptance Criteria

- **AC1:** Given a completed CSV log, when `build` is called, then JSON includes `qc.run_stats` with `samples_dropped`, `queue_max`, `queue_depth`, `flush_count`, `flush_max_ms`, `flush_avg_ms`, `flush_total_ms`, `buffer_size`.
- **AC2:** Given csv path `/260516_201542.CSV`, when `metadataPathForCsv` is called, then returns `/260516_201542.json`.

---

### ZipArchiveWriter — `firmware/src/ZipArchiveWriter.{h,cpp}`

**Design doc reference:** Component Contracts → ZipArchiveWriter
**Depends on:** FS (SD_MMC)

#### Interface Signatures

```cpp
bool ZipArchiveWriter_createStoreOnly(const char* destinationPath,
                                      const ZipArchiveEntry* entries,
                                      uint8_t entryCount,
                                      String* error = nullptr);
```

#### Acceptance Criteria

- **AC1:** Given destination file exists, when `createStoreOnly` is called, then returns false (refuses overwrite).
- **AC2:** Given 2 entries (CSV + JSON), when archive created, then ZIP contains exactly 2 root-level files with same basename.

---

### WiFiManager — `firmware/src/WiFiManager.{h,cpp}`

**Design doc reference:** Component Contracts → WiFiManager
**Depends on:** ConfigManager, RTCManager, UploadModeManager

#### Interface Signatures

```cpp
class WiFiManager {
public:
  static void begin(IsLoggingActiveFn isLoggingFn = nullptr);
  static void loop();
  static void enable();
  static void disable();
  static bool isEnabled();
  static void connectNow();
  static void startConfiguredMode();
  static void disconnect();
  static void maybeConnectForRTC();
  static bool forceRtcSync();
  static bool isRtcSyncPending();
  static WiFiStatus status();
  static bool isNetworkUp();
  static IPAddress localAddress();
  static String networkName();
  static String hostname();
  static void refreshDiscovery();
  static void noteUserActivity();
  static void suspendForLogging();
  static void resumeAfterLogging();
  static void setOnlineCallback(OnOnlineFn cb);
  static void setOfflineCallback(OnOfflineFn cb);
  static void setUiCallback(OnUiFn cb);
};
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| Station scan timeout | 6 s | Return to IDLE |
| Connect timeout | 12 s | Return to IDLE |
| RSSI floor | -90 dBm | Weaker networks ignored |
| AP password | 8–63 chars | Default `bodaqslogger` |
| RTC sync retries | 3, 5 s delay | Give up after max |
| Hostname | ≤ 63 chars, sanitized | Fallback `bodaqs-logger` |

#### Acceptance Criteria

- **AC1:** Given station mode and valid credentials, when `connectNow` is called, then state transitions `IDLE → SCANNING → CONNECTING → ONLINE`.
- **AC2:** Given AP mode, when `startConfiguredMode` is called, then `WiFi.softAP` started and state is `AP_ONLINE`.
- **AC3:** Given station-online, when `refreshDiscovery` is called, then mDNS `_bodaqs-logger._tcp` advertised on port 80.
- **AC4:** Given AP mode, when `refreshDiscovery` is called, then mDNS not started.
- **AC5:** Given logging starts, when `suspendForLogging` is called, then radio torn down synchronously.
- **AC6:** Given logging stops, when `resumeAfterLogging` is called, then prior enabled state restored.

---

### WebServerManager — `firmware/src/WebServerManager.{h,cpp}`, `Routes_*.{h,cpp}`

**Design doc reference:** Component Contracts → WebServerManager
**Depends on:** ConfigManager, StorageManager, SensorManager, UploadModeManager, UploadSessionScanner, UploadAckIndex, UploadSessionCleanup, TransformRegistry, HttpFileSender, HtmlUtil

#### Interface Signatures

```cpp
class WebServerManager {
public:
  using IsLoggingFn = bool (*)();
  static void begin(IsLoggingFn isLogging = nullptr);
  static void attachConfig(LoggerConfig* cfg);
  static bool start();
  static void stop();
  static void loop();
  static bool isRunning();
  static bool canStart();
};
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| Start precondition | Logging inactive | `canStart()` false |
| Config edit | Logging and upload mode inactive | Rejected |
| SD mutation | Logging and upload mode inactive | Rejected (downloads allowed) |
| Session API | Upload mode active | 409 Conflict |
| Path | No traversal (`..`) | 400 Bad Request |

#### Error Specifications

| Error | When | Status | Payload |
|-------|------|--------|---------|
| Upload mode required | Session endpoint without upload mode | 409 | JSON error |
| Unknown session | Session ID not found | 404 | JSON error |
| Storage unavailable | SD not mounted | 503 | JSON error |
| Invalid argument | Missing/invalid query param | 400 | JSON error |

#### Acceptance Criteria

- **AC1:** Given logging active, when `canStart` is called, then returns false.
- **AC2:** Given upload mode inactive, when `GET /api/v1/sessions` is called, then returns 409.
- **AC3:** Given upload mode active, when `GET /api/v1/sessions` is called, then returns JSON with session list.
- **AC4:** Given logging active, when `POST /config` is called, then rejected with error.
- **AC5:** Given `/` requested, when served, then redirects to `/files`.

---

### UploadModeManager — `firmware/src/UploadModeManager.{h,cpp}`

**Design doc reference:** Component Contracts → UploadModeManager
**Depends on:** None (predicate function)

#### Interface Signatures

```cpp
namespace UploadModeManager {
  void begin(UploadModeLoggingActiveFn isLoggingFn = nullptr);
  bool isActive();
  bool canEnter();
  bool enter();
  void exit();
  bool toggle();
  const char* stateLabel();
}
```

#### Acceptance Criteria

- **AC1:** Given logging active, when `enter` is called, then returns false.
- **AC2:** Given upload mode active, when `exit` is called, then `isActive()` returns false.
- **AC3:** Given upload mode inactive, when `toggle` is called, then `isActive()` returns true.

---

### UploadSessionScanner — `firmware/src/UploadSessionScanner.{h,cpp}`

**Design doc reference:** Component Contracts → UploadSessionScanner
**Depends on:** UploadAckIndex, FS

#### Interface Signatures

```cpp
namespace UploadSessionScanner {
  uint16_t scan(const char* directory, SessionInfo* out,
                uint16_t outCapacity, ScanSummary* summary = nullptr);
  bool findBySessionId(const char* sessionId, SessionInfo& out,
                       const char* directory = "/");
}
```

#### Acceptance Criteria

- **AC1:** Given a `.zip` session, when `scan` is called, then returns entry with `data_format=csv_zip`, `archive_ready=true`.
- **AC2:** Given a `.bdq` session, when `scan` is called, then returns entry with `data_format=bdq`, `data_ready=true`.
- **AC3:** Given a `.zip.tmp` file, when `scan` is called, then not listed as importable but counted in `tempArchiveCount`.
- **AC4:** Given a session ID, when `findBySessionId` is called, then returns the matching session.

---

### UploadAckIndex — `firmware/src/UploadAckIndex.{h,cpp}`

**Design doc reference:** Component Contracts → UploadAckIndex
**Depends on:** FS

#### Interface Signatures

```cpp
namespace UploadAckIndex {
  const char* indexPath();
  bool markSessionAcknowledged(const AckRecord& record, String* error = nullptr);
  bool findSessionAcknowledgement(const char* sessionId, AckRecord& out, String* error = nullptr);
  bool applyAcknowledgementStatuses(AckStatusLookup* lookups, uint16_t count, String* error = nullptr);
  bool isSessionAcknowledged(const char* sessionId);
}
```

#### Acceptance Criteria

- **AC1:** Given a session acknowledged, when `markSessionAcknowledged` called again, then no duplicate appended.
- **AC2:** Given a corrupt NDJSON line, when `findSessionAcknowledgement` is called, then line skipped, listing continues.
- **AC3:** Given `indexPath`, when called, then returns `/upload_index.ndjson`.

---

### UploadSessionCleanup — `firmware/src/UploadSessionCleanup.{h,cpp}`

**Design doc reference:** Component Contracts → UploadSessionCleanup
**Depends on:** UploadSessionScanner, FS

#### Interface Signatures

```cpp
namespace UploadSessionCleanup {
  bool parseMode(const char* text, CleanupMode& out);
  const char* modeKey(CleanupMode mode);
  bool cleanupSession(const UploadSessionScanner::SessionInfo& session,
                      CleanupMode mode, CleanupResult& result);
}
```

#### Acceptance Criteria

- **AC1:** Given `MoveToUploaded` mode, when `cleanupSession` is called, then ZIP moved to `/uploaded/`.
- **AC2:** Given `Delete` mode, when `cleanupSession` is called, then ZIP removed.
- **AC3:** Given loose CSV/JSON present, when cleanup runs, then they are also moved/deleted.

---

### RTCManager — `firmware/src/RTCManager.{h,cpp}`

**Design doc reference:** Component Contracts → RTCManager
**Depends on:** BoardProfile (RtcProfile), WiFiManager (for NTP)

#### Interface Signatures

```cpp
void RTCManager_begin(RTCSource source = RTC_INTERNAL, TwoWire* extRtcWire = nullptr);
void RTCManager_begin(const board::RtcProfile& rtcProfile);
void RTCManager_setTimezone(const char* tz);
const char* RTCManager_getTimezone();
void RTCManager_loop();
String RTCManager_getTimestamp();
String RTCManager_getFastTimestamp();
String RTCManager_getDateTimeString();
uint64_t RTCManager_getEpochMs();
time_t RTCManager_getEpoch();
bool RTCManager_isHumanReadable();
void RTCManager_setHumanReadable(bool humanReadable);
bool RTCManager_hasValidTime();
bool RTCManager_usingExternalRtc();
void RTCManager_sync();
bool RTCManager_syncNetworkTime(const char* tz, const char* ntpServersCsv,
                                const char* timeCheckUrl,
                                uint32_t sntpTimeoutMs = 8000,
                                uint32_t httpTimeoutMs = 5000);
bool RTCManager_syncFromHttp(const char* url, uint32_t timeoutMs = 5000);
bool RTCManager_waitForSNTP(uint32_t timeoutMs = 8000);
void RTCManager_invalidateInternalTime();
```

#### Acceptance Criteria

- **AC1:** Given epoch < 2020, when `hasValidTime` is called, then returns false.
- **AC2:** Given human mode, when `getTimestamp` is called, then returns `HH:MM:SS.mmm`.
- **AC3:** Given fast mode, when `getTimestamp` is called, then returns epoch ms integer.
- **AC4:** Given NTP unavailable, when `syncNetworkTime` is called, then falls back to HTTP.

---

### PowerManager — `firmware/src/PowerManager.{h,cpp}`

**Design doc reference:** Component Contracts → PowerManager
**Depends on:** BoardProfile, I2CManager

#### Interface Signatures

```cpp
namespace PowerManager {
  void begin(const board::BoardProfile& board);
  void sleepOnEnterEXT0();
  void noteActivity();
  void loop();
  void setCpuFreqForLogging();
  void restoreCpuFreqAfterLogging();
  void fuelGaugeBegin(uint8_t i2c_addr = 0x36, TwoWire* wire = nullptr);
  void fuelGaugeLoop();
  bool fuelGaugeOk();
  float batterySocPercent();
  float batteryVoltage();
  bool batteryLow();
  bool fuelAlertActive();
  void setAnalogRailEnabled(bool enabled);
  bool analogRailEnabled();
  bool analogRailFaultActive();
  bool analogRailFaultLatched();
  bool canStartLogging();
}
```

#### Acceptance Criteria

- **AC1:** Given battery low, when `canStartLogging` is called, then returns false.
- **AC2:** Given analog rail fault latched, when `canStartLogging` is called, then returns false.
- **AC3:** Given idle timeout elapsed, when `loop` is called, then enters deep sleep with EXT0 wake.

---

### ButtonManager — `firmware/src/ButtonManager.{h,cpp}`

**Design doc reference:** Component Contracts → ButtonManager
**Depends on:** None

#### Interface Signatures

```cpp
void ButtonManager_register(uint8_t pin, ButtonMode mode, unsigned long debounceDelay, ButtonCallback cb);
void ButtonManager_register(uint8_t pin, ButtonMode mode, unsigned long debounceDelay,
                            ButtonCallback cb, bool activeLow, bool useInternalPullup);
ButtonEvent ButtonManager_read(uint8_t pin);
void ButtonManager_loop();
void ButtonManager_setPollingEnabled(bool enabled);
void ButtonManager_setPollIntervalMs(uint32_t ms);
void ButtonManager_setPressActivityCallback(ButtonActivityCallback cb);
void ButtonManager_setDebounceAll(unsigned long debounceDelay);
```

#### Acceptance Criteria

- **AC1:** Given interrupt mode, when pin goes LOW, then `BUTTON_PRESSED` posted from ISR.
- **AC2:** Given pin held LOW > 800 ms, when `loop` runs, then `BUTTON_HELD` synthesized.
- **AC3:** Given poll mode, when `loop` runs, then debounce applied before event.

---

### ButtonBindingTable / ButtonActions — `firmware/src/ButtonBindingTable.{h,cpp}`, `ButtonActions.{h,cpp}`

**Design doc reference:** Component Contracts → ButtonBindingTable / ButtonActions
**Depends on:** ConfigManager, ButtonManager, LoggingManager, WebServerManager, UploadModeManager, MenuSystem, PowerManager

#### Interface Signatures

```cpp
namespace ButtonBindingTable {
  void initFromConfig(const LoggerConfig& cfg);
  void handleButtonEvent(uint8_t buttonIndex, ButtonEvent ev);
}

namespace ButtonActions {
  void begin();
  void registerButtons();
  void reloadBindingsFromConfig(const LoggerConfig& cfg);
  void invoke(ActionId action, ButtonEvent ev);
  MarkOverrideHandle pushMarkOverride(std::function<void(ButtonEvent)> handler);
  bool popMarkOverride(MarkOverrideHandle handle);
  bool hasActiveMarkOverride();
}
```

#### Acceptance Criteria

- **AC1:** Given binding `mark` + `held` → `logging_toggle`, when mark button held, then logging toggles.
- **AC2:** Given a pushed mark override, when mark pressed, then override handler called (not default).
- **AC3:** Given override popped, when mark pressed, then default mark behavior resumes.

---

### MenuSystem — `firmware/src/MenuSystem.{h,cpp}`

**Design doc reference:** Component Contracts → MenuSystem
**Depends on:** ConfigManager, SensorManager, LoggingManager, WiFiManager, UploadModeManager, UI, DisplayManager, PowerManager, FirmwareInfo

#### Interface Signatures

```cpp
namespace MenuSystem {
  void begin(const LoggerConfig* cfg);
  void setIdleCloseMs(uint32_t ms);
  bool isActive();
  void requestOpen();
  void requestClose();
  void requestSleep();
  void loop();
  void navUp();
  void navDown();
  void navLeft();
  void navRight();
  void select();
  void onNav(Dir d, ButtonEvent ev);
  bool handleAction(ButtonActions::ActionId action, ButtonEvent ev);
  void onMark();
}
```

#### Acceptance Criteria

- **AC1:** Given menu inactive, when Enter short-pressed, then menu opens and `UI::setModal(true)` called.
- **AC2:** Given menu open, when Enter long-pressed, then menu closes and `UI::setModal(false)` called.
- **AC3:** Given menu open and idle for 300 s, when `loop` runs, then menu auto-closes.
- **AC4:** Given SensorsList state, when Enter pressed on a sensor, then mute toggled via `SensorManager::setMuted`.
- **AC5:** Given About screen, when viewed, then shows firmware version, board profile, build timestamp.

---

### UI / DisplayManager — `firmware/src/UI.{h,cpp}`, `DisplayManager.{h,cpp}`

**Design doc reference:** Component Contracts → UI / DisplayManager
**Depends on:** ConfigManager, BoardProfile, I2CManager

#### Interface Signatures

```cpp
namespace UI {
  void begin(const LoggerConfig& cfg);
  void configure(const LoggerConfig& cfg);
  void loop();
  void println(const String& serialText, const String& oledText = "",
               uint8_t targets = TARGET_DEFAULT, uint8_t level = LVL_INFO,
               uint16_t oledToastMs = 2000, uint8_t oledToastSize = 2);
  void status(const String& line);
  void toast(const String& oledText, uint16_t durationMs = 1500, uint8_t textSize = 2);
  void clear(uint8_t target = TARGET_OLED);
  void beginModal();
  void endModal();
  bool isModal();
}

namespace DisplayManager {
  bool begin(const LoggerConfig& cfg, const board::DisplayProfile& disp, TwoWire* wire);
  void loop();
  void setStatusLine(const String& line);
  void setFooterLine(const String& line);
  void toast(const String& text, uint16_t durationMs = 1500, uint8_t textSize = 2);
  bool available();
  void clear();
  void setBrightness(uint8_t b);
}
```

#### Acceptance Criteria

- **AC1:** Given `UI::isModal()` true, when `DisplayManager::loop` runs, then exits early (no telemetry draw).
- **AC2:** Given `UI::status("Ready")`, when called, then sticky top line set on OLED.
- **AC3:** Given `UI::toast("Marked", 1200)`, when called, then transient bottom message shown for 1200 ms.
- **AC4:** Given no OLED, when `DisplayManager::available()` called, then returns false; UI still routes to Serial.

---

### I2CManager — `firmware/src/I2CManager.{h,cpp}`

**Design doc reference:** Component Contracts → I2CManager
**Depends on:** BoardProfile

#### Interface Signatures

```cpp
namespace I2CManager {
  void begin(const board::BoardProfile& bp);
  bool available(uint8_t busIndex);
  TwoWire* bus(uint8_t busIndex);
  const board::I2CProfile* profile(uint8_t busIndex);
  bool lock(TwoWire* wire, uint32_t timeoutMs = 50);
  void unlock(TwoWire* wire);
}
```

#### Acceptance Criteria

- **AC1:** Given board with 2 I2C buses, when `begin` called, then both initialized.
- **AC2:** Given bus index 1 not present, when `bus(1)` called, then returns nullptr.

---

### AnalogInputManager — `firmware/src/AnalogInputManager.{h,cpp}`

**Design doc reference:** Component Contracts → AnalogInputManager
**Depends on:** BoardProfile, ConfigManager, SensorManager

#### Interface Signatures

```cpp
namespace AnalogInputManager {
  void begin(const board::BoardProfile& board);
  bool available(uint8_t ain);
  bool inputIsExternal(uint8_t ain);
  int8_t pinForAin(uint8_t ain);
  bool readCounts(uint8_t ain, int32_t& outCounts);
  uint16_t configureFromConfig(const LoggerConfig& cfg, uint16_t requestedHz);
  uint16_t effectiveSampleRateHz();
  uint16_t requestedSampleRateHz();
  uint8_t activeChannelCount(uint8_t externalAdcIndex);
  uint16_t configuredDataRateSps(uint8_t externalAdcIndex);
  void beginSample();
  void endSample();
}
```

#### Acceptance Criteria

- **AC1:** Given V1RC3 with external ADCs, when `inputIsExternal(0)` called, then returns true.
- **AC2:** Given 4D with internal ADC, when `pinForAin(0)` called, then returns GPIO pin.
- **AC3:** Given requested 500 Hz but external ADC can only do 200 Hz, when `configureFromConfig` called, then returns 200.

---

### IndicatorManager — `firmware/src/IndicatorManager.{h,cpp}`

**Design doc reference:** Component Contracts → IndicatorManager
**Depends on:** BoardProfile

#### Interface Signatures

```cpp
class IndicatorManager {
public:
  static void begin(const board::BoardProfile& bp);
  static void ledOn();
  static void ledOff();
  static bool hasLed();
};
```

#### Acceptance Criteria

- **AC1:** Given logging starts, when `ledOn` called, then LED illuminated.
- **AC2:** Given board with no LED, when `hasLed` called, then returns false; `ledOn` no-op.

---

### DebugLog / DebugTrace — `firmware/src/DebugLog.{h,cpp}`, `DebugTrace.h`

**Design doc reference:** Component Contracts → DebugLog / DebugTrace
**Depends on:** None

#### Interface Signatures

```cpp
void Log_setEnabled(bool on);
bool Log_isEnabled();
void Log_setLevel(LogLevel lvl);
void Log_resetLevel();
LogLevel Log_getLevel();
bool Log_would(LogLevel lvl);
void Log_printf(LogLevel lvl, const char* fmt, ...);
void Log_taggedPrintf(LogLevel lvl, const char* tag, const char* fmt, ...);

// Macros (compile-time gated)
#define LOGE(...)
#define LOGE_TAG(tag, ...)
#define LOGW(...) / LOGW_TAG(tag, ...)
#define LOGI(...) / LOGI_TAG(tag, ...)
#define LOGD(...) / LOGD_TAG(tag, ...)
#define LOGT(...) / LOGT_TAG(tag, ...)

#define TRACE(msg)  // DebugTrace.h
```

#### Acceptance Criteria

- **AC1:** Given `BODAQS_LOG_LEVEL=INFO`, when `LOGD` called, then compiled out.
- **AC2:** Given runtime level set to `LOG_WARN`, when `LOGI` called, then not printed.
- **AC3:** Given `TRACE_ENABLED=1`, when `TRACE("msg")` called, then logs timestamped message at DEBUG.

---

## Implementation Approach

### High-Level Architecture

The firmware is a single-binary Arduino-ESP32 application built with PlatformIO.
It uses a manager-pattern architecture where each subsystem is a namespace or
static class with free-function APIs. The main `setup()` initializes all
managers in dependency order; `loop()` calls each manager's `loop()` in
sequence.

Sampling runs on a dedicated FreeRTOS task (pinned to core 0 via `xCoreID=0`,
priority 3; code comment claims core 1) that is
decoupled from SD writes via a spinlock-protected ring buffer. The main loop
(core 0) drains the buffer and writes to SD in time-bounded chunks.

See the design doc's High-Level Architecture section for Mermaid diagrams of
the boot sequence, sampling/drain path, and config/sensor framework.

### Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Framework | Arduino-ESP32 + PlatformIO | Mature ecosystem, library availability |
| Storage backend | SDMMC only (SD_MMC) | Retired SPI/SdFat to reduce flash use |
| Sampling | FreeRTOS task (core 0) | Decouples sample timing from SD latency |
| Queue | Fixed-capacity ring buffer + spinlock | No heap allocation in hot path |
| Config format | Line-oriented `key=value` text | Human-readable, easy to parse on-device |
| Sensor config | ParamPack (KV view into ParamStore) | Single source of truth, no copying |
| Transform identity | `meta.id` (not filename) | Stable across file renames |
| Log formats | 3 (CSV+ZIP, syn_bike, BDQ binary) | Supports different downstream tools |
| Wi-Fi modes | Station + AP, same API | Field use without router |
| Upload gating | Explicit upload mode | Prevents partial-session import |
| Board abstraction | Static BoardProfile structs | Compile-time hardware config, no heap |

### Research

- BDQ v1 format designed for power-loss resilience: chunks are self-validating
  via CRC32, and a missing final summary is not fatal for data recovery.
- ZIP archives use store-only (no compression) to minimize CPU and avoid
  library dependencies.
- mDNS used only in station mode because AP mode clients connect directly to
  the known IP `192.168.4.1`.

### Alternatives Considered

| Alternative | Why not chosen |
|-------------|----------------|
| SPI/SdFat storage | Retired — more flash use, SDMMC is native |
| USB mass storage | Filesystem contention with logging |
| USB serial download | Reliability issues, parked |
| Per-sample wall-clock timestamp in BDQ | Storage overhead; fixed-rate timebase sufficient |
| Dynamic transform reload | Complexity; once-per-boot is simpler |
| Heap-allocated sample queue | Fragmentation risk in long runs |

## Dependencies

### Design Dependencies

- `docs/design/esp32-logger-firmware.md` (this spec's design doc)

### Spec Dependencies

- None (this is the first spec for this sphere)

### Package Dependencies

- Arduino-ESP32 core (3.3.0 tested)
- Adafruit BusIO, GFX Library, SSD1306 (OLED)
- ArduinoJson (metadata/schema JSON)
- SparkFun u-blox GNSS v3 (GPS sensor)
- ESP32 FreeRTOS (task, queue, spinlock)
- ESP32 WiFi, WebServer, ESPmDNS, SD_MMC

## Open Questions

| # | Question | Blocks | Resolution |
|---|----------|--------|------------|
| 1 | `g_sdTrackEnabled`/`g_sdWriteSinceLastSample` consumer unclear | None | UNRESOLVED (unverified intent — needs review) |
| 2 | SensorManager ownership boundary with ConfigManager implicit | None | UNRESOLVED (unverified intent — needs review) |
| 3 | `s_pot1` in LoggingManager unused | None | Legacy — may be removed |
| 4 | Compile-time probe modes undocumented | None | UNRESOLVED (unverified intent — needs review) |
| 5 | `log_format=bodaqs_CSV` in Prototype F config doesn't match enum | None | UNRESOLVED (unverified intent — needs review) |
| 6 | CalCapture.cpp relationship to CalibrationWizard unclear | None | UNRESOLVED (unverified intent — needs review) |
| 7 | Sample task `xCoreID=0` (core 0) but code comment says "core 1" | None | UNRESOLVED (unverified intent — needs review) |

## Risks

| Risk | Mitigation |
|------|------------|
| Power loss mid-session truncates CSV | BDQ format is chunk-resilient; CSV may have partial last row |
| Sample task stack overflow | 4096-byte stack; monitor high-water mark |
| SD write latency spikes | Time-bounded drain (5 ms), buffered writes, flush every 5 s |
| Wi-Fi + SD coexistence | Wi-Fi suspended during logging; sample task on core 0 |
| Config file corruption | Atomic write-then-rename with `.bak` backup |
| Transform ID mismatch silent | Identity fallback is intentional; web UI must write `meta.id` |
| Upload ack index growth | Oversized index refused; manual compaction needed |

## Success Criteria

- [ ] All 28 system invariants (INV-1 through INV-28) are documented and traceable to code.
- [ ] All 35 failure modes are documented with handled/unhandled status.
- [ ] All 27 component contracts are documented with interface signatures.
- [ ] All 6 sensor types are documented with param schemas and calibration support.
- [ ] All 3 log formats are documented with file lifecycle and acceptance criteria.
- [ ] Wi-Fi upload API v1 endpoints are documented with status codes and response shapes.
- [ ] Board profiles (4D, 4F, V1RC3) are documented with hardware mappings.
- [ ] Backwards compatibility shims (legacy keys, type names) are documented.
- [ ] Open questions are classified (7 unknown/legacy).
- [ ] Design doc and spec validate against the code with no discrepancies.
