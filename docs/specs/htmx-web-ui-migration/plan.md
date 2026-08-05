# Implementation Plan: htmx Web UI Migration

**Spec**: `docs/specs/htmx-web-ui-migration/spec.md`
**Design Docs**: `docs/design/htmx-web-ui-migration.md`
**Created**: 2025-06-23
**Status**: Draft

## Quality Gates

Every task must pass these gates before the phase is considered complete. No phase
proceeds until the current phase passes all gates.

| Gate | Command | Expected |
|------|---------|----------|
| Build | `cd firmware && pio run -e thingplus_s3_usb_cdcserial_bodaqs_4f` | Exit 0, no errors |
| Test | `cd firmware && make -C test test` | All tests pass, exit 0 |
| Binary size | Compare `.pio/build/thingplus_s3_usb_cdcserial_bodaqs_4f/firmware.bin` to baseline | Delta < 20 KB total across all phases; < 5 KB for Phase 1 |
| No test code in firmware | `grep -r "test/stubs" firmware/src/` returns no matches; no `#ifdef TEST` in `firmware/src/` | Zero matches |

The baseline `firmware.bin` is the build output before any changes in this spec.
Record its size before starting Phase 1.

## Rules for Implementation

1. **Never skip a phase.** Phases are ordered by dependency. Phase 0 (test
   infrastructure) must complete before any production code changes.
2. **Never proceed to the next phase until the current phase passes all quality
   gates.** Run build + test + size check after every task, not just at phase end.
3. **Never weaken or skip tests to make them pass.** If a test fails, fix the
   code, not the test. Tests encode the spec's acceptance criteria.
4. **All forms must work without JavaScript (INV-1).** Every `hx-post` form must
   also function as a normal POST. The server returns a full page when
   `HX-Request` header is absent. Verify by disabling JS in the browser.
5. **Fragment responses must use 2 KB chunked streaming (INV-3).** Use
   `HttpFileSender::sendText()` or `ChunkedHtmlResponse` — never buffer a full
   response body in heap.
6. **Config lock must work for htmx requests (INV-4).** When
   `configEditLocked_()` returns true, htmx requests receive 200 with an
   `.alert-warn` fragment (htmx v2.0 does not swap 4xx bodies by default);
   non-htmx requests receive 423 with plain text (current behavior).
7. **All forms must have `hx-sync="this:replace"` (INV-5).** This prevents
   overlapping requests on the single-threaded ESP32 WebServer.
8. **Static assets must include `?v=<FirmwareInfo::version()>` in URLs and
   `Cache-Control: max-age=31536000` in responses (INV-2).** The version string
   comes from `FirmwareInfo::version()` (returns `BODAQS_FW_VERSION` macro,
   currently `"0.4.1"`).
9. **Test code must NOT be in the firmware binary.** Tests live in
   `firmware/test/` only. PlatformIO compiles only `firmware/src/`. No
   `#ifdef TEST` guards in production code — the separation is purely at the
   build system level.
10. **No new JSON APIs.** htmx consumes HTML fragments. The existing `/api/*`
    endpoints are unchanged.
11. **No build step for static assets.** `htmx.min.js` is used as-is from the
    upstream distribution. `app.css` is hand-written CSS, not preprocessed.
12. **`HX-Request` header collection:** The ESP32 WebServer's
    `collectHeaders()` call in `WebServerManager::prepareServer_()` currently
    collects only `Range`. `hasHeader("HX-Request")` will return false at
    runtime unless `"HX-Request"` is added to the `kHeaderKeys` array. Add it
    unconditionally in Phase 1 (T04).
