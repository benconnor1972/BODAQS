#!/usr/bin/env bash
#
# build.sh — Build, merge, and flash BODAQS firmware
#
# Usage:
#   ./build.sh                     Build + merge (default env)
#   ./build.sh build [env]         Build + merge for a specific env
#   ./build.sh merge [env]         Merge only (skip build, use existing artifacts)
#   ./build.sh flash [env]         Build + merge + flash to device
#   ./build.sh clean [env]         Clean build directory for an env
#   ./build.sh check               Verify tools, project, port, and device
#   ./build.sh detect              Scan /dev for connected ESP32-S3 devices
#   ./build.sh list                List available environments
#   ./build.sh help                Show this help
#
# Options (can appear after any command):
#   --port PORT    Serial port for flashing (use 'auto' to detect)
#   --no-build     Skip build step (use with flash to reflash existing binary)
#   --env ENV      Override environment (alternative to positional arg)
#   -h, --help     Show help
#
# Examples:
#   ./build.sh                                              # build default
#   ./build.sh build bodaqs_s3_mini_n4r2                    # build different board
#   ./build.sh flash --port auto                           # auto-detect and flash
#   ./build.sh flash --port /dev/cu.usbmodem2101            # flash to specific port
#   ./build.sh flash bodaqs_s3_mini_n4r2 --no-build         # reflash without rebuild
#   ./build.sh check                                        # verify build environment
#   ./build.sh detect                                       # find connected ESP32-S3
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# All defaults live here. Edit these values to change behavior.
# If a build.conf file exists next to this script, it will be sourced
# afterwards and can override any of these values.

# PlatformIO environment to build (must match an [env:...] in platformio.ini).
# Run './build.sh list' to see all available environments.
DEFAULT_ENV="thingplus_s3_usb_cdcserial_bodaqs_4f"

# ESP32 chip variant passed to esptool.
CHIP="esp32s3"

# Default serial port for flashing. Override per-run with --port.
# Set to "auto" to auto-detect a connected ESP32-S3 on each run.
# Common macOS values: /dev/cu.usbmodem1101, /dev/cu.SLAB_USBtoUART
DEFAULT_PORT="auto"

# Upload baud rate. Leave empty to auto-select per board
# (A8: 460800, Thing Plus: 921600). Set to a specific value to
# force one rate for all boards.
FLASH_BAUD=""

# Flash layout offsets (standard ESP32 no_ota layout):
#   0x00000  bootloader
#   0x08000  partition table
#   0x10000  application firmware
OFFSET_BOOTLOADER="0x0"
OFFSET_PARTITIONS="0x8000"
OFFSET_FIRMWARE="0x10000"

# Name of the merged binary written to the firmware/ directory.
OUTPUT_BIN="bodaqs-firmware.bin"

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Ensure pipx-installed tools (pio) are findable
export PATH="$HOME/.local/bin:$PATH"

# Source optional config overrides (build.conf is not required)
CONFIG_FILE="${SCRIPT_DIR}/build.conf"
if [[ -f "$CONFIG_FILE" ]]; then
  # shellcheck source=build.conf
  source "$CONFIG_FILE"
fi

# Runtime state (populated by arg parser)
ENV="${DEFAULT_ENV}"
PORT="${DEFAULT_PORT}"
SKIP_BUILD=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

print_help() {
  awk 'NR>=3 && /^#/ {sub(/^# ?/, ""); print; next} NR>=3 {exit}' "$0"
  exit 0
}

list_envs() {
  local ini="${SCRIPT_DIR}/platformio.ini"
  if [[ ! -f "$ini" ]]; then
    echo "ERROR: platformio.ini not found at $ini"
    exit 1
  fi
  echo "Available environments (from platformio.ini):"
  echo ""
  while IFS= read -r env; do
    if [[ "$env" == "$DEFAULT_ENV" ]]; then
      printf "  %-55s (default)\n" "$env"
    else
      printf "  %s\n" "$env"
    fi
  done < <(grep '^\[env:' "$ini" | sed 's/^\[env://; s/\]$//')
  echo ""
  echo "Set DEFAULT_ENV in build.sh (or build.conf) to change the default."
}

