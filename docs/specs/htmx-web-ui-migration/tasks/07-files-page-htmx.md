STEP 07: Files page htmx with HX-Redirect
=========================================

STATUS
------

Status: COMPLETE
Completed: 2025-07-16
Verified by: implement (independent re-run)

DEPENDS ON: step 06

SPEC
----

Make file operations on `/files` return htmx-compatible responses using `HX-Redirect` for state changes. The file table is too complex for partial swaps, so `HX-Redirect` triggers a full page reload after the operation completes (resolved question 1).

### Operations to modify

For each operation, when `isHtmxRequest(srv)` is true:
1. Send `HX-Redirect` response header with the target URL
2. Return 200 with a small fragment body (`.alert-ok` or `.alert-warn`)
3. Non-htmx requests keep current behavior (303 redirect)

**POST /upload-mode/enter** (currently 303 redirect to /files):
```cpp
if (isHtmxRequest(srv)) {
  srv.sendHeader(F("HX-Redirect"), F("/files"));
  HttpFileSender::sendText(srv, 200, F("text/html"),
    F("<div class='alert-ok'>Upload mode active.</div>"), F("no-store"));
  return;
}
```

**POST /upload-mode/exit** (currently 303 redirect to /files):
```cpp
if (isHtmxRequest(srv)) {
  srv.sendHeader(F("HX-Redirect"), F("/files"));
  HttpFileSender::sendText(srv, 200, F("text/html"),
    F("<div class='alert-ok'>Upload mode exited.</div>"), F("no-store"));
  return;
}
```

**GET /delete** (currently 303 redirect to /files?path=<parent>):
```cpp
if (isHtmxRequest(srv)) {
  String redirectUrl = F("/files?path=") + urlEncodeQueryValue_(parentDir(path));
  srv.sendHeader(F("HX-Redirect"), redirectUrl);
  HttpFileSender::sendText(srv, 200, F("text/html"),
    F("<div class='alert-ok'>Deleted.</div>"), F("no-store"));
  return;
}
```

**POST /delete_multi** (confirmed delete — currently renders full results page):
```cpp
if (isHtmxRequest(srv)) {
  String redirectUrl = F("/files?path=") + urlEncodeQueryValue_(dir);
  srv.sendHeader(F("HX-Redirect"), redirectUrl);
  HttpFileSender::sendText(srv, 200, F("text/html"),
    String(F("<div class='alert-ok'>Deleted ")) + String(okCount) + F(" file(s).</div>"), F("no-store"));
  return;
}
```

**POST /mkdir** (currently 303 redirect to /files?path=<dir>):
```cpp
if (isHtmxRequest(srv)) {
  String redirectUrl = F("/files?path=") + urlEncodeQueryValue_(normDir(base));
  srv.sendHeader(F("HX-Redirect"), redirectUrl);
  HttpFileSender::sendText(srv, 200, F("text/html"),
    F("<div class='alert-ok'>Folder created.</div>"), F("no-store"));
  return;
}
```

**409 mutation blocked** (currently `rejectManualFileMutation_` returns 409 plain text):
```cpp
if (isHtmxRequest(srv)) {
  HttpFileSender::sendText(srv, 200, F("text/html"),
    String(F("<div class='alert-warn'>Manual file changes are disabled while ")) + reason + F(".</div>"), F("no-store"));
  return true;
}
```

### Operations NOT modified

- **POST /upload** (multipart) — unchanged, always redirects. Multipart upload is not htmx-compatible.
- **GET /download** — unchanged, direct file download via `sendSdFile`.
- **POST /download_zip** — unchanged, binary ZIP response.

### GET /files form changes

Upload mode enter/exit forms get htmx attributes:
```html
<form method='POST' action='/upload-mode/enter'
      hx-post="/upload-mode/enter" hx-target="this" hx-swap="outerHTML" hx-sync="this:replace">
```

FILES TO CREATE
---------------

None.

FILES TO MODIFY
---------------

- `firmware/src/Routes_Files.cpp`: POST /upload-mode/enter, POST /upload-mode/exit, GET /delete, POST /delete_multi (confirmed), POST /mkdir — add isHtmxRequest checks with HX-Redirect; modify rejectManualFileMutation_ for htmx; GET /files — add hx-* to upload mode forms

TEST CASES
----------

T1: htmx upload mode enter returns HX-Redirect
    POST /upload-mode/enter with HX-Request: true → 200, HX-Redirect: /files header, body contains `<div class='alert-ok'>Upload mode active.</div>`

T2: Non-htmx upload mode enter returns 303
    POST /upload-mode/enter without HX-Request → 303 redirect to /files

T3: htmx delete returns HX-Redirect
    GET /delete?path=/file.csv with HX-Request: true → 200, HX-Redirect: /files?path=/ header, body contains `<div class='alert-ok'>Deleted.</div>`

T4: htmx delete while locked returns warn
    GET /delete with HX-Request: true while logging → 200, body contains `<div class='alert-warn'>`

T5: htmx mkdir returns HX-Redirect
    POST /mkdir with HX-Request: true and valid name → 200, HX-Redirect header, body contains `<div class='alert-ok'>Folder created.</div>`

T6: Upload mode forms have hx attributes
    GET /files page upload mode forms contain hx-post and hx-target

T7: Upload unchanged
    POST /upload still redirects (not htmx)

T8: Download unchanged
    GET /download still serves file directly (not htmx)

VERIFICATION
------------

  cd firmware && make -C test test && pio run -e thingplus_s3_usb_cdcserial_bodaqs_4f

Expected output:
  All tests passed.
  [PlatformIO build succeeds]

Exit code: 0

DONE WHEN
---------

- All previous tests still pass
- PlatformIO build succeeds
- POST /upload-mode/enter with HX-Request returns 200 + HX-Redirect header
- GET /delete with HX-Request returns 200 + HX-Redirect header
- 409 mutation blocked returns .alert-warn fragment for htmx
- POST /upload unchanged (still redirects)
- GET /download unchanged (still serves file)
- Upload mode forms on /files have hx-* attributes

## Notes

- All 6 operations modified: `rejectManualFileMutation_`, POST /upload-mode/enter, POST /upload-mode/exit, GET /delete, POST /delete_multi (confirmed), POST /mkdir.
- `rejectManualFileMutation_` now checks `isHtmxRequest(srv)` before sending 409; htmx requests get 200 with `.alert-warn` fragment. This automatically covers all callers: GET /delete, POST /delete_multi, POST /rmdir (GET+POST), POST /mkdir, POST /upload.
- POST /delete_multi confirmed: htmx path does a separate simple delete loop (count only) and returns fragment with `HX-Redirect`. Non-htmx path keeps the full results table page unchanged.
- `F("/files?path=") + urlEncodeQueryValue_(...)` does not compile on ESP32 (no `operator+(__FlashStringHelper*, String)`). Wrapped in `String(F(...))` for all three redirect URL constructions. The task file's code snippets used `F()` directly — this is a minor correction for the ESP32 compiler.
- Upload mode forms get `hx-post`, `hx-target='this'`, `hx-swap='outerHTML'`, `hx-sync='this:replace'` attributes.
- POST /upload, GET /download, POST /download_zip remain unchanged (not htmx-compatible).
- Host-based tests (79 passed) do not compile Routes_Files.cpp — only HtmlUtil.cpp and Routes_Static.cpp. Firmware build verifies Routes_Files.cpp compiles correctly.
- `HtmlUtil.h` and `HttpFileSender.h` were already included; no new includes needed.
