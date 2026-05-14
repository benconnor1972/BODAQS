# BODAQS Logger Firmware v0.2.0

## Overview

This release expands the public BODAQS firmware with support for the 4F board
profile and a broader set of usability, connectivity, and downstream-data
compatibility improvements. The release focuses on making the logger easier to
configure and access in the field, while improving interoperability with the
current BODAQS analysis workflow and SynBike export path.

## Highlights

- Added a public 4F firmware build alongside the 4E release build.
- Added Wi-Fi access point mode for direct browser-based access to the logger
  without requiring an existing network.
- Expanded configuration and web-management behaviour, including general web UI
  tidy-up and continued refinement of the config-file-based workflow.
- Improved downstream data compatibility by extending logger metadata output and
  supporting SynBike-oriented output modes, including unwrapped raw counts for
  string-pot sensors where needed.
- Added on-device log output access through the menu to improve diagnostics in
  the field.
- Fixed retained-time handling after deep sleep to reduce the risk of incorrect
  timestamps after wake or reboot.

## Build Variants

- 4E build: USB CDC serial release build for the current 4E hardware release.
- 4F build: release build for the 4F board profile.

## How To Update

For a routine firmware update, users would usually flash only the application
image. Users should only need to flash `bootloader.bin` and `partitions.bin`
if:

- this is the first flash onto a blank device
- the device currently has an unknown or incompatible image
- the partition layout has changed in a future release
- a full recovery flash is required

If a full manual flash is needed, the usual offsets are:

- `0x0000` bootloader
- `0x8000` partitions
- `0x10000` firmware