check_tools() {
  local missing=0
  if ! command -v pio &>/dev/null; then
    echo "ERROR: PlatformIO CLI (pio) not found."
    echo "  Install with:  pipx install platformio"
    missing=1
  fi
  if ! command -v esptool &>/dev/null; then
    echo "ERROR: esptool not found."
    echo "  Install with:  pipx install esptool  (or: brew install esptool)"
    missing=1
  fi
  if [[ $missing -eq 1 ]]; then
    exit 1
  fi
}

# Scan /dev/cu.* for connected ESP32-S3 devices by probing each candidate port
# with esptool. Sets DETECTED_PORT and DETECTED_MAC on success.
# Filters out Bluetooth, debug, and other non-USB serial ports.
detect_port() {
  local candidates=()
  local port

  # Collect candidate USB serial ports (exclude Bluetooth, debug, etc.)
  while IFS= read -r port; do
    case "$port" in
      /dev/cu.Bluetooth-*|/dev/cu.debug-*) ;;
      *) candidates+=("$port") ;;
    esac
  done < <(ls /dev/cu.* 2>/dev/null || true)

  if [[ ${#candidates[@]} -eq 0 ]]; then
    echo "ERROR: No serial ports found in /dev/cu.*"
    echo "  Connect an ESP32-S3 via USB and try again."
    return 1
  fi

  echo "=== Scanning for ESP32-S3 devices ==="
  echo "  Found ${#candidates[@]} serial port(s): ${candidates[*]}"
  echo ""

  local found=0
  local matches=()

  for port in "${candidates[@]}"; do
    # Probe each port — esptool exits non-zero if no ESP32-S3 responds
    local chip_info
    if chip_info=$(esptool --chip "$CHIP" --port "$port" chip-id 2>&1); then
      local chip_type chip_mac
      chip_type=$(echo "$chip_info" | grep -i 'Chip type:' | head -1 | sed 's/^Chip type:[[:space:]]*//')
      chip_mac=$(echo "$chip_info" | grep -i '^MAC:' | head -1 | sed 's/^MAC:[[:space:]]*//')

      if echo "$chip_type" | grep -qi "ESP32-S3"; then
        echo "  ✓  ${port}  —  ${chip_type}  (MAC: ${chip_mac})"
        matches+=("${port}|${chip_mac}")
        found=$((found + 1))
      else
        echo "  -  ${port}  —  ${chip_type} (not ESP32-S3, skipping)"
      fi
    else
      echo "  -  ${port}  —  no device responding"
    fi
  done

  echo ""

  if [[ $found -eq 0 ]]; then
    echo "ERROR: No ESP32-S3 devices found on any serial port."
    echo "  Check that the device is connected and in bootloader mode."
    return 1
  fi

  if [[ $found -eq 1 ]]; then
    # Single match — use it
    local match="${matches[0]}"
    DETECTED_PORT="${match%%|*}"
    DETECTED_MAC="${match##*|}"
    echo "=== Detected: ${DETECTED_PORT} (MAC: ${DETECTED_MAC}) ==="
    return 0
  fi

  # Multiple matches — list them and pick the first
  echo "WARNING: Multiple ESP32-S3 devices found:"
  local i=1
  for match in "${matches[@]}"; do
    local p="${match%%|*}"
    local m="${match##*|}"
    echo "  ${i}. ${p}  (MAC: ${m})"
    i=$((i + 1))
  done
  echo ""
  echo "Using the first device. Use --port to specify a different one."
  local match="${matches[0]}"
  DETECTED_PORT="${match%%|*}"
  DETECTED_MAC="${match##*|}"
  echo "=== Selected: ${DETECTED_PORT} (MAC: ${DETECTED_MAC}) ==="
  return 0
}

# Resolve PORT: if "auto" or empty, run detect_port and set PORT to the result.
resolve_port() {
  if [[ "$PORT" == "auto" || -z "$PORT" ]]; then
    detect_port
    PORT="$DETECTED_PORT"
  fi
}

# Resolve flash baud rate for the current environment.
# If FLASH_BAUD is set (e.g. in build.conf), use it. Otherwise, pick based on env.
resolve_flash_baud() {
  if [[ -n "$FLASH_BAUD" ]]; then
    RESOLVED_BAUD="$FLASH_BAUD"
    return
  fi
  case "$ENV" in
    bodaqs_s3_mini_n4r2*) RESOLVED_BAUD="460800" ;;
    *)                    RESOLVED_BAUD="921600" ;;
  esac
}

