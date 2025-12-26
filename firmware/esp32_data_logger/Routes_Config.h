#pragma once
#include <WebServer.h>

// Registers /config (GET + POST)
void registerConfigRoutes();

// optional (only if you like splitting later)
// void registerConfigGeneral(WebServer& srv);
// void registerConfigSensors(WebServer& srv);
// void registerConfigButtons(WebServer& srv);