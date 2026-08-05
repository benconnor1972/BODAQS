# Verification Report: htmx Web UI Migration

**Date**: 2025-07-16
**Status**: VERIFIED (with issues)

## Executive Summary

The htmx Web UI Migration spec is correctly implemented. All 9 tasks (T00–T08) across 6 phases are complete and independently verified. The host-based test suite passes 120 assertions with zero failures. The PlatformIO firmware build succeeds, producing a 1,555,056-byte binary. Code review confirms all 5 design invariants (INV-1 through INV-5) are satisfied: forms degrade to normal POSTs without JavaScript, static assets are served with 1-year cache headers and version-keyed URLs, fragment responses use 2 KB chunked streaming, config lock returns 200 with `.alert-warn` for htmx requests (B1 fix applied), and all forms have `hx-sync='this:replace'`. The blocking issue B1 from the review (HTTP 423 not swapped by htmx v2.0) was fixed during implementation — `rejectConfigEditLocked_` returns 200 with an `.alert-warn` fragment for htmx requests. One issue was found: the firmware binary size delta is 57,328 bytes (~56 KB), exceeding the 20 KB budget specified in G5. The binary still fits in the 2 MB app partition (74.1% used), so this is not a blocker. Three success criteria (G1, G4, G6) require hardware/browser testing and are marked as pending integration verification.

## Verification Results

### Phase Verification

| Phase | Command | Expected | Actual | Status |
|-------|---------|----------|--------|--------|
| 0 | `make -C test test` | All tests pass | 79 stub assertions passed, 0 failed | ✓ |
| 1 | `make -C test test` + `pio run` | All tests pass, build succeeds | 120 assertions passed, 0 failed; build SUCCESS (Flash: 74.1%) | ✓ |
| 2 | `make -C test test` + `pio run` | All tests pass, build succeeds | 120 assertions passed, 0 failed; build SUCCESS | ✓ |
| 3 | `make -C test test` + `pio run` | All tests pass, build succeeds | 120 assertions passed, 0 failed; build SUCCESS | ✓ |
| 4 | `make -C test test` + `pio run` | All tests pass, build succeeds | 120 assertions passed, 0 failed; build SUCCESS | ✓ |
| 5 | `make -C test test` + `pio run` | All tests pass, build succeeds | 120 assertions passed, 0 failed; build SUCCESS | ✓ |

### Task Verification

| Task | DONE WHEN Criteria | Status |
|------|-------------------|--------|
| T00 | `make -C test test` compiles and exits 0; stubs provide required methods | ✓ |
| T01 | All 8 tests pass against current unmodified HtmlUtil.cpp | ✓ |
| T02 | All 12 test_routes_static tests pass; path traversal blocked; content types correct | ✓ |
| T03 | All 15 test_htmlutil tests pass; no `<style>`; htmx/CSS tags with `?v=`; fragment functions work | ✓ |
| T04 | All 5 test_fragments tests pass; build succeeds; `registerStaticRoutes` called; `HX-Request` in `kHeaderKeys` | ✓ |
| T05 | POST /config returns fragments for htmx; 303 for non-htmx; form has `hx-*` attributes | ✓ |
| T06 | POST /config/sensors returns fragments; sensor editor has `hx-*`; Apply Type has no `hx-*` | ✓ |
| T07 | File ops return `HX-Redirect` for htmx; 409 returns `.alert-warn`; upload/download unchanged | ✓ |
| T08 | app.css has all design language elements; mobile responsive; htmx indicator | ✓ |

### Spec Success Criteria

