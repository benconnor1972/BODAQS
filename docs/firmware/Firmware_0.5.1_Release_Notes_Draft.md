# BODAQS Firmware 0.5.1 Release Notes Draft

Status: draft  
Release date: TBD

Firmware `0.5.1` is a maintenance release for BODAQS A8 loggers that improves
RV-3028 real-time clock battery-backup reliability.

## Changes

- The A8 now checks the RV-3028 backup-power configuration on every startup.
- If necessary, the firmware enables Level Switching Mode so the RTC transfers
  to its CR1220 backup battery when main power is removed.
- Trickle charging is kept disabled because the CR1220 is non-rechargeable.
- Existing RTC calibration and unrelated configuration bits are preserved.
- Configuration EEPROM is written only when correction is required, and the
  saved value is read back for verification.
- A configuration repair failure is reported through diagnostic logging but
  does not prevent the logger from starting.

If the RTC has already lost its time, the logger will still require its normal
network or manual time synchronization once. The repaired backup configuration
then applies to subsequent power cycles.

## Compatibility

- No logger configuration changes are required.
- Existing log formats, sensor configuration, metadata, and analysis workflows
  are unchanged.
- The change applies only to A8 hardware using the external RV-3028 RTC;
  Prototype F behavior is unchanged.

## Release Images

The A8 images are in `firmware/dist/0.5.1/`.

| Image | Flash address | SHA-256 |
| --- | --- | --- |
| `bodaqs_a8-0.5.1.bin` | `0x10000` | `DC4E367A2B4DB6ECC79DB8F37613901D77091DACF7A37FB40BD892A3CFD7D4A5` |
| `bodaqs_a8-0.5.1-full.bin` | `0x00000` | `8C4FDD3F582FA1A616540869B9D43BD2D17F9D8D3E3E576054C7DBB78D6BC8D9` |

Use the application image for a normal firmware update. Use the combined full
image for blank, erased, or uncertain devices.

## Validation

- The `bodaqs_s3_mini_n4r2` PlatformIO target built successfully.
- Build usage was 147,540 of 327,680 bytes RAM (45.0%) and 1,738,013 of
  2,097,152 bytes application flash (82.9%).
- The application image was verified to contain firmware version `0.5.1`.
- Physical main-power removal and battery-retention testing remains part of
  release acceptance.
