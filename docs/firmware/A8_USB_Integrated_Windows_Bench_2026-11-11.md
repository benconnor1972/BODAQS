# A8 integrated USB Windows bench, 2026-11-11

Firmware tested: `bodaqs_a8_usb_drive_dev`, source `90a1fa9`, flashed manually
by the user from the supplied merged-image ZIP. ESP32-S3 A8 identity
`1c:db:d4:bc:5e:2c`, Espressif32 6.12.0 / Arduino-ESP32 2.0.17.
The agent did not flash or reset the logger through USB.

## Observations

- The user initially reported no drive on two computers despite cable and mode
  cycling. The logger displayed `USB active` and periodically `SD: not ready`.
- On the connected Windows host, no USB disk was initially exposed. After an
  observed unplug/reconnect, Device Manager reported `Unknown USB Device (Port
  Reset Failed)`, problem code 43. No CDC or MSC interface enumerated.
- While battery powered, the logger continued to display `USB active` after
  USB was unplugged. The displayed state therefore did not establish a live
  host connection.
- A normal user-performed restart with USB connected restored enumeration in
  NORMAL mode: BODAQS composite device, CDC COM5, and the MSC interface were
  healthy. No usable medium was exposed in NORMAL mode.
- Entering UPLOAD from that fresh boot exposed the card as F:, FAT32, physical
  size 15,634,268,160 bytes and filesystem capacity 15,613,296,640 bytes.
- Exiting UPLOAD and unplugging/reconnecting in NORMAL mode preserved healthy
  CDC/MSC enumeration. The USB disk reported `No Media`, size zero, as expected.
- Entering UPLOAD again and unplugging/reconnecting while remaining in UPLOAD
  reproduced a narrower failure: composite USB and CDC COM5 were healthy, but
  the MSC interface failed with problem code 10, status `0xC0000001`, and no
  USB disk/volume was exposed. An exit request still reached NORMAL/Ready.
  A blocked SD reclaim is therefore not required to reproduce the failure.

The initial port-reset failure cleared after the restart. Its root cause is
unresolved; successful startup does not establish reliable recovery from every
disconnect. No transfers, source-file modifications, formatting, repair, or
firmware-update recovery checks were performed during this investigation.

## OLED warning correction

`UI.cpp::makeBoardWarning_()` previously treated every unmounted local card as
an SD fault. USB deliberately unmounts that filesystem. The warning now ignores
the External and Reclaiming ownership states; missing cards and failed local
remounts still produce a warning. This correction changes the display only and
does not fix USB enumeration or guarantee cable-disconnect detection. The
observations above were made with the original `90a1fa9` image, before flashing
this display correction.

## Reconnect probe

A temporary `BODAQS_USB_DIAGNOSTICS` build records USB start/stop/suspend/resume
counters, configured/connected/suspended flags, ownership, media admission,
read/write/error counts, and raw I/O lock timeouts on CDC at 115200 baud. It
does not alter the reconnect policy. Its `[DEBUG-a8usb]` summaries are emitted
at most once per second and only with a serial monitor attached. It must not
be presented as a reconnect fix without repeating the physical reproduction.

Probe artifact: `firmware/packages/a8-usb-reconnect-probe-20261111/application.bin`,
application-only address `0x00010000`, using the already-installed A8 partition
layout. Image checksum and validation hash passed. The normal A8, USB development,
and probe target builds passed; this is not on-device evidence for the display
correction. The user was asked to perform the application update manually.

After that update, capture only the tagged telemetry with:

```powershell
& 'C:/Users/Ben Connor/.platformio/penv/Scripts/python.exe' `
  .scratch/a8-usb-drive-access/monitor_reconnect_probe.py --seconds 12
