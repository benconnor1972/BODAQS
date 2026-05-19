#include "WiFiManager.h"
#include "ConfigManager.h"
#include "UploadModeManager.h"
#include <esp_wifi.h>
#include <esp_bt.h>
#include <esp_coexist.h>
#include <esp_heap_caps.h>
#include <esp_sleep.h>
#include <esp_system.h>
#include <ESPmDNS.h>
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
static const uint32_t RTC_SYNC_RETRY_DELAY_MS = 5000;
static const uint8_t  RTC_SYNC_MAX_ATTEMPTS   = 3;
static uint32_t s_linkDropDeadlineMs = 0;
static uint32_t s_idleOffLastActivityMs = 0;
static bool s_rtcSyncPending = false;   // we connected solely to set time
static uint32_t s_rtcSyncRetryAtMs = 0;
static uint8_t s_rtcSyncAttempts = 0;
static int s_targetConfigIndex = -1;
static int s_lastConnectedIndex = -1;
static bool s_forceRtcSyncOnBoot = false;
static bool s_invalidateRtcOnBoot = false;
static esp_reset_reason_t s_bootResetReason = ESP_RST_UNKNOWN;
static esp_sleep_wakeup_cause_t s_bootWakeCause = ESP_SLEEP_WAKEUP_UNDEFINED;
static bool s_prevEnabledBeforeLogging = false;
static bool s_suspendedForLogging = false;
static bool s_restoreWifiAfterRtcSync = false;
static bool s_prevEnabledBeforeRtcSync = false;
static bool s_forceNetworkRtcSync = false;
static bool s_mdnsActive = false;

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

static bool wifiRadioIsAp_() {
  const wifi_mode_t mode = WiFi.getMode();
  return mode == WIFI_MODE_AP || mode == WIFI_MODE_APSTA;
}

static bool configuredWifiModeIsStation_() {
  return ConfigManager::get().wifiMode == WiFiMode::Station;
}

static String discoveryHostname_() {
  String id = ConfigManager::loggerId();
  id.toLowerCase();

  String suffix;
  suffix.reserve(id.length());
  bool lastDash = false;
  for (uint16_t i = 0; i < id.length(); ++i) {
    const char c = id[i];
    const bool ok = (c >= 'a' && c <= 'z') ||
                    (c >= '0' && c <= '9') ||
                    c == '-';
    if (ok) {
      suffix += c;
      lastDash = (c == '-');
    } else if (!lastDash) {
      suffix += '-';
      lastDash = true;
    }
  }

  while (suffix.startsWith("-")) suffix.remove(0, 1);
  while (suffix.endsWith("-")) suffix.remove(suffix.length() - 1);

  String host = F("bodaqs");
  if (suffix.length()) {
    host += '-';
    host += suffix;
  }
  if (host.length() > 63) {
    host = host.substring(0, 63);
    while (host.endsWith("-")) host.remove(host.length() - 1);
  }
  return host.length() ? host : String(F("bodaqs-logger"));
}

static void stopMdns_(const char* reason) {
  if (!s_mdnsActive) return;
  MDNS.end();
  s_mdnsActive = false;
  WIFI_LOGI("mDNS stopped%s%s\n", reason ? ": " : "", reason ? reason : "");
}

static void startMdns_() {
  if (!WiFiManager::isNetworkUp() || ConfigManager::get().wifiMode != WiFiMode::Station) {
    stopMdns_("not station online");
    return;
  }

  const String host = discoveryHostname_();
  stopMdns_("refresh");

  if (!MDNS.begin(host.c_str())) {
    WIFI_LOGW("mDNS begin failed host='%s'\n", host.c_str());
    return;
  }

  MDNS.addService("bodaqs-logger", "tcp", 80);
  MDNS.addServiceTxt("bodaqs-logger", "tcp", "api", "1");
  const String loggerId = ConfigManager::loggerId();
  MDNS.addServiceTxt("bodaqs-logger", "tcp", "logger_id", loggerId.c_str());
  MDNS.addServiceTxt("bodaqs-logger", "tcp", "upload_mode", UploadModeManager::isActive() ? "true" : "false");
  MDNS.addServiceTxt("bodaqs-logger", "tcp", "hostname", host.c_str());
  s_mdnsActive = true;
  WIFI_LOGI("mDNS started host='%s.local' service='_bodaqs-logger._tcp'\n", host.c_str());
}