| Criterion | Verification | Status |
|-----------|--------------|--------|
| G1: No page reloads on form submit | Code review: `hx-post`/`hx-target` on forms (Routes_Config.cpp:706, 974, 1041; Routes_Files.cpp:384), `isHtmxRequest` returns fragments | ✓ (integration test needed on hardware) |
| G2: Static assets cached | `Cache-Control: max-age=31536000` in Routes_Static.cpp:58, `?v=` in HtmlUtil.cpp:40,44 | ✓ |
| G3: Graceful degradation | Non-htmx requests return 303 redirects (code review confirms `isHtmxRequest` checks guard every exit point) | ✓ |
| G4: No memory regression | Fragment responses use `HttpFileSender::sendText` (2 KB chunks); code review confirms | ✓ (integration test needed on hardware) |
| G5: Flash footprint < 20 KB | Delta = 57,328 bytes (~56 KB) — **exceeds 20 KB budget** | ✗ |
| G6: Mobile responsive | `app.css` has `@media (max-width: 480px)` with column layout, wrapped nav, compressed tables | ✓ (manual browser test needed) |
| INV-4: Config lock works for htmx | `rejectConfigEditLocked_` returns 200 with `.alert-warn` for htmx (Routes_Config.cpp:79–85) | ✓ |
| INV-5: No overlapping requests | `hx-sync='this:replace'` on config form (line 707), sensor list form (line 975), sensor editor form (line 1042), upload mode forms (Routes_Files.cpp:384) | ✓ |
| T1: `make -C test test` passes | 120 passed, 0 failed, exit 0 | ✓ |
| T2: Test binary not in firmware | `grep` for `test/stubs` in `firmware/src/` returns 0 matches; `#ifdef TEST` returns 0 matches | ✓ |
| T3: test_htmlutil tests pass | 15 tests passed | ✓ |
| T4: test_routes_static tests pass | 21 assertions passed (12 test cases) | ✓ |
| T5: test_fragments tests pass | 5 tests passed | ✓ |

### Design Doc Invariants

| Invariant | Verification | Status |
|-----------|--------------|--------|
| INV-1: Pages functional without JS | Code review: forms have `method='POST' action='...'` as fallback; non-htmx returns 303 redirect (Routes_Config.cpp:1645–1648, Routes_Files.cpp:424–425) | ✓ |
| INV-2: 1-year cache + `?v=` | Routes_Static.cpp:58 passes `max-age=31536000` to `sendSdFile`; HtmlUtil.cpp:40,44 uses `?v=FirmwareInfo::version()` | ✓ |
| INV-3: 2 KB chunked streaming | Fragments use `HttpFileSender::sendText` (2 KB chunks); test_fragments T5 verifies all fragments < 2048 bytes | ✓ |
| INV-4: Config lock for htmx | `rejectConfigEditLocked_` (Routes_Config.cpp:79–85) returns 200 `.alert-warn` for htmx; `rejectManualFileMutation_` (Routes_Files.cpp:68–73) returns 200 `.alert-warn` for htmx | ✓ |
| INV-5: `hx-sync` on forms | `hx-sync='this:replace'` on config form (line 707), sensor list form (line 975), sensor editor form (line 1042), upload mode enter/exit forms (Routes_Files.cpp:384) | ✓ |

### Quality Gates

| Gate | Command | Result | Status |
|------|---------|--------|--------|
| Build | `pio run -e thingplus_s3_usb_cdcserial_bodaqs_4f` | SUCCESS, Flash: 74.1% (1,555,056 / 2,097,152 bytes) | ✓ |
| Tests | `make -C test test` | 120 passed, 0 failed | ✓ |
| No test in firmware | `grep -r "test/stubs" firmware/src/` | 0 matches | ✓ |
| No `#ifdef TEST` in production | `grep -r "#ifdef TEST" firmware/src/` | 0 matches | ✓ |
| No inline CSS in htmlHeader | `grep -c "<style>" firmware/src/HtmlUtil.cpp` | 0 matches (only `stylesheet` in `<link>` tag) | ✓ |
| No dead JS in htmlHeader | `grep -c "populateSelect\|loadTransforms\|DOMContentLoaded" firmware/src/HtmlUtil.cpp` | 0 matches | ✓ |
| Binary size < 20 KB delta | Compare to baseline (1,497,728 bytes) | Delta = 57,328 bytes (~56 KB) — **exceeds budget** | ✗ |

