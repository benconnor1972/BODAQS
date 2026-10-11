#include "DeviceRestart.h"
#include "LoggingManager.h"
#include "DisplayManager.h"
#include "RTCManager.h"
#include "UI.h"
#include <esp_system.h>

void DeviceRestart::restart() {
  if (LoggingManager::isRunning()) {
    UI::toast("Stop logging first", 1200, 1);
    return;
  }
  UI::toastModal("Restarting...", 800, 1);
  DisplayManager::present();
  Serial.println("[Restart] Restarting via esp_restart()");
  Serial.flush();
  delay(150);
  RTCManager_invalidateInternalTime();
  esp_restart();
}
