# Firmware 0.4 User Guide Documentation Audit

Status: draft  
Date: 2026-06-21  
Scope: `bodocs/src/content/docs/user-guide/index.mdx` and `bodocs/src/content/docs/user-guide/accessing logs and configuration.mdx`  
Firmware context: current `firmware` tree after the 0.4.0 feature work.

This note identifies changes needed before editing the website content. It is intentionally an audit/planning document, not an edit of the published docs.

## Source Docs Reviewed

- `bodocs/src/content/docs/user-guide/index.mdx`
- `bodocs/src/content/docs/user-guide/accessing logs and configuration.mdx`

## Firmware Areas Checked

- OLED/menu behavior: `firmware/src/MenuSystem.cpp`, `firmware/src/UI.cpp`, `firmware/src/DisplayManager.cpp`
- Web routes: `firmware/src/Routes_Config.cpp`, `firmware/src/Routes_Files.cpp`, `firmware/src/Routes_Api.cpp`, `firmware/src/HtmlUtil.cpp`
- Sensor model/registry: `firmware/src/SensorRegistry.cpp`, `firmware/src/SensorManager.cpp`, sensor class files
- File/log behavior: `firmware/src/StorageManager.cpp`, `firmware/src/BdqLogWriter.cpp`, `firmware/src/LogMetadataWriter.cpp`

## Existing Items Whose Details Have Changed

### Display Overview

- The idle footer no longer has a `Time:` label. It shows the clock on the left, optional GPS status in the middle, and battery percentage on the right.
- GPS status now appears only when a GPS sensor is configured:
  - `GPS` = fix achieved
  - `.....` = GPS configured and acquiring
  - `NOGPS` = GPS configured but absent/error/no usable state
- The top status line can now show AP-mode state as well as station Wi-Fi state. It alternates network name and IP when network is up.
- The status line can temporarily show board warnings such as missing SD card, SD not ready, analog rail fault, low battery, or battery alert.
- The existing `Idle.png` explanation needs updating to include GPS, battery percentage, and AP/status-warning behavior.

### Navigation Model And Main Menu

The top-level menu currently contains:

- `WiFi: ON/OFF/STARTING`
- `Upload: ON/OFF`
- `Mute sensors`
- `Sample rate: <rate> Hz`
- `Calibration`
- `Sag helper`
- `Sleep`
- `Settings`

The current docs still list `Reset time` and `Restart` as top-level items. These now live under `Settings`.

The new `Settings` submenu contains:

- `WiFi mode: STA/AP`
- `Log format`
- `Reset time`
- `Health`
- `Restart`
- `About`

### Logging Start/Stop

- The docs say Wi-Fi may be restored after stopping a log if it was active when logging started. Current behavior should be described more conservatively: starting a log stops Wi-Fi/web so sampling has ownership; users should manually re-enable Wi-Fi/upload mode after logging if needed.
- Logging is blocked while upload mode is active.
- The docs should clarify that web/config/file mutation is not a while-logging workflow.

### Marking Events

- The existing docs say marks require the bar switch and cannot be logged using the logger keypad. That may still be the intended user-facing policy, but the firmware now treats marks as a configurable button action rather than a hard-coded special case.
- The docs should describe the shipped/default user flow rather than implying a firmware limitation. Suggested wording: marks are normally made using the configured mark/bar-switch button while logging is active.
- Mention that the display shows `Marked` when the mark is accepted.

### Wi-Fi And Web Interface

- The docs currently assume station Wi-Fi only. Firmware now supports both station and access-point modes.
- The main menu Wi-Fi row starts/stops the selected Wi-Fi mode and web server. The row can show `WiFi: STARTING`.
- AP mode should be documented as a direct-connect workflow, typically using the logger AP SSID/password and the AP IP address.
- The Settings menu now has a `WiFi mode` picker (`Station` / `Access point`).
- The General web config page also exposes Wi-Fi mode, AP SSID, and AP password.
- AP credential changes should be described as taking effect after Wi-Fi restart, not necessarily immediately during the active browser session.

