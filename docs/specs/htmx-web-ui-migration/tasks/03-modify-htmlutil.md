STEP 03: Modify HtmlUtil for htmx/CSS tags and fragment support
==============================================================

STATUS
------

Status: COMPLETE
Completed: 2025-07-16
Verified by: implement (independent re-run)

DEPENDS ON: step 02

SPEC
----

Modify `HtmlUtil.cpp` to: (1) remove all inline CSS from `htmlHeader()`, (2) add `<script>` and `<link>` tags for htmx and app.css with `?v=<FirmwareInfo::version()>`, (3) add new functions `isHtmxRequest()`, `htmlFragment()`, `htmlRespond()`.

### htmlHeader() changes

Remove the entire `<style>...</style>` block (currently ~1 KB of inline CSS). Also remove the dead JavaScript code (functions `populateSelect`, `loadTransforms`, and the `DOMContentLoaded` listener) that is a standalone string expression never concatenated to the output string `s`. Add two tags in `<head>`:

```cpp
s += F("<script src='/static/htmx.min.js?v=");
s += FirmwareInfo::version();
s += F("' defer></script>");
s += F("<link rel='stylesheet' href='/static/app.css?v=");
s += FirmwareInfo::version();
s += F("'>");
```

The `defer` attribute on `<script>` ensures htmx loads without blocking page rendering. The `<link>` tag causes the browser to fetch CSS in parallel.

Everything else in `htmlHeader()` stays the same: titlebar, netbar, topnav.

### New functions

```cpp
bool isHtmxRequest(WebServer& srv) {
  if (!srv.hasHeader(F("HX-Request"))) return false;
  String val = srv.header(F("HX-Request"));
  val.trim();
  val.toLowerCase();
  return val == "true";
}

String htmlFragment(const String& body) {
  return body;  // just the body, no wrapper
}

String htmlRespond(WebServer& srv, const String& title, const String& body) {
  if (isHtmxRequest(srv)) {
    return htmlFragment(body);
  }
  return htmlHeader(title) + body + htmlFooter();
}
```

### HtmlUtil.h additions

```cpp
bool isHtmxRequest(WebServer& srv);
String htmlFragment(const String& body);
String htmlRespond(WebServer& srv, const String& title, const String& body);
```

FILES TO CREATE
---------------

None.

FILES TO MODIFY
---------------

- `firmware/src/HtmlUtil.h`: Add declarations for `isHtmxRequest`, `htmlFragment`, `htmlRespond`. Add `#include "FirmwareInfo.h"` if not already included.
- `firmware/src/HtmlUtil.cpp`: Remove inline `<style>` block from `htmlHeader()`. Add `<script>` and `<link>` tags with `?v=FirmwareInfo::version()`. Implement `isHtmxRequest()`, `htmlFragment()`, `htmlRespond()`.
- `firmware/test/test_htmlutil.cpp`: Update tests — remove test for `<style>` block (T3 from T01), add new tests for htmx/CSS tags, fragment functions, isHtmxRequest, htmlRespond, version changes

TEST CASES
----------

T1: htmlHeader includes htmx script with version
    htmlHeader("Config") output contains `<script src='/static/htmx.min.js?v=0.4.1' defer></script>`

T2: htmlHeader includes app.css link with version
    htmlHeader("Config") output contains `<link rel='stylesheet' href='/static/app.css?v=0.4.1'>`

T3: htmlHeader does NOT contain inline style
    htmlHeader("Config") output does NOT contain `<style>`

T4: htmlHeader still includes navbar
    Output contains `href='/files'`, `href='/config'`, `href='/config/sensors'`

T5: htmlHeader still includes titlebar
    Output contains `BODAQS data logger:`

T6: htmlFragment returns body only
    htmlFragment("<p>Saved.</p>") returns exactly `<p>Saved.</p>`

T7: htmlFragment has no html wrapper
    htmlFragment("<div>test</div>") does NOT contain `<html>`, `<head>`, `<script>`, `<link>`

T8: isHtmxRequest true
    Request with HX-Request: true header → returns true

T9: isHtmxRequest false when absent
    Request without HX-Request header → returns false

T10: isHtmxRequest false when other value
    Request with HX-Request: false → returns false

T11: htmlRespond fragment mode
    htmx request → htmlRespond() returns fragment (no `<html>`)

T12: htmlRespond full page mode
    non-htmx request → htmlRespond() returns full page (with `<html>`, `<script>`, `<link>`)

T13: Version changes with firmware
    Set FirmwareInfo::version() to "0.5.0" → htmlHeader() output contains `?v=0.5.0`

T14: htmlFooter returns closing tags
    htmlFooter() returns exactly `</body></html>` (retained from T01 baseline)

T15: htmlEscape escapes special characters
    htmlEscape("a&b<c>d\"e") returns `a&amp;b&lt;c&gt;d&quot;e` (retained from T01 baseline)

VERIFICATION
------------

  cd firmware && make -C test test

Expected output:
  test_htmlutil: 15 tests passed
  test_routes_static: 12 tests passed
  All tests passed.

Exit code: 0

DONE WHEN
---------

- All 15 test_htmlutil tests pass (updated from 8 baseline — 13 new + 2 retained)
- All previous tests still pass
- htmlHeader() has no `<style>` block
- htmlHeader() has no dead JavaScript code (populateSelect, loadTransforms, DOMContentLoaded listener removed)
- htmlHeader() includes `<script>` and `<link>` with `?v=0.4.1`
- isHtmxRequest() correctly detects HX-Request header
- htmlFragment() returns body only
- htmlRespond() switches between fragment and full page based on isHtmxRequest()
- htmlFooter() and htmlEscape() tests retained from T01 baseline

NOTES
-----

- Created `firmware/test/stubs/FirmwareInfo.h` (new file, not listed in FILES TO
  CREATE). The real `FirmwareInfo.h` defines `version()` as `inline` returning the
  compile-time `BODAQS_FW_VERSION` macro, which cannot be mocked at runtime. T13
  requires changing the version at runtime. The stub declares the functions as
  non-inline so `mocks.cpp` can return `mockGetVersion()`. The spec's test
  strategy (Phase 0) called for `FirmwareInfo::version()` in mocks.h, but Phase 0
  only added `mockSetVersion`/`mockGetVersion` — the actual `FirmwareInfo` mock
  was not wired up. This task fills that gap.

- Modified `firmware/test/stubs/mocks.cpp` (not listed in FILES TO MODIFY) to add
  `FirmwareInfo::version()`, `name()`, `buildDateTime()`, and `boardName()`
  implementations. `version()` returns `mockGetVersion()`; the others return
  hardcoded defaults.

- Added `#include <WebServer.h>` to `HtmlUtil.cpp` (production) for the
  `WebServer&` parameters in `isHtmxRequest()` and `htmlRespond()`. Used a
  forward declaration `class WebServer;` in `HtmlUtil.h` to avoid pulling the
  full WebServer header into every file that includes HtmlUtil.h.

- The `test_routes_static` suite reports 21 tests passed (not 12 as shown in the
  task's expected output). T02 created more check calls than the spec estimated.
  This is not a regression — all tests pass.

- `test_main.cpp` T5 (HtmlUtil integration) still passes unchanged — it checks
  `startsWith("<!DOCTYPE html>")`, titlebar, title tag, footer, escape, and path
  helpers, all of which are preserved.
