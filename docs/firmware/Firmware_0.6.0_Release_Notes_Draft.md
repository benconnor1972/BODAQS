# BODAQS Firmware 0.6.0 Release Notes Draft

Status: draft  
Release date: TBD

Firmware `0.6.0` is a feature and usability release for BODAQS A8, RC3, and
Prototype F loggers. It adds BDQ v2 multi-stream logging, expands BMI270 support
for multi-IMU and higher-rate configurations, raises the usable A8 ADC sampling
ceiling, and gives A8 and RC3 distinct power-management behavior.

## Highlights

- Added opt-in BDQ v2 multi-stream logging. A recording can contain a primary
  stream plus independent sensor-native streams, allowing high-rate devices to
  retain their native cadence without forcing every channel into one row rate.
- Expanded BMI270 support with selectable acquisition profiles and multi-IMU
  operation, including configurations with up to four IMUs.
- Removed the A8 external-ADC 500 Hz cap, increased the ADC conversion-time
  budget from 55% to 70%, and added 700 Hz to the permitted logger sample rates.
- Split the A8 and RC3 board profiles. A8 no longer has a default Sleep button
  binding or a Sleep menu item; RC3 and Prototype F retain Sleep because they
  use it as their user power-off function.
- Simplified the paused logging display to show `Logging` once, made the sensor
  mute list scroll, and stopped muted IMUs from unnecessarily holding the OLED
  in its reduced-update logging state.
- Moved Restart from Settings to the bottom of the main menu.

## Logging and IMU Changes

BDQ v2 is selected with `log_format=bodaqs_multi_stream_binary`. Existing CSV
and BDQ v1 selections remain supported. The new format records a primary stream
alongside independent native-rate streams and includes the catalog, event, and
diagnostic information needed to interpret them downstream. Use current BODAQS
import and analysis tooling when reading BDQ v2 files.

BMI270 support now includes several accelerometer and gyroscope rate profiles,
mixed-rate FIFO handling, dynamically sized queues, and stronger FIFO, I2C, and
timing diagnostics. The I2C scheduler and recovery paths have also been improved
for shared-bus, multi-sensor operation.

## Sample Rates and A8 ADC Capacity

The permitted logger rates are now:

```text
10, 20, 50, 100, 200, 500, 700, and 1000 Hz
```

The A8 external ADC gate now accepts configurations whose estimated conversion
time uses up to 70% of an ADC's available time. There is no longer a separate
500 Hz hard cap. Capacity still depends on how many active channels share each
ADC; the validation error reports the accepted rate for the current channel
allocation.

The higher budget reduces timing margin for conversion variation, I2C traffic,
and other runtime work. High-rate configurations, especially 700 Hz and 1000 Hz,
should be checked on physical hardware for missed samples and data freshness
before routine deployment.

## Board and User-Interface Changes

- A8 and RC3 now compile against separate board profiles while retaining their
  shared pin mapping.
- A8 defaults no longer bind a held button to Sleep, and its menu omits Sleep.
- RC3 and Prototype F continue to expose Sleep and its default button binding.
- Existing A8 configuration files with an explicit Sleep binding retain that
  binding until the configuration is updated.
- Restart is now the final item on the main menu.
- The reduced-update logging screen now displays `Logging` in full-size text and
  removes the duplicate small `logging` label.
- The sensor mute menu scrolls when more than five sensors are configured.
- When every asynchronous I2C sensor is muted, the OLED can resume normal
  updates after the logging warm-up period because no sensor deadline is at
  risk.

## Build and Developer Tooling

- Added a dedicated RC3 production build target.
- Removed the obsolete ADC diagnostic, AS5048 probe, and GPS UART probe
  PlatformIO tasks. Their dormant source helpers remain available if future
  diagnostic work needs them.
- Added host coverage for the A8, RC3, and Prototype F board-profile behavior.

## Compatibility and Migration

- Use the firmware image that matches the logger hardware. A8 and RC3 images are
  now distinct even though the boards share their pin mapping.
- Update A8 configuration files to remove any explicit Sleep button binding.
- Existing CSV and BDQ v1 configurations remain valid. BDQ v2 is opt-in.
- Use current BODAQS import and analysis tooling for BDQ v2 recordings and
  multi-IMU native streams.
- The nominal 700 Hz period is represented in integer microseconds, producing an
  effective scheduler cadence of approximately 700.28 Hz.

## Release Images

