# ESP32 Data Logger (SD + Web UI)

ESP32-based data logger with:
- An extensible sensor framework - initial target is 2 potentiometer, 2 accelerometer, 2 strain gauge and one event mark channels
- Up to 500Hz logging (tested to 100Hz so far)
- SD card logging
- On-device web UI (list/download/delete files, simple config page)
- mDNS discovery (browse to `http://esp32-logger.local/`)
- Button control (start/stop logging, mark events, menu navigation)
- General and sensor configuration via config file on SD (`loggercfg`) 

Developed mainly for mountain bike use.

## Hardware

- **ESP32** (Arduino core 3.3.0 tested) - SparkFun ESP32 Thing Plus dev board
- **MicroSD** via SPI
- **Buttons**
- **0.96" monochrome OLED display**
- **Sensors** starting with potentiometers on ADC pins (configurable)

## Development

# ESP32 Data Logger — Module Overview

This document summarizes the major modules in the project, what each one is responsible for, how they interact, and key APIs/gotchas. It’s meant to be kept at the repo root for quick orientation.

---

## Top-Level Flow (boot → ready)

1. **setup()** initializes storage (SD), applies defaults, loads config, brings up Wi‑Fi (optional), syncs RTC, constructs sensors from the config, starts Display/UI, and registers buttons.
2. **loop()** runs the main managers’ `loop()` functions (logging, web server, menu, button dispatch, etc.).

---

## `ConfigManager`

**Purpose:** Load/save the logger’s global settings and the list of **SensorSpec**s from `loggercfg.txt`. It also owns a per‑sensor key/value store backing the **ParamPack** interface used by sensor code.

**Key responsibilities**
- `begin(SdFs*, filename)` — wire to shared SD object and file name.
- `load(LoggerConfig&)` / `save(const LoggerConfig&)` — merge text file with defaults and persist changes.
- Manage **SensorSpec** array (type, name, mutedDefault, ParamPack for per-sensor params).
- Simple string‑backed **ParamStore** (arrays `keys[]`/`vals[]`, bounded sizes) with case‑insensitive lookups.

**APIs**
- `uint8_t sensorCount()`
- `bool getSensorSpec(uint8_t i, SensorSpec& out)` — returns a copy; ParamPack is rebound to the correct store.
- `bool getParam/getIntParam/getFloatParam/getBoolParam(index, key, out)` — safe accessors used by UI/Web to read current per‑sensor values.
- Global parse helpers: `parseBool`, etc.

**Notes/Gotchas**
- `save()` writes **all** config keys (globals + sensors) deterministically.
- Fixed per‑sensor KV capacity (currently 16). Exceeding keys will drop extra pairs.
- File format keys used by analog pot sensors: `pin`, `mode`, `include_raw`, `invert`, `ema_alpha_permille`, `deadband_counts`, `zero_count`, `full_count`, `full_travel_mm`.
- File format keys used by AS5600 string-pot sensors include `counts_per_turn`, `wrap_threshold_counts`, `sensor_zero_count`, `sensor_full_count`, `installed_zero_count`, `sensor_full_travel_mm`, and `assume_turn0_at_start`.

---

## `SensorManager`

**Purpose:** Owns the live sensor objects, registration, primary pot selection, and per‑sensor mute state that the logger and UI respect.

**Key responsibilities**
- `begin(const LoggerConfig*)` — reset internal lists and prepare to accept sensors.
- Build sensors in `setup()` by iterating `ConfigManager::sensorCount()` and mapping `ParamPack` → sensor params.
- `registerSensor(Sensor*)`, `finalizeBegin()`, `debugDump()` for inspection.
- Mute control used by logger/UI: `getMuted(idx, bool&)`, `setMuted(idx, bool)`.
- `primaryPot()` selection for UI convenience.

**Notes/Gotchas**
- Keep the **construction order** deterministic so UI indices match spec indices.
- Treat `SensorManager` APIs as **static** utilities across the codebase.

---

## `AnalogPotSensor` (potentiometer)

**Purpose:** Acquire analog position and report one or more columns depending on mode and configuration.

**Key params (from ParamPack)**
- `pin` (ADC pin), `mode` (`raw`/`norm`/`mm`), `include_raw` (bool), `invert` (bool),
- `ema_alpha_permille` (smoothing), `deadband_counts`, `zero_count`, `full_count`, `full_travel_mm`.

**Notes**
- Produces normalized and/or raw columns; column names include the sensor `name` (e.g. `pot1_norm`).
- Honors **muted** state via `SensorManager` (muted sensors still tick but are skipped in log output).

## `AS5600StringPotSensorBase` / `AS5600StringPotAnalog`

**Purpose:** Acquire a wrapped one-turn AS5600 reading, unwrap it across multiple turns in firmware, and report unwrapped travel while still logging wrapped raw counts.

