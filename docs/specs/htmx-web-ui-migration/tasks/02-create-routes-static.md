STEP 02: Create Routes_Static.cpp/.h
=====================================

STATUS
------

Status: COMPLETE
Completed: 2025-07-16
Verified by: implement (independent re-run)

DEPENDS ON: step 01

SPEC
----

Create the static asset server that serves `/static/<filename>` from `/www/<filename>` on the SD card with 1-year cache headers and path traversal protection.

The route handler:
1. Extracts the filename from the URI by stripping the `/static/` prefix
2. Strips any query string (everything after `?`) — `?v=0.4.1` is ignored for file lookup
3. Validates the filename: rejects `..`, `/`, `\`, and empty strings (returns 404)
4. Checks SD card is mounted (`SD_MMC.cardType() != CARD_NONE`)
5. Maps content type by extension: `.js` → `application/javascript`, `.css` → `text/css`
6. Delegates to `HttpFileSender::sendSdFile()` with `Cache-Control: max-age=31536000`

The `HttpFileSender::sendSdFile` already supports Range requests and chunked streaming, so we reuse it directly.

```cpp
// Routes_Static.h
#pragma once
#include <WebServer.h>
void registerStaticRoutes(WebServer& srv);
```

```cpp
// Routes_Static.cpp — key logic
static String extractStaticFilename_(const String& uri) {
  // Strip "/static/" prefix
  String path = uri.substring(8);  // after "/static/"
  // Strip query string
  int q = path.indexOf('?');
  if (q >= 0) path = path.substring(0, q);
  // Validate: reject empty, .., /, \
  if (path.length() == 0) return "";
  if (path.indexOf("..") >= 0) return "";
  if (path.indexOf('/') >= 0) return "";
  if (path.indexOf('\\') >= 0) return "";
  return path;
}

static String contentTypeFor_(const String& filename) {
  String lower = filename;
  lower.toLowerCase();
  if (lower.endsWith(".js"))  return F("application/javascript");
  if (lower.endsWith(".css")) return F("text/css");
  return F("application/octet-stream");
}
```

FILES TO CREATE
---------------

- `firmware/src/Routes_Static.h`: `void registerStaticRoutes(WebServer& srv);` declaration
- `firmware/src/Routes_Static.cpp`: Route handler with `extractStaticFilename_`, `contentTypeFor_`, and `registerStaticRoutes` that registers GET handler for `/static/*`
- `firmware/test/test_routes_static.cpp`: 12 tests for path validation, content types, cache headers, SD card absent

FILES TO MODIFY
---------------

None.

TEST CASES
----------

T1: Serves JS file with correct content type
    SD card has /www/htmx.min.js → GET /static/htmx.min.js?v=0.4.1 → 200, Content-Type: application/javascript

T2: Serves CSS file with correct content type
    SD card has /www/app.css → GET /static/app.css?v=0.4.1 → 200, Content-Type: text/css

T3: Works without query string
    GET /static/htmx.min.js (no ?v=) → 200

T4: Path traversal blocked
    GET /static/../etc/passwd → 404

T5: Subdirectory blocked
    GET /static/subdir/file.js → 404

T6: Backslash blocked
    GET /static\..\file → 404

T7: Empty filename blocked
    GET /static/ → 404

T8: File not found returns 404
    SD card has no /www/missing.js → GET /static/missing.js → 404

T9: No SD card returns 404
    SD_MMC.cardType() == CARD_NONE → GET /static/htmx.min.js → 404

T10: Content type for .js
    .js extension → application/javascript

T11: Content type for .css
    .css extension → text/css

T12: Cache-Control header present
    All 200 responses include Cache-Control: max-age=31536000

VERIFICATION
------------

  cd firmware && make -C test test

Expected output:
  test_htmlutil: 8 tests passed
  test_routes_static: 12 tests passed
  All tests passed.

Exit code: 0

DONE WHEN
---------

- All 12 test_routes_static tests pass
- All previous tests still pass
- `extractStaticFilename_` rejects `..`, `/`, `\`, empty
- `contentTypeFor_` returns correct types for .js and .css
- Route handler delegates to `HttpFileSender::sendSdFile` with `max-age=31536000`
