#pragma once

#include <WebServer.h>

// Registers GET handlers for /static/app.css and /static/htmx.min.js.
// Serves files from embedded flash assets (WebAssets.h) with 1-year cache headers.
// Cache-busting is via content hash in the ?v= query parameter (see WebAssets.h).
void registerStaticRoutes(WebServer& srv);