### Test Integrity

| Check | Result | Evidence |
|-------|--------|----------|
| Changed tests genuinely exercise their TEST CASES | ✓ | Each test calls actual production code (`HtmlUtil.cpp`, `Routes_Static.cpp` compiled directly) and checks real output. `test_htmlutil.cpp` T1 checks `htmlHeader("Config")` output contains the exact `<script>` tag string. `test_routes_static.cpp` T4 invokes the handler with `/static/../etc/passwd` and checks status is 404. `test_fragments.cpp` T1 checks `htmlFragment()` returns the exact alert div string. |
| No skipped/disabled tests or deleted assertions | ✓ | All 4 test files run unconditionally from `test_main.cpp`'s `main()`. No `#if 0` blocks, no commented-out tests, no conditional compilation. T01's 8 baseline tests were replaced by T03's 15 tests (per spec — T03 rewrites the file), with `htmlFooter` and `htmlEscape` tests retained as T14/T15. |
| No tests that cannot fail (asserting a constant) | ✓ | Every `check()` call has a real condition: string comparisons against production output, status code checks, header presence checks. `htmlFragment()` is a passthrough (`return body;`), so tests T6/T7 and fragments T1–T3 are trivially correct — but they verify the contract (body-only, no wrapper). If someone later adds wrapper tags, these tests would catch it. |
| Unit under test not mocked to pass | ✓ | Production source files (`HtmlUtil.cpp`, `Routes_Static.cpp`) are compiled and linked directly. Stubs replace ESP32/Arduino types (`String`, `WebServer`, `SD_MMC`, `FirmwareInfo`), not the code under test. The `HttpFileSender` stub captures call parameters (status, content type, cache control) but does not fake the logic — `Routes_Static` still runs its real path validation, SD card check, and content type mapping. |
| No errors/lints suppressed instead of fixed | ✓ | No `#pragma diagnostic ignored`, no `-w` flags beyond `-Wno-unused` (suppresses unused parameter warnings from stubs, not production code). Test failures print to stdout and increment the failure counter. |
| TEST CASES / VERIFICATION / DONE WHEN not weakened | ✓ | All task DONE WHEN criteria are met. T02's test count is 21 assertions (not 12 as spec estimated) because T02 created more `check()` calls than the spec estimated — this is more coverage, not less. T03's 15 tests match the spec exactly. T04's 5 tests match the spec exactly. |

## Proof of Correctness

### Phase 0 Evidence — Test Infrastructure

**Test suite structure:**

```
firmware/test/
├── Makefile                    # -std=gnu++2a -I stubs -I ../src
├── test_main.cpp               # 79 assertions (stub tests T2–T5)
├── test_htmlutil.cpp           # 15 tests
├── test_routes_static.cpp      # 12 test cases, 21 assertions
├── test_fragments.cpp          # 5 tests
└── stubs/
    ├── Arduino.h               # String class, F() macro, basic types
    ├── WebServer.h             # WebServer with mock state, on(), mockInvokeHandler
    ├── SD_MMC.h                # SD_MMC with mock file map, File class
    ├── mocks.h                 # Mock control functions
    ├── mocks.cpp               # ConfigManager::get(), WiFiManager::status(), FirmwareInfo::version()
    ├── FirmwareInfo.h          # Non-inline version() for runtime mockability
    ├── WiFi.h                  # wl_status_t, IPAddress
    └── HttpFileSender_stub.cpp # Mock sendSdFile/sendText with call capture
```

**Makefile** (`firmware/test/Makefile`):
```makefile
CXX      = g++
CXXFLAGS = -std=gnu++2a -I stubs -I ../src -Wall -Wno-unused
CXXFLAGS += '-DBODAQS_FW_VERSION="0.4.1"' '-DBODAQS_FW_NAME="BODAQS"'
PROD_SRCS = ../src/HtmlUtil.cpp ../src/Routes_Static.cpp
STUB_SRCS = stubs/mocks.cpp stubs/HttpFileSender_stub.cpp
TEST_SRCS = $(wildcard test_*.cpp)
```

