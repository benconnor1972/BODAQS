#pragma once

#include <WebServer.h>

// Registers GET handler for /static/* path prefix.
// Serves files from /www/ on the SD card with 1-year cache headers.
void registerStaticRoutes(WebServer& srv);
