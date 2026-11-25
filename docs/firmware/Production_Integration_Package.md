# Source-pinned A8 integration package (#229)

`firmware/tools/package_a8_production.py` builds the A8 ESP32-S3 Mini N4R2
4MB board explicitly. It never searches serial ports or flashes hardware.
Use committed, clean source and a new output directory outside the checkout.
The package has separate `bodaqs_a8_production` and
`bodaqs_a8_integration_candidate` directories. The latter permits unqualified
integration work; strict production retains the trusted-qualification START gate.
Neither a successful build nor a package audit supplies physical qualification.

```powershell
C:/Users/benco/.platformio/penv/Scripts/python.exe firmware/tools/package_a8_production.py `
  --output C:/Users/benco/dev/BODAQS-worktrees/a8-production-package-01 `
  --peer-bundle C:/Users/benco/dev/BODAQS-worktrees/adc-timer-1x1000-3333-r133 `
  --node-image C:/Users/benco/dev/BODAQS-worktrees/imu-native-1667-r127/artifacts/node/bodaqs_can_node.out `
  --node-inputs C:/Users/benco/dev/BODAQS-worktrees/imu-native-1667-r127/validation-logs/node-inputs.json `
  --master-command C:/Users/benco/dev/BODAQS-worktrees/imu-progress-view-r109/validation-logs/master-command.json `
  --pio-python C:/Users/benco/.platformio/penv/Scripts/python.exe `
  --esptool C:/Users/benco/.platformio/packages/tool-esptoolpy/esptool.py `
  --source-date-epoch 1795478400 --jobs 4
```

These historical input locations are local evidence dependencies. A missing or
hash-mismatched peer image/input/archive fails packaging. Do not substitute an
arbitrary current `.out` file. The selected master preserves the proven r109
behavior, including its instrumentation; packaging does not strip observers.
The node is the native-profile r127 image selected by r133. Both retain their
original identities, independently of the current logger commit. The manifest
records source differences relative to the sealed r133 archive for review with
the integrated protocol/lifecycle tests. This comparison is evidence about source,
not attestation of firmware installed on a device.

Each environment gets two clean builds in the same checkout. The tool requires
byte equality for app, bootloader, partitions, ELF, map and recipe. It sets
`SOURCE_DATE_EPOCH` for both builds and checks that the actual application bytes
contain the corresponding `FirmwareInfo` compiler timestamp, addressing
`__DATE__`/`__TIME__`. This proves repeatability with the recorded local toolchain;
it does not establish reproducibility across different operating systems or paths.
Recipe IDs describe source/options and remain separate from actual SHA256 hashes.

The package retains resolved PlatformIO dependencies, installed tool package
versions, hook hashes, command logs, ELF/map/recipe, `SOURCE.zip`, peer provenance
and `SHA256SUMS.txt`. The source archive selects public firmware/analysis build
and test sources, canonical firmware/analysis/agent/ADR documentation and build
entry files from the pinned commit. Its manifest lists exact included/excluded
paths. It excludes configuration settings, personal notes, media, datasets,
prebuilt archives/images and unrelated applications. Private reference
configurations, card recovery archives and full device-flash backups are not copied.
Extracted source can build directly through PlatformIO because recipe identity
uses file contents and options, without Git. Running the package driver again
requires a clean checkout of the recorded Git commit. Check
`BUILD_MANIFEST.json` for `status: passed` before considering installation. A
failed directory contains diagnostics and must not be used as a release package.

## Image layout and installation audit

| Component | Flash offset | Bound |
|---|---:|---|
| `bootloader.bin` | `0x0000` | Before partition table |
| `partitions.bin` | `0x8000` | Before boot app data |
| `boot_app0.bin` | `0xE000` | Before application |
| `firmware.bin` | `0x10000` | Within actual app partition and 4MB flash |

The tool checks ESP32-S3 chip ID 9 and 4MB image headers, requires the canonical
unencrypted A8 nvs/otadata/app0/coredump table, parses real partition bounds,
runs the partition verifier and esptool image checksum/hash inspection,
and records actual offsets, ends, sizes and hashes. Each
`recovery-merged.bin` begins at offset zero and contains the same component bytes
with erased `0xFF` gaps; a readback audit verifies every component and gap at
its expected offset. Flashing it overwrites the NVS gap; preserve required
settings separately before choosing that recovery operation. An app-only update
uses `firmware.bin` at `0x10000` with an already matching partition layout.
Use components and merged image from the same environment/package. Peer `.out`
files target MSPM0 and use their separate manual programming workflow.

Before any manual installation, compare all package checksums, selected
environment, board flash capacity, actual partition bounds and peer hashes with
the manifest. The package does not authorize flashing or configuration changes.

## Operation and qualification

Follow [migration](Production_Integration_Migration.md),
[finalization](Production_Integration_Finalization.md),
[admission](Production_Integration_Admission.md) and
[path retirement](Production_Integration_Retirement.md). Ordinary boot requires
no console or benchmark selection. Review and accept migration before START.
After STOP, wait for finalization and ownership retirement before removing the
card. Retained ownership/finalization failures require recovery; a displayed STOP
request alone does not establish safe removal. Import the resulting BDQ through
the normal import pipeline, retaining loss and uncertainty evidence.

The implemented native IMU rates 833/1667/3333Hz and supported local sensor
families are not a generally qualified mixed-load envelope. Trusted qualification
coverage is still required by strict production. Physical no-console startup,
UI/migration, mixed-load acquisition, storage stalls/full-card/removal,
STOP/recovery, heap and timing gates remain pending. Historical r133 performance
references and their limits live in the [progress ledger](Production_Integration_Progress.md)
and [integration handoff](Logger_Production_Integration_Handoff_2026-11-24.md).

Focused tooling check: `python firmware/tools/test_production_package.py`.
