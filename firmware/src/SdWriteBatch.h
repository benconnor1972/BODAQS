#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

// Synchronous, owner-only staging. The caller validates card/source/range and
// DMA buffer capability before entering; write must finish borrowing the buffer
// before returning. A failing chunk is terminal and is never retried here.
namespace SdWriteBatch {
constexpr size_t sectorBytes = 512;
constexpr size_t bufferBytes = 4096;
constexpr size_t maxSectors = bufferBytes / sectorBytes;

struct Stats {
  uint32_t requests = 0, chunks = 0, failedChunks = 0, maximumChunkSectors = 0;
  uint64_t sectors = 0, copiedBytes = 0;
};

inline bool validRange(const void* source, size_t start, size_t count, int capacity) {
  if (!source || !count || capacity <= 0 || count > SIZE_MAX / sectorBytes) return false;
  const size_t limit = static_cast<size_t>(capacity);
  if (start > limit || count > limit - start) return false;
  const uintptr_t address = reinterpret_cast<uintptr_t>(source);
  return address <= UINTPTR_MAX - count * sectorBytes;
}

template<class Write>
int write(uint8_t* buffer, const void* source, size_t start, size_t count,
          Stats& stats, Write&& driver) {
  ++stats.requests;
  const auto* input = static_cast<const uint8_t*>(source);
  while (count) {
    const size_t sectors = count < maxSectors ? count : maxSectors;
    const size_t bytes = sectors * sectorBytes;
    memcpy(buffer, input, bytes);
    ++stats.chunks;
    stats.sectors += sectors;
    stats.copiedBytes += bytes;
    if (sectors > stats.maximumChunkSectors) stats.maximumChunkSectors = static_cast<uint32_t>(sectors);
    const int result = driver(buffer, start, sectors);
    if (result != 0) { ++stats.failedChunks; return result; }
    input += bytes;
    start += sectors;
    count -= sectors;
  }
  return 0;
}
} // namespace SdWriteBatch