### Reset Time

- `Reset time` is now under `Settings`, not the top-level menu.
- Time sync depends on station Wi-Fi/NTP. AP mode is useful for direct browser access but does not provide internet NTP unless another route is present.
- The docs should distinguish station-mode NTP from AP-mode web access.

### Log Format

- Log format can be selected on-device from `Settings` -> `Log format`.
- The General web config page now offers three formats:
  - `BODAQS CSV`
  - `syn.bike CSV`
  - `BODAQS compact binary`
- The docs currently talk mainly about CSV and syn.bike output. They need to mention compact binary `.bdq` output, what it is for, and what downstream software support is required.

### Files Page

- The Files page now includes a `Logger upload` panel with:
  - upload mode active/inactive state
  - network mode/name/IP/hostname
  - importable session count
  - incomplete session count where applicable
  - enter/exit upload mode button
- Upload mode is now distinct from ordinary manual file browsing.
- Manual upload/create/delete operations are disabled while logging is active or upload mode is active.
- The docs should add `.bdq` compact binary files to the list of possible log files.
- The current text says `fip files` in the ZIP/download card. That looks like a typo and should be corrected.

### General Configuration Page

The current docs need updates for fields now present or changed:

- `Log format` includes compact binary.
- `Wi-Fi mode` is now configurable (`Station` / `Access point`).
- `AP SSID` and `AP password` are present.
- `HTTP time check URL` is present.
- Hidden SSID and static IP details remain present.
- Config pages are locked while logging is active or upload mode is active.
- The recommendation around `Timestamp mode` should be checked. The existing text says to generally leave it as `fast`, but the current defaults and downstream expectations should be verified before preserving that advice.

### Sensor Configuration Page Structure

- The Sensors page is no longer a single long editor for every sensor. It now shows a sensor summary table and a `New sensor` block.
- Each sensor has its own detail page at `/config/sensor?id=N`.
- Screenshots and text should reflect the list/detail split.
- Add/delete/type changes still require restart before relying on the live sensor set.

### Sensor Types

The currently documented sensor configuration is centered on analog pots/I2C basics. The supported type list now includes at least:

- Analog Potentiometer
- AS5600 String Pot (Analog)
- AS5600 String Pot (I2C)
- AS5600 Angle (I2C)
- AS5048B Angle (I2C)
- DAN-F10N GPS (UART)

The docs should describe these at a user-facing level, especially which fields appear for each family: analog input, I2C bus/address, UART port/baud, wrapping, GPS update rate/diagnostics, etc.

### Sensor Output Section

- Output mode is now firmware-limited to `RAW` and `LINEAR` in the web UI.
- The docs still describe logger-side `LUT` and `Poly` output modes as active options. That is out of date.
- The docs should say complex transforms are applied downstream during import/analysis. Legacy POLY/LUT configs may be read but saved back as LINEAR.
- `Units label` is no longer an editable override. Units are inherited from the sensor class/output mode.
- `Installed range` is now a sensor parameter for sag percentage display.
- Bus speed (`i2c_hz`) is no longer a per-sensor web field; bus speed is part of the board profile.

### Sensor Usage / Semantics

- Usage fields are still important: `End`, `Primary domain`, and `Primary quantity` feed log metadata and features such as Sag Helper.
- The docs should explicitly connect `primary_domain=suspension` to Sag Helper eligibility.
- GPS signals should be described in terms of signal semantics rather than as ordinary fixed-rate scalar sensors. Mention that GPS rows may initially be invalid and downstream processing should respect validity/status fields.

### Sensor Calibration Section

