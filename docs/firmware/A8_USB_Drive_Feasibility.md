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

- #194-#196 now have an integrated, opt-in development build with automatic
  cable/UPLOAD activation, exclusive SD ownership, asynchronous exit/cancellation,
  host-eject suppression, card-removal errors, and explicit reclaim retry. OLED,
  menu, web UI, and API expose transfer status. Active USB sessions prevent idle
  sleep; sleep is refused while storage belongs to the computer.
- #198 now has mounted-volume discovery, validated identity markers, persistent
  local pairing, and acquisition through existing enabled filesystem sources.
- #199 has usage/identity/API documentation and automated lifecycle/import tests.
  Integrated hardware and cross-platform acceptance remain pending.

Normal logger firmware continues to use its existing USB configuration. Build
the integration explicitly with `pio run -d firmware -e bodaqs_a8_usb_drive_dev`.
This environment pins Espressif32 6.12.0 and enables USB-OTG CDC/MSC. It is not
enabled in normal release environments and has not been flashed. Compilation
is not evidence that physical USB/SD operation works.
No ticket has been closed. The diagnostic has now been flashed for the
[Windows bench](A8_USB_Windows_Bench_2026-11-10.md); its data-path checks passed,
but the software bootloader transition failed. Restoration was deferred at the
user's request for manual reflashing; the recovery requirement remains unresolved.

## Automated validation on Windows, 2026-11-10

| Check | Result |
| --- | --- |
| Tracked Python analysis test set | 578 passed, 1 skipped |
| Import agent tests | 167 passed, 1 skipped; covers mounted acquisition, USB identity/pairing, concurrent watcher access, and whole-volume containment |
| Firmware host harness and four runtime fixtures | Passed, including ownership and USB upload lifecycle checks |
| Isolated A8 USB diagnostic build | Passed |
| Normal A8 build | Passed |
| Prototype F build | Passed |
| Opt-in integrated A8 USB development build | Passed; not flashed |
| Real USB/SD and Windows enumeration/CDC | Diagnostic data-path checks passed; see Windows bench report |
| Firmware restoration/recovery | Software transition failed; user chose manual reflashing, recovery check unresolved |
| macOS/Linux and integrated physical acceptance | Pending |

The broad local Python run also collected older untracked tests previously hidden
by the old branch's ignore rules: 635 passed, 1 skipped, and 10 failures in those
untracked legacy tests. The tracked test set was then run separately and passed;
those local files were preserved. Existing deprecation warnings remain.

Standards and specification reviews each identified the same two defects: an
unmigrated transform-reload filesystem reference and starvation with a configured
import scan limit. Both were fixed; review confirmed resolution and the added
scan-limit regression test passes. No further concrete defect was reported in
the initial checkpoint. The continuation also reproduced and fixed in-process
contention between USB acquisition and the watcher; its regression test passes.
The continuation review identified a card-volume containment gap for recording
subfolders. Pairing and both automatic/manual acquisition now validate the whole
mounted volume; regression tests reject sibling workspace/output paths on it.
Raw USB pin assignments also use the selected canonical board profile. No hard
standards violation was found; two optional interface-design observations remain.

USB session checks cover both connection orders, actual local-lease draining,
quiet-time boundaries, cancellation, ten minutes of simulated traffic without a
forced exit, timer wraparound, eject/reconnect, card removal, and reclaim retry.
This does not establish completion of the physical acceptance gates.

## Remaining integrated bench acceptance

After reliable normal updating and recovery have been restored, test the opt-in
build on disposable media. Do not interpret the diagnostic's Windows result as
an integrated pass. Record each host OS, A8 revision, firmware SHA, and SD card.

- Check both cable/mode activation orders, normal boot, recording entry refusal,
  and simultaneous CDC visibility. Confirm normal updating and recovery.
- Complete an existing Wi-Fi transfer before USB exposure; reject new SD work
  while shared and verify independent status, cancel, and retry controls.
- Check writable browse/copy/add/delete and independent checksums in both
  directions. Exercise timed exit during quiet, continuous reads and writes,
  cancellation, and record/verify a new session after successful reclaim.
- Exercise host eject, reconnect, missing/full cards, physical removal/reinsert,
  cable loss, I/O failure, and remount failure/retry without automatic formatting.
- Check discovery and first-use pairing, repeated/reconnected acquisition,
  multiple loggers, ZIP/BDQ import, source retention, and manual fallback.
- Repeat host-specific enumeration, ejection, discovery, and transfer checks on
  Windows, macOS, and Linux. A cache-loss guarantee is not an acceptance claim.

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
or unmounting the card themselves. The development transport connects to this
interface only in the opt-in build; the production default remains gated on
physical feasibility and recovery.

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

## Repeatable physical feasibility procedure

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

An A8 was subsequently connected and tested. Refer to the Windows bench report
for performed checks and the remaining recovery blocker; hardware evidence is
still incomplete for #192 and its dependent production USB tickets.
