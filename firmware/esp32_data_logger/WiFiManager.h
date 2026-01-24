#ifndef WIFI_MANAGER_H
#define WIFI_MANAGER_H

#include <Arduino.h>
#include <WiFi.h>

// Forward-declared to avoid hard dependency. You’ll wire this from your .ino.
typedef bool (*IsLoggingActiveFn)();

enum class WiFiMgrState : uint8_t {
  OFF,
  IDLE,        // enabled, waiting for user action or RTC need
  SCANNING,
  CONNECTING,
  ONLINE
};

struct WiFiStatus {
  WiFiMgrState state;
  wl_status_t  wl;
  String       ssid;
  int          rssi;   // dBm (WL_CONNECTED only; otherwise 0)
  bool         enabled;
};

class WiFiManager {
public:
  // One-time init; does NOT turn Wi-Fi on.
  static void begin(IsLoggingActiveFn isLoggingFn = nullptr);

  // Call every loop() — non-blocking state machine.
  static void loop();

  // User API — explicit control
  static void enable();                 // allow Wi-Fi activity (does not force connect)
  static void disable();                // immediately tear down radio and stop attempts
  static bool isEnabled();

  // “Do a connect now” — triggers scan + selection + connect (once).
  // Ignored if logging is active or Wi-Fi is disabled.
  static void connectNow();

  // Disconnect but keep enabled; returns to IDLE.
  static void disconnect();

  // For RTC path: if RTC is invalid and auto-time is allowed, attempt one connect cycle.
  // (You can call this once at startup; it won’t churn.)
  static void maybeConnectForRTC();

  // Simple status snapshot for Display/Web.
  static WiFiStatus status();

  // Events (optional, set from .ino)
  typedef void (*OnOnlineFn)();         // called once when ONLINE (got IP)
  typedef void (*OnOfflineFn)();        // called when leaving ONLINE
  typedef void (*OnUiFn)();         // UI notifier (no args; call status() inside)

  static void setOnlineCallback(OnOnlineFn cb);
  static void setOfflineCallback(OnOfflineFn cb);
  static void setUiCallback(OnUiFn cb);
  static void noteUserActivity();   
  static void suspendForLogging();
  static void resumeAfterLogging();


private:
  // internals
  static void enterOff_();
  static void enterIdle_();
  static void startScan_();
  static void selectAndConnect_();  
  static bool loggingGuard_();      // true if logging is active
  static bool configuredNetworksExist_();
  static void clearIntent_();
  static void shutdownRadio_();     // 
  static bool s_loggingSuspended;
  static bool s_restoreEnabledAfterLogging; 


  static WiFiMgrState s_state;
  static bool         s_enabled;
  static bool         s_haveIntentConnect;   // user/RTC requested a connect pass
  static uint32_t     s_stateDeadlineMs;     // timeouts for scan/connect

  static String       s_targetSsid;
  static uint8_t      s_targetBssid[6];
  static bool         s_targetBssidSet;

  static IsLoggingActiveFn s_isLogging;
  static OnOnlineFn  s_onOnline;
  static OnOfflineFn s_onOffline;

  static OnUiFn    s_onUi;
  static void      notifyUi_();     // helper to invoke s_onUi with current status

  // cached ONLINE info
  static String s_currSsid;
  static int    s_currRssi;
};

#endif
