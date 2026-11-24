#include "StoragePathProbe.h"
#if BODAQS_STORAGE_PATH_PROBE
#include "StoragePathCounters.h"
#include "SdWriteBatch.h"
#include "BdqV2Format.h"
#include "FirmwareInfo.h"
#include <Arduino.h>
#include <atomic>
#include <new>
#include <string.h>
#include "esp_heap_caps.h"
#include "soc/soc_memory_types.h"
#include "esp_rom_crc.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdmmc_cmd.h"

namespace StoragePathProbe {
namespace {
struct State {
  Counters counts;
  Counters driverCounts;
  SdWriteBatch::Stats batch;
  std::atomic<TaskHandle_t> owner{nullptr};
  uint8_t* dmaBuffer = nullptr;
  bool active = false;
  bool rom = false;
  bool qualified = false;
  bool batchEnabled = false;
  bool dmaQualified = false;
};
// Avoid consuming scarce static DRAM; both CRC modes reserve identical memory.
State* state = nullptr;

uint32_t romCrc(const uint8_t* data, size_t length) {
  // Preserve the portable helper's empty/null behavior exactly.
  if (!data || length == 0) return 0;
  return esp_rom_crc32_le(0, data, static_cast<uint32_t>(length));
}

bool calibrate() {
  constexpr size_t capacity = 80624;
  auto* external = static_cast<uint8_t*>(heap_caps_malloc(capacity, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  auto* internal = static_cast<uint8_t*>(heap_caps_malloc(16388, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
  bool passed = external && internal;
  if (passed) {
    for (size_t i = 0; i < capacity; ++i) external[i] = static_cast<uint8_t>((i * 131u) ^ (i >> 3));
    memcpy(internal, external, 16388);
    passed = romCrc(nullptr, 0) == 0 && romCrc(nullptr, 1) == 0 &&
        romCrc(reinterpret_cast<const uint8_t*>("123456789"), 9) == 0xcbf43926u;
    const size_t lengths[] = {0,1,2,3,4,7,8,15,16,511,512,513,4095,4096,16383,16384,65536,80621};
    for (size_t length : lengths) {
      for (unsigned offset = 0; offset < 4; ++offset) {
        passed = (romCrc(external + offset, length) == BdqV2Format::crc32(external + offset, length)) && passed;
        if (length <= 16384)
          passed = (romCrc(internal + offset, length) == BdqV2Format::crc32(internal + offset, length)) && passed;
      }
      delay(1);
    }
    // Quiet, fixed work. Timing is a local kernel measurement, not a throughput promise.
    for (unsigned memory = 0; memory < 2; ++memory) {
      const auto* data = memory ? external : internal;
      uint64_t duration[2] = {};
      volatile uint32_t guard = 0;
      for (unsigned mode = 0; mode < 2; ++mode) {
        const auto start = esp_timer_get_time();
        for (unsigned n = 0; n < 16; ++n)
          guard = guard ^ (mode ? romCrc(data + (n & 3u), 16384) : BdqV2Format::crc32(data + (n & 3u), 16384));
        duration[mode] = esp_timer_get_time() - start;
      }
      Serial.printf("{\"schema\":\"bodaqs.storage-crc-calibration.v1\",\"type\":\"benchmark\",\"memory\":\"%s\",\"bytes_per_mode\":262144,\"legacy_us\":%llu,\"rom_us\":%llu,\"guard\":%u}\n",
          memory ? "psram" : "internal", duration[0], duration[1], static_cast<unsigned>(guard));
      delay(1);
    }
  }
  heap_caps_free(external);
  heap_caps_free(internal);
  state->qualified = passed;
  Serial.printf("{\"schema\":\"bodaqs.storage-crc-calibration.v1\",\"type\":\"finished\",\"recipe\":\"%s\",\"passed\":%s}\n",
      FirmwareInfo::buildRecipe(), passed ? "true" : "false");
  return passed;
}

void batchGate() {
  char line[24] = {}; unsigned used = 0; bool overflow = false;
  uint32_t announcement = 0;
  for (;;) {
    if (!announcement || millis() - announcement > 2000) {
      announcement = millis();
      Serial.printf("{\"schema\":\"bodaqs.sd-batch-gate.v1\",\"type\":\"ready\",\"recipe\":\"%s\",\"buffer_bytes\":4096,\"dma_qualified\":%s,\"commands\":\"sd on,sd off\"}\n",
          FirmwareInfo::buildRecipe(), state->dmaQualified ? "true" : "false");
    }
    while (Serial.available()) {
      const char ch = static_cast<char>(Serial.read());
      if (ch == '\r') continue;
      if (ch != '\n') { if (used + 1 < sizeof(line)) line[used++] = ch; else overflow = true; continue; }
      line[used] = 0;
      if (!overflow && (!strcmp(line, "sd on") || !strcmp(line, "sd off"))) {
        state->batchEnabled = !strcmp(line, "sd on");
        Serial.printf("{\"schema\":\"bodaqs.sd-batch-gate.v1\",\"type\":\"selected\",\"recipe\":\"%s\",\"enabled\":%s,\"buffer_bytes\":4096,\"dma_qualified\":%s,\"buffer_address\":%u,\"internal_free\":%u,\"internal_largest\":%u}\n",
            FirmwareInfo::buildRecipe(), state->batchEnabled ? "true" : "false", state->dmaQualified ? "true" : "false",
            static_cast<unsigned>(reinterpret_cast<uintptr_t>(state->dmaBuffer)),
            static_cast<unsigned>(heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)),
            static_cast<unsigned>(heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)));
        Serial.flush(); return;
      }
      used = 0; overflow = false;
    }
    delay(1);
  }
}
} // namespace

void bootGate() {
  void* allocation = heap_caps_malloc(sizeof(State), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
  if (!allocation) {
    Serial.println("[STORAGEPATH] diagnostic reservation failed; boot stopped");
    for (;;) delay(1000);
  }
  state = new (allocation) State;
  state->dmaBuffer = static_cast<uint8_t*>(heap_caps_malloc(SdWriteBatch::bufferBytes,
      MALLOC_CAP_INTERNAL | MALLOC_CAP_DMA | MALLOC_CAP_8BIT));
  state->dmaQualified = state->dmaBuffer &&
      !(reinterpret_cast<uintptr_t>(state->dmaBuffer) & 3u) &&
      esp_ptr_dma_capable(state->dmaBuffer) &&
      esp_ptr_dma_capable(state->dmaBuffer + SdWriteBatch::bufferBytes - 1);
  if (state->dmaQualified) {
    for (size_t i = 0; i < SdWriteBatch::bufferBytes; ++i) state->dmaBuffer[i] = static_cast<uint8_t>(i ^ (i >> 8));
    for (size_t i = 0; i < SdWriteBatch::bufferBytes; ++i)
      if (state->dmaBuffer[i] != static_cast<uint8_t>(i ^ (i >> 8))) state->dmaQualified = false;
  }
  if (!state->dmaQualified) {
    Serial.println("[STORAGEPATH] staging reservation failed; boot stopped");
    for (;;) delay(1000);
  }
#if defined(BODAQS_BENCH_AUTO_BOOT) && BODAQS_BENCH_AUTO_BOOT
  if(!calibrate()) {
    Serial.println("[STORAGEPATH] automatic ROM qualification failed; boot stopped");
    for(;;)delay(1000);
  }
  state->rom=true;state->batchEnabled=true;
  Serial.printf("{\"schema\":\"bodaqs.storage-path-gate.v1\",\"type\":\"selected\",\"recipe\":\"%s\",\"crc\":\"rom\",\"qualified\":true,\"automatic\":true}\n",FirmwareInfo::buildRecipe());
  Serial.printf("{\"schema\":\"bodaqs.sd-batch-gate.v1\",\"type\":\"selected\",\"recipe\":\"%s\",\"enabled\":true,\"dma_qualified\":true,\"buffer_bytes\":4096,\"automatic\":true}\n",FirmwareInfo::buildRecipe());
  return;
#endif
  char line[32] = {}; unsigned used = 0; bool overflow = false;
  uint32_t announcement = 0;
  for (;;) {
    if (!announcement || millis() - announcement > 2000) {
      announcement = millis();
      Serial.printf("{\"schema\":\"bodaqs.storage-path-gate.v1\",\"type\":\"ready\",\"recipe\":\"%s\",\"commands\":\"storage test,storage rom\"}\n", FirmwareInfo::buildRecipe());
    }
    while (Serial.available()) {
      const char ch = static_cast<char>(Serial.read());
      if (ch == '\r') continue;
      if (ch != '\n') { if (used + 1 < sizeof(line)) line[used++] = ch; else overflow = true; continue; }
      line[used] = 0;
      if (!overflow && !strcmp(line, "storage test")) (void)calibrate();
      else if (!overflow && !strcmp(line, "storage rom")) {
        if (!state->qualified) Serial.println("[STORAGEPATH] run storage test before selecting ROM");
        else {
          state->rom = true;
          Serial.printf("{\"schema\":\"bodaqs.storage-path-gate.v1\",\"type\":\"selected\",\"recipe\":\"%s\",\"crc\":\"%s\",\"qualified\":%s}\n",
              FirmwareInfo::buildRecipe(), "rom", state->qualified ? "true" : "false");
          Serial.flush(); batchGate(); return;
        }
      }
      used = 0; overflow = false;
    }
    delay(1);
  }
}

uint32_t payloadCrc(const uint8_t* data, size_t length) {
  return state && state->rom ? romCrc(data, length) : BdqV2Format::crc32(data, length);
}

void begin(uint64_t context) {
  if (!state) return;
  state->counts = {};
  state->counts.context = context;
  state->driverCounts = {};
  state->driverCounts.context = context;
  state->batch = {};
  state->owner.store(xTaskGetCurrentTaskHandle(), std::memory_order_release);
  state->active = true;
}

void finish(bool clean) {
  if (!state || state->owner.load(std::memory_order_acquire) != xTaskGetCurrentTaskHandle() || !state->active) return;
  state->active = false;
  const auto& c = state->counts;
  Serial.printf("{\"schema\":\"bodaqs.storage-path.v2\",\"recipe\":\"%s\",\"context\":\"%llu\",\"crc\":\"%s\",\"clean\":%s,\"scope\":\"storage_owner_open_through_close_including_fat\",\"sector_size\":%u,\"sector_size_changes\":%u,\"max_sectors\":%u,\"unaligned\":%u,\"outside_dma\":%u,\"input_paths\":[",
      FirmwareInfo::buildRecipe(), c.context, state->rom ? "rom" : "legacy", clean ? "true" : "false",
      c.sectorSize, c.sectorSizeChanges, c.maxSectors, c.unaligned, c.outsideDma);
  for (unsigned path = 0; path < 2; ++path) {
    Serial.printf("%s{\"predicate\":\"%s\",\"calls\":%u,\"requested_sectors\":%llu,\"failed_calls\":%u,\"sector_histogram\":[%u,%u,%u,%u,%u]}",
        path ? "," : "", path ? "needs_bounce" : "direct_dma", c.calls[path], c.sectors[path], c.failed[path],
        c.histogram[path][0],c.histogram[path][1],c.histogram[path][2],c.histogram[path][3],c.histogram[path][4]);
  }
  Serial.print("],\"driver_paths\":[");
  const auto& d = state->driverCounts;
  for (unsigned path = 0; path < 2; ++path) {
    Serial.printf("%s{\"predicate\":\"%s\",\"calls\":%u,\"requested_sectors\":%llu,\"failed_calls\":%u,\"sector_histogram\":[%u,%u,%u,%u,%u]}",
        path ? "," : "", path ? "sdk_bounce" : "direct_dma", d.calls[path], d.sectors[path], d.failed[path],
        d.histogram[path][0],d.histogram[path][1],d.histogram[path][2],d.histogram[path][3],d.histogram[path][4]);
  }
  const auto& batch = state->batch;
  Serial.printf("],\"batching\":{\"enabled\":%s,\"buffer_bytes\":4096,\"dma_qualified\":%s,\"staged_requests\":%u,\"chunks\":%u,\"attempted_sectors\":%llu,\"copied_bytes\":%llu,\"failed_chunks\":%u,\"maximum_chunk_sectors\":%u}}\n",
      state->batchEnabled ? "true" : "false", state->dmaQualified ? "true" : "false", batch.requests, batch.chunks,
      batch.sectors, batch.copiedBytes, batch.failedChunks, batch.maximumChunkSectors);
}

// Called only from the owner-task wrapper after the real driver returns.
void observe(const void* data, size_t count, uint32_t sectorSize, esp_err_t result) {
  if (state && state->owner.load(std::memory_order_acquire) == xTaskGetCurrentTaskHandle() && state->active)
    record(state->counts, reinterpret_cast<uintptr_t>(data), esp_ptr_dma_capable(data), count, sectorSize, result);
}
} // namespace StoragePathProbe

// Pinned IDF4.4.7: unsuitable source pointers otherwise bounce one sector at a
// time. Only the active storage owner may reuse our persistent staging buffer.
extern "C" esp_err_t __real_sdmmc_write_sectors(sdmmc_card_t*, const void*, size_t, size_t);
extern "C" esp_err_t __wrap_sdmmc_write_sectors(sdmmc_card_t* card, const void* data, size_t sector, size_t count) {
  using namespace StoragePathProbe;
  const bool owner = state && state->owner.load(std::memory_order_acquire) == xTaskGetCurrentTaskHandle() && state->active;
  const auto driver = [card, owner](const void* source, size_t start, size_t sectors) {
    const esp_err_t result = __real_sdmmc_write_sectors(card, source, start, sectors);
    if (owner) record(state->driverCounts, reinterpret_cast<uintptr_t>(source), esp_ptr_dma_capable(source),
        sectors, card ? card->csd.sector_size : 0, result);
    return result;
  };
  const bool suitable = esp_ptr_dma_capable(data) && !(reinterpret_cast<uintptr_t>(data) & 3u);
  const bool stage = owner && state->batchEnabled && state->dmaQualified && !suitable && card &&
      card->csd.sector_size == SdWriteBatch::sectorBytes &&
      SdWriteBatch::validRange(data, sector, count, card->csd.capacity);
  const esp_err_t result = stage ? SdWriteBatch::write(state->dmaBuffer, data, sector, count, state->batch, driver)
                               : driver(data, sector, count);
  StoragePathProbe::observe(data, count, card ? card->csd.sector_size : 0, result);
  return result;
}
#endif
