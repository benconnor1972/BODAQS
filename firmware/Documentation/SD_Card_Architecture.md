# SD Card Architecture (BODAQS Firmware)

This document describes **only** the SD card architecture used in the BODAQS firmware:
what hardware paths exist, which filesystem APIs are used, and why those choices were made.

Transform formats, IDs, and selection logic are intentionally **out of scope** and
documented separately.

---

## 1. Design goals

The SD card subsystem is designed to:

- Support **ESP32 SDMMC (SDIO)** and **SPI** hardware backends
- Use the **most reliable filesystem API** for each backend
- Avoid pretending incompatible APIs are interchangeable
- Make backend choice explicit and debuggable
- Minimise refactors when hardware changes

---

## 2. Hardware backends

### 2.1 SDMMC (SDIO)

- Uses the ESP32 SD/MMC peripheral
- Supports 1‑bit and 4‑bit bus modes
- High throughput, low CPU overhead
- Pins are defined by the active `BoardProfile`

This is the **primary / production backend**.

### 2.2 SPI

- Uses SPI peripheral
- Lower throughput
- Useful for:
  - older boards
  - bring‑up
  - compatibility testing

SPI is supported but not the preferred path.

---

## 3. Filesystem APIs

Hardware transport and filesystem API are **separate layers**.

| Hardware | Filesystem API | Type |
|-------|---------------|------|
| SDMMC | `SD_MMC` | Arduino `fs::FS` |
| SPI   | SdFat | `SdFat` / `SdFs` |

### Key point

> **SDMMC does not use SdFat in this project.**

Although SdFat is excellent for SPI, it does not integrate cleanly with SDMMC on
Arduino‑ESP32 without a deeper refactor.

---

## 4. Global storage handles

The firmware intentionally keeps backend‑specific handles.

```cpp
SdFs* gSd = nullptr;   // Valid ONLY for SPI backend
```

- `gSd` is **null in SDMMC mode**
- `SD_MMC` is accessed directly where needed
- There is no attempt to wrap both backends behind a single pointer

This avoids:
- null pointer ambiguity
- accidental API misuse
- hidden backend switching

---

## 5. StorageManager responsibilities

### 5.1 SDMMC path

When SDMMC is selected:

- Configure SDMMC pins from `BoardProfile`
- Call `SD_MMC.begin(...)`
- Verify:
  - card present
  - card type
  - capacity
- Leave `gSd == nullptr`

All file I/O uses **Arduino FS (`SD_MMC`)**.

---

### 5.2 SPI path

When SPI is selected:

- Initialise SdFat/SdFs
- Assign `gSd` to the active SdFat instance
- All file I/O uses **SdFat**

---

## 6. Backend selection

Backend choice is made during startup based on board profile
and/or compile‑time configuration.

At runtime, code should assume:

```text
if (SD_MMC is active)
    use SD_MMC (fs::FS)
else if (gSd != nullptr)
    use SdFat
else
    no SD available
```

No attempt is made to “convert” between APIs.

---

## 7. ConfigManager and SD pointers

`ConfigManager` does **not** retain an SdFat pointer in SDMMC mode.

Rationale:

- Config files are read via `SD_MMC`
- There is no valid SdFat instance in SDMMC mode
- Retaining a stale or null SdFat pointer is misleading

This behaviour is intentional and correct.

---

## 8. Why no unified filesystem abstraction?

A single abstract `IFileSystem` layer was considered and rejected because:

- Arduino `fs::FS` and SdFat differ significantly
- Directory iteration semantics differ
- Error handling and lifetime rules differ
- The abstraction would obscure real hardware behaviour

Explicit overloads and backend‑aware code were chosen instead.

---

## 9. Summary

- **SDMMC is the primary backend**
- **Arduino `SD_MMC` is the filesystem API for SDMMC**
- **SdFat is used only for SPI**
- `gSd` being `nullptr` in SDMMC mode is correct
- Backend differences are explicit by design

This architecture prioritises correctness, clarity, and debuggability over abstraction.

---

_End of document._