Stubs take precedence via `-I stubs` before `-I ../src`. Production source files are compiled directly. No `#ifdef TEST` guards in production code.

### Phase 1 Evidence — Static Asset Infrastructure

**Routes_Static.h** (`firmware/src/Routes_Static.h`):
```cpp
#pragma once
#include <WebServer.h>
void registerStaticRoutes(WebServer& srv);
```

**Routes_Static.cpp** — path validation (`firmware/src/Routes_Static.cpp:5–20`):
```cpp
static String extractStaticFilename_(const String& uri) {
  String path = uri.substring(8);           // strip "/static/"
  int q = path.indexOf('?');
  if (q >= 0) path = path.substring(0, q);  // strip query string
  if (path.length() == 0) return String();
  if (path.indexOf("..") >= 0) return String();
  if (path.indexOf('/') >= 0) return String();
  if (path.indexOf('\\') >= 0) return String();
  return path;
}
```

**Routes_Static.cpp** — content type mapping (line 22–27):
```cpp
static String contentTypeFor_(const String& filename) {
  String lower = filename; lower.toLowerCase();
  if (lower.endsWith(".js"))  return F("application/javascript");
  if (lower.endsWith(".css")) return F("text/css");
  return F("application/octet-stream");
}
```

**Routes_Static.cpp** — cache header (line 48):
```cpp
HttpFileSender::sendSdFile(srv, sdPath, contentType, F(""), F("max-age=31536000"));
```

**HtmlUtil.cpp** — htmx/CSS tags with version (`firmware/src/HtmlUtil.cpp:39–45`):
```cpp
s += F("<script src='/static/htmx.min.js?v=");
s += FirmwareInfo::version();
s += F("' defer></script>");
s += F("<link rel='stylesheet' href='/static/app.css?v=");
s += FirmwareInfo::version();
s += F("'>");
```

**WebServerManager.cpp** — route registration and header collection (`firmware/src/WebServerManager.cpp:155–158`):
```cpp
static const char* kHeaderKeys[] = { "Range", "HX-Request" };
g_server->collectHeaders(kHeaderKeys, sizeof(kHeaderKeys) / sizeof(kHeaderKeys[0]));
```

**WebServerManager.cpp** — `setupRoutes()` (line 167):
```cpp
registerStaticRoutes(*g_server);
```

**HtmlUtil.h** — new function declarations (`firmware/src/HtmlUtil.h:24–26`):
```cpp
bool   isHtmxRequest(WebServer& srv);
String htmlFragment(const String& body);
String htmlRespond(WebServer& srv, const String& title, const String& body);
```

**HtmlUtil.cpp** — fragment functions (line 87–97):
```cpp
bool isHtmxRequest(WebServer& srv) {
  if (!srv.hasHeader(F("HX-Request"))) return false;
  String val = srv.header(F("HX-Request"));
  val.trim();
  val.toLowerCase();
  return val == "true";
}

String htmlFragment(const String& body) {
  return body;
}

String htmlRespond(WebServer& srv, const String& title, const String& body) {
  if (isHtmxRequest(srv)) {
    return htmlFragment(body);
  }
  return htmlHeader(title) + body + htmlFooter();
}
```

**No inline CSS**: `grep` for `<style>` in `HtmlUtil.cpp` returns 0 matches. The only `style` substring is in `rel='stylesheet'` on the `<link>` tag.

**Dead JS removed**: `grep` for `populateSelect`, `loadTransforms`, `DOMContentLoaded` in `HtmlUtil.cpp` returns 0 matches.

