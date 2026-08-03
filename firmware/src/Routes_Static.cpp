#include "Routes_Static.h"
#include "HttpFileSender.h"
#include "SD_MMC.h"

// ─────────────────────────────────────────────────────────────────
// Routes_Static.cpp — serves /static/* from SD card /www/ with caching
// ─────────────────────────────────────────────────────────────────

static String extractStaticFilename_(const String& uri) {
  // Strip "/static/" prefix (8 chars)
  String path = uri.substring(8);

  // Strip query string (everything after ?)
  int q = path.indexOf('?');
  if (q >= 0) {
    path = path.substring(0, q);
  }

  // Validate: reject empty, .., forward slash, backslash
  if (path.length() == 0) return String();
  if (path.indexOf("..") >= 0) return String();
  if (path.indexOf('/') >= 0) return String();
  if (path.indexOf('\\') >= 0) return String();

  return path;
}

static String contentTypeFor_(const String& filename) {
  String lower = filename;
  lower.toLowerCase();
  if (lower.endsWith(".js"))  return F("application/javascript");
  if (lower.endsWith(".css")) return F("text/css");
  return F("application/octet-stream");
}

static void handleStaticRequest_(WebServer& srv) {
  String filename = extractStaticFilename_(srv.uri());
  if (filename.length() == 0) {
    srv.send(404, F("text/plain"), F("Not found"));
    return;
  }

  // Check SD card is mounted
  if (SD_MMC.cardType() == CARD_NONE) {
    srv.send(404, F("text/plain"), F("Not found"));
    return;
  }

  String sdPath = String(F("/www/")) + filename;
  if (!SD_MMC.exists(sdPath)) {
    srv.send(404, F("text/plain"), F("Not found"));
    return;
  }

  String contentType = contentTypeFor_(filename);
  HttpFileSender::sendSdFile(srv, sdPath, contentType, F(""), F("max-age=31536000"));
}

void registerStaticRoutes(WebServer& srv) {
  srv.on("/static/*", HTTP_GET, [&srv]() {
    handleStaticRequest_(srv);
  });
}
