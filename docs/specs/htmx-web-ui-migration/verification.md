# Verification: htmx Web UI Migration

**Spec**: `docs/specs/htmx-web-ui-migration/spec.md`
**Design**: `docs/design/htmx-web-ui-migration.md`
**Plan**: `docs/specs/htmx-web-ui-migration/plan.md`
**Created**: 2025-06-23
**Status**: Plan

---

## 1. Acceptance Criteria Verification

### Static Asset Server — `firmware/src/Routes_Static.cpp` (new)

| AC | Criterion | Verification type | How verified | Task |
|----|-----------|-------------------|--------------|------|
| AC1 | Given SD card with `/www/htmx.min.js` mounted, when GET `/static/htmx.min.js?v=0.4.1`, then 200 with `Content-Type: application/javascript`, `Cache-Control: max-age=31536000`, `Accept-Ranges: bytes`, and file contents | unit | `test_routes_static.cpp`: `test_static_serves_js`, `test_static_cache_control_header` | T02 |
| AC2 | Given SD card with `/www/app.css` mounted, when GET `/static/app.css?v=0.4.1`, then 200 with `Content-Type: text/css` and `Cache-Control: max-age=31536000` | unit | `test_routes_static.cpp`: `test_static_serves_css`, `test_static_cache_control_header` | T02 |
| AC3 | Given no SD card mounted, when GET `/static/htmx.min.js`, then 404 with `text/plain` | unit | `test_routes_static.cpp`: `test_static_no_sd_card` | T02 |
| AC4 | Given SD card mounted, when GET `/static/../etc/passwd`, then 404 (path traversal blocked) | unit | `test_routes_static.cpp`: `test_static_path_traversal_blocked` | T02 |
| AC5 | Given SD card mounted, when GET `/static/subdir/file.js`, then 404 (subdirectories blocked) | unit | `test_routes_static.cpp`: `test_static_subdirectory_blocked` | T02 |
| AC6 | Given SD card with `/www/htmx.min.js`, when GET `/static/htmx.min.js` (no query string), then 200 (query string is optional) | unit | `test_routes_static.cpp`: `test_static_no_query_string` | T02 |
| AC7 | Given GET `/static/htmx.min.js?v=0.4.1` with `Range: bytes=0-1023` header, then 206 with `Content-Range: bytes 0-1023/<total>` (Range support delegated to `sendSdFile`) | integration | Manual test on ESP32 hardware with `curl -H "Range: bytes=0-1023" http://<ip>/static/htmx.min.js?v=0.4.1` | T04 |

### Fragment Responder — `firmware/src/HtmlUtil.cpp` / `HtmlUtil.h` (modified)

| AC | Criterion | Verification type | How verified | Task |
|----|-----------|-------------------|--------------|------|
| AC1 | Given request with header `HX-Request: true`, when `isHtmxRequest(srv)`, then returns `true` | unit | `test_htmlutil.cpp`: `test_isHtmxRequest_true` | T03 |
| AC2 | Given request without `HX-Request` header, when `isHtmxRequest(srv)`, then returns `false` | unit | `test_htmlutil.cpp`: `test_isHtmxRequest_false_absent` | T03 |
| AC3 | Given request with header `HX-Request: false`, when `isHtmxRequest(srv)`, then returns `false` | unit | `test_htmlutil.cpp`: `test_isHtmxRequest_false_other_value` | T03 |
| AC4 | Given `isHtmxRequest()` returns true, when `htmlRespond(srv, "Config", "<p>Saved.</p>")`, then output contains `<p>Saved.</p>` and does NOT contain `<html>`, `<head>`, `<script>`, or `<link>` | unit | `test_htmlutil.cpp`: `test_htmlRespond_fragment_mode` | T03 |
| AC5 | Given `isHtmxRequest()` returns false, when `htmlRespond(srv, "Config", "<p>Saved.</p>")`, then output contains `<html>`, `<head>`, `<title>Config</title>`, `<script src='/static/htmx.min.js?v=`, `<link rel='stylesheet' href='/static/app.css?v=`, and `<p>Saved.</p>` | unit | `test_htmlutil.cpp`: `test_htmlRespond_full_page_mode` | T03 |
| AC6 | Given `htmlFragment("<div class='alert-ok'>Saved.</div>")`, then output is exactly `<div class='alert-ok'>Saved.</div>` (no wrapping tags beyond the body content) | unit | `test_htmlutil.cpp`: `test_htmlFragment_returns_body_only`, `test_htmlFragment_no_html_tag` | T03 |

### HtmlUtil (modified) — `firmware/src/HtmlUtil.cpp`

| AC | Criterion | Verification type | How verified | Task |
|----|-----------|-------------------|--------------|------|
| AC1 | Given `htmlHeader("Config")` is called, then output contains `<script src='/static/htmx.min.js?v=0.4.1' defer></script>` in `<head>` (where `0.4.1` is the current `FirmwareInfo::version()`) | unit | `test_htmlutil.cpp`: `test_htmlHeader_includes_htmx_script` | T03 |
| AC2 | Given `htmlHeader("Config")` is called, then output contains `<link rel='stylesheet' href='/static/app.css?v=0.4.1'>` in `<head>` | unit | `test_htmlutil.cpp`: `test_htmlHeader_includes_app_css_link` | T03 |
| AC3 | Given `htmlHeader("Config")` is called, then output does NOT contain a `<style>` block (no inline CSS) | unit | `test_htmlutil.cpp`: `test_htmlHeader_no_inline_style` | T03 |
| AC4 | Given `htmlHeader("Config")` is called, then output still contains the title bar (`BODAQS data logger: <name>`), network bar, and nav bar (Files / General / Sensors) — same as current behavior | unit | `test_htmlutil.cpp`: `test_htmlHeader_includes_titlebar`, `test_htmlHeader_includes_navbar` | T03 |
| AC5 | Given `htmlFooter()` is called, then output is `</body></html>` (unchanged) | unit | `test_htmlutil.cpp`: `test_htmlFooter_returns_closing_tags` (from T01 baseline) | T01 |
| AC6 | Given SD card is absent and `app.css` returns 404, when page loads in browser, then page renders with browser default styles — forms are visible and functional (labels, inputs, fieldsets, buttons all work) | manual | Browser test: remove SD card, load `/config`, verify forms are usable without CSS | T04 |

### Route Handlers: Config Page — `firmware/src/Routes_Config.cpp` (modified)