do_build() {
  echo "=== Building (env: ${ENV}) ==="
  echo ""
  pio run -e "$ENV"
  echo ""
}

verify_artifacts() {
  local build_dir="${SCRIPT_DIR}/.pio/build/${ENV}"
  local bootloader="${build_dir}/bootloader.bin"
  local partitions="${build_dir}/partitions.bin"
  local firmware="${build_dir}/firmware.bin"

  for f in "$bootloader" "$partitions" "$firmware"; do
    if [[ ! -f "$f" ]]; then
      echo "ERROR: Build artifact not found: $f"
      echo "  Run './build.sh build ${ENV}' first."
      exit 1
    fi
  done

  echo "=== Build artifacts ==="
  ls -lh "$bootloader" "$partitions" "$firmware"
  echo ""

  ARTIFACT_BOOTLOADER="$bootloader"
  ARTIFACT_PARTITIONS="$partitions"
  ARTIFACT_FIRMWARE="$firmware"
}

do_merge() {
  verify_artifacts

  local output="${SCRIPT_DIR}/${OUTPUT_BIN}"

  echo "=== Merging into ${OUTPUT_BIN} ==="
  echo "  bootloader  @ ${OFFSET_BOOTLOADER}  (${ARTIFACT_BOOTLOADER##*/})"
  echo "  partitions  @ ${OFFSET_PARTITIONS}  (${ARTIFACT_PARTITIONS##*/})"
  echo "  firmware    @ ${OFFSET_FIRMWARE}  (${ARTIFACT_FIRMWARE##*/})"
  echo ""

  esptool --chip "$CHIP" merge-bin \
    -o "$output" \
    "$OFFSET_BOOTLOADER" "$ARTIFACT_BOOTLOADER" \
    "$OFFSET_PARTITIONS" "$ARTIFACT_PARTITIONS" \
    "$OFFSET_FIRMWARE" "$ARTIFACT_FIRMWARE"

  echo ""
  echo "=== Merged binary ==="
  ls -lh "$output"
  echo ""
}

do_flash() {
  local output="${SCRIPT_DIR}/${OUTPUT_BIN}"

  if [[ ! -f "$output" ]]; then
    echo "ERROR: ${OUTPUT_BIN} not found. Run './build.sh build' first."
    exit 1
  fi

  if [[ -z "$PORT" ]]; then
    echo "ERROR: No serial port specified."
    echo "  Set DEFAULT_PORT in build.sh (or build.conf) or use --port /dev/cu.xxx"
    exit 1
  fi

  resolve_flash_baud

  echo "=== Flashing ==="
  echo "  binary:  ${OUTPUT_BIN}"
  echo "  port:    ${PORT}"
  echo "  baud:    ${RESOLVED_BAUD}"
  echo "  offset:  0x0"
  echo ""

  esptool --chip "$CHIP" --port "$PORT" --baud "$RESOLVED_BAUD" \
    write-flash 0x0 "$output"

  echo ""
  echo "=== Flash complete ==="
}

do_clean() {
  echo "=== Cleaning (env: ${ENV}) ==="
  pio run -e "$ENV" -t clean
  echo ""
  echo "=== Clean complete ==="
}

