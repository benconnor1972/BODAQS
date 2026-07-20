# BODAQS Firmware 0.4.1 Release Notes Draft

Status: draft  
Release date: TBD

Firmware `0.4.1` is a small maintenance release following `0.4.0`, focused on
RTC behavior for RC3 loggers with a fitted backup battery.

## Highlights

- Fixed RC3 external RTC startup behavior.
- Rebuilt Proto-F and RC3 firmware images as `0.4.1`.

## Fixes

- RC3 loggers now trust a valid RV3028 external RTC after reset instead of
  discarding the copied system time and forcing a network time sync.
- Automatic Wi-Fi/NTP time recovery is still used when the external RTC is not
  available, cannot be read, or reports PORF/power-loss state.

## Compatibility

No configuration changes are required.

Existing `0.4.0` logger configs should continue to load unchanged. This release
does not change the OLED, sensor, logging, GPS, ADC, web UI, or file format
behavior introduced in `0.4.0`.

## Builds

Release binaries:

```text
bodaqs_4f-0.4.1.bin
bodaqs_v1RC3-0.4.1.bin
```

Matching bootloader and partition images are also available for full flashing
onto blank or erased devices.

## Flash Addresses

The local staging directory for the generated release binaries is:

```text
firmware/dist/0.4.1/
```

For a normal firmware update on a device that already has a compatible
bootloader and partition table, flash only the application binary:

```text
0x10000  bodaqs_4f-0.4.1.bin
0x10000  bodaqs_v1RC3-0.4.1.bin
```

For blank, erased, or uncertain devices, flash the full image set for the
target board:

```text
0x0000   <board>-0.4.1-bootloader.bin
0x8000   <board>-0.4.1-partitions.bin
0x10000  <board>-0.4.1.bin
```

Use the matching board prefix throughout: `bodaqs_4f` for Proto-F loggers, or
`bodaqs_v1RC3` for RC3 loggers.

## Notes

This release is mainly useful for RC3 hardware with the RV3028 backup RTC
battery installed. Proto-F users can stay on `0.4.0`, but `0.4.1` is a harmless
baseline update.
