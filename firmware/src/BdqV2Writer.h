#pragma once

#include <stddef.h>
#include <stdint.h>

#include "BdqV2StreamSource.h"

class BdqV2ByteSink {
public:
  virtual ~BdqV2ByteSink() = default;
  virtual bool write(const uint8_t* data, size_t length) = 0;
  virtual bool flush() = 0;
};

struct BdqV2WriterConfig {
  uint16_t maximumRecordsPerChunk = 128;
  uint16_t maximumObservationsPerChunk = 16;
  // Normal live draining waits for either this many records or the latency
  // bound below. Forced drains at shutdown ignore both thresholds.
  uint16_t minimumRecordsPerChunk = 1;
  uint32_t maximumChunkLatencyUs = 0;
};

struct BdqV2WriterStreamStats {
  uint16_t streamId = 0;
  uint32_t recordsWritten = 0;
  uint32_t observationsWritten = 0;
  uint32_t dataChunksWritten = 0;
  uint32_t firstSequence = 0;
  uint32_t lastSequence = 0;
  bool hasSequence = false;
};

struct BdqV2WriterStats {
  uint32_t chunksWritten = 0;
  uint32_t streamDataChunksWritten = 0;
  uint32_t recordsWritten = 0;
  uint32_t observationsWritten = 0;
  uint32_t bytesWritten = 0;
  uint32_t fatalErrors = 0;
};

// Single-consumer BDQ v2 file writer. Producers remain isolated behind their
// own bounded queues; drainNextChunk() services one stream per call in strict
// round-robin order among streams that have pending data.
class BdqV2Writer {
public:
  static constexpr size_t kMaximumStreams = 16;

  bool addStream(const BdqV2StreamSource& source);
  void clearStreams();

  // Workspace is caller-owned for the full session and stores one chunk
  // payload. No allocation occurs in begin(), drain(), or end().
  bool begin(
      BdqV2ByteSink& sink,
      uint8_t* workspace,
      size_t workspaceBytes,
      uint64_t createdUnixUs,
      const char* metadataJson,
      size_t metadataLength,
      const char* streamCatalogJson,
      size_t streamCatalogLength,
      const BdqV2WriterConfig& config = {});

  bool writeEventJson(const char* eventJson, size_t length);
  // Immediate/forced drain retained for shutdown and deterministic tests.
  bool drainNextChunk();
  // Live drain which batches sparse arrivals but guarantees a bounded age.
  bool drainNextReadyChunk(uint64_t nowUs);
  size_t drain(size_t maximumChunks);
  bool flush();

  // Producers must be stopped before end() so the queues converge to empty.
  bool end(const char* finalSummaryJson, size_t finalSummaryLength);
  void abort();

  bool isActive() const { return active_ && !failed_; }
  bool failed() const { return failed_; }
  bool hasPendingData() const;
  size_t streamCount() const { return streamCount_; }
  uint32_t nextChunkSequence() const { return nextChunkSequence_; }
  const BdqV2WriterStats& stats() const { return stats_; }
  const BdqV2WriterStreamStats* streamStats(uint16_t streamId) const;

private:
  struct RegisteredStream {
    BdqV2StreamSource source;
    BdqV2WriterStreamStats stats;
    uint64_t pendingSinceUs = 0;
    bool pendingAgeTracked = false;
  };

  bool writeChunk_(BdqV2Format::ChunkType type, const uint8_t* payload, size_t length);
  bool stageAndWriteStream_(size_t streamIndex);
  bool streamReady_(RegisteredStream& stream, uint64_t nowUs);
  void updatePendingAgeAfterWrite_(RegisteredStream& stream, uint64_t nowUs);
  bool fail_();
  void resetSession_();

  RegisteredStream streams_[kMaximumStreams] {};
  size_t streamCount_ = 0;
  size_t nextStreamIndex_ = 0;
  BdqV2ByteSink* sink_ = nullptr;
  uint8_t* workspace_ = nullptr;
  size_t workspaceBytes_ = 0;
  BdqV2WriterConfig config_;
  BdqV2WriterStats stats_;
  uint32_t nextChunkSequence_ = 0;
  bool active_ = false;
  bool failed_ = false;
};