| AC | Criterion | Verification type | How verified | Task |
|----|-----------|-------------------|--------------|------|
| AC1 | Given htmx request (`HX-Request: true`), when POST `/config` with valid form data, then 200 with `text/html` containing `<div class='alert-ok'>Configuration saved.</div>` and no `<html>` tag | integration | Manual test on ESP32: `curl -H "HX-Request: true" -X POST -d "submit=globals&logger_name=test" http://<ip>/config` | T05 |
| AC2 | Given non-htmx request, when POST `/config` with valid form data, then 303 redirect to `/config?ok=1` (current behavior unchanged) | integration | Manual test on ESP32: `curl -X POST -d "submit=globals&logger_name=test" http://<ip>/config` — verify 303 | T05 |
| AC3 | Given htmx request, when POST `/config` with `wifi_ap_password` of 3 characters, then 200 with `<div class='alert-err'>` containing password length error message | integration | Manual test on ESP32: `curl -H "HX-Request: true" -X POST -d "submit=globals&wifi_ap_password=abc" http://<ip>/config` | T05 |
| AC4 | Given htmx request, when POST `/config` while logging is active, then 200 with `<div class='alert-warn'>` containing lock message | integration | Manual test on ESP32: start logging, then `curl -H "HX-Request: true" -X POST -d "submit=globals" http://<ip>/config` | T05 |
| AC5 | Given htmx request, when POST `/config` and `ConfigManager::save()` fails, then 200 with `<div class='alert-err'>Failed to save config</div>` | integration | Manual test on ESP32: simulate save failure (e.g., corrupt NVS), POST with htmx header | T05 |
| AC6 | Given the `/config` GET page, when rendered, then the `<form>` tag contains `hx-post="/config"`, `hx-target="#save-result"`, `hx-swap="innerHTML"`, and `hx-sync="this:replace"` | code review | Grep `Routes_Config.cpp` for `hx-post`, `hx-target`, `hx-swap`, `hx-sync` in the GET `/config` handler | T05 |
| AC7 | Given the `/config` GET page, when rendered, then a `<div id="save-result"></div>` exists before the form (htmx swap target) | code review | Grep `Routes_Config.cpp` for `save-result` div before form tag | T05 |
| AC8 | Given the `/config` GET page, when rendered, then the submit button contains `<span class="htmx-indicator">Saving...</span>` | code review | Grep `Routes_Config.cpp` for `htmx-indicator` in submit button | T05 |
| AC9 | Given non-htmx request, when POST `/config/sensors` with `delete_sensor_idx`, then 303 redirect (current behavior unchanged) | integration | Manual test on ESP32: `curl -X POST -d "delete_sensor_idx=0" http://<ip>/config/sensors` — verify 303 | T06 |
| AC10 | Given htmx request, when POST `/config/sensors` with `delete_sensor_idx`, then 200 with `<div class='alert-ok'>Sensor deleted. Restart the logger to rebuild the live sensor set.</div>` | integration | Manual test on ESP32: `curl -H "HX-Request: true" -X POST -d "delete_sensor_idx=0" http://<ip>/config/sensors` | T06 |
| AC11 | Given htmx request, when POST `/config/sensors` with `add_sensor`, then 200 with `<div class='alert-ok'>Sensor added. Restart the logger to rebuild the live sensor set.</div>` | integration | Manual test on ESP32: `curl -H "HX-Request: true" -X POST -d "add_sensor=1" http://<ip>/config/sensors` | T06 |
| AC12 | Given the `/config/sensor?id=N` GET page, when rendered, then the `<form>` tag contains `hx-post="/config/sensors"`, `hx-target="#sensor-result"`, `hx-swap="innerHTML"` | code review | Grep `Routes_Config.cpp` for `sensor-result` and `hx-post` in sensor editor form | T06 |
| AC13 | Given htmx request, when POST `/config/sensors` with sensor field data (save), then 200 with `<div class='alert-ok'>Saved.</div>` | integration | Manual test on ESP32: `curl -H "HX-Request: true" -X POST -d "s0.name=test" http://<ip>/config/sensors` | T06 |

### Route Handlers: Files Page — `firmware/src/Routes_Files.cpp` (modified)

| AC | Criterion | Verification type | How verified | Task |
|----|-----------|-------------------|--------------|------|
| AC1 | Given htmx request, when POST `/upload-mode/enter`, then 200 with `<div class='alert-ok'>Upload mode active.</div>` and `HX-Redirect: /files` response header | integration | Manual test on ESP32: `curl -H "HX-Request: true" -X POST http://<ip>/upload-mode/enter` — check body and `HX-Redirect` header | T07 |
| AC2 | Given non-htmx request, when POST `/upload-mode/enter`, then 303 redirect to `/files` (current behavior) | integration | Manual test on ESP32: `curl -X POST http://<ip>/upload-mode/enter` — verify 303 | T07 |
| AC3 | Given htmx request, when GET `/delete?path=/file.csv`, then 200 with `<div class='alert-ok'>Deleted.</div>` and `HX-Redirect: /files?path=/` response header | integration | Manual test on ESP32: create file on SD card, `curl -H "HX-Request: true" http://<ip>/delete?path=/file.csv` | T07 |
| AC4 | Given non-htmx request, when GET `/delete?path=/file.csv`, then 303 redirect to `/files?path=/` (current behavior) | integration | Manual test on ESP32: `curl http://<ip>/delete?path=/file.csv` — verify 303 | T07 |
| AC5 | Given htmx request, when GET `/delete` while logging active, then 200 with `<div class='alert-warn'>` containing lock message | integration | Manual test on ESP32: start logging, `curl -H "HX-Request: true" http://<ip>/delete?path=/file.csv` | T07 |
| AC6 | Given the `/files` GET page, when rendered, then upload mode enter/exit forms contain `hx-post` and `hx-target` attributes | code review | Grep `Routes_Files.cpp` for `hx-post` in `appendUploadModePanel_` | T07 |
| AC7 | Given the `/files` GET page, when rendered, then delete links can be converted to htmx via `hx-get` with `hx-target` (or remain as regular links that redirect — implementation choice) | code review | Inspect `Routes_Files.cpp` delete link rendering in `listDirMMC_` | T07 |
| AC8 | Given htmx request, when POST `/mkdir` with valid name, then 200 with `<div class='alert-ok'>Folder created.</div>` and `HX-Redirect: /files?path=<dir>` header | integration | Manual test on ESP32: `curl -H "HX-Request: true" -X POST -d "path=/&name=testdir" http://<ip>/mkdir` | T07 |

### WebServerManager (modified) — `firmware/src/WebServerManager.cpp`

| AC | Criterion | Verification type | How verified | Task |
|----|-----------|-------------------|--------------|------|
| AC1 | Given firmware is compiled with `Routes_Static.cpp`, when `setupRoutes()` is called, then `/static/htmx.min.js` is a registered route | code review | Grep `WebServerManager.cpp` for `registerStaticRoutes` call in `setupRoutes()` | T04 |
| AC2 | Given `/static/*` route is registered, when GET `/static/nonexistent.js`, then 404 (does not fall through to `onNotFound`) | integration | Manual test on ESP32: `curl http://<ip>/static/nonexistent.js` — verify 404, not the `onNotFound` 404 page | T04 |

### Static Assets — `htmx.min.js`, `app.css`

| AC | Criterion | Verification type | How verified | Task |
|----|-----------|-------------------|--------------|------|
| AC1 | Given `/www/htmx.min.js` on SD card, when GET `/static/htmx.min.js`, then response body starts with `htmx` (minified JS) | integration | Manual test on ESP32: `curl http://<ip>/static/htmx.min.js` — verify body starts with `htmx` | T04 |
| AC2 | Given `/www/app.css` on SD card, when GET `/static/app.css`, then response body contains `--shadow-grey: #212227` and `--lavender-grey: #8693ab` | integration | Manual test on ESP32: `curl http://<ip>/static/app.css` — verify CSS custom properties present | T04, T08 |
| AC3 | Given `app.css` loaded in browser, when viewing `/config` at 375px width, then no horizontal scrolling (all fields fit) | manual | Browser DevTools: set viewport to 375px, load `/config`, verify no horizontal scrollbar | T08 |

---

## 2. Validation & Error Spec Verification

### Validation Rules

