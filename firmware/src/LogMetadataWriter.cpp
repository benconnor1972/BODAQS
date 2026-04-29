#include "LogMetadataWriter.h"

#include "SensorManager.h"

namespace {

void appendIndent_(String& out, uint8_t depth) {
  while (depth--) out += F("  ");
}

void appendJsonString_(String& out, const char* s) {
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

void appendKey_(String& out, uint8_t depth, const char* key) {
  appendIndent_(out, depth);
  appendJsonString_(out, key);
  out += F(": ");
}

void appendKeyString_(String& out, uint8_t depth, const char* key, const char* value, bool comma = true) {
  appendKey_(out, depth, key);
  appendJsonString_(out, value);
  if (comma) out += ',';
  out += '\n';
}

void appendKeyBool_(String& out, uint8_t depth, const char* key, bool value, bool comma = true) {
  appendKey_(out, depth, key);
  out += value ? F("true") : F("false");
  if (comma) out += ',';
  out += '\n';
}

void appendKeyUInt_(String& out, uint8_t depth, const char* key, uint32_t value, bool comma = true) {
  appendKey_(out, depth, key);
  out += String(value);
  if (comma) out += ',';
  out += '\n';
}

void appendKeyUInt64_(String& out, uint8_t depth, const char* key, uint64_t value, bool comma = true) {
  appendKey_(out, depth, key);
  char buf[24];
  snprintf(buf, sizeof(buf), "%llu", (unsigned long long)value);
  out += buf;
  if (comma) out += ',';
  out += '\n';
}

void appendKeyInt_(String& out, uint8_t depth, const char* key, int32_t value, bool comma = true) {
  appendKey_(out, depth, key);
  out += String(value);
  if (comma) out += ',';
  out += '\n';
}

void appendKeyFloat_(String& out, uint8_t depth, const char* key, float value, bool comma = true) {
  appendKey_(out, depth, key);
  out += String(value, 6);
  if (comma) out += ',';
  out += '\n';
}

void appendCsvRefByHeader_(String& out, uint8_t depth, const char* header) {
  appendKey_(out, depth, "csv_ref");
  out += F("{ \"by\": \"header\", \"header\": ");
  appendJsonString_(out, header);
  out += F(" },\n");
}

void appendCsvRefByIndex_(String& out, uint8_t depth, uint8_t index) {
  appendKey_(out, depth, "csv_ref");
  out += F("{ \"by\": \"index\", \"index\": ");
  out += String((unsigned)index);
  out += F(" },\n");
}

bool hasText_(const char* s) {
  return s && *s;
}

void appendRunStats_(String& out, uint8_t depth, const LogMetadataContext& ctx, bool comma = true) {
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
  appendKeyUInt_(out, depth + 1, "buffer_size", ctx.bufferSize, false);
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

void appendSensor_(String& out, const SensorMetadataDescriptor& s, bool comma) {
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
    appendKeyBool_(out, 4, "invert", s.invert, false);
    appendIndent_(out, 3);
    out += F("}\n");
  } else {
    appendKeyBool_(out, 3, "calibration_available", false, false);
  }

  appendIndent_(out, 2);
  out += comma ? F("},\n") : F("}\n");
}

void appendSignalColumn_(String& out,
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
  appendKeyString_(out, 3, "dtype", c.raw ? "uint32" : "float64");
  appendKeyString_(out, 3, "stream", "primary");
  appendKeyString_(out, 3, "sensor", c.sensorName);
  if (hasText_(c.end)) appendKeyString_(out, 3, "end", c.end);
  appendKeyString_(out, 3, "quantity", c.quantity);
  if (hasText_(c.domain)) appendKeyString_(out, 3, "domain", c.domain);
  appendKeyString_(out, 3, "unit", c.unit[0] ? c.unit : "");
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

String localStartedAtFromSessionId_(const char* sessionId) {
  if (!sessionId || strlen(sessionId) < 19) return String();
  String s(sessionId);
  s.replace("_", "T");
  if (s.length() >= 19) {
    s.setCharAt(13, ':');
    s.setCharAt(16, ':');
  }
  return s;
}

void appendSynBikeRawColumn_(String& out,
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

void appendSynBikeBlankFloatColumn_(String& out,
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

bool buildSynBikeRawMetadata_(const LogMetadataContext& ctx, String& out) {
  SensorManager::SynBikeRawBindings bindings;
  (void)SensorManager::resolveSynBikeRawBindings(bindings);

  const uint16_t sensorCount = SensorManager::describeSensors(nullptr, 0);
  SensorMetadataDescriptor* sensors = sensorCount ? new SensorMetadataDescriptor[sensorCount] : nullptr;
  if (sensorCount && !sensors) return false;
  const uint16_t sensorsWritten = SensorManager::describeSensors(sensors, sensorCount);
  String startedAt = hasText_(ctx.startedAtLocal) ? String(ctx.startedAtLocal) : localStartedAtFromSessionId_(ctx.sessionId);

  out.reserve(2048 + (sensorsWritten * 520));
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
  appendRunStats_(out, 2, ctx, false);
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
  return true;
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

bool LogMetadataWriter_build(const LogMetadataContext& ctx, String& out) {
  out = "";
  if (ctx.logFormat == LogFormat::SynBikeRaw) {
    return buildSynBikeRawMetadata_(ctx, out);
  }

  const uint16_t sensorCount = SensorManager::describeSensors(nullptr, 0);
  const uint16_t columnCount = SensorManager::describeSensorColumns(nullptr, 0);

  SensorMetadataDescriptor* sensors = sensorCount ? new SensorMetadataDescriptor[sensorCount] : nullptr;
  SensorColumnDescriptor* columns = columnCount ? new SensorColumnDescriptor[columnCount] : nullptr;
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

  out.reserve(2048 + (columnsWritten * 520) + (sensorsWritten * 520));
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
    appendSignalColumn_(out, columns, i, true);
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
  appendRunStats_(out, 2, ctx, false);
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
  return true;
}
