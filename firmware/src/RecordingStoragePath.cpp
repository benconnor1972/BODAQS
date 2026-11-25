#include "RecordingStoragePath.h"
#if BODAQS_PRODUCTION_RECORDING
#include "SdWriteBatch.h"
#include <atomic>
#include "esp_heap_caps.h"
#include "soc/soc_memory_types.h"
#include "esp_rom_crc.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdmmc_cmd.h"

namespace RecordingStoragePath {
namespace {
std::atomic<TaskHandle_t> owner{nullptr};
uint8_t* staging = nullptr;
}

bool begin() {
  TaskHandle_t expected = nullptr;
  if (!owner.compare_exchange_strong(expected, xTaskGetCurrentTaskHandle(), std::memory_order_acq_rel))
    return false;
  if (!staging) {
    auto* buffer = static_cast<uint8_t*>(heap_caps_malloc(SdWriteBatch::bufferBytes,
        MALLOC_CAP_INTERNAL | MALLOC_CAP_DMA | MALLOC_CAP_8BIT));
    if (!buffer) {
      owner.store(nullptr, std::memory_order_release);
      return false;
    }
    if ((reinterpret_cast<uintptr_t>(buffer) & 3u) || !esp_ptr_dma_capable(buffer) ||
        !esp_ptr_dma_capable(buffer + SdWriteBatch::bufferBytes - 1)) {
      heap_caps_free(buffer);
      owner.store(nullptr, std::memory_order_release);
      return false;
    }
    staging = buffer;
  }
  return true;
}

void finish() {
  if (owner.load(std::memory_order_acquire) == xTaskGetCurrentTaskHandle())
    owner.store(nullptr, std::memory_order_release);
}

uint32_t payloadCrc(const uint8_t* data, size_t length) {
  if (!data || !length) return 0;
  return esp_rom_crc32_le(0, data, static_cast<uint32_t>(length));
}
}

// IDF 4.4.7 otherwise bounces unsuitable source pointers one sector at a time.
// This synchronous call borrows the persistent buffer only from its owner.
extern "C" esp_err_t __real_sdmmc_write_sectors(sdmmc_card_t*, const void*, size_t, size_t);
extern "C" esp_err_t __wrap_sdmmc_write_sectors(sdmmc_card_t* card, const void* data, size_t sector, size_t count) {
  using namespace RecordingStoragePath;
  const auto driver = [card](const void* source, size_t start, size_t sectors) {
    return __real_sdmmc_write_sectors(card, source, start, sectors);
  };
  const bool suitable = esp_ptr_dma_capable(data) && !(reinterpret_cast<uintptr_t>(data) & 3u);
  const bool stage = owner.load(std::memory_order_acquire) == xTaskGetCurrentTaskHandle() &&
      staging && !suitable && card && card->csd.sector_size == SdWriteBatch::sectorBytes &&
      SdWriteBatch::validRange(data, sector, count, card->csd.capacity);
  SdWriteBatch::Stats ignored;
  return stage ? SdWriteBatch::write(staging, data, sector, count, ignored, driver)
               : driver(data, sector, count);
}
#endif
