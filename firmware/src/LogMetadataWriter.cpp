#include "LogMetadataWriter.h"

#include "BoardProfile.h"
#include "SensorManager.h"
#include <new>

namespace {

class MetadataOutput {
public:
  virtual ~MetadataOutput() = default;

  virtual bool reserve(size_t bytes) = 0;
  virtual bool append(const char* text, size_t length) = 0;

  bool ok() const { return ok_; }

  MetadataOutput& operator+=(const __FlashStringHelper* text) {
    const char* chars = reinterpret_cast<const char*>(text);
    append_(chars, chars ? strlen(chars) : 0);
    return *this;
  }

  MetadataOutput& operator+=(const char* text) {
    append_(text, text ? strlen(text) : 0);
    return *this;
  }

  MetadataOutput& operator+=(const String& text) {
    append_(text.c_str(), text.length());
    return *this;
  }

  MetadataOutput& operator+=(char value) {
    append_(&value, 1);
    return *this;
  }

protected:
  void append_(const char* text, size_t length) {
    if (ok_ && length) ok_ = append(text, length);
  }

private:
  bool ok_ = true;
};

class StringMetadataOutput final : public MetadataOutput {
public:
  explicit StringMetadataOutput(String& target) : target_(target) {}

  bool reserve(size_t bytes) override { return target_.reserve(bytes); }
  bool append(const char* text, size_t length) override {
    return target_.concat(text, length);
  }

private:
  String& target_;
};

class PrintMetadataOutput final : public MetadataOutput {
public:
  explicit PrintMetadataOutput(Print& target) : target_(target) {}