| # | Component | Field | Rule | Error | Verification type | How verified | Task |
|---|-----------|-------|------|-------|-------------------|--------------|------|
| V1 | Static Asset Server | URI path | Must start with `/static/` | 404 Not Found | unit | `test_routes_static.cpp`: all tests use `/static/` prefix | T02 |
| V2 | Static Asset Server | Filename (after `/static/` strip) | Must not contain `..` | 404 Not Found | unit | `test_routes_static.cpp`: `test_static_path_traversal_blocked` | T02 |
| V3 | Static Asset Server | Filename | Must not contain `/` (no subdirectories) | 404 Not Found | unit | `test_routes_static.cpp`: `test_static_subdirectory_blocked` | T02 |
| V4 | Static Asset Server | Filename | Must not contain `\` (no backslash) | 404 Not Found | unit | `test_routes_static.cpp`: `test_static_backslash_blocked` | T02 |
| V5 | Static Asset Server | Filename | Must not be empty | 404 Not Found | unit | `test_routes_static.cpp`: `test_static_empty_filename` | T02 |
| V6 | Static Asset Server | Query string | Stripped before file lookup — `?v=0.4.1` ignored | N/A | unit | `test_routes_static.cpp`: `test_static_no_query_string` | T02 |
| V7 | Static Asset Server | SD card | Must be mounted (`SD_MMC.cardType() != CARD_NONE`) | 404 Not Found | unit | `test_routes_static.cpp`: `test_static_no_sd_card` | T02 |
| V8 | Static Asset Server | File | Must exist at `/www/<filename>` on SD card | 404 Not Found | unit | `test_routes_static.cpp`: `test_static_file_not_found` | T02 |
| V9 | Config Page | `wifi_ap_password` | 8-63 characters | htmx: 200 with `.alert-err`; non-htmx: 303 redirect to `/config?err=wifi_ap_password_length` | integration | Manual test: POST with 3-char password, both htmx and non-htmx | T05 |
| V10 | Config Page | `wifi_static_ip` | IP/gateway/subnet required if enabled | htmx: 200 with `.alert-err`; non-htmx: 303 redirect to `/config?err=wifi_static_ip_incomplete` | integration | Manual test: enable static IP, leave gateway blank, POST | T05 |
| V11 | Config Page | Config lock | `configEditLocked_()` returns true | htmx: 200 with `.alert-warn`; non-htmx: 423 with plain text | integration | Manual test: start logging, POST `/config` with and without htmx header | T05 |
| V12 | Files Page | Mutation lock | `manualFileMutationBlocked_()` returns true | htmx: 200 with `.alert-warn`; non-htmx: 409 with plain text | integration | Manual test: start logging, GET `/delete?path=/file.csv` with and without htmx header | T07 |
| V13 | Files Page | Path safety | `safeRelPath()` rejects `..`, `\`, `//` | 400 Bad Request | integration | Manual test: `curl http://<ip>/delete?path=../etc/passwd` | T07 |

### Error Specifications

| # | Component | Error | When | htmx response | Non-htmx response | Verification type | How verified | Task |
|---|-----------|-------|------|---------------|-------------------|-------------------|--------------|------|
| E1 | Static Asset Server | 404 Not Found | SD card not mounted, file not found, or invalid path | N/A (same for all) | `text/plain`: "Not found" | unit | `test_routes_static.cpp`: `test_static_no_sd_card`, `test_static_file_not_found`, `test_static_path_traversal_blocked` | T02 |
| E2 | Config Page | 423 Locked | Logging or upload mode active | 200, `text/html`, `<div class='alert-warn'>Configuration is locked while <reason>.</div>` (htmx v2.0 does not swap 4xx bodies) | 423, `text/plain`, `Configuration is locked while <reason>.` (current) | integration | Manual test: start logging, POST `/config` with and without `HX-Request: true` | T05 |
| E3 | Config Page | Validation error | Field validation fails (e.g., password length) | 200, `text/html`, `<div class='alert-err'>Error: <message></div>` | 303 redirect to `/config?err=<code>` (current) | integration | Manual test: POST with short password, both modes | T05 |
| E4 | Config Page | 500 Save failure | `ConfigManager::save()` returns false | 200, `text/html`, `<div class='alert-err'>Failed to save config</div>` | 500, `text/plain`, `Failed to save config` (current) | integration | Manual test: simulate save failure, POST with htmx header | T05 |
| E5 | Config Page | Success | Config saved | 200, `text/html`, `<div class='alert-ok'>Configuration saved.</div>` | 303 redirect to `/config?ok=1` (current) | integration | Manual test: POST valid config, both modes | T05 |
| E6 | Files Page | 409 Mutation blocked | Logging or upload mode active | 200, `text/html`, `<div class='alert-warn'>Manual file changes are disabled while <reason>.</div>` | 409, `text/plain` (current) | integration | Manual test: start logging, GET `/delete` with and without htmx header | T07 |
| E7 | Files Page | 404 Not found | File not found | 200, `text/html`, `<div class='alert-err'>File not found.</div>` | 404, `text/plain` (current) | integration | Manual test: GET `/delete?path=/nonexistent.csv` with htmx header | T07 |
| E8 | Files Page | Success (delete) | File deleted | 200, `text/html`, `<div class='alert-ok'>Deleted.</div>` + `HX-Redirect: /files?path=<dir>` header | 303 redirect (current) | integration | Manual test: create file, GET `/delete?path=/file.csv` with htmx header | T07 |
| E9 | Files Page | Success (upload mode) | Mode entered/exited | 200, `text/html`, `<div class='alert-ok'>Upload mode active.</div>` + `HX-Redirect: /files` header | 303 redirect (current) | integration | Manual test: POST `/upload-mode/enter` with htmx header | T07 |

---

## 3. Invariant & Contract Verification

| ID | Invariant / Contract | Verification | Verified By |
|----|----------------------|-------------|-------------|
| INV-1 | Every page is fully functional without JavaScript. htmx enhances; it does not replace. Forms POST normally and the server returns full pages when `HX-Request` header is absent. | manual: Disable JS in browser, navigate to `/config`, submit form — verify form POSTs and page reloads with result. Repeat for `/config/sensor`, `/files`. | T05, T06, T07 |
| INV-2 | Static assets served with `Cache-Control: max-age=31536000` and `?v=<firmware-version>` query string. Browser caches indefinitely for a given firmware version. Cache invalidates automatically on firmware update. | unit: `test_routes_static.cpp` verifies `Cache-Control: max-age=31536000` header. unit: `test_htmlutil.cpp` verifies `?v=0.4.1` in script/link tags. manual: Browser DevTools Network tab — first load fetches `?v=0.4.1`, subsequent loads use cache (zero requests). | T02, T03, T04 |
| INV-3 | No response exceeds the existing memory envelope. Fragment responses use the same 2 KB chunked streaming as full-page responses. No response body is buffered in full in heap. | unit: `test_fragments.cpp`: `test_fragment_size_under_2kb` verifies fragment strings < 2048 bytes. code review: Verify fragment responses use `HttpFileSender::sendText()` (which chunks at 2 KB) or `ChunkedHtmlResponse`, not `srv.send()` with full body. | T04, T05 |
| INV-4 | Config editing remains locked during logging or upload mode. htmx requests receive 200 with `.alert-warn` fragment (htmx v2.0 does not swap 4xx bodies); non-htmx requests receive 423 plain text. | integration: Start logging, POST `/config` with `HX-Request: true` — verify 200 with `.alert-warn` fragment. POST without header — verify 423 with plain text. | T05 |
| INV-5 | The server handles one request at a time. htmx is configured with `hx-sync` where needed to prevent overlapping requests. | code review: Grep all form tags in `Routes_Config.cpp` and `Routes_Files.cpp` for `hx-sync="this:replace"`. | T05, T06, T07 |

---

## 4. Success Criteria Traceability