**Key params (from ParamPack)**
- `ain` / `pin`
- `counts_per_turn`, `wrap_threshold_counts`, `assume_turn0_at_start`
- `sensor_zero_count`, `sensor_full_count`, `installed_zero_count`, `sensor_full_travel_mm`
- `invert`, `ema_alpha`, `deadband`, `output_mode`, `include_raw`

**Notes**
- `RAW` mode reports wrapped counts as the primary column.
- `LINEAR` mode reports unwrapped mm using the calibrated unwrapped span.
- The sensor resets its unwrap tracker to turn 0 at each logging start when `assume_turn0_at_start=true`.

---

## `StorageManager`

**Purpose:** Single owner of the `SdFat` instance and log file lifecycle; provides sample interval/buffer knobs.

**Common APIs**
- `StorageManager_begin(csPin)`
- `StorageManager_getSd()` (shared SdFat* used by Config/Web)
- `StorageManager_setSampleRate(hz)` / `StorageManager_getSampleIntervalMs()`
- `StorageManager_setBufferSize(bytes)`

**Notes**
- `sd.begin()` and error handling live here.
- A small smoke test may create `TEST.TXT` during setup.

---

## `LoggingManager`

**Purpose:** Turn logging on/off, write headers and rows from active sensors, and accept **mark** events.

**Common APIs**
- `bool start()` / `void stop()` / `bool isRunning()`
- `void mark()` — insert a marked row/annotation.

**Interlocks**
- Will **refuse to start** while the web server is running (see `ButtonActions`).

---

## `RTCManager`

**Purpose:** Timekeeping (internal ESP32 RTC or external DS3231), NTP sync, timezone application.

**Common APIs**
- `RTCManager_begin(RTC_INTERNAL|RTC_EXTERNAL)`
- `RTCManager_setHumanReadable(bool)` — UI/log timestamp format.
- `RTCManager_syncWithNTP(ssid, pass)`
- Tied to `configTzTime(tz, ntp1, ntp2, ntp3)` in `setup()`.

---

## `WebServerManager`

**Purpose:** Lightweight HTTP UI for status, SD file browsing, and editing **all** configuration (globals + sensors).

**Routes**
- `/` status; `/files` with `download` and `delete` actions.
- `/config` (GET) displays editable globals and sensor sections.
- `/config` (POST) updates globals and rewrites `loggercfg.txt` with all keys; also rewrites each sensor’s block.

**Interlocks**
- `canStart()` returns false while logging is active; `ButtonActions` also blocks starting logging while Wi‑Fi/web is running.

**Helpers**
- Minimal HTML/CSS, simple CSV inputs (e.g., NTP servers), basic HTML escaping, safe path checks.

---

## `UI` & `DisplayManager`

**Purpose:** Unified printing to Serial and OLED with levels and targets, plus transient toasts and a status line.

**UI APIs (typical)**
- `UI::begin(g_cfg)` — apply target/level preferences.
- `UI::println(serialText, oledText, target, level, oledToastMs=0)`
- `UI::status("Ready")` — persistent status line when idle.
- `UI::toast("Marked", 1200)` — small transient message.
- `UI::clear(target)` / `UI::flush()` — OLED control.
- `UI::setModal(true/false)`, `UI::isModal()` — allow **MenuSystem** to “own” the OLED while a menu is open.

**DisplayManager**
- Owns the OLED device and regular idle/telemetry rendering.
- In `loop()`, it **exits early** when `UI::isModal()` is true so the menu can draw unobstructed.

---

## `ButtonManager`

**Purpose:** Register buttons in **poll** or **interrupt** mode, debounce, and raise callbacks with **edge** and **hold** events.

**APIs**
- `ButtonManager_register(pin, BUTTON_POLL|BUTTON_INTERRUPT, debounceMs, callback)`
- `ButtonManager_loop()` — delivers events & performs polling.
- Optional `ButtonManager_read(pin)` — single-pin polled edge read.

**Events**
- `BUTTON_PRESSED`, `BUTTON_RELEASED`, `BUTTON_HELD` (long‑press; ~800 ms default).

**Notes/Gotchas**
- Interrupt mode posts **PRESS** from ISR; **HELD** is synthesized in the main loop when the level stays LOW long enough.
- Some pins can’t generate external interrupts on ESP32; keep **Enter** on a reliable GPIO when using interrupt mode, or use **poll** for nav keys.

---

## `ButtonActions`

**Purpose:** Wire configured pins to user-visible actions and UI feedback.

**Mappings (typical)**
- **Web** → start/stop web server (blocks when logging).
- **Log** → start/stop logging (blocks when web server is running).
- **Mark** → inserts a mark only when logging is active.
- **Nav Up/Down/Left/Right/Enter** → dispatch into **MenuSystem** when the menu is active; otherwise show small UI toasts.

**Setup**
```cpp
ButtonActions::begin(&g_cfg);
ButtonActions::registerButtons();  // reads pins & debounce from config
```

---

## `MenuSystem`

**Purpose:** A small, modal OLED UI navigated by five buttons. Current focus: **Sensors on/off** list for mute toggling.