do_check() {
  local pass=0
  local fail=0
  local warn=0

  ok()   { echo "  ✓  $1"; pass=$((pass + 1)); }
  bad()  { echo "  ✗  $1"; fail=$((fail + 1)); }
  wa()   { echo "  !  $1"; warn=$((warn + 1)); }

  echo "=== System Check ==="
  echo ""

  # --- Tools ---
  echo "Tools"
  if command -v pio &>/dev/null; then
    local pio_ver
    pio_ver=$(pio --version 2>&1 | head -1)
    ok "PlatformIO CLI: ${pio_ver}"
  else
    bad "PlatformIO CLI (pio) not found — install with: pipx install platformio"
  fi

  if command -v esptool &>/dev/null; then
    local et_ver
    et_ver=$(esptool version 2>&1 | head -1)
    ok "esptool: ${et_ver}"
  else
    bad "esptool not found — install with: pipx install esptool (or: brew install esptool)"
  fi
  echo ""

  # --- Project files ---
  echo "Project"
  local ini="${SCRIPT_DIR}/platformio.ini"
  if [[ -f "$ini" ]]; then
    ok "platformio.ini found"
  else
    bad "platformio.ini not found at ${ini}"
  fi

  if [[ -d "${SCRIPT_DIR}/src" ]]; then
    local src_count
    src_count=$(find "${SCRIPT_DIR}/src" -name '*.cpp' -o -name '*.h' 2>/dev/null | wc -l | tr -d ' ')
    ok "src/ directory (${src_count} source files)"
  else
    bad "src/ directory not found"
  fi

  if [[ -d "${SCRIPT_DIR}/boards" ]]; then
    local board_count
    board_count=$(find "${SCRIPT_DIR}/boards" -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
    ok "boards/ directory (${board_count} board definitions)"
  else
    wa "boards/ directory not found (custom boards may not be available)"
  fi

  if [[ -d "${SCRIPT_DIR}/variants" ]]; then
    ok "variants/ directory found"
  else
    wa "variants/ directory not found"
  fi
  echo ""

  # --- Environment ---
  echo "Environment"
  if [[ -f "$ini" ]]; then
    if grep -q "^\[env:${ENV}\]" "$ini"; then
      ok "Environment '${ENV}' exists in platformio.ini"
    else
      bad "Environment '${ENV}' not found in platformio.ini"
      echo "     Run './build.sh list' to see available environments."
    fi
  fi

  if [[ -f "${SCRIPT_DIR}/build.conf" ]]; then
    ok "build.conf override file present"
  else
    wa "No build.conf — using inline defaults from build.sh"
  fi

  resolve_flash_baud
  if [[ -n "$FLASH_BAUD" ]]; then
    ok "Flash baud: ${RESOLVED_BAUD} (forced via FLASH_BAUD)"
  else
    ok "Flash baud: ${RESOLVED_BAUD} (auto-selected for '${ENV}')"
  fi
  echo ""

  # --- Serial port ---
  echo "Serial Port"
  if [[ -n "$PORT" ]]; then
    if [[ "$PORT" == "auto" ]]; then
      ok "Port set to auto-detect (scans /dev/cu.* at flash time)"
    elif [[ -e "$PORT" ]]; then
      ok "Port ${PORT} exists"
    else
      bad "Port ${PORT} does not exist"
      echo "     Available ports:"
      ls /dev/cu.* 2>/dev/null | sed 's/^/       /' || true
    fi
  else
    wa "No port configured (set DEFAULT_PORT in build.sh or use --port)"
  fi
  echo ""

  # --- Connected device ---
  echo "Device"
  if [[ "$PORT" == "auto" ]]; then
    wa "Auto-detect mode — run './build.sh detect' to scan for devices"
  elif [[ -n "$PORT" && -e "$PORT" ]]; then
    local chip_info
    if chip_info=$(esptool --chip "$CHIP" --port "$PORT" chip-id 2>&1); then
      local chip_type chip_mac
      chip_type=$(echo "$chip_info" | grep -i 'Chip type:' | head -1 | sed 's/^Chip type:[[:space:]]*//')
      chip_mac=$(echo "$chip_info" | grep -i '^MAC:' | head -1 | sed 's/^MAC:[[:space:]]*//')
      ok "Device connected: ${chip_type:-unknown}"
      ok "  MAC: ${chip_mac:-N/A}"
    else
      wa "No device responding on ${PORT} (may not be in bootloader mode)"
    fi
  else
    wa "Cannot probe device (port not available)"
  fi
  echo ""

  # --- Build state ---
  echo "Build State"
  local build_dir="${SCRIPT_DIR}/.pio/build/${ENV}"
  if [[ -d "$build_dir" ]]; then
    ok "Build directory exists for '${ENV}'"

    local artifacts_found=1
    for f in bootloader.bin partitions.bin firmware.bin; do
      if [[ ! -f "${build_dir}/${f}" ]]; then
        artifacts_found=0
      fi
    done
    if [[ $artifacts_found -eq 1 ]]; then
      ok "Build artifacts present (bootloader, partitions, firmware)"
    else
      wa "Build directory exists but some artifacts missing"
    fi
  else
    wa "No previous build for '${ENV}' — run './build.sh build' first"
  fi

  local output="${SCRIPT_DIR}/${OUTPUT_BIN}"
  if [[ -f "$output" ]]; then
    local size
    size=$(ls -lh "$output" | awk '{print $5}')
    ok "Merged binary: ${OUTPUT_BIN} (${size})"
  else
    wa "No merged binary — run './build.sh build' to create ${OUTPUT_BIN}"
  fi
  echo ""

  # --- Summary ---
  echo "=== Summary: ${pass} passed, ${fail} failed, ${warn} warnings ==="
  if [[ $fail -gt 0 ]]; then
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

COMMAND="build"
POSITIONAL=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      print_help
      ;;
    --port)
      PORT="$2"
      shift 2
      ;;
    --env)
      ENV="$2"
      shift 2
      ;;
    --no-build)
      SKIP_BUILD=1
      shift
      ;;
    --)
      shift
      POSITIONAL+=("$@")
      break
      ;;
    -*)
      echo "ERROR: Unknown option: $1"
      echo "Run './build.sh help' for usage."
      exit 1
      ;;
    *)
      POSITIONAL+=("$1")
      shift
      ;;
  esac
