# BODAQS Firmware Work To Date

Date: 2026-05-11

This note summarizes the recent firmware work and decisions, including the USB SD-card download investigation that has been parked, and the access-point Wi-Fi mode implementation that is currently active in the working tree.

## 1. USB SD-card Download Over Serial

Goal: allow users to download files from the logger SD card over the USB cable without removing the card.

The safer approach chosen was a serial-download protocol rather than exposing the SD card as USB mass storage. The mass-storage route would risk filesystem contention with firmware logging and would require much tighter ownership of the SD card. The serial approach keeps the logger firmware in control of the card and lets a host-side tool request files.

Design direction discussed:

- Add a firmware-side serial file-transfer command mode.
- Mute normal serial logs while a transfer is active.
- Provide a Windows batch wrapper and a small executable so users do not need Python.
- Support macOS as well, ideally with the same host tool compiled for each platform.
- Provide easy port discovery, including an `auto` option and list/scan behavior.
- Support resumable downloads, file listing, all-file download, and retry behavior.

Testing exposed reliability and speed issues:

- Initial transfers could time out mid-file.
- Later retries could receive stale protocol responses such as `END DATA`.
- Large files transferred but still showed periodic pauses.
- Shorter pauses improved after tuning, but the process remained patchy enough that it was parked.

Recommended path when this work resumes:

- Tighten the transfer protocol around explicit request/response framing.
- Add chunk-level sequence numbers and CRC/checksum validation.
- Ensure the host drains stale serial data before each command.
- Consider fixed-size binary chunks rather than line-oriented data for file payloads.
- Keep normal logs fully silenced during transfer.
- Add a robust resume path based on byte offsets and verified chunk boundaries.
- Add hardware-in-the-loop soak tests using several multi-megabyte files.
- Keep this feature separate from AP Wi-Fi work until the transfer path is predictably reliable.

Current status: deferred. The active working tree does not currently show USB-download files or changes.

## 2. Access Point Wi-Fi Mode

Goal: allow the logger to create its own Wi-Fi network so users can connect directly to the device and use the existing web UI without needing a local router.

Implemented config keys:

- `wifi_mode=station|access_point`
- `wifi_ap_ssid=BODAQS`
- `wifi_ap_password=bodaqslogger`

Notes:

- `bodaqslogger` was chosen because ESP32 secured AP passwords need 8-63 characters.
- AP mode is AP-only.
- Station mode remains the mode used for normal network joining and NTP.
- RTC/NTP sync remains station-only and is skipped in AP mode.

Files changed for AP mode:

- `src/ConfigManager.h`
- `src/ConfigManager.cpp`
- `src/WiFiManager.h`
- `src/WiFiManager.cpp`
- `src/WebServerManager.cpp`
- `src/Routes_Config.cpp`
- `src/MenuSystem.h`
- `src/MenuSystem.cpp`
- `src/ButtonActions.cpp`
- `src/UI.cpp`
- `src/HtmlUtil.cpp`
- `src/main.cpp`

Main implementation points:

- Added a `WiFiMode` enum with `Station` and `AccessPoint`.
- Added config parsing, saving, defaults, labels, and helpers for Wi-Fi mode.
- Added AP credential defaults and normalization.
- Added `AP_ONLINE` state to `WiFiManager`.
- Added mode-aware Wi-Fi startup:
  - station mode uses the existing scan/select/connect flow
  - access-point mode starts `WiFi.softAP(...)`
- Added `WiFiManager::isNetworkUp()`, `localAddress()`, and `networkName()` so other modules no longer assume that `WL_CONNECTED` is the only valid network-up state.
- Updated `WebServerManager` so the web server can run in either station or AP mode.
- Updated the web UI config page with Wi-Fi mode, AP SSID, and AP password fields.
- Added a main-menu Wi-Fi mode picker.
- If Wi-Fi is currently active and the user changes mode from the main menu, Wi-Fi is stopped and restarted in the new mode.
- Updated status displays so AP mode shows AP name/IP rather than station SSID/IP.
- Updated boot behavior so `wifi_enabled_default=true` can start AP mode even with no station networks configured.

Expected user flow:

1. Set `wifi_mode=access_point` via the web UI or main menu.
2. Start Wi-Fi from the menu/button shortcut, or set `wifi_enabled_default=true`.
3. Connect a phone or laptop to SSID `BODAQS`.
4. Use password `bodaqslogger`.
5. Open `http://192.168.4.1/` in a browser, assuming the ESP32 default AP IP is unchanged.

Current limitation:

- Changing AP SSID/password in the web UI saves the new values but does not forcibly restart the active AP session. The new credentials take effect on the next Wi-Fi restart. This avoids unexpectedly disconnecting the browser during save.

## 3. Verification

Firmware build was run successfully:

```text
pio run
```

Result:

```text
Environment: thingplus_s3_usb_cdcserial
Status: SUCCESS
```

The AP feature has been compile-verified, but still needs hardware testing on the logger:

- Confirm AP SSID appears as `BODAQS`.
- Confirm password `bodaqslogger` works.
- Confirm the web UI loads at `http://192.168.4.1/`.
- Confirm changing Wi-Fi mode from the main menu restarts active Wi-Fi.
- Confirm station mode still connects to configured networks.
- Confirm NTP reset works in station mode and is unavailable/ignored in AP mode.
- Confirm logging still disables Wi-Fi/AP as intended.

## 4. Suggested Next Steps

- Upload the firmware to a logger and test AP mode from a phone and laptop.
- Add a small UI notice on the config page explaining that AP credential changes apply after Wi-Fi restart.
- Consider showing the AP client count in the status or health endpoint.
- After AP mode is validated, decide whether to document it in the user docs.
- Resume the USB serial-download work later as a separate reliability-focused task.
