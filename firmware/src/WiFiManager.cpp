#include "WiFiManager.h"
#include "ConfigManager.h"
#include <esp_wifi.h>
#include <esp_bt.h>
#include <esp_coexist.h>
#include <esp_heap_caps.h>
#include <cstring>
#include "RTCManager.h"
#include "DebugLog.h"

#define WIFI_LOGE(...) LOGE_TAG("WiFi", __VA_ARGS__)
#define WIFI_LOGW(...) LOGW_TAG("WiFi", __VA_ARGS__)
#define WIFI_LOGI(...) LOGI_TAG("WiFi", __VA_ARGS__)
#define WIFI_LOGD(...) LOGD_TAG("WiFi", __VA_ARGS__)
#define RTC_LOGI(...)  LOGI_TAG("RTC", __VA_ARGS__)
#define ADC_LOGD(...)  LOGD_TAG("ADC", __VA_ARGS__)

static const uint32_t SCAN_TIMEOUT_MS     = 6000;   // single active scan budget
static const uint32_t CONNECT_TIMEOUT_MS  = 12000;  // assoc/auth/IP wait
static const int      RSSI_FLOOR_DBM      = -90;    // ignore weaker than this
static uint32_t s_linkDropDeadlineMs = 0;
static const uint32_t IDLE_OFF_MS = 015UL * 60UL * 500UL;  // 15 minutes
static uint32_t s_idleOffDeadlineMs = 0;
static bool s_rtcSyncPending = false;   // we connected solely to set time
static bool s_prevEnabledBeforeLogging = false;
static bool s_suspendedForLogging = false;

WiFiMgrState WiFiManager::s_state = WiFiMgrState::OFF;
bool         WiFiManager::s_enabled = false;
bool         WiFiManager::s_haveIntentConnect = false;
uint32_t     WiFiManager::s_stateDeadlineMs = 0;

String       WiFiManager::s_targetSsid;
uint8_t      WiFiManager::s_targetBssid[6] = {0};
bool         WiFiManager::s_targetBssidSet = false;
bool         WiFiManager::s_loggingSuspended = false;
bool         WiFiManager::s_restoreEnabledAfterLogging = false;


IsLoggingActiveFn WiFiManager::s_isLogging = nullptr;
WiFiManager::OnOnlineFn  WiFiManager::s_onOnline = nullptr;
WiFiManager::OnOfflineFn WiFiManager::s_onOffline = nullptr;
WiFiManager::OnUiFn WiFiManager::s_onUi = nullptr;


String WiFiManager::s_currSsid;
int    WiFiManager::s_currRssi = 0;

static const char* wifiModeName_(wifi_mode_t mode) {
  switch (mode) {
    case WIFI_MODE_NULL: return "OFF";
    case WIFI_MODE_STA:  return "STA";
    case WIFI_MODE_AP:   return "AP";
    case WIFI_MODE_APSTA:return "AP+STA";
    default:             return "?";
  }
}

static void wifiDiag_(const char* reason) {
  WIFI_LOGD("%s: mode=%s wl=%d heap=%u largest=%u\n",
            reason ? reason : "wifi",
            wifiModeName_(WiFi.getMode()),
            (int)WiFi.status(),
            ESP.getFreeHeap(),
            heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));
}

static void keepStaIdle_(const char* reason) {
  wifiDiag_(reason);
  WiFi.scanDelete();
  WiFi.disconnect(false, false);
  if (WiFi.getMode() != WIFI_STA && !WiFi.mode(WIFI_STA)) {
    WIFI_LOGW("keepStaIdle_: failed to enter WIFI_STA\n");
  }
  btStop();
  wifiDiag_("keepStaIdle done");
}

static void hardOff_(const char* reason) {
  wifiDiag_(reason);
  WiFi.scanDelete();
  if (!WiFi.mode(WIFI_OFF)) {
    WIFI_LOGW("hardOff_: WiFi.mode(WIFI_OFF) failed\n");
  }
  btStop();
  wifiDiag_("hardOff done");
}

