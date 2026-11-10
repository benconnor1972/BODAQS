# A8 USB drive implementation checkpoint

Parent specification: [#191](https://github.com/benconnor1972/BODAQS/issues/191).
Development branch: `feat/a8-usb-drive-access`, based on `origin/main` at
`42bc399`, independently of CAN-FD.

## Current scope

- [#192](https://github.com/benconnor1972/BODAQS/issues/192): an isolated native
  USB CDC + MSC diagnostic is ready for physical testing. It compiles against
  Arduino-ESP32 2.0.17 with PlatformIO Espressif32 6.12.0. No framework upgrade
  was required to compile raw SDMMC read/write callbacks.
- [#193](https://github.com/benconnor1972/BODAQS/issues/193): the logger uses a
  guarded filesystem and ownership admission boundary. An existing file retains
  its local lease through close, including children of a directory scan. Pending
  handoff rejects new access, waits for leases to finish, unmounts locally, and
  only then reports external ownership. Remount failure blocks local access.
- [#197](https://github.com/benconnor1972/BODAQS/issues/197): manual mounted-card
  acquisition is available through Import Manager's local-source context menu.
  Completed copies enter the existing local import pipeline; originals remain.

Normal logger firmware continues to use its existing USB configuration. Production
USB drive activation, asynchronous exit/cancellation, lifecycle recovery, automatic
discovery/pairing, and full platform acceptance remain the later tickets #194-#196
and #198-#199. Compilation is not evidence that physical USB/SD operation works.
No ticket has been closed and no device has been flashed.

## Ownership interface

Call storage handoff/reclaim functions on the main loop. A request is admitted
only in UPLOAD mode, with mounted storage and no recording. It closes admission
immediately; service from the storage loop grants external ownership after all
local files/operations finish. Cancellation is possible while waiting. The API
status storage object includes an additive `ownership` field; existing fields and
formats are preserved. UI file listing and machine-readable session operations
report paused access while external ownership is pending or active.

An external transport must wait for the `external` state before initializing raw
card access. Stop/deinitialize that transport before requesting local reclaim.
USB callbacks must queue requests for main-loop processing rather than mounting
or unmounting the card themselves. The production transport is not connected to
this interface until the feasibility gate is satisfied.

## Isolated diagnostic

This is a diagnostic replacement firmware, not a logger release. Use a disposable
SD card containing no irreplaceable recordings. Flashing temporarily replaces the
logger application; obtain device-owner authorization and retain a known working
normal firmware image and configuration backup first.

Build without flashing:

```powershell
pio run -d firmware -e bodaqs_a8_usb_drive_diagnostic
```

Artifacts are the diagnostic environment's `firmware.bin`, `bootloader.bin`, and
`partitions.bin` under the PlatformIO build directory. Do not confuse this image
with the normal A8 build. Flash only when explicitly authorized and target the
identified A8 port, never an automatically guessed unrelated port:

```powershell
pio run -d firmware -e bodaqs_a8_usb_drive_diagnostic -t upload --upload-port COM_PORT
pio device monitor --port COM_PORT --baud 115200
```

In the native USB serial monitor, send a newline for help:

- `u`: enter diagnostic UPLOAD and export the card for exclusive computer access.
- `x`: request exit, waiting at least three seconds and one second without I/O.
- `c`: cancel the pending exit.
- `l`: list local card files while in normal diagnostic mode.
- `r`: retry a failed local remount after USB storage is unavailable.

The diagnostic is deliberately isolated from logging, sensors, Wi-Fi, and the
production ownership layer. It uses the A8's existing SDMMC pin assignments,
internal DMA memory, and serialized raw-sector callbacks. It handles partial
sector transfers without treating USB buffers as SDMMC DMA memory. It is not
the acceptance implementation for all host-eject or cable-loss behavior.

## Physical feasibility procedure (not yet performed)

1. Identify the A8, disposable SD card, host OS, firmware/toolchain versions,
   known-good recovery firmware, and authorized flashing port.
2. Check native serial help and normal-mode local listing. Confirm no mounted
   writable USB medium before `u`.
3. Enter `u`, confirm enumeration/capacity and compare independent checksums for
   files copied from the card. Copy known files onto it and verify their contents.
4. Finish computer writes; optionally eject on the computer, then use `x` and
   verify the local listing after reclaim. The delay does not flush host caches.
5. Repeat with sustained read/write activity and cancel exit with `c`; verify
   the drive remains usable. Exercise remount retry using disposable media.
6. Confirm USB serial remains available alongside MSC. Restore known-good normal
   firmware using ordinary updating and separately verify recovery flashing.
7. Record observations and failures. Repeat platform-dependent checks on Windows,
   macOS, and Linux before claiming cross-platform support.

The only serial device detected during development was an unrelated Marlin port;
no A8 feasibility test or flashing was attempted. Hardware evidence is required
before completing #192 and enabling its dependent production USB tickets.
