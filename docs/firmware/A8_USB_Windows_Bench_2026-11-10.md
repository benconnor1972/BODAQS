# A8 USB drive Windows bench, 2026-11-10

Status: data-path checks passed; firmware restoration deferred at the user's
request for manual reflashing. The USB bootloader/recovery failure remains open.

Related work: [specification #191](https://github.com/benconnor1972/BODAQS/issues/191),
[feasibility #192](https://github.com/benconnor1972/BODAQS/issues/192).

## Equipment and recovery copy

- A8 ESP32-S3 revision 0.2, 4 MB embedded flash, 2 MB PSRAM.
- Device MAC: `1c:db:d4:bc:5e:2c`; initial hardware CDC port COM3.
- Windows 11 Home, version 10.0.26200, build 26200.
- Diagnostic environment: `bodaqs_a8_usb_drive_diagnostic`, built from the
  main-based feature branch, PlatformIO Espressif32 6.12.0 / Arduino-ESP32 2.0.17.
- The diagnostic exposed CDC on COM5 and a BODAQS USB storage device on F:.
  The association with the USB physical disk was verified before file writes.
- Exposed filesystem capacity: 15,613,296,640 bytes. Existing recordings were
  retained; no formatting or automatic filesystem repair was performed.
- A complete 4,194,304-byte flash image was saved before diagnostic flashing,
  including the original firmware, partition table, and on-chip settings.
  Flash encryption and secure boot were disabled; no eFuses were changed.
- Recovery artifacts and raw bench logs are private local files under
  `%LOCALAPPDATA%/BODAQS/bench/a8-usb-2026-11-10-1cdbd4bc5e2c-01/`, outside Git.
  The backup is `original-flash-4mb.bin`, SHA-256
  `ec05d7f6f242cb342529a89f950119c20f7258f33db2e6a657940e42fdb9338f`.

## Observations

| Check | Observation |
| --- | --- |
| Diagnostic flash from hardware CDC | Passed; esptool verified written data |
| Normal diagnostic state | Serial help and local SD listing worked; Windows exposed a removable-drive slot without accessible media |
| Enter UPLOAD | Card became accessible on F:; device model and disk-to-drive mapping matched the diagnostic |
| CDC alongside MSC | Serial help responded during USB storage use |
| Computer-to-card write | Passed: 4,194,341 bytes written and flushed in approximately 9.08 seconds |
| Card-to-computer read | Passed using Windows unbuffered I/O to bypass its file cache; initial read took approximately 7.70 seconds |
| Automatic idle reclaim | Passed: normal/local storage message approximately 3.05 seconds after exit request, followed by successful local SD listing |
| Re-enter after reclaim | Passed; test file remained readable with matching contents |
| Exit during sustained reads | Remained pending for 4.25 seconds while uncached USB reads continued; no premature normal-state message |
| Cancel pending exit | Acknowledged cancellation; continued uncached reads/checksum succeeded |
| Computer-side eject | F: became unavailable with Windows error 21 (not ready); CDC remained usable |
| Suppress immediate re-exposure | Sending UPLOAD entry again while still in ejected UPLOAD did not expose the card |
| Mode cycle after host eject | Drive eventually became accessible again, with matching checksum; Windows readiness was noticeably delayed |
| Rename and delete | Passed using only the newly created test file; subsequent local listing confirmed its removal |
| Restore original firmware | Deferred at user's request for manual reflashing; not a passed check |

The generated test file was `BODAQS_USB_BENCH_20261110_01.bin`, deliberately sized
to include a non-sector-aligned tail. Independent expected and uncached readback
SHA-256 values matched:

`271f3009793c53f509d9fb997b38a75aa068a59230d6983652933701e08278d8`

Checksum validation was repeated after reclaim/re-entry, cancellation, host eject,
and rename. The renamed test file was deleted and final local SD listing showed
the original recordings and no bench file. Only the new test file was renamed or
deleted. Windows may maintain its own volume metadata.

## Problems requiring follow-up

1. **Bootloader transition failed.** An ordinary esptool connection to application
   CDC COM5 could not enter download mode. Opening CDC at 1200 baud then removed
   the device, but a usable download port did not reappear. Windows reported an
   unknown USB device with a descriptor-request failure. Physical power cycling
   was requested before restoration. Ordinary power cycling, manual BOOT/RESET,
   reconnecting with BOOT held, and an administrator-authorized restart of only
   the failed Windows USB device did not restore enumeration. A full USB-and-
   battery disconnection also failed to restore enumeration. The USB hub was
   inspected and had only the failed logger node attached; a proposed hub
   restart did not run because its Windows administrator request was cancelled.
   A different known-good USB data cable or another host was requested as the
   next isolation check. The user then asked to stop restoration attempts and
   stated they would reflash manually. No further device operations were made.
   The
   saved original image has not been lost, but the original-firmware
   restore/recovery acceptance check is still open. Its size, SHA-256, bootloader
   header, partition table, and application header were rechecked successfully.
   The complete backup is a whole-flash image for address `0x00000000`, not an
   application-only image for `0x00010000`. Diagnostic firmware remains the last
   image written by this bench session; no restoration write was started.
2. **Windows readiness latency.** Enumeration/readiness after mode changes and
   ejection was sometimes slow. One uncached 4 MB read after re-entry took about
   32.19 seconds overall versus 7.70 seconds initially. This measurement includes
   host readiness and I/O, so it does not establish steady-state SD throughput.
   Characterize host media-change signaling and readiness before production use.

Espressif documents manual download-mode recovery using BOOT and RESET in its
[USB CDC/DFU guide](https://docs.espressif.com/projects/arduino-esp32/en/latest/tutorials/cdc_dfu_flash.html).
Use the actual A8 board's controls/wiring rather than assuming the navigation
buttons are BOOT or RESET. An ordinary power cycle was requested first.

## Limits of this evidence

These checks validate the isolated diagnostic on one physical A8 and Windows.
They do not validate production ownership integration, recording after reclaim,
Import Manager auto-discovery, Wi-Fi arbitration, macOS/Linux, unexpected physical
cable/card removal, or full failure recovery. No filesystem checks or throughput
guarantees are inferred from successful transfers. Delays and quiet intervals do
not guarantee that unseen computer write caches have been flushed.

Do not close #192 or enable its dependent production USB tickets until restoration
and the serial/firmware-update recovery requirements are resolved.