// Free helper, no access to WiFiManager privates needed
static void tryRtcSyncIfPending_() {
  if (!s_rtcSyncPending) return;
  {
    const auto& cfg = ConfigManager::get();
    // Use saved TZ if set; else fall back to AWST (UTC+8; POSIX uses inverted sign)
    const char* tz = (cfg.tz[0] ? cfg.tz : "AWST-8");

    // Re-issue SNTP config AFTER link-up to ensure client starts a query now.
    // (Safe to call multiple times; it resets the SNTP client.)
    configTzTime(tz, "0.pool.ntp.org", "1.pool.ntp.org", "time.nist.gov");
    RTC_LOGI("Re-kicked SNTP with TZ='%s'\n", tz);

  }
  (void)RTCManager_waitForSNTP(15000); // wait briefly for NTP
  RTCManager_sync();                            // capture baseEpoch from system
  s_rtcSyncPending = false;

  const auto& cfg = ConfigManager::get();
  if (!cfg.wifiEnabledDefault) {
    WiFiManager::disable();
  } else {
    WiFiManager::noteUserActivity();
  }
}



// ----- lifecycle -----
void WiFiManager::begin(IsLoggingActiveFn isLoggingFn) {
  s_isLogging = isLoggingFn;
  s_enabled   = false;
  s_state     = WiFiMgrState::OFF;
  s_haveIntentConnect = false;
  s_currSsid = "";
  s_currRssi = 0;
  s_idleOffDeadlineMs = 0;

  WiFi.persistent(false);       // don’t touch NVS
  hardOff_("begin");

}

void WiFiManager::loop() {
  // Hard guard: never do Wi-Fi work while logging
  if (loggingGuard_()) {
    // Only do the teardown once, when we transition into "logging"
    if (s_state != WiFiMgrState::OFF) {
      if (s_state == WiFiMgrState::ONLINE && s_onOffline) {
        s_onOffline();
      }
      shutdownRadio_();     // <-- actually power down radio/BT
      enterOff_();          // logical state = OFF
      notifyUi_();          // let the UI know Wi-Fi is now off
    }
    return;                 // while logging, WiFiManager is inert
  }

  // If WiFi link is already up, ensure our state reflects that.
  // This covers cases where we reconnected outside the CONNECTING path.
  if (s_enabled && WiFi.status() == WL_CONNECTED) {
    if (s_state != WiFiMgrState::ONLINE) {
      s_currSsid = WiFi.SSID();
      s_currRssi = WiFi.RSSI();
      s_state    = WiFiMgrState::ONLINE;
      s_idleOffDeadlineMs = millis() + IDLE_OFF_MS;   
      clearIntent_();
      if (s_onOnline) s_onOnline();
      notifyUi_();
      tryRtcSyncIfPending_();     

    } else {
      // keep live RSSI fresh
      s_currRssi = WiFi.RSSI();
    }
  }
  switch (s_state) {
    case WiFiMgrState::OFF:
      // stay here until enable()
      break;

    case WiFiMgrState::IDLE:
      if (!s_enabled) { enterOff_(); break; }
      if (s_haveIntentConnect) {
        // only attempt if we actually have configured networks
        if (configuredNetworksExist_()) startScan_();
        else clearIntent_(); // nothing to do
      }
      break;

    case WiFiMgrState::SCANNING:
      // startScan_() performs a synchronous scan and advances state directly.
      break;

    case WiFiMgrState::CONNECTING: {
      if (WiFi.status() == WL_CONNECTED) {
        s_currSsid = WiFi.SSID();
        s_currRssi = WiFi.RSSI();
        s_state = WiFiMgrState::ONLINE;
        s_idleOffDeadlineMs = millis() + IDLE_OFF_MS;   // <-- start idle timer

        if (s_onOnline) s_onOnline();
        clearIntent_();
        notifyUi_();
        tryRtcSyncIfPending_();     // <-- add this

      } else if (millis() >= s_stateDeadlineMs) {
        // connection attempt ended — return to IDLE (single pass only)
        keepStaIdle_("connect timeout");
        enterIdle_();
        clearIntent_();
        notifyUi_();
      }
      break;
    }

    case WiFiMgrState::ONLINE: {
      wl_status_t wl = WiFi.status();

      if (!s_enabled) {
        // user disabled Wi-Fi: immediate teardown
        if (s_onOffline) s_onOffline();
        hardOff_("disabled while online");
        enterOff_();
        s_linkDropDeadlineMs = 0;
        notifyUi_();
        break;
      }

      if (wl == WL_CONNECTED) {
        // link OK; keep sticky & fresh RSSI
        s_currRssi = WiFi.RSSI();
        s_linkDropDeadlineMs = 0;      // cancel any pending drop
          // ---- Auto-off check (idle timeout) ----
          if (s_idleOffDeadlineMs != 0 && (int32_t)(millis() - s_idleOffDeadlineMs) >= 0) {
            // Timeout: drop to IDLE (radio off) until user asks again
            if (s_onOffline) s_onOffline();
            keepStaIdle_("idle timeout");
            enterIdle_();
            s_idleOffDeadlineMs = 0;
            clearIntent_();
            notifyUi_();
            break;
          }
        break;
      }

      // Not connected: start (or honor) a drop deadline
      if (s_linkDropDeadlineMs == 0) {
        s_linkDropDeadlineMs = millis() + 1500;  // 1.5 s debounce
      } else if ((int32_t)(millis() - s_linkDropDeadlineMs) >= 0) {
        // still down after debounce: tear down to IDLE
        if (s_onOffline) s_onOffline();
        keepStaIdle_("link drop");
        enterIdle_();
        clearIntent_();
        s_linkDropDeadlineMs = 0;
        notifyUi_();
      }
      break;
    }
  }
}