| # | Success Criterion | How measured | Covered by |
|---|-------------------|--------------|------------|
| G1 | Submit any form on `/config` or `/config/sensor` — browser URL does not change, scroll position is preserved, no white flash | manual: Browser test — fill form, scroll down, submit, verify URL unchanged and scroll position preserved | T05, T06 |
| G2 | First page load fetches `htmx.min.js?v=0.4.1` and `app.css?v=0.4.1`; subsequent page loads use cache (zero requests for static assets) | manual: Browser DevTools Network tab — first load shows 2 requests for static assets, second load shows 0 | T04 |
| G3 | Disable JavaScript in browser, navigate to `/config`, submit form — form POSTs normally and page reloads with result | manual: Browser test — disable JS, navigate, submit, verify page reloads with result | T05 |
| G4 | `ESP.getFreeHeap()` before and after a config page load is within ±2 KB of baseline | integration: ESP32 serial monitor — call `ESP.getFreeHeap()` before and after loading `/config`, compare to baseline | T04 |
| G5 | `firmware.bin` size delta < 20 KB | measurement: Compare `.pio/build/thingplus_s3_usb_cdcserial_bodaqs_4f/firmware.bin` size before and after all phases | T04, T08 |
| G6 | Open `/config` in browser DevTools at 375px width — no horizontal scroll, all fields tappable | manual: Browser DevTools — set viewport to 375px, load `/config`, verify no horizontal scrollbar | T08 |
| INV-4 | Config editing locked during logging — htmx request receives 200 with `.alert-warn` fragment; non-htmx receives 423 plain text | integration: Start logging, POST `/config` with `HX-Request: true`, verify 200 + `.alert-warn`; POST without header, verify 423 plain text | T05 |
| INV-5 | No overlapping requests — `hx-sync="this:replace"` on all forms prevents queued requests | code review: Grep for `hx-sync` on all form tags in `Routes_Config.cpp` and `Routes_Files.cpp` | T05, T06, T07 |
| T1 | `make -C firmware/test test` passes all host-based unit tests with zero failures | automated: Run test command, verify exit 0 | T00–T04 |
| T2 | Test binary is NOT included in `firmware.bin` — `firmware.bin` size does not increase by more than the production code delta (< 20 KB per G5) | measurement: Compare firmware.bin size; verify `firmware/test/` is not in PlatformIO build path | T04 |
| T3 | All `test_htmlutil.cpp` tests pass (15 tests covering htmlHeader, htmlFooter, htmlEscape, htmlFragment, isHtmxRequest, htmlRespond) | automated: Run test command, verify 15 tests pass | T03 |
| T4 | All `test_routes_static.cpp` tests pass (12 tests covering path validation, content types, cache headers, SD card absent) | automated: Run test command, verify 12 tests pass | T02 |
| T5 | All `test_fragments.cpp` tests pass (5 tests covering fragment format, alert classes, size constraints) | automated: Run test command, verify 5 tests pass | T04 |

---

## 5. Unit Test Plan

30 host-based tests across 3 files. Ordered by risk: high-priority tests cover security (path traversal) and core functionality (htmx detection, fragment format); medium-priority tests cover content types and cache headers; low-priority tests cover CSS content and structural HTML.

### High Priority

Tests that protect security boundaries and core htmx detection logic. Failure would break path traversal protection or cause htmx to malfunction.

| # | File | Test name | What it verifies | AC / INV covered | Task |
|---|------|-----------|------------------|------------------|------|
| 1 | `test_routes_static.cpp` | `test_static_path_traversal_blocked` | GET `/static/../etc/passwd` → 404 | Static AC4, V2 | T02 |
| 2 | `test_routes_static.cpp` | `test_static_subdirectory_blocked` | GET `/static/subdir/file.js` → 404 | Static AC5, V3 | T02 |
| 3 | `test_routes_static.cpp` | `test_static_backslash_blocked` | GET `/static\..\file` → 404 | V4 | T02 |
| 4 | `test_routes_static.cpp` | `test_static_empty_filename` | GET `/static/` → 404 | V5 | T02 |
| 5 | `test_routes_static.cpp` | `test_static_no_sd_card` | `SD_MMC.cardType() == CARD_NONE` → 404 | Static AC3, V7 | T02 |
| 6 | `test_routes_static.cpp` | `test_static_file_not_found` | File not on SD card → 404 | V8 | T02 |
| 7 | `test_htmlutil.cpp` | `test_isHtmxRequest_true` | `HX-Request: true` header → returns `true` | Fragment AC1 | T03 |
| 8 | `test_htmlutil.cpp` | `test_isHtmxRequest_false_absent` | No `HX-Request` header → returns `false` | Fragment AC2, INV-1 | T03 |
| 9 | `test_htmlutil.cpp` | `test_isHtmxRequest_false_other_value` | `HX-Request: false` → returns `false` | Fragment AC3 | T03 |
| 10 | `test_htmlutil.cpp` | `test_htmlRespond_fragment_mode` | htmx request → returns fragment (no `<html>`) | Fragment AC4 | T03 |
| 11 | `test_htmlutil.cpp` | `test_htmlRespond_full_page_mode` | non-htmx request → returns full page (with `<html>`, `<script>`, `<link>`) | Fragment AC5, INV-1 | T03 |
| 12 | `test_fragments.cpp` | `test_fragment_no_html_wrapper` | No fragment contains `<html>`, `<head>`, `<body>`, `<script>`, or `<link>` | INV-3 | T04 |
| 13 | `test_fragments.cpp` | `test_fragment_size_under_2kb` | All fragment responses are < 2048 bytes | INV-3 | T04 |

### Medium Priority

Tests that verify correct content types, cache headers, and HTML structure. Failure would cause browser rendering issues or cache misses.

| # | File | Test name | What it verifies | AC / INV covered | Task |
|---|------|-----------|------------------|------------------|------|
| 14 | `test_routes_static.cpp` | `test_static_serves_js` | SD card has `/www/htmx.min.js` → GET returns 200, `application/javascript` | Static AC1 | T02 |
| 15 | `test_routes_static.cpp` | `test_static_serves_css` | SD card has `/www/app.css` → GET returns 200, `text/css` | Static AC2 | T02 |
| 16 | `test_routes_static.cpp` | `test_static_no_query_string` | GET `/static/htmx.min.js` (no `?v=`) → 200 | Static AC6, V6 | T02 |
| 17 | `test_routes_static.cpp` | `test_static_content_type_js` | `.js` extension → `application/javascript` | Static AC1 | T02 |
| 18 | `test_routes_static.cpp` | `test_static_content_type_css` | `.css` extension → `text/css` | Static AC2 | T02 |
| 19 | `test_routes_static.cpp` | `test_static_cache_control_header` | All 200 responses include `Cache-Control: max-age=31536000` | Static AC1, AC2, INV-2 | T02 |
| 20 | `test_htmlutil.cpp` | `test_htmlHeader_includes_htmx_script` | `htmlHeader("Config")` contains `<script src='/static/htmx.min.js?v=0.4.1' defer></script>` | HtmlUtil AC1, INV-2 | T03 |
| 21 | `test_htmlutil.cpp` | `test_htmlHeader_includes_app_css_link` | `htmlHeader("Config")` contains `<link rel='stylesheet' href='/static/app.css?v=0.4.1'>` | HtmlUtil AC2, INV-2 | T03 |
| 22 | `test_htmlutil.cpp` | `test_htmlHeader_no_inline_style` | `htmlHeader("Config")` does NOT contain `<style>` | HtmlUtil AC3 | T03 |
| 23 | `test_htmlutil.cpp` | `test_htmlFragment_returns_body_only` | `htmlFragment("<div class='alert-ok'>OK</div>")` is exactly that string | Fragment AC6 | T03 |
| 24 | `test_htmlutil.cpp` | `test_htmlFragment_no_html_tag` | `htmlFragment` output does NOT contain `<html>`, `<head>`, `<script>`, `<link>` | Fragment AC6 | T03 |
| 25 | `test_fragments.cpp` | `test_fragment_success_format` | Success fragment is `<div class='alert-ok'>Configuration saved.</div>` | Config AC1, E5 | T04 |
| 26 | `test_fragments.cpp` | `test_fragment_error_format` | Error fragment is `<div class='alert-err'>Error: <message></div>` | Config AC3, E3 | T04 |
| 27 | `test_fragments.cpp` | `test_fragment_warn_format` | Warning fragment is `<div class='alert-warn'>Configuration is locked while <reason>.</div>` | Config AC4, E2 | T04 |

