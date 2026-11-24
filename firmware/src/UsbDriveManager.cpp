#include "UsbDriveManager.h"

#if BODAQS_A8_USB_DRIVE
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
#include "BoardSelect.h"
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
std::atomic<bool> usbConfigured{false}, mediaPublished{false};
std::atomic<uint32_t> usbConnectionEpoch{0}, publishedEpoch{0};
#if defined(BODAQS_USB_DIAGNOSTICS)
// Temporary reconnect probe. Excluded from ordinary development/release builds.
std::atomic<uint32_t> probeStarted{0}, probeStopped{0}, probeSuspended{0}, probeResumed{0};
std::atomic<uint32_t> probeReads{0}, probeWrites{0}, probeFailures{0}, probeLockTimeouts{0};
std::atomic<int32_t> probeLastError{0};
#endif

void publishMedia(bool present) {
  mediaPublished = present;
  drive.mediaPresent(present);
}

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
  if (!board::gBoard) return false;
  const auto& storage = board::gBoard->storage;
  sdmmc_host_t host = SDMMC_HOST_DEFAULT();
  host.flags = storage.sdmmc_1bit ? SDMMC_HOST_FLAG_1BIT : SDMMC_HOST_FLAG_4BIT;
  host.max_freq_khz = SDMMC_FREQ_DEFAULT;
  sdmmc_slot_config_t slot = SDMMC_SLOT_CONFIG_DEFAULT();
  slot.width = storage.sdmmc_1bit ? 1 : 4;
  slot.clk = gpio_num_t(storage.sdmmc_clk); slot.cmd = gpio_num_t(storage.sdmmc_cmd);
  slot.d0 = gpio_num_t(storage.sdmmc_d0); slot.d1 = gpio_num_t(storage.sdmmc_d1);
  slot.d2 = gpio_num_t(storage.sdmmc_d2); slot.d3 = gpio_num_t(storage.sdmmc_d3);
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
#if defined(BODAQS_USB_DIAGNOSTICS)
  if (write) ++probeWrites; else ++probeReads;
#endif
  if (!ioLock || xSemaphoreTake(ioLock, pdMS_TO_TICKS(1000)) != pdTRUE) {
#if defined(BODAQS_USB_DIAGNOSTICS)
    ++probeLockTimeouts;
#endif
    return -1;
  }
  const uint32_t epoch = usbConnectionEpoch.load();
  if (!usbConfigured || !mediaPublished || publishedEpoch.load() != epoch) {
    xSemaphoreGive(ioLock);
    return -1; // Old host session; not an SD I/O failure.
  }
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
#if defined(BODAQS_USB_DIAGNOSTICS)
    if (!ok) probeLastError = result;
#endif
    bytes += count; position += count; remaining -= count;
  }
  if (!ok) ioFailed = true;
#if defined(BODAQS_USB_DIAGNOSTICS)
  if (!ok) ++probeFailures;