The release directory contains application, bootloader, partition, and combined
full-flash images for all three supported boards:

```text
firmware/dist/0.6.0/
```

| Image | Purpose | SHA-256 |
| --- | --- | --- |
| `bodaqs_a8-0.6.0.bin` | A8 application update | `20E221E611BDCF6235BFDBC3B00C1CA490EC597F8B31A83FA14A5B6DA6358DFD` |
| `bodaqs_a8-0.6.0-bootloader.bin` | A8 bootloader | `E01A2300DE23C8D601E9F2A37684B5DBC83AE37132D5A8833E23520AFD895F92` |
| `bodaqs_a8-0.6.0-partitions.bin` | A8 partition table | `6A88D59601A83A16A19A08114B59D338324B8DEC267D8B43E5D61AD56EC92102` |
| `bodaqs_a8-0.6.0-full.bin` | A8 combined full-flash image | `AF38A5260547A1C6C0545FD881EEA77ABF0D1BC3B87866BB3A853B5F6164EDB5` |
| `bodaqs_v1RC3-0.6.0.bin` | RC3 application update | `D73C72C2638463E94272D03C0C40C11EDCCD9F6F2285D9A1836B23177A1608BA` |
| `bodaqs_v1RC3-0.6.0-bootloader.bin` | RC3 bootloader | `E01A2300DE23C8D601E9F2A37684B5DBC83AE37132D5A8833E23520AFD895F92` |
| `bodaqs_v1RC3-0.6.0-partitions.bin` | RC3 partition table | `6A88D59601A83A16A19A08114B59D338324B8DEC267D8B43E5D61AD56EC92102` |
| `bodaqs_v1RC3-0.6.0-full.bin` | RC3 combined full-flash image | `DFB9E206592D1DA48BBBDF1F39AFBA1F5F932A3C4974218E8387698BF7444ACC` |
| `bodaqs_4f-0.6.0.bin` | Prototype F application update | `381C5537C53427DFF0EB1142D9A3C165DD7630DA768CC5CFAC90EBD77BB11218` |
| `bodaqs_4f-0.6.0-bootloader.bin` | Prototype F bootloader | `9BF9AAB34441621D794360CA427CBDDC3D62F38A7950F8790696BB3D7986769F` |
| `bodaqs_4f-0.6.0-partitions.bin` | Prototype F partition table | `6A88D59601A83A16A19A08114B59D338324B8DEC267D8B43E5D61AD56EC92102` |
| `bodaqs_4f-0.6.0-full.bin` | Prototype F combined full-flash image | `380715DA89C0B3D28D636F02A35C330FCE1B2DE83D208E664E8A6C261D30848F` |

## Flash Addresses

For a normal application-only update, flash the matching application image at
`0x10000`. For a blank or erased logger, flash the matching `-full.bin` image at
`0x00000`.

The separate component offsets are:

```text
0x00000  <board>-0.6.0-bootloader.bin
0x08000  <board>-0.6.0-partitions.bin
0x10000  <board>-0.6.0.bin
```

Do not mix components from different board targets.

## Validation Performed

- The full native host test suite passed.
- All three production PlatformIO environments built successfully:
  - A8: 162,628 of 327,680 bytes RAM (49.6%); 1,827,045 of 2,097,152 bytes
    application flash (87.1%).
  - RC3: 162,628 of 327,680 bytes RAM (49.6%); 1,828,117 of 2,097,152 bytes
    application flash (87.2%).
  - Prototype F: 162,368 of 327,680 bytes RAM (49.6%); 1,824,897 of
    2,097,152 bytes application flash (87.0%).
- Each application image was checked for embedded version `0.6.0` and the
  matching firmware identity (`bodaqs_a8`, `bodaqs_v1RC3`, or `bodaqs_4f`).
- Combined images were generated with the established bootloader, partition,
  and application offsets, and SHA-256 hashes were recorded for all 12 files.

Physical smoke testing on each board remains a release acceptance step. The new
700 Hz ADC configuration and the relaxed 70% ADC budget should receive specific
hardware timing and data-quality checks.

## Known Limitations

- A logging configuration may emit no more than 64 primary-stream sensor
  columns.
- The higher A8 ADC rates depend on the active-channel allocation and conversion
  timing; not every multi-channel configuration can run at 700 Hz or 1000 Hz.
- Existing ArduinoJson deprecation warnings remain during compilation. They do
  not prevent the firmware from building or linking.