### Low Priority

Tests that verify structural HTML elements and version string behavior. Failure would be visible but not security-critical.

| # | File | Test name | What it verifies | AC / INV covered | Task |
|---|------|-----------|------------------|------------------|------|
| 28 | `test_htmlutil.cpp` | `test_htmlHeader_includes_navbar` | `htmlHeader("Config")` contains `Files`, `General`, `Sensors` nav links | HtmlUtil AC4 | T03 |
| 29 | `test_htmlutil.cpp` | `test_htmlHeader_includes_titlebar` | `htmlHeader("Config")` contains `BODAQS data logger:` | HtmlUtil AC4 | T03 |
| 30 | `test_htmlutil.cpp` | `test_htmlHeader_version_changes_with_firmware` | Set `FirmwareInfo::version()` to `"0.5.0"` → `htmlHeader()` output contains `?v=0.5.0` | INV-2 | T03 |

---

## 6. Integration / Deployment Test Plan

Integration tests require ESP32-S3 hardware with SD card containing `/www/htmx.min.js` and `/www/app.css`. Tests are performed manually via `curl` or browser.

### Test 1: Static asset serving — JS file

**Setup**: ESP32 with SD card containing `/www/htmx.min.js`. Logger in AP or STA mode.

**Steps**:
1. `curl -s -o /dev/null -w "%{http_code}" http://<ip>/static/htmx.min.js?v=0.4.1`
2. `curl -s -I http://<ip>/static/htmx.min.js?v=0.4.1`
3. Verify response body starts with `htmx`

**Expected**: HTTP 200, `Content-Type: application/javascript`, `Cache-Control: max-age=31536000`, `Accept-Ranges: bytes`

**Covers**: Static AC1, Static AC1 (assets), INV-2

### Test 2: Static asset serving — CSS file

**Setup**: ESP32 with SD card containing `/www/app.css`.

**Steps**:
1. `curl -s -o /dev/null -w "%{http_code}" http://<ip>/static/app.css?v=0.4.1`
2. `curl -s -I http://<ip>/static/app.css?v=0.4.1`
3. Verify response body contains `--shadow-grey: #212227`

**Expected**: HTTP 200, `Content-Type: text/css`, `Cache-Control: max-age=31536000`

**Covers**: Static AC2, Static AC2 (assets), INV-2

### Test 3: Static asset — Range request

**Setup**: ESP32 with SD card containing `/www/htmx.min.js`.

**Steps**:
1. `curl -s -o /dev/null -w "%{http_code}" -H "Range: bytes=0-1023" http://<ip>/static/htmx.min.js?v=0.4.1`
2. `curl -s -I -H "Range: bytes=0-1023" http://<ip>/static/htmx.min.js?v=0.4.1`

**Expected**: HTTP 206, `Content-Range: bytes 0-1023/<total>`

**Covers**: Static AC7

### Test 4: Static asset — path traversal blocked

**Setup**: ESP32 with SD card mounted.

**Steps**:
1. `curl -s -o /dev/null -w "%{http_code}" http://<ip>/static/../etc/passwd`
2. `curl -s -o /dev/null -w "%{http_code}" http://<ip>/static/subdir/file.js`

**Expected**: HTTP 404 for both

**Covers**: Static AC4, AC5

### Test 5: Static asset — nonexistent file returns 404 (not onNotFound page)

**Setup**: ESP32 with SD card mounted.

**Steps**:
1. `curl -s http://<ip>/static/nonexistent.js`
2. Verify response is `text/plain` "Not found", not the HTML 404 page from `onNotFound`

**Expected**: HTTP 404, `text/plain`, body "Not found"

**Covers**: WebServerManager AC2

### Test 6: Config page — htmx save success

**Setup**: ESP32 with SD card. Logger not logging, not in upload mode.

**Steps**:
1. `curl -s -H "HX-Request: true" -X POST -d "submit=globals&logger_name=test" http://<ip>/config`
2. Verify response body

**Expected**: HTTP 200, `text/html`, body contains `<div class='alert-ok'>Configuration saved.</div>`, no `<html>` tag

**Covers**: Config AC1, E5

### Test 7: Config page — non-htmx save success (303 redirect)

**Setup**: ESP32 with SD card. Logger not logging.

**Steps**:
1. `curl -s -o /dev/null -w "%{http_code}" -X POST -d "submit=globals&logger_name=test" http://<ip>/config`
2. `curl -s -I -X POST -d "submit=globals&logger_name=test" http://<ip>/config`

**Expected**: HTTP 303, `Location: /config?ok=1&tab=globals`

**Covers**: Config AC2, INV-1

### Test 8: Config page — htmx validation error

**Setup**: ESP32 with SD card. Logger not logging.

**Steps**:
1. `curl -s -H "HX-Request: true" -X POST -d "submit=globals&wifi_ap_password=abc" http://<ip>/config`
2. Verify response body

**Expected**: HTTP 200, `text/html`, body contains `<div class='alert-err'>` with password length error message

**Covers**: Config AC3, E3, V9

### Test 9: Config page — htmx lock (200 with warn fragment)

**Setup**: ESP32 with SD card. Start logging via the web UI or button.

**Steps**:
1. `curl -s -H "HX-Request: true" -X POST -d "submit=globals" http://<ip>/config`
2. Verify response body and status code

**Expected**: HTTP 200, `text/html`, body contains `<div class='alert-warn'>Configuration is locked while logging is active.</div>`

**Covers**: Config AC4, E2, INV-4

### Test 10: Config page — non-htmx 423 lock

**Setup**: ESP32 with SD card. Start logging.

**Steps**:
1. `curl -s -X POST -d "submit=globals" http://<ip>/config`
2. Verify response body and status code

**Expected**: HTTP 423, `text/plain`, body `Configuration is locked while logging is active.`

**Covers**: Config AC4, E2, INV-1, INV-4

### Test 11: Config page — form has hx-* attributes

**Setup**: ESP32 with SD card.

**Steps**:
1. `curl -s http://<ip>/config`
2. Verify form tag contains `hx-post="/config"`, `hx-target="#save-result"`, `hx-swap="innerHTML"`, `hx-sync="this:replace"`
3. Verify `<div id="save-result"></div>` exists before the form
4. Verify submit button contains `<span class="htmx-indicator">Saving...</span>`

**Expected**: All attributes and elements present in HTML

**Covers**: Config AC6, AC7, AC8, INV-5

### Test 12: Sensor page — htmx delete

**Setup**: ESP32 with SD card. At least 1 sensor configured. Logger not logging.

**Steps**:
1. `curl -s -H "HX-Request: true" -X POST -d "delete_sensor_idx=0" http://<ip>/config/sensors`
2. Verify response body

