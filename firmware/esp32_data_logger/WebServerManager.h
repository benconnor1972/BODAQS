#pragma once
#include <Arduino.h>
#include <SdFat.h>
#include "SensorRegistry.h"
#include "ConfigManager.h"
#include <WebServer.h>

// forward declaration so the header doesn't depend on ConfigManager
struct LoggerConfig; 
extern WebServer g_server;

class WebServerManager {
public:
  static void begin(SdFs* sdRef);
  static bool start();
  static void stop();
  static void loop();
  static bool isRunning();
  static bool canStart();

  static void attachConfig(LoggerConfig* cfg);
  static SdFs* sd();   // expose the shared SdFat* for route modules

private:
  static void setupRoutes();
  static void handleRoot();
  static void handleNotFound();

};