static const char* resetReasonName_(esp_reset_reason_t reason) {
  switch (reason) {
    case ESP_RST_UNKNOWN:   return "UNKNOWN";
    case ESP_RST_POWERON:   return "POWERON";
    case ESP_RST_EXT:       return "EXT";
    case ESP_RST_SW:        return "SW";
    case ESP_RST_PANIC:     return "PANIC";
    case ESP_RST_INT_WDT:   return "INT_WDT";
    case ESP_RST_TASK_WDT:  return "TASK_WDT";
    case ESP_RST_WDT:       return "WDT";
    case ESP_RST_DEEPSLEEP: return "DEEPSLEEP";
    case ESP_RST_BROWNOUT:  return "BROWNOUT";
    case ESP_RST_SDIO:      return "SDIO";
    default:                return "?";
  }
}

static const char* wakeCauseName_(esp_sleep_wakeup_cause_t cause) {
  switch (cause) {
    case ESP_SLEEP_WAKEUP_UNDEFINED:       return "UNDEFINED";
    case ESP_SLEEP_WAKEUP_ALL:             return "ALL";
    case ESP_SLEEP_WAKEUP_EXT0:            return "EXT0";
    case ESP_SLEEP_WAKEUP_EXT1:            return "EXT1";
    case ESP_SLEEP_WAKEUP_TIMER:           return "TIMER";
    case ESP_SLEEP_WAKEUP_TOUCHPAD:        return "TOUCHPAD";
    case ESP_SLEEP_WAKEUP_ULP:             return "ULP";
    case ESP_SLEEP_WAKEUP_GPIO:            return "GPIO";
    case ESP_SLEEP_WAKEUP_UART:            return "UART";
    case ESP_SLEEP_WAKEUP_WIFI:            return "WIFI";
    case ESP_SLEEP_WAKEUP_COCPU:           return "COCPU";
    case ESP_SLEEP_WAKEUP_COCPU_TRAP_TRIG: return "COCPU_TRAP";
    case ESP_SLEEP_WAKEUP_BT:              return "BT";
    default:                               return "?";
  }
}

static bool shouldForceRtcSyncOnBoot_(esp_reset_reason_t resetReason,
                                      esp_sleep_wakeup_cause_t wakeCause) {
  if (wakeCause != ESP_SLEEP_WAKEUP_UNDEFINED) return true;

  switch (resetReason) {
    case ESP_RST_POWERON:
    case ESP_RST_UNKNOWN:
      return false;
    default:
      return true;
  }
}

static bool shouldInvalidateRtcOnBoot_(esp_reset_reason_t resetReason,
                                       esp_sleep_wakeup_cause_t wakeCause) {
  // Keep retained RTC time across deep-sleep wakes so the logger can continue
  // to use the carried clock immediately, then force a background resync to
  // correct any drift once Wi-Fi is available.
  if (wakeCause != ESP_SLEEP_WAKEUP_UNDEFINED || resetReason == ESP_RST_DEEPSLEEP) {
    return false;
  }

  // Invalidate on suspicious warm-reset paths where retained system time is
  // more likely to be stale or corrupted and there is no "sleep duration"
  // context to bound the error.
  switch (resetReason) {
    case ESP_RST_SW:
    case ESP_RST_PANIC:
    case ESP_RST_INT_WDT:
    case ESP_RST_TASK_WDT:
    case ESP_RST_WDT:
    case ESP_RST_BROWNOUT:
      return true;
    default:
      return false;
  }
}