**Expected**: HTTP 200, `text/html`, body contains `<div class='alert-ok'>Sensor deleted. Restart the logger to rebuild the live sensor set.</div>`

**Covers**: Config AC10

### Test 13: Sensor page — htmx add

**Setup**: ESP32 with SD card. Logger not logging.

**Steps**:
1. `curl -s -H "HX-Request: true" -X POST -d "add_sensor=1" http://<ip>/config/sensors`
2. Verify response body

**Expected**: HTTP 200, `text/html`, body contains `<div class='alert-ok'>Sensor added. Restart the logger to rebuild the live sensor set.</div>`

**Covers**: Config AC11

### Test 14: Sensor page — non-htmx delete (303 redirect)

**Setup**: ESP32 with SD card. At least 1 sensor configured. Logger not logging.

**Steps**:
1. `curl -s -o /dev/null -w "%{http_code}" -X POST -d "delete_sensor_idx=0" http://<ip>/config/sensors`

**Expected**: HTTP 303

**Covers**: Config AC9, INV-1

### Test 15: Sensor editor — form has hx-* attributes

**Setup**: ESP32 with SD card. At least 1 sensor configured.

**Steps**:
1. `curl -s "http://<ip>/config/sensor?id=0"`
2. Verify form tag contains `hx-post="/config/sensors"`, `hx-target="#sensor-result"`, `hx-swap="innerHTML"`, `hx-sync="this:replace"`
3. Verify `<div id="sensor-result"></div>` exists before the form
4. Verify Apply Type button does NOT have `hx-*` attributes

**Expected**: All attributes present on Save Sensor form; Apply Type is a plain submit button

**Covers**: Config AC12, INV-5

### Test 16: Files page — htmx upload mode enter

**Setup**: ESP32 with SD card. Logger not logging, not in upload mode.

**Steps**:
1. `curl -s -H "HX-Request: true" -X POST http://<ip>/upload-mode/enter`
2. Verify response body and headers

**Expected**: HTTP 200, `text/html`, body contains `<div class='alert-ok'>Upload mode active.</div>`, `HX-Redirect: /files` header

**Covers**: Files AC1, E9

### Test 17: Files page — non-htmx upload mode enter (303 redirect)

**Setup**: ESP32 with SD card. Logger not logging.

**Steps**:
1. `curl -s -o /dev/null -w "%{http_code}" -X POST http://<ip>/upload-mode/enter`

**Expected**: HTTP 303, `Location: /files`

**Covers**: Files AC2, INV-1

### Test 18: Files page — htmx delete

**Setup**: ESP32 with SD card. Create a test file at `/file.csv`. Logger not logging.

**Steps**:
1. `curl -s -H "HX-Request: true" http://<ip>/delete?path=/file.csv`
2. Verify response body and headers

**Expected**: HTTP 200, `text/html`, body contains `<div class='alert-ok'>Deleted.</div>`, `HX-Redirect: /files?path=/` header

**Covers**: Files AC3, E8

### Test 19: Files page — htmx delete while locked

**Setup**: ESP32 with SD card. Start logging.

**Steps**:
1. `curl -s -H "HX-Request: true" http://<ip>/delete?path=/file.csv`
2. Verify response body

**Expected**: HTTP 200, `text/html`, body contains `<div class='alert-warn'>` with lock message

**Covers**: Files AC5, E6, V12

### Test 20: Files page — htmx mkdir

**Setup**: ESP32 with SD card. Logger not logging.

**Steps**:
1. `curl -s -H "HX-Request: true" -X POST -d "path=/&name=testdir" http://<ip>/mkdir`
2. Verify response body and headers

**Expected**: HTTP 200, `text/html`, body contains `<div class='alert-ok'>Folder created.</div>`, `HX-Redirect` header

**Covers**: Files AC8

### Test 21: Files page — upload unchanged

**Setup**: ESP32 with SD card. Logger not logging.

**Steps**:
1. `curl -s -o /dev/null -w "%{http_code}" -X POST -F "file=@test.txt" http://<ip>/upload?path=/`

**Expected**: HTTP 303 (redirect, not htmx response)

**Covers**: Files AC7 (upload unchanged)

### Test 22: Files page — download unchanged

**Setup**: ESP32 with SD card. File exists at `/file.csv`.

**Steps**:
1. `curl -s -o /dev/null -w "%{http_code}" http://<ip>/download?path=/file.csv`

**Expected**: HTTP 200, file contents (not htmx response)

**Covers**: Files AC7 (download unchanged)

### Test 23: Browser — no page reload on config save

**Setup**: ESP32 with SD card. Browser connected to logger WiFi.

**Steps**:
1. Open browser, navigate to `http://<ip>/config`
2. Scroll down to a WiFi slot
3. Change logger name, click Save
4. Observe: URL does not change, scroll position preserved, no white flash
5. Verify success banner appears above the form

**Expected**: Page does not reload, inline success feedback visible

**Covers**: G1, G2 (US2)

### Test 24: Browser — graceful degradation without JS

**Setup**: ESP32 with SD card. Browser connected to logger WiFi.

**Steps**:
1. Disable JavaScript in browser
2. Navigate to `http://<ip>/config`
3. Change logger name, click Save
4. Observe: page reloads with result

**Expected**: Form POSTs normally, page reloads with success/error

**Covers**: G3, INV-1

### Test 25: Browser — static asset caching

**Setup**: ESP32 with SD card. Browser connected to logger WiFi.

**Steps**:
1. Open browser DevTools Network tab
2. Navigate to `http://<ip>/config` (first load)
3. Verify Network tab shows requests for `htmx.min.js?v=0.4.1` and `app.css?v=0.4.1`
4. Navigate to `http://<ip>/config/sensors` (second page)
5. Verify Network tab shows zero requests for static assets (from disk cache)

**Expected**: First load fetches assets, subsequent loads use cache

**Covers**: G2, INV-2

### Test 26: Browser — mobile responsive at 375px

**Setup**: ESP32 with SD card. Browser connected to logger WiFi.

**Steps**:
1. Open browser DevTools
2. Set viewport to 375px width
3. Navigate to `http://<ip>/config`
4. Verify: no horizontal scrollbar, all form fields visible and tappable, nav bar wraps

**Expected**: Page usable at 375px without horizontal scroll

**Covers**: G6, Static AC3 (assets)

### Test 27: Browser — SD card absent (graceful degradation)

**Setup**: ESP32 without SD card. Browser connected to logger WiFi.

**Steps**:
1. Navigate to `http://<ip>/config`
2. Verify: page loads with browser default styles (unstyled), forms are visible and functional
3. Fill form, click Save
4. Verify: form POSTs normally, page reloads (htmx not loaded)

**Expected**: Unstyled but functional page, forms work via normal POST

**Covers**: HtmlUtil AC6, INV-1

### Test 28: Memory envelope — heap usage

**Setup**: ESP32 with SD card. Serial monitor connected.

**Steps**:
1. Note `ESP.getFreeHeap()` value (baseline)
2. Load `/config` in browser
3. Note `ESP.getFreeHeap()` value (after)
4. Compare delta

**Expected**: Delta within ±2 KB of baseline

**Covers**: G4, INV-3

---

## 7. Code Path Trace

### Path 1: Static asset request

