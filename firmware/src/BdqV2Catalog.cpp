#include "BdqV2Catalog.h"

#include <stdio.h>
#include <string.h>

namespace {

class JsonBuffer {
public:
  JsonBuffer(char* destination, size_t capacity)
      : destination_(destination), capacity_(capacity), measuring_(!destination) {}

  void append(const char* text) {
    if (!text) text = "";
    append(text, strlen(text));
  }

  void append(const char* text, size_t length) {
    if (!ok_ || length == 0) return;
    if (SIZE_MAX - length_ < length) {
      ok_ = false;
      return;
    }
    if (!measuring_) {
      if (length_ + length >= capacity_) {
        ok_ = false;
        return;
      }
      memcpy(destination_ + length_, text, length);
    }
    length_ += length;
  }

  void appendChar(char value) { append(&value, 1); }

  void appendUnsigned(uint64_t value) {
    char text[24];
    const int length = snprintf(
        text, sizeof(text), "%llu", static_cast<unsigned long long>(value));
    if (length <= 0 || static_cast<size_t>(length) >= sizeof(text)) {
      ok_ = false;
      return;
    }
    append(text, static_cast<size_t>(length));
  }

  void appendString(const char* value) {
    appendChar('"');
    const uint8_t* cursor = reinterpret_cast<const uint8_t*>(value ? value : "");
    while (*cursor) {
      const uint8_t byte = *cursor++;
      switch (byte) {
        case '"': append("\\\""); break;
        case '\\': append("\\\\"); break;
        case '\b': append("\\b"); break;
        case '\f': append("\\f"); break;
        case '\n': append("\\n"); break;
        case '\r': append("\\r"); break;
        case '\t': append("\\t"); break;
        default:
          if (byte < 0x20) {
            char escaped[7];
            snprintf(escaped, sizeof(escaped), "\\u%04x", byte);
            append(escaped);
          } else {
            appendChar(static_cast<char>(byte));
          }
          break;
      }
    }
    appendChar('"');
  }

