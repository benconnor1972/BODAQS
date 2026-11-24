#pragma once
#include <stddef.h>
#include <stdint.h>

// Owner-only counters. A successful request is not proof of durable card media.
namespace StoragePathProbe {
struct Counters {
  uint64_t context = 0;
  uint64_t sectors[2] = {}; // [0] direct DMA predicate, [1] SDK bounce predicate
  uint32_t calls[2] = {}, failed[2] = {}, histogram[2][5] = {};
  uint32_t maxSectors = 0, sectorSize = 0, sectorSizeChanges = 0;
  uint32_t unaligned = 0, outsideDma = 0;
};

inline unsigned sectorBin(size_t count) {
  return count == 0 ? 0 : count == 1 ? 1 : count <= 8 ? 2 : count <= 32 ? 3 : 4;
}

inline void record(Counters& value, uintptr_t address, bool dmaCapable,
                   size_t count, uint32_t sectorSize, int result) {
  const bool unaligned = (address & 3u) != 0;
  const unsigned path = !dmaCapable || unaligned ? 1 : 0;
  ++value.calls[path];
  value.sectors[path] += count;
  ++value.histogram[path][sectorBin(count)];
  if (result != 0) ++value.failed[path];
  if (count > value.maxSectors) value.maxSectors = static_cast<uint32_t>(count);
  if (value.sectorSize && value.sectorSize != sectorSize) ++value.sectorSizeChanges;
  value.sectorSize = sectorSize;
  if (unaligned) ++value.unaligned;
  if (!dmaCapable) ++value.outsideDma;
}
} // namespace StoragePathProbe
