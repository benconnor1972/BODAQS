# BODAQS Firmware Versioning Policy

Status: Proposed

This document defines how semantic versioning applies to the BODAQS firmware.

For BODAQS, the "public API" is not just C++ source interfaces. It includes any externally relied-on behaviour: log files, SD-card layout, configuration files, web routes, user controls, and compatibility promises that downstream tooling or operators depend on.

## 1. Versioning Model

BODAQS firmware versions should follow `MAJOR.MINOR.PATCH`.

- Increase `MAJOR` for breaking changes to the external contract described here.
- Increase `MINOR` for backward-compatible additions or new capabilities.
- Increase `PATCH` for bug fixes and internal improvements that preserve the external contract.

This policy is intended to be practical for a small evolving firmware project:

- If a change would force users to update scripts, notebooks, saved configs, SD-card contents, operating habits, or hardware assumptions, it is probably not a patch.
- If a change is only visible inside the codebase and does not change externally observed behaviour, it should not drive a version bump beyond patch level.

## 2. What Counts As The Public API

The following surfaces should be treated as the firmware's semver-governed external contract.

### 2.1 Logged Files And SD-Card Data Layout

Current observed behaviour in firmware:

- Log filenames are created from local RTC time as `YYYY-MM-DD_HH-MM-SS.CSV`.
- Logs are comma-separated CSV files with one header row.
- The first CSV column is `sample_id`.
- The time column is `timestamp` in human mode or `timestamp_ms` in fast mode.
- The final CSV column is `mark`.
- Sensor columns are named from the configured sensor name plus units, for example:
  - `front_shock [mm]`
  - `front_shock_raw [counts]`
  - `String pot [mm]`
- Human timestamps are currently written as local time-of-day `HH:MM:SS.mmm`.
- Fast timestamps are currently written as integer epoch milliseconds.
- `sample_id` is currently zero-based within each log.
- The logger may append a footer block delimited by:
  - `# run_stats_begin`
  - `# run_stats_end`
  with key/value lines such as `samples_dropped`, `queue_max`, and `flush_count`.

For semver purposes, the public contract includes:

- CSV delimiter, header names, and reserved control columns
- units embedded in header names where present
- timestamp field names and semantics
- meaning of `mark`
- meaning of `sample_id`
- filename convention for log files
- footer marker names and the fact that footer lines are comment-prefixed

Recommended stability rule:

- Consumers should match CSV columns by header name, not by absolute column position, except that `sample_id` should remain first and `mark` should remain last.
- Adding optional columns is backward-compatible only when existing columns keep the same names and meanings.

### 2.2 Persistent Configuration And Saved Settings

Current observed behaviour in firmware:

- Runtime configuration is loaded from `/config/loggercfg.txt`.
- The file is a line-oriented `key=value` text format with `#` comments.
- The firmware persists global keys such as:
  - `sample_rate_hz`
  - `timestamp_mode`
  - `tz`
  - `ntp_servers`
  - `time_check_url`
  - `debounce_ms`
  - `log_level`
- Wi-Fi settings are persisted as `wifiN.*`.
- Button bindings are persisted as `bindingN.button`, `bindingN.event`, `bindingN.action`.
- Sensors are persisted as `sensorN.*`, including `type`, `name`, `muted`, `output_mode`, `output_id`, calibration fields, and sensor-specific parameters.
- Transform selection is persisted via `sensorN.output_id`.

For semver purposes, the public contract includes:

- config file location
- config file syntax
- supported persisted key names
- meaning of saved values
- accepted stable sensor type keys
- transform selection key names and semantics
- backward compatibility of existing config files across firmware updates

Recommended stability rule:

- A new firmware version should continue to load an existing supported `loggercfg.txt` without manual migration whenever possible.
- If migration is required, that is a breaking change unless the old format remains accepted.

### 2.3 Transform Files And Transform Selection

Current observed behaviour in firmware:

- Sensor transforms are loaded from `/cal/<sensor_name>/`.
- Supported on-disk formats currently include:
  - `.lut.csv`
  - `.poly.json`
  - `.poly.cfg`
  - `.poly.txt`
  - `.poly`
- The selected transform is identified by `output_id`.
- Selection is by logical transform ID, not by filename.
- Missing or unknown transforms fall back to identity without blocking logging.

For semver purposes, the public contract includes:

- per-sensor transform directory layout
- supported transform file formats
- `output_id` matching semantics
- identity fallback behaviour

### 2.4 Web And File-Server Interfaces

Current observed behaviour in firmware:

- User-facing routes include:
  - `/`
  - `/files`
  - `/config`
  - `/config/sensors`
  - `/config/buttons`
- File actions include routes such as:
  - `/download`
  - `/delete`
  - `/delete_multi`
  - `/download_zip`
  - `/mkdir`
  - `/rmdir`
  - `/upload`
