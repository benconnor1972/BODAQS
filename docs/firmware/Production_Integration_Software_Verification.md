# Production-integration software verification

Requirements checkpoint: `c11cc31e`. Candidate source for the final package:
`e0f023e4`. These checks establish software behavior and reproducibility, not a
qualified physical load envelope. The destination remains `feat-CAN-firmware`;
the [representative hardware checklist](Production_Integration_Qualification.md)
still applies before completing #230.

## Regression evidence

The full analysis suite passed **615 tests, with one skipped**, before the final
review corrections. The affected ADC/import files subsequently passed 30 tests,
including the new per-field missing-count contract. Restored diagnostic source
fixtures passed 44 tests after supplying the explicit native-profile identity
required by the integrated validator. No production validator was relaxed to
make a historical fixture pass.

The firmware host runner's compiled core and initial runtime adapters passed.
Its remaining 89 runtime/tool recipes were executed sequentially with independent
hardware/time/transport models. Four initial failures were resolved: two stale
fixtures and two missing baseline dependency closures. The changed configuration
fixture and control recovery fixture (normal and clock-wrap paths) passed their
reruns; retained bench tools passed 11 tests and optimization tools passed five.
Restored files and their original hashes are recorded in
[diagnostic dependency provenance](Diagnostic_Source_Dependency_Provenance.md).

CAN common/protocol, master and node Makefile suites passed. They cover the
native node profiles, control/identity/snapshot lifecycle, transport/CRC,
retention, hardware adapter models, queue boundaries and SPI initialization.
They do not prove electrical timing on the connected boards.

Final focused checks also passed:

- Shared production readiness/controller: 120 strict-build and 126 candidate-build
  checks; asynchronous storage/controller: 55 checks; ordinary START: 140 checks.
- Actual I2C worker creation with no clients, partial allocation failure, safe
  retry and an existing retiring worker. Failure cannot publish a running session.
- Actual GPS UART/task allocation failure, acquisition-suppressing diagnostics,
  retiring-worker restart rejection, cleanup/retry, coherent previews and normal
  native import, with retained diagnostic behavior checked separately.
- Actual ADC-owner device timeout isolation, healthy-device row continuation,
  invalid native publication, common cadence and STOP/restart reset. Shared SPI,
  register-readback and timer faults retain global controlled STOP.
- Operational footer serialization, allocation/workspace failure, explicit
  ADC-source failure evidence and marked-row queue overflow accounting. The
  four-failed-node fixture now uses 3981 bytes of its 8192-byte workspace; the
  deliberately excessive 37-stream fixture fails honestly rather than emitting
  a partial successful footer.
- Package image/layout, merged-image readback, public source filtering, and
  fixed compiler timestamp checks. Included `.inc` implementation changes now
  change the recipe fingerprint. Actual artifact hashes remain separate proof.

The retained `bodaqs_s3_mini_n4r2_imu_smoke` target builds after the final source
changes. Interrupted earlier packaging directories are not installation candidates.

## Completed package audit

Final local package: `BODAQS-worktrees/a8-production-integration-package-03`.
Its `BUILD_MANIFEST.json` reports `status: passed`, source `e0f023e4`, fixed
`SOURCE_DATE_EPOCH=1795478400`, explicit pending physical qualification and
installation not performed. Each environment passed two clean builds with equal
app, bootloader, partition, ELF, map and recipe bytes. The actual compiler
timestamp, ESP32-S3/4MB headers, checksums/digests, canonical partition layout,
component bounds and merged-image readback passed. All 41 package file checksums
were independently verified. Every recipe source-input hash matches the public
archive; its 895 files include the referenced CAN implementations and instructions.

| Environment | Static DRAM bytes | Loadable flash bytes | App SHA-256 |
|---|---:|---:|---|
| `bodaqs_a8_production` | 237108 | 2035853 | `0c3133abd18e7050c9e5dcf968677ff93584b8a0329a2b878d2bc77d45c36538` |
| `bodaqs_a8_integration_candidate` | 237108 | 2035877 | `a3e089b92c2f653b0c87a6355d0e2e83d33813a97de7a6e85fdd419efa8e3b90` |

The strict recipe is
`recipe-sha256:1d389ebcb2d83f635c8074acf5b9d6266ff24219f60f2f6d5b4c9686c5002b7a`;
the candidate recipe is
`recipe-sha256:c79306fd731ce43afcecc20a9916610056dbf91e57079930031d94b18628d934`.
Neither identifies installed hardware by itself. Both linked images pass the
operational/retired-root symbol audit, while the retained diagnostic still
contains its legacy writers and transform registry. Against the recorded
intermediate baseline, final strict production saves 49376 static DRAM bytes
and 142316 loadable flash bytes. Runtime free heap remains unmeasured.

The package contains exact hash-verified selected master/node images and their
historical provenance, not newly rebuilt peer firmware. Only the scoped logger
control-observer implementation/header differ in the recorded peer source
comparison. Build/recovery and safe operation are described in
[the package guide](Production_Integration_Package.md). Use the explicitly
unqualified candidate for hardware integration; ordinary production still
requires supplied qualification coverage. No generally qualified envelope is
installed by these software results.

## Independent review

Standards and specification reviews used the fixed requirements checkpoint and
the approved issue criteria. Focused rechecks confirmed the earlier membership,
prospective BMI readiness, legacy BMI row semantics, migration parsing/application
and string-pot uncertainty fixes. The final review additionally found and resolved:

| Finding | Resolution |
|---|---|
| GPS reports success without an acquisition task | Propagate UART/task failure and reject production modes that suppress acquisition. |
| A retiring GPS worker can be rearmed, then clear a new session's owner | Atomic state and creator/exit publication synchronization; reject restart until the old owner retires. |
| I2C worker allocation is ignored | Check every active bus owner; retain partial allocations through ordinary STOP retirement. |
| One ADC DRDY timeout stops healthy independent sources | Retire the failed ADC for this session and publish declared missing counts and source failure evidence. |
| Rejected marked rows disappear from operational loss totals | Increment the persistent mark-loss counter when the primary queue rejects the marked row. |
| Partition-table image can extend into NVS | Bound the component at `0x9000`, independently of the next packaged flash component. |
| Public archive omits included CAN implementations | Include `.inc` files; fingerprint their contents and preserve root instructions. |

Independent final rechecks reported no additional concrete standards or
specification defects in those fixes. Static image reductions, host tests and
source review do not establish runtime heap, latency, physical acquisition,
storage behavior or UI acceptance. No device was flashed and no issue was
closed by these verification steps.