static void rememberConnectedNetwork_() {
  if (s_targetConfigIndex >= 0) {
    s_lastConnectedIndex = s_targetConfigIndex;
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
  stopMdns_(reason);
  wifiDiag_(reason);
  WiFi.scanDelete();
  WiFi.softAPdisconnect(true);
  WiFi.disconnect(false, false);
  if (WiFi.getMode() != WIFI_STA && !WiFi.mode(WIFI_STA)) {
    WIFI_LOGW("keepStaIdle_: failed to enter WIFI_STA\n");
  }
  btStop();
  wifiDiag_("keepStaIdle done");
}

static void hardOff_(const char* reason) {
  stopMdns_(reason);
  wifiDiag_(reason);
  WiFi.scanDelete();
  WiFi.softAPdisconnect(true);
  if (!WiFi.mode(WIFI_OFF)) {
    WIFI_LOGW("hardOff_: WiFi.mode(WIFI_OFF) failed\n");
  }
  btStop();
  wifiDiag_("hardOff done");
}

static uint32_t wifiIdleTimeoutMs_() {
  return ConfigManager::get().wifiIdleTimeoutMs;
}

static void noteIdleOffActivity_() {
  s_idleOffLastActivityMs = millis();
}

static void splitCsv3_(const char* csv, String& s1, String& s2, String& s3) {
  s1 = "";
  s2 = "";
  s3 = "";
  if (!csv) return;

  String src(csv);
  src.trim();
  if (!src.length()) return;

  int p1 = src.indexOf(',');
  if (p1 < 0) {
    s1 = src;
    s1.trim();
    return;
  }

  s1 = src.substring(0, p1);
  s1.trim();

  int p2 = src.indexOf(',', p1 + 1);
  if (p2 < 0) {
    s2 = src.substring(p1 + 1);
    s2.trim();
    return;
  }

  s2 = src.substring(p1 + 1, p2);
  s2.trim();
  s3 = src.substring(p2 + 1);
  s3.trim();
}

static const char* firstNonEmptyHost_(const String& s1, const String& s2, const String& s3) {
  if (s1.length()) return s1.c_str();
  if (s2.length()) return s2.c_str();
  if (s3.length()) return s3.c_str();
  return nullptr;
}

static void logRtcSyncNetworkDiag_(const char* ntpHost) {
  LOGD_TAG("RTC", "RTC sync net: local=%s gateway=%s subnet=%s dns1=%s\n",
           WiFi.localIP().toString().c_str(),
           WiFi.gatewayIP().toString().c_str(),
           WiFi.subnetMask().toString().c_str(),
           WiFi.dnsIP(0).toString().c_str());

  if (!ntpHost || !*ntpHost) {
    LOGD_TAG("RTC", "RTC sync DNS: no NTP hostname configured\n");
    return;
  }

  IPAddress resolved;
  const int rc = WiFi.hostByName(ntpHost, resolved);
  if (rc == 1) {
    LOGD_TAG("RTC", "RTC sync DNS: hostByName('%s') -> %s\n",
             ntpHost,
             resolved.toString().c_str());
  } else {
    LOGW_TAG("RTC", "RTC sync DNS: hostByName('%s') failed rc=%d\n", ntpHost, rc);
  }
}

static void setRtcSyncPowerSave_(bool enabled) {
  if (enabled) {
    LOGD_TAG("RTC", "RTC sync: restoring WiFi modem sleep\n");
    WiFi.setSleep(true);
    esp_wifi_set_ps(WIFI_PS_MIN_MODEM);
  } else {
    LOGD_TAG("RTC", "RTC sync: forcing WiFi power save off\n");
    WiFi.setSleep(false);
    esp_wifi_set_ps(WIFI_PS_NONE);
  }
}

// Free helper, no access to WiFiManager privates needed
static void tryRtcSyncIfPending_() {
  if (!s_rtcSyncPending) return;
  if (WiFi.status() != WL_CONNECTED) return;
  if (!s_forceNetworkRtcSync && RTCManager_hasValidTime()) {
    RTC_LOGI("RTC sync completed after delayed SNTP update\n");
    RTCManager_sync();
    s_rtcSyncPending = false;
    s_rtcSyncRetryAtMs = 0;
    s_rtcSyncAttempts = 0;
    s_forceNetworkRtcSync = false;

    const auto& cfg = ConfigManager::get();
    if (s_restoreWifiAfterRtcSync) {
      const bool keepEnabled = s_prevEnabledBeforeRtcSync;
      s_restoreWifiAfterRtcSync = false;
      s_prevEnabledBeforeRtcSync = false;
      if (!keepEnabled) {
        WiFiManager::disable();
      } else {
        WiFiManager::noteUserActivity();
      }
    } else if (!cfg.wifiEnabledDefault) {
      WiFiManager::disable();
    } else {
      WiFiManager::noteUserActivity();
    }
    return;
  }
  if (s_rtcSyncRetryAtMs != 0 && (int32_t)(millis() - s_rtcSyncRetryAtMs) < 0) return;

  bool synced = false;
  bool finalAttempt = false;
  {
    const auto& cfg = ConfigManager::get();
    String n1, n2, n3;
    splitCsv3_(cfg.ntpServers, n1, n2, n3);

    setRtcSyncPowerSave_(false);
    const uint8_t attempt = (uint8_t)(s_rtcSyncAttempts + 1);
    RTC_LOGI("Starting RTC network sync attempt %u/%u with TZ='%s' servers='%s'\n",
             (unsigned)attempt,
             (unsigned)RTC_SYNC_MAX_ATTEMPTS,
             cfg.tz[0] ? cfg.tz : "UTC",
             cfg.ntpServers);
    logRtcSyncNetworkDiag_(firstNonEmptyHost_(n1, n2, n3));
    synced = RTCManager_syncNetworkTime(cfg.tz, cfg.ntpServers, cfg.timeCheckUrl, 15000, 5000);
    s_rtcSyncAttempts = attempt;
    finalAttempt = (s_rtcSyncAttempts >= RTC_SYNC_MAX_ATTEMPTS);
    if (!synced) {
      LOGW_TAG("RTC", "RTC sync failed after SNTP and HTTP fallback\n");
      if (!finalAttempt) {
        s_rtcSyncRetryAtMs = millis() + RTC_SYNC_RETRY_DELAY_MS;
        RTC_LOGI("RTC sync retry scheduled in %lu ms\n",
                 (unsigned long)RTC_SYNC_RETRY_DELAY_MS);
      }
    }
  }
  setRtcSyncPowerSave_(true);
  if (!synced && !finalAttempt) return;

  if (synced) {
    RTCManager_sync();                          // capture baseEpoch from system
  }
  s_rtcSyncPending = false;
  s_rtcSyncRetryAtMs = 0;
  s_rtcSyncAttempts = 0;
  s_forceNetworkRtcSync = false;

  const auto& cfg = ConfigManager::get();
  if (s_restoreWifiAfterRtcSync) {
    const bool keepEnabled = s_prevEnabledBeforeRtcSync;
    s_restoreWifiAfterRtcSync = false;
    s_prevEnabledBeforeRtcSync = false;
    if (!keepEnabled) {
      WiFiManager::disable();
    } else {
      WiFiManager::noteUserActivity();
    }
  } else if (!cfg.wifiEnabledDefault) {
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
  s_targetConfigIndex = -1;
  s_lastConnectedIndex = -1;
  s_currSsid = "";
  s_currRssi = 0;
  s_idleOffLastActivityMs = 0;
  s_rtcSyncPending = false;
  s_rtcSyncRetryAtMs = 0;
  s_rtcSyncAttempts = 0;
  s_bootResetReason = esp_reset_reason();
  s_bootWakeCause = esp_sleep_get_wakeup_cause();
  s_forceRtcSyncOnBoot = shouldForceRtcSyncOnBoot_(s_bootResetReason, s_bootWakeCause);
  s_invalidateRtcOnBoot = shouldInvalidateRtcOnBoot_(s_bootResetReason, s_bootWakeCause);
  s_restoreWifiAfterRtcSync = false;
  s_prevEnabledBeforeRtcSync = false;
  s_forceNetworkRtcSync = false;

  WiFi.persistent(false);       // don’t touch NVS
  hardOff_("begin");

  if (s_forceRtcSyncOnBoot || s_invalidateRtcOnBoot) {
    RTC_LOGI("RTC boot state: reset=%s wake=%s forceResync=%d invalidate=%d\n",
             resetReasonName_(s_bootResetReason),
             wakeCauseName_(s_bootWakeCause),
             s_forceRtcSyncOnBoot ? 1 : 0,
             s_invalidateRtcOnBoot ? 1 : 0);
  } else {
    LOGD_TAG("RTC", "RTC boot state: reset=%s wake=%s forceResync=%d invalidate=%d\n",
             resetReasonName_(s_bootResetReason),
             wakeCauseName_(s_bootWakeCause),
             s_forceRtcSyncOnBoot ? 1 : 0,
             s_invalidateRtcOnBoot ? 1 : 0);
  }

}

void WiFiManager::loop() {
  // Hard guard: never do Wi-Fi work while logging
  if (loggingGuard_()) {
    // Only do the teardown once, when we transition into "logging"
    if (s_state != WiFiMgrState::OFF) {
      if ((s_state == WiFiMgrState::ONLINE || s_state == WiFiMgrState::AP_ONLINE) && s_onOffline) {
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
  if (s_enabled && s_state != WiFiMgrState::AP_ONLINE && WiFi.status() == WL_CONNECTED) {
    if (s_state != WiFiMgrState::ONLINE) {
      s_currSsid = WiFi.SSID();
      s_currRssi = WiFi.RSSI();
      s_state    = WiFiMgrState::ONLINE;
      noteIdleOffActivity_();
      rememberConnectedNetwork_();
      clearIntent_();
      if (s_onOnline) s_onOnline();
      startMdns_();
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
        noteIdleOffActivity_();
        rememberConnectedNetwork_();

        if (s_onOnline) s_onOnline();
        startMdns_();
        clearIntent_();
        notifyUi_();
        tryRtcSyncIfPending_();     // <-- add this

      } else if (millis() >= s_stateDeadlineMs) {
        // connection attempt ended — return to IDLE (single pass only)
        s_targetConfigIndex = -1;
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
        const uint32_t idleTimeoutMs = wifiIdleTimeoutMs_();
        s_currRssi = WiFi.RSSI();
        tryRtcSyncIfPending_();
        s_linkDropDeadlineMs = 0;      // cancel any pending drop
        if (idleTimeoutMs == 0) {
          noteIdleOffActivity_();
          break;
        }
        // ---- Auto-off check (idle timeout) ----
        if (s_idleOffLastActivityMs != 0 &&
            (uint32_t)(millis() - s_idleOffLastActivityMs) >= idleTimeoutMs) {
          // Timeout: fully turn Wi-Fi off until the user explicitly enables it again.
          if (s_onOffline) s_onOffline();
          s_enabled = false;
          hardOff_("idle timeout");
          enterOff_();
          s_idleOffLastActivityMs = 0;
          s_linkDropDeadlineMs = 0;
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
        s_targetConfigIndex = -1;
        keepStaIdle_("link drop");
        enterIdle_();
        clearIntent_();
        s_linkDropDeadlineMs = 0;
        notifyUi_();
      }
      break;
    }

    case WiFiMgrState::AP_ONLINE: {
      if (!s_enabled) {
        if (s_onOffline) s_onOffline();
        hardOff_("disabled while ap online");
        enterOff_();
        s_linkDropDeadlineMs = 0;
        notifyUi_();
        break;
      }

      if (!wifiRadioIsAp_()) {
        if (s_onOffline) s_onOffline();
        enterIdle_();
        s_linkDropDeadlineMs = 0;
        notifyUi_();
        break;
      }

      const uint32_t idleTimeoutMs = wifiIdleTimeoutMs_();
      if (idleTimeoutMs == 0) {
        noteIdleOffActivity_();
        break;
      }

      if (s_idleOffLastActivityMs != 0 &&
          (uint32_t)(millis() - s_idleOffLastActivityMs) >= idleTimeoutMs) {
        if (s_onOffline) s_onOffline();
        s_enabled = false;
        hardOff_("ap idle timeout");
        enterOff_();
        s_idleOffLastActivityMs = 0;
        s_linkDropDeadlineMs = 0;
        clearIntent_();
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
  if ((s_state == WiFiMgrState::ONLINE || s_state == WiFiMgrState::AP_ONLINE) && s_onOffline) s_onOffline();

  s_targetConfigIndex = -1;
  clearIntent_();
  s_idleOffLastActivityMs = 0;
  s_linkDropDeadlineMs = 0;
  s_rtcSyncPending = false;
  s_rtcSyncRetryAtMs = 0;
  s_rtcSyncAttempts = 0;
  s_restoreWifiAfterRtcSync = false;
  s_prevEnabledBeforeRtcSync = false;
  s_forceNetworkRtcSync = false;
  hardOff_("disable");

  enterOff_();
  notifyUi_();
}


bool WiFiManager::isEnabled() { return s_enabled; }

void WiFiManager::connectNow() {
  if (ConfigManager::get().wifiMode == WiFiMode::AccessPoint) {
    startAccessPoint_();
    return;
  }
  connectStationNow_();
}

void WiFiManager::startConfiguredMode() {
  connectNow();
}

void WiFiManager::connectStationNow_() {
  if (!s_enabled || loggingGuard_()) return;
  if (!configuredNetworksExist_()) {
    clearIntent_();
    wifiDiag_("connectNow ignored: no configured station networks");
    return;
  }
  if (s_state == WiFiMgrState::SCANNING || s_state == WiFiMgrState::CONNECTING) {
    wifiDiag_("connectNow ignored: already busy");
    return;
  }
  if (s_state == WiFiMgrState::ONLINE) {
    noteUserActivity();
    wifiDiag_("connectNow ignored: already online");
    return;
  }
  if (s_state == WiFiMgrState::AP_ONLINE) {
    if (s_onOffline) s_onOffline();
    keepStaIdle_("station connect from ap");
    enterIdle_();
  }

  s_haveIntentConnect = true;

  // Treat as user activity regardless of state
  noteIdleOffActivity_();

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
  if ((s_state == WiFiMgrState::ONLINE || s_state == WiFiMgrState::AP_ONLINE) && s_onOffline) s_onOffline();
  s_targetConfigIndex = -1;
  clearIntent_();
  s_idleOffLastActivityMs = 0;
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
  if (!configuredWifiModeIsStation_()) return;      // AP-only mode has no upstream NTP path
  if (!configuredNetworksExist_()) return;          // nowhere to connect

  bool haveValidTime = RTCManager_hasValidTime();
  if (s_invalidateRtcOnBoot && haveValidTime) {
    RTC_LOGI("RTC auto-sync: invalidating retained time after reset=%s wake=%s\n",
             resetReasonName_(s_bootResetReason),
             wakeCauseName_(s_bootWakeCause));
    RTCManager_invalidateInternalTime();
    haveValidTime = false;
  }

  if (!s_forceRtcSyncOnBoot && haveValidTime) return;  // already valid and not a retained-clock boot

  if (s_forceRtcSyncOnBoot) {
    RTC_LOGI("RTC auto-sync: forcing resync after reset=%s wake=%s validBefore=%d\n",
             resetReasonName_(s_bootResetReason),
             wakeCauseName_(s_bootWakeCause),
             haveValidTime ? 1 : 0);
  }

  enable();                         // radios on
  connectStationNow_();
  s_rtcSyncPending = true;          // remember why we’re doing this
  s_rtcSyncRetryAtMs = 0;
  s_rtcSyncAttempts = 0;
  s_forceNetworkRtcSync = s_forceRtcSyncOnBoot;
  s_forceRtcSyncOnBoot = false;
  s_invalidateRtcOnBoot = false;
}

bool WiFiManager::forceRtcSync() {
  if (loggingGuard_()) return false;
  if (!configuredWifiModeIsStation_()) return false;
  if (!configuredNetworksExist_()) return false;
  if (s_rtcSyncPending) {
    if (s_enabled) {
      noteUserActivity();
    }
    return true;
  }

  RTC_LOGI("RTC manual sync requested\n");
  s_prevEnabledBeforeRtcSync = s_enabled;
  s_restoreWifiAfterRtcSync = true;
  s_rtcSyncPending = true;
  s_rtcSyncRetryAtMs = 0;
  s_rtcSyncAttempts = 0;
  s_forceNetworkRtcSync = true;
  s_forceRtcSyncOnBoot = false;
  s_invalidateRtcOnBoot = false;

  enable();
  connectStationNow_();
  if (s_enabled) {
    noteUserActivity();
  }
  return true;
}

bool WiFiManager::isRtcSyncPending() {
  return s_rtcSyncPending;
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
  st.mode    = (s_state == WiFiMgrState::AP_ONLINE) ? WiFiMode::AccessPoint : ConfigManager::get().wifiMode;
  st.wl      = WiFi.status();
  st.enabled = s_enabled;
  st.networkUp = isNetworkUp();
  st.ssid    = st.networkUp ? networkName() : "";
  st.ip      = st.networkUp ? localAddress().toString() : "";
  st.hostname = hostname();
  st.rssi    = (s_state == WiFiMgrState::ONLINE) ? s_currRssi : 0;
  st.apClients = (s_state == WiFiMgrState::AP_ONLINE && wifiRadioIsAp_())
                 ? (uint8_t)WiFi.softAPgetStationNum()
                 : 0;
  return st;
}

bool WiFiManager::isNetworkUp() {
  if (!s_enabled) return false;
  if (s_state == WiFiMgrState::ONLINE) {
    return WiFi.status() == WL_CONNECTED;
  }
  if (s_state == WiFiMgrState::AP_ONLINE) {
    return wifiRadioIsAp_();
  }
  return false;
}

IPAddress WiFiManager::localAddress() {
  if (s_state == WiFiMgrState::AP_ONLINE && wifiRadioIsAp_()) {
    return WiFi.softAPIP();
  }
  return WiFi.localIP();
}

String WiFiManager::networkName() {
  if (s_state == WiFiMgrState::AP_ONLINE && s_currSsid.length()) {
    return s_currSsid;
  }
  if (s_state == WiFiMgrState::ONLINE && s_currSsid.length()) {
    return s_currSsid;
  }
  return WiFi.SSID();
}

String WiFiManager::hostname() {
  return discoveryHostname_();
}

void WiFiManager::refreshDiscovery() {
  if (s_state == WiFiMgrState::ONLINE && isNetworkUp()) {
    startMdns_();
  } else {
    stopMdns_("refresh while offline");
  }
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

void WiFiManager::startAccessPoint_() {
  if (!s_enabled || loggingGuard_()) return;

  if (s_state == WiFiMgrState::AP_ONLINE && wifiRadioIsAp_()) {
    noteUserActivity();
    wifiDiag_("startAccessPoint ignored: already online");
    return;
  }

  if (s_state == WiFiMgrState::ONLINE && s_onOffline) {
    s_onOffline();
  }
  stopMdns_("access point mode");

  clearIntent_();
  s_targetConfigIndex = -1;
  s_targetSsid = "";
  s_targetBssidSet = false;
  memset(s_targetBssid, 0, sizeof(s_targetBssid));
  WiFi.scanDelete();
  WiFi.disconnect(false, false);
  WiFi.softAPdisconnect(true);

  const auto& cfg = ConfigManager::get();
  String ssid(cfg.wifiApSsid);
  ssid.trim();
  if (!ssid.length()) ssid = F("BODAQS");
  if (ssid.length() > 31) ssid = ssid.substring(0, 31);

  String password(cfg.wifiApPassword);
  password.trim();
  if (password.length() < 8 || password.length() > 63) {
    WIFI_LOGW("AP password length invalid; using default\n");
    password = F("bodaqslogger");
  }

  wifiDiag_("startAccessPoint");
  if (!WiFi.mode(WIFI_AP)) {
    WIFI_LOGE("startAccessPoint_: WiFi.mode(WIFI_AP) failed\n");
    enterIdle_();
    notifyUi_();
    return;
  }
  WiFi.setSleep(false);
  esp_wifi_set_ps(WIFI_PS_NONE);
  btStop();

  const bool ok = WiFi.softAP(ssid.c_str(), password.c_str());
  if (!ok) {
    WIFI_LOGE("startAccessPoint_: WiFi.softAP failed\n");
    hardOff_("softAP failed");
    enterIdle_();
    notifyUi_();
    return;
  }

  s_currSsid = ssid;
  s_currRssi = 0;
  s_state = WiFiMgrState::AP_ONLINE;
  noteIdleOffActivity_();
  s_linkDropDeadlineMs = 0;

  WIFI_LOGI("AP started ssid='%s' ip=%s\n",
            s_currSsid.c_str(),
            WiFi.softAPIP().toString().c_str());
  if (s_onOnline) s_onOnline();
  notifyUi_();
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
  s_targetConfigIndex = -1;
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
    s_targetConfigIndex = -1;
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
  int preferredIndex = -1;
  int preferredRssi = -127;
  uint8_t preferredBssid[6] = {0};
  bool preferredBssidSet = false;
  int preferredChannel = 0;

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

    if ((int)i == s_lastConnectedIndex) {
      preferredIndex = (int)i;
      preferredRssi = bestRssi;
      memcpy(preferredBssid, bestBssid, 6);
      preferredBssidSet = bestSet;
      preferredChannel = bestChannel;
    }

    // Keep the strongest overall; if tied, prefer earlier priority (smaller i)
    if (bestRssi > chosenRssi || (bestRssi == chosenRssi && chosenIndex == -1)) {
      chosenIndex   = (int)i;
      chosenRssi    = bestRssi;
      memcpy(chosenBssid, bestBssid, 6);
      chosenBssidSet = bestSet;
      chosenChannel  = bestChannel;
    }
  }

  if (preferredIndex >= 0) {
    WIFI_LOGI("selectAndConnect_: preferring last successful network[%d] ssid='%s' rssi=%d\n",
              preferredIndex,
              nets[preferredIndex].ssid,
              preferredRssi);
    chosenIndex = preferredIndex;
    chosenRssi = preferredRssi;
    memcpy(chosenBssid, preferredBssid, 6);
    chosenBssidSet = preferredBssidSet;
    chosenChannel = preferredChannel;
  }

  // No candidate — back to IDLE
  if (chosenIndex < 0) {
    WIFI_LOGW("selectAndConnect_: no eligible AP found\n");
    s_targetConfigIndex = -1;
    WiFi.scanDelete();
    enterIdle_();
    clearIntent_();
    return;
  }

  // Attempt connect to the chosen network
  s_targetConfigIndex = chosenIndex;
  s_targetSsid = String(nets[chosenIndex].ssid);
  if (chosenBssidSet) { memcpy(s_targetBssid, chosenBssid, 6); s_targetBssidSet = true; }
  else { memset(s_targetBssid, 0, 6); s_targetBssidSet = false; }

  WiFi.scanDelete();
  wifiDiag_("selectAndConnect");
  if (!WiFi.mode(WIFI_STA)) {
    WIFI_LOGE("selectAndConnect_: WiFi.mode(WIFI_STA) failed\n");
    s_targetConfigIndex = -1;
    enterIdle_();
    clearIntent_();
    return;
  }
  WiFi.setSleep(true);
  const String host = hostname();
  WiFi.setHostname(host.c_str());
  esp_wifi_set_ps(WIFI_PS_MIN_MODEM);
  noteIdleOffActivity_();

  auto ipFrom = [](const uint8_t a[4]) -> IPAddress {
    return IPAddress(a[0], a[1], a[2], a[3]);
  };

  if (nets[chosenIndex].staticIp) {
    IPAddress ip = ipFrom(nets[chosenIndex].ip);
    IPAddress gw = ipFrom(nets[chosenIndex].gateway);
    IPAddress sn = ipFrom(nets[chosenIndex].subnet);
    IPAddress d1 = ipFrom(nets[chosenIndex].dns1);

    // Sensible fallback: if DNS1 unset, use gateway
    if (d1 == IPAddress(0, 0, 0, 0)) d1 = gw;

    WiFi.config(ip, gw, sn, d1);
  } else {
    // IMPORTANT: revert to DHCP when switching away from a static network
    WiFi.config(INADDR_NONE, INADDR_NONE, INADDR_NONE);
  }


  // Comparison patch: avoid pinning channel/BSSID during association.
  // We still use the scan results for network selection, but let the core choose the BSSID/channel.
  const char* pwd = nets[chosenIndex].password;
  WIFI_LOGI("selected[%d]: ssid='%s' rssi=%d channel=%d staticIp=%d\n",
            chosenIndex,
            s_targetSsid.c_str(),
            chosenRssi,
            chosenChannel,
            (int)nets[chosenIndex].staticIp);
  wifiDiag_("before WiFi.begin");
  WiFi.begin(s_targetSsid.c_str(), (pwd ? pwd : ""));
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
  if (s_enabled && (s_state == WiFiMgrState::ONLINE || s_state == WiFiMgrState::AP_ONLINE)) {
    noteIdleOffActivity_();
  }
}