- `Calibration methods` is now read-only in the web UI. It reflects sensor capability/effective calibration availability; it is not a user override.
- Calibration state/values remain editable where exposed.
- Rotary zero calibration now includes a direction/polarity step (`Capture +move`) so the firmware can infer positive direction. The old docs describe zero as a single capture.
- Rotary polarity is now represented by `direction`; `invert` continues to be emitted for compatibility where needed.
- Range calibration language should be narrowed to sensor families that actually support it. Rotary angle sensors do not need range calibration for counts-to-degrees.
- The zero-calibration section currently has `<Flag src="" alt="">`; that should be replaced with a real screenshot or plain text until an image exists.

### Sample Rate

- The OLED sample-rate picker still offers `10, 20, 50, 100, 200, 500, 1000 Hz`.
- The web page numeric field allows a wider range. The docs should either document the OLED-supported preset list separately from the web numeric field, or recommend using presets unless there is a reason to do otherwise.
- Add a caution that some sensor combinations, especially external ADC and asynchronous sensors, may limit the practical logging rate.

### Mute Sensors

- The basic behavior remains, but the docs should mention that muted sensors are also hidden from Sag Helper and excluded from active logging output.

### Sleep / Power

- The broad behavior is still valid, but the Proto-E-specific warning is probably less central now that Proto F/RC3 are the active hardware targets. Consider moving that warning to a legacy hardware note.
- The docs should mention current board warnings on the idle display if keeping the display overview comprehensive.

## New Items Or Features Not Currently Covered

### Access Point Mode

Add a direct-connect workflow:

1. Set Wi-Fi mode to `Access point` from OLED Settings or General web config.
2. Start Wi-Fi from the main menu or configured button binding.
3. Connect laptop/phone to the logger AP SSID.
4. Browse to the AP IP shown on the OLED, typically the ESP32 AP address unless configured otherwise.
5. Understand that AP mode is for local browser access, not internet/NTP time sync.

### Upload Mode

Add a section explaining Upload Mode:

- What it is: a protected mode for Import Manager / session transfer workflows.
- How to enter/exit from the Files page and OLED main menu.
- What it changes: configuration and manual file mutations are locked while active.
- Why it exists: gives file transfer/import workflows clear ownership of the SD card/network interaction.

### Sag Helper

Add a full OLED feature section:

- Main menu item: `Sag helper`, after `Calibration` and before `Sleep`.
- Not available while logging; stop logging first.
- Shows unmuted sensors with `primary_domain=suspension`.
- Updates live values once per second.
- Up/down cycles display modes:
  - raw counts
  - linear units, only for sensors configured for linear output
  - sag percentage, only when `installed_range` is set
- Enter/mark freezes/unfreezes the displayed values.
- Frozen values briefly flash off every two seconds and show `HOLD`.
- Left exits back to the main menu.

### GPS Sensor Support

Add GPS coverage:

- DAN-F10N GPS over UART.
- GPS is asynchronous/lower-rate relative to the main log loop.
- GPS state appears on OLED footer when configured.
- GPS columns/signals need validity/status interpretation downstream.
- Initial invalid GPS rows are normal while acquiring a fix.
- GPS does not currently discipline the RTC in this firmware release.
- L5 is not enabled for now.

### Compact Binary Log Format

Add user-facing explanation of compact binary output:

- The file extension is `.bdq`.
- It is smaller/more efficient than CSV but requires compatible downstream tooling.
- Metadata/semantics remain important.
- Users who want simple manual inspection should keep using BODAQS CSV.

### RC3 And External ADC Analog Inputs

Add a short note for RC3 users:

- Analog input dropdowns are board-aware.
- RC3 analog inputs may be external ADC channels rather than ESP32 GPIO ADC pins.
- External ADC sampling has practical rate limits depending on channels/sensor configuration.

### New Rotary Sensors

Add sensor-type notes for:

- AS5600 angle sensor.
- AS5048B angle sensor.
- AS5600 string-pot modes if not already covered elsewhere.
- Direction/polarity calibration workflow.
- I2C address and bus selection at a high level.

