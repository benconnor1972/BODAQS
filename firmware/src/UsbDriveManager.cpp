#include "UsbDriveManager.h"

#if defined(BODAQS_A8_USB_DRIVE)
#include <Arduino.h>
#include <ArduinoJson.h>
#include <USB.h>
#include <USBMSC.h>
#include <tusb.h>
#include <driver/sdmmc_host.h>
#include <sdmmc_cmd.h>
#include <esp_mac.h>
#include <freertos/semphr.h>
#include <atomic>
#include "ConfigManager.h"
#include "StorageManager.h"
#include "UI.h"
#include "WiFiManager.h"
#include "PowerManager.h"
#include "UsbUploadSession.h"

#if ARDUINO_USB_MODE != 0 || !ARDUINO_USB_CDC_ON_BOOT
#error "A8 USB drive development build requires USB-OTG and CDC on boot"
#endif

namespace {
// Register MSC before Arduino starts the composite CDC/MSC device. No media is
// exposed at boot, even with a connected cable.
class RegisteredDrive : public USBMSC {
public:
  RegisteredDrive() { vendorID("BODAQS"); productID("A8 SD card"); productRevision("0001"); }
} drive;
SemaphoreHandle_t ioLock = nullptr;
sdmmc_card_t rawCard{};
bool rawReady = false;
DMA_ATTR uint8_t sector[512];
std::atomic<bool> busy{false}, hostEjected{false}, ioFailed{false};
std::atomic<uint32_t> lastIoMs{0};

bool writeIdentity() {
  uint8_t mac[6];
  if (esp_efuse_mac_get_default(mac) != ESP_OK) return false;
  char identity[32];
  snprintf(identity, sizeof(identity), "esp32s3-%02x%02x%02x%02x%02x%02x",
           mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
  JsonDocument marker;
  marker["schema"] = "bodaqs.logger.usb";
  marker["version"] = 1;
  marker["device_id"] = identity;
  marker["logger_id"] = ConfigManager::loggerId();
  String displayName(ConfigManager::get().loggerName);
  displayName.trim();
  marker["display_name"] = displayName.length() ? displayName : ConfigManager::loggerId();
  marker["recordings_path"] = ".";
  String body;
  serializeJson(marker, body);
  return StorageManager_saveTextFile("/.bodaqs-logger.json", body);
}

bool beginRaw() {
  sdmmc_host_t host = SDMMC_HOST_DEFAULT();
  host.flags = SDMMC_HOST_FLAG_4BIT;
  host.max_freq_khz = SDMMC_FREQ_DEFAULT;
  sdmmc_slot_config_t slot = SDMMC_SLOT_CONFIG_DEFAULT();
  slot.width = 4;
  slot.clk = GPIO_NUM_10; slot.cmd = GPIO_NUM_9; slot.d0 = GPIO_NUM_11;
  slot.d1 = GPIO_NUM_12; slot.d2 = GPIO_NUM_7; slot.d3 = GPIO_NUM_8;
  esp_err_t result = host.init();
  if (result != ESP_OK) return false;
  result = sdmmc_host_init_slot(host.slot, &slot);
  if (result == ESP_OK) result = sdmmc_card_init(&host, &rawCard);
  if (result != ESP_OK || rawCard.csd.sector_size != sizeof(sector)) {
    host.deinit();
    return false;
  }
  rawReady = true;
  return true;
}

int32_t transfer(uint32_t lba, uint32_t offset, void* data, uint32_t size, bool write) {
  if (!ioLock || xSemaphoreTake(ioLock, pdMS_TO_TICKS(1000)) != pdTRUE) return -1;
  busy = true;
  const uint64_t address = uint64_t(lba) * sizeof(sector) + offset;
  bool ok = rawReady && StorageManager_cardDetected() &&
            address + size <= uint64_t(rawCard.csd.capacity) * sizeof(sector);
  auto* bytes = static_cast<uint8_t*>(data);
  uint64_t position = address;
  uint32_t remaining = size;
  while (ok && remaining) {
    const uint32_t block = position / sizeof(sector);
    const size_t within = position % sizeof(sector);
    const size_t count = min(size_t(remaining), sizeof(sector) - within);
    esp_err_t result = ESP_OK;
    if (!write || within || count != sizeof(sector)) result = sdmmc_read_sectors(&rawCard, sector, block, 1);
    if (result == ESP_OK && write) {
      memcpy(sector + within, bytes, count);
      result = sdmmc_write_sectors(&rawCard, sector, block, 1);
    } else if (result == ESP_OK) memcpy(bytes, sector + within, count);
    ok = result == ESP_OK;
    bytes += count; position += count; remaining -= count;
  }
  if (!ok) ioFailed = true;
  lastIoMs = millis();
  busy = false;
  xSemaphoreGive(ioLock);
  return ok ? int32_t(size) : -1;
}

class Backend : public UsbUploadSession::Backend {
public:
  bool localReady() const override {
    return StorageManager_cardDetected() && StorageFilesystem::ownership().localAvailable() && StorageManager_isMounted();
  }
  bool requestStorage() override { return writeIdentity() && StorageManager_requestExternalAccess(); }
  bool storageGranted() const override {
    return StorageFilesystem::ownership().state() == StorageOwnership::State::External;
  }
  void cancelStorage() override { StorageManager_cancelExternalAccess(); }
  bool expose() override {
    if (!ioLock || !storageGranted() || xSemaphoreTake(ioLock, 0) != pdTRUE) return false;
    bool ok = StorageManager_cardDetected() && beginRaw();
    if (ok) ok = drive.begin(rawCard.csd.capacity, rawCard.csd.sector_size);
    if (ok) { lastIoMs = millis(); drive.mediaPresent(true); }
    else if (rawReady) { sdmmc_host_deinit(); rawReady = false; }
    xSemaphoreGive(ioLock);
    return ok;
  }
  bool withdraw(bool requireQuiet) override {
    if (!ioLock) return true; // No export is possible without the lock.
    if (xSemaphoreTake(ioLock, 0) != pdTRUE) return false;
    if (rawReady && requireQuiet && uint32_t(millis() - lastIoMs.load()) < 1000) {
      xSemaphoreGive(ioLock);
      return false;
    }
    drive.mediaPresent(false);
    if (rawReady) sdmmc_host_deinit();
    rawReady = false;
    xSemaphoreGive(ioLock);
    return true;
  }
  bool reclaim() override {
    if (!StorageManager_cardDetected()) return false;
    if (StorageFilesystem::ownership().localAvailable()) return StorageManager_readyForLogging();
    return StorageManager_reclaimLocalAccess();
  }
} backend;
UsbUploadSession session(backend);
}

namespace UsbDriveManager {
bool enabled() { return true; }
void begin() {
  if (ioLock) return;
  ioLock = xSemaphoreCreateMutex();
  drive.onRead([](uint32_t lba, uint32_t offset, void* data, uint32_t size) {
    return transfer(lba, offset, data, size, false);
  });
  drive.onWrite([](uint32_t lba, uint32_t offset, uint8_t* data, uint32_t size) {
    return transfer(lba, offset, data, size, true);
  });
  drive.onStartStop([](uint8_t, bool start, bool eject) {
    if (!start && eject) hostEjected = true; // Main loop stops I/O and reclaims.
    return true;
  });
}
void loop() {
  UsbUploadSession::Inputs input{tud_mounted(), StorageManager_cardDetected(), busy.load(),
                                hostEjected.exchange(false), ioFailed.exchange(false), lastIoMs.load()};
  const auto previous = session.state();
  session.poll(input, millis());
  if (session.active() && input.connected && session.state() != UsbUploadSession::State::Ejected &&
      session.state() != UsbUploadSession::State::Error) PowerManager::noteActivity();
  if (previous != session.state()) { UI::status(session.label()); WiFiManager::refreshDiscovery(); }
}
bool active() { return session.active(); }
bool enter(bool logging) { return session.enter(logging); }
void requestExit() { session.requestExit(millis()); }
bool cancelExit() {
  const bool ok = session.cancelExit();
  if (ok) { UI::status(session.label()); WiFiManager::refreshDiscovery(); }
  return ok;
}
void retry() { session.retry(); }
bool exitPending() { return session.exitPending(); }
uint8_t phase() { return uint8_t(session.state()); }
const char* stateKey() { return session.stateKey(); }
const char* label() { return session.label(); }
const char* shortLabel() { return session.shortLabel(); }
}
#else
namespace UsbDriveManager {
bool enabled() { return false; }
void begin() {}
void loop() {}
bool active() { return false; }
bool enter(bool) { return false; }
void requestExit() {}
bool cancelExit() { return false; }
void retry() {}
bool exitPending() { return false; }
uint8_t phase() { return 0; }
const char* stateKey() { return "disabled"; }
const char* label() { return "Upload mode"; }
const char* shortLabel() { return "Upload mode"; }
}
#endif