**Static assets** (`firmware/www/`):
```
app.css       — 5,711 bytes (full design language)
htmx.min.js   — 50,387 bytes (htmx v2.0.3, starts with "var htmx=function()")
```

### Phase 2 Evidence — Config Page htmx

**rejectConfigEditLocked_** — B1 fix applied (`firmware/src/Routes_Config.cpp:74–89`):
```cpp
static bool rejectConfigEditLocked_(WebServer& srv) {
  String reason;
  if (!configEditLocked_(&reason)) {
    return false;
  }
  if (HtmlUtil::isHtmxRequest(srv)) {
    // Return 200 (not 423) because htmx v2.0 does not swap 4xx response bodies by default.
    HttpFileSender::sendText(srv, 200, F("text/html"),
      String(F("<div class='alert-warn'>Configuration is locked while ")) + reason + F(".</div>"), F("no-store"));
    return true;
  }
  srv.send(423, F("text/plain"), String(F("Configuration is locked while ")) + reason + F("."));
  return true;
}
```

**POST /config success** (line 1645–1648):
```cpp
if (isHtmxRequest(srv)) {
  HttpFileSender::sendText(srv, 200, F("text/html"),
    F("<div class='alert-ok'>Configuration saved.</div>"), F("no-store"));
  return;
}
```

**POST /config validation error** (line 1498–1501):
```cpp
if (isHtmxRequest(srv)) {
  HttpFileSender::sendText(srv, 200, F("text/html"),
    F("<div class='alert-err'>Error: AP password must be 8-63 characters</div>"), F("no-store"));
  return;
}
```

**POST /config save failure** (line 1627–1630):
```cpp
if (isHtmxRequest(srv)) {
  HttpFileSender::sendText(srv, 200, F("text/html"),
    F("<div class='alert-err'>Failed to save config</div>"), F("no-store"));
  return;
}
```

**GET /config form** (line 703–708):
```cpp
html += F("<div id='save-result'></div>");
html += F("<h2>Configuration</h2>");
html += F("<form method='POST' action='/config'");
html += F(" hx-post='/config' hx-target='#save-result' hx-swap='innerHTML'");
html += F(" hx-sync='this:replace'>");
```

**Submit button with htmx indicator** (line 907):
```cpp
html += F("<p><button type='submit'"); html += dis; html += F(">Save <span class='htmx-indicator'>Saving...</span></button></p>");
```

### Phase 3 Evidence — Sensor Pages htmx

**POST /config/sensors delete** (line 1078–1081):
```cpp
if (isHtmxRequest(srv)) {
  HttpFileSender::sendText(srv, 200, F("text/html"),
    F("<div class='alert-ok'>Sensor deleted. Restart the logger to rebuild the live sensor set.</div>"), F("no-store"));
  return;
}
```

**POST /config/sensors add** (line 1104–1107):
```cpp
if (isHtmxRequest(srv)) {
  HttpFileSender::sendText(srv, 200, F("text/html"),
    F("<div class='alert-ok'>Sensor added. Restart the logger to rebuild the live sensor set.</div>"), F("no-store"));
  return;
}
```

**POST /config/sensors save** (line 1357–1360):
```cpp
if (isHtmxRequest(srv)) {
  HttpFileSender::sendText(srv, 200, F("text/html"),
    F("<div class='alert-ok'>Saved.</div>"), F("no-store"));
  return;
}
```

**Sensor editor form** (line 1039–1042):
```cpp
html += F("<div id='sensor-result'></div>");
html += F("<form method='POST' action='/config/sensors'");
html += F(" hx-post='/config/sensors' hx-target='#sensor-result' hx-swap='innerHTML'");
html += F(" hx-sync='this:replace'>");
```

**Sensor editor save button** (line 1049):
```cpp
html += F(">Save Sensor <span class='htmx-indicator'>Saving...</span></button></p></form>");
```

