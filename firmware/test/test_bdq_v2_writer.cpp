#include <cstdio>
#include <cmath>
#include <cstring>
#include <string>
#include <vector>

#include "BMI270BdqV2.h"
#include "BdqV2Catalog.h"
#include "BdqV2Format.h"
#include "BdqV2PrimaryStream.h"
#include "BdqV2StreamQueue.h"
#include "BdqV2Writer.h"

namespace {

class MemorySink final : public BdqV2ByteSink {
public:
    bool write(const uint8_t* data, size_t length) override {
        if (failWrites) return false;
        bytes.insert(bytes.end(), data, data + length);
        return true;
    }

    bool flush() override {
        flushed = true;
        return !failWrites;
    }

    std::vector<uint8_t> bytes;
    bool failWrites = false;
    bool flushed = false;
};

void makeRecord(
        uint8_t* out,
        size_t length,
        uint32_t sequence,
        uint32_t nativeTick,
        uint16_t status = 0,
        int16_t value = 0) {
    std::memset(out, 0, length);
    BdqV2Format::StreamRecordPrefix prefix;
    prefix.sequence = sequence;
    prefix.nativeTick = nativeTick;
    prefix.statusFlags = status;
    BdqV2Format::encodeStreamRecordPrefix(prefix, out, length);
    BdqV2Format::putU16(out + 12, static_cast<uint16_t>(value));
}

std::vector<uint16_t> streamChunkOrder(const std::vector<uint8_t>& bytes) {
    std::vector<uint16_t> result;
    size_t cursor = BdqV2Format::kFileHeaderBytes;
    while (cursor + BdqV2Format::kChunkHeaderBytes <= bytes.size()) {
        const uint8_t* header = bytes.data() + cursor;
        const uint16_t type = BdqV2Format::getU16(header + 6);
        const uint32_t payloadLength = BdqV2Format::getU32(header + 12);
        const uint32_t expectedCrc = BdqV2Format::getU32(header + 16);
        cursor += BdqV2Format::kChunkHeaderBytes;
        if (cursor + payloadLength > bytes.size()) return {};
        if (BdqV2Format::crc32(bytes.data() + cursor, payloadLength) != expectedCrc) {
            return {};
        }
        if (type == static_cast<uint16_t>(BdqV2Format::ChunkType::StreamData)) {
            result.push_back(BdqV2Format::getU16(bytes.data() + cursor));
        }
        cursor += payloadLength;
    }
    if (cursor != bytes.size()) return {};
    return result;
}

}  // namespace

