# USB drive integration into the production candidate

This ports firmware, tests and relevant contracts from
`origin/feat/a8-usb-drive-access` at `da69dfb7` onto production integration
checkpoint `ca41e194`. It is a selective port, not an ancestry merge of that
branch's Import Manager, analysis, skill or unrelated repository changes.
The original USB spec's independent-of-CAN development boundary describes the
original feature; the user explicitly requested this subsequent integration.

## Operational boundary

The USB feature retains its writable, exclusive UPLOAD-mode card access,
three-second exit delay, one-second quiet interval, cancellation, reconnect/eject
handling, remount error/retry and factory-derived identity contract. A quiet
interval does not prove that host write caches are flushed. Do not remove power
or the card during a transfer. Computer-side eject remains useful but optional.

The recording lifecycle is authoritative. Upload entry and storage export reject
preparation, recording, producer retirement, finalization, retained master
ownership and outstanding storage I/O. A stopped sampler alone never permits
unmounting. Existing admitted Wi-Fi/file operations may finish while new local
filesystem work is refused; copied handles and directory children retain their
access until they close. Only then can the control loop unmount and grant USB
ownership. The storage worker's fault/deadline monitoring remains active before
the USB ownership early return.

Software restart and sleep also refuse while local card ownership is unavailable.
Finish or cancel the transition and reclaim the card first; a physical reset or
power interruption cannot provide the same software guarantee.

All firmware SD consumers use `StorageFilesystem`, including the production
storage health probe and migration backup existence check added after the USB
branch diverged. Raw USB writes pass through the existing SD driver wrapper but
cannot borrow the recording task's DMA buffer. Configuration/migration/calibration
guards, native count recording, operational loss evidence and bounded finalization
remain in force. File edits made by the host do not silently replace the logger's
live configuration; use its supported reload/restart and migration workflow.

USB-disabled builds use the original SDK `SD_MMC` object directly. The tracked
file adapter and raw USB resources are compiled only when USB drive support is
enabled. No ADC/CAN scheduling, task priority/core placement, row format or
acquisition-rate policy changes are part of this port.

## Explicit build and package choices

| Environment | USB drive | Recording qualification |
|---|---|---|
| `bodaqs_a8_production` | Disabled | Trusted supplied coverage required |
| `bodaqs_a8_integration_candidate` | Disabled | Explicit unqualified measurements |
| `bodaqs_a8_production_usb` | Composite CDC/MSC | Trusted supplied coverage required |
| `bodaqs_a8_integration_candidate_usb` | Composite CDC/MSC | Explicit unqualified measurements |

The new USB environments derive the existing operational flags, libraries and
4MB partition layout, select USB-OTG (`ARDUINO_USB_MODE=0`) with CDC on boot,
and pin the currently recorded PlatformIO platform `espressif32@6.13.0`.
Historical USB diagnostic/development environments retain their original pin;
they are not the combined production candidate.

`firmware/tools/package_a8_production.py --usb` selects the two combined USB
environments. All other required arguments and audit rules are unchanged; omitting
`--usb` still selects the original USB-disabled pair. Never interchange app,
bootloader, partitions or merged recovery images from different packages.
The selected master/node firmware remains unchanged.

Native USB controller changes can change the enumerated serial port. Preserve
USB serial diagnostics and verify normal updating and ROM recovery on the A8;
do not assume COM9 remains the device port. No installation is implicit in this
software integration.

## Tests and qualification

The agreed firmware seams are the public upload/storage coordination and actual
recording lifecycle with independent clock/USB/SD observations. Existing portable
ownership and USB-session tests are retained. Added composition checks cover all
busy recording phases, outstanding I/O, retained handoff, existing file transfer,
new-operation refusal and delayed reclaim. The actual SDK file adapter is exercised
with an independent filesystem model: copied handles, directory children,
external no-I/O, failed remount/retry and disabled-build pass-through.

Physical results from the USB branch remain historical evidence for that image,
not qualification of this combined candidate. Before completing integration,
exercise both cable/UPLOAD activation orders, byte-verified read/write, reconnect,
eject, cancellation/remount, and recording after reclaim. Include STOP/finalization
with the representative four-node mixed load, then a second recording without
power cycling. Compare a USB-disabled control and USB-enabled recording: USB
stack CPU/RAM/interrupt costs may remain even when no card is exported.

Normal import of transferred recordings must retain counts, source identities,
calibration, gaps and uncertainty. Import Manager USB discovery/pairing changes
are intentionally outside this port; the versioned marker contract is preserved
for compatible clients. Windows, macOS/Linux, runtime headroom, composite serial,
updating and recovery coverage must be reported explicitly rather than inferred
from host tests or successful compilation.

Copy recordings to a local folder before normal import. Do not use the older
moving folder-source workflow directly on the mounted logger card; the desktop
USB discovery/pairing adapter is outside this firmware port.

## Software verification and package

The audited package is
`C:/Users/benco/dev/BODAQS-worktrees/a8-production-usb-package-01`, built from
`a15fbeae`. Its manifest reports `passed`; installation was not performed and
physical qualification remains pending.

Both strict and candidate USB images passed two clean builds with identical app,
bootloader, partitions, ELF, map and recipe artifacts. Independent checks verified
the compiler timestamp, ESP32-S3 image checksums/digest, canonical 4MB partitions,
merged-image contents, all 41 package checksums and recipe inputs against the
914-file public source archive. Selected master/node images remain unchanged.

| Image | App SHA-256 |
|---|---|
| `bodaqs_a8_production_usb` | `7155f88333243135e07fcb59466babf11d6c27fa9c82a61a8596645b0da44e7e` |
| `bodaqs_a8_integration_candidate_usb` | `1208cd69d7a390f6c9d427f686d80f26769d5878b7194887b8e00d4746fff0af` |

All 113 firmware test recipes passed. The analysis suite passed 660 tests with one
skip. The USB pair, USB-disabled candidate, retained IMU smoke and Thing Plus
compatibility targets built successfully. ELF audits confirmed retired production
paths remain absent. Independent standards and specification reviews completed;
the follow-up restart ownership guard was independently rechecked.

The USB candidate uses 249,932 bytes of static DRAM versus 237,116 for the updated
USB-disabled control: an increase of 12,816 bytes. Loadable flash increases from
2,041,605 to 2,081,361 bytes. These are ELF measurements, not runtime heap or CPU
measurements. Runtime headroom, acquisition performance and USB behavior require
the hardware comparisons above; no firmware was flashed during this port.
