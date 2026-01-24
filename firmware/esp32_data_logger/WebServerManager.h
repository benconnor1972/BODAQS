#pragma once
#include <Arduino.h>
#include <SdFat.h>
#include "SensorRegistry.h"
#include "ConfigManager.h"

// forward declaration so the header doesn't depend on ConfigManager
struct LoggerConfig; 

class WebServerManager {
public:
  using IsLoggingFn = bool (*)();

  static void begin(SdFs* sdRef, IsLoggingFn isLogging = nullptr);
  static void setStaConfig(const String& ssid, const String& password); //legacy
  static bool start();
  static void stop();
  static void loop();
  static bool isRunning();
  static bool canStart();

  // NEW: give the web server access to the live config struct
  static void attachConfig(LoggerConfig* cfg);
  static SdFs* sd();   // expose the shared SdFat* for route modules


private:
  static void setupRoutes();
  static void handleRoot();
  static void handleNotFound();

};
