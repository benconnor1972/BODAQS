#include "BdqV2Writer.h"

#include <limits.h>
#include <string.h>

namespace {

constexpr uint16_t kChunkHeaderVersion = 1;

bool pending_(const BdqV2StreamSource& source) {
  return source.pendingRecords(source.context) != 0 ||
         source.pendingObservations(source.context) != 0;
}

bool sequenceFollows_(uint32_t previous, uint32_t current, uint16_t statusFlags) {
  const uint32_t delta = current - previous;
  if (delta != 0 && delta < 0x80000000u) return true;
  return (statusFlags & (BdqV2Format::DiscontinuityBefore |
                         BdqV2Format::SourceRecoveryBefore)) != 0;
}

}  // namespace

bool BdqV2Writer::addStream(const BdqV2StreamSource& source) {
  if (active_ || !source.valid() || streamCount_ >= kMaximumStreams) return false;
  for (size_t index = 0; index < streamCount_; ++index) {
    if (streams_[index].source.streamId == source.streamId) return false;
  }
  streams_[streamCount_].source = source;
  streams_[streamCount_].stats = {};
  streams_[streamCount_].stats.streamId = source.streamId;
  ++streamCount_;
  return true;
}

void BdqV2Writer::clearStreams() {
  if (active_) return;
  for (size_t index = 0; index < kMaximumStreams; ++index) {
    streams_[index] = {};
  }
  streamCount_ = 0;
  nextStreamIndex_ = 0;
}

bool BdqV2Writer::begin(
    BdqV2ByteSink& sink,
    uint8_t* workspace,
    size_t workspaceBytes,
    uint64_t createdUnixUs,
    const char* metadataJson,
    size_t metadataLength,
    const char* streamCatalogJson,
    size_t streamCatalogLength,
    const BdqV2WriterConfig& config) {
  if (active_ || failed_ || streamCount_ == 0 || !workspace ||
      !metadataJson || metadataLength == 0 ||
      !streamCatalogJson || streamCatalogLength == 0 ||
      config.maximumRecordsPerChunk == 0 ||
      config.maximumObservationsPerChunk == 0) {
    return false;
  }

  size_t largestRecord = 0;
  for (size_t index = 0; index < streamCount_; ++index) {
    const size_t recordSize = streams_[index].source.recordSizeBytes;
    if (recordSize > largestRecord) largestRecord = recordSize;
    streams_[index].stats = {};
    streams_[index].stats.streamId = streams_[index].source.streamId;
  }
  const size_t minimumWorkspace = BdqV2Format::kStreamDataHeaderBytes +
                                  largestRecord +
                                  BdqV2Format::kTimeObservationBytes;
  if (workspaceBytes < minimumWorkspace || workspaceBytes > UINT32_MAX) return false;

  resetSession_();
  sink_ = &sink;
  workspace_ = workspace;
  workspaceBytes_ = workspaceBytes;
  config_ = config;
  active_ = true;

  uint8_t fileHeader[BdqV2Format::kFileHeaderBytes];
  BdqV2Format::FileHeader fileHeaderValue;
  fileHeaderValue.createdUnixUs = createdUnixUs;
  if (!BdqV2Format::encodeFileHeader(
          fileHeaderValue, fileHeader, sizeof(fileHeader)) ||
      !sink_->write(fileHeader, sizeof(fileHeader))) {
    return fail_();
  }
  stats_.bytesWritten = sizeof(fileHeader);

  if (!writeChunk_(
          BdqV2Format::ChunkType::Metadata,
          reinterpret_cast<const uint8_t*>(metadataJson),
          metadataLength) ||
      !writeChunk_(
          BdqV2Format::ChunkType::StreamCatalog,
          reinterpret_cast<const uint8_t*>(streamCatalogJson),
          streamCatalogLength)) {
    return false;
  }
  return true;
}

bool BdqV2Writer::writeEventJson(const char* eventJson, size_t length) {
  if (!isActive() || !eventJson || length == 0) return false;
  return writeChunk_(
      BdqV2Format::ChunkType::Event,
      reinterpret_cast<const uint8_t*>(eventJson),
      length);
}

