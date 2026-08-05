STEP 05: Config page htmx fragment responses
============================================

STATUS
------

Status: COMPLETE
Completed: 2025-07-16
Verified by: implement (independent re-run)

DEPENDS ON: step 04

SPEC
----

Make the `/config` POST handler return HTML fragments when `HX-Request: true` is present. Add `hx-*` attributes to the config form so htmx swaps the response into a `#save-result` div. Non-htmx requests keep the current 303 redirect behavior.

### POST /config handler changes

At each exit point in the POST handler, check `isHtmxRequest(srv)` and return a fragment instead of a 303 redirect:

**On success** (currently `srv.sendHeader("Location", "/config?ok=1&tab=" + submit); srv.send(303, ...)`):
```cpp
if (isHtmxRequest(srv)) {
  HttpFileSender::sendText(srv, 200, F("text/html"),
    F("<div class='alert-ok'>Configuration saved.</div>"), F("no-store"));
  return;
}
// existing 303 redirect
```

**On validation error** (currently `srv.sendHeader("Location", "/config?err=wifi_ap_password_length"); srv.send(303, ...)`):
```cpp
if (isHtmxRequest(srv)) {
  HttpFileSender::sendText(srv, 200, F("text/html"),
    F("<div class='alert-err'>Error: AP password must be 8-63 characters</div>"), F("no-store"));
  return;
}
// existing 303 redirect
```

**On 423 lock** (currently `rejectConfigEditLocked_` returns 423 plain text):
```cpp
// In rejectConfigEditLocked_, or in the POST handler before calling it:
if (isHtmxRequest(srv)) {
  // Return 200 (not 423) because htmx v2.0 does not swap 4xx response bodies by default.
  // Returning 423 would cause htmx to fire htmx:responseError and discard the body,
  // leaving #save-result empty with no lock feedback visible to the user.
  HttpFileSender::sendText(srv, 200, F("text/html"),
    String(F("<div class='alert-warn'>Configuration is locked while ")) + reason + F(".</div>"), F("no-store"));
  return true;
}
// existing 423 plain text
```

**On 500 save failure** (currently `srv.send(500, F("text/plain"), F("Failed to save config"))`):
```cpp
if (isHtmxRequest(srv)) {
  HttpFileSender::sendText(srv, 200, F("text/html"),
    F("<div class='alert-err'>Failed to save config</div>"), F("no-store"));
  return;
}
// existing 500 plain text
```

### GET /config form changes

Modify the form tag to add htmx attributes:
```html
<form method='POST' action='/config'
      hx-post="/config" hx-target="#save-result" hx-swap="innerHTML" hx-sync="this:replace">
```

Add swap target before the form:
```html
<div id="save-result"></div>
```

Add htmx indicator to submit button:
```html
<button type='submit'>Save <span class="htmx-indicator">Saving...</span></button>
```

FILES TO CREATE
---------------

None.

FILES TO MODIFY
---------------

- `firmware/src/Routes_Config.cpp`: POST /config handler — add isHtmxRequest checks at each exit point (success, validation errors, 423 lock, 500 failure); GET /config — add hx-* attributes to form tag, add #save-result div, add htmx-indicator to submit button. Also modify `rejectConfigEditLocked_` to return HTML fragment for htmx requests.

TEST CASES
----------

T1: htmx success returns fragment
    POST /config with HX-Request: true and valid data → 200, text/html, body contains `<div class='alert-ok'>Configuration saved.</div>`, no `<html>` tag

T2: Non-htmx success returns redirect
    POST /config without HX-Request and valid data → 303 redirect to /config?ok=1

T3: htmx validation error returns fragment
    POST /config with HX-Request: true and wifi_ap_password of 3 chars → 200, body contains `<div class='alert-err'>` with password error

T4: htmx lock returns warn fragment
    POST /config with HX-Request: true while logging → 200, body contains `<div class='alert-warn'>` (not 423 — htmx v2.0 does not swap 4xx bodies)

T5: htmx save failure returns error fragment
    POST /config with HX-Request: true and ConfigManager::save() fails → 200, body contains `<div class='alert-err'>Failed to save config</div>`

T6: GET /config form has hx attributes
    Form tag contains hx-post="/config", hx-target="#save-result", hx-swap="innerHTML", hx-sync="this:replace"

T7: GET /config has swap target
    Page contains `<div id="save-result"></div>` before the form

T8: GET /config has htmx indicator
    Submit button contains `<span class="htmx-indicator">Saving...</span>`

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
- POST /config with HX-Request returns fragment (no <html>)
- POST /config without HX-Request returns 303 redirect (current behavior)
- 423 lock returns 200 with .alert-warn fragment for htmx (not 423)
- Validation errors return .alert-err fragment for htmx
- GET /config form has hx-post, hx-target, hx-swap, hx-sync
- #save-result div exists before form
- Submit button has htmx-indicator span

## Notes

- Used `HtmlUtil::isHtmxRequest(srv)` (fully qualified) in `rejectConfigEditLocked_` because that function is defined at file scope before the `using namespace HtmlUtil;` directive (line 275). All other htmx checks inside `registerConfigRoutes` use the unqualified `isHtmxRequest(srv)` since they're after the using directive.
- `rejectConfigEditLocked_` is a shared helper used by both POST /config and POST /config/sensors. The htmx fragment response applies to both routes. T06 (sensor pages) will add sensor-specific fragment messages for add/delete/save operations.
- The 500 save failure in POST /config/sensors (line ~1311) was NOT modified — that's T06's scope. Only the POST /config 500 failure was modified.
- `HtmlUtil.h` and `HttpFileSender.h` were already included in Routes_Config.cpp — no new includes needed.
- Host tests: 79 passed, 0 failed. PlatformIO build: SUCCESS (Flash: 73.9%, 1550337 bytes).
