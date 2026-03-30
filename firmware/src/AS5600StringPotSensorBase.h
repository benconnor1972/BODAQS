#pragma once

#include "Sensor.h"
#include "SensorParams.h"
#include <limits.h>

class AS5600StringPotSensorBase : public Sensor {
public:
  struct BaseParams {
    const char* name = nullptr;
    bool     invert = false;
    uint16_t emaAlphaPermille = 1000;
    uint16_t deadbandCounts = 0;
    uint16_t countsPerTurn = 4096;
    uint16_t wrapThresholdCounts = 2048;
    int32_t  sensorZeroCount = 0;
    int32_t  sensorFullCount = 4095;
    int32_t  installedZeroCount = 0;
    float    sensorFullTravelMm = 0.0f;
    bool     assumeTurn0AtStart = true;
    bool     includeRawColumn = true;
    char     unitsLabel[48] = "mm";
  };

  explicit AS5600StringPotSensorBase(const BaseParams& p);

  void loop() override {}
  void applyConfig(const LoggerConfig&) override {}
  void onLoggingStart() override;
  void onLoggingStop() override;

  bool muted() const override { return m_muted; }
  void setMuted(bool m) override { m_muted = m; }

  uint8_t columnCount() const override;
  void getColumnName(uint8_t idx, char* out, size_t cap) const override;
  void sampleValues(float* out, uint8_t max) override;

  const char* name() const override { return m_name; }

  OutputConfig outputConfig() const override;
  void setOutputConfig(const OutputConfig& cfg) override;
  OutputMode outputMode() const override;
  void setOutputMode(OutputMode m) override;

  CalMask allowedCalMask() const override { return m_allowedMask; }
  void setAllowedCalMask(CalMask m) override { m_allowedMask = m; }

  bool beginCalibration(CalMode mode) override;
  bool updateCalibration(int32_t latestCounts) override;
  bool finishCalibration(bool persist) override;
  CalPhase currentCalPhase() const override { return cal_.phase; }

  bool supportsCalibration() const override { return true; }
  bool hasRawCounts() const override { return true; }
  int32_t currentRawCounts() const override;

  CalibrationState calibration() const override;
  bool setCalibration(const CalibrationState& s) override;

  SmoothingConfig smoothing() const override;
  void setSmoothing(const SmoothingConfig& s) override;
  void setIncludeRaw(bool b) override;
  void setOutputUnitsLabel(const char* u) override;

protected:
  virtual int readWrappedCountsOnce() const = 0;

  void applyBaseParams(const BaseParams& p);
  void resetTrackingState(bool assumeTurnZero);
  void recomputeScale();

private:
  struct SampleState {
    int wrappedRaw = 0;
    int32_t unwrappedRaw = 0;
    int32_t unwrappedSmoothed = 0;
  };

  struct CalState {
    CalMode  mode = CalMode::NONE;
    CalPhase phase = CalPhase::IDLE;
    int32_t  first_counts = INT32_MAX;
    int32_t  second_counts = INT32_MIN;
    uint32_t started_ms = 0;
    uint32_t samples = 0;
  };

  int normalizeWrapped_(int wrapped) const;
  int32_t initialUnwrappedFromWrapped_(int wrapped) const;
  int32_t updateUnwrappedFromWrapped_(int wrapped) const;
  int32_t updateUnwrappedEma_(int32_t raw) const;
  SampleState captureSample_() const;
  float countsToMm_(int32_t counts) const;
  bool rawColumnEnabled_() const;

private:
  CalState cal_;

  int32_t sensor_zero_count_ = 0;
  int32_t sensor_full_count_ = 4095;
  float   sensor_full_travel_mm_ = 0.0f;
  int32_t installed_zero_count_ = 0;
  double  counts_per_mm_ = 0.0;

  char    m_name[16] = "as5600";
  char    m_unitsLabel[48] = "mm";

  bool     m_invert = false;
  uint16_t m_countsPerTurn = 4096;
  uint16_t m_wrapThreshold = 2048;
  bool     m_assumeTurn0AtStart = true;

  float    m_alpha = 1.0f;
  uint16_t m_deadband = 0;

  CalMask  m_allowedMask = (CalMask)(CAL_ZERO | CAL_RANGE);
  bool     m_muted = false;

  mutable bool    m_trackingInit = false;
  mutable int     m_lastWrappedRaw = 0;
  mutable int32_t m_turnIndex = 0;
  mutable int32_t m_lastUnwrappedRaw = 0;
  mutable bool    m_emaInit = false;
  mutable float   m_ema = 0.0f;
};
