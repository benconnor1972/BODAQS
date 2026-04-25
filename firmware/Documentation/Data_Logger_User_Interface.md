# BODAQS Data Logger User Interface Guide

Status: Draft

This guide explains the BODAQS data logger from an operator's point of view. It focuses on the display, the navigation model, the main menu, and the common tasks a rider or test operator is likely to perform.

It deliberately does not document button bindings or custom gestures. The logger's configured controls provide the usual navigation actions: move up, move down, go back, open/select, mark an event, start or stop logging, toggle the web interface, and sleep. The standard bindings in `loggercfg.txt` are assumed to be representative.

## 1. Display Overview

BODAQS uses a small OLED display for status, menu navigation, and short confirmation messages.

When the menu is not open, the display shows the idle/status screen. This is the normal screen to expect before and after a logging run.

> Photo placeholder: Idle/status screen showing sample rate and active channel count.

The idle/status screen shows:

- The current status at the top of the display, such as ready, logging, or Wi-Fi state.
- The active sample rate, for example `500 Hz`.
- The number of active channels.
- A footer line when available, typically used for time/status information.

While logging is active, the main idle information blinks periodically. This provides a visible indication that the logger is recording.

Short messages, also called toasts, appear in the middle of the screen after actions such as starting a log, stopping a log, marking an event, saving calibration, or encountering an error.

> Photo placeholder: Toast message after starting or stopping a log.

The OLED dims after a period of inactivity to save power. Using the controls wakes it back to normal brightness.

## 2. Navigation Model

The user interface is built around a simple menu model:

- Move up and down to change the highlighted row.
- Open or select the highlighted row to enter a submenu or apply an action.
- Go back to return to the previous screen.
- Leaving the top-level menu returns to the idle/status screen.

The selected row is shown with a leading `>` marker.

> Photo placeholder: Main menu with one row selected.

If a menu has more rows than can fit on the display, the visible list scrolls as you move through it.

The menu closes automatically after a period of inactivity. If that happens, reopen the menu and continue from the top-level screen.

## 3. Logging

Logging is the main operating mode of the data logger. When logging starts, BODAQS creates a new log file on the SD card and begins recording samples from the active sensors.

Starting a log:

- Stops Wi-Fi and the web server if they are running.
- Uses the current sample rate.
- Uses the current sensor configuration and calibration.
- Shows a `Log start` confirmation if the run starts successfully.
- Shows a failure message if the logger cannot start.

Stopping a log:

- Stops sampling.
- Closes the current log file.
- Re-enables normal navigation polling.
- Restores Wi-Fi behavior after logging.
- Shows a `Log stop` confirmation.

> Photo placeholder: Idle screen while logging is active.

## 4. Marking Events

During a logging run, the operator can mark an event. A mark is written into the log stream so the event can be found later during analysis.

Use event marks for moments such as:

- Beginning a test section.
- Hitting a trail feature.
- Changing setup or riding condition.
- Noting an unusual event during a run.

When a mark is accepted, the display shows `Marked`.

Marks are only recorded while logging is active. Mark actions outside a logging run do not add anything to a log file.

> Photo placeholder: `Marked` confirmation toast.

## 5. Main Menu

The main menu contains the primary on-device settings and actions.

> Photo placeholder: Main menu top-level list.

Current top-level items are:

- `WiFi: ON`, `WiFi: OFF`, or `WiFi: CONNECTING`
- `Mute sensors`
- `Sample rate: <rate> Hz`
- `Calibration`
- `Sleep`
- `Reset time`
- `Restart`

### 5.1 Wi-Fi And Web Interface

The Wi-Fi menu item starts or stops Wi-Fi and the web interface.

When Wi-Fi is off, selecting the row starts a connection attempt. The display changes to `WiFi: CONNECTING` while the logger tries to connect. If the connection succeeds and the web server starts, the row changes to `WiFi: ON`.

When Wi-Fi is on, selecting the row stops the web server and disables Wi-Fi. The row changes back to `WiFi: OFF`.

> Photo placeholder: Main menu showing `WiFi: CONNECTING`.

Wi-Fi and logging are interlocked. The logger will not start the web server while logging is active. If Wi-Fi is running when logging starts, it is stopped so that sampling has priority.

If Wi-Fi cannot start, the display shows a short failure message such as `WiFi fail` or `WiFi timeout`.

### 5.2 Mute Sensors

The `Mute sensors` menu opens a list of configured sensors. This screen lets you enable or mute individual sensor channels without editing the configuration file.

> Photo placeholder: Sensors on/off screen.

Each sensor appears by name. Muted sensors show `[M]` beside the name.

Selecting a sensor toggles it between muted and active:

- `Muted` means the sensor is excluded from active logging output.
- Active sensors are included in the channel count and log data.

The display shows a short `Muted` or `Unmuted` confirmation after the change.

### 5.3 Sample Rate

The `Sample rate` menu opens a list of supported sample rates.

> Photo placeholder: Sample rate picker.

Supported rates are:

- `10 Hz`
- `20 Hz`
- `50 Hz`
- `100 Hz`
- `200 Hz`
- `500 Hz`
- `1000 Hz`

The current rate is shown with `[*]`. Other available rates are shown with `[ ]`.

Select a rate to apply it. The logger saves the new rate and returns to the main menu after showing a confirmation such as `Rate: 500 Hz`.

