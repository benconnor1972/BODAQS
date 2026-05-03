# SD Card Architecture (BODAQS Firmware)

This document describes the SD card architecture used in the BODAQS firmware.

## 1. Current Policy

BODAQS firmware now supports **SDMMC only** for logger storage.

The old SPI/SdFat backend and the ancient `ThingPlus_A` prototype profile have been retired. Production board profiles are expected to provide SDMMC pins through `BoardProfile::storage`.

## 2. Hardware Backend

The SD card subsystem uses the ESP32 SD/MMC peripheral via Arduino `SD_MMC`.

- Pins are defined by the active `BoardProfile`.
- 1-bit mode is currently used by the BODAQS 4D/4F profiles.
- 4-bit mode remains represented in `StorageProfile` for future SDMMC boards, but it is still handled through `SD_MMC`.

## 3. Filesystem API

All firmware file I/O uses Arduino FS objects from `SD_MMC`:

```cpp
File f = SD_MMC.open("/path.txt", FILE_READ);
```

There is no active `SdFat`, `SdFs`, or SPI SD storage path in the firmware.

## 4. StorageManager Responsibilities

`StorageManager` owns storage startup and log file lifecycle:

- Configure SDMMC pins from `BoardProfile`.
- Call `SD_MMC.begin(...)`.
- Verify card presence, card type, and capacity.
- Open, write, flush, and close CSV log files.
- Provide common text-file helpers used by config and metadata:
  - `StorageManager_loadTextFile(...)`
  - `StorageManager_saveTextFile(...)`

## 5. Consumers

Other modules should not hold storage backend pointers. They should either:

- use `StorageManager_loadTextFile(...)` / `StorageManager_saveTextFile(...)` for simple text files, or
- use `SD_MMC` directly where streaming/directory APIs are needed, such as file browser and transform routes.

## 6. Summary

- SDMMC is the only supported logger storage backend.
- `SD_MMC` / Arduino `File` is the only active filesystem API.
- SPI/SdFat support has been removed to reduce flash use and simplify maintenance.
- Board profiles remain the source of SDMMC pin configuration.

