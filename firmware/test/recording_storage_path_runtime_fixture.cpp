#include "RecordingStoragePath.h"
#include "sdmmc_cmd.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <vector>

static void* current = reinterpret_cast<void*>(1);
static void* dma = nullptr;
static bool allocationFails = true, dmaValid = true;
static unsigned allocations = 0, writes = 0, failWrite = 0;
static std::vector<uint8_t> disk(64 * 512, 0);
void* xTaskGetCurrentTaskHandle() { return current; }
void* heap_caps_malloc(size_t bytes, unsigned) {
  ++allocations;
  return allocationFails ? nullptr : (dma = malloc(bytes));
}
void heap_caps_free(void* pointer) { free(pointer); dma = nullptr; }
bool esp_ptr_dma_capable(const void* pointer) {
  const auto address = reinterpret_cast<uintptr_t>(pointer);
  const auto base = reinterpret_cast<uintptr_t>(dma);
  return dmaValid && dma && address >= base && address < base + 4096;
}
uint32_t esp_rom_crc32_le(uint32_t initial, const uint8_t* data, uint32_t size) {
  uint32_t crc = ~initial;
  for (uint32_t i = 0; i < size; ++i) {
    crc ^= data[i];
    for (unsigned bit = 0; bit < 8; ++bit)
      crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1u)));
  }
  return ~crc;
}
extern "C" int __real_sdmmc_write_sectors(sdmmc_card_t*, const void* data, size_t start, size_t count) {
  ++writes;
  if (writes == failWrite) return 19;
  assert(start + count <= 64);
  memcpy(disk.data() + start * 512, data, count * 512);
  return 0;
}
extern "C" int __wrap_sdmmc_write_sectors(sdmmc_card_t*, const void*, size_t, size_t);

int main() {
  // Failed required reservations return promptly and leave ownership available.
  assert(!RecordingStoragePath::begin());
  assert(writes == 0 && allocations == 1);
  allocationFails = false;
  dmaValid = false;
  assert(!RecordingStoragePath::begin());
  dmaValid = true;
  assert(RecordingStoragePath::begin());
  assert(!RecordingStoragePath::begin()); // no overlapping sessions
  const unsigned reserved = allocations;
  assert(RecordingStoragePath::payloadCrc(nullptr, 0) == 0);
  assert(RecordingStoragePath::payloadCrc(nullptr, 7) == 0);
  assert(RecordingStoragePath::payloadCrc(reinterpret_cast<const uint8_t*>("123456789"), 9) == 0xcbf43926u);
  std::vector<uint8_t> input(17 * 512);
  for (size_t i = 0; i < input.size(); ++i) input[i] = uint8_t(i * 13 + i / 512);
  sdmmc_card_t card{{512, 64}};
  assert(__wrap_sdmmc_write_sectors(&card, input.data(), 3, 17) == 0);
  assert(writes == 3); // ordered 8 + 8 + 1 sectors through one persistent buffer
  assert(memcmp(disk.data() + 3 * 512, input.data(), input.size()) == 0);
  writes = 0; failWrite = 2;
  memset(disk.data(), 0, disk.size());
  assert(__wrap_sdmmc_write_sectors(&card, input.data(), 0, 17) == 19);
  assert(writes == 2 && memcmp(disk.data(), input.data(), 8 * 512) == 0);
  for (size_t i = 8 * 512; i < disk.size(); ++i) assert(disk[i] == 0);
  current = reinterpret_cast<void*>(2);
  assert(!RecordingStoragePath::begin());
  RecordingStoragePath::finish(); // another task cannot release the owner
  current = reinterpret_cast<void*>(1);
  assert(!RecordingStoragePath::begin());
  RecordingStoragePath::finish();
  assert(RecordingStoragePath::begin());
  assert(allocations == reserved); // no per-session or per-write allocation
  RecordingStoragePath::finish();
  writes = 0; failWrite = 0;
  assert(__wrap_sdmmc_write_sectors(&card, input.data(), 3, 17) == 0);
  assert(writes == 1); // outside session, preserve the SDK path
  puts("Operational storage: allocation recovery, CRC, ownership and ordered writes passed");
}