  bool finish(size_t& length) {
    length = length_;
    if (!ok_) return false;
    if (!measuring_) {
      if (length_ >= capacity_) return false;
      destination_[length_] = '\0';
    }
    return true;
  }

private:
  char* destination_ = nullptr;
  size_t capacity_ = 0;
  size_t length_ = 0;
  bool measuring_ = false;
  bool ok_ = true;
};

bool nonEmpty_(const char* value) {
  return value && value[0] != '\0';
}

size_t storageSize_(const char* storageType) {
  if (!storageType) return 0;
  if (strcmp(storageType, "uint8") == 0 || strcmp(storageType, "int8") == 0) return 1;
  if (strcmp(storageType, "uint16") == 0 || strcmp(storageType, "int16") == 0) return 2;
  if (strcmp(storageType, "uint32") == 0 || strcmp(storageType, "int32") == 0 ||
      strcmp(storageType, "float32") == 0) return 4;
  return 0;
}

void appendKey_(JsonBuffer& out, const char* key) {
  out.appendString(key);
  out.appendChar(':');
}

void appendStringField_(JsonBuffer& out, const char* key, const char* value) {
  appendKey_(out, key);
  out.appendString(value);
}

void appendUnsignedField_(JsonBuffer& out, const char* key, uint64_t value) {
  appendKey_(out, key);
  out.appendUnsigned(value);
}

void appendOptionalStringField_(
    JsonBuffer& out,
    const char* key,
    const char* value) {
  if (!nonEmpty_(value)) return;
  out.appendChar(',');
  appendStringField_(out, key, value);
}

bool uniqueStreams_(const BdqV2StreamDescriptor* streams, size_t streamCount) {
  for (size_t index = 0; index < streamCount; ++index) {
    if (!streams[index].valid()) return false;
    for (size_t previous = 0; previous < index; ++previous) {
      if (streams[index].source.streamId == streams[previous].source.streamId ||
          strcmp(streams[index].streamKey, streams[previous].streamKey) == 0) {
        return false;
      }
    }
  }
  return true;
}

void appendChannel_(
    JsonBuffer& out,
    const BdqV2CatalogChannel& channel,
    const BdqV2StreamDescriptor& stream) {
  out.appendChar('{');
  appendStringField_(out, "field", channel.field);
  out.appendChar(',');
  appendStringField_(out, "quantity", channel.quantity);
  out.appendChar(',');
  appendStringField_(out, "unit", channel.unit);
  out.appendChar(',');
  appendStringField_(out, "storage_type", channel.storageType);
  out.appendChar(',');
  appendUnsignedField_(out, "byte_offset", channel.byteOffset);
  out.appendChar(',');
  appendStringField_(out, "class", channel.columnClass);
  appendOptionalStringField_(out, "component", channel.component);
  appendOptionalStringField_(out, "coordinate_frame", channel.coordinateFrame);
  appendOptionalStringField_(out, "vector_group", channel.vectorGroup);
  appendOptionalStringField_(
      out, "sensor", nonEmpty_(channel.sensor) ? channel.sensor : stream.sensorId);
  appendOptionalStringField_(
      out, "domain", nonEmpty_(channel.domain) ? channel.domain : stream.domain);
  appendOptionalStringField_(
      out, "end", nonEmpty_(channel.end) ? channel.end : stream.end);
  out.appendChar('}');
}

void appendStream_(
    JsonBuffer& out,
    const char* sourceDeviceId,
    const BdqV2StreamDescriptor& stream) {
  out.appendChar('{');
  appendUnsignedField_(out, "stream_id", stream.source.streamId);
  out.appendChar(',');
  appendStringField_(out, "stream_key", stream.streamKey);
  out.appendChar(',');
  appendStringField_(out, "stream_kind", stream.streamKind);
  out.appendChar(',');
  appendKey_(out, "sensor_id");
  if (nonEmpty_(stream.sensorId)) out.appendString(stream.sensorId);
  else out.append("null");
  out.appendChar(',');
  appendStringField_(out, "source_device_id", sourceDeviceId);
  out.appendChar(',');
  appendStringField_(out, "transport", stream.transport);
  out.appendChar(',');
  appendStringField_(out, "clock_id", stream.clockId);
  out.appendChar(',');
  appendStringField_(out, "record_format", stream.recordFormat);
  out.appendChar(',');
  appendUnsignedField_(out, "record_size_bytes", stream.source.recordSizeBytes);

  out.append(",\"timebase\":{");
  appendStringField_(out, "type", "native_ticks");
  out.appendChar(',');
  appendStringField_(out, "native_tick_field", "native_tick");
  out.appendChar(',');
  appendUnsignedField_(out, "native_tick_bits", stream.nativeTickBits);
  out.appendChar(',');
  appendUnsignedField_(out, "native_tick_modulus", stream.source.nativeTickModulus);
  out.append(",\"nominal_tick_period_us\":{");
  appendUnsignedField_(out, "numerator", stream.nominalTickPeriodNumeratorUs);
  out.appendChar(',');
  appendUnsignedField_(out, "denominator", stream.nominalTickPeriodDenominator);
  out.append("},\"nominal_sample_rate_hz\":{");
  appendUnsignedField_(out, "numerator", stream.nominalSampleRateNumeratorHz);
  out.appendChar(',');
  appendUnsignedField_(out, "denominator", stream.nominalSampleRateDenominator);
  out.append("},");
  appendUnsignedField_(out, "expected_sequence_step", stream.expectedSequenceStep);
  out.appendChar(',');
  appendStringField_(out, "clock_relation", stream.clockRelation);
  out.appendChar('}');

  if (nonEmpty_(stream.requestedProfile)) {
    out.append(",\"acquisition\":{");
    appendStringField_(out, "requested_profile", stream.requestedProfile);
    out.appendChar(',');
    appendUnsignedField_(out, "effective_accel_rate_hz", stream.effectiveAccelRateHz);
    out.appendChar(',');
    appendUnsignedField_(out, "effective_gyro_rate_hz", stream.effectiveGyroRateHz);
    out.appendChar('}');
  }

  if (nonEmpty_(stream.domain) || nonEmpty_(stream.end) ||
      nonEmpty_(stream.mountPoint) || nonEmpty_(stream.calibrationRef)) {
    out.append(",\"mounting\":{");
    bool comma = false;
    const struct { const char* key; const char* value; } values[] = {
        {"domain", stream.domain},
        {"end", stream.end},
        {"mount_point", stream.mountPoint},
        {"calibration_ref", stream.calibrationRef},
    };
    for (const auto& value : values) {
      if (!nonEmpty_(value.value)) continue;
      if (comma) out.appendChar(',');
      appendStringField_(out, value.key, value.value);
      comma = true;
    }
    out.appendChar('}');
  }

  out.append(",\"channels\":[");
  for (size_t index = 0; index < stream.channelCount; ++index) {
    if (index) out.appendChar(',');
    appendChannel_(out, stream.channels[index], stream);
  }
  out.append("]");

  out.append(",\"status_flags\":{");
  for (size_t index = 0; index < stream.statusFlagCount; ++index) {
    if (index) out.appendChar(',');
    appendUnsignedField_(
        out, stream.statusFlags[index].name, stream.statusFlags[index].mask);
  }
  out.append("}}");
}

bool serialize_(
    JsonBuffer& out,
    const char* sourceDeviceId,
    const BdqV2StreamDescriptor* streams,
    size_t streamCount,
    size_t& length) {
  if (!nonEmpty_(sourceDeviceId) || !streams || streamCount == 0 ||
      !uniqueStreams_(streams, streamCount)) {
    return false;
  }

  out.append("{\"schema_format\":\"bdq.stream_catalog.v1\","
             "\"endianness\":\"little\","
             "\"record_prefix\":{"
             "\"format\":\"bdq.stream_record_prefix.v1\","
             "\"size_bytes\":12},\"streams\":[");
  for (size_t index = 0; index < streamCount; ++index) {
    if (index) out.appendChar(',');
    appendStream_(out, sourceDeviceId, streams[index]);
  }
  out.append("]}");
  return out.finish(length);
}

}  // namespace

