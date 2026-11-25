# BODAQS Firmware 0.6.2-beta Release Notes Draft

Status: draft for beta release  
Tag: `firmware-v0.6.2-beta`  
Build date: 17 November 2026

Firmware `0.6.2-beta` supports both A8 v1.0 and A8 v1.1 with the same A8 image.
It adds support for the ISL1208 real-time clock fitted to v1.1 and automatically
selects the RTC present at startup.

## Changes since 0.6.1-beta

- A8 automatically selects its RV-3028 (v1.0) or ISL1208 (v1.1) RTC. The detected
  chip and address are included in startup diagnostics.
- An RTC whose time has been lost is still detected, allowing the normal network
  synchronization to set it. ISL1208 calendar writes enable its crystal oscillator
  and restore calendar write protection afterwards.
- If neither supported RTC is detected, or both candidates respond, the logger
  reports a warning and uses internal/network time. Detection is retried on the
  next startup.
- Existing RV-3028 battery-backup configuration repair is retained. Both RTC
  addresses are reserved against conflicting sensor assignments on A8.
- Includes the AS5600 string-pot wrap fix already on `main`: analog rollover
  readings that briefly pass through midscale no longer lose the wrap transition.

## Compatibility and upgrade

- **A8 only:** use the same image on A8 v1.0 and v1.1. No RC3 or Prototype F
  images are included in this release.
- Firmware identity: `bodaqs_a8-0.6.2-beta`.
- No logger settings migration is required. Log formats, timestamp formats and
  the flash partition layout are unchanged from the previous A8 beta.
- RTC diagnostics can now identify `ISL1208`. The existing `external_porf` field
  represents either RV-3028 PORF or ISL1208 RTCF (loss of time).
- This release is built from the RTC branch based on `main`; the separate CAN-FD
  feature work is not included.

## Files

The release archive is `BODAQS-0.6.2-beta.zip`:

| File | Purpose | Flash offset |
| --- | --- | --- |
| `bodaqs_a8-0.6.2-beta.bin` | Application update on an existing A8 logger | `0x10000` |
| `bodaqs_a8-0.6.2-beta-full.bin` | Combined bootloader, partitions and application | `0x00000` |
| `bodaqs_a8-0.6.2-beta-bootloader.bin` | Separate bootloader component | `0x00000` |
| `bodaqs_a8-0.6.2-beta-partitions.bin` | Separate partition-table component | `0x08000` |

Use the application-only image for an update that preserves existing flash
settings. Use the full image for a blank/erased logger: its padding spans the
settings region and overwrites existing flash settings if used on a configured
logger. SD-card files are separate from internal flash.

`SHA256SUMS.txt`, `BUILD_MANIFEST.json`, `BUILD_LOG.txt` and `HOST_TEST_LOG.txt`
record artifact integrity, build provenance and automated validation.

## Validation and limits

- The project owner reports the RTC development firmware working on both A8
  revisions. These tests preceded the release version-number change.
- The host suite covers RTC selection, unset time, invalid calendars, hour
  formats, I2C faults and write protection, alongside the existing firmware tests.
- The versioned A8 release image is compiled and checked during packaging.
  Earlier development builds also compiled successfully for RC3 and Prototype F.
- This remains beta firmware. Detailed battery-retention and clock-accuracy
  measurements have not been recorded in the release evidence.

RTC implementation and bench procedure:
[A8 RTC detection](A8_RTC_Autodetection.md).
