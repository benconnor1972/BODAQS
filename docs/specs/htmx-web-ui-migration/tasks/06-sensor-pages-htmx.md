STEP 06: Sensor pages htmx fragment responses
============================================

STATUS
------

Status: COMPLETE
Completed: 2025-07-16
Verified by: implement (independent re-run)

DEPENDS ON: step 05

SPEC
----

Make the `/config/sensors` POST handler return fragments for sensor save, add, and delete operations. The sensor editor form (`/config/sensor?id=N`) gets `hx-*` attributes for the Save Sensor button. Apply Type remains a full page reload (resolved question 2).

### POST /config/sensors handler changes

At each exit point, check `isHtmxRequest(srv)`:

**Delete sensor** (currently `srv.sendHeader("Location", "/config/sensors?ok=1&reboot=1"); srv.send(303, ...)`):
```cpp
if (isHtmxRequest(srv)) {
  HttpFileSender::sendText(srv, 200, F("text/html"),
    F("<div class='alert-ok'>Sensor deleted. Restart the logger to rebuild the live sensor set.</div>"), F("no-store"));
  return;
}
```

**Add sensor** (currently `srv.sendHeader("Location", "/config/sensors?ok=1&reboot=1#sensor-" + ...); srv.send(303, ...)`):
```cpp
if (isHtmxRequest(srv)) {
  HttpFileSender::sendText(srv, 200, F("text/html"),
    F("<div class='alert-ok'>Sensor added. Restart the logger to rebuild the live sensor set.</div>"), F("no-store"));
  return;
}
```

**Save sensor** (at the end of the sensor field processing loop, currently redirects back to `/config/sensor?id=N`):
```cpp
if (isHtmxRequest(srv)) {
  HttpFileSender::sendText(srv, 200, F("text/html"),
    F("<div class='alert-ok'>Saved.</div>"), F("no-store"));
  return;
}
```

**423 lock** — same pattern as config page, return 200 with `.alert-warn` fragment for htmx (not 423 — htmx v2.0 does not swap 4xx bodies).

### GET /config/sensor?id=N form changes

Add htmx attributes to the sensor editor form:
```html
<form method='POST' action='/config/sensors'
      hx-post="/config/sensors" hx-target="#sensor-result" hx-swap="innerHTML" hx-sync="this:replace">
```

Add swap target before the form:
```html
<div id="sensor-result"></div>
```

Add htmx indicator to Save Sensor button:
```html
<button type='submit'>Save Sensor <span class="htmx-indicator">Saving...</span></button>
```

**Apply Type button does NOT get hx-* attributes.** It submits as a normal POST, causing a full page reload with rebuilt fields. This is intentional (resolved question 2).

### GET /config/sensors (sensor list page)

The add sensor form can also get htmx attributes:
```html
<form method='POST' action='/config/sensors'
      hx-post="/config/sensors" hx-target="#sensor-list-result" hx-swap="innerHTML" hx-sync="this:replace">
```

FILES TO CREATE
---------------

None.

FILES TO MODIFY
---------------

- `firmware/src/Routes_Config.cpp`: POST /config/sensors handler — add isHtmxRequest checks at delete, add, save exit points; GET /config/sensor?id=N — add hx-* to form, add #sensor-result div, add htmx-indicator to Save button; GET /config/sensors — add hx-* to add sensor form, add #sensor-list-result div

TEST CASES
----------

T1: htmx save sensor returns fragment
    POST /config/sensors with HX-Request: true and sensor field data → 200, body contains `<div class='alert-ok'>Saved.</div>`

T2: htmx delete sensor returns fragment
    POST /config/sensors with HX-Request: true and delete_sensor_idx → 200, body contains `<div class='alert-ok'>Sensor deleted.`

T3: htmx add sensor returns fragment
    POST /config/sensors with HX-Request: true and add_sensor → 200, body contains `<div class='alert-ok'>Sensor added.`

T4: Non-htmx requests return 303 redirect
    POST /config/sensors without HX-Request → 303 redirect (current behavior)

T5: Sensor editor form has hx attributes
    GET /config/sensor?id=0 form contains hx-post="/config/sensors", hx-target="#sensor-result", hx-swap="innerHTML", hx-sync="this:replace"

T6: Sensor editor has swap target
    GET /config/sensor?id=0 page contains `<div id="sensor-result"></div>` before form

T7: Apply Type does NOT have hx attributes
    Apply Type button does not have hx-post or hx-target — it submits as normal POST

T8: htmx lock returns warn fragment
    POST /config/sensors with HX-Request: true while logging → 200, body contains `<div class='alert-warn'>`

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
- POST /config/sensors with HX-Request returns fragments for save/add/delete
- POST /config/sensors without HX-Request returns 303 redirects (current behavior)
- Sensor editor form has hx-post, hx-target, hx-swap, hx-sync
- #sensor-result div exists before form
- Apply Type button does NOT have hx-* attributes
- 423 lock returns 200 with .alert-warn fragment for htmx (not 423)