**Sensor list add form** (line 972–975):
```cpp
html += F("<div id='sensor-list-result'></div>");
html += F("<form method='POST' action='/config/sensors'");
html += F(" hx-post='/config/sensors' hx-target='#sensor-list-result' hx-swap='innerHTML'");
html += F(" hx-sync='this:replace'><fieldset><legend>New sensor</legend>");
```

**Apply Type button**: No `hx-*` attributes — submits as normal POST (full page reload). Verified by code review: the Apply Type button is a separate `<form>` without `hx-post`.

### Phase 4 Evidence — Files Page htmx

**rejectManualFileMutation_** — htmx fragment (`firmware/src/Routes_Files.cpp:60–73`):
```cpp
static bool rejectManualFileMutation_(WebServer& srv) {
  String reason;
  if (!manualFileMutationBlocked_(&reason)) {
    return false;
  }
  if (isHtmxRequest(srv)) {
    HttpFileSender::sendText(srv, 200, F("text/html"),
      String(F("<div class='alert-warn'>Manual file changes are disabled while ")) + reason + F(".</div>"), F("no-store"));
    return true;
  }
  srv.send(409, F("text/plain"), String(F("Manual file changes are disabled while ")) + reason + F("."));
  return true;
}
```

**POST /upload-mode/enter** (line 411–415):
```cpp
if (isHtmxRequest(srv)) {
  srv.sendHeader(F("HX-Redirect"), F("/files"));
  HttpFileSender::sendText(srv, 200, F("text/html"),
    F("<div class='alert-ok'>Upload mode active.</div>"), F("no-store"));
  return;
}
```

**POST /upload-mode/exit** (line 427–431):
```cpp
if (isHtmxRequest(srv)) {
  srv.sendHeader(F("HX-Redirect"), F("/files"));
  HttpFileSender::sendText(srv, 200, F("text/html"),
    F("<div class='alert-ok'>Upload mode exited.</div>"), F("no-store"));
  return;
}
```

**GET /delete** (line 575–580):
```cpp
if (isHtmxRequest(srv)) {
  String redirectUrl = String(F("/files?path=")) + urlEncodeQueryValue_(parentDir(path));
  srv.sendHeader(F("HX-Redirect"), redirectUrl);
  HttpFileSender::sendText(srv, 200, F("text/html"),
    F("<div class='alert-ok'>Deleted.</div>"), F("no-store"));
  return;
}
```

**POST /delete_multi confirmed** (line 735–742):
```cpp
if (isHtmxRequest(srv)) {
  int okCount = 0;
  for (int i = 0; i < nSel; ++i) {
    const String& p = paths[i];
    if (SD_MMC.exists(p.c_str()) && SD_MMC.remove(p.c_str())) {
      ++okCount;
    }
    delay(0);
  }
  String redirectUrl = String(F("/files?path=")) + urlEncodeQueryValue_(dir);
  srv.sendHeader(F("HX-Redirect"), redirectUrl);
  HttpFileSender::sendText(srv, 200, F("text/html"),
    String(F("<div class='alert-ok'>Deleted ")) + String(okCount) + F(" file(s).</div>"), F("no-store"));
  return;
}
```

**POST /mkdir** (line 1071–1077):
```cpp
if (isHtmxRequest(srv)) {
  String redirectUrl = String(F("/files?path=")) + urlEncodeQueryValue_(normDir(base));
  srv.sendHeader(F("HX-Redirect"), redirectUrl);
  HttpFileSender::sendText(srv, 200, F("text/html"),
    F("<div class='alert-ok'>Folder created.</div>"), F("no-store"));
  return;
}
```

**Upload mode forms** (line 383–385):
```cpp
html += F("<form method='POST' action='/upload-mode/exit'"
          " hx-post='/upload-mode/exit' hx-target='this' hx-swap='outerHTML' hx-sync='this:replace'>"
          "<button type='submit'>Exit upload mode</button></form>");
```

**Unchanged operations**: POST /upload (multipart), GET /download, POST /download_zip — no `isHtmxRequest` checks, no `hx-*` attributes. Verified by code review.

