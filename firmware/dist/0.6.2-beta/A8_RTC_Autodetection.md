# A8 RTC detection and v1.1 support

The `BODAQS_A8` profile and `bodaqs_s3_mini_n4r2` build support both A8
revisions without a configuration change:

| Hardware | RTC | 7-bit I2C address |
| --- | --- | --- |
| A8 v1.0 | Micro Crystal RV-3028-C7 | `0x52` |
| A8 v1.1 | Renesas ISL1208IB8Z-TK | `0x6F` |

The v1.0 part is recorded in the repository BOM. The v1.1 part and `SDA0`/`SCL0`
connections were checked against U8 in the private v1.1 BOM and `UI.kicad_sch`
provided by the user. Private design files are not copied into this repository.

## Selection and compatibility

At startup, `RTCManager` reads status and calendar registers at both candidate
addresses on the profile's RTC bus (bus 0 on A8). Reserved-bit checks reject
incompatible register layouts. Calendar validity and loss-of-time flags do not
determine presence: an unset clock still needs to be selected for network sync.
This is detection of the two known board components, not unique silicon-ID
authentication of arbitrary I2C devices.

If exactly one candidate matches, its driver is selected and its name/address
are logged. If neither or both match, initialization logs a warning and uses
ESP32 internal/network time. Detection runs once per startup; a transient failure
requires another boot to retry. Probe transactions never write register data.
Normal RV-3028 backup-configuration repair runs only after selection.

Both addresses are reserved against user sensor assignments on an automatic
profile. RC3 keeps its explicit RV-3028 profile; profiles with no external RTC
retain internal time. Explicit RTC profiles remain available.

The existing `RTCManager` function signatures, logger configuration and timestamp
formats are preserved. Source labels may now report `ISL1208`. The existing
`external_porf` diagnostic and `RTCManager_externalRtcPorf()` also represent
ISL1208 RTCF (loss of both power supplies); this does not mean a depleted battery
has been measured. No settings migration is required.

## ISL1208 driver

Calendar transfers use the chip's register order and separate status transactions.
Reads handle both hour formats and reject invalid BCD, impossible dates,
pre-2020 time, RTCF and a disabled crystal oscillator. Network time writes enable
the crystal, set a UTC calendar in 24-hour mode, then re-protect calendar writes
and verify status. Failed transfers report failure and attempt re-protection.
Calibration, interrupt configuration and battery-switching settings are preserved.

Sources: [Renesas ISL1208 datasheet, FN8085 rev. 9.01, pp. 11-14](https://www.renesas.com/en/document/dst/isl1208-datasheet?language=en)
and [Micro Crystal RV-3028 application manual, rev. 1.4](https://www.microcrystal.com/fileadmin/Media/Products/RTC/App.Manual/RV-3028-C7_App-Manual.pdf).

## Validation

On 2026-11-17, the full host suite, including the RTC runtime fixture, passed on
Windows with MSYS2 UCRT64 g++. After disk space was freed, all three PlatformIO
target builds passed and generated `firmware.bin` application images:

| Environment | Result | RAM used | Flash used |
| --- | --- | --- | --- |
| `bodaqs_s3_mini_n4r2` (A8) | Passed | 176,140 bytes (53.8%) | 1,852,845 bytes (88.4%) |
| `bodaqs_s3_mini_n4r2_rc3` | Passed | 176,140 bytes (53.8%) | 1,852,861 bytes (88.4%) |
| `thingplus_s3_usb_cdcserial_bodaqs_4f` | Passed | 175,880 bytes (53.7%) | 1,850,681 bytes (88.2%) |

Application images are under `firmware/.pio/build/<environment>/firmware.bin`.
The build log is `firmware/.pio/rtc-build-validation.log`. Existing ArduinoJson
deprecation warnings remain in `Routes_Transforms.cpp` and `TransformRegistry.cpp`.
The project owner subsequently reported successful operation of the RTC
development firmware on both A8 board revisions. Individual retention and
accuracy measurements were not supplied. The release build uses version
`0.6.2-beta`; no device was flashed by the agent.

Run the host suite from `firmware/` with `make -C test test`. The focused test is:

```text
python tools/test_rtc_runtime.py --compiler g++
```

The focused harness compiles production driver, transport, detection and startup
functions against a register-level I2C model. It checks both chips, unset time,
both/neither present, unavailable bus, lock failures, NACK/short reads, UTC leap
day and hour formats, malformed calendars, write protection and retained RV-3028
backup repair. Model checks cannot establish physical retention or clock accuracy.

Compile A8 plus legacy profiles:

```text
pio run -e bodaqs_s3_mini_n4r2 -e bodaqs_s3_mini_n4r2_rc3 -e thingplus_s3_usb_cdcserial_bodaqs_4f
```

Before release, test the same A8 application on both physical board revisions:

1. Start offline with an already-set RTC. Confirm the expected chip/address log,
   correct local time and valid external RTC diagnostics without network access.
2. With the RTC unset, confirm selection succeeds but time is untrusted. Connect
   to the network, synchronize, and confirm the external RTC update succeeds.
3. Power off main power for several minutes with the backup battery fitted.
   Restart offline: the clock must have advanced correctly and remain valid.
4. On a spare/test board, remove both supplies, restore power and confirm time
   remains untrusted until network synchronization. Refit the backup battery.
5. Record a log, stop normally, and check timestamps and filenames. Confirm RC3
   and Prototype F retain their existing time-source behavior.

No device is flashed as part of automated validation. Keep the checks above as
the detailed acceptance procedure; the owner's successful tests on both board
revisions do not record individual results for every step.