### Health And About Screens

Add lightweight descriptions:

- `Health` shows SD, battery, analog rail, sample-rate/effective-rate style status.
- `About` gives device/firmware information.

### Web API / Import Manager Endpoints

Probably not a main user-guide topic, but the accessing-logs page may need a short note that Import Manager uses API endpoints and Upload Mode. Avoid documenting the API exhaustively in the user guide; link to an API/developer note if one exists.

## Screenshots / Photos That Are Out Of Date

These screenshots are referenced by the two reviewed docs and should be considered stale or at least suspect after the UI changes:

- `Idle.png` - footer/time/GPS/battery/status behavior changed.
- `mainmenu.png` - top-level menu items changed; add Upload, Sag helper, Settings; remove top-level Reset time/Restart.
- `connecting.png` - Wi-Fi row now can show `STARTING`; AP mode should be represented too.
- `wifiip.png` - idle Wi-Fi status now alternates network/IP and can show AP mode.
- `wifion.png` / `wifinetwork.png` if used elsewhere - likely old station-only assumptions.
- `mute.png` - verify against current list layout and muted marker.
- `samplerate.png` - likely mostly valid, but verify visible preset list and header.
- `calibration.png` - sensor list may now show changed calibration capabilities, including rotary zero-only cases.
- `rangestart.png` / `rangefinish.png` - verify phased calibration UI and labels.
- `config.png` - General page now includes compact binary and updated layout/locking behavior.
- `wifi.png` - Network section now includes Wi-Fi mode, AP SSID/password, HTTP time check URL, etc.
- `files.png` - Files page now includes the Logger upload panel and upload-mode controls.
- `sensorbasic.png` - sensor editing moved to detail pages and Basic has board-aware fields.
- `sensorbasici2c.png` - I2C page should be re-shot for current detail page; bus speed no longer appears as a sensor field.
- `sensoroutput.png` - output mode is now RAW/LINEAR only; no editable units label; installed range added.
- `sensorusage.png` - verify section appears only for sensors with usage params and matches current labels.
- `sensorcalibration.png` - calibration methods read-only; direction/zero_count fields for rotary sensors may need separate shots.
- `sensorwrapping.png` - verify against current string-pot wrapping fields and labels.
- `logformat.JPG` / `logformatmenu.JPG` - likely need updating for compact binary and Settings submenu placement if reused.

## Screenshots / Photos We Should Have But Currently Do Not

OLED screenshots/photos to add:

- Idle/status with no GPS configured.
- Idle/status with GPS acquiring (`.....`).
- Idle/status with GPS fixed (`GPS`).
- Idle/status in AP mode showing AP name/IP behavior.
- Main menu showing the current top-level item list.
- Settings menu showing Wi-Fi mode, Log format, Reset time, Health, Restart, About.
- Wi-Fi Mode picker (`Station` / `Access point`).
- Log Format picker including `BODAQS compact binary`.
- Upload Mode screen from the OLED.
- Sag Helper RAW mode with one or two suspension sensors.
- Sag Helper LINEAR mode.
- Sag Helper `%` mode with installed range configured.
- Sag Helper frozen/HOLD state.
- Rotary zero calibration `Capture +move` screen.
- Rotary calibration save/cancel screen after +move capture.
- Health screen.
- Optional: About screen.

Web screenshots to add:

- Files page with Logger upload panel at the top.
- Files page in upload mode.
- Files page while manual mutation is disabled.
- General config page showing compact binary and Network & NTP fields.
- General config page in AP mode with AP SSID/password fields.
- Sensors summary/list page.
- New sensor block with current supported type list.
- Sensor detail page for an analog pot on Proto F/RC3.
- Sensor detail page for an RC3 external ADC analog input showing board-aware analog input options.
- Sensor detail page for an I2C rotary angle sensor.
- Sensor detail page for DAN-F10N GPS over UART.
- Sensor detail Output section showing RAW/LINEAR only and installed range.
- Sensor detail Calibration section showing read-only calibration methods.
- Locked configuration warning while logging active.
- Locked configuration warning while upload mode active.