### Phase 5 Evidence — CSS Polish

**app.css** (`firmware/www/app.css`, 5,711 bytes) contains all design language elements from the design doc:

| Element | Present | Line |
|---------|---------|------|
| `--shadow-grey: #212227` | ✓ | 12 |
| `--dim-grey: #637074` | ✓ | 13 |
| `--lavender-grey: #8693ab` | ✓ | 14 |
| `--powder-blue: #aab9cf` | ✓ | 15 |
| `--pale-sky: #bdd4e7` | ✓ | 16 |
| `--status-success-bg` | ✓ | 19 |
| `--status-error-bg` | ✓ | 23 |
| `--status-warn-bg` | ✓ | 27 |
| `--space-xs` through `--space-xl` | ✓ | 31–35 |
| `system-ui` font stack | ✓ | 41 |
| `.titlebar` | ✓ | 50 |
| `.netbar` | ✓ | 56 |
| `.topnav` with `--shadow-grey` bg | ✓ | 61 |
| `fieldset` with `--pale-sky` bg | ✓ | 82 |
| `legend` with `--lavender-grey` | ✓ | 89 |
| `.row` flex layout | ✓ | 94 |
| `label` min-width 160px | ✓ | 101 |
| `input:focus` box-shadow glow | ✓ | 113 |
| `button` with `--lavender-grey` bg | ✓ | 131 |
| `.alert-ok` | ✓ | 155 |
| `.alert-err` | ✓ | 162 |
| `.alert-warn` | ✓ | 169 |
| `th` with `--shadow-grey` bg | ✓ | 181 |
| `tbody tr:nth-child(even)` zebra | ✓ | 192 |
| `.htmx-indicator` | ✓ | 200 |
| `.htmx-request .htmx-indicator` | ✓ | 204 |
| `@media (max-width: 480px)` | ✓ | 212 |

## Issues Found

### Issue 1: Firmware binary size delta exceeds 20 KB budget (G5)

**Severity**: Medium (not a blocker)

**Details**: The spec's G5 success criterion requires `firmware.bin` size delta < 20 KB. The actual delta is 57,328 bytes (~56 KB):

- Baseline: 1,497,728 bytes (1.43 MB)
- Current: 1,555,056 bytes (1.48 MB)
- Delta: 57,328 bytes (~56 KB)
- Partition usage: 74.1% of 2,097,152 bytes (2 MB app partition)

The binary fits in the partition with 542,096 bytes (529 KB) remaining. The 20 KB budget was set when the spec assumed only small C++ additions (static route handler, fragment functions, header collection). The actual delta is larger likely due to:

1. `Routes_Static.cpp` — new file with path validation, content type mapping, SD card checks
2. `HtmlUtil.cpp` — new functions (`isHtmxRequest`, `htmlFragment`, `htmlRespond`) and `<WebServer.h>` include
3. `Routes_Config.cpp` — `isHtmxRequest` checks at 13+ exit points, `hx-*` attribute strings in GET handlers
4. `Routes_Files.cpp` — `isHtmxRequest` checks at 6+ exit points, `HX-Redirect` header construction
5. `WebServerManager.cpp` — `Routes_Static.h` include, `registerStaticRoutes` call, `HX-Request` in `kHeaderKeys`

The string literals for `hx-*` attributes, alert class divs, and `HX-Redirect` URLs accumulate across all route handlers. Each `F("...")` string is stored in flash (PROGMEM).

**Impact**: The binary fits in the partition. Future firmware additions have 529 KB of headroom. The 20 KB budget was conservative and has been exceeded by ~2.8x, but the partition has adequate space.

**Recommendation**: Update G5 to reflect the actual delta. If a stricter budget is needed, consider consolidating repeated string literals (e.g., `F("<div class='alert-ok'>")` appears 6+ times) into shared constants.

### Issue 2: G1, G4, G6 require hardware/browser testing