// ----- public control -----
void WiFiManager::enable() {
  if (s_enabled) return;
  auto dumpAdc = [](const char* tag){
    ADC_LOGD("\n%s\n", tag);
    int pins[] = {15,17,18,10};
    for (int p : pins) {
      int v = analogRead(p);
      LOGD("  GPIO%02d = %d\n", p, v);
    }
  };
  dumpAdc("after WiFi on");
  wifiDiag_("enable");
  s_enabled = true;
  if (s_state == WiFiMgrState::OFF) enterIdle_();
  notifyUi_();
}

void WiFiManager::disable() {
  s_enabled = false;

  // Tell app we're going offline (only if we were actually online)
  if (s_state == WiFiMgrState::ONLINE && s_onOffline) s_onOffline();

  clearIntent_();
  s_idleOffDeadlineMs = 0;
  s_linkDropDeadlineMs = 0;
  hardOff_("disable");

  enterOff_();
  notifyUi_();
}


bool WiFiManager::isEnabled() { return s_enabled; }

void WiFiManager::connectNow() {
  if (!s_enabled || loggingGuard_()) return;
  if (s_state == WiFiMgrState::SCANNING || s_state == WiFiMgrState::CONNECTING) {
    wifiDiag_("connectNow ignored: already busy");
    return;
  }
  if (s_state == WiFiMgrState::ONLINE) {
    noteUserActivity();
    wifiDiag_("connectNow ignored: already online");
    return;
  }

  s_haveIntentConnect = true;

  // Treat as user activity regardless of state
  s_idleOffDeadlineMs = millis() + IDLE_OFF_MS;

  // If we're not already trying, kick the state machine
  if (s_state == WiFiMgrState::OFF) {
    enterIdle_();
  }
  if (s_state == WiFiMgrState::IDLE) {
    // Start a fresh scan/connect pass.
    startScan_();
  }
  notifyUi_();
}

void WiFiManager::disconnect() {
  if (s_state == WiFiMgrState::ONLINE && s_onOffline) s_onOffline();
  clearIntent_();
  s_idleOffDeadlineMs = 0;
  s_linkDropDeadlineMs = 0;
  keepStaIdle_("disconnect");
  enterIdle_();
  notifyUi_();
}

void WiFiManager::shutdownRadio_() {
  hardOff_("shutdownRadio");
}



void WiFiManager::maybeConnectForRTC() {
  const auto& cfg = ConfigManager::get();
  if (!cfg.wifiAutoTimeOnRtcInvalid) return;        // feature off in config
  if (RTCManager_hasValidTime()) return;            // already valid
  if (!configuredNetworksExist_()) return;          // nowhere to connect

  enable();                         // radios on
  s_haveIntentConnect = true;       // kick SCANNING → CONNECTING path
  s_rtcSyncPending = true;          // remember why we’re doing this
}

void WiFiManager::suspendForLogging() {
  if (s_suspendedForLogging) return;
  s_prevEnabledBeforeLogging = s_enabled;
  s_suspendedForLogging = true;
  disable();  
}

void WiFiManager::resumeAfterLogging() {
  if (!s_suspendedForLogging) return;
  s_suspendedForLogging = false;
  if (s_prevEnabledBeforeLogging) {
    enable();
    connectNow();
    noteUserActivity();
  } else {
    disable(); // stay OFF
  }
}