  // Print destinations do not need a contiguous metadata allocation.
  bool reserve(size_t) override { return true; }
  bool append(const char* text, size_t length) override {
    return target_.write(reinterpret_cast<const uint8_t*>(text), length) == length;
  }

private:
  Print& target_;
};

void appendIndent_(MetadataOutput& out, uint8_t depth) {
  while (depth--) out += F("  ");
}

void appendJsonString_(MetadataOutput& out, const char* s) {
  out += '"';
  if (!s) s = "";
  for (const char* p = s; *p; ++p) {
    switch (*p) {
      case '\\': out += F("\\\\"); break;
      case '"':  out += F("\\\""); break;
      case '\n': out += F("\\n"); break;
      case '\r': out += F("\\r"); break;
      case '\t': out += F("\\t"); break;
      default:
        if ((uint8_t)*p < 0x20) {
          char buf[7];
          snprintf(buf, sizeof(buf), "\\u%04x", (unsigned)(uint8_t)*p);
          out += buf;
        } else {
          out += *p;
        }
        break;
    }
  }
  out += '"';
}

void appendKey_(MetadataOutput& out, uint8_t depth, const char* key) {
  appendIndent_(out, depth);
  appendJsonString_(out, key);
  out += F(": ");
}

void appendKeyString_(MetadataOutput& out, uint8_t depth, const char* key, const char* value, bool comma = true) {
  appendKey_(out, depth, key);
  appendJsonString_(out, value);
  if (comma) out += ',';
  out += '\n';
}

void appendKeyBool_(MetadataOutput& out, uint8_t depth, const char* key, bool value, bool comma = true) {
  appendKey_(out, depth, key);
  out += value ? F("true") : F("false");
  if (comma) out += ',';
  out += '\n';
}

void appendKeyUInt_(MetadataOutput& out, uint8_t depth, const char* key, uint32_t value, bool comma = true) {
  appendKey_(out, depth, key);
  out += String(value);
  if (comma) out += ',';
  out += '\n';
}

void appendKeyHex8_(MetadataOutput& out, uint8_t depth, const char* key, uint8_t value, bool comma = true) {
  appendKey_(out, depth, key);
  char buf[7];
  snprintf(buf, sizeof(buf), "\"0x%02X\"", (unsigned)value);
  out += buf;
  if (comma) out += ',';
  out += '\n';
}

void appendKeyHex16_(MetadataOutput& out, uint8_t depth, const char* key, uint16_t value, bool comma = true) {
  appendKey_(out, depth, key);
  char buf[9];
  snprintf(buf, sizeof(buf), "\"0x%04X\"", (unsigned)value);
  out += buf;
  if (comma) out += ',';
  out += '\n';
}

void appendKeyUInt64_(MetadataOutput& out, uint8_t depth, const char* key, uint64_t value, bool comma = true) {
  appendKey_(out, depth, key);
  char buf[24];
  snprintf(buf, sizeof(buf), "%llu", (unsigned long long)value);
  out += buf;
  if (comma) out += ',';
  out += '\n';
}

void appendKeyInt_(MetadataOutput& out, uint8_t depth, const char* key, int32_t value, bool comma = true) {
  appendKey_(out, depth, key);
  out += String(value);
  if (comma) out += ',';
  out += '\n';
}

void appendKeyFloat_(MetadataOutput& out, uint8_t depth, const char* key, float value, bool comma = true) {
  appendKey_(out, depth, key);
  out += String(value, 6);
  if (comma) out += ',';
  out += '\n';
}

const char* imuStartupStateName_(uint8_t state) {
  switch (state) {
    case 0: return "disabled";
    case 1: return "collecting";
    case 2: return "accepted";
    case 3: return "rejected";
    default: return "unknown";
  }
}

const char* imuStartupRejectionName_(uint8_t state, uint16_t mask) {
  if (state == 0) return "disabled";
  if (state == 1) return "window_incomplete";
  if (mask == 0) return "none";
  if (mask & 0x0001) return "insufficient_samples";
  if (mask & 0x0002) return "quality_incident";
  if (mask & 0x0004) return "accel_mean_outside_gravity_band";
  if (mask & 0x0008) return "accel_magnitude_unstable";
  if (mask & 0x0010) return "gyro_x_unstable";
  if (mask & 0x0020) return "gyro_y_unstable";
  if (mask & 0x0040) return "gyro_z_unstable";
  if (mask & 0x0080) return "gyro_motion_detected";
  return "unknown";
}

void appendImuQualityDiagnostics_(
    MetadataOutput& out,
    uint8_t depth,
    const SensorRuntimeDiagnostics& diagnostics) {
  appendKey_(out, depth, "near_rail_counts");
  out += F("{\n");
  appendKey_(out, depth + 1, "accel");
  out += F("{\n");
  appendKeyUInt64_(out, depth + 2, "x", diagnostics.imuAccelNearRail[0]);
  appendKeyUInt64_(out, depth + 2, "y", diagnostics.imuAccelNearRail[1]);
  appendKeyUInt64_(out, depth + 2, "z", diagnostics.imuAccelNearRail[2], false);
  appendIndent_(out, depth + 1);
  out += F("},\n");
  appendKey_(out, depth + 1, "gyro");
  out += F("{\n");
  appendKeyUInt64_(out, depth + 2, "x", diagnostics.imuGyroNearRail[0]);
  appendKeyUInt64_(out, depth + 2, "y", diagnostics.imuGyroNearRail[1]);
  appendKeyUInt64_(out, depth + 2, "z", diagnostics.imuGyroNearRail[2], false);
  appendIndent_(out, depth + 1);
  out += F("}\n");
  appendIndent_(out, depth);
  out += F("},\n");

  appendKeyUInt64_(out, depth, "timing_degraded_samples", diagnostics.imuTimingDegradedSamples);
  appendKeyUInt64_(out, depth, "sequence_discontinuity_events", diagnostics.imuSequenceDiscontinuityEvents);
  appendKeyUInt64_(out, depth, "native_time_discontinuity_events", diagnostics.imuNativeTimeDiscontinuityEvents);

  appendKey_(out, depth, "acquisition_age_us");
  out += F("{\n");
  appendKeyUInt64_(out, depth + 1, "count", diagnostics.imuAgeSamples);
  appendKeyUInt64_(out, depth + 1, "unavailable", diagnostics.imuAgeUnavailable);
  appendKeyUInt64_(out, depth + 1, "histogram_clipped", diagnostics.imuAgeClipped);
  appendKeyUInt_(out, depth + 1, "histogram_resolution_us", diagnostics.imuAgeResolutionUs);
  appendKeyUInt_(out, depth + 1, "minimum", diagnostics.imuAgeMinimumUs);
  appendKeyUInt_(out, depth + 1, "median", diagnostics.imuAgeMedianUs);
  appendKeyUInt_(out, depth + 1, "p95", diagnostics.imuAgeP95Us);
  appendKeyUInt_(out, depth + 1, "p99", diagnostics.imuAgeP99Us);
  appendKeyUInt_(out, depth + 1, "maximum", diagnostics.imuAgeMaximumUs, false);
  appendIndent_(out, depth);
  out += F("},\n");

  appendKey_(out, depth, "temperature_deg_c");
  out += F("{\n");
  appendKeyUInt64_(out, depth + 1, "samples", diagnostics.imuTemperatureSamples);
  appendKeyFloat_(out, depth + 1, "minimum", diagnostics.imuTemperatureMinimumC);
  appendKeyFloat_(out, depth + 1, "maximum", diagnostics.imuTemperatureMaximumC, false);
  appendIndent_(out, depth);
  out += F("},\n");

  appendKey_(out, depth, "startup_stationary_observation");
  out += F("{\n");
  appendKeyString_(out, depth + 1, "schema", "bodaqs.imu_startup_observation.v1");
  appendKeyString_(out, depth + 1, "state", imuStartupStateName_(diagnostics.imuStartupObservationState));
  appendKeyBool_(out, depth + 1, "accepted", diagnostics.imuStartupObservationState == 2);
  appendKeyString_(out, depth + 1, "rejection_reason",
                   imuStartupRejectionName_(diagnostics.imuStartupObservationState,
                                            diagnostics.imuStartupRejectionMask));
  appendKeyHex16_(out, depth + 1, "rejection_mask", diagnostics.imuStartupRejectionMask);
  appendKeyUInt_(out, depth + 1, "configured_window_s", diagnostics.imuStartupConfiguredSeconds);
  appendKeyUInt_(out, depth + 1, "target_sample_slots", diagnostics.imuStartupTargetSampleSlots);
  appendKeyUInt_(out, depth + 1, "minimum_valid_samples", 800);
  appendKeyUInt_(out, depth + 1, "valid_samples", diagnostics.imuStartupValidSamples);
  appendKeyUInt_(out, depth + 1, "settling_sample_slots", diagnostics.imuStartupSettlingSampleSlots);
  appendKeyUInt_(out, depth + 1, "measurement_start_sequence", diagnostics.imuStartupMeasurementStartSequence);
  appendKeyHex16_(out, depth + 1, "settling_status_mask", diagnostics.imuStartupSettlingStatusMask);
  appendKey_(out, depth + 1, "thresholds");
  out += F("{\n");
  appendKeyFloat_(out, depth + 2, "accel_mean_tolerance_g", 0.15f);
  appendKeyFloat_(out, depth + 2, "accel_magnitude_std_max_g", 0.03f);
  appendKeyFloat_(out, depth + 2, "gyro_axis_std_max_dps", 0.5f);
  appendKeyFloat_(out, depth + 2, "gyro_magnitude_max_dps", 5.0f, false);
  appendIndent_(out, depth + 1);
  out += F("},\n");
  appendKey_(out, depth + 1, "gyro_mean_raw");
  out += F("{\n");
  appendKeyFloat_(out, depth + 2, "x", diagnostics.imuStartupGyroMeanRaw[0]);
  appendKeyFloat_(out, depth + 2, "y", diagnostics.imuStartupGyroMeanRaw[1]);
  appendKeyFloat_(out, depth + 2, "z", diagnostics.imuStartupGyroMeanRaw[2], false);
  appendIndent_(out, depth + 1);
  out += F("},\n");
  appendKey_(out, depth + 1, "gyro_std_raw");
  out += F("{\n");
  appendKeyFloat_(out, depth + 2, "x", diagnostics.imuStartupGyroStdRaw[0]);
  appendKeyFloat_(out, depth + 2, "y", diagnostics.imuStartupGyroStdRaw[1]);
  appendKeyFloat_(out, depth + 2, "z", diagnostics.imuStartupGyroStdRaw[2], false);
  appendIndent_(out, depth + 1);
  out += F("},\n");
  appendKeyFloat_(out, depth + 1, "accel_magnitude_mean_g", diagnostics.imuStartupAccelMagnitudeMeanG);
  appendKeyFloat_(out, depth + 1, "accel_magnitude_std_g", diagnostics.imuStartupAccelMagnitudeStdG);
  appendKeyFloat_(out, depth + 1, "maximum_gyro_magnitude_dps", diagnostics.imuStartupMaximumGyroMagnitudeDps);
  appendKey_(out, depth + 1, "temperature_deg_c");
  out += F("{\n");
  appendKeyUInt_(out, depth + 2, "samples", diagnostics.imuStartupTemperatureSamples);
  appendKeyFloat_(out, depth + 2, "mean", diagnostics.imuStartupTemperatureMeanC);
  appendKeyFloat_(out, depth + 2, "minimum", diagnostics.imuStartupTemperatureMinimumC);
  appendKeyFloat_(out, depth + 2, "maximum", diagnostics.imuStartupTemperatureMaximumC, false);
  appendIndent_(out, depth + 1);
  out += F("}\n");
  appendIndent_(out, depth);
  out += F("},\n");
}

void appendCsvRefByHeader_(MetadataOutput& out, uint8_t depth, const char* header) {
  appendKey_(out, depth, "csv_ref");
  out += F("{ \"by\": \"header\", \"header\": ");
  appendJsonString_(out, header);
  out += F(" },\n");
}

void appendCsvRefByIndex_(MetadataOutput& out, uint8_t depth, uint8_t index) {
  appendKey_(out, depth, "csv_ref");
  out += F("{ \"by\": \"index\", \"index\": ");
  out += String((unsigned)index);
  out += F(" },\n");
}

bool hasText_(const char* s) {
  return s && *s;
}

const TimingSummary& emptyTimingSummary_() {
  static const TimingSummary empty;
  return empty;
}

const StorageTimingStats& emptyStorageTiming_() {
  static const StorageTimingStats empty;
  return empty;
}

const ExternalAdcTimingStats& emptyExternalAdcTiming_() {
  static const ExternalAdcTimingStats empty;
  return empty;
}

const SensorTimingStats& emptySensorTiming_() {
  static const SensorTimingStats empty;
  return empty;
}

const I2CBusSchedulerTimingStats& emptyI2CSchedulerTiming_() {
  static const I2CBusSchedulerTimingStats empty;
  return empty;
}

void appendTimingSummary_(MetadataOutput& out, uint8_t depth, const char* key, const TimingSummary& s, bool comma = true) {
  appendKey_(out, depth, key);
  out += F("{\n");
  appendKeyUInt_(out, depth + 1, "count", s.count);
  appendKeyUInt_(out, depth + 1, "min_us", s.minUs);
  appendKeyFloat_(out, depth + 1, "avg_us", TimingStats_avgUs(s));
  appendKeyUInt_(out, depth + 1, "max_us", s.maxUs);
  appendKeyUInt64_(out, depth + 1, "total_us", s.totalUs);
  appendKey_(out, depth + 1, "buckets_us");
  out += F("{\n");
  appendKeyUInt_(out, depth + 2, "lt_250", s.bucketLt250);
  appendKeyUInt_(out, depth + 2, "250_500", s.bucket250To500);
  appendKeyUInt_(out, depth + 2, "500_1000", s.bucket500To1000);
  appendKeyUInt_(out, depth + 2, "1000_1500", s.bucket1000To1500);
  appendKeyUInt_(out, depth + 2, "1500_2000", s.bucket1500To2000);
  appendKeyUInt_(out, depth + 2, "ge_2000", s.bucketGe2000, false);
  appendIndent_(out, depth + 1);
  out += F("}\n");
  appendIndent_(out, depth);
  out += comma ? F("},\n") : F("}\n");
}

void appendAdcTiming_(MetadataOutput& out, uint8_t depth, const ExternalAdcTimingStats& stats, bool comma = true) {
  appendKey_(out, depth, "external_adc_timing");
  out += F("{\n");
  bool wroteAny = false;
  for (uint8_t adc = 0; adc < ExternalAdcTimingStats::kMaxAdcs; ++adc) {
    const auto& a = stats.adc[adc];
    if (!a.present && a.activeChannels == 0 && a.scanUs.count == 0) continue;
    if (wroteAny) out += F(",\n");
    wroteAny = true;

    char key[8];
    snprintf(key, sizeof(key), "adc%u", (unsigned)adc);
    appendKey_(out, depth + 1, key);
    out += F("{\n");
    appendKeyBool_(out, depth + 2, "present", a.present);
    appendKeyBool_(out, depth + 2, "async_running", a.asyncRunning);
    appendKeyUInt_(out, depth + 2, "active_channels", a.activeChannels);
    appendKeyUInt_(out, depth + 2, "configured_sps", a.configuredSps);
    appendKeyUInt_(out, depth + 2, "wait_timeouts", a.waitTimeouts);
    appendKeyUInt_(out, depth + 2, "drdy_already_ready", a.drdyAlreadyReady);
    appendTimingSummary_(out, depth + 2, "scan_us", a.scanUs);
    appendTimingSummary_(out, depth + 2, "async_loop_us", a.asyncLoopUs);
    appendTimingSummary_(out, depth + 2, "config_us", a.configUs);
    appendTimingSummary_(out, depth + 2, "start_us", a.startUs);
    appendTimingSummary_(out, depth + 2, "wait_us", a.waitUs);
    appendTimingSummary_(out, depth + 2, "read_us", a.readUs);
    appendKey_(out, depth + 2, "channels");
    out += F("{\n");
    bool wroteChannel = false;
    for (uint8_t ch = 0; ch < ExternalAdcTimingStats::kMaxChannels; ++ch) {
      const auto& c = a.channel[ch];
      if (c.totalUs.count == 0 && c.waitUs.count == 0 && c.rowUses == 0) continue;
      if (wroteChannel) out += F(",\n");
      wroteChannel = true;
      char chKey[8];
      snprintf(chKey, sizeof(chKey), "ch%u", (unsigned)ch);
      appendKey_(out, depth + 3, chKey);
      out += F("{\n");
      appendTimingSummary_(out, depth + 4, "total_us", c.totalUs);
      appendTimingSummary_(out, depth + 4, "wait_us", c.waitUs);
      appendTimingSummary_(out, depth + 4, "row_age_us", c.rowAgeUs);
      appendKeyUInt_(out, depth + 4, "acquire_ok", c.acquireOk);
      appendKeyUInt_(out, depth + 4, "acquire_fail", c.acquireFail);
      appendKeyUInt_(out, depth + 4, "row_uses", c.rowUses);
      appendKeyUInt_(out, depth + 4, "row_fresh", c.rowFresh);
      appendKeyUInt_(out, depth + 4, "row_reused", c.rowReused);
      appendKeyUInt_(out, depth + 4, "row_no_sample", c.rowNoSample, false);
      appendIndent_(out, depth + 3);
      out += F("}");
    }
    if (wroteChannel) out += '\n';
    appendIndent_(out, depth + 2);
    out += F("}\n");
    appendIndent_(out, depth + 1);
    out += F("}");
  }
  if (wroteAny) out += '\n';
  appendIndent_(out, depth);
  out += comma ? F("},\n") : F("}\n");
}

void appendSensorTiming_(MetadataOutput& out, uint8_t depth, const SensorTimingStats& stats, bool comma = true) {
  appendKey_(out, depth, "sensor_timing");
  out += F("{\n");
  appendKeyUInt_(out, depth + 1, "sensor_count", stats.sensorCount);
  appendKey_(out, depth + 1, "sensors");
  out += F("{\n");

  bool wroteAny = false;
  for (uint8_t i = 0; i < SensorTimingStats::kMaxSensors; ++i) {
    const auto& s = stats.sensor[i];
    if (!s.present && s.sampleUs.count == 0) continue;
    if (wroteAny) out += F(",\n");
    wroteAny = true;

    char key[12];
    snprintf(key, sizeof(key), "sensor%u", (unsigned)i);
    appendKey_(out, depth + 2, key);
    out += F("{\n");
    appendKeyBool_(out, depth + 3, "present", s.present);
    appendKeyBool_(out, depth + 3, "muted", s.muted);
    appendKeyBool_(out, depth + 3, "synchronous", s.synchronous);
    appendKeyString_(out, depth + 3, "name", s.name);
    appendKeyString_(out, depth + 3, "label", s.label);
    appendKeyUInt_(out, depth + 3, "column_count", s.columnCount);
    appendTimingSummary_(out, depth + 3, "sample_us", s.sampleUs, false);
    appendIndent_(out, depth + 2);
    out += F("}");
  }
  if (wroteAny) out += '\n';
  appendIndent_(out, depth + 1);
  out += F("}\n");
  appendIndent_(out, depth);
  out += comma ? F("},\n") : F("}\n");
}

void appendI2CSchedulerTiming_(MetadataOutput& out,
                               uint8_t depth,
                               const I2CBusSchedulerTimingStats& stats,
                               bool comma = true) {
  appendKey_(out, depth, "i2c_scheduler_timing");
  out += F("{\n");
  appendKeyUInt_(out, depth + 1, "client_count", stats.clientCount);

  appendKey_(out, depth + 1, "buses");
  out += F("{\n");
  bool wroteBus = false;
  for (uint8_t bus = 0; bus < I2CBusSchedulerTimingStats::kMaxBuses; ++bus) {
    const auto& b = stats.bus[bus];
    if (!b.present && !b.running && b.clientCount == 0 && b.acquireLoopUs.count == 0) continue;
    if (wroteBus) out += F(",\n");
    wroteBus = true;
    char key[8];
    snprintf(key, sizeof(key), "bus%u", (unsigned)bus);
    appendKey_(out, depth + 2, key);
    out += F("{\n");
    appendKeyBool_(out, depth + 3, "present", b.present);
    appendKeyBool_(out, depth + 3, "running", b.running);
    appendKeyUInt_(out, depth + 3, "client_count", b.clientCount);
    appendKeyUInt_(out, depth + 3, "hz", b.hz);
    appendTimingSummary_(out, depth + 3, "acquire_loop_us", b.acquireLoopUs, false);
    appendIndent_(out, depth + 2);
    out += F("}");
  }
  if (wroteBus) out += '\n';
  appendIndent_(out, depth + 1);
  out += F("},\n");

  appendKey_(out, depth + 1, "clients");
  out += F("{\n");
  bool wroteClient = false;
  for (uint8_t i = 0; i < I2CBusSchedulerTimingStats::kMaxClients; ++i) {
    const auto& c = stats.client[i];
    if (!c.present && c.acquireUs.count == 0 && c.rowUses == 0) continue;
    if (wroteClient) out += F(",\n");
    wroteClient = true;
    char key[12];
    snprintf(key, sizeof(key), "client%u", (unsigned)i);
    appendKey_(out, depth + 2, key);
    out += F("{\n");
    appendKeyBool_(out, depth + 3, "present", c.present);
    appendKeyBool_(out, depth + 3, "active", c.active);
    appendKeyString_(out, depth + 3, "name", c.name);
    appendKeyString_(out, depth + 3, "kind", c.kind);
    appendKeyUInt_(out, depth + 3, "bus", c.busIndex);
    appendKeyUInt_(out, depth + 3, "address", c.address);
    appendKeyUInt_(out, depth + 3, "target_rate_hz", c.targetRateHz);
    appendKeyUInt_(out, depth + 3, "period_us", c.periodUs);
    appendKeyUInt_(out, depth + 3, "acquire_ok", c.acquireOk);
    appendKeyUInt_(out, depth + 3, "acquire_fail", c.acquireFail);
    appendKeyUInt_(out, depth + 3, "row_uses", c.rowUses);
    appendKeyUInt_(out, depth + 3, "row_fresh", c.rowFresh);
    appendKeyUInt_(out, depth + 3, "row_reused", c.rowReused);
    appendKeyUInt_(out, depth + 3, "row_no_sample", c.rowNoSample);
    appendKeyUInt_(out, depth + 3, "acquire_fail_streak_max", c.acquireFailStreakMax);
    appendKeyUInt_(out, depth + 3, "row_reuse_streak_max", c.rowReuseStreakMax);
    appendKeyUInt_(out, depth + 3, "row_no_sample_streak_max", c.rowNoSampleStreakMax);
    appendTimingSummary_(out, depth + 3, "acquire_us", c.acquireUs);
    appendTimingSummary_(out, depth + 3, "row_age_us", c.rowAgeUs, false);
    appendIndent_(out, depth + 2);
    out += F("}");
  }
  if (wroteClient) out += '\n';
  appendIndent_(out, depth + 1);
  out += F("}\n");
  appendIndent_(out, depth);
  out += comma ? F("},\n") : F("}\n");
}

void appendI2CBusDiagnostics_(MetadataOutput& out,
                              uint8_t depth,
                              const board::BoardProfile* bp,
                              bool comma = true) {
  appendKey_(out, depth, "i2c_buses");
  out += F("{\n");
  appendKeyString_(out, depth + 1, "board", bp ? bp->name : "");
  appendKeyUInt_(out, depth + 1, "count", bp ? bp->i2c_count : 0);
  appendKey_(out, depth + 1, "buses");
  out += F("{\n");

  bool wroteAny = false;
  if (bp) {
    const uint8_t count = (bp->i2c_count < board::BOARD_MAX_I2C_BUSES)
      ? bp->i2c_count
      : board::BOARD_MAX_I2C_BUSES;
    for (uint8_t i = 0; i < count; ++i) {
      const auto& bus = bp->i2c[i];
      if (wroteAny) out += F(",\n");
      wroteAny = true;
      char key[8];
      snprintf(key, sizeof(key), "bus%u", (unsigned)i);
      appendKey_(out, depth + 2, key);
      out += F("{\n");
      appendKeyBool_(out, depth + 3, "present", bus.present);
      appendKeyInt_(out, depth + 3, "sda", bus.sda);
      appendKeyInt_(out, depth + 3, "scl", bus.scl);
      appendKeyUInt_(out, depth + 3, "hz", bus.hz, false);
      appendIndent_(out, depth + 2);
      out += F("}");
    }
  }
  if (wroteAny) out += '\n';
  appendIndent_(out, depth + 1);
  out += F("}\n");
  appendIndent_(out, depth);
  out += comma ? F("},\n") : F("}\n");
}

void appendRunStats_(MetadataOutput& out, uint8_t depth, const LogMetadataContext& ctx, bool comma = true) {
  appendKey_(out, depth, "run_stats");
  out += F("{\n");
  appendKeyUInt_(out, depth + 1, "samples_dropped", ctx.samplesDropped);
  appendKeyUInt_(out, depth + 1, "queue_max", ctx.queueMax);
  appendKeyUInt_(out, depth + 1, "queue_depth", ctx.queueDepth);
  appendKeyUInt_(out, depth + 1, "flush_count", ctx.flushCount);
  appendKeyUInt_(out, depth + 1, "flush_max_ms", ctx.flushMaxMs);
  const float avgFlush = ctx.flushCount ? (float)((double)ctx.flushTotalMs / (double)ctx.flushCount) : 0.0f;
  appendKeyFloat_(out, depth + 1, "flush_avg_ms", avgFlush);
  appendKeyUInt64_(out, depth + 1, "flush_total_ms", ctx.flushTotalMs);
#if BODAQS_TIMING_INSTRUMENTATION
  appendKeyUInt_(out, depth + 1, "buffer_size", ctx.bufferSize);
  appendKeyUInt_(out, depth + 1, "sampler_late_ticks", ctx.samplerLateTicks);
  appendKeyUInt_(out, depth + 1, "sampler_late_max_lag_ms", ctx.samplerLateMaxLagMs);
  appendKeyUInt_(out, depth + 1, "missed_sample_slots", ctx.missedSampleSlots);
  const StorageTimingStats& storageTiming = ctx.storageTiming ? *ctx.storageTiming : emptyStorageTiming_();
  appendTimingSummary_(out, depth + 1, "sample_once_us", ctx.sampleOnceUs ? *ctx.sampleOnceUs : emptyTimingSummary_());
  appendTimingSummary_(out, depth + 1, "sensor_sample_us", ctx.sensorSampleUs ? *ctx.sensorSampleUs : emptyTimingSummary_());
  appendTimingSummary_(out, depth + 1, "enqueue_us", ctx.enqueueUs ? *ctx.enqueueUs : emptyTimingSummary_());
  appendTimingSummary_(out, depth + 1, "storage_row_write_us", storageTiming.rowWriteUs);
  appendTimingSummary_(out, depth + 1, "storage_drain_loop_us", storageTiming.drainLoopUs);
  appendKeyUInt_(out, depth + 1, "storage_drain_loops", storageTiming.drainLoops);
  appendKeyUInt_(out, depth + 1, "storage_drain_rows", storageTiming.drainRows);
  appendAdcTiming_(out, depth + 1, ctx.externalAdcTiming ? *ctx.externalAdcTiming : emptyExternalAdcTiming_());
  appendSensorTiming_(out, depth + 1, ctx.sensorTiming ? *ctx.sensorTiming : emptySensorTiming_());
  appendI2CSchedulerTiming_(out, depth + 1, ctx.i2cSchedulerTiming ? *ctx.i2cSchedulerTiming : emptyI2CSchedulerTiming_());
  appendI2CBusDiagnostics_(out, depth + 1, ctx.boardProfile, false);
#else
  appendKeyUInt_(out, depth + 1, "buffer_size", ctx.bufferSize, false);
#endif
  appendIndent_(out, depth);
  out += comma ? F("},\n") : F("}\n");
}

void makeUniqueColumnId_(const SensorColumnDescriptor* cols,
                         uint16_t upto,
                         const SensorColumnDescriptor& current,
                         char* out,
                         size_t cap) {
  if (!out || cap == 0) return;
  const char* base = current.columnId[0] ? current.columnId : current.csvHeader;
  if (!base || !*base) base = "signal";

  snprintf(out, cap, "%s", base);
  bool duplicate = false;
  for (uint16_t i = 0; i < upto; ++i) {
    const char* prev = cols[i].columnId[0] ? cols[i].columnId : cols[i].csvHeader;
    if (prev && strcmp(prev, out) == 0) {
      duplicate = true;
      break;
    }
  }

  if (duplicate) {
    snprintf(out, cap, "%s_%u", base, (unsigned)upto);
  }
}

void appendDeviceConfig_(MetadataOutput& out, const SensorDeviceConfigDescriptor& cfg) {
  appendKey_(out, 3, "device_config");
  out += F("{\n");
  appendKeyString_(out, 4, "kind", cfg.kind);
  appendKeyString_(out, 4, "policy", cfg.policy[0] ? cfg.policy : "read_only");
  appendKeyString_(out, 4, "status", cfg.status);
  if (hasText_(cfg.requestedSlowFilter)) appendKeyString_(out, 4, "requested_slow_filter", cfg.requestedSlowFilter);
  if (hasText_(cfg.writeStatus)) appendKeyString_(out, 4, "write_status", cfg.writeStatus);
  appendKeyBool_(out, 4, "read_ok", cfg.readOk);

  appendKey_(out, 4, "registers");
  out += F("{\n");
  appendKeyUInt_(out, 5, "zpos", cfg.zpos);
  appendKeyUInt_(out, 5, "mpos", cfg.mpos);
  appendKeyUInt_(out, 5, "mang", cfg.mang);
  appendKeyUInt_(out, 5, "conf", cfg.conf);
  appendKeyHex16_(out, 5, "conf_hex", cfg.conf);
  appendKeyUInt_(out, 5, "raw_angle", cfg.rawAngle);
  appendKeyUInt_(out, 5, "angle", cfg.angle);
  appendKeyUInt_(out, 5, "status", cfg.statusReg);
  appendKeyHex8_(out, 5, "status_hex", cfg.statusReg);
  appendKeyUInt_(out, 5, "agc", cfg.agc);
  appendKeyUInt_(out, 5, "magnitude", cfg.magnitude, false);
  appendIndent_(out, 4);
  out += F("},\n");

  appendKey_(out, 4, "decoded");
  out += F("{\n");
  appendKeyString_(out, 5, "power_mode", cfg.readOk ? cfg.confPowerMode : "");
  appendKeyString_(out, 5, "hysteresis", cfg.readOk ? cfg.confHysteresis : "");
  appendKeyString_(out, 5, "output_stage", cfg.readOk ? cfg.confOutputStage : "");
  appendKeyString_(out, 5, "pwm_frequency", cfg.readOk ? cfg.confPwmFrequency : "");
  appendKeyString_(out, 5, "slow_filter", cfg.readOk ? cfg.confSlowFilter : "");
  appendKeyString_(out, 5, "fast_filter_threshold", cfg.readOk ? cfg.confFastFilterThreshold : "");
  appendKeyBool_(out, 5, "watchdog", cfg.readOk && cfg.confWatchdog, false);
  appendIndent_(out, 4);
  out += F("}\n");

  appendIndent_(out, 3);
  out += F("},\n");
}

void appendImuRuntimeDiagnostics_(MetadataOutput& out, uint8_t depth, bool comma = true) {
  uint8_t imuCount = 0;
  const uint8_t sensorCount = SensorManager::count();
  SensorRuntimeDiagnostics diagnostics;
  for (uint8_t i = 0; i < sensorCount; ++i) {
    if (SensorManager::describeRuntimeDiagnosticsAt(i, diagnostics) &&
        diagnostics.present && diagnostics.hasImuSession) {
      ++imuCount;
    }
  }

  appendKey_(out, depth, "imu_runtime_diagnostics");
  out += F("{\n");
  appendKeyUInt_(out, depth + 1, "sensor_count", imuCount);
  appendKey_(out, depth + 1, "sensors");
  out += F("{\n");
  bool wrote = false;
  for (uint8_t i = 0; i < sensorCount; ++i) {
    if (!SensorManager::describeRuntimeDiagnosticsAt(i, diagnostics) ||
        !diagnostics.present || !diagnostics.hasImuSession) {
      continue;
    }
    if (wrote) out += F(",\n");
    wrote = true;
    appendIndent_(out, depth + 2);
    appendJsonString_(out, diagnostics.sensorName);
    out += F(": {\n");
    appendKeyUInt_(out, depth + 3, "device_state", diagnostics.imuDeviceState);
    appendKeyUInt_(out, depth + 3, "initialization_attempts", diagnostics.imuInitializationAttempts);
    appendKeyUInt_(out, depth + 3, "initialization_failures", diagnostics.imuInitializationFailures);
    appendKeyUInt_(out, depth + 3, "initialization_failure_step", diagnostics.imuInitializationFailureStep);
    appendKeyInt_(out, depth + 3, "initialization_api_result", diagnostics.imuInitializationApiResult);
    appendKeyBool_(out, depth + 3, "initialization_chip_id_read", diagnostics.imuInitializationChipIdRead);
    appendKeyBool_(out, depth + 3, "initialization_chip_id_matched", diagnostics.imuInitializationChipIdMatched);
    appendKeyHex8_(out, depth + 3, "initialization_chip_id", diagnostics.imuInitializationChipId);
    appendKeyBool_(out, depth + 3, "initialization_cleanup_attempted", diagnostics.imuInitializationCleanupAttempted);
    appendKeyBool_(out, depth + 3, "initialization_cleanup_ok", diagnostics.imuInitializationCleanupOk);
    appendKeyUInt64_(out, depth + 3, "drain_calls", diagnostics.imuDrainCalls);
    appendKeyUInt64_(out, depth + 3, "drain_passes", diagnostics.imuDrainPasses);
    appendKeyUInt64_(out, depth + 3, "empty_passes", diagnostics.imuEmptyPasses);
    appendKeyUInt64_(out, depth + 3, "drain_pass_limit_hits", diagnostics.imuDrainPassLimitHits);
    appendKeyUInt64_(out, depth + 3, "fifo_bytes_read", diagnostics.imuFifoBytesRead);
    appendKeyUInt64_(out, depth + 3, "fifo_frames_parsed", diagnostics.imuFifoFramesParsed);
    appendKeyUInt64_(out, depth + 3, "sensor_time_frames", diagnostics.imuSensorTimeFrames);
    appendKeyUInt64_(out, depth + 3, "missing_sensor_time_batches", diagnostics.imuMissingSensorTimeBatches);
    appendKeyUInt64_(out, depth + 3, "fifo_skip_control_frames", diagnostics.imuSkipControlFrames);
    appendKeyUInt64_(out, depth + 3, "fifo_overflow_events", diagnostics.imuFifoOverflowEvents);
    appendKeyUInt64_(out, depth + 3, "fifo_full_observations", diagnostics.imuFifoFullObservations);
    appendKeyUInt64_(out, depth + 3, "hardware_skipped_frames", diagnostics.imuHardwareSkippedFrames);
    appendKeyUInt64_(out, depth + 3, "unpaired_frames", diagnostics.imuUnpairedFrames);
    appendKeyUInt64_(out, depth + 3, "input_config_frames", diagnostics.imuInputConfigFrames);
    appendKeyUInt64_(out, depth + 3, "invalid_headers", diagnostics.imuInvalidHeaders);
    appendKeyUInt64_(out, depth + 3, "partial_frames", diagnostics.imuPartialFrames);
    appendKeyUInt64_(out, depth + 3, "overread_frames", diagnostics.imuOverreadFrames);
    appendKeyUInt64_(out, depth + 3, "parser_output_drops", diagnostics.imuParserOutputDrops);
    appendKeyUInt64_(out, depth + 3, "samples_enqueued", diagnostics.imuSamplesEnqueued);
    appendKeyUInt64_(out, depth + 3, "samples_emitted", diagnostics.imuSamplesEmitted);
    appendKeyUInt64_(out, depth + 3, "samples_intentionally_decimated", diagnostics.imuSamplesIntentionallyDecimated);
    appendKeyUInt64_(out, depth + 3, "queue_drops", diagnostics.imuQueueDrops);
    appendKeyUInt_(out, depth + 3, "queue_capacity", diagnostics.imuQueueCapacity);
    appendKeyUInt_(out, depth + 3, "queue_high_water", diagnostics.imuQueueHighWater);
    appendKeyUInt_(out, depth + 3, "final_queue_depth", diagnostics.imuFinalQueueDepth);
    appendKeyUInt64_(out, depth + 3, "pre_session_queue_discards", diagnostics.imuPreSessionQueueDiscards);
    appendKeyUInt64_(out, depth + 3, "explicit_queue_discards", diagnostics.imuExplicitQueueDiscards);
    appendKeyUInt64_(out, depth + 3, "temperature_reads", diagnostics.imuTemperatureReads);
    appendKeyUInt64_(out, depth + 3, "temperature_read_failures", diagnostics.imuTemperatureReadFailures);
    appendKeyUInt64_(out, depth + 3, "ioc_offset_read_attempts", diagnostics.imuIocOffsetReadAttempts);
    appendKeyUInt64_(out, depth + 3, "ioc_offset_read_failures", diagnostics.imuIocOffsetReadFailures);
    appendKeyUInt64_(out, depth + 3, "ioc_offset_snapshot_drops", diagnostics.imuIocOffsetSnapshotDrops);
    appendKeyUInt64_(out, depth + 3, "operational_validation_attempts", diagnostics.imuOperationalValidationAttempts);
    appendKeyUInt64_(out, depth + 3, "operational_validation_failures", diagnostics.imuOperationalValidationFailures);
    appendKeyUInt64_(out, depth + 3, "session_start_validation_attempts", diagnostics.imuSessionStartValidationAttempts);
    appendKeyUInt64_(out, depth + 3, "session_start_validation_failures", diagnostics.imuSessionStartValidationFailures);
    appendKeyUInt_(out, depth + 3, "no_progress_timeout_us", diagnostics.imuNoProgressTimeoutUs);
    appendKeyUInt64_(out, depth + 3, "no_progress_events", diagnostics.imuNoProgressEvents);
    appendKeyUInt_(out, depth + 3, "maximum_no_progress_us", diagnostics.imuMaximumNoProgressUs);
    appendKeyUInt_(out, depth + 3, "last_validation_issues", diagnostics.imuLastValidationIssues);
    appendKeyInt_(out, depth + 3, "last_validation_api_result", diagnostics.imuLastValidationApiResult);
    appendKeyUInt_(out, depth + 3, "last_validation_chip_id", diagnostics.imuLastValidationChipId);
    appendKeyUInt_(out, depth + 3, "last_validation_internal_status", diagnostics.imuLastValidationInternalStatus);
    appendKeyUInt_(out, depth + 3, "last_validation_power_control", diagnostics.imuLastValidationPowerControl);
    appendKeyUInt_(out, depth + 3, "last_validation_fifo_config", diagnostics.imuLastValidationFifoConfig);
    appendKeyUInt_(out, depth + 3, "last_validation_fifo_watermark", diagnostics.imuLastValidationFifoWatermark);
    appendKeyUInt_(out, depth + 3, "last_validation_accel_downsample", diagnostics.imuLastValidationAccelDownsample);
    appendKeyUInt_(out, depth + 3, "last_validation_gyro_downsample", diagnostics.imuLastValidationGyroDownsample);
    appendKeyUInt_(out, depth + 3, "last_validation_accel_filtered", diagnostics.imuLastValidationAccelFiltered);
    appendKeyUInt_(out, depth + 3, "last_validation_gyro_filtered", diagnostics.imuLastValidationGyroFiltered);
    appendKeyUInt64_(out, depth + 3, "fifo_flushes", diagnostics.imuFifoFlushes);
    appendKeyUInt64_(out, depth + 3, "fifo_flush_failures", diagnostics.imuFifoFlushFailures);
    appendKeyUInt64_(out, depth + 3, "stop_drain_attempts", diagnostics.imuStopDrainAttempts);
    appendKeyUInt64_(out, depth + 3, "stop_drain_failures", diagnostics.imuStopDrainFailures);
    appendKeyUInt_(out, depth + 3, "maximum_fifo_bytes_observed", diagnostics.imuMaximumFifoBytesObserved);
    appendKeyUInt_(out, depth + 3, "maximum_drain_duration_us", diagnostics.imuMaximumDrainDurationUs);
    appendKeyUInt_(out, depth + 3, "maximum_drain_failure_streak", diagnostics.imuMaximumDrainFailureStreak);
    appendKeyUInt64_(out, depth + 3, "i2c_operations", diagnostics.imuI2cOperations);
    appendKeyUInt64_(out, depth + 3, "i2c_failures", diagnostics.imuI2cFailures);
    appendKeyUInt64_(out, depth + 3, "i2c_recoveries", diagnostics.imuI2cRecoveries);
    appendKeyUInt_(out, depth + 3, "i2c_maximum_failure_streak", diagnostics.imuI2cMaximumFailureStreak);
    appendKeyUInt64_(out, depth + 3, "i2c_bus_lock_attempts", diagnostics.imuI2cBusLockAttempts);
    appendKeyUInt64_(out, depth + 3, "i2c_bus_lock_timeouts", diagnostics.imuI2cBusLockTimeouts);
    appendKeyUInt64_(out, depth + 3, "i2c_bus_lock_wait_total_us", diagnostics.imuI2cBusLockWaitTotalUs);
    appendKeyUInt_(out, depth + 3, "i2c_bus_lock_wait_maximum_us", diagnostics.imuI2cBusLockWaitMaximumUs);
    appendKey_(out, depth + 3, "i2c_failures_by_stage");
    out += F("{\n");
    appendKeyUInt_(out, depth + 4, "invalid_argument", diagnostics.imuI2cFailureStageCounts[1]);
    appendKeyUInt_(out, depth + 4, "bus_unavailable", diagnostics.imuI2cFailureStageCounts[2]);
    appendKeyUInt_(out, depth + 4, "bus_lock_timeout", diagnostics.imuI2cFailureStageCounts[3]);
    appendKeyUInt_(out, depth + 4, "register_address", diagnostics.imuI2cFailureStageCounts[4]);
    appendKeyUInt_(out, depth + 4, "write_payload", diagnostics.imuI2cFailureStageCounts[5]);
    appendKeyUInt_(out, depth + 4, "end_transmission", diagnostics.imuI2cFailureStageCounts[6]);
    appendKeyUInt_(out, depth + 4, "request_bytes", diagnostics.imuI2cFailureStageCounts[7]);
    appendKeyUInt_(out, depth + 4, "read_bytes", diagnostics.imuI2cFailureStageCounts[8], false);
    appendIndent_(out, depth + 3);
    out += F("},\n");
    appendKeyUInt64_(out, depth + 3, "recovery_attempts", diagnostics.imuRecoveryAttempts);
    appendKeyUInt64_(out, depth + 3, "recovery_successes", diagnostics.imuRecoverySuccesses);
    appendKeyUInt64_(out, depth + 3, "recovery_failures", diagnostics.imuRecoveryFailures);
    appendKeyUInt_(out, depth + 3, "last_recovery_reason", diagnostics.imuLastRecoveryReason);
    appendKeyUInt_(out, depth + 3, "consecutive_recovery_failures", diagnostics.imuConsecutiveRecoveryFailures);
    appendKeyUInt_(out, depth + 3, "recovery_attempts_without_progress", diagnostics.imuRecoveryAttemptsWithoutProgress);
    appendKeyUInt64_(out, depth + 3, "terminal_fault_events", diagnostics.imuTerminalFaultEvents);
    appendKeyBool_(out, depth + 3, "terminal_fault", diagnostics.imuTerminalFault);
    appendImuQualityDiagnostics_(out, depth + 3, diagnostics);
    appendKeyBool_(out, depth + 3, "counter_saturated", diagnostics.imuCounterSaturated, false);
    appendIndent_(out, depth + 2);
    out += F("}");
  }
  if (wrote) out += '\n';
  appendIndent_(out, depth + 1);
  out += F("}\n");
  appendIndent_(out, depth);
  out += comma ? F("},\n") : F("}\n");
}

void appendFloatVector3_(
    MetadataOutput& out,
    uint8_t depth,
    const char* key,
    const float values[3],
    bool comma = true) {
  appendKey_(out, depth, key);
  out += '[';
  for (uint8_t i = 0; i < 3; ++i) {
    if (i) out += F(", ");
    out += String(values[i], 8);
  }
  out += comma ? F("],\n") : F("]\n");
}

void appendRotationMatrix_(
    MetadataOutput& out,
    uint8_t depth,
    const float matrix[3][3],
    bool comma = true) {
  appendKey_(out, depth, "matrix");
  out += F("[\n");
  for (uint8_t row = 0; row < 3; ++row) {
    appendIndent_(out, depth + 1);
    out += '[';
    for (uint8_t column = 0; column < 3; ++column) {
      if (column) out += F(", ");
      out += String(matrix[row][column], 8);
    }
    out += row < 2 ? F("],\n") : F("]\n");
  }
  appendIndent_(out, depth);
  out += comma ? F("],\n") : F("]\n");
}

void appendImuConfig_(MetadataOutput& out, const SensorImuConfigDescriptor& imu) {
  appendKey_(out, 3, "imu_config");
  out += F("{\n");
  appendKeyString_(out, 4, "contract_id", imu.contractId);
  appendKeyString_(out, 4, "imu_id", imu.imuId);
  appendKeyString_(out, 4, "domain", imu.domain);
  if (hasText_(imu.end)) appendKeyString_(out, 4, "end", imu.end);
  if (hasText_(imu.mountPoint)) appendKeyString_(out, 4, "mount_point", imu.mountPoint);
  // Retained for readers of the original MVP metadata shape.
  appendKeyString_(out, 4, "location", imu.location);
  appendKeyUInt_(out, 4, "i2c_bus", imu.busIndex);
  appendKeyUInt_(out, 4, "i2c_address", imu.address);
  appendKeyUInt_(out, 4, "i2c_clock_hz", imu.i2cClockHz);
  appendKeyUInt_(out, 4, "chip_id", imu.chipId);
  appendKeyBool_(out, 4, "initialization_ok", imu.initializationOk);
  appendKeyString_(out, 4, "requested_profile", imu.profile);
  appendKeyString_(out, 4, "driver_revision", imu.driverRevision);
  appendKeyString_(out, 4, "calibration_ref", imu.calibrationRef);
  appendKeyUInt_(out, 4, "logger_rate_hz", imu.loggerRateHz);
  appendKeyUInt_(out, 4, "imu_rate_hz", imu.imuRateHz);
  appendKeyUInt_(out, 4, "output_rate_hz", imu.outputRateHz);
  appendKeyUInt_(out, 4, "output_decimation_factor", imu.outputDecimationFactor);
  appendKeyString_(out, 4, "output_selection", imu.outputSelection);
  appendKey_(out, 4, "gyro_bias_correction");
  out += F("{\n");
  appendKeyString_(out, 5, "mode", imu.gyroBiasMode);
  appendKeyBool_(out, 5, "hardware_offset_applied", imu.gyroHardwareOffsetApplied);
  appendKeyBool_(out, 5, "offset_register_trace_enabled", imu.iocDiagnosticsEnabled, false);
  appendIndent_(out, 4);
  out += F("},\n");

  appendKeyString_(out, 4, "orientation_status",
                   imu.orientationValid ? "accepted" : "unset");
  if (imu.orientationValid) {
    appendKey_(out, 4, "mount_transform");
    out += F("{\n");
    appendKeyString_(out, 5, "from", "sensor_native");
    appendKeyString_(out, 5, "to", "body_local");
    appendKeyString_(out, 5, "representation", "rotation_matrix");
    appendRotationMatrix_(out, 5, imu.orientationMatrix, false);
    appendIndent_(out, 4);
    out += F("},\n");

    appendKey_(out, 4, "orientation_calibration");
    out += F("{\n");
    appendKeyString_(out, 5, "status", "accepted");
    appendKeyString_(out, 5, "method", "gravity_plus_declared_plane");
    appendKeyString_(out, 5, "declared_plane", imu.orientationPlane);
    appendKeyString_(out, 5, "normal_maps_to", "body_positive_y");
    appendKeyInt_(out, 5, "normal_sign", imu.orientationNormalSign);
    appendKeyFloat_(out, 5, "maximum_roll_deviation_deg",
                    ImuOrientation::kMaximumRollDeviationDeg);
    appendKeyFloat_(out, 5, "observed_roll_deviation_deg",
                    imu.orientationRollDeviationDeg);
    appendKeyUInt64_(out, 5, "sample_count", imu.orientationSampleCount);
    appendKeyUInt64_(out, 5, "captured_at_unix_ms",
                     imu.orientationCapturedAtUnixMs);
    appendFloatVector3_(out, 5, "mean_accel_raw", imu.orientationMeanAccelRaw);
    appendKeyFloat_(out, 5, "accel_magnitude_mean_g",
                    imu.orientationAccelMagnitudeMeanG);
    appendKeyFloat_(out, 5, "accel_magnitude_std_g",
                    imu.orientationAccelMagnitudeStdG);
    appendKeyFloat_(out, 5, "gyro_std_maximum_dps",
                    imu.orientationGyroStdMaximumDps);
    appendKeyFloat_(out, 5, "gyro_magnitude_maximum_dps",
                    imu.orientationMaximumGyroMagnitudeDps, false);
    appendIndent_(out, 4);
    out += F("},\n");
  }

  appendKey_(out, 4, "effective_config");
  out += F("{\n");
  appendKeyBool_(out, 5, "matched", imu.effectiveConfigMatched);
  appendKeyUInt_(out, 5, "config_file_major", imu.configFileMajor);
  appendKeyUInt_(out, 5, "config_file_minor", imu.configFileMinor);
  appendKeyUInt_(out, 5, "accel_odr_hz", 200);
  appendKeyUInt_(out, 5, "accel_range_g", 16);
  appendKeyString_(out, 5, "accel_bandwidth", "normal_avg4");
  appendKeyString_(out, 5, "accel_filter_performance", "performance_optimized");
  appendKeyUInt_(out, 5, "gyro_odr_hz", 200);
  appendKeyUInt_(out, 5, "gyro_range_dps", 2000);
  appendKeyString_(out, 5, "gyro_bandwidth", "normal");
  appendKeyString_(out, 5, "gyro_noise_performance", "power_optimized");
  appendKeyString_(out, 5, "gyro_filter_performance", "performance_optimized");
  appendKeyUInt_(out, 5, "accel_odr_code", imu.accelOdr);
  appendKeyUInt_(out, 5, "accel_range_code", imu.accelRange);
  appendKeyUInt_(out, 5, "accel_bandwidth_code", imu.accelBandwidth);
  appendKeyUInt_(out, 5, "accel_filter_performance_code", imu.accelFilterPerformance);
  appendKeyUInt_(out, 5, "gyro_odr_code", imu.gyroOdr);
  appendKeyUInt_(out, 5, "gyro_range_code", imu.gyroRange);
  appendKeyUInt_(out, 5, "gyro_bandwidth_code", imu.gyroBandwidth);
  appendKeyUInt_(out, 5, "gyro_noise_performance_code", imu.gyroNoisePerformance);
  appendKeyUInt_(out, 5, "gyro_filter_performance_code", imu.gyroFilterPerformance, false);
  appendIndent_(out, 4);
  out += F("},\n");

  appendKey_(out, 4, "fifo");
  out += F("{\n");
  appendKeyString_(out, 5, "mode", "header");
  appendKeyString_(out, 5, "content", "accel,gyro,sensor_time");
  appendKeyUInt_(out, 5, "poll_rate_hz", imu.fifoPollRateHz);
  appendKeyUInt_(out, 5, "watermark", imu.fifoWatermark);
  appendKeyUInt_(out, 5, "effective_config", imu.fifoConfig, false);
  appendIndent_(out, 4);
  out += F("},\n");

  appendKey_(out, 4, "sensor_time");
  out += F("{\n");
  appendKeyUInt_(out, 5, "tick_numerator_us", 625);
  appendKeyUInt_(out, 5, "tick_denominator", 16);
  appendKeyUInt_(out, 5, "modulus_ticks", 16777216, false);
  appendIndent_(out, 4);
  out += F("},\n");

  appendKey_(out, 4, "temperature");
  out += F("{\n");
  appendKeyUInt_(out, 5, "observation_rate_hz", imu.temperatureRateHz);
  appendKeyUInt_(out, 5, "freshness_limit_us", imu.temperatureFreshnessUs);
  appendKeyString_(out, 5, "sample_policy", "latest_held_value", false);
  appendIndent_(out, 4);
  out += F("},\n");

  appendKeyUInt_(out, 4, "startup_bias_capture_s", imu.startupBiasCaptureSeconds);
  appendKeyString_(out, 4, "row_policy", "sparse_once_sample_valid");
  appendKeyString_(out, 4, "invalid_placeholder_policy", "zero_except_sample_age_us_nan", false);
  appendIndent_(out, 3);
  out += F("},\n");
}

void appendSensor_(MetadataOutput& out, const SensorMetadataDescriptor& s, bool comma) {
  appendIndent_(out, 2);
  appendJsonString_(out, s.sensorId);
  out += F(": {\n");
  appendKeyString_(out, 3, "name", s.name);
  appendKeyString_(out, 3, "type", s.type);
  if (hasText_(s.domain)) appendKeyString_(out, 3, "domain", s.domain);
  appendKeyString_(out, 3, "raw_unit", s.rawUnit);

  if (s.hasTracking) {
    appendKey_(out, 3, "tracking");
    out += F("{\n");
    appendKeyUInt_(out, 4, "counts_per_turn", s.countsPerTurn);
    appendKeyUInt_(out, 4, "wrap_threshold_counts", s.wrapThresholdCounts);
    appendKeyBool_(out, 4, "assume_turn0_at_start", s.assumeTurn0AtStart, false);
    appendIndent_(out, 3);
    out += F("},\n");
  }

  if (s.hasDeviceConfig) {
    appendDeviceConfig_(out, s.deviceConfig);
  }

  if (s.hasImuConfig) {
    appendImuConfig_(out, s.imuConfig);
  }

  if (s.hasCalibration) {
    appendKey_(out, 3, "calibration");
    out += F("{\n");
    appendKeyString_(out, 4, "type", s.calibrationType[0] ? s.calibrationType : "linear");
    appendKeyString_(out, 4, "input_unit", s.calibrationInputUnit);
    appendKeyString_(out, 4, "output_unit", s.calibrationOutputUnit);
    appendKeyInt_(out, 4, "installed_zero_count", s.installedZeroCount);
    appendKeyInt_(out, 4, "sensor_zero_count", s.sensorZeroCount);
    appendKeyInt_(out, 4, "sensor_full_count", s.sensorFullCount);
    appendKeyFloat_(out, 4, "sensor_full_travel", s.sensorFullTravel);
    if (hasText_(s.direction)) appendKeyString_(out, 4, "direction", s.direction);
    appendKeyBool_(out, 4, "invert", s.invert, false);
    appendIndent_(out, 3);
    out += F("}\n");
  } else {
    appendKeyBool_(out, 3, "calibration_available", false, false);
  }

  appendIndent_(out, 2);
  out += comma ? F("},\n") : F("}\n");
}

void appendSignalColumn_(MetadataOutput& out,
                         const SensorColumnDescriptor* cols,
                         uint16_t idx,
                         bool comma) {
  const SensorColumnDescriptor& c = cols[idx];
  char key[80];
  makeUniqueColumnId_(cols, idx, c, key, sizeof(key));

  appendIndent_(out, 2);
  appendJsonString_(out, key);
  out += F(": {\n");
  appendCsvRefByHeader_(out, 3, c.csvHeader);
  appendKeyString_(out, 3, "class", "signal");
  const char* dtype = "float32";
  switch (c.storageType) {
    case SensorColumnStorageType::UInt16: dtype = "uint16"; break;
    case SensorColumnStorageType::Int16: dtype = "int16"; break;
    case SensorColumnStorageType::Int32: dtype = "int32"; break;
    case SensorColumnStorageType::UInt32: dtype = "uint32"; break;
    case SensorColumnStorageType::Float32: dtype = "float32"; break;
    case SensorColumnStorageType::Automatic:
    default: dtype = c.raw ? "uint32" : "float64"; break;
  }
  appendKeyString_(out, 3, "dtype", dtype);
  appendKeyString_(out, 3, "stream", "primary");
  appendKeyString_(out, 3, "sensor", c.sensorName);
  if (hasText_(c.end)) appendKeyString_(out, 3, "end", c.end);
  appendKeyString_(out, 3, "quantity", c.quantity);
  if (hasText_(c.domain)) appendKeyString_(out, 3, "domain", c.domain);
  if (hasText_(c.mountPoint)) appendKeyString_(out, 3, "mount_point", c.mountPoint);
  if (hasText_(c.component)) appendKeyString_(out, 3, "component", c.component);
  if (hasText_(c.coordinateFrame)) appendKeyString_(out, 3, "coordinate_frame", c.coordinateFrame);
  if (hasText_(c.vectorGroup)) appendKeyString_(out, 3, "vector_group", c.vectorGroup);
  appendKeyString_(out, 3, "unit", c.unit[0] ? c.unit : "");
  if (hasText_(c.kind) || c.raw) appendKeyString_(out, 3, "kind", c.kind[0] ? c.kind : "raw");
  if (hasText_(c.source)) appendKeyString_(out, 3, "source", c.source);
  if (hasText_(c.processingRole)) appendKeyString_(out, 3, "processing_role", c.processingRole);
  if (c.semanticSelectionExcluded) appendKeyBool_(out, 3, "semantic_selection_excluded", true);
  if (c.allowNaN) appendKeyBool_(out, 3, "nan_allowed", true);
  if (hasText_(c.calibrationId)) appendKeyString_(out, 3, "calibration_ref", c.sensorName);

  if (hasText_(c.transformChain)) {
    appendKey_(out, 3, "transform_chain");
    out += '[';
    appendJsonString_(out, c.transformChain);
    out += F("],\n");
  } else {
    appendKey_(out, 3, "transform_chain");
    out += F("[],\n");
  }

  if (c.raw) appendKeyString_(out, 3, "raw_representation", c.source);
  if (hasText_(c.notes)) appendKeyString_(out, 3, "notes", c.notes, false);
  else appendKeyBool_(out, 3, "required", true, false);

  appendIndent_(out, 2);
  out += comma ? F("},\n") : F("}\n");
}

void appendDiagnosticColumn_(MetadataOutput& out,
                             const SensorColumnDescriptor* cols,
                             uint16_t idx,
                             bool comma) {
  const SensorColumnDescriptor& c = cols[idx];
  char key[80];
  makeUniqueColumnId_(cols, idx, c, key, sizeof(key));

  appendIndent_(out, 2);
  appendJsonString_(out, key);
  out += F(": {\n");
  appendCsvRefByHeader_(out, 3, c.csvHeader);
  appendKeyString_(out, 3, "class", "diagnostic");
  const char* dtype = "uint32";
  switch (c.storageType) {
    case SensorColumnStorageType::UInt16: dtype = "uint16"; break;
    case SensorColumnStorageType::Int16: dtype = "int16"; break;
    case SensorColumnStorageType::Int32: dtype = "int32"; break;
    case SensorColumnStorageType::UInt32: dtype = "uint32"; break;
    case SensorColumnStorageType::Float32: dtype = "float32"; break;
    case SensorColumnStorageType::Automatic:
    default: break;
  }
  appendKeyString_(out, 3, "dtype", dtype);
  appendKeyString_(out, 3, "stream", "primary");
  appendKeyString_(out, 3, "sensor", c.sensorName);
  appendKeyString_(out, 3, "metric", c.quantity);
  appendKeyString_(out, 3, "unit", c.unit[0] ? c.unit : "");
  if (hasText_(c.source)) appendKeyString_(out, 3, "source", c.source);
  if (c.allowNaN) appendKeyBool_(out, 3, "nan_allowed", true);
  if (hasText_(c.notes)) appendKeyString_(out, 3, "notes", c.notes, false);
  else appendKeyBool_(out, 3, "required", true, false);

  appendIndent_(out, 2);
  out += comma ? F("},\n") : F("}\n");
}

bool isDigitAt_(const String& s, int index) {
  if (index < 0 || index >= (int)s.length()) return false;
  const char c = s.charAt(index);
  return c >= '0' && c <= '9';
}

bool hasDigits_(const String& s, int start, int count) {
  for (int i = 0; i < count; ++i) {
    if (!isDigitAt_(s, start + i)) return false;
  }
  return true;
}

String localStartedAtFromSessionId_(const char* sessionId) {
  if (!sessionId || !*sessionId) return String();

  String s(sessionId);
  int loggerSep = -1;
  for (int i = 0; i + 1 < (int)s.length(); ++i) {
    if (s.charAt(i) == '_' && s.charAt(i + 1) == '_') {
      loggerSep = i;
    }
  }
  if (loggerSep >= 0 && loggerSep + 2 < (int)s.length()) {
    s = s.substring(loggerSep + 2);
  }

  if (s.length() >= 19
      && hasDigits_(s, 0, 4)
      && s.charAt(4) == '-'
      && hasDigits_(s, 5, 2)
      && s.charAt(7) == '-'
      && hasDigits_(s, 8, 2)
      && s.charAt(10) == '_'
      && hasDigits_(s, 11, 2)
      && s.charAt(13) == '-'
      && hasDigits_(s, 14, 2)
      && s.charAt(16) == '-'
      && hasDigits_(s, 17, 2)) {
    String out = s.substring(0, 19);
    out.replace("_", "T");
    out.setCharAt(13, ':');
    out.setCharAt(16, ':');
    return out;
  }

  if (s.length() >= 13
      && hasDigits_(s, 0, 6)
      && s.charAt(6) == '_'
      && hasDigits_(s, 7, 6)) {
    String out(F("20"));
    out += s.substring(0, 2);
    out += '-';
    out += s.substring(2, 4);
    out += '-';
    out += s.substring(4, 6);
    out += 'T';
    out += s.substring(7, 9);
    out += ':';
    out += s.substring(9, 11);
    out += ':';
    out += s.substring(11, 13);
    return out;
  }

  return String();
}

void appendSynBikeRawColumn_(MetadataOutput& out,
                             const char* key,
                             uint8_t index,
                             const char* end,
                             const SensorManager::SynBikeRawColumnBinding& binding,
                             bool comma) {
  appendIndent_(out, 2);
  appendJsonString_(out, key);
  out += F(": {\n");
  appendCsvRefByIndex_(out, 3, index);
  appendKeyString_(out, 3, "class", "signal");
  appendKeyString_(out, 3, "dtype", "uint32");
  appendKeyString_(out, 3, "stream", "primary");
  if (binding.available && hasText_(binding.sensorName)) appendKeyString_(out, 3, "sensor", binding.sensorName);
  appendKeyString_(out, 3, "end", end);
  appendKeyString_(out, 3, "quantity", "raw");
  if (binding.available && hasText_(binding.domain)) appendKeyString_(out, 3, "domain", binding.domain);
  appendKeyString_(out, 3, "unit", "counts");
  appendKey_(out, 3, "transform_chain");
  out += F("[],\n");
  appendKeyString_(out, 3, "raw_representation",
                   binding.available && hasText_(binding.source) ? binding.source : "unavailable");
  if (binding.invert) appendKeyBool_(out, 3, "inverted_for_export", true);
  appendKeyBool_(out, 3, "required", false, false);
  appendIndent_(out, 2);
  out += comma ? F("},\n") : F("}\n");
}

void appendSynBikeBlankFloatColumn_(MetadataOutput& out,
                                    const char* key,
                                    uint8_t index,
                                    const char* quantity,
                                    bool comma) {
  appendIndent_(out, 2);
  appendJsonString_(out, key);
  out += F(": {\n");
  appendCsvRefByIndex_(out, 3, index);
  appendKeyString_(out, 3, "class", "signal");
  appendKeyString_(out, 3, "dtype", "float64");
  appendKeyString_(out, 3, "stream", "primary");
  appendKeyString_(out, 3, "quantity", quantity);
  appendKeyString_(out, 3, "unit", "");
  appendKeyString_(out, 3, "notes", "Reserved for syn.bike GPS field; firmware currently emits blank values.");
  appendKeyBool_(out, 3, "required", false, false);
  appendIndent_(out, 2);
  out += comma ? F("},\n") : F("}\n");
}

bool writeSynBikeRawMetadata_(const LogMetadataContext& ctx, MetadataOutput& out) {
  SensorManager::SynBikeRawBindings bindings;
  (void)SensorManager::resolveSynBikeRawBindings(bindings);

  const uint16_t sensorCount = SensorManager::describeSensors(nullptr, 0);
  SensorMetadataDescriptor* sensors = sensorCount ? new (std::nothrow) SensorMetadataDescriptor[sensorCount] : nullptr;
  if (sensorCount && !sensors) return false;
  const uint16_t sensorsWritten = SensorManager::describeSensors(sensors, sensorCount);
  String startedAt = hasText_(ctx.startedAtLocal) ? String(ctx.startedAtLocal) : localStartedAtFromSessionId_(ctx.sessionId);

  if (!out.reserve(2048 + (sensorsWritten * 900))) {
    delete[] sensors;
    return false;
  }
  out += F("{\n");

  appendKey_(out, 1, "contract");
  out += F("{\n");
  appendKeyString_(out, 2, "name", "mtb_logger_timeseries");
  appendKeyString_(out, 2, "version", "0.2.0");
  appendKeyString_(out, 2, "sidecar_kind", "session", false);
  appendIndent_(out, 1);
  out += F("},\n");

  appendKey_(out, 1, "data_file");
  out += F("{\n");
  appendKeyString_(out, 2, "path", ctx.csvPath);
  appendKeyString_(out, 2, "delimiter", ",");
  appendKeyBool_(out, 2, "header", false);
  appendKeyUInt_(out, 2, "row_count", ctx.rowCount, false);
  appendIndent_(out, 1);
  out += F("},\n");

  appendKey_(out, 1, "session");
  out += F("{\n");
  appendKeyString_(out, 2, "session_id", ctx.sessionId);
  if (hasText_(ctx.startedAtUtc)) appendKeyString_(out, 2, "started_at_utc", ctx.startedAtUtc);
  if (startedAt.length()) appendKeyString_(out, 2, "started_at_local", startedAt.c_str());
  if (hasText_(ctx.timezone)) appendKeyString_(out, 2, "timezone", ctx.timezone);
  appendKeyString_(out, 2, "notes", "CSV emitted in syn.bike raw import format.", false);
  appendIndent_(out, 1);
  out += F("},\n");

  appendKey_(out, 1, "streams");
  out += F("{\n");
  appendIndent_(out, 2);
  out += F("\"primary\": {\n");
  appendKeyString_(out, 3, "type", "uniform");
  appendKeyString_(out, 3, "time_column", "sample_id");
  appendKeyString_(out, 3, "time_encoding", "sample_index");
  appendKeyString_(out, 3, "time_unit", "sample");
  appendKeyUInt_(out, 3, "sample_rate_hz", ctx.sampleRateHz, false);
  appendIndent_(out, 2);
  out += F("}\n");
  appendIndent_(out, 1);
  out += F("},\n");

  appendKey_(out, 1, "sensors");
  out += F("{\n");
  for (uint16_t i = 0; i < sensorsWritten; ++i) {
    appendSensor_(out, sensors[i], i + 1 < sensorsWritten);
  }
  appendIndent_(out, 1);
  out += F("},\n");

  appendKey_(out, 1, "columns");
  out += F("{\n");
  appendIndent_(out, 2);
  out += F("\"sample_id\": {\n");
  appendCsvRefByIndex_(out, 3, 0);
  appendKeyString_(out, 3, "class", "time");
  appendKeyString_(out, 3, "dtype", "uint32");
  appendKeyString_(out, 3, "stream", "primary");
  appendKeyString_(out, 3, "unit", "sample", false);
  appendIndent_(out, 2);
  out += F("},\n");

  appendSynBikeRawColumn_(out, "front_raw", 1, "front", bindings.front, true);
  appendSynBikeRawColumn_(out, "rear_raw", 2, "rear", bindings.rear, true);
  appendSynBikeBlankFloatColumn_(out, "lat", 3, "latitude", true);
  appendSynBikeBlankFloatColumn_(out, "long", 4, "longitude", true);
  appendSynBikeBlankFloatColumn_(out, "speed", 5, "speed", false);
  appendIndent_(out, 1);
  out += F("},\n");

  appendKey_(out, 1, "qc");
  out += F("{\n");
  appendIndent_(out, 2);
  out += F("\"warnings\": [");
  bool wroteWarning = false;
  if (!bindings.front.available) {
    appendJsonString_(out, "syn_bike_front_raw_not_available");
    wroteWarning = true;
  }
  if (!bindings.rear.available) {
    if (wroteWarning) out += F(", ");
    appendJsonString_(out, "syn_bike_rear_raw_not_available");
  }
  out += F("],\n");
  appendRunStats_(out, 2, ctx);
  appendImuRuntimeDiagnostics_(out, 2, false);
  appendIndent_(out, 1);
  out += F("},\n");

  appendKey_(out, 1, "provenance");
  out += F("{\n");
  appendKeyString_(out, 2, "logger_family", "BODAQS");
  appendKeyString_(out, 2, "generator", "BODAQS firmware log metadata writer");
  appendKeyString_(out, 2, "log_format", ConfigManager::logFormatKey(LogFormat::SynBikeRaw));
  if (hasText_(ctx.generatedAtLocal)) appendKeyString_(out, 2, "metadata_generated_at", ctx.generatedAtLocal, false);
  else appendKeyString_(out, 2, "metadata_generated_at", "", false);
  appendIndent_(out, 1);
  out += F("}\n");

  out += F("}\n");
  delete[] sensors;
  return out.ok();
}

} // namespace