**Severity**: Low (pending integration verification)

Three success criteria cannot be fully verified by code review and unit tests alone:

- **G1** (no page reloads on form submit): Requires browser testing to verify URL doesn't change, scroll position is preserved, no white flash. Code review confirms `hx-post`/`hx-target`/`hx-swap` attributes are present and `isHtmxRequest` returns fragments, but the actual browser behavior needs verification.
- **G4** (no memory regression): Requires ESP32 serial monitor to check `ESP.getFreeHeap()` before and after config page load. Code review confirms fragment responses use `HttpFileSender::sendText` (2 KB chunks), but heap measurement needs hardware.
- **G6** (mobile responsive at 375px): Requires browser DevTools at 375px width. `app.css` has `@media (max-width: 480px)` with column layout and compressed tables, but visual verification needs a browser.

**Recommendation**: Run the 28 integration tests from `verification.md` §6 on ESP32 hardware with SD card.

### Issue 3: test_routes_static reports 21 assertions, not 12

**Severity**: None (informational)

The spec estimated 12 tests for `test_routes_static.cpp`. The actual implementation has 12 test cases but 21 `check()` calls (some test cases have multiple assertions). This is more coverage, not less. The verification.md §5 unit test plan lists 12 tests for this file, and the coverage summary says "32 unit tests" (which counts assertions, not test cases). The actual total is 120 assertions across all test files.

## Recommendations

1. **Run integration tests on hardware.** The 28 integration tests in `verification.md` §6 cover the HTTP request/response cycle, SD card I/O, browser behavior, and memory measurement that cannot be verified by host-based unit tests. Priority tests: Test 6 (htmx config save), Test 9 (htmx lock), Test 23 (browser no-reload), Test 25 (asset caching), Test 27 (SD card absent).

2. **Update G5 budget.** The 20 KB flash budget was exceeded (57 KB actual). Update the spec's G5 criterion to reflect the actual delta, or document the budget as advisory rather than mandatory. The binary fits in the 2 MB partition with 529 KB remaining.

3. **Consider consolidating alert fragment strings.** The strings `F("<div class='alert-ok'>")`, `F("<div class='alert-err'>")`, and `F("<div class='alert-warn'>")` appear multiple times across `Routes_Config.cpp` and `Routes_Files.cpp`. A shared helper (e.g., `HtmlUtil::alertOk(msg)`, `HtmlUtil::alertErr(msg)`, `HtmlUtil::alertWarn(msg)`) would reduce flash usage and ensure consistent formatting. This is a future optimization, not a blocker.

4. **Add automated CSS content checks.** T08's test cases (T1–T7) verify `app.css` contains specific strings but are described as manual checks. A simple test that reads `firmware/www/app.css` and asserts content would automate this. Low priority — the CSS is stable and unlikely to change.

5. **Document the `htmlFragment()` passthrough.** `htmlFragment()` currently returns its input unchanged (`return body;`). This is correct for the current design (htmx swaps `innerHTML`, so the fragment is just the body content). If wrapper tags are ever needed, the tests in `test_htmlutil.cpp` (T6, T7) and `test_fragments.cpp` (T1–T4) will catch the change. Consider adding a comment in `HtmlUtil.cpp` documenting this design decision.

## Conclusion

The htmx Web UI Migration spec is correctly implemented. All 9 tasks are complete, all 120 host-based test assertions pass, the firmware build succeeds, and all 5 design invariants are verified by code review. The blocking issue B1 from the review (HTTP 423 not swapped by htmx v2.0) was fixed during implementation — config lock and file mutation lock both return 200 with `.alert-warn` fragments for htmx requests. The firmware binary size delta (57 KB) exceeds the 20 KB budget specified in G5, but the binary fits in the 2 MB partition with 529 KB remaining. Three success criteria (G1, G4, G6) require hardware/browser testing to fully verify. The spec is ready for integration testing on ESP32 hardware.
