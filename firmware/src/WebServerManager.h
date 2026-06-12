#pragma once
#include <Arduino.h>
#include "SensorRegistry.h"
#include "ConfigManager.h"

// forward declaration so the header doesn't depend on ConfigManager
struct LoggerConfig; 

class WebServerManager {
public:
  using IsLoggingFn = bool (*)();

  static void begin(IsLoggingFn isLogging = nullptr);
  static void setStaConfig(const String& ssid, const String& password); //legacy
  static bool start();
  static void stop();
  static void loop();
  static bool isRunning();
  static bool canStart();

  // NEW: give the web server access to the live config struct
  static void attachConfig(LoggerConfig* cfg);
private:
  static bool prepareServer_();
  static void setupRoutes();
  static void handleRoot();
  static void handleNotFound();

};