bool BdqV2Writer::drainNextChunk() {
  if (!isActive() || streamCount_ == 0) return false;
  for (size_t offset = 0; offset < streamCount_; ++offset) {
    const size_t index = (nextStreamIndex_ + offset) % streamCount_;
    if (!pending_(streams_[index].source)) continue;
    if (!stageAndWriteStream_(index)) return false;
    nextStreamIndex_ = (index + 1) % streamCount_;
    return true;
  }
  return false;
}

size_t BdqV2Writer::drain(size_t maximumChunks) {
  size_t written = 0;
  while (written < maximumChunks && drainNextChunk()) {
    ++written;
  }
  return written;
}

bool BdqV2Writer::flush() {
  if (!isActive()) return false;
  if (!sink_->flush()) return fail_();
  return true;
}

bool BdqV2Writer::end(const char* finalSummaryJson, size_t finalSummaryLength) {
  if (!isActive() || !finalSummaryJson || finalSummaryLength == 0) return false;

  while (hasPendingData()) {
    if (!drainNextChunk()) return fail_();
  }
  if (!writeChunk_(
          BdqV2Format::ChunkType::FinalSummary,
          reinterpret_cast<const uint8_t*>(finalSummaryJson),
          finalSummaryLength)) {
    return false;
  }
  if (!sink_->flush()) return fail_();

  active_ = false;
  sink_ = nullptr;
  workspace_ = nullptr;
  workspaceBytes_ = 0;
  return true;
}

void BdqV2Writer::abort() {
  active_ = false;
  failed_ = false;
  sink_ = nullptr;
  workspace_ = nullptr;
  workspaceBytes_ = 0;
}

bool BdqV2Writer::hasPendingData() const {
  for (size_t index = 0; index < streamCount_; ++index) {
    if (pending_(streams_[index].source)) return true;
  }
  return false;
}

const BdqV2WriterStreamStats* BdqV2Writer::streamStats(uint16_t streamId) const {
  for (size_t index = 0; index < streamCount_; ++index) {
    if (streams_[index].source.streamId == streamId) {
      return &streams_[index].stats;
    }
  }
  return nullptr;
}

bool BdqV2Writer::writeChunk_(
    BdqV2Format::ChunkType type,
    const uint8_t* payload,
    size_t length) {
  if (!isActive() || (!payload && length != 0) || length > UINT32_MAX) return false;

  BdqV2Format::ChunkHeader chunk;
  chunk.headerVersion = kChunkHeaderVersion;
  chunk.type = type;
  chunk.sequence = nextChunkSequence_;
  chunk.payloadLength = static_cast<uint32_t>(length);
  chunk.payloadCrc32 = BdqV2Format::crc32(payload, length);

  uint8_t header[BdqV2Format::kChunkHeaderBytes];
  if (!BdqV2Format::encodeChunkHeader(chunk, header, sizeof(header)) ||
      !sink_->write(header, sizeof(header)) ||
      !sink_->write(payload, length)) {
    return fail_();
  }

  ++nextChunkSequence_;
  ++stats_.chunksWritten;
  const size_t chunkBytes = sizeof(header) + length;
  if (chunkBytes > UINT32_MAX - stats_.bytesWritten) {
    stats_.bytesWritten = UINT32_MAX;
  } else {
    stats_.bytesWritten += static_cast<uint32_t>(chunkBytes);
  }
  return true;
}