```
Browser
  → GET /static/htmx.min.js?v=0.4.1
  → WebServerManager::setupRoutes() [registers /static/* handler]
  → Routes_Static::registerStaticRoutes() [T04]
  → extractStaticFilename_() [strips /static/, strips ?v=, validates no ../\]
  → SD_MMC.cardType() [check mounted]
  → SD_MMC.open("/www/htmx.min.js") [check exists]
  → contentTypeFor_() [.js → application/javascript]
  → HttpFileSender::sendSdFile() [Range support, 2 KB chunked streaming]
  → Cache-Control: max-age=31536000 header
  → Browser (cached)
```

**Verification status**: Path 1 is verified by unit tests (T02: `test_routes_static.cpp`) for path validation, content types, cache headers, and SD card absent. Range support (AC7) requires integration test on hardware.

### Path 2: Config page htmx fragment response

```
Browser (htmx)
  → POST /config [HX-Request: true header]
  → WebServer collects HX-Request header [T04: add to kHeaderKeys if needed]
  → Routes_Config POST /config handler [T05]
  → HtmlUtil::isHtmxRequest(srv) [T03: checks HX-Request: true]
  → ConfigManager::save(tmp) [persist config]
  → HttpFileSender::sendText(srv, 200, "text/html",
      "<div class='alert-ok'>Configuration saved.</div>", "no-store")
  → Browser (htmx swaps into #save-result)
```

**Verification status**: Path 2 is verified by unit tests (T03: `isHtmxRequest`, `htmlFragment`) for the detection and fragment format. The full POST handler path requires integration test on hardware (T05).

### Path 3: Config page non-htmx full page response

```
Browser (no JS)
  → POST /config [no HX-Request header]
  → Routes_Config POST /config handler [T05]
  → HtmlUtil::isHtmxRequest(srv) → false [T03]
  → ConfigManager::save(tmp) [persist config]
  → srv.sendHeader("Location", "/config?ok=1&tab=globals")
  → srv.send(303, ...) [current behavior unchanged]
  → Browser (full page reload)
```

**Verification status**: Path 3 is verified by integration test (T05: Config AC2). The non-htmx path is the existing behavior and must not change.

### Path 4: Config page lock (htmx — 200 with warn fragment)

```
Browser (htmx)
  → POST /config [HX-Request: true header]
  → Routes_Config POST /config handler [T05]
  → rejectConfigEditLocked_(srv) [T05: modified for htmx]
  → isHtmxRequest(srv) → true
  → HttpFileSender::sendText(srv, 200, "text/html",
      "<div class='alert-warn'>Configuration is locked while logging is active.</div>",
      "no-store")
  → Browser (htmx swaps warn fragment into #save-result)
```

**Verification status**: Path 4 is verified by integration test (T05: Config AC4, E2). The `rejectConfigEditLocked_` function must be modified to check `isHtmxRequest` and return an HTML fragment instead of plain text.

### Path 5: Files page htmx delete with HX-Redirect

```
Browser (htmx)
  → GET /delete?path=/file.csv [HX-Request: true header]
  → Routes_Files GET /delete handler [T07]
  → rejectManualFileMutation_(srv) [T07: modified for htmx]
    → if locked: isHtmxRequest → true → sendText(200, .alert-warn) → return
  → SD_MMC.exists(path) → true
  → SD_MMC.remove(path) → true
  → isHtmxRequest(srv) → true
  → srv.sendHeader("HX-Redirect", "/files?path=/")
  → HttpFileSender::sendText(srv, 200, "text/html",
      "<div class='alert-ok'>Deleted.</div>", "no-store")
  → Browser (htmx follows HX-Redirect, reloads /files)
```

**Verification status**: Path 5 is verified by integration test (T07: Files AC3, AC5, E6, E8). The `rejectManualFileMutation_` function must be modified to check `isHtmxRequest`.

### Path 6: Sensor page htmx save

```
Browser (htmx)
  → POST /config/sensors [HX-Request: true header, sensor field data]
  → Routes_Config POST /config/sensors handler [T06]
  → rejectConfigEditLocked_(srv) [T06: same htmx modification as T05]
  → Process sensor fields (same as current)
  → ConfigManager::save(tmp)
  → isHtmxRequest(srv) → true
  → HttpFileSender::sendText(srv, 200, "text/html",
      "<div class='alert-ok'>Saved.</div>", "no-store")
  → Browser (htmx swaps into #sensor-result)
```

**Verification status**: Path 6 is verified by integration test (T06: Config AC13). The sensor POST handler must add `isHtmxRequest` checks at the save, add, and delete exit points.

### Path 7: Full page render (GET /config)

```
Browser
  → GET /config
  → Routes_Config GET /config handler [T05: modified]
  → HtmlUtil::htmlHeader("Config") [T03: modified]
    → <script src='/static/htmx.min.js?v=0.4.1' defer></script>
    → <link rel='stylesheet' href='/static/app.css?v=0.4.1'>
    → (no <style> block — CSS removed)
    → titlebar, netbar, topnav (unchanged)
  → Form tag with hx-post, hx-target, hx-swap, hx-sync [T05]
  → <div id="save-result"></div> [T05]
  → Submit button with htmx-indicator [T05]
  → HtmlUtil::htmlFooter()
  → HttpFileSender::sendText(srv, 200, "text/html", html, "no-store")
  → Browser
```

**Verification status**: Path 7 is verified by unit tests (T03: `htmlHeader` output) and code review (T05: form attributes, save-result div, htmx-indicator). Full page rendering requires integration test on hardware.

---

## 8. Migration & Compatibility

### Breaking Change Assessment

| Change | Impact | Severity | Mitigation | Verified by |
|--------|--------|----------|------------|-------------|
| Inline CSS removed from `htmlHeader()` | Pages unstyled if SD card absent or `/www/app.css` missing | Medium | Forms remain functional with browser default styles (INV-1). User can still read labels, fill fields, submit. | HtmlUtil AC6, Integration Test 27 |
| `htmlHeader()` output structure changes | Any code that parses `htmlHeader()` output by string matching may break | Low | No code in the firmware parses `htmlHeader()` output — it is sent directly to the browser. | Code review: grep for `htmlHeader` usage |
| `rejectConfigEditLocked_()` returns HTML for htmx requests | Callers that check response body format may break | Low | Only the POST handlers call `rejectConfigEditLocked_()`, and they `return` immediately after. No body parsing. | Code review: `Routes_Config.cpp` |
| `rejectManualFileMutation_()` returns HTML for htmx requests | Same as above | Low | Same — callers return immediately. | Code review: `Routes_Files.cpp` |

### Legacy Compatibility

| Behavior | Before | After | Compatible? | Verified by |
|----------|--------|-------|-------------|-------------|
| Form POST without JS | 303 redirect to full page | 303 redirect to full page (unchanged) | Yes | Config AC2, AC9; Integration Test 7, 14, 24 |
| Form POST with JS (htmx) | 303 redirect to full page | 200 with HTML fragment | Changed (enhanced) | Config AC1; Integration Test 6 |
| Static asset request | 404 (no `/static/*` route) | 200 with file from SD card | New route | Static AC1; Integration Test 1 |
| `/api/*` JSON endpoints | JSON responses | JSON responses (unchanged) | Yes | Code review: no changes to `Routes_Api.cpp` |
| `/download` file download | Direct file serve | Direct file serve (unchanged) | Yes | Files AC7; Integration Test 22 |
| `/upload` multipart upload | 303 redirect | 303 redirect (unchanged) | Yes | Files AC7; Integration Test 21 |
| `/download_zip` ZIP download | Binary response | Binary response (unchanged) | Yes | Code review: no changes to `/download_zip` handler |
| Config lock (423) | 423 plain text | 423 plain text (non-htmx) or 200 HTML fragment (htmx) | Yes (non-htmx unchanged) | Config AC4; Integration Test 9, 10 |
| File mutation lock (409) | 409 plain text | 409 plain text (non-htmx) or 200 HTML fragment (htmx) | Yes (non-htmx unchanged) | Files AC5; Integration Test 19 |

