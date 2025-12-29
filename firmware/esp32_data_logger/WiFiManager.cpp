#include "WiFiManager.h"
#include "ConfigManager.h"
#include <esp_wifi.h>
#include <esp_bt.h>
#include <esp_coexist.h>
#include "RTCManager.h"   // <-- add this include


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
    Serial.printf("[RTC] Re-kicked SNTP with TZ='%s'\n", tz);

  }
  const bool ok = RTCManager_waitForSNTP(15000); // wait briefly for NTP
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
  WiFi.mode(WIFI_OFF);          // fully stop Wi-Fi driver
  btStop();                     // stop BT controller (safe to call even if never started)

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

    case WiFiMgrState::SCANNING: {
      int sc = WiFi.scanComplete();
      if (sc >= 0 || millis() >= s_stateDeadlineMs) {
        // scan finished OR timebox expired — proceed
        selectAndConnect_();
      }
      break;
    }

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
        WiFi.disconnect(true, true);
        WiFi.mode(WIFI_OFF);
        btStop();
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
        WiFi.disconnect(true);
        WiFi.mode(WIFI_OFF);
        btStop();
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
            WiFi.disconnect(true);
            WiFi.mode(WIFI_OFF);
            btStop();
            enterOff_();
            s_idleOffDeadlineMs = 0;

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
        WiFi.disconnect(true);
        WiFi.mode(WIFI_OFF);
        btStop();
        enterIdle_();
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
    Serial.printf("\n[ADC] %s\n", tag);
    int pins[] = {15,17,18,10};
    for (int p : pins) {
      int v = analogRead(p);
      Serial.printf("  GPIO%02d = %d\n", p, v);
    }
  };
  dumpAdc("after WiFi on");
  s_enabled = true;
  if (s_state == WiFiMgrState::OFF) enterIdle_();
  notifyUi_();
}

void WiFiManager::disable() {
  s_enabled = false;

  // Tell app we're going offline (only if we were actually online)
  if (s_state == WiFiMgrState::ONLINE && s_onOffline) s_onOffline();

  // FAST OFF: do not wait for graceful disconnect; just kill the radio.
  // WiFi.disconnect(...) can block for seconds when connected / sockets active.
  WiFi.mode(WIFI_OFF);
  btStop();

  // Optional best-effort cleanup AFTER the radio is already off.
  // Keep it non-blocking-ish: no erase, no long waits.
  WiFi.disconnect(false);

  enterOff_();
  notifyUi_();
}


bool WiFiManager::isEnabled() { return s_enabled; }

void WiFiManager::connectNow() {
  if (!s_enabled || loggingGuard_()) return;

  s_haveIntentConnect = true;

  // Treat as user activity regardless of state
  s_idleOffDeadlineMs = millis() + IDLE_OFF_MS;

  // If we're not already trying, kick the state machine
  if (s_state == WiFiMgrState::OFF) {
    enterIdle_();
  }
  if (s_state == WiFiMgrState::IDLE) {
    // Start the actual connection attempt
    selectAndConnect_();          // or enterScanning_()/enterConnecting_()
  }
  notifyUi_();
}

void WiFiManager::disconnect() {
  if (s_state == WiFiMgrState::ONLINE && s_onOffline) s_onOffline();
  WiFi.disconnect(true, true);
  WiFi.mode(WIFI_OFF);
  btStop();
  enterIdle_();
  notifyUi_();
}

void WiFiManager::shutdownRadio_() {
  // FAST OFF: kill Wi-Fi + BT immediately.
  WiFi.mode(WIFI_OFF);
  btStop();

  // Best-effort cleanup after OFF (avoid erase=true / wifioff waits)
  WiFi.disconnect(false);
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
  // Configure radio for STA scans only; we’ll bring it up briefly
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(true);                  // allow modem-sleep while connected
  esp_wifi_set_ps(WIFI_PS_MIN_MODEM);   // IDF-level: modem sleep policy (optional but nice)
  // Reset any target decided earlier
  s_targetSsid = "";
  s_targetBssidSet = false;
  memset(s_targetBssid, 0, sizeof(s_targetBssid));

  // Kick scan in async mode; we’ll timebox with a deadline
  WiFi.scanDelete();
  WiFi.scanNetworks(true /* async */, true /* show hidden */);
  s_state = WiFiMgrState::SCANNING;
  s_stateDeadlineMs = millis() + SCAN_TIMEOUT_MS;
  notifyUi_();
}

static bool bssidEqual_(const uint8_t a[6], const uint8_t b[6]) {
  for (int i=0;i<6;++i) if (a[i] != b[i]) return false;
  return true;
}

void WiFiManager::selectAndConnect_() {
  int n = WiFi.scanComplete();
  if (n < 0) n = 0;  // treat as no results if scan not finished
  // Build a quick map of best RSSI per SSID (and remember BSSID/channel)
  struct Seen {
    int rssi = -127;
    uint8_t bssid[6] = {0};
    bool bssidSet = false;
  };
  // Since we only have up to 5 targets, we can choose directly without a full map.

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
        uint8_t b[6]; WiFi.BSSID(k, b);
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
          WiFi.BSSID(k, bestBssid);
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
    WiFi.scanDelete();
    enterIdle_();
    return;
  }

  // Attempt connect to the chosen network
  s_targetSsid = String(nets[chosenIndex].ssid);
  if (chosenBssidSet) { memcpy(s_targetBssid, chosenBssid, 6); s_targetBssidSet = true; }
  else { memset(s_targetBssid, 0, 6); s_targetBssidSet = false; }

  WiFi.scanDelete();
  WiFi.mode(WIFI_STA);
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