13. **Path traversal protection on `/static/*`:** Reject any filename containing
    `..`, `/`, or `\` after the `/static/` prefix strip. Return 404.
14. **Fragment format:** Success fragments are
    `<div class='alert-ok'>Configuration saved.</div>`. Error fragments are
    `<div class='alert-err'>Error: <message></div>`. Warning (lock) fragments
    are `<div class='alert-warn'>Configuration is locked while <reason>.</div>`.
    No `<html>`, `<head>`, `<body>`, `<script>`, or `<link>` tags in fragments.
15. **Files page uses `HX-Redirect` for state-changing operations (resolved
    question 1).** File delete, upload mode toggle, and mkdir return 200 with an
    `HX-Redirect` response header. htmx follows the redirect and reloads `/files`.
    No partial swap of the file table.
16. **Sensor "Apply Type" uses full page reload (resolved question 2).** Only
    "Save Sensor" uses htmx. Apply Type rebuilds the form structure and requires
    a full page reload.
17. **Single `#save-result` target for the config form (resolved question 3).**
    WiFi slot fieldsets are not individually swappable. One target div before the
    form receives success/error fragments.

## Code Placement Rules

| Code Type | Location | Notes |
|-----------|----------|-------|
| Production firmware source | `firmware/src/` | Compiled by PlatformIO for ESP32-S3 |
| New static asset route | `firmware/src/Routes_Static.cpp` / `Routes_Static.h` | Serves `/static/*` from SD card `/www/` |
| Modified route handlers | `firmware/src/Routes_Config.cpp`, `Routes_Files.cpp` | htmx fragment responses on POST |
| Modified HTML utilities | `firmware/src/HtmlUtil.cpp` / `HtmlUtil.h` | New functions: `isHtmxRequest`, `htmlFragment`, `htmlRespond`; CSS removal from `htmlHeader` |
| Modified server setup | `firmware/src/WebServerManager.cpp` | Add `registerStaticRoutes` call; possibly add `HX-Request` to `collectHeaders` |
| Host-based tests | `firmware/test/` | NOT compiled into firmware; built with host g++ via Makefile |
| Test stubs | `firmware/test/stubs/` | `Arduino.h`, `WebServer.h`, `SD_MMC.h`, `mocks.h` — minimal ESP32/Arduino type stubs |
| Test Makefile | `firmware/test/Makefile` | Compiles stubs + production source + test files with host g++ |
| Static assets | SD card `/www/htmx.min.js`, `/www/app.css` | Placed on SD card manually; not in firmware binary |
| Design artifacts | `docs/artifacts/htmx-web-ui-migration/` | Standalone HTML files for visual verification |

## Code Generation Steps

None. All code is hand-written C++, CSS, and JavaScript. No code generators,
scaffolding tools, or build steps beyond PlatformIO and the test Makefile.

## Phases

### Phase 0 — Test Infrastructure

**Purpose:** Set up the host-based test suite before any production code changes.
This ensures every subsequent phase can be verified by tests. The test suite
compiles production source files (`HtmlUtil.cpp`, later `Routes_Static.cpp`)
against stub headers that replace ESP32/Arduino types.

**Delivers:**
- `firmware/test/` directory with Makefile
- `firmware/test/stubs/Arduino.h` — `String` class, `F()` macro, basic types
- `firmware/test/stubs/WebServer.h` — `WebServer` with `hasHeader`/`header`/`arg`/`send`/mock state
- `firmware/test/stubs/SD_MMC.h` — `SD_MMC` with `cardType`/`open`/`exists`/mock file map
- `firmware/test/stubs/mocks.h` — `FirmwareInfo::version()`, `ConfigManager::get()`, `WiFiManager::status()` mocks
- `firmware/test/test_htmlutil.cpp` — initial tests against current (unmodified) `HtmlUtil`
- Tests pass against current `htmlHeader()` output (before CSS removal)

**Tasks:** T00, T01

---

### Phase 1 — Static Asset Infrastructure

**Purpose:** Serve `htmx.min.js` and `app.css` from the SD card with 1-year
cache headers. Modify `htmlHeader()` to include `<script>` and `<link>` tags
with `?v=<FirmwareInfo::version()>`. Remove all inline CSS from `htmlHeader()`.

**Delivers:**
- `firmware/src/Routes_Static.cpp` / `Routes_Static.h` — new static asset server
- `firmware/src/HtmlUtil.cpp` / `HtmlUtil.h` — `htmlHeader()` modified (CSS removed, htmx/CSS tags added); new `isHtmxRequest()`, `htmlFragment()`, `htmlRespond()` functions
- `firmware/src/WebServerManager.cpp` — `registerStaticRoutes(*g_server)` call added to `setupRoutes()`; `HX-Request` added to `collectHeaders` if needed
- `firmware/test/test_routes_static.cpp` — 12 tests for path validation, content types, cache headers, SD card absent
- `firmware/test/test_fragments.cpp` — 5 tests for fragment format, alert classes, size constraints
- `app.css` file (placed on SD card at `/www/app.css`)
- `htmx.min.js` file (placed on SD card at `/www/htmx.min.js`)

**Tasks:** T02, T03, T04
- `cd firmware && pio run -e thingplus_s3_usb_cdcserial_bodaqs_4f` — build succeeds
- `firmware.bin` size delta < 5 KB from baseline
- `htmlHeader("Config")` output contains `<script src='/static/htmx.min.js?v=0.4.1' defer></script>` and `<link rel='stylesheet' href='/static/app.css?v=0.4.1'>`
- `htmlHeader("Config")` output does NOT contain `<style>`
- GET `/static/htmx.min.js?v=0.4.1` returns 200 with `Content-Type: application/javascript` and `Cache-Control: max-age=31536000`
- GET `/static/../etc/passwd` returns 404 (path traversal blocked)

---

### Phase 2 — Config Page htmx

**Purpose:** Make the `/config` POST handler return HTML fragments when
`HX-Request: true` is present. Add `hx-*` attributes to the config form so htmx
swaps the response into a `#save-result` div. Non-htmx requests keep the current
303 redirect behavior.

**Delivers:**
- `firmware/src/Routes_Config.cpp` — POST `/config` handler modified: checks `isHtmxRequest()`, returns fragment on htmx, 303 redirect otherwise
- Config form tag gets `hx-post="/config"`, `hx-target="#save-result"`, `hx-swap="innerHTML"`, `hx-sync="this:replace"`
- `<div id="save-result"></div>` added before the form
- Submit button gets `<span class="htmx-indicator">Saving...</span>`
- Config lock (423) returns `.alert-warn` fragment for htmx requests
- Validation errors return `.alert-err` fragment for htmx requests
- Save failure returns `.alert-err` fragment for htmx requests
- `firmware/test/test_htmlutil.cpp` — updated with `htmlRespond` tests for fragment vs full page mode

**Tasks:** T05
- POST `/config` without `HX-Request` header returns 303 redirect to `/config?ok=1` (current behavior unchanged)
- POST `/config` with `HX-Request: true` while logging active returns 423 with `<div class='alert-warn'>` fragment
- POST `/config` with `HX-Request: true` and `wifi_ap_password` of 3 characters returns 200 with `<div class='alert-err'>` containing password length error
- `/config` GET page renders `<form>` with `hx-post="/config"`, `hx-target="#save-result"`, `hx-swap="innerHTML"`, `hx-sync="this:replace"`
- `/config` GET page renders `<div id="save-result"></div>` before the form
- `/config` GET page submit button contains `<span class="htmx-indicator">Saving...</span>`

---

### Phase 3 — Sensor Pages htmx

**Purpose:** Make the `/config/sensors` POST handler return fragments for sensor
save, add, and delete operations. The sensor editor form (`/config/sensor?id=N`)
gets `hx-*` attributes for the Save Sensor button. Apply Type remains a full
page reload (resolved question 2).

**Delivers:**
- `firmware/src/Routes_Config.cpp` — POST `/config/sensors` handler modified: returns fragments for save, add, delete when `HX-Request: true`
- Sensor editor form gets `hx-post="/config/sensors"`, `hx-target="#sensor-result"`, `hx-swap="innerHTML"`, `hx-sync="this:replace"`
- `<div id="sensor-result"></div>` added before the sensor editor form
- Delete sensor returns `<div class='alert-ok'>Sensor deleted. Restart the logger to rebuild the live sensor set.</div>` for htmx
- Add sensor returns `<div class='alert-ok'>Sensor added. Restart the logger to rebuild the live sensor set.</div>` for htmx
- Save sensor returns `<div class='alert-ok'>Saved.</div>` for htmx
- Apply Type button does NOT get `hx-*` attributes — it submits normally (full page reload)
- Config lock (423) returns `.alert-warn` fragment for htmx requests on sensor routes

