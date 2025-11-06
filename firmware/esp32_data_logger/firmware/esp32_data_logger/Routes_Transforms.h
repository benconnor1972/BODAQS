#pragma once
#include <WebServer.h>

// Registers /api/transforms/* endpoints
void registerTransformRoutes(WebServer& srv);
