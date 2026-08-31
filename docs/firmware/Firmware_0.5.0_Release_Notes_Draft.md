# BODAQS Firmware 0.5.0 Release Notes Draft

Status: release  
Release date: 2026-08-31

Firmware `0.5.0` is a major capability and reliability release for BODAQS A8
(previously identified as RC3) and Prototype F loggers. Since `0.4.2`, it adds
end-to-end BMI270 IMU logging, assisted sensor orientation, a self-contained web
interface, more consistent I2C sensor health reporting, and substantial
improvements to BDQ and CSV metadata integrity.

## Highlights

- Added production logging support for one Bosch BMI270 six-axis IMU, including
  native 200 Hz FIFO acquisition, timing and loss diagnostics, temperature,
  startup quality observations, and automatic recovery from several classes of
  transient device failure.
- Added an on-device assisted installation-orientation workflow for the BMI270.
  Accepted orientation is stored in logger configuration and emitted as a
  validated `sensor_native -> body_local` rotation matrix without modifying the
  recorded raw measurements.
- Reworked the logger web interface around htmx and embedded all required web
  assets in firmware. The configuration interface no longer depends on files
  being present on the SD card.
- Added mDNS/Bonjour discovery in both station and access-point modes. The OLED
  displays the logger's `.local` address when available.
- Expanded AS5048B and AS5600 string-pot health handling to match the established
  AS5600 angle-sensor lifecycle more closely, including magnetic diagnostics,
  read-quality fields, failure transitions, and deferred recovery.
- Improved BDQ and CSV metadata completeness and write reliability. BDQ files now
  retain richer typed channel schemas and session diagnostics, while CSV JSON
  metadata is streamed safely and packaged only after completeness checks.
- Deprecated direct syn.bike-format CSV output. Existing configurations that
  request it now silently fall back to BDQ.

## BMI270 IMU Support

The new `bmi270_imu_i2c` sensor records native accelerometer and gyroscope data
from the BMI270's hardware FIFO. Its fixed `orientation_200` profile uses:

- 200 Hz accelerometer and gyroscope acquisition;
- accelerometer range of +/-16 g;
- gyroscope range of +/-2000 degrees per second;
- explicit sequence, native sensor-time, sample-age, validity, temperature, and
  status fields; and
- sparse emission into supported logger rates without inventing replacement
  samples when no new native IMU sample is available.

The implementation preserves sensor-native raw data as the authority. Session
metadata and final diagnostics expose FIFO loss, queue pressure, timing quality,
near-rail events, recovery activity, temperature range, and startup stationary
evidence so collection quality can be assessed downstream.

The logger can also guide the user through an installation-orientation capture
while it is not logging. The capture checks stationarity, acceleration magnitude,
gyro stability, clipping, sample count, and roll residual before accepting the
result. An unset orientation does not prevent raw IMU logging.

## Sensor Reliability and Diagnostics

- AS5048B angle sensors now expose optional magnetic status, AGC, magnitude,
  `read_ok`, reused-sample, raw-read-failure, and diagnostic-failure columns.
- AS5600 I2C string-pot sensors now retain AS5600 device-configuration snapshots,
  magnetic health, read-quality fields, bounded runtime transition events, and
  deferred post-session recovery.
- AS5600 angle sensors, AS5600 string pots, and AS5048B sensors now use a more
  consistent session lifecycle and diagnostic vocabulary.
- Repeated read failures are coalesced into bounded transition histories instead
  of producing unbounded diagnostic output.
- Recovery that could overwrite useful session evidence is deferred until after
  log metadata has been finalized.
- GPS session startup now clears stale cached and queued observations, preventing
  a new session from beginning with the previous session's final position.

## Logging, Metadata, and File Integrity

- BDQ v1 now supports explicit `int16`, `uint16`, `int32`, `uint32`, and
  `float32` sensor-channel storage. This preserves the intended signed and
  unsigned representation of IMU and other native fields.
- Embedded BDQ metadata and CSV JSON metadata now carry substantially closer
  sensor provenance, semantic channel descriptions, runtime sensor health,
  acquisition timing, storage timing, and final session-quality information.
- Large JSON metadata is generated through a streaming path, avoiding the fixed
  in-memory document limit that could truncate metadata as diagnostics grew.
- Standard CSV completion uses a temporary archive and validates its metadata
  before publishing the final ZIP. Loose intermediate CSV and JSON files are
  removed after successful packaging.
- CSV row-buffer sizing is based on a safe worst case, and formatting or storage
  failures are counted rather than silently ignored.
- Both standard CSV and BDQ refuse to start if the configuration emits more than
  64 sensor columns.
- BDQ chunk sizing and storage-stall diagnostics have been improved for sustained
  high-rate logging.

## Web and Network Changes

- The configuration UI now uses htmx-driven routes and more reliable full-page
  refreshes after sensor additions, removals, or type changes.
- CSS, htmx, and other required static assets are embedded in flash and served by
  the firmware, so an incomplete or replaced SD card does not break the UI.
- Content-hashed asset URLs prevent browsers from retaining stale interface
  files after a firmware update.
- The logger advertises its service through mDNS/Bonjour in both Wi-Fi station
  and access-point modes. The normal address is:

  ```text
  bodaqs-<logger_id>.local
  ```

## Compatibility and Migration

- Existing standard BODAQS CSV and BDQ configuration selections remain
  supported.
- Direct syn.bike-format CSV generation has been removed from the logger. Legacy
  syn.bike format keys remain accepted but silently select BDQ, with no warning.
  Existing syn.bike files remain importable, and syn.bike output can still be
  generated by the downstream Import Manager workflow.
- Existing BMI270 `location` configuration remains accepted as an alias for the
  newer domain/end semantics. Obsolete `mount_x`, `mount_y`, and `mount_z` keys
  are removed when configuration is next saved; assisted orientation replaces
  them with a full rotation matrix.
