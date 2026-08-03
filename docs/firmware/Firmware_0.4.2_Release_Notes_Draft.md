# BODAQS Firmware 0.4.2 Release Notes Draft

Status: draft  
Release date: TBD

Firmware `0.4.2` is a reliability and observability release for current
Prototype F and RC3 loggers. It builds on `0.4.1` with asynchronous sensor
sampling by I2C bus, stronger sensor-runtime diagnostics, and improved
instrumentation of acquisition and logging behavior.

## Highlights

- Rebuilt production firmware for Prototype F and RC3 as `0.4.2`.
- Moved supported sensor acquisition onto separate asynchronous tasks by bus to
  reduce interference between sensor reads and logging.
- Added lifecycle and timing instrumentation for I2C acquisition, sensor-row
  freshness, reused samples, missing samples, and failure streaks.
- Expanded logger metadata and diagnostic output so downstream tools can better
  distinguish acquisition behavior from row-use behavior.

## Compatibility

- Existing `0.4.x` logger configurations remain supported.
- The BDQ archive format remains compatible with the current import and
  preprocessing workflow.
- Standard over-the-air or update flashing normally requires only the
  application image. Use matching bootloader and partition images for blank,
  erased, or uncertain devices.

## Release Images

The release directory is:

```text
firmware/dist/0.4.2/
```

| Target | Application image | SHA-256 |
| --- | --- | --- |
| Prototype F | `bodaqs_4f-0.4.2.bin` | `022D87A28E64636BB72C489FAFD3B7D16290334C7B474585FE110BFB444A3480` |
| RC3 | `bodaqs_v1RC3-0.4.2.bin` | `F32B08B04A1F9E23A6CC3FBFC66230AC6B93A85657B97F53556B53A61A4B2297` |

Matching full-flash images are included:

```text
bodaqs_4f-0.4.2-bootloader.bin
bodaqs_4f-0.4.2-partitions.bin
bodaqs_v1RC3-0.4.2-bootloader.bin
bodaqs_v1RC3-0.4.2-partitions.bin
```

## Flash Addresses

For a normal update:

```text
0x10000  bodaqs_4f-0.4.2.bin
0x10000  bodaqs_v1RC3-0.4.2.bin
```

For a blank, erased, or uncertain device, flash the matching target set:

```text
0x0000   <board>-0.4.2-bootloader.bin
0x8000   <board>-0.4.2-partitions.bin
0x10000  <board>-0.4.2.bin
```

Use `bodaqs_4f` for Prototype F and `bodaqs_v1RC3` for RC3.

## Validation Performed

- Built `thingplus_s3_usb_cdcserial_bodaqs_4f` successfully.
- Built `bodaqs_s3_mini_n4r2` successfully.
- Prototype F build: 74.1% flash, 42.9% RAM.
- RC3 build: 74.2% flash, 42.9% RAM.

## Known Limitations

- This release retains existing ArduinoJson deprecation warnings during the
  build. They do not prevent the generated images from building or flashing.
- Runtime timing instrumentation is intended to improve diagnostics; it does
  not replace normal validation on the target logger and sensor configuration.