done

# First positional = command, second = env
if [[ ${#POSITIONAL[@]} -ge 1 ]]; then
  COMMAND="${POSITIONAL[0]}"
fi
if [[ ${#POSITIONAL[@]} -ge 2 ]]; then
  ENV="${POSITIONAL[1]}"
fi

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

case "$COMMAND" in
  detect)
    check_tools
    detect_port
    ;;

  check)
    do_check
    ;;

  list|envs)
    list_envs
    ;;

  help)
    print_help
    ;;

  *)
    check_tools
    case "$COMMAND" in
      build)
        if [[ $SKIP_BUILD -eq 0 ]]; then
          do_build
        fi
        do_merge
        resolve_flash_baud
        echo "Done. Flash with:"
        echo "  ./build.sh flash"
        echo ""
        echo "Or manually:"
        echo "  esptool --chip ${CHIP} --port ${PORT:-<port>} --baud ${RESOLVED_BAUD} write-flash 0x0 ${SCRIPT_DIR}/${OUTPUT_BIN}"
        ;;

      merge)
        do_merge
        ;;

      flash)
        resolve_port
        if [[ $SKIP_BUILD -eq 0 ]]; then
          do_build
        fi
        do_merge
        do_flash
        ;;

      clean)
        do_clean
        ;;

      *)
        echo "ERROR: Unknown command: $COMMAND"
        echo "Run './build.sh help' for usage."
        exit 1
        ;;
    esac
    ;;
esac
