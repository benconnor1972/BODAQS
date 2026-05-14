# BODAQS Logger Firmware v0.2.0 Package

This folder contains staged firmware release assets built from the current
workspace with `BODAQS_FW_VERSION` set to `0.2.0`.

## Included Variants

- `4E`
  USB CDC serial release build staged from PlatformIO environment
  `thingplus_s3_usb_cdcserial`.
- `4F`
  Proto F board-profile release build staged from PlatformIO environment
  `thingplus_s3_usb_cdcserial_bodaqs_4f`.

Each variant includes:

- `bootloader.bin`
- `partitions.bin`
- `firmware.bin`

## Flash Offsets

For a full manual flash, the usual offsets are:

- `0x0000` `bootloader.bin`
- `0x8000` `partitions.bin`
- `0x10000` `firmware.bin`

For a routine update, users would normally flash only the application image
(`firmware.bin`) unless a full recovery or first-time flash is required.

## Integrity

`SHA256SUMS.txt` contains SHA-256 hashes for all staged assets in this folder.