### Version Skew

| Scenario | Risk | Mitigation | Verified by |
|----------|------|------------|-------------|
| Browser caches `htmx.min.js?v=0.4.1` from old firmware | Low — old htmx still works | `?v=` query string changes on firmware update, forcing re-fetch | INV-2, Integration Test 25 |
| Browser caches `app.css?v=0.4.1` from old firmware | Low — old CSS still renders | Same `?v=` mechanism | INV-2 |
| SD card has old `app.css` after firmware update | Medium — new HTML structure may not match old CSS | `?v=` forces browser re-fetch, but SD card file must be manually updated | Manual: update `/www/app.css` on SD card when updating firmware |
| SD card has old `htmx.min.js` after firmware update | Low — htmx is stable | htmx v2.0.x API is stable; pin version on SD card | Manual: verify htmx version on SD card matches spec |

---

## 9. Edge Cases

| # | Scenario | Expected outcome | Covers |
|---|----------|------------------|--------|
| 1 | SD card absent — logger boots without SD card | `/static/*` returns 404. Browser receives 404 for `htmx.min.js` and `app.css`. htmx never initializes — forms submit as normal POSTs with full page reloads. No CSS loads — page renders with browser default styles (unstyled but functional). | INV-1, INV-2, HtmlUtil AC6, Integration Test 27 |
| 2 | htmx.js fails to load (corrupt file on SD card) | Browser console error. htmx never initializes. Forms degrade to normal POSTs with full page reloads. | INV-1 |
| 3 | Browser fires overlapping requests (user clicks Save twice quickly) | WebServer processes one request at a time. `hx-sync="this:replace"` on the form drops the in-flight request if a new one comes in. Only the latest request is sent. | INV-5, Config AC6 |
| 4 | Config lock activates during htmx request (logging starts while config page open) | POST `/config` with `HX-Request: true` receives 200 with `.alert-warn` fragment. htmx swaps the warn fragment into `#save-result`. Non-htmx request receives 423 plain text. | INV-4, Config AC4, E2 |
| 5 | Fragment response too large (sensor editor with many fields) | Sensor editor save returns only `<div class='alert-ok'>Saved.</div>` (~40 bytes) — the form itself is not re-rendered. Fragment responses use 2 KB chunked streaming via `HttpFileSender::sendText()`. | INV-3 |
| 6 | Path traversal attempt on `/static/*` (`/static/../etc/passwd`) | `extractStaticFilename_()` rejects `..` after prefix strip, returns empty string. Route handler returns 404. | Static AC4, V2 |
| 7 | Subdirectory attempt on `/static/*` (`/static/subdir/file.js`) | `extractStaticFilename_()` rejects `/` after prefix strip, returns empty string. Route handler returns 404. | Static AC5, V3 |
| 8 | Backslash attempt on `/static/*` (`/static\..\file`) | `extractStaticFilename_()` rejects `\` after prefix strip, returns empty string. Route handler returns 404. | V4 |
| 9 | Empty filename on `/static/*` (`/static/`) | `extractStaticFilename_()` returns empty string. Route handler returns 404. | V5 |
| 10 | Query string on `/static/*` (`/static/htmx.min.js?v=0.4.1`) | `extractStaticFilename_()` strips everything after `?` before file lookup. File resolved as `htmx.min.js`. | Static AC6, V6 |
| 11 | Incognito mode (browser bypasses cache) | htmx.js re-read from SD card on every page load. 14 KB read is negligible compared to log file writes. Risk accepted per design doc. | Design doc: Unmitigated Risks |
| 12 | `HX-Request` header not collected by ESP32 WebServer | `srv.hasHeader("HX-Request")` returns false even when header is present. Fix: add `"HX-Request"` to `kHeaderKeys` array in `prepareServer_()`. Test early in Phase 1. | Plan rule 12, T04 |
| 13 | Firmware version changes (0.4.1 → 0.5.0) | `?v=0.5.0` in script/link tags. Browser fetches fresh `htmx.min.js?v=0.5.0` and `app.css?v=0.5.0` (different URL = cache miss). Old cached assets remain but are not requested. | INV-2, `test_htmlHeader_version_changes_with_firmware` |
| 14 | Apply Type button on sensor editor | Apply Type does NOT get `hx-*` attributes. It submits as a normal POST, causing a full page reload with rebuilt fields. This is intentional (resolved question 2). | Config AC12, Plan rule 16 |
| 15 | File delete via htmx — file table does not partially swap | `HX-Redirect` response header triggers full page reload of `/files`. File table is too complex for partial swap (resolved question 1). | Files AC3, Plan rule 15 |

---

## 10. Quality Gates

| Gate | Command | Expected |
|------|---------|----------|
| Build | `cd firmware && pio run -e thingplus_s3_usb_cdcserial_bodaqs_4f` | Exit 0, no errors |
| Tests | `cd firmware && make -C test test` | All 30 tests pass, exit 0 |
| Binary size (Phase 1) | Compare `.pio/build/thingplus_s3_usb_cdcserial_bodaqs_4f/firmware.bin` to baseline | Delta < 5 KB |
| Binary size (all phases) | Compare `.pio/build/thingplus_s3_usb_cdcserial_bodaqs_4f/firmware.bin` to baseline | Delta < 20 KB total |
| No test code in firmware | `grep -r "test/stubs" firmware/src/` | Zero matches |
| No `#ifdef TEST` in production | `grep -r "#ifdef TEST" firmware/src/` | Zero matches |
| No inline CSS in htmlHeader | `grep -c "<style>" firmware/src/HtmlUtil.cpp` | Zero matches |

---

## 11. Sign-Off

| Gate | Result | Date | Verifier |
|------|--------|------|----------|
| Acceptance criteria (45 ACs across 7 components) | ☐ Pass / ☐ Fail | | |
| Validation rules (13 rules) | ☐ Pass / ☐ Fail | | |
| Error specs (9 error specs) | ☐ Pass / ☐ Fail | | |
| Invariants & contracts (INV-1 through INV-5) | ☐ Pass / ☐ Fail | | |
| Success criteria (G1-G6, INV-4, INV-5, T1-T5) | ☐ Pass / ☐ Fail | | |
| Unit tests (30 tests across 3 files) | ☐ Pass / ☐ Fail | | |
| Build | ☐ Pass / ☐ Fail | | |
| Binary size (< 20 KB delta) | ☐ Pass / ☐ Fail | | |
| No test code in firmware | ☐ Pass / ☐ Fail | | |
| Integration tests (28 tests on ESP32 hardware) | ☐ Pass / ☐ Fail / ☐ N/A | | |
| Migration compatibility | ☐ Pass / ☐ Fail / ☐ N/A | | |
| Edge cases (15 scenarios) | ☐ Pass / ☐ Fail | | |

---

## Coverage Summary

| Category | Total | Covered | Gaps |
|----------|-------|---------|------|
| Acceptance Criteria | 45 | 45 | 0 |
| Validation Rules | 13 | 13 | 0 |
| Error Specs | 9 | 9 | 0 |
| Invariants & Contracts | 5 | 5 | 0 |
| Success Criteria | 13 | 13 | 0 |
| Unit Tests | 32 | 32 | 0 |
| Integration Tests | 28 | 28 | 0 |
| Edge Cases | 15 | 15 | 0 |