- Transform-related API routes include:
  - `/api/transforms/list`
  - `/api/transforms/select`
  - `/api/transforms/reload`
- Config writes are blocked while logging is active.

For semver purposes, the public contract should include:

- route paths
- HTTP methods
- required query/form arguments
- high-level behaviour and side effects
- lock-while-logging behaviour

The following should not be treated as stable unless separately documented:

- HTML structure
- CSS
- inline JavaScript
- exact form field ordering
- diagnostic endpoints such as `/__ping` and `/__health`

### 2.5 User-Facing Controls And Device Behaviour

Current observed behaviour in firmware:

- Button IDs are board-defined and include:
  - `nav_up`
  - `nav_down`
  - `nav_left`
  - `nav_right`
  - `nav_enter`
  - `mark`
- Button bindings map button IDs and events to actions such as:
  - `logging_toggle`
  - `mark_event`
  - `web_toggle`
  - `menu_nav_up`
  - `menu_nav_down`
  - `menu_nav_left`
  - `menu_nav_right`
  - `menu_nav_enter`
- Available button events include:
  - `pressed`
  - `released`
  - `click`
  - `double_click`
  - `held`
- The current menu exposes top-level items for:
  - Wi-Fi on/off
  - muting sensors
  - sample rate
  - calibration
  - sleep
  - restart
- Logging and web serving are mutually interlocked.
- Mark events are only recorded while logging is active.

For semver purposes, the public contract includes:

- button IDs and binding vocabulary
- meaning of supported button events
- top-level user-visible control behaviour
- menu structure when users are expected to navigate it
- logging/web-server interlock behaviour

Exact wording of OLED or serial status messages is not part of the stable API unless explicitly documented elsewhere.

### 2.6 Supported Hardware, Boards, And Sensor Compatibility

Current observed behaviour in firmware:

- Board profiles currently include:
  - `ThingPlusS3_BODAQS_4_D`
  - `ThingPlusS3_BODAQS_4_D_UartI2C1`
  - `ThingPlus_A`
- Supported sensor families currently include:
  - `analog_pot`
  - `as5600_string_pot_analog`
  - `as5600_string_pot_i2c`
- Analog sensors may rely on `ain` ordinal mapping through the active `BoardProfile`.
- AS5600 I2C sensors rely on `i2c_bus` and `i2c_addr`.
- Storage backends currently support SDMMC and SPI.

For semver purposes, the public contract includes:

- supported board variants that are intentionally shipped
- supported sensor types
- stable meaning of hardware-facing config keys such as `ain`, `i2c_bus`, and `i2c_addr`
- compatibility of existing supported SD-card layouts and wiring assumptions for documented board variants

### 2.7 Downstream Analysis And Tooling Compatibility

The analysis package already consumes logger outputs directly. In current code and docs, downstream tooling relies on things like:

- `timestamp` or `timestamp_ms`
- `sample_id`
- `mark`
- unit-bearing signal headers such as `[mm]` and `[counts]`
- the optional `run_stats` footer block

For semver purposes:

- If a firmware change requires updates to the BODAQS analysis loader, notebooks, widgets, or documented interchange contracts, it should be treated as an external API change.

## 3. What Should NOT Drive Semver

The following are internal implementation details and should not, by themselves, require a major or minor version bump:

- refactoring C++ classes, modules, or file layout
- changing task structure, buffering, queue depths, or flush strategy
- swapping SD backends internally while preserving external behaviour
- changing log tag names or debug verbosity
- changing internal calibration implementation while preserving saved keys and externally observed meanings
- changing HTML/CSS presentation without changing route behaviour
- changing fallback or error-handling internals when the externally visible contract stays the same
- changing build flags, compile-time organisation, or library choices without affecting supported public behaviour

## 4. Version Bump Rules

### 4.1 MAJOR

Increase `MAJOR` when an external user, script, notebook, saved SD card, or documented hardware setup would need to change to keep working.

Examples:

- Renaming `timestamp` to `time_s` in firmware CSV output.
- Changing human timestamps from `HH:MM:SS.mmm` to another format.
- Changing `timestamp_ms` from epoch milliseconds to elapsed milliseconds.
- Renaming or removing `mark` or `sample_id`.
- Changing existing sensor column names or units.
- Changing the log filename convention.
- Removing or renaming `/config`, `/files`, or file-action routes.
- Changing `sensorN.output_id` to mean filename instead of transform ID.
- Moving the config file away from `/config/loggercfg.txt`.
- Changing the meaning of `ain` numbering for an existing supported board.
- Dropping support for a board variant or sensor type that was previously supported.
- Changing default button behaviour in a way that reassigns an existing user action, such as moving logging toggle from Enter release to a different gesture without preserving the old behaviour.
- Requiring users to manually rewrite existing config or transform files after updating firmware.