Photos that may be useful, depending on how far the user guide wants to go:

- Proto F logger with keypad/OLED in current enclosure.
- RC3 board/logger hardware if it is now a supported target for users.
- DAN-F10N GPS board wired to the UART pins.
- AS5600/AS5048 rotary sensor examples if sensor setup is covered in this guide rather than hardware docs.

## Suggested Restructure

### `Using the data logger` (`index.mdx`)

Suggested structure:

1. Display overview
   - Status line
   - Footer: time, GPS, battery
   - Warnings/toasts/dimming
2. Controls and navigation
   - Button model
   - Default bindings / bar-switch note
   - Menu navigation pattern
3. Start/stop logging and marks
   - Logging owns sensors/storage; Wi-Fi/upload mode are stopped/blocked
   - Marks from configured mark button
4. Main menu map
   - Short table of top-level items and what they do
5. Settings submenu
   - Wi-Fi mode
   - Log format
   - Reset time
   - Health/About/Restart
6. Wi-Fi quick start
   - Station mode summary
   - AP mode summary
   - Link to full accessing-logs/config page
7. Sensor operations
   - Mute sensors
   - Sample rate
   - Calibration overview
   - Sag Helper
8. Sleep/power

This would keep the on-device guide focused on what a rider/operator sees on the logger.

### `Accessing logger data and configuration`

Suggested structure:

1. What the web UI is for
   - Setup, file transfer, configuration
   - Not while logging
2. Connection options
   - Station mode
   - Access point mode
   - Finding IP/hostname
3. Files and upload mode
   - Files page overview
   - Manual downloads/ZIP
   - Upload mode and Import Manager workflow
   - What files you will see: `.CSV`, `.json`, `.bdq`
4. General configuration
   - Logger identity/rates/log formats
   - Time and timezone
   - Wi-Fi station/AP settings
5. Sensor configuration concepts
   - Sensor list vs sensor detail page
   - Basic/wiring
   - Output policy
   - Usage/semantics
   - Calibration state
   - Wrapping/other advanced fields
6. Sensor type notes
   - Analog pot / external ADC
   - AS5600 string pot
   - AS5600/AS5048 angle sensors
   - DAN-F10N GPS
7. Safety/locking behavior
   - Config locked while logging/upload mode
   - Manual file mutation disabled while logging/upload mode
   - Restart requirements after add/delete/type changes

### General Editorial Suggestions

- Use tables for menu items and web fields rather than long prose lists where possible. The firmware UI is now feature-rich enough that tables will be easier to maintain.
- Separate current user workflows from legacy caveats. Proto-E-specific limitations should move to a legacy hardware note unless the page is explicitly covering older builds.
- Avoid documenting every low-level sensor parameter inline. Instead, group parameters by concept and add type-specific notes for fields users are likely to touch.
- Treat complex transforms as downstream/import-manager work, not a logger-side workflow.
- Include a short glossary for terms that now matter to both firmware and downstream processing: `domain`, `quantity`, `linear output`, `installed range`, `upload mode`, `AP mode`, `valid GPS fix`.

## Priority Update List

Recommended first pass:

1. Replace `mainmenu.png`, `Idle.png`, `files.png`, `config.png`, `wifi.png`, and all sensor config screenshots.
2. Rewrite menu structure in `index.mdx` to match current top-level menu plus Settings submenu.
3. Add AP mode and upload mode to `accessing logs and configuration.mdx`.
4. Update sensor configuration text to match RAW/LINEAR-only output and split list/detail pages.
5. Add Sag Helper section.
6. Add GPS support and GPS footer/status section.
7. Fix calibration docs for rotary `Capture +move` direction calibration and read-only calibration methods.
8. Add compact binary `.bdq` format note.