**Behavior**
- **Open/Close**: short‑press Enter to open, long‑press Enter to close (or via left/back).
- **Auto‑close** after inactivity (default 15 s; `setIdleCloseMs(ms)`).
- **States**: `Inactive` → `Main` (shows “Sensors on/off”) → `SensorsList` (list of sensors with `[M]` suffix when muted).
- **Navigation**:
  - From **Main**: Right/Enter opens “Sensors on/off” list.
  - In **SensorsList**: Up/Down to move selection, Right/Enter toggles mute for the selected sensor via `SensorManager::getMuted/setMuted`.
  - Left goes back; closing returns the OLED to `DisplayManager` by calling `UI::setModal(false)` internally.

**Notes**
- Calls `UI::setModal(true)` on open and `UI::setModal(false)` on close so normal telemetry rendering pauses while the menu is visible.
- Uses `ConfigManager::sensorCount()`/`getSensorSpec()` to render names; relies on `SensorManager` for the **live** mute state.

---

## `DebugLog` (optional)

**Purpose:** Compile‑time and run‑time gated debug printing without littering the codebase with `#ifdef`s.

**Typical use (pseudocode)**

```cpp
// DebugLog.h
// #define DEBUGLOG_ENABLED 1  // uncomment to compile logs in
enum DebugLevel : uint8_t { DL_ERROR=0, DL_WARN=1, DL_INFO=2, DL_DEBUG=3, DL_VERBOSE=4 };
void DBG_SET_LEVEL(DebugLevel lvl);
bool DBG_WOULD_LOG(DebugLevel lvl);
void DBG_IMPL(DebugLevel lvl, const char* fmt, ...);

#define DBG(lvl, fmt, ...)    do { if (DBG_WOULD_LOG(lvl)) DBG_IMPL(lvl, fmt, ##__VA_ARGS__); } while(0)
#define DBG_IF(cond, lvl, fmt, ...) do { if ((cond) && DBG_WOULD_LOG(lvl)) DBG_IMPL(lvl, fmt, ##__VA_ARGS__); } while(0)
```

**Notes**
- You can flip a single global to enable/disable logs and adjust verbosity.
- Keep fast‑path disabled in production to save cycles and flash.

---

## Configuration Keys (globals)

- `sample_rate_hz`, `timestamp_mode` (`human|fast`), `tz`
- `debounce_ms`
- Button pins: `web_button_pin`, `log_button_pin`, `mark_button_pin`, `nav_up_pin`, `nav_down_pin`, `nav_left_pin`, `nav_right_pin`, `nav_enter_pin`
- Network/time: `wifi_ssid`, `wifi_password`, `ntp_servers`, `time_check_url`
- UI: `ui_target`, `ui_serial_level`, `ui_oled_level`, `oled_brightness`, `oled_idle_dim_ms`
- RTC: `use_external_rtc`

Sensor sections follow the pattern:
```
sensorN.type=analog_pot
sensorN.name=pot1
sensorN.muted=true|false
sensorN.pin=34
sensorN.mode=raw|norm|mm
sensorN.include_raw=true|false
sensorN.invert=true|false
sensorN.ema_alpha_permille=200
sensorN.deadband_counts=0
sensorN.zero_count=0
sensorN.full_count=4095
sensorN.full_travel_mm=0

sensorN.type=as5600_string_pot_analog
sensorN.name=stringpot1
sensorN.ain=0
sensorN.counts_per_turn=4096
sensorN.wrap_threshold_counts=2048
sensorN.assume_turn0_at_start=true
sensorN.sensor_zero_count=0
sensorN.sensor_full_count=24576
sensorN.installed_zero_count=0
sensorN.sensor_full_travel_mm=600
sensorN.output_mode=LINEAR
sensorN.include_raw=true
```

---

## Interactions at a Glance

- **WebServerManager ↔ LoggingManager**: mutual gating (don’t run both at once).
- **MenuSystem ↔ DisplayManager/UI**: menu takes OLED ownership (modal) and then releases it.
- **ConfigManager ↔ SensorManager**: specs/params come from `ConfigManager`; live mute and sensor objects live in `SensorManager`.
- **ButtonManager ↔ ButtonActions**: hardware events → high-level behaviors.

---

## Troubleshooting Tips

- **Crashes during config print**: ensure any `st->items[k]` legacy code was replaced with the current `ParamStore` (`keys[k]` / `vals[k]`).
- **Wi‑Fi/Web won’t start**: check STA credentials and the “busy while logging” guard.
- **Buttons unreliable**: confirm GPIO supports interrupts if using ISR mode; otherwise fallback to `BUTTON_POLL`.
- **Menu flicker/overdraw**: verify `UI::isModal()` check in `DisplayManager::loop()` short‑circuits while menus are active.
- **Sensor list shows only one entry**: confirm `s_sensorSel` clamping and that `ConfigManager::sensorCount()` matches the constructed sensors.

---

*Last updated: generated by ChatGPT.*

