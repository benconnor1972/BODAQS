#include "UploadModeManager.h"

#include "DebugLog.h"
#include "UI.h"
#include "WiFiManager.h"
#include "StorageManager.h"
#include "LoggingManager.h"
#include "UsbDriveManager.h"

#define UPLOAD_LOGI(...) LOGI_TAG("Upload", __VA_ARGS__)
#define UPLOAD_LOGW(...) LOGW_TAG("Upload", __VA_ARGS__)

namespace {
  UploadModeLoggingActiveFn s_isLogging = nullptr;
  bool s_active = false;

  bool loggingActive_() {
    return (s_isLogging && s_isLogging()) || LoggingManager::configurationLocked() ||
        StorageManager_recordingIoPending();
  }
}

void UploadModeManager::begin(UploadModeLoggingActiveFn isLoggingFn) {
  s_isLogging = isLoggingFn;
  s_active = false;
  UsbDriveManager::begin();
}

void UploadModeManager::loop() { UsbDriveManager::loop(); }

bool UploadModeManager::isActive() {
  return UsbDriveManager::enabled() ? UsbDriveManager::active() : s_active;
}

bool UploadModeManager::canEnter() {
  return !loggingActive_();
}

bool UploadModeManager::enter() {
  if (isActive()) {
    return true;
  }
  if (!canEnter()) {
    UPLOAD_LOGW("enter refused: logging active\n");
    UI::println("Cannot enter upload mode while logging.", "Busy", UI::TARGET_BOTH, UI::LVL_WARN, 1500, 2);
    return false;
  }

  if (UsbDriveManager::enabled()) {
    if (!UsbDriveManager::enter(loggingActive_())) return false;
  } else s_active = true;
  UPLOAD_LOGI("Upload mode entered\n");
  UI::println("Upload mode active.", "Upload\nmode", UI::TARGET_BOTH, UI::LVL_INFO, 1500, 2);
  UI::status("Upload mode");
  WiFiManager::refreshDiscovery();
  return true;
}

void UploadModeManager::exit() {
  if (!isActive()) {
    return;
  }

  if (UsbDriveManager::enabled()) {
    UsbDriveManager::requestExit();
    UI::status("Disconnecting USB...");
    return;
  }

  if (!StorageFilesystem::ownership().localAvailable() &&
      !StorageManager_cancelExternalAccess()) {
    UI::println("Storage reclaim required before exit.", "Storage busy", UI::TARGET_BOTH, UI::LVL_WARN, 1500, 2);
    return;
  }

  s_active = false;
  UPLOAD_LOGI("Upload mode exited\n");
  UI::println("Upload mode exited.", "Upload off", UI::TARGET_BOTH, UI::LVL_INFO, 1200, 2);
  UI::status("Ready");
  WiFiManager::refreshDiscovery();
}

bool UploadModeManager::toggle() {
  if (exitPending()) { cancelExit(); return isActive(); }
  if (isActive()) {
    exit();
    return isActive();
  }
  return enter();
}

const char* UploadModeManager::stateLabel() {
  return isActive() ? "upload" : "normal";
}

bool UploadModeManager::usbEnabled() { return UsbDriveManager::enabled(); }
bool UploadModeManager::exitPending() { return UsbDriveManager::exitPending(); }
bool UploadModeManager::cancelExit() { return UsbDriveManager::cancelExit(); }
bool UploadModeManager::retryStorage() {
  if (!usbEnabled() || !isActive() || strcmp(usbStateKey(), "error") != 0) return false;
  UsbDriveManager::retry();
  return true;
}
uint8_t UploadModeManager::usbPhase() { return UsbDriveManager::phase(); }
const char* UploadModeManager::usbStateKey() { return UsbDriveManager::stateKey(); }
const char* UploadModeManager::transferLabel() { return UsbDriveManager::label(); }
const char* UploadModeManager::shortTransferLabel() { return UsbDriveManager::shortLabel(); }