int runBdqV2WriterTests() {
    int passed = 0;
    int failed = 0;

    auto check = [&](bool condition, const char* description) {
        if (condition) {
            ++passed;
        } else {
            std::printf("    FAIL: test_bdq_v2_writer: %s\n", description);
            ++failed;
        }
    };

    {
        BdqV2StreamQueue<16, 4, 2> primaryQueue(
            BdqV2PrimaryStreamSchema::kStreamId, uint64_t{1} << 32);
        SensorColumnDescriptor columns[3];
        std::strcpy(columns[0].columnId, "signed_raw");
        std::strcpy(columns[0].quantity, "raw");
        std::strcpy(columns[0].unit, "count");
        columns[0].storageType = SensorColumnStorageType::Int16;
        columns[0].raw = true;
        std::strcpy(columns[1].columnId, "counter");
        std::strcpy(columns[1].quantity, "counter");
        std::strcpy(columns[1].unit, "count");
        columns[1].storageType = SensorColumnStorageType::UInt32;
        columns[1].diagnostic = true;
        std::strcpy(columns[2].columnId, "optional_value");
        std::strcpy(columns[2].quantity, "value");
        std::strcpy(columns[2].unit, "mm");
        columns[2].storageType = SensorColumnStorageType::Float32;
        columns[2].allowNaN = true;

        BdqV2PrimaryStreamSchema schema;
        check(schema.configure(columns, 3, 200, primaryQueue.source()) &&
              schema.recordSizeBytes() == 22,
              "primary schema derives a packed record layout");
        const float values[] = {-123.0f, 42.0f, NAN};
        uint8_t record[32];
        check(schema.encodeRecord(
                  7, 0xFFFFFFF0u, BdqV2Format::DiscontinuityBefore,
                  values, 3, record, sizeof(record)),
              "primary record encodes mixed storage types");
        BdqV2Format::StreamRecordPrefix prefix;
        BdqV2Format::decodeStreamRecordPrefix(record, sizeof(record), prefix);
        uint32_t optionalRaw = 0;
        std::memcpy(&optionalRaw, record + 18, sizeof(optionalRaw));
        float optionalValue = 0.0f;
        std::memcpy(&optionalValue, &optionalRaw, sizeof(optionalValue));
        check(prefix.sequence == 7 && prefix.nativeTick == 0xFFFFFFF0u &&
              prefix.statusFlags == BdqV2Format::DiscontinuityBefore &&
              static_cast<int16_t>(BdqV2Format::getU16(record + 12)) == -123 &&
              BdqV2Format::getU32(record + 14) == 42 &&
              std::isnan(optionalValue),
              "primary record preserves tick, status, signed values, and allowed NaN");
        const float invalid[] = {70000.0f, 42.0f, 1.0f};
        check(schema.encodeRecord(8, 10, 0, invalid, 3, record, sizeof(record)) &&
              (BdqV2Format::getU16(record + 8) &
               BdqV2PrimaryStreamSchema::kSensorErrorStatus) != 0,
              "primary record exposes conversion range errors");
    }

    {
        BMI270ImuSample sample;
        sample.accelX = -123;
        sample.accelY = 456;
        sample.gyroZ = -789;
        sample.temperatureRaw = 512;
        sample.sequence = 0xFFFFFFFEu;
        sample.sensorTime = 0x01ABCDE0u;
        sample.statusFlags = BMI270ImuStatus::markPreSessionBoundary(
            BMI270ImuStatus::kFifoDiscontinuityBefore) |
            BMI270ImuStatus::kTemperatureStale;
        uint8_t encoded[BMI270BdqV2::kRecordSizeBytes];
        check(BMI270BdqV2::encodeRecord(sample, encoded, sizeof(encoded)),
              "BMI270 native record encodes");
        BdqV2Format::StreamRecordPrefix prefix;
        BdqV2Format::decodeStreamRecordPrefix(encoded, sizeof(encoded), prefix);
        check(prefix.sequence == sample.sequence && prefix.nativeTick == 0x00ABCDE0u &&
              prefix.statusFlags == (BMI270ImuStatus::kFifoDiscontinuityBefore |
                                     BMI270ImuStatus::kTemperatureStale),
              "BMI270 record preserves public status and masks internal evidence");
        check(static_cast<int16_t>(BdqV2Format::getU16(encoded + 12)) == -123 &&
              static_cast<int16_t>(BdqV2Format::getU16(encoded + 14)) == 456 &&
              static_cast<int16_t>(BdqV2Format::getU16(encoded + 22)) == -789,
              "BMI270 record preserves signed sensor values");

        BMI270BdqV2::TimingObservationSampler sampler;
        sample.acquisitionBatchId = 1;
        sample.acquisitionAnchorUs = 100000;
        sample.acquisitionBeforeUs = 20;
        sample.acquisitionAfterUs = 60;
        BdqV2Format::TimeObservation observation;
        check(sampler.observe(sample, observation) &&
              observation.hostMinUs == 99980 && observation.hostMaxUs == 100060,
              "BMI270 timing observation preserves asymmetric transfer bounds");
        check(!sampler.observe(sample, observation),
              "BMI270 timing sampler emits at most once per FIFO batch");
        sample.acquisitionBatchId = 2;
        sample.acquisitionAnchorUs = 150000;
        check(!sampler.observe(sample, observation),
              "BMI270 timing evidence is intentionally rate limited");
        sample.acquisitionBatchId = 3;
        sample.acquisitionAnchorUs = 200000;
        sample.statusFlags = BMI270ImuStatus::kSensorTimeEstimated |
                             BMI270ImuStatus::kTimingDegraded |
                             BMI270ImuStatus::kSensorRecoveryBefore;
        check(sampler.observe(sample, observation) &&
              (observation.flags & BdqV2Format::ObservationNativeTickEstimated) != 0 &&
              (observation.flags & BdqV2Format::ObservationTimingDegraded) != 0 &&
              (observation.flags & BdqV2Format::ObservationPostRecovery) != 0,
              "BMI270 timing observation carries source quality evidence");
        sample.acquisitionBatchId = 4;
        sample.acquisitionAnchorUs = 300000;
        sample.acquisitionBeforeUs = 0;
        sample.acquisitionAfterUs = 0;
        check(!sampler.observe(sample, observation),
              "BMI270 timing sampler suppresses unrepresentable bounds");
    }

    {
        BdqV2StreamQueue<16, 4, 2> queue(1, uint64_t{1} << 32);
        uint8_t record[16];
        for (uint32_t sequence = 0; sequence < 4; ++sequence) {
            makeRecord(record, sizeof(record), sequence, sequence * 10);
            check(queue.enqueueRecord(record, sizeof(record)), "record queue accepts capacity");
        }
        makeRecord(record, sizeof(record), 4, 40);
        check(!queue.enqueueRecord(record, sizeof(record)), "full record queue drops newest");

        BdqV2StreamSource source = queue.source();
        uint8_t popped[16];
        check(source.popRecord(source.context, popped, sizeof(popped)),
              "record source pops oldest record");
        makeRecord(record, sizeof(record), 5, 50);
        check(queue.enqueueRecord(record, sizeof(record)),
              "record queue accepts data after consumer progress");
        for (int index = 0; index < 3; ++index) {
            check(source.popRecord(source.context, popped, sizeof(popped)),
                  "record queue retains pre-drop records");
        }
        check(source.popRecord(source.context, popped, sizeof(popped)),
              "record after queue loss is retained");
        BdqV2Format::StreamRecordPrefix prefix;
        BdqV2Format::decodeStreamRecordPrefix(popped, sizeof(popped), prefix);
        check(prefix.sequence == 5 &&
              (prefix.statusFlags & BdqV2Format::DiscontinuityBefore) != 0 &&
              (prefix.statusFlags & BdqV2Format::ProducerQueueDropBefore) != 0,
              "next retained record carries explicit queue-loss boundary");

        BdqV2Format::TimeObservation observation;
        observation.nativeTick = 50;
        observation.relatedSequence = 5;
        observation.hostMinUs = 1000;
        observation.hostMaxUs = 1100;
        check(queue.enqueueObservation(observation) &&
              queue.enqueueObservation(observation),
              "observation queue accepts its declared capacity");
        check(!queue.enqueueObservation(observation),
              "full observation queue reports timing-evidence loss");
        BdqV2Format::TimeObservation poppedObservation;
        check(source.popObservation(source.context, poppedObservation),
              "observation source makes room for continued production");
        makeRecord(record, sizeof(record), 6, 60);
        check(queue.enqueueRecord(record, sizeof(record)) &&
              source.popRecord(source.context, popped, sizeof(popped)),
              "record after observation loss is retained");
        BdqV2Format::decodeStreamRecordPrefix(popped, sizeof(popped), prefix);
        check((prefix.statusFlags & BdqV2Format::TimingDegraded) != 0,
              "lost timing evidence marks the next retained record degraded");
        const BdqV2StreamQueueStats stats = queue.stats();
        check(stats.recordsEnqueued == 6 && stats.recordsDropped == 1 &&
              stats.recordQueueHighWater == 4 &&
              stats.observationsEnqueued == 2 && stats.observationsDropped == 1,
              "queues report exact loss and high-water counts");
    }

    {
        BdqV2StreamQueue<16, 4, 2> queue(2, uint64_t{1} << 24);
        const BdqV2CatalogChannel channels[] = {
            {"sequence", "sample_sequence", "count", "uint32", 0, "diagnostic"},
            {"native_tick", "sensor_time", "tick", "uint32", 4, "diagnostic"},
            {"status_flags", "status", "bitfield", "uint16", 8, "diagnostic"},
            {"value_raw", "raw", "count", "int16", 12, "signal"},
        };
        const BdqV2CatalogStatusFlag flags[] = {
            {"discontinuity_before", BdqV2Format::DiscontinuityBefore},
        };
        BdqV2StreamDescriptor descriptor;
        descriptor.source = queue.source();
        std::strcpy(descriptor.streamKey, "imu_test");
        std::strcpy(descriptor.sensorId, "test_imu");
        std::strcpy(descriptor.transport, "i2c_direct");
        std::strcpy(descriptor.clockId, "bmi270:test_imu");
        descriptor.nativeTickBits = 24;
        descriptor.nominalTickPeriodNumeratorUs = 625;
        descriptor.nominalTickPeriodDenominator = 16;
        descriptor.nominalSampleRateNumeratorHz = 1600;
        descriptor.channels = channels;
        descriptor.channelCount = sizeof(channels) / sizeof(channels[0]);
        descriptor.statusFlags = flags;
        descriptor.statusFlagCount = sizeof(flags) / sizeof(flags[0]);

        const size_t measured = BdqV2Catalog::measure("A8_TEST", &descriptor, 1);
        std::vector<char> json(measured + 1);
        size_t written = 0;
        check(measured != 0 && BdqV2Catalog::write(
                  "A8_TEST", &descriptor, 1, json.data(), json.size(), written) &&
              written == measured,
              "catalog measurement and bounded serialization agree exactly");
        const std::string text(json.data(), written);
        check(text.find("\"schema_format\":\"bdq.stream_catalog.v1\"") !=
                  std::string::npos &&
              text.find("\"stream_key\":\"imu_test\"") != std::string::npos &&
              text.find("\"native_tick_modulus\":16777216") != std::string::npos &&
              text.find("\"field\":\"value_raw\"") != std::string::npos,
              "catalog contains the declared stream, timebase, and channel schema");
        check(!BdqV2Catalog::write(
                  "A8_TEST", &descriptor, 1, json.data(), measured, written) &&
              written == 0,
              "catalog serializer rejects a buffer without trailing-NUL capacity");
        descriptor.nativeTickBits = 23;
        check(!descriptor.valid(),
              "catalog rejects a modulus wider than its declared native tick");
        descriptor.nativeTickBits = 24;
        const BdqV2CatalogStatusFlag duplicateFlags[] = {
            {"discontinuity_before", BdqV2Format::DiscontinuityBefore},
            {"duplicate_mask", BdqV2Format::DiscontinuityBefore},
        };
        descriptor.statusFlags = duplicateFlags;
        descriptor.statusFlagCount =
            sizeof(duplicateFlags) / sizeof(duplicateFlags[0]);
        check(!descriptor.valid(),
              "catalog rejects ambiguous duplicate status masks");
    }

    {
        BdqV2StreamQueue<16, 8, 4> primary(1, uint64_t{1} << 32);
        BdqV2StreamQueue<16, 8, 4> imu(2, uint64_t{1} << 24);
        uint8_t record[16];
        for (uint32_t sequence = 0; sequence < 3; ++sequence) {
            makeRecord(record, sizeof(record), sequence, 100 + sequence, 0,
                       static_cast<int16_t>(sequence));
            check(primary.enqueueRecord(record, sizeof(record)), "primary record enqueues");
        }
        for (uint32_t sequence = 10; sequence < 12; ++sequence) {
            makeRecord(record, sizeof(record), sequence, 1000 + sequence, 0,
                       static_cast<int16_t>(sequence));
            check(imu.enqueueRecord(record, sizeof(record)), "IMU record enqueues");
        }
        BdqV2Format::TimeObservation observation;
        observation.nativeTick = 1011;
        observation.relatedSequence = 11;
        observation.hostMinUs = 5000;
        observation.hostMaxUs = 5080;
        observation.flags = BdqV2Format::ObservationHostBoundsConservative;
        check(imu.enqueueObservation(observation), "timing observation enqueues");

        MemorySink sink;
        uint8_t workspace[256];
        BdqV2Writer writer;
        check(writer.addStream(primary.source()) && writer.addStream(imu.source()),
              "writer registers unique stream sources");
        check(!writer.addStream(primary.source()), "writer rejects duplicate stream IDs");

        const char metadata[] = "{\"format\":\"bdq.v2\"}";
        const char catalog[] = "{\"schema_format\":\"bdq.stream_catalog.v1\"}";
        BdqV2WriterConfig config;
        config.maximumRecordsPerChunk = 2;
        config.maximumObservationsPerChunk = 2;
        check(writer.begin(
                  sink,
                  workspace,
                  sizeof(workspace),
                  123456,
                  metadata,
                  sizeof(metadata) - 1,
                  catalog,
                  sizeof(catalog) - 1,
                  config),
              "writer emits file header, metadata, and catalog");
        check(writer.drain(10) == 3, "writer drains three bounded stream chunks");
        const char eventJson[] = "{\"event_format\":\"bdq.events.v1\",\"events\":[{}]}";
        check(writer.writeEventJson(eventJson, sizeof(eventJson) - 1),
              "writer emits an independent event chunk");
        const char summary[] = "{\"summary_format\":\"bdq.final_summary.v2\"}";
        check(writer.end(summary, sizeof(summary) - 1) && sink.flushed,
              "writer drains and closes with a final summary");
        check(sink.bytes.size() >= BdqV2Format::kFileHeaderBytes &&
              std::memcmp(sink.bytes.data(), BdqV2Format::kFileMagic, 8) == 0,
              "writer output starts with BDQ v2 magic");
        const std::vector<uint16_t> order = streamChunkOrder(sink.bytes);
        check(order == std::vector<uint16_t>({1, 2, 1}),
              "writer services active streams in deterministic round-robin order");
        const BdqV2WriterStats& stats = writer.stats();
        check(stats.recordsWritten == 5 && stats.observationsWritten == 1 &&
              stats.streamDataChunksWritten == 3 && stats.chunksWritten == 7,
              "writer reports exact persisted record, observation, and chunk counts");
        const BdqV2WriterStreamStats* imuStats = writer.streamStats(2);
        check(imuStats && imuStats->recordsWritten == 2 &&
              imuStats->observationsWritten == 1 && imuStats->firstSequence == 10 &&
              imuStats->lastSequence == 11,
              "writer retains per-stream persistence diagnostics");
    }

    std::printf("BDQ v2 writer: %d passed, %d failed\n", passed, failed);
    return failed;
}