#endif
  lastIoMs = millis();
  busy = false;
  xSemaphoreGive(ioLock);
  return ok && usbConfigured && usbConnectionEpoch.load() == epoch ? int32_t(size) : -1;
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
  UsbUploadSession::ExposeResult expose() override {
    using Result = UsbUploadSession::ExposeResult;
    if (!ioLock || !storageGranted()) return Result::Failed;
    if (!usbConfigured || xSemaphoreTake(ioLock, 0) != pdTRUE) return Result::LinkChanged;
    const uint32_t epoch = usbConnectionEpoch.load();
    bool ok = StorageManager_cardDetected() && beginRaw();
    if (ok) ok = drive.begin(rawCard.csd.capacity, rawCard.csd.sector_size);
    bool changed = !usbConfigured || usbConnectionEpoch.load() != epoch;
    if (ok && !changed) {
      publishedEpoch = epoch;
      lastIoMs = millis();
      publishMedia(true);
      // Cover a USB event racing initialization/publication on the other task.
      changed = !usbConfigured || usbConnectionEpoch.load() != epoch;
    }
    if (!ok || changed) {
      publishMedia(false);
      if (rawReady) { sdmmc_host_deinit(); rawReady = false; }
    }
    xSemaphoreGive(ioLock);
    return changed ? Result::LinkChanged : (ok ? Result::Ready : Result::Failed);
  }
  bool withdraw(bool requireQuiet) override {
    if (!ioLock) return true; // No export is possible without the lock.
    if (xSemaphoreTake(ioLock, 0) != pdTRUE) return false;
    if (rawReady && requireQuiet && uint32_t(millis() - lastIoMs.load()) < 1000) {
      xSemaphoreGive(ioLock);
      return false;
    }
    publishMedia(false);
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
  usbConfigured = bool(USB);
  USB.onEvent([](void*, esp_event_base_t, int32_t event, void*) {
    if (event == ARDUINO_USB_STARTED_EVENT || event == ARDUINO_USB_STOPPED_EVENT) {
      // Stop admitting media immediately. Raw I/O already in progress finishes
      // under ioLock; only the main loop deinitializes or remounts the card.
      usbConfigured = false;
      publishMedia(false);
      if (event == ARDUINO_USB_STARTED_EVENT) {
        hostEjected = false;
        ++usbConnectionEpoch;
        usbConfigured = true;
      }
    }
#if defined(BODAQS_USB_DIAGNOSTICS)
    switch (event) {
      case ARDUINO_USB_STARTED_EVENT: ++probeStarted; break;
      case ARDUINO_USB_STOPPED_EVENT: ++probeStopped; break;
      case ARDUINO_USB_SUSPEND_EVENT: ++probeSuspended; break;
      case ARDUINO_USB_RESUME_EVENT: ++probeResumed; break;
    }
#endif
  });
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
  UsbUploadSession::Inputs input{usbConfigured.load(), StorageManager_cardDetected(), busy.load(),
                                hostEjected.exchange(false), ioFailed.exchange(false), lastIoMs.load(),
                                usbConnectionEpoch.load()};
  const auto previous = session.state();
  session.poll(input, millis());
  if (session.active() && input.connected && session.state() != UsbUploadSession::State::Ejected &&
      session.state() != UsbUploadSession::State::Error) PowerManager::noteActivity();
  if (previous != session.state()) { UI::status(session.label()); WiFiManager::refreshDiscovery(); }
#if defined(BODAQS_USB_DIAGNOSTICS)
  static uint32_t lastProbeMs = 0;
  if (uint32_t(millis() - lastProbeMs) >= 1000 && Serial) {
    lastProbeMs = millis();
    Serial.printf("[DEBUG-a8usb] state=%s owner=%s connected=%u mounted=%u suspended=%u media=%u busy=%u "
                  "start=%lu stop=%lu suspend=%lu resume=%lu read=%lu write=%lu failed=%lu lock_timeout=%lu error=%ld\n",
                  session.stateKey(), StorageManager_ownershipStatus(), usbConfigured.load(), tud_mounted(), tud_suspended(),
                  mediaPublished.load(), busy.load(), (unsigned long)probeStarted.load(), (unsigned long)probeStopped.load(),
                  (unsigned long)probeSuspended.load(), (unsigned long)probeResumed.load(),
                  (unsigned long)probeReads.load(), (unsigned long)probeWrites.load(),
                  (unsigned long)probeFailures.load(), (unsigned long)probeLockTimeouts.load(),
                  (long)probeLastError.load());
  }
#endif
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
#if defined(BODAQS_USB_DIAGNOSTICS)
const char* diagnosticLine(uint8_t row) {
  static char text[48];
  switch (row) {
    case 0:
      snprintf(text, sizeof(text), "C%u M%u S%u B%u", usbConfigured.load(), tud_mounted(), tud_suspended(), busy.load());
      break;
    case 1:
      snprintf(text, sizeof(text), "U%lu D%lu S%lu R%lu", (unsigned long)probeStarted.load(),
               (unsigned long)probeStopped.load(), (unsigned long)probeSuspended.load(), (unsigned long)probeResumed.load());
      break;
    case 2:
      snprintf(text, sizeof(text), "R%lu W%lu E%lu", (unsigned long)probeReads.load(),
               (unsigned long)probeWrites.load(), (unsigned long)probeFailures.load());
      break;
    default:
      snprintf(text, sizeof(text), "L%lu rc%lx", (unsigned long)probeLockTimeouts.load(), (unsigned long)probeLastError.load());
      break;
  }
  return text;
}
#endif
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