- Existing angle-sensor measurement columns retain their order. Optional health
  columns are appended when diagnostics are enabled.
- Newly added or materially reconfigured BMI270 sensors require a logger restart
  before use so the active device and recorded configuration cannot diverge.
- Use current BODAQS import and analysis tooling when consuming logs containing
  BMI270 secondary streams, typed BDQ fields, or the expanded metadata.

## Build and Developer Tooling

- Added a reproducible command-line build workflow for listing targets, checking
  dependencies, building, merging full-flash images, flashing, and cleaning.
- The Bosch BMI270 SensorAPI dependency is pinned to a specific upstream revision
  and constrained to the required sources.
- Added focused native test coverage for BMI270 profile validation, FIFO parsing,
  queue behavior, timing, mounting/orientation validation, web fragments, static
  routes, and HTML utilities.

## Release Images

The release includes application, bootloader, partition, and combined full-flash
images for A8 and Prototype F. Always use files for the same hardware target.

Expected release directory:

```text
firmware/dist/0.5.0/
```

| Image | Purpose | SHA-256 |
| --- | --- | --- |
| `bodaqs_a8-0.5.0.bin` | Application update image | `DF48353BB8EA2B0ED6074B59946C516E8BFD296F134AD6CF8EECB3868F72A36D` |
| `bodaqs_a8-0.5.0-bootloader.bin` | A8 bootloader | `E01A2300DE23C8D601E9F2A37684B5DBC83AE37132D5A8833E23520AFD895F92` |
| `bodaqs_a8-0.5.0-partitions.bin` | A8 partition table | `6A88D59601A83A16A19A08114B59D338324B8DEC267D8B43E5D61AD56EC92102` |
| `bodaqs_a8-0.5.0-full.bin` | Combined full-flash image | `373E1CA0ABDD24298FB0645DB4F75C2B2495DCFAC14209F6B83BF4BCBB0DC908` |
| `bodaqs_4f-0.5.0.bin` | Prototype F application update image | `CD10F64D323D8E7F0AC723C5DAF6E8715A9305C187C4EEB6D142861441C2B217` |
| `bodaqs_4f-0.5.0-bootloader.bin` | Prototype F bootloader | `9BF9AAB34441621D794360CA427CBDDC3D62F38A7950F8790696BB3D7986769F` |
| `bodaqs_4f-0.5.0-partitions.bin` | Prototype F partition table | `6A88D59601A83A16A19A08114B59D338324B8DEC267D8B43E5D61AD56EC92102` |
| `bodaqs_4f-0.5.0-full.bin` | Prototype F combined full-flash image | `ECAC4D8B12CFC4FF5449347B4E330F98CB77A4A2E3BCD97AFBF18CB117AF6DA3` |

## Flash Addresses

For a normal application-only update, use the image matching the hardware:

```text
0x10000  bodaqs_a8-0.5.0.bin
0x10000  bodaqs_4f-0.5.0.bin
```

For a blank, erased, or uncertain logger, either flash the matching combined
image:

```text
0x00000  bodaqs_a8-0.5.0-full.bin
0x00000  bodaqs_4f-0.5.0-full.bin
```

or flash one matching component set:

```text
# A8
0x00000  bodaqs_a8-0.5.0-bootloader.bin
0x08000  bodaqs_a8-0.5.0-partitions.bin
0x10000  bodaqs_a8-0.5.0.bin

# Prototype F
0x00000  bodaqs_4f-0.5.0-bootloader.bin
0x08000  bodaqs_4f-0.5.0-partitions.bin
0x10000  bodaqs_4f-0.5.0.bin
```

## Validation Performed

- The final A8 `bodaqs_s3_mini_n4r2` PlatformIO environment was built cleanly.
- Final build usage is 147,540 of 327,680 bytes RAM (45.0%) and 1,737,037 of
  2,097,152 bytes application flash (82.8%).
- The linked application was checked for embedded firmware name `bodaqs_a8`,
  version `0.5.0`, and board name `BODAQS A8`.
- The final Prototype F `thingplus_s3_usb_cdcserial_bodaqs_4f` PlatformIO
  environment was built cleanly.
- The Prototype F build uses 147,280 of 327,680 bytes RAM (44.9%) and 1,734,833
  of 2,097,152 bytes application flash (82.7%).
- The linked Prototype F application was checked for embedded firmware name
  `bodaqs_4f`, version `0.5.0`, and board name `BODAQS 4F`.
- Combined full-flash images were generated successfully from each target's
  final bootloader, partition table, and application images.
- Focused parser, storage, metadata, IMU, orientation, and host-extraction tests
  were added and exercised during development.
- BMI270 ride-log inspection drove fixes for FIFO sensor-time parsing, shared-bus
  scheduling, sparse-row handling, clock fitting, and recovery from silent
  volatile-state loss.
- SHA-256 hashes were recorded for all eight release images. Hardware smoke
  testing remains a separate release acceptance step.

## Known Limitations

- This release supports at most one active BMI270 IMU per logger.
- The BMI270 physical acquisition profile is fixed at 200 Hz. Supported sparse
  logger output rates are 5, 10, 20, 25, 40, 50, 100, and 200 Hz.
- BMI270 orientation capture must be run while the logger is idle and the bicycle
  and sensor are held stationary in the requested pose.
- BMI270 component self-test is not run automatically; it requires a future
  maintenance-mode workflow because the Bosch self-test reconfigures the device.
- Direct syn.bike-format CSV output is no longer available in firmware.
- A logging configuration may emit no more than 64 sensor columns.
- Existing ArduinoJson deprecation warnings remain during compilation. They do
  not prevent the firmware from building or linking.