bool BdqV2StreamDescriptor::valid() const {
  if (!source.valid() || !nonEmpty_(streamKey) || !nonEmpty_(streamKind) ||
      !nonEmpty_(transport) || !nonEmpty_(clockId) ||
      !nonEmpty_(clockRelation) || !nonEmpty_(recordFormat) ||
      nativeTickBits == 0 || nativeTickBits > 32 ||
      nominalTickPeriodNumeratorUs == 0 ||
      nominalTickPeriodDenominator == 0 ||
      nominalSampleRateNumeratorHz == 0 ||
      nominalSampleRateDenominator == 0 ||
      expectedSequenceStep == 0 || !channels || channelCount == 0 ||
      !statusFlags || statusFlagCount == 0) {
    return false;
  }
  const uint64_t maximumTickModulus = uint64_t{1} << nativeTickBits;
  if (source.nativeTickModulus > maximumTickModulus) return false;
  for (size_t index = 0; index < channelCount; ++index) {
    const BdqV2CatalogChannel& channel = channels[index];
    const size_t fieldSize = storageSize_(channel.storageType);
    if (!nonEmpty_(channel.field) || !nonEmpty_(channel.quantity) ||
        !nonEmpty_(channel.unit) || !nonEmpty_(channel.storageType) ||
        !nonEmpty_(channel.columnClass) || fieldSize == 0 ||
        static_cast<size_t>(channel.byteOffset) + fieldSize >
            source.recordSizeBytes) {
      return false;
    }
    for (size_t previous = 0; previous < index; ++previous) {
      if (strcmp(channel.field, channels[previous].field) == 0) return false;
    }
  }
  const struct { const char* field; const char* type; uint16_t offset; } prefix[] = {
      {"sequence", "uint32", 0},
      {"native_tick", "uint32", 4},
      {"status_flags", "uint16", 8},
  };
  for (const auto& expected : prefix) {
    bool matched = false;
    for (size_t index = 0; index < channelCount; ++index) {
      const BdqV2CatalogChannel& channel = channels[index];
      if (strcmp(channel.field, expected.field) == 0 &&
          strcmp(channel.storageType, expected.type) == 0 &&
          channel.byteOffset == expected.offset) {
        matched = true;
        break;
      }
    }
    if (!matched) return false;
  }
  for (size_t index = 0; index < statusFlagCount; ++index) {
    if (!nonEmpty_(statusFlags[index].name) || statusFlags[index].mask == 0) {
      return false;
    }
    for (size_t previous = 0; previous < index; ++previous) {
      if (strcmp(statusFlags[index].name, statusFlags[previous].name) == 0 ||
          statusFlags[index].mask == statusFlags[previous].mask) {
        return false;
      }
    }
  }
  return true;
}

namespace BdqV2Catalog {

size_t measure(
    const char* sourceDeviceId,
    const BdqV2StreamDescriptor* streams,
    size_t streamCount) {
  JsonBuffer output(nullptr, 0);
  size_t length = 0;
  return serialize_(output, sourceDeviceId, streams, streamCount, length)
      ? length
      : 0;
}

bool write(
    const char* sourceDeviceId,
    const BdqV2StreamDescriptor* streams,
    size_t streamCount,
    char* destination,
    size_t capacity,
    size_t& jsonLength) {
  jsonLength = 0;
  if (!destination || capacity == 0) return false;
  JsonBuffer output(destination, capacity);
  size_t serializedLength = 0;
  if (!serialize_(
          output, sourceDeviceId, streams, streamCount, serializedLength)) {
    return false;
  }
  jsonLength = serializedLength;
  return true;
}

}  // namespace BdqV2Catalog