**Tasks:** T06
- POST `/config/sensors` with `HX-Request: true` and `delete_sensor_idx` returns 200 with `<div class='alert-ok'>Sensor deleted.`
- POST `/config/sensors` with `HX-Request: true` and `add_sensor` returns 200 with `<div class='alert-ok'>Sensor added.`
- POST `/config/sensors` without `HX-Request` header returns 303 redirect (current behavior unchanged)
- `/config/sensor?id=N` GET page renders `<form>` with `hx-post="/config/sensors"`, `hx-target="#sensor-result"`, `hx-swap="innerHTML"`
- `/config/sensor?id=N` GET page renders `<div id="sensor-result"></div>` before the form
- Apply Type button does not have `hx-*` attributes (submits as normal POST)

---

### Phase 4 — Files Page htmx

**Purpose:** Make file operations on `/files` return htmx-compatible responses
using `HX-Redirect` for state changes. The file table is too complex for partial
swaps, so `HX-Redirect` triggers a full page reload after the operation completes.

**Delivers:**
- `firmware/src/Routes_Files.cpp` — POST `/upload-mode/enter`, POST `/upload-mode/exit`, GET `/delete`, POST `/delete_multi`, POST `/mkdir` modified: return 200 with `HX-Redirect` header when `HX-Request: true`
- Upload mode enter/exit forms get `hx-post` and `hx-target` attributes
- Delete links can use `hx-get` with `hx-target` (or remain as regular links — implementation choice per spec AC7)
- Mutation blocked (409) returns `.alert-warn` fragment for htmx requests
- File not found returns `.alert-err` fragment for htmx requests
- POST `/upload` (multipart) unchanged — always redirects
- GET `/download` unchanged — direct file download, no htmx
- POST `/download_zip` unchanged — binary response, no htmx

**Tasks:** T07
- POST `/upload-mode/enter` without `HX-Request` header returns 303 redirect to `/files` (current behavior)
- GET `/delete?path=/file.csv` with `HX-Request: true` returns 200 with `<div class='alert-ok'>Deleted.</div>` and `HX-Redirect: /files?path=/` response header
- GET `/delete` with `HX-Request: true` while logging active returns 200 with `<div class='alert-warn'>` containing lock message
- POST `/mkdir` with `HX-Request: true` and valid name returns 200 with `<div class='alert-ok'>Folder created.</div>` and `HX-Redirect` header
- `/files` GET page upload mode forms contain `hx-post` and `hx-target` attributes
- POST `/upload` (multipart) still redirects (unchanged)
- GET `/download` still serves file directly (unchanged)

---

### Phase 5 — CSS Polish

**Purpose:** Finalize `app.css` with the full design language from the design
doc: brand palette CSS custom properties, semantic status colors, typography,
spacing scale, component styles (nav bar, fieldsets, form rows, buttons, alerts,
tables), htmx loading indicators, and mobile responsive breakpoint at 480px.

**Delivers:**
- `app.css` updated with full design language implementation:
  - `:root` block with brand palette (`--shadow-grey`, `--dim-grey`, `--lavender-grey`, `--powder-blue`, `--pale-sky`) and semantic status colors
  - Spacing scale (`--space-xs` through `--space-xl`)
  - Typography (system-ui font stack, 14px base, 1.5 line height)
  - Page shell (`.titlebar`, `.netbar`, `.topnav`)
  - Fieldsets and form rows (flex layout, 160px labels, focus glow)
  - Buttons (primary, hover, disabled)
  - Alerts (`.alert-ok`, `.alert-err`, `.alert-warn`)
  - Tables (dark header, zebra striping, hover)
  - htmx indicator (`.htmx-indicator`, `.htmx-request .htmx-indicator`)
  - Mobile responsive `@media (max-width: 480px)` breakpoint