### 4.2 MINOR

Increase `MINOR` for backward-compatible additions: new functionality that does not break existing users or existing saved artifacts.

Examples:

- Adding support for a new sensor type while keeping existing sensor types unchanged.
- Adding support for a new board profile.
- Adding a new optional config key with a safe default.
- Adding a new optional footer statistic inside the existing `run_stats` block.
- Adding a new route or API endpoint without changing existing routes.
- Adding a new menu item without repurposing existing controls.
- Adding an optional log column only when a user explicitly enables a new feature or adds a new sensor.
- Adding a new transform file format while keeping existing transform formats and `output_id` behaviour unchanged.

### 4.3 PATCH

Increase `PATCH` for fixes and internal improvements that preserve the public contract.

Examples:

- Refactoring `StorageManager`, `SensorManager`, or route handlers with no external behaviour change.
- Improving sampling performance or SD write efficiency without changing file formats.
- Fixing a bug where a valid config file was incorrectly rejected, while keeping the config format unchanged.
- Tightening file-path validation in the file browser without changing route names or normal successful behaviour.
- Fixing a measurement bug while preserving documented column names, units, and timestamp semantics.
- Updating menu rendering, display timing, or debug output text without changing the functional control model.

## 5. Ambiguous Or Currently Underdocumented Areas

The current codebase has a few areas where behaviour exists but the contract is not yet cleanly documented. These should be clarified and then treated consistently.

### 5.1 Human Timestamp Semantics

Current code writes human timestamps as `HH:MM:SS.mmm`, not full local date-time. The date currently lives in the filename, not in the CSV timestamp column.

Recommendation:

- Treat this as the current contract until intentionally changed.
- If the project later wants full local date-time in the CSV, that should be a major change unless a new additive column is introduced instead.

### 5.2 Legacy `buttonN.*` Config Entries

Sample configs still contain `buttonN.*`, but the current firmware ignores these and uses `BoardProfile` for physical button hardware.

Recommendation:

- Do not treat `buttonN.*` as a stable config input.
- Treat only button bindings and board-defined button IDs as stable.

### 5.3 Legacy Sensor Type Names In Sample Configs

Sample config files use names such as `analog_potentiometer`, but the parser's explicit stable keys are:

- `analog_pot`
- `as5600_string_pot_analog`
- `as5600_string_pot_i2c`

Recommendation:

- Only the explicit stable keys above should be considered part of the public contract.
- Other accepted strings should be treated as compatibility shims unless documented.

### 5.4 `use_external_rtc`

`use_external_rtc` appears in older docs/config examples, but current firmware startup is hard-wired to `RTC_INTERNAL`.

Recommendation:

- Do not treat `use_external_rtc` as part of the current stable config contract until it is actually implemented and documented.

### 5.5 Transform-Selection Persistence Semantics

Transform routes exist, but persistence semantics are not yet clearly documented end-to-end.

Recommendation:

- Treat saved `output_id` in `loggercfg.txt` as the stable persistent contract.
- Treat live transform-selection HTTP behaviour as stable only at the route/effect level once formally documented.

## 6. Recommended Project Rule Of Thumb

When deciding a version bump, ask:

1. Would an existing SD card, config file, transform file, analysis notebook, or user workflow stop working?
2. Would an operator have to relearn a button or menu action?
3. Would a downstream parser have to change how it reads the CSV?

If yes:

- likely `MAJOR` if existing behaviour is broken or redefined
- likely `MINOR` if the change is only additive and old behaviour still works
- `PATCH` only if existing external behaviour still works as documented

## 7. Concrete Examples

- Breaking change to log format: renaming `rear_shock_raw [counts]` to `rear_shock_counts` is `MAJOR`.
- Adding an optional field/column: adding a new footer key `sd_backend=sdmmc` inside the existing `run_stats` block is `MINOR`.
- Changing button behaviour: changing the default mark-button double-click from web toggle to restart is `MAJOR`.
- Adding support for new sensors: adding a supported `imu_6dof` sensor type with new optional config keys is `MINOR`.
- Dropping support for a hardware variant: removing `ThingPlus_A` support is `MAJOR`.
- Internal refactor with no external effect: replacing route helper internals or changing queue sizes is `PATCH`.
- Bug fix that preserves interfaces: fixing a log write bug while keeping CSV schema and config compatibility unchanged is `PATCH`.

## 8. Suggested Adoption

This document should become the source of truth for firmware release versioning.

If the project wants to signal "stable external contract" clearly, the first release made under this policy should be considered the starting point for a `1.0.0` style contract. If the project stays on `0.x` for a while longer, the same classification rules should still be used internally so downstream consumers get predictable change signalling.