String LogMetadataWriter_metadataPathForCsv(const char* csvPath) {
  String path(csvPath ? csvPath : "");
  const int slash = path.lastIndexOf('/');
  const int dot = path.lastIndexOf('.');
  if (dot > slash) {
    path = path.substring(0, dot);
  }
  path += F(".json");
  return path;
}

static bool writeMetadata_(const LogMetadataContext& ctx, MetadataOutput& out) {
  if (ctx.logFormat == LogFormat::SynBikeRaw) {
    return writeSynBikeRawMetadata_(ctx, out);
  }

  const uint16_t sensorCount = SensorManager::describeSensors(nullptr, 0);
  const uint16_t columnCount = SensorManager::describeSensorColumns(nullptr, 0);

  SensorMetadataDescriptor* sensors = sensorCount ? new (std::nothrow) SensorMetadataDescriptor[sensorCount] : nullptr;
  SensorColumnDescriptor* columns = columnCount ? new (std::nothrow) SensorColumnDescriptor[columnCount] : nullptr;
  if ((sensorCount && !sensors) || (columnCount && !columns)) {
    delete[] sensors;
    delete[] columns;
    return false;
  }

  const uint16_t sensorsWritten = SensorManager::describeSensors(sensors, sensorCount);
  const uint16_t columnsWritten = SensorManager::describeSensorColumns(columns, columnCount);
  const char* timeColumn = ctx.humanReadableTime ? "timestamp" : "timestamp_ms";
  const char* timeEncoding = ctx.humanReadableTime ? "local_time" : "epoch_ms";
  const char* timeUnit = ctx.humanReadableTime ? "time_of_day" : "ms";
  const char* timeDtype = ctx.humanReadableTime ? "string" : "uint64";
  String startedAt = hasText_(ctx.startedAtLocal) ? String(ctx.startedAtLocal) : localStartedAtFromSessionId_(ctx.sessionId);

  if (!out.reserve(2048 + (columnsWritten * 520) + (sensorsWritten * 900))) {
    delete[] sensors;
    delete[] columns;
    return false;
  }
  out += F("{\n");

  appendKey_(out, 1, "contract");
  out += F("{\n");
  appendKeyString_(out, 2, "name", "mtb_logger_timeseries");
  appendKeyString_(out, 2, "version", "0.2.0");
  appendKeyString_(out, 2, "sidecar_kind", "session", false);
  appendIndent_(out, 1);
  out += F("},\n");

  appendKey_(out, 1, "data_file");
  out += F("{\n");
  appendKeyString_(out, 2, "path", ctx.csvPath);
  appendKeyString_(out, 2, "delimiter", ",");
  appendKeyBool_(out, 2, "header", true);
  appendKeyUInt_(out, 2, "row_count", ctx.rowCount, false);
  appendIndent_(out, 1);
  out += F("},\n");

  appendKey_(out, 1, "session");
  out += F("{\n");
  appendKeyString_(out, 2, "session_id", ctx.sessionId);
  if (hasText_(ctx.startedAtUtc)) appendKeyString_(out, 2, "started_at_utc", ctx.startedAtUtc);
  if (startedAt.length()) appendKeyString_(out, 2, "started_at_local", startedAt.c_str());
  if (hasText_(ctx.timezone)) appendKeyString_(out, 2, "timezone", ctx.timezone);
  const char* sessionNote = "";
  if (!startedAt.length()) sessionNote = "Logger RTC was not valid at log start.";
  else if (!hasText_(ctx.timezone)) sessionNote = "Logger timezone was not available.";
  appendKeyString_(out, 2, "notes", sessionNote, false);
  appendIndent_(out, 1);
  out += F("},\n");

  appendKey_(out, 1, "streams");
  out += F("{\n");
  appendIndent_(out, 2);
  out += F("\"primary\": {\n");
  appendKeyString_(out, 3, "type", "uniform");
  appendKeyString_(out, 3, "time_column", timeColumn);
  appendKeyString_(out, 3, "time_encoding", timeEncoding);
  appendKeyString_(out, 3, "time_unit", timeUnit);
  if (ctx.humanReadableTime) appendKeyString_(out, 3, "time_format", "HH:MM:SS.mmm");
  else appendKeyString_(out, 3, "time_anchor", "unix_epoch_utc");
  appendKeyUInt_(out, 3, "sample_rate_hz", ctx.sampleRateHz, false);
  appendIndent_(out, 2);
  out += F("}\n");
  appendIndent_(out, 1);
  out += F("},\n");

  appendKey_(out, 1, "sensors");
  out += F("{\n");
  for (uint16_t i = 0; i < sensorsWritten; ++i) {
    appendSensor_(out, sensors[i], i + 1 < sensorsWritten);
  }
  appendIndent_(out, 1);
  out += F("},\n");

  appendKey_(out, 1, "columns");
  out += F("{\n");
  appendIndent_(out, 2);
  out += F("\"sample_id\": {\n");
  appendCsvRefByHeader_(out, 3, "sample_id");
  appendKeyString_(out, 3, "class", "index");
  appendKeyString_(out, 3, "dtype", "uint32", false);
  appendIndent_(out, 2);
  out += F("},\n");

  appendIndent_(out, 2);
  appendJsonString_(out, timeColumn);
  out += F(": {\n");
  appendCsvRefByHeader_(out, 3, timeColumn);
  appendKeyString_(out, 3, "class", "time");
  appendKeyString_(out, 3, "dtype", timeDtype);
  appendKeyString_(out, 3, "stream", "primary");
  appendKeyString_(out, 3, "unit", timeUnit, false);
  appendIndent_(out, 2);
  out += F("},\n");

  for (uint16_t i = 0; i < columnsWritten; ++i) {
    if (columns[i].diagnostic) appendDiagnosticColumn_(out, columns, i, true);
    else appendSignalColumn_(out, columns, i, true);
  }

  appendIndent_(out, 2);
  out += F("\"mark\": {\n");
  appendCsvRefByHeader_(out, 3, "mark");
  appendKeyString_(out, 3, "class", "event_flag");
  appendKeyString_(out, 3, "dtype", "bool");
  appendKeyString_(out, 3, "stream", "primary");
  appendKeyString_(out, 3, "meaning", "user mark", false);
  appendIndent_(out, 2);
  out += F("}\n");
  appendIndent_(out, 1);
  out += F("},\n");

  appendKey_(out, 1, "qc");
  out += F("{\n");
  appendIndent_(out, 2);
  out += F("\"warnings\": [],\n");
  appendRunStats_(out, 2, ctx);
  appendImuRuntimeDiagnostics_(out, 2, false);
  appendIndent_(out, 1);
  out += F("},\n");

  appendKey_(out, 1, "provenance");
  out += F("{\n");
  appendKeyString_(out, 2, "logger_family", "BODAQS");
  appendKeyString_(out, 2, "generator", "BODAQS firmware log metadata writer");
  if (hasText_(ctx.generatedAtLocal)) {
    appendKeyString_(out, 2, "metadata_generated_at", ctx.generatedAtLocal, false);
  } else {
    appendKeyString_(out, 2, "metadata_generated_at", "", false);
  }
  appendIndent_(out, 1);
  out += F("}\n");

  out += F("}\n");

  delete[] sensors;
  delete[] columns;
  return out.ok();
}

bool LogMetadataWriter_build(const LogMetadataContext& ctx, String& out) {
  out = "";
  StringMetadataOutput writer(out);
  return writeMetadata_(ctx, writer);
}

bool LogMetadataWriter_write(const LogMetadataContext& ctx, Print& out) {
  PrintMetadataOutput writer(out);
  return writeMetadata_(ctx, writer);
}