bool BdqV2Writer::stageAndWriteStream_(size_t streamIndex) {
  RegisteredStream& registered = streams_[streamIndex];
  const BdqV2StreamSource& source = registered.source;
  size_t cursor = BdqV2Format::kStreamDataHeaderBytes;
  uint32_t recordCount = 0;
  uint16_t observationCount = 0;
  uint32_t firstSequence = 0;
  uint32_t previousSequence = registered.stats.lastSequence;
  bool havePreviousSequence = registered.stats.hasSequence;

  const size_t pendingObservations = source.pendingObservations(source.context);
  size_t reservedObservationCount = pendingObservations;
  if (reservedObservationCount > config_.maximumObservationsPerChunk) {
    reservedObservationCount = config_.maximumObservationsPerChunk;
  }
  const size_t maximumReservation =
      (workspaceBytes_ - BdqV2Format::kStreamDataHeaderBytes -
       source.recordSizeBytes) /
      BdqV2Format::kTimeObservationBytes;
  if (reservedObservationCount > maximumReservation) {
    reservedObservationCount = maximumReservation;
  }
  const size_t recordLimit = workspaceBytes_ -
      reservedObservationCount * BdqV2Format::kTimeObservationBytes;

  while (recordCount < config_.maximumRecordsPerChunk &&
         source.pendingRecords(source.context) != 0 &&
         cursor + source.recordSizeBytes <= recordLimit) {
    uint8_t* record = workspace_ + cursor;
    if (!source.popRecord(source.context, record, source.recordSizeBytes)) {
      return fail_();
    }

    BdqV2Format::StreamRecordPrefix prefix;
    if (!BdqV2Format::decodeStreamRecordPrefix(
            record, source.recordSizeBytes, prefix) ||
        prefix.reserved != 0 ||
        prefix.nativeTick >= source.nativeTickModulus ||
        (havePreviousSequence &&
         !sequenceFollows_(previousSequence, prefix.sequence, prefix.statusFlags))) {
      return fail_();
    }
    if (recordCount == 0) firstSequence = prefix.sequence;
    previousSequence = prefix.sequence;
    havePreviousSequence = true;
    cursor += source.recordSizeBytes;
    ++recordCount;
  }

  while (observationCount < config_.maximumObservationsPerChunk &&
         source.pendingObservations(source.context) != 0 &&
         cursor + BdqV2Format::kTimeObservationBytes <= workspaceBytes_) {
    BdqV2Format::TimeObservation observation;
    if (!source.popObservation(source.context, observation) ||
        !BdqV2Format::validTimeObservation(observation) ||
        observation.nativeTick >= source.nativeTickModulus ||
        !BdqV2Format::encodeTimeObservation(
            observation,
            workspace_ + cursor,
            workspaceBytes_ - cursor)) {
      return fail_();
    }
    if (recordCount == 0 && observationCount == 0) {
      firstSequence = observation.relatedSequence;
    }
    cursor += BdqV2Format::kTimeObservationBytes;
    ++observationCount;
  }

  if (recordCount == 0 && observationCount == 0) return fail_();

  BdqV2Format::StreamDataHeader dataHeader;
  dataHeader.streamId = source.streamId;
  dataHeader.firstSequence = firstSequence;
  dataHeader.recordCount = recordCount;
  dataHeader.recordSizeBytes = source.recordSizeBytes;
  dataHeader.observationCount = observationCount;
  if (!BdqV2Format::encodeStreamDataHeader(
          dataHeader, workspace_, workspaceBytes_)) {
    return fail_();
  }
  if (!writeChunk_(BdqV2Format::ChunkType::StreamData, workspace_, cursor)) {
    return false;
  }

  BdqV2WriterStreamStats& streamStats = registered.stats;
  if (recordCount != 0) {
    if (!streamStats.hasSequence) streamStats.firstSequence = firstSequence;
    streamStats.lastSequence = previousSequence;
    streamStats.hasSequence = true;
  }
  streamStats.recordsWritten += recordCount;
  streamStats.observationsWritten += observationCount;
  ++streamStats.dataChunksWritten;
  stats_.recordsWritten += recordCount;
  stats_.observationsWritten += observationCount;
  ++stats_.streamDataChunksWritten;
  return true;
}

bool BdqV2Writer::fail_() {
  if (!failed_) ++stats_.fatalErrors;
  failed_ = true;
  active_ = false;
  return false;
}

void BdqV2Writer::resetSession_() {
  nextStreamIndex_ = 0;
  sink_ = nullptr;
  workspace_ = nullptr;
  workspaceBytes_ = 0;
  config_ = {};
  stats_ = {};
  nextChunkSequence_ = 0;
  active_ = false;
  failed_ = false;
}