The sample rate cannot be changed while logging is active. Stop the current log before changing it.

### 5.4 Calibration

The `Calibration` menu is used to set zero and range values for sensors that support on-device calibration.

> Photo placeholder: Calibration sensor list.

The first calibration screen lists the configured sensors. Each row shows the sensor name and the calibration operations available for that sensor:

- `[Z]` means zero calibration is available.
- `[R]` means range calibration is available.
- `[Z|R]` means both zero and range calibration are available.
- `[none]` means the sensor does not currently expose on-device calibration actions.

Select a sensor to open its calibration detail screen.

#### Zero Calibration

Zero calibration captures the sensor's current raw position and saves it as the installed zero point.

Typical zero calibration workflow:

1. Put the sensor or suspension component at the desired zero/reference position.
2. Open `Calibration`.
3. Select the sensor.
4. Select `Zero`.
5. Check the captured count shown on the display.
6. Select `Save` to keep the value, or `Cancel` to discard it.

> Photo placeholder: Calibration detail screen showing `Zero`.

After a zero capture, the display briefly shows the captured raw count. Saving writes the new calibration to the logger configuration.

#### Range Calibration

Range calibration captures the sensor's travel range between a start position and a finish position.

Typical range calibration workflow:

1. Put the sensor or suspension component at the range start position.
2. Open `Calibration`.
3. Select the sensor.
4. Select `Start RANGE`.
5. Move the sensor or suspension component through the intended travel to the finish position.
6. Select `Finish RANGE`.
7. Check the captured count shown on the display.
8. Select `Save` to keep the range, or `Cancel` to discard it.

> Photo placeholder: Active range calibration screen showing live counts.

While range calibration is active, the display shows live raw counts at the bottom of the screen. This helps confirm that the sensor is moving and that the logger is seeing the change.

Saving a range calibration writes the range values to the logger configuration. For sensors where direction matters, the logger also updates the sensor's inversion setting based on the captured start and finish positions.

### 5.5 Sleep

The `Sleep` menu item puts the logger into sleep mode.

Use sleep when you want to conserve battery without fully disconnecting power. The exact wake behavior depends on the hardware build.

> Photo placeholder: Main menu with `Sleep` selected.

### 5.6 Reset Time

The `Reset time` menu item forces a time sync using Wi-Fi.

Use this when:

- The logger has lost valid time.
- Log filenames or timestamps appear incorrect.
- The logger has been powered off long enough that time should be checked.

> Photo placeholder: Main menu showing `Time: SYNCING`.

Time reset cannot run while logging is active. Stop logging before resetting time.

If the sync starts, the menu row changes to `Time: SYNCING`. If the sync fails, the display shows `Time sync fail`.

### 5.7 Restart

The `Restart` menu item restarts the firmware.

Use restart after configuration changes or if the logger is in an unexpected state. Restart is blocked while logging is active, so stop the current log first.

> Photo placeholder: `Restarting...` confirmation toast.

## 6. Common Workflows

### 6.1 Before A Ride Or Test

1. Power on the logger.
2. Confirm the idle screen shows the expected sample rate.
3. Confirm the active channel count is correct.
4. Open `Mute sensors` if you need to enable or mute channels.
5. Open `Sample rate` if you need a different logging rate.
6. Use `Reset time` if time is invalid or has not been synced recently.
7. Start logging when ready.

> Photo placeholder: Ready-to-log idle screen.

### 6.2 During A Run

1. Leave the logger on the idle/status screen.
2. Confirm the display indicates logging is active.
3. Mark events at important moments.
4. Avoid opening Wi-Fi or changing settings during the run.

### 6.3 After A Run

1. Stop logging.
2. Wait for the stop confirmation.
3. Turn on Wi-Fi if you want to use the web interface.
4. Download or inspect the log files as needed.
5. Put the logger to sleep if it will not be used again soon.

> Photo placeholder: Wi-Fi enabled after logging has stopped.

## 7. Messages And What They Mean

Common display messages include:

- `Log start`: logging started successfully.
- `Log start failed`: logging could not start.
- `Log stop`: logging stopped and the file was closed.
- `Marked`: an event mark was recorded in the current log.
- `Busy/logging`: the requested action cannot run while logging is active.
- `Stop logging first`: stop the current log before using this action.
- `WiFi: CONNECTING`: the logger is attempting to connect to Wi-Fi.
- `WiFi fail`: Wi-Fi connected, but the web server did not start.
- `WiFi timeout`: the connection attempt took too long.
- `Time: SYNCING`: the logger is attempting to update its clock.
- `Time sync fail`: the clock sync attempt failed.
- `Muted`: the selected sensor was muted.
- `Unmuted`: the selected sensor was re-enabled.
- `Zero saved`: zero calibration was saved.
- `Range saved`: range calibration was saved.
- `Save failed` or `Save fail`: calibration could not be saved.
- `Restarting...`: the logger is restarting.

## 8. Notes For Operators

- Logging has priority over Wi-Fi and configuration changes.
- Stop logging before changing sample rate, resetting time, restarting, or using the web interface.
- Check the active channel count before a run, especially after muting or unmuting sensors.
- Recalibrate sensors after installation changes, mechanical changes, or sensor replacement.
- Use event marks generously during testing; they make later analysis much easier.
- If the menu closes by itself, it has timed out due to inactivity. Reopen it and continue.

