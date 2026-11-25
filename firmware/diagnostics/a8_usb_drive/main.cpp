// Isolated feasibility build for #192. Never linked into the normal logger.
#include <Arduino.h>
#include <SD_MMC.h>
#include <USB.h>
#include <USBMSC.h>
#include <driver/sdmmc_host.h>
#include <sdmmc_cmd.h>
#include <freertos/semphr.h>

#if ARDUINO_USB_MODE != 0
#error "This diagnostic requires USB-OTG, not USB Serial/JTAG"
#endif

namespace {
USBCDC console;
USBMSC drive;
SemaphoreHandle_t cardLock;
sdmmc_card_t card{};
bool rawReady = false;
bool upload = false;
bool exiting = false;
bool ejected = false;
uint32_t exitRequestedMs = 0;
uint32_t lastIoMs = 0;
// SDMMC DMA must use internal, aligned memory, not a USB buffer in PSRAM.
DMA_ATTR uint8_t sector[512];

bool mountLocal() {
  SD_MMC.setPins(10, 9, 11, 12, 7, 8);
  return SD_MMC.begin("/sdcard", false, false);
}

bool beginRaw() {
  sdmmc_host_t host = SDMMC_HOST_DEFAULT();
  host.flags = SDMMC_HOST_FLAG_4BIT;
  host.max_freq_khz = SDMMC_FREQ_DEFAULT;
  sdmmc_slot_config_t slot = SDMMC_SLOT_CONFIG_DEFAULT();
  slot.width = 4;
  slot.clk = GPIO_NUM_10;
  slot.cmd = GPIO_NUM_9;
  slot.d0 = GPIO_NUM_11;
  slot.d1 = GPIO_NUM_12;
  slot.d2 = GPIO_NUM_7;
  slot.d3 = GPIO_NUM_8;
  esp_err_t result = host.init();
  if (result != ESP_OK) return false;
  result = sdmmc_host_init_slot(host.slot, &slot);
  if (result == ESP_OK) result = sdmmc_card_init(&host, &card);
  if (result != ESP_OK || card.csd.sector_size != sizeof(sector)) {
    host.deinit();
    return false;
  }
  rawReady = true;
  return true;
}

int32_t transfer(uint32_t lba, uint32_t offset, void* data, uint32_t size, bool write) {
  if (xSemaphoreTake(cardLock, pdMS_TO_TICKS(1000)) != pdTRUE) return -1;
  lastIoMs = millis();
  const uint64_t address = uint64_t(lba) * sizeof(sector) + offset;
  if (!rawReady || ejected || address + size > uint64_t(card.csd.capacity) * sizeof(sector)) {
    xSemaphoreGive(cardLock);
    return -1;
  }
  auto* bytes = static_cast<uint8_t*>(data);
  uint32_t remaining = size;
  uint64_t position = address;
  while (remaining) {
    const uint32_t block = position / sizeof(sector);
    const size_t within = position % sizeof(sector);
    const size_t count = min(size_t(remaining), sizeof(sector) - within);
    esp_err_t result = ESP_OK;
    if (!write || within || count != sizeof(sector)) {
      result = sdmmc_read_sectors(&card, sector, block, 1);
    }
    if (result == ESP_OK && write) {
      memcpy(sector + within, bytes, count);
      result = sdmmc_write_sectors(&card, sector, block, 1);
    } else if (result == ESP_OK) {
      memcpy(bytes, sector + within, count);
    }
    if (result != ESP_OK) {
      lastIoMs = millis();
      xSemaphoreGive(cardLock);
      return -1;
    }
    bytes += count;
    position += count;
    remaining -= count;
  }
  lastIoMs = millis();
  xSemaphoreGive(cardLock);
  return size;
}

void enterUpload() {
  if (upload || digitalRead(SDIO_DET) != LOW) return;
  if (xSemaphoreTake(cardLock, pdMS_TO_TICKS(1000)) != pdTRUE) return;
  SD_MMC.end();
  if (beginRaw() && drive.begin(card.csd.capacity, card.csd.sector_size)) {
    upload = true;
    ejected = false;
    lastIoMs = millis();
    drive.mediaPresent(true);
    console.println("UPLOAD: SD exclusively owned by USB. Finish copying before exit.");
  } else {
    if (rawReady) sdmmc_host_deinit();
    rawReady = false;
    console.println(mountLocal() ? "Export failed; local storage restored." : "Storage error; local remount failed.");
  }
  xSemaphoreGive(cardLock);
}

void reclaim() {
  // Caller holds the same lock as all raw I/O callbacks.
  drive.mediaPresent(false);
  if (rawReady) sdmmc_host_deinit();
  rawReady = false;
  if (mountLocal()) {
    upload = false;
    exiting = false;
    console.println("NORMAL: local storage restored. 'l' lists files.");
  } else {
    exiting = false;
    console.println("Storage error: retained UPLOAD, 'r' retries remount.");
  }
}
} // namespace

void setup() {
  cardLock = xSemaphoreCreateMutex();
  if (!cardLock) abort();
  pinMode(SDIO_DET, INPUT_PULLUP);
  drive.vendorID("BODAQS");
  drive.productID("A8 SD diagnostic");
  drive.productRevision("0001");
  drive.onRead([](uint32_t lba, uint32_t offset, void* data, uint32_t size) {
    return transfer(lba, offset, data, size, false);
  });
  drive.onWrite([](uint32_t lba, uint32_t offset, uint8_t* data, uint32_t size) {
    return transfer(lba, offset, data, size, true);
  });
  drive.onStartStop([](uint8_t, bool start, bool loadEject) {
    if (!start && loadEject) {
      xSemaphoreTake(cardLock, portMAX_DELAY);
      ejected = true;
      drive.mediaPresent(false);
      xSemaphoreGive(cardLock);
    }
    return true;
  });
  console.begin(115200);
  USB.productName("BODAQS A8 USB diagnostic");
  USB.begin();
  mountLocal();
}

void loop() {
  if (console.available()) {
    switch (console.read()) {
      case 'u': enterUpload(); break;
      case 'x':
        if (upload) {
          exiting = true;
          exitRequestedMs = millis();
          console.println("Disconnecting USB... at least 3s plus 1s quiet; 'c' cancels.");
        }
        break;
      case 'c': exiting = false; console.println("Exit cancelled."); break;
      case 'r':
        if (xSemaphoreTake(cardLock, 0) == pdTRUE) {
          if (upload && !rawReady) reclaim();
          xSemaphoreGive(cardLock);
        }
        break;
      case 'l':
        if (!upload) {
          File root = SD_MMC.open("/");
          for (File item = root.openNextFile(); item; item = root.openNextFile()) {
            console.printf("%s %u\n", item.name(), unsigned(item.size()));
          }
        }
        break;
      default:
        console.println("DIAGNOSTIC ONLY: disposable card. u=UPLOAD x=exit c=cancel l=list r=retry");
    }
  }
  if (xSemaphoreTake(cardLock, 0) == pdTRUE) {
    if (rawReady && digitalRead(SDIO_DET) != LOW) {
      drive.mediaPresent(false);
      ejected = true;
      sdmmc_host_deinit();
      rawReady = false;
      console.println("Card removed. Reinsert, exit and re-enter UPLOAD to expose again.");
    }
    if (exiting && uint32_t(millis() - exitRequestedMs) >= 3000 &&
        uint32_t(millis() - lastIoMs) >= 1000) reclaim();
    xSemaphoreGive(cardLock);
  }
  delay(1);
}
