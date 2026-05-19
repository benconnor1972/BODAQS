#include "UploadModeManager.h"

#include "DebugLog.h"
#include "UI.h"
#include "WiFiManager.h"

#define UPLOAD_LOGI(...) LOGI_TAG("Upload", __VA_ARGS__)
#define UPLOAD_LOGW(...) LOGW_TAG("Upload", __VA_ARGS__)

namespace {
  UploadModeLoggingActiveFn s_isLogging = nullptr;
  bool s_active = false;

  bool loggingActive_() {
    return s_isLogging && s_isLogging();
  }
}

void UploadModeManager::begin(UploadModeLoggingActiveFn isLoggingFn) {
  s_isLogging = isLoggingFn;
  s_active = false;
}

bool UploadModeManager::isActive() {
  return s_active;
}

bool UploadModeManager::canEnter() {
  return !loggingActive_();
}

bool UploadModeManager::enter() {
  if (s_active) {
    return true;
  }
  if (!canEnter()) {
    UPLOAD_LOGW("enter refused: logging active\n");
    UI::println("Cannot enter upload mode while logging.", "Busy", UI::TARGET_BOTH, UI::LVL_WARN, 1500, 2);
    return false;
  }

  s_active = true;
  UPLOAD_LOGI("Upload mode entered\n");
  UI::println("Upload mode active.", "Upload\nmode", UI::TARGET_BOTH, UI::LVL_INFO, 1500, 2);
  UI::status("Upload mode");
  WiFiManager::refreshDiscovery();
  return true;
}

void UploadModeManager::exit() {
  if (!s_active) {
    return;
  }

  s_active = false;
  UPLOAD_LOGI("Upload mode exited\n");
  UI::println("Upload mode exited.", "Upload off", UI::TARGET_BOTH, UI::LVL_INFO, 1200, 2);
  UI::status("Ready");
  WiFiManager::refreshDiscovery();
}

bool UploadModeManager::toggle() {
  if (s_active) {
    exit();
    return false;
  }
  return enter();
}

const char* UploadModeManager::stateLabel() {
  return s_active ? "upload" : "normal";
}
