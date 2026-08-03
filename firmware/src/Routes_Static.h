#pragma once

#include <WebServer.h>

// Registers GET handler for /static/* path prefix.
// Serves files from embedded flash assets (WebAssets.h) with 1-year cache headers.
void registerStaticRoutes(WebServer& srv);