- Design artifact HTML files updated to match final CSS

**Tasks:** T08
- `app.css` contains `@media (max-width: 480px)` breakpoint
- `app.css` contains `.htmx-indicator` and `.htmx-request .htmx-indicator` rules
- Open `/config` in browser DevTools at 375px width — no horizontal scroll, all fields tappable
- `firmware.bin` total size delta across all phases < 20 KB

## Verification Plan

### Per-Phase Verification

| Phase | Verification Command | Expected Result |
|-------|---------------------|-----------------|
| 0 | `cd firmware && make -C test test` | All tests pass, exit 0 |
| 1 | `cd firmware && make -C test test` + `pio run -e thingplus_s3_usb_cdcserial_bodaqs_4f` | Tests pass, build succeeds, binary delta < 5 KB |
| 2 | `cd firmware && make -C test test` + `pio run -e thingplus_s3_usb_cdcserial_bodaqs_4f` | Tests pass, build succeeds, binary delta cumulative < 10 KB |
| 3 | `cd firmware && make -C test test` + `pio run -e thingplus_s3_usb_cdcserial_bodaqs_4f` | Tests pass, build succeeds, binary delta cumulative < 15 KB |
| 4 | `cd firmware && make -C test test` + `pio run -e thingplus_s3_usb_cdcserial_bodaqs_4f` | Tests pass, build succeeds, binary delta cumulative < 18 KB |
| 5 | `cd firmware && make -C test test` + `pio run -e thingplus_s3_usb_cdcserial_bodaqs_4f` | Tests pass, build succeeds, binary delta cumulative < 20 KB |

### Overall Verification

**Functional Verification**:
- [ ] All spec acceptance criteria pass (see spec.md — each component has AC1–ACn)
- [ ] All 30 host-based tests pass: 13 in `test_htmlutil.cpp`, 12 in `test_routes_static.cpp`, 5 in `test_fragments.cpp`
- [ ] Forms work without JavaScript — disable JS in browser, navigate to `/config`, submit form, page reloads with result (INV-1)
- [ ] Scroll position preserved on config save with htmx (G1)
- [ ] Inline success/error feedback after saving (G2, US2)
- [ ] File delete updates list via `HX-Redirect` reload (US4)

**Contract Verification**:
- [ ] INV-1: Every page functional without JS — verified by disabling JS and submitting each form
- [ ] INV-2: Static assets cached 1 year — first load fetches `?v=0.4.1`, subsequent loads use cache (zero requests), `Cache-Control: max-age=31536000` present
- [ ] INV-3: No response exceeds memory envelope — fragment responses use `sendText()` with 2 KB chunked streaming, no full-body heap buffering
- [ ] INV-4: Config lock works for htmx — POST `/config` with `HX-Request: true` while logging returns 423 with `.alert-warn` fragment
- [ ] INV-5: No overlapping requests — all forms have `hx-sync="this:replace"`

**Integration Verification**:
- [ ] `firmware.bin` size delta < 20 KB from baseline
- [ ] No test code in firmware binary — `grep -r "test/stubs" firmware/src/` returns zero matches; no `#ifdef TEST` in `firmware/src/`
- [ ] Existing routes unchanged: `/api/*` JSON endpoints, `/files` GET, `/download` GET, `/download_zip` POST, `/upload` POST
- [ ] `ESP.getFreeHeap()` before and after config page load within ±2 KB of baseline (G4)
- [ ] `/config` at 375px width in DevTools — no horizontal scroll, all fields tappable (G6)

## Phase Status Tracker

- [ ] Phase 0: Test Infrastructure
- [ ] Phase 1: Static Asset Infrastructure
- [ ] Phase 2: Config Page htmx
- [ ] Phase 3: Sensor Pages htmx
- [ ] Phase 4: Files Page htmx
- [ ] Phase 5: CSS Polish

## Dependencies

### Must Complete First
None — this is the first spec for this system.

### Can Start in Parallel
None.

### Blocked By This
None.
