#include "Routes_Static.h"
#include "WebAssets.h"
#include "HttpFileSender.h"

// ─────────────────────────────────────────────────────────────────
// Routes_Static.cpp — serves /static/* from embedded flash assets
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

  const char* data = nullptr;
  unsigned int len = 0;

  if (filename == "app.css") {
    data = (const char*)app_css_data;
    len = app_css_len;
  } else if (filename == "htmx.min.js") {
    data = (const char*)htmx_js_data;
    len = htmx_js_len;
  }

  if (!data) {
    srv.send(404, F("text/plain"), F("Not found"));
    return;
  }

  String contentType = contentTypeFor_(filename);
  srv.sendHeader(F("Cache-Control"), F("max-age=31536000"));
  srv.setContentLength(len);
  srv.send(200, contentType, "");
  HttpFileSender::writeResponseChunk(srv, data, len);
}

void registerStaticRoutes(WebServer& srv) {
  srv.on("/static/app.css", HTTP_GET, [&srv]() {
    handleStaticRequest_(srv);
  });
  srv.on("/static/htmx.min.js", HTTP_GET, [&srv]() {
    handleStaticRequest_(srv);
  });
}
