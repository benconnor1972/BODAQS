# Build Configuration Reference

All configuration lives in the "Configuration" section at the top of `firmware/build.sh`. An optional `firmware/build.conf` file can override any value — if it exists, it is sourced after the inline defaults.

## Settings

### DEFAULT_ENV

**What it controls:** Which PlatformIO environment is built when no env is specified on the command line.

**Default:** `thingplus_s3_usb_cdcserial_bodaqs_4f`

**When to prompt the user:** When they ask to change the default board, or when they're unsure which environment to use. Run `./build.sh list` to show available options. Ask which board they're targeting:

- SparkFun ESP32-S3 Thing Plus → `thingplus_s3_usb_cdcserial_bodaqs_4f` (BODAQS 4F profile)
- BODAQS V1RC3 custom board (A8) → `bodaqs_s3_mini_n4r2`
- Diagnostic/probe builds → envs ending in `_probe` or `_bringup`

### CHIP

**What it controls:** ESP32 chip variant passed to esptool for merge and flash operations.

**Default:** `esp32s3`

**When to change:** Only if switching to a different ESP32 family (e.g., `esp32`, `esp32c3`). All BODAQS boards use the ESP32-S3.

### DEFAULT_PORT

**What it controls:** Serial port used for flashing when `--port` is not passed on the command line.

**Default:** `auto`

**Special value:** `auto` (the default) auto-detects a connected ESP32-S3 on each run. The script scans `/dev/cu.*`, probes each port with esptool, and uses the first ESP32-S3 that responds. See the Port Detection section in SKILL.md.

**When to prompt the user:** When flashing fails with a port error, or when the user mentions a different USB port or device. Common macOS values:

- `/dev/cu.usbmodem1101` — typical ESP32-S3 USB CDC
- `/dev/cu.usbmodem2101` — second USB CDC device
- `/dev/cu.SLAB_USBtoUART` — CP210x UART bridge (older boards)
- `auto` — auto-detect by scanning /dev and probing with esptool

To discover available ports: `ls /dev/cu.*` with the device plugged in, or run `./build.sh detect`.

### FLASH_BAUD

**What it controls:** Upload baud rate for esptool flashing.

**Default:** Empty (auto-selected per board — 460800 for V1RC3, 921600 for Thing Plus)

**When to change:** Set to a specific value to force one rate for all boards. If flash uploads are unreliable, drop to `460800`. Higher speeds (`1500000`, `2000000`) work on some boards but can fail with long USB cables.

**Board-specific note:** The V1RC3 board definition specifies 460800 in its board JSON. When `FLASH_BAUD` is empty, build.sh auto-selects this rate for `bodaqs_s3_mini_n4r2*` environments. Setting `FLASH_BAUD` explicitly overrides this for all boards.

### OFFSET_BOOTLOADER, OFFSET_PARTITIONS, OFFSET_FIRMWARE

**What they control:** Flash addresses where each binary component is placed during the merge step.

**Defaults (no_ota partition scheme):**

| Setting | Default | Contents |
|---|---|---|
| `OFFSET_BOOTLOADER` | `0x0` | Bootloader |
| `OFFSET_PARTITIONS` | `0x8000` | Partition table |
| `OFFSET_FIRMWARE` | `0x10000` | Application firmware |

**When to change:** Only if `board_build.partitions` in `platformio.ini` is changed from `no_ota.csv` to a different partition scheme. The partition table CSV defines where each component lives. Verify offsets against the partition CSV before changing.

### OUTPUT_BIN

**What it controls:** Filename of the merged binary written to `firmware/`.

**Default:** `bodaqs-firmware.bin`

**When to change:** When building for multiple boards, set a per-env filename to avoid overwriting. Both environments produce the same `bodaqs-firmware.bin` by default — each build overwrites the previous binary. For multi-board workflows, use distinct names (e.g., `bodaqs-4f.bin` vs `bodaqs-v1rc3.bin`) via `build.conf`.

## Optional build.conf File

If `firmware/build.conf` exists, it is sourced after the inline defaults and can override any variable. This lets users keep customizations out of the script itself. Example:

```bash
# firmware/build.conf
DEFAULT_ENV="bodaqs_s3_mini_n4r2"
DEFAULT_PORT="/dev/cu.usbmodem2101"
OUTPUT_BIN="bodaqs-v1rc3.bin"
```

The file is optional — the script works standalone with inline defaults if `build.conf` does not exist.
