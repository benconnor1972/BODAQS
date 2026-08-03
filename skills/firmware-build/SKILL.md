---
name: firmware-build
description: "Build, merge, and flash BODAQS ESP32-S3 firmware using the firmware/build.sh script. Use when the user wants to compile firmware, create a flashable .bin file, flash firmware to a device, change the default build environment or serial port, list available firmware environments, clean build artifacts, or configure build settings. Triggers on: build firmware, flash firmware, make a .bin, upload firmware, esptool, platformio, build.sh, change build config, which environment, serial port."
---

# Firmware Build

Build, merge, and flash BODAQS ESP32-S3 firmware via `firmware/build.sh`.

## Prerequisites

The script requires two tools. If either is missing, the script prints install instructions and exits:

- **PlatformIO CLI** (`pio`) — install with `pipx install platformio`
- **esptool** — install with `pipx install esptool` or `brew install esptool`

## Quick Reference

All commands run from `firmware/`:

| Command | Purpose |
|---|---|
| `./build.sh` | Build + merge (default env) |
| `./build.sh build [env]` | Build + merge for a specific env |
| `./build.sh merge [env]` | Merge only (skip build, reuse existing artifacts) |
| `./build.sh flash [env]` | Build + merge + flash to device |
| `./build.sh clean [env]` | Clean build directory |
| `./build.sh check` | Verify tools, project, port, and device |
| `./build.sh detect` | Scan /dev for connected ESP32-S3 devices |
| `./build.sh list` | List all environments from platformio.ini |

Options: `--port PORT` (or `auto`), `--no-build`, `--env ENV`, `-h`/`--help`.

## Configuration

All defaults are inline at the top of `firmware/build.sh` under the "Configuration" section. An optional `firmware/build.conf` file can override any value if it exists.

When the user asks to change build configuration (default environment, serial port, baud rate, flash offsets, output filename), read [references/configuration.md](references/configuration.md) for the full list of settings, what each controls, and what to prompt the user about.

## Workflow

1. **Run a system check.** Execute `./build.sh check` to verify tools, project files, environment, serial port, connected device, and build state. This catches problems before a build or flash attempt.
2. **Determine the target environment.** If the user doesn't specify, use the default (`DEFAULT_ENV` in build.sh). Run `./build.sh list` to see all options. Ask the user which board they're targeting if unclear.
3. **Build + merge.** Run `./build.sh build [env]`. Produces `bodaqs-firmware.bin` in `firmware/`.
4. **Flash.** Run `./build.sh flash [env]` (builds + merges + flashes in one step), or `./build.sh flash --no-build` to reflash an existing binary.
5. **If flashing fails**, run `./build.sh check` to diagnose, then verify the serial port with `--port` and that the device is connected and in bootloader mode.

## Environments

Environments are defined in `firmware/platformio.ini`. Each maps to a board + set of build flags. Key environments:

- `thingplus_s3_usb_cdcserial_bodaqs_4f` — SparkFun Thing Plus, BODAQS 4F board profile (default)
- `bodaqs_s3_mini_n4r2` — BODAQS V1RC3 custom board (A8)
- `*_as5048_probe` / `*_gps_uart_probe` — diagnostic variants for sensor bringup
- `*_bringup` — minimal diagnostics build

Run `./build.sh list` for the current full list.

## Multi-Board Workflows

When building for multiple boards (e.g., Prototype F and A8/RC3), both environments produce the same output file (`bodaqs-firmware.bin`). Each build overwrites the previous binary — the filename gives no indication of which board it targets.

To avoid confusion:

- **Set per-env `OUTPUT_BIN`** in `build.conf` to keep separate binaries (e.g., `bodaqs-4f.bin` vs `bodaqs-v1rc3.bin`).
- **Flash baud differs by board** — V1RC3 flashes at 460800, Thing Plus at 921600. The script auto-selects based on environment. Override with `FLASH_BAUD` in build.conf if needed.
- **Always specify the env** when flashing: `./build.sh flash bodaqs_s3_mini_n4r2` rather than relying on the default.

## System Check

`./build.sh check` runs a full diagnostic of the build environment. It does not require tools to be installed — it reports what's missing rather than exiting. Use it:

- **Before building** — catches missing tools, bad env names, missing project files
- **Before flashing** — verifies serial port exists and device is connected
- **When troubleshooting** — isolates whether a failure is tools, config, port, or device

The check reports six categories with ✓/✗/! markers:

| Category | What it verifies |
|---|---|
| Tools | PlatformIO CLI and esptool installed with versions |
| Project | platformio.ini, src/, boards/, variants/ directories present |
| Environment | DEFAULT_ENV exists in platformio.ini; build.conf status |
| Serial Port | Configured port exists in /dev |
| Device | ESP32 chip type and MAC (probes via esptool chip-id) |
| Build State | Previous build artifacts and merged binary present |

Exits with code 1 if any check fails, 0 if all pass. Warnings (build.conf missing, no previous build) do not cause a failure.

## Port Detection

Auto-detection is enabled by default (`DEFAULT_PORT="auto"` in build.sh). The script scans `/dev/cu.*` and probes each port with esptool to find a connected ESP32-S3.

**Standalone:** `./build.sh detect` — scans and reports all ESP32-S3 devices found.

**With flash:** Auto-detection runs automatically before flashing. To override with a specific port:
```
./build.sh flash --port /dev/cu.usbmodem1101
```

**How it works:**
1. Lists all `/dev/cu.*` ports (filters out Bluetooth and debug ports)
2. Probes each with `esptool --chip esp32s3 --port <port> chip-id`
3. If exactly one ESP32-S3 responds, uses it automatically
4. If multiple respond, lists them all and uses the first (user can override with `--port`)
5. If none respond, reports failure with a hint to check the connection

To disable auto-detection, set `DEFAULT_PORT` to a specific port (e.g. `/dev/cu.usbmodem1101`) in build.sh or build.conf.
