#pragma once

#include "Sensor.h"
#include "SensorParams.h"
#include "SensorTypes.h"
#include <stdint.h>

class HardwareSerial;
class SFE_UBLOX_GNSS_SERIAL;

#if defined(ESP32)
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#endif

class DANF10NGpsSensor : public Sensor {
public:
  enum class QualityColumns : uint8_t {
    None = 0,
    Minimal,
    Full,
  };

  enum class ValidityPolicy : uint8_t {
    ValidOnly = 0,
    LatestWithStatus,
    FreshOnly,
  };

  enum class DiagnosticMode : uint8_t {
    Normal = 0,
    Disabled,
    SerialOnly,
    SleepTask,
    DrainTask,
  };

  enum class ColumnKind : uint8_t {
    LatDeg,
    LonDeg,
    AltM,
    SpeedMps,
    HeadingDeg,
    Valid,
    AgeMs,
    Seq,
    Fresh,
    FixType,
    Satellites,
    HAccM,
    VAccM,
    SpeedAccuracyMps,
    CourseAccuracyDeg,
    TimeOfWeekCs,
  };

  struct Params {
    const char* name = nullptr;
    uint8_t uartPort = 0;
    uint32_t baud = 38400;
    uint8_t updateRateHz = 1;
    uint32_t staleAfterMs = 1500;
    uint16_t beginMaxWaitMs = 1000;
    uint16_t configMaxWaitMs = 500;
    uint16_t rxBufferBytes = 4096;
    QualityColumns qualityColumns = QualityColumns::Minimal;
    ValidityPolicy validityPolicy = ValidityPolicy::ValidOnly;
    DiagnosticMode diagnosticMode = DiagnosticMode::Normal;
    bool emitPosition = true;
    bool emitAltitude = true;
    bool emitMotion = true;
  };

  explicit DANF10NGpsSensor(const Params& p);

  void begin() override;
  void onLoggingStart() override;
  void onLoggingStop() override;

  bool muted() const override { return m_muted; }
  void setMuted(bool m) override;

  SensorSampleMode sampleMode() const override { return SensorSampleMode::Asynchronous; }
  uint8_t columnCount() const override;
  void getColumnName(uint8_t idx, char* out, size_t cap) const override;
  void sampleValues(float* out, uint8_t max) override;
  bool describeColumn(uint8_t idx, SensorColumnDescriptor& out) const override;
  bool describeSensorMetadata(SensorMetadataDescriptor& out) const override;
  bool gpsStatus(SensorGpsStatus& out) const override;

  const char* label() const override { return "DAN-F10N GPS"; }
  const char* name() const override { return m_name; }

  bool reconfigureFromSpec(const SensorSpec& spec) override;

  static const ParamDef* paramDefs(size_t& count);
  static Sensor* create(const char* instanceName, const ParamPack& params, bool mutedDefault);

private:
  struct Snapshot {
    bool have = false;
    bool fixOk = false;
    bool invalidLlh = true;
    bool valid = false;
    uint8_t fixType = 0;
    uint8_t satellites = 0;
    int32_t latE7 = 0;
    int32_t lonE7 = 0;
    int32_t altMslMm = 0;
    int32_t groundSpeedMmS = 0;
    int32_t headingDegE5 = 0;
    uint32_t hAccMm = 0;
    uint32_t vAccMm = 0;
    uint32_t speedAccMmS = 0;
    uint32_t headingAccDegE5 = 0;
    uint32_t gpsTowMs = 0;
    uint32_t gpsUnixSeconds = 0;
    uint32_t receivedMs = 0;
    uint32_t seq = 0;
  };

  void applyParams(const Params& p);
  bool startSerial_();
  bool startTask_();
  void stopTask_();
  bool initializeGnss_();
  void taskLoop_();
  void updateSnapshotFromGnss_();
  void clearSessionSnapshot_();
  bool copySnapshot_(Snapshot& out) const;
  bool outputValueValid_(const Snapshot& s, uint32_t ageMs, bool fresh) const;
  uint32_t snapshotAgeMs_(const Snapshot& s, uint32_t nowMs) const;
  uint8_t collectColumns_(ColumnKind* out, uint8_t max) const;
  float valueForColumn_(ColumnKind kind, const Snapshot& s, uint32_t ageMs, bool fresh, bool emitValue) const;

  static void taskThunk_(void* arg);
  static HardwareSerial* serialForPort_(uint8_t port);

private:
  char m_name[16] = "gps";
  uint8_t m_uartPort = 0;
  uint32_t m_baud = 38400;
  uint8_t m_updateRateHz = 1;
  uint32_t m_staleAfterMs = 1500;
  uint16_t m_beginMaxWaitMs = 1000;
  uint16_t m_configMaxWaitMs = 500;
  uint16_t m_rxBufferBytes = 4096;
  QualityColumns m_qualityColumns = QualityColumns::Minimal;
  ValidityPolicy m_validityPolicy = ValidityPolicy::ValidOnly;
  DiagnosticMode m_diagnosticMode = DiagnosticMode::Normal;
  bool m_emitPosition = true;
  bool m_emitAltitude = true;
  bool m_emitMotion = true;
  bool m_muted = false;

  HardwareSerial* m_serial = nullptr;
  SFE_UBLOX_GNSS_SERIAL* m_gnss = nullptr;
  bool m_initialized = false;
  bool m_warnedNoUart = false;
  bool m_warnedInit = false;
  volatile bool m_taskRun = false;

  Snapshot m_snapshot;
  uint32_t m_nextSeq = 0;
  uint32_t m_lastLoggedSeq = 0;

#if defined(ESP32)
  TaskHandle_t m_task = nullptr;
  SemaphoreHandle_t m_mutex = nullptr;
#endif
};