WiFiStatus WiFiManager::status() {
  WiFiStatus st;
  st.state   = s_state;
  st.wl      = WiFi.status();
  st.enabled = s_enabled;
  st.ssid    = (s_state == WiFiMgrState::ONLINE) ? s_currSsid : "";
  st.rssi    = (s_state == WiFiMgrState::ONLINE) ? s_currRssi : 0;
  return st;
}

void WiFiManager::notifyUi_() {
  if (s_onUi) s_onUi();
}




// ----- internals -----
void WiFiManager::enterOff_() {
  s_state = WiFiMgrState::OFF;
  s_currSsid = "";
  s_currRssi = 0;
}

void WiFiManager::enterIdle_() {
  s_state = s_enabled ? WiFiMgrState::IDLE : WiFiMgrState::OFF;
}

void WiFiManager::startScan_() {
  // Configure radio for STA scans only; we'll bring it up briefly.
  wifiDiag_("startScan");
  if (!WiFi.mode(WIFI_STA)) {
    WIFI_LOGE("startScan_: WiFi.mode(WIFI_STA) failed\n");
    enterIdle_();
    clearIntent_();
    return;
  }
  WiFi.setSleep(false);
  esp_wifi_set_ps(WIFI_PS_NONE);
  // Reset any target decided earlier
  s_targetSsid = "";
  s_targetBssidSet = false;
  memset(s_targetBssid, 0, sizeof(s_targetBssid));

  // Run a synchronous scan. The async path was unreliable on this core/runtime.
  WiFi.scanDelete();
  s_state = WiFiMgrState::SCANNING;
  s_stateDeadlineMs = 0;
  notifyUi_();

  const int sc = WiFi.scanNetworks(false /* sync */, true /* show hidden */, false /* passive */, 300 /* ms per chan */);
  WIFI_LOGI("startScan_: sync scan returned %d\n", sc);
  if (sc < 0) {
    WIFI_LOGW("startScan_: synchronous scan failed\n");
    enterIdle_();
    clearIntent_();
    notifyUi_();
    return;
  }

  selectAndConnect_();
}

static bool bssidEqual_(const uint8_t a[6], const uint8_t b[6]) {
  for (int i=0;i<6;++i) if (a[i] != b[i]) return false;
  return true;
}