```

Record a NORMAL baseline, then fresh UPLOAD, then the same UPLOAD cable cycle.
Compare USB event/transfer counter changes with Windows MSC problem status.
The reader uses 115200 baud, filters by the logger's USB identity, and does not
perform a bootloader reset. No credentials or file contents are captured.

### Probe follow-up

The user manually loaded the serial probe. Nine NORMAL-mode summaries confirmed
`connected=1 mounted=1 suspended=0`, logger ownership, no exposed medium, and
zero read/write failures or lock timeouts. On a subsequent UPLOAD cable cycle,
Windows instead reported `Device Descriptor Request Failed` and CDC disappeared.
The serial-only probe therefore could not report the failed state. No post-failure
counter values are available; zero baseline errors do not establish zero errors
during the failure.

A read-only RAM-counter attempt through ROM was prepared but could not connect:
after the user's BOOT/RESET and cable reconnection, no ROM serial port enumerated.
No RAM read, stub upload, or flash write took place. Normal PCB RESET restored the
application screen but did not restore USB enumeration. A complete cold-start
download-mode check was requested next; repeated reset attempts are not a fix.

An OLED revision of the same probe is available at
`firmware/packages/a8-usb-oled-probe-20261111/application.bin`, application address
`0x00010000`. The Upload screen is titled `USB probe` and updates four rows:

- `C/M/S/B`: connected/configured/suspended/I/O busy flags.
- `U/D/S/R`: configured/unmounted/suspended/resumed USB event counts.
- `R/W/E`: raw read/write/failure counts.
- `L/rc`: raw I/O lock timeouts/latest SD error in hexadecimal.

These diagnostics work without an attached serial monitor, including when USB
enumeration fails. They are guarded by `BODAQS_USB_DIAGNOSTICS`; ordinary builds
retain their existing Upload-screen layout. The OLED probe compiled successfully
but has not yet been flashed or tested on the device. A future reproduction
should keep browser flashers and serial monitors closed to remove their CDC
line-state transitions from the test.
Normal A8 and integrated USB development builds also passed after the OLED
diagnostic guards were added.

The user then performed one cold start with USB and battery disconnected for
10 seconds and BOOT held while power/USB were restored. Windows still exposed
no A8 USB or serial device, including after an additional enumeration wait.
ROM entry could not be confirmed. Recovery attempts were stopped rather than
repeating resets. The OLED probe remains unflashed. Neither a post-failure RAM
snapshot nor a reconnect fix has been verified. Because download-mode enumeration
is unconfirmed, the observations do not isolate the cause to application software
versus boot entry, power, or the physical USB path. The earlier failed-state
snapshots and successful fresh-boot mount remain valid observations.

### OLED probe installation and identity verification

The user subsequently flashed the OLED probe at `0x010000`. Initially no
diagnostic rows were visible because the user was viewing the unchanged home
screen's large UPLOAD banner. The diagnostic view is reached with navigation
RIGHT to the main menu, then selecting `Upload: OFF/ON` and pressing ENTER/RIGHT.
The user confirmed that this menu page shows `USB probe` and all four rows.
No reflash was needed to resolve the display confusion.

Before resolving the view mismatch, hardware BOOT/RESET successfully exposed
ROM download CDC COM3. A read-only, no-stub, no-reset esptool command read 512
bytes from flash address `0x10000`. They matched the supplied OLED application
header exactly, including ELF SHA
`88817ab5be8bde784fe94df02af83b00bd2daff533280a16700f48e358ddd4b8`.
This confirms the intended build at the intended address; it is not a whole-flash
verification. No firmware was written by the agent. Adafruit's current frontend
parses offsets in base 16, so the user's `010000` entry was correct.

A distinct alias for the same image is
`firmware/packages/a8-usb-oled-probe-20261111/bodaqs-a8-OLED-PROBE-f740043b.bin`.
Its complete SHA-256 remains
`f740043b696b036bf875d633446cac2c017184ebbb69a699506e57bf8e97f4c5`.
The next requested test records the four rows before and after an UPLOAD cable
cycle, without an attached serial monitor and without resetting afterward.

### Second Windows 11 computer: activation and reconnect passed

One earlier OLED trace showed zero raw reads/writes both before and after a
cable cycle. The user subsequently reported `Ready` and no initial drive:
UPLOAD had not been active, so that trace did not test reconnecting shared
storage. This does not invalidate the separately observed initial USB failures.

On a second Windows 11 computer, the user explicitly activated UPLOAD with
navigation RIGHT on the probe menu page. The status changed from `Ready` to
`USB active` and the drive enumerated. After unplugging, reconnecting, and
waiting five seconds while remaining in UPLOAD, the drive reappeared.

| Counter/flag | Before cable cycle | After reconnect |
| --- | --- | --- |
| Connected / mounted / suspended / busy | 1 / 1 / 0 / 0 | 1 / 1 / 0 / 0 |
| Configured / unmounted USB events | 1 / 1 | 2 / 3 |
| Suspend / resume events | 0 / 0 | 0 / 0 |
| Raw read callbacks | 3,794 | 7,555 |
| Raw write callbacks | 0 | 0 |
| Raw transfer failures | 0 | 0 |
| Raw I/O lock timeouts | 0 | 0 |
| Latest SD error | 0 | 0 |

This is a passing activation/reconnect observation for the verified OLED probe
on the second host. No USB reconnect-policy fix was made between the earlier
failure and this result. Host differences, activation state, and CDC/flasher
interactions remain factors to distinguish; no specific root cause is proven.
The original host's code-10/code-43 failures still need a controlled retest with
UPLOAD positively active and serial/flasher sessions closed. This read-only
observation does not validate write integrity, recording after reclaim, normal
firmware updating, recovery reliability, macOS, or Linux.

### Original Windows host: drive-letter reappearance did not prove usable media

The user returned to the original computer. UPLOAD initially mounted after about
20 seconds. Reported rows were `C1 M1 S0 B0`, `U1 D0 S0 R0`, `R3756 W0 E0`,
`L0 rc0`. After unplug/replug, the drive appeared again, with `C1 M1 S0 B0`,
`U2 D4 S0 R0`, `R3756 W0 E0`, `L0 rc0`; the status remained `USB active`.

The agent then verified that USB interfaces were healthy but the disk reported
`No Media`, size zero, and F: had no filesystem/capacity. An unbuffered read of
`F:/.bodaqs-logger.json` failed with Windows I/O error 1117. The unchanged raw
read count is consistent with a failure before sector callbacks. Thus the
original-host reconnect was not a passing usable-media check. Drive-letter
reappearance alone must not be counted as a mount pass.

### Event-driven reconnect candidate

The previous adapter sampled `tud_mounted()` and did not consume configuration
or unmount events. A portable regression reproduced the retained-export state
when the connection stayed true across polls but the host-session epoch changed.
It failed twice before the fix and passed afterward.

The candidate tracks SDK configured/unmounted events and a configuration epoch.
Events immediately close media admission; the main loop drains raw I/O, reclaims
the card, and prepares a new export. Transfers are gated by the published epoch.
An export raced by a link change returns `ExposeResult::LinkChanged` and is
retried without a storage-fault state. `Inputs::connectionEpoch` and the typed
backend expose result are internal coordination-interface changes; consumers
and fixtures are updated. No automatic formatting is introduced.

Host tests additionally cover an in-flight transfer during a missed-edge
reconnect and a link change during export initialization. The full host harness
and four runtime fixtures passed. The diagnostic screen for this candidate is
titled `USB reconnect v1`, and its C flag follows SDK connection events rather
than the potentially retained TinyUSB configured flag shown as M. Physical
verification is still required; the missed-event case is a demonstrated
software defect, not proof that it is the only cause of the Windows failure.

Candidate artifact:
`firmware/packages/a8-usb-reconnect-v1/bodaqs-a8-usb-reconnect-v1-app.bin`,
application address `0x00010000`, SHA-256
`d8173be8439f861cb10c8350d9468ae78c7d8cb31afba364a2736c4caf978d03`.
Its application ELF SHA is
`444e233c061a10f54a418609d35389d673df3645d8a5a75d6893fc02eb1f9f0e`.
Image checksum/hash verification and the fresh `bodaqs_a8_usb_reconnect_v1`
target build passed. An earlier probe-target attempt failed on a missing SCons
cache file; the candidate was built in a new output environment. Normal A8,
USB development, and Prototype F builds passed, as did the full host harness
and four runtime fixtures.

Independent Standards review reported no concrete findings in admission/drain
handling, event callbacks, or updated interface consumers. Independent Spec
review reported no concrete findings in reconnect, eject, cancellation, or
failure behavior. Both reviews explicitly require physical verification and
do not establish that Windows media reads recover.

The user was asked to flash this candidate manually, return to NORMAL with USB
connected on the original PC, and close the flasher. The agent will verify
unbuffered identity-file reads both before and after a controlled reconnect.
This candidate is not yet recorded as a physical pass, and no new firmware
has been flashed by the agent.

### Candidate follow-up, 2026-11-12

The user reported flashing the `USB reconnect v1` candidate and returning to
NORMAL on the original PC, with the flasher closed. Windows initially enumerated
composite USB, CDC COM5, and MSC normally; the disk reported No Media, as expected
in NORMAL. A premature identity-file check while no F: volume was available
returned path-not-found and is not counted as an UPLOAD failure.

The user then reported `USB active`, `C1 M1 S0 B0`, `U0 D0 S0 R0`, `R0 W0 E0`,
and `L0 rc0`. On checking the host, Windows instead exposed only `Unknown USB
Device (Device Descriptor Request Failed)`, with no logger CDC or storage
interface. This is a failed initial-export observation for the candidate,
before the planned reconnect test or any observed sector reads. The epoch
regression fix has not established a hardware fix.

The user was asked to press navigation LEFT, without reset or unplug, to check
whether the application remains responsive. A retained OLED frame alone does
not establish application liveness. If the menu has timed out to the home view,
RIGHT should open the menu instead. Windows' saved COM5 default was checked
read-only and was `9600,n,8,1`, not 1200 baud. Enabled USB operational logs had
zero records. No serial port was opened and no firmware/reset command was sent
during these host checks. Application liveness and the exact trigger remain
unresolved pending the physical response.

### Menu timing clarified, 2026-11-12

The user confirmed that navigation returned to the main menu, so the application
was responsive despite the host USB failure. They also identified menu timeout
as a possible confounder. Source inspection established:

- `main.cpp` overrides the menu's two-minute default with 300,000 ms (five
  minutes). `MenuSystem::loop()` closes the menu after that input-idle interval.
- `requestClose()` ends the modal UI, clears the menu state/display, and cancels
  pending web-server UI choreography. It does not exit UPLOAD, withdraw USB
  media, or reclaim storage. The home `UPLOAD / USB active` view after timeout
  is therefore expected while that upload state persists.
- Enter/Right input is guarded for 180 ms after a page transition. A rapid
  extra press can be ignored, so page navigation alone does not prove entry
  into UPLOAD. Entry also defers page redraw for about 1.5 seconds.
- Once inside the upload page, ENTER/RIGHT toggles mode (or cancels a pending
  exit). Reopening the page and pressing again when already active can therefore
  undo the intended test setup.
- On this page, a short navigation UP or DOWN press refreshes the menu's idle
  timer but has no mode-changing action. This is a keepalive for the current
  probe, without another firmware update. Do not substitute a held UP gesture
  outside the menu, where an upload-mode shortcut may be configured.

Subsequent tests should separate navigation from activation: open the probe
page, wait at least one second, inspect its status, and toggle only if it is
not already active. Allow two seconds for redraw, record status plus counters,
and keep the page visible with a short UP/DOWN tap when needed. Keep tests
within the menu timeout or refresh it, rather than interpreting a home-screen
return as a firmware crash or an automatic upload exit. Windows descriptor
failures and unsuccessful uncached reads remain independently observed failures;
the menu timeout does not establish their cause.

### Controlled candidate test after menu clarification, 2026-11-12

The user exited UPLOAD to Ready, then unplugged/reconnected in NORMAL on the
original PC, with flashers and serial monitors closed. Windows enumerated
composite USB, CDC COM5, and MSC as healthy. No reset or reflash was requested.
The user then activated UPLOAD once and reported `USB active`,
`C1 M1 S0 B0`, `U2 D2 S0 R0`, `R3755 W1 E0`, `L0 rc0`.
The write count records host activity; the agent had not issued a file write.

The agent ran `check_usb_media.py` against the logger identity file using
unbuffered Windows reads. It passed with 160 bytes and SHA-256
`d50512d16c808d27567f52045e697efcc40f1da3f3cc78bf6c45d87f651c7047`.
The reader also verified the factory-derived device ID. This is a passing
real-media baseline on the original host, not merely an Explorer drive icon.
A subsequent three-second cable cycle while remaining in UPLOAD was requested;
post-reconnect file-read verification is pending.

The user then unplugged for three seconds and reconnected without changing
UPLOAD mode. Status remained `USB active`; reported rows were `C1 M1 S0 B0`,
`U4 D5 S0 R0`, `R5646 W2 E0`, `L0 rc0`. The post-reconnect unbuffered identity
read passed again: 160 bytes, with the same SHA-256 as the baseline. This is
one controlled, usable-media reconnect pass on the original PC, with no raw
SD failures or lock timeouts reported. It is stronger evidence than the earlier
drive-letter-only observation. The two host writes were observed in the
callback counter; the agent did not issue a card-file write in this test.

This does not retrospectively explain every earlier descriptor failure or
prove repeated-cycle reliability, write integrity, post-reclaim recording,
firmware-update recovery, or other operating systems. The tested candidate
includes temporary OLED/serial diagnostics. The production reconnect logic
and SD-warning correction are separated from that instrumentation for commit;
the existing target builds validate the non-diagnostic code path, but it has
not been separately reflashed in this controlled run.

After that successful reconnect read, the agent performed one bounded write
check on the same mounted card. The reader first reverified the logger identity,
then exclusively created
`BODAQS_USB_V1_BENCH_20261112_5a6914fd65.bin`, wrote 8,229 deterministic bytes,
flushed/fsynced the file, and verified exact contents through unbuffered reads.
Expected and actual SHA-256 matched:
`510cd0ef0d470d90374ef2f5d80bbf6b8cc2e2f89634284e8d70b1bb38a29c31`.
Only that newly created and verified test file was removed; absence was checked.
No source recording was changed. The complete write/read/cleanup operation took
about 0.145 seconds; this small check is not a throughput benchmark or a
power-loss/cache-safety guarantee.

The user was then asked to exit UPLOAD with the logger control alone, leaving
USB connected and without computer-side ejection. Confirmation of Ready/local
reclaim after this write check is pending. Recording after reclaim, larger-file
write integrity, repeated-cycle reliability, other operating systems, and
update/recovery requirements remain outside this passing controlled check.

The user confirmed Ready after requesting exit once, with no Windows eject or
USB unplug. Windows composite USB, CDC COM5, and MSC remained healthy. A further
unbuffered identity-file read was rejected with Windows error 21 (device not
ready), confirming that media was withdrawn in NORMAL mode. The candidate's
Ready transition occurs only after successful local reclaim. This completes
one controlled activation/read, cable reconnect/read, small write/read/delete,
and logger-only exit/reclaim cycle. No new recording was made after reclaim.

The pinned framework has other reported disconnect problems, including
[Espressif issue #7228](https://github.com/espressif/arduino-esp32/issues/7228),
but that report does not establish the cause of this A8 failure. Do not infer
that changing framework versions or clearing media on a USB event will fix it.