void WiFiManager::selectAndConnect_() {
  int n = WiFi.scanComplete();
  if (n < 0) n = 0;

  // Choose the strongest eligible network across ALL configured entries.
  size_t count = 0;
  const auto* nets = ConfigManager::wifiNetworks(count);
  int chosenIndex = -1;
  int chosenRssi  = -127;
  uint8_t chosenBssid[6] = {0};
  bool chosenBssidSet = false;
  int chosenChannel = 0;

  for (size_t i = 0; i < count; ++i) {
    if (!nets[i].ssid[0]) continue;

    // Find strongest BSSID for this SSID in the scan results
    int bestRssi = -127;
    uint8_t bestBssid[6] = {0};
    bool bestSet = false;
    int bestChannel = 0;

    // If user pinned a BSSID, prefer/require that exact AP if present
    if (nets[i].bssidSet) {
      for (int k = 0; k < n; ++k) {
        if (!String(nets[i].ssid).equals(WiFi.SSID(k))) continue;

        const uint8_t* b = WiFi.BSSID(k);
        if (!b) continue;

        if (bssidEqual_(b, nets[i].bssid)) {
          bestRssi = WiFi.RSSI(k);
          memcpy(bestBssid, b, 6);
          bestSet = true;
          bestChannel = WiFi.channel(k);
          break; // exact match found; no need to check other BSSIDs
        }
      }
    }

    // If no pinned BSSID or the pinned one wasn't seen, take the strongest for this SSID
    if (!bestSet) {
      for (int k = 0; k < n; ++k) {
        if (!String(nets[i].ssid).equals(WiFi.SSID(k))) continue;
        int r = WiFi.RSSI(k);
        if (r > bestRssi) {
          bestRssi = r;

          const uint8_t* b = WiFi.BSSID(k);
          if (b) {
            memcpy(bestBssid, b, 6);
          } else {
            memset(bestBssid, 0, 6);
          }

          bestSet = true;
          bestChannel = WiFi.channel(k);
        }
      }
    }
    // Eligibility check: respect per-entry min RSSI (or global floor)
    const int minNeed = (nets[i].minRssi >= -100 && nets[i].minRssi <= -10)
                        ? nets[i].minRssi : RSSI_FLOOR_DBM;
    if (!bestSet || bestRssi < minNeed) continue;

    // Keep the strongest overall; if tied, prefer earlier priority (smaller i)
    if (bestRssi > chosenRssi || (bestRssi == chosenRssi && chosenIndex == -1)) {
      chosenIndex   = (int)i;
      chosenRssi    = bestRssi;
      memcpy(chosenBssid, bestBssid, 6);
      chosenBssidSet = bestSet;
      chosenChannel  = bestChannel;
    }
  }

  // No candidate — back to IDLE
  if (chosenIndex < 0) {
    WIFI_LOGW("selectAndConnect_: no eligible AP found\n");
    WiFi.scanDelete();
    enterIdle_();
    clearIntent_();
    return;
  }

  // Attempt connect to the chosen network
  s_targetSsid = String(nets[chosenIndex].ssid);
  if (chosenBssidSet) { memcpy(s_targetBssid, chosenBssid, 6); s_targetBssidSet = true; }
  else { memset(s_targetBssid, 0, 6); s_targetBssidSet = false; }

  WiFi.scanDelete();
  wifiDiag_("selectAndConnect");
  if (!WiFi.mode(WIFI_STA)) {
    WIFI_LOGE("selectAndConnect_: WiFi.mode(WIFI_STA) failed\n");
    enterIdle_();
    clearIntent_();
    return;
  }
  WiFi.setSleep(true);
  esp_wifi_set_ps(WIFI_PS_MIN_MODEM);
  s_idleOffDeadlineMs = millis() + IDLE_OFF_MS;

  auto ipFrom = [](const uint8_t a[4]) -> IPAddress {
    return IPAddress(a[0], a[1], a[2], a[3]);
  };

  if (nets[chosenIndex].staticIp) {
    IPAddress ip = ipFrom(nets[chosenIndex].ip);
    IPAddress gw = ipFrom(nets[chosenIndex].gateway);
    IPAddress sn = ipFrom(nets[chosenIndex].subnet);
    IPAddress d1 = ipFrom(nets[chosenIndex].dns1);
    IPAddress d2 = ipFrom(nets[chosenIndex].dns2);

    // Sensible fallback: if DNS1 unset, use gateway
    if (d1 == IPAddress(0, 0, 0, 0)) d1 = gw;

    // Use 4-arg if you don't want dns2, or 5-arg if your core supports it
    WiFi.config(ip, gw, sn, d1, d2);
  } else {
    // IMPORTANT: revert to DHCP when switching away from a static network
    WiFi.config(INADDR_NONE, INADDR_NONE, INADDR_NONE);
  }


  // Begin connect (password may be empty for open). Use the 5-arg overload to pin BSSID/channel.
  const char* pwd = nets[chosenIndex].password;
  const uint8_t* bssidPtr = s_targetBssidSet ? s_targetBssid : nullptr;
  int channel = chosenChannel > 0 ? chosenChannel : 0; // 0 = auto if unknown
  WIFI_LOGI("selected[%d]: ssid='%s' rssi=%d channel=%d staticIp=%d\n",
            chosenIndex,
            s_targetSsid.c_str(),
            chosenRssi,
            channel,
            (int)nets[chosenIndex].staticIp);
  wifiDiag_("before WiFi.begin");
  WiFi.begin(s_targetSsid.c_str(), (pwd ? pwd : ""), channel, bssidPtr, true /* connect */);
  s_state = WiFiMgrState::CONNECTING;
  s_stateDeadlineMs = millis() + CONNECT_TIMEOUT_MS;
  notifyUi_();

}

bool WiFiManager::loggingGuard_() {
  return s_isLogging && s_isLogging();
}

bool WiFiManager::configuredNetworksExist_() {
  return ConfigManager::hasConfiguredNetworks();
}

void WiFiManager::clearIntent_() {
  s_haveIntentConnect = false;
}

void WiFiManager::noteUserActivity() {
  if (s_enabled && s_state == WiFiMgrState::ONLINE) {
    s_idleOffDeadlineMs = millis() + IDLE_OFF_MS;
  }
}
