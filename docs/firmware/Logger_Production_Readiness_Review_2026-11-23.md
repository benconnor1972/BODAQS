# Logger production-readiness review ? 23 November 2026

## Purpose and review scope

The r120 raw producer is a promising implementation to keep: its ten-minute
four-IMU plus one 1000 Hz channel per ADC result retained 99.9471% of source-bounded IMU
readings, with 100% fresh retained ADC columns and 0.0352% omitted primary rows.
It is still an experimental firmware profile. This review identifies the work
needed before promoting that descendant to a supported logger release; it does
not implement that work or define a new admission policy.

The fixed comparison is canonical production `b8407363a4b07e114e4b39dfd95fd5073a1c64c9`
versus the sealed r120 source archive
`bd7f98bd6ba79e062ecdf21ab8c6f139f8c126a163038c14868ba899791146f9`.
The experimental source is not a Git branch, so reviewers compared corresponding
files and relevant `git diff --no-index` outputs, excluding generated build trees.
No later canonical firmware edits or untracked research notes were changed.

Target source root:
`C:/Users/benco/dev/BODAQS-worktrees/adc-raw-buffer-r120-source/firmware`.
Production reference root: `C:/Users/benco/dev/BODAQS`.
Source citations below are pinned to those snapshots and their then-current line
numbers; source-level concerns are not all reproduced hardware defects.

Two independent review contexts were used: standards/maintainability and
requirements/product integration. Their findings remain separate below rather
than combining implementation smells with contract omissions. No consolidated
production release spec exists, so inferred acceptance gaps are identified as such.

Retain CRC, source identity, honest losses/uncertain tails and STOP integrity.
Occasional visible loss is allowed. Preserve the current fixed local row cadence,
raw/calibration metadata, and existing transformation support; do not delete
CSV/v1, unrelated sensor families or board support without a compatibility decision.
Useful fault tests, sealed source archives, on-host exporters and assessment tools
are not runtime overhead and should remain available outside the release image.

## Standards


Reviewed sealed `adc-raw-buffer-r120-source/firmware` against canonical production checkout `BODAQS/firmware` at `b8407363a4b07e114e4b39dfd95fd5073a1c64c9`. The sealed source is not a Git checkout: comparison used per-file content hashes and `git diff --no-index` for relevant files, excluding generated `.pio`, caches and binaries. All references below are **target firmware-relative paths and target line numbers**. This is a static audit; no build, tests, flash, configuration, device or tracker changes were made.

Standards: repository `AGENTS.md` sections 1, 4 and 6; `firmware/AGENTS.md`; `docs/agents/engineering.md`; `GLOSSARY.md`; `skills/firmware-build/SKILL.md`. No separate contributing/coding-standards document was found. Smell assessments below are judgment calls; documented repository rules take precedence.

## Release blockers and changes needed before promotion

1. **P1 — Remove the mandatory serial startup gate from the release path.** `src/main.cpp:228-234` calls diagnostic gates before board selection and power initialization. `src/BacklogBalance.cpp:37-53` waits forever for `drain control` or `drain adaptive`, although the inherited raw environment sets `BODAQS_BENCH_AUTO_BOOT=1` (`platformio.ini:780`). Consequently an unattended logger cannot reach normal startup. Make the selected, qualified drain policy an explicit release setting; retain interactive selection in bench builds. Verify cold boot without a serial host and with the intended battery/power configuration.

2. **P1 — Make restart respect the complete recording lifecycle.** `src/DeviceRestart.cpp:9-19` checks only `isRunning()` before restarting. New asynchronous STOP sets that flag false before producer retirement and storage finalization (`src/LoggingManager.cpp:1162-1214`), leaving the menu/home restart reachable during cleanup. START also has a nonrunning preparation interval. Gate restart on lifecycle ownership, outstanding storage I/O and control handoff completion. Preserve the rule that outstanding I/O owns its handles; do not force-close/free them. Exercise restart during preparing, draining, failed storage and completed cleanup.

3. **P1 — Apply the same lifecycle fence to rate/configuration actions.** `src/MenuSystem.cpp:1431-1440` permits rate changes whenever logging is not running. `src/LoggingManager.cpp:1080-1087` then reconfigures ADC hardware and storage cadence even during START/STOP. The persistence call ignores failure (`src/ConfigManager.cpp:782-790`), so the storage write fence does not stop hardware reconfiguration. Use the existing complete lifecycle predicate and report persistence/application failure. Audit similar menu guards, including Wi-Fi mode (`src/MenuSystem.cpp:1541-1564`), against the same ownership model. This is a public-call-site completion issue under AGENTS sections 1.4 and 6.

4. **P1 release gate — Supply measured production admission, keeping experimental fences until then.** The raw profile inherits multiple bench admissions (`platformio.ini:768-807`); `src/RemoteImuRecording.cpp:520-530` selects these instead of budgeted production evaluation. The production profile defaults unqualified (`src/ImuAdmission.h:114-129`), and no firmware call site installs `setAdmissionProfile`. This is intentional experimental containment, not an instruction to delete the gates. Define supported board/load/rate combinations, qualify their timing, queue coverage and recovery, then install the corresponding profile and release environment. A successful r121 run alone cannot establish all supported cases.

5. **P2 — Separate operational storage behavior from diagnostic boot resources.** The selected path reserves internal DMA memory and runs CRC calibration with fatal boot loops (`src/StoragePathProbe.cpp:115-145`). CPU diagnostics reserve internal state and timer/interrupt resources even when automatically selected OFF (`src/CpuOccupancy.cpp:159-173`). Extract the approved CRC/batching implementation and required DMA buffer into storage ownership; leave benchmarking and optional CPU instrumentation in explicit diagnostic builds. Retain CRC equivalence tests and fail safely if a resource required for correctness is unavailable. An optional diagnostic allocation must not prevent normal board/UI initialization.

6. **P2 — Make a release reproducible and bind packaged bytes to its board/environment.** The platform remains unpinned (`platformio.ini:122`); default environments also have floating libraries (`platformio.ini:68-74`). `tools/build_identity.py:13-24` fingerprints source/options, not resolved toolchain/library versions, and omits the BMI setup hook. Preserve its honest recipe identity, but archive resolved versions and hook inputs alongside hashes of app, bootloader, partitions and merged binary. `build.sh:267-282,290-314` uses a shared output filename without verifying its environment before flashing; use environment-specific release artifacts/manifests. This packaging risk predates the experiment but must be addressed before distributing this descendant.

## Production hardening and later cleanup

7. **P2 — Establish explicit cross-task lifecycle ownership.** `s_running` is volatile and `s_starting/s_stopping` are plain booleans (`src/LoggingManager.cpp:55-60`), while the new capture callback reads run state from the ADC worker (`:241-258`) and sampler error paths call `stop()` directly (`:496,503,519,589,593`). Volatile does not provide C++ intertask synchronization. Route lifecycle transitions/errors to one owner and publish synchronized state; atomics alone would not make the multi-step cleanup transaction safe. Preserve producer retirement and existing queue barriers. Validate stop/error races across the supported capture profiles.

8. **P2 — Bound final-summary memory while preserving integrity evidence.** `src/StorageManager.cpp:1990-2340` constructs extensive diagnostic JSON; `:1958-1987` then reserves a second contiguous serialized copy. Allocation failure prevents writing the final summary/footer (`:2943-2947`). This is outside the sampling path, but still a release reliability/memory-budget concern. Measure worst-case finalization memory with four nodes/failures and fragmented heap; separate optional profiling into an explicit diagnostic schema or stream bounded serialization. Keep identity, losses, final source boundaries and uncertain-tail reporting in the operational record.

9. **P3 — Retire experimental alternatives only after a supported profile is fixed.** The environment history adds 546 lines versus canonical production; `platformio.ini:141-405,660-807` retains many old trials and duplicated flag sets. Possible speculative generality/shotgun surgery: inventory externally used environments, retain reproducibility manifests/tests, then remove retired alternatives and centralize approved policy flags. Do not infer that every legacy sensor/transport path is obsolete.

10. **P3 — Clarify qualification names and extract duplicated finalization shape.** `src/StorageManager.cpp:1652` sets raw `qualified=true` from schema eligibility, and `:2133` publishes it alongside a separately unqualified remote admission. Rename/document that narrow qualification scope. Possible mysterious name and duplicated code: `finalizeBdqV1_` and `finalizeBdqV2_` repeat stop/runtime field assembly (`:2864-2931`); extract a common snapshot builder while preserving their separate stack frames and format-specific semantics. These maintainability changes are not reasons to delay controlled bench testing.

## Spec


Read-only audit, 23 November 2026. `T:` references the sealed r120 source under `C:/Users/benco/dev/BODAQS-worktrees/adc-raw-buffer-r120-source/`; `P:` references canonical `C:/Users/benco/dev/BODAQS/` at `b8407363a4b07e114e4b39dfd95fd5073a1c64c9`. Line references describe r120 before concurrent r121 edits. No device tests or production implementation were performed.

There is no consolidated production release specification. The r120 `SPEC.md` and `RUNBOOK.md` explicitly qualify one experimental layout and roughly 244 seconds; they disclaim general capacity and analog accuracy. Missing release decisions below are **acceptance gaps**, not invented violations. Occasional visible ADC/CAN loss is acceptable under the user's direction; CRC, identity, explicit loss accounting and STOP integrity remain mandatory. Retain fixed local row cadence until the hardware revision and preserve transformation support.

## Release blockers

1. **Cold boot requires a bench operator.** `T:firmware/src/BacklogBalance.cpp:37` waits forever for `drain control` or `drain adaptive`; `main.cpp:232` invokes it before ordinary startup, and the selected environment enables it (`platformio.ini:778`). `StoragePathProbe.cpp:115` also contains permanent boot loops for diagnostic allocation/qualification failures. Extract the selected scheduling and CRC/DMA implementation into an explicit production build with deterministic startup policy and visible, recoverable failure state. Remove serial selection from that build. **Validate:** battery-only cold boot, absent console, missing SD, resource failure, repeated boots. This is a product acceptance gap; the r120 runbook intentionally requires the console.

2. **RAW format admission can be bypassed.** The RAW layout/rate guard exists only inside BDQ-v2 initialization (`T:firmware/src/StorageManager.cpp:1614`). ADC-only CSV/v1 selections can avoid that function: no remote IMU requires automatic promotion. Nevertheless `LoggingManager.cpp:194` selects the RAW callback, and `StorageManager.cpp:1070` rejects each submission when RAW storage is inactive, before incrementing its drop counters. Source inspection therefore identifies a path to a running, empty recording rather than refused START. This contradicts r120 `SPEC.md`, “Other layouts/formats/output modes fail START.” Put a complete guard before file creation/acquisition. **Validate:** actual START with CSV and v1, remote IMUs muted, fresh boot and after valid BDQ recording; assert no recording starts and no empty session is published. The primary agent may address this in r121; it was not yet verified here.

3. **No production admission profile replaces bench exceptions.** `T:firmware/src/RemoteImuRecording.cpp:296` defaults to an unqualified profile; `:520` routes the selected build through exact bench admission instead. `ImuAdmission.cpp:69` rejects unqualified production costs. Deleting BENCH flags alone can remove remote acquisition while allowing local logging. Define a supported board/master/node/profile/channel/rate matrix and an explicit bounded-loss policy, then implement production admission against verified effective settings. Existing 70%/85%/1.25 headroom numbers are implementation policy, not user-approved new zero-loss release criteria. **Validate:** every supported matrix entry, overload and unsupported combinations, measured service pauses, visible losses and unchanged source identities. Contract: `P:docs/firmware/CAN-FD_Network_Protocol.md:464` requires admission from effective descriptors and no silent rate or participant reduction.

4. **Web/API state still represents the earlier configuration-only stage.** `T:firmware/src/Routes_Config.cpp:809` says acquisition is unavailable; `:828` hardcodes readiness false and `:830` describes an obsolete 500 Hz bench scope. API readiness is also always false (`Routes_Api.cpp:332`, `:383`, `:945`). Replace these with shared capability/admission/lifecycle observations: desired versus effective settings, readiness reasons, actual membership, selected primary cadence, exclusion and finalization state. Preserve unknown measured-rate/timing fields until measured. **Validate:** UI/API agreement for absent/rebooted/rejected nodes, supported load, failed START and incomplete cleanup. This is missing stage integration: `P:docs/firmware/CAN-FD_Node_Control_Contract.md:627` correctly prohibited premature readiness claims. Live web control additionally requires an explicit product decision: `LoggingManager.cpp:871` deliberately shuts Wi-Fi down for logging.

5. **Unavailable configured native streams disappear from the catalog.** `T:firmware/src/SensorManager.cpp:1472` describes participating sensors only; remote admission failure returns before selection (`RemoteImuRecording.cpp:500`, `:531`) and remote descriptors enumerate selected nodes only (`:672`). Configuration diagnostics preserve some evidence but cannot substitute for stream descriptors. Decide how unavailable streams obtain honest immutable descriptors without inventing effective settings, then preserve configured identity and explicit zero-record/exclusion state. This conflicts with accepted `P:docs/firmware/BDQ_v2_Multi_Stream_Contract.md:110`, which requires unavailable configured sensors to remain catalogued. **Validate:** missing local IMU, missing/rejected remote node, prepare failure, and a zero-data stream imported with its reason intact.

6. **The production analysis path lacks the experiment's IMU decoding integration.** The selected image emits `bodaqs.can_imu_units.v2` (`T:firmware/src/RemoteImuStream.cpp:544`); its catalog exposes packed `unit_word*` diagnostics (`:33`), not decoded six-axis signals. Canonical `P:analysis/bodaqs_analysis/io_bdq.py:1603` generically exposes descriptors and builds signal metadata, but there is no CAN-unit/evidence decoder in the canonical analysis package. Generic BDQ loading is not evidence of usable IMU reconstruction. Promote a supported decoder and QC interpretation into the reusable import engine, retaining original units/evidence and explicit unreconstructed timing. **Validate:** a sealed nine-stream file through the normal Import Manager, source sample counts, scales, identities, gaps, clock boundaries and STOP tails. Contract: `P:docs/firmware/BDQ_v2_Multi_Stream_Contract.md:724` requires raw stream exposure and semantic metadata; `:704` prohibits implicit common-grid merging.

## Required acceptance work and cleanup

7. **Configuration support must match the shipped product.** Web/menu still offer three formats (`T:firmware/src/Routes_Config.cpp:1047`, `MenuSystem.cpp:1373`) and all supported cadence choices; the RAW image accepts two ordered AnalogPot RAW columns at 1000 Hz (`SensorManager.cpp:1215`, `StorageManager.cpp:1614`). Establish whether production generalizes this path or uses explicit compatible paths. Validate syntax at save and prevent unsupported execution at preflight; retain valid desired settings when hardware is absent or rejects them. Explain migration. Do not erase transforms, CSV/v1, other sensors or board variants merely because this experiment cannot exercise them. Validate supported older configurations and transformation/calibration semantics.

8. **Make lifecycle and evidence tests a release gate.** Keep the existing producer retirement → drain → summary → close → membership-release order (`T:firmware/src/LoggingManager.cpp:724`, `:1314`); restart refusal during handoff is intentional. Define repeat START/STOP, cancellation, source reboot/bus-off, SD stall/full/removal, power-cut recovery and sustained thermal/memory acceptance. Require CRC-valid files, explicit loss counters, marks, per-source STOP completion and honest incomplete-tail reporting. Contract references: `P:docs/firmware/BDQ_v2_Multi_Stream_Contract.md:144`, `:692`; `P:docs/firmware/Sensor_Lifecycle_and_Deferred_Recovery.md:5`.

After those gates, consolidate inherited experimental environments (`T:firmware/platformio.ini:682` onward), isolate serial gates/probes/export scripts from production runtime, and retire obsolete paths only after mapping their callers and compatibility obligations. Keep useful host/fault fixtures and sealed evidence. Package a distinct version, reproducible recipe, supported-board images and operator instructions. Cleanup is desirable; evidence preservation and truthful operation take priority.

## Concurrent r121 implementation note

The two-channel-per-ADC 700 Hz trial is a separate six-file extension, not the production
cleanup. It keeps the established scheduling and wire paths and expands the
RAW record to four ordered count columns. A narrow part of Spec finding 2 is
addressed there: raw builds reject CSV/v1 and wrong *requested* rates before
sensor/storage side effects, preventing the existing effective-rate cap from
silently accepting a 1000 Hz request as 700 Hz. Actual START transition tests cover
these refusals and a successful 700 Hz BDQ-v2 start. Scope/layout eligibility is
still enforced by the cold storage gate. UI save-time validation, complete
preflight feedback and supported-production-path selection remain outstanding.
The rest of this review is recommendations only and is not part of r121.

## Promotion and verification guidance

Select and document a supported production profile before retiring its alternate
paths. Move approved behavior out of bench boot gates; unify lifecycle guards
and make actual admission/membership visible in UI/API; integrate the data decoder
into normal analysis/import workflows. These are release integration activities,
not evidence that diagnostic flags can simply be removed.

Preserve a known-good performance comparison while cleaning up. A release check
must exercise actual nine-stream files through the normal importer, unattended
boot, repeated START/STOP without power cycles, cancellation/restart while busy,
configuration editing, missing/rebooted nodes, storage errors, and honest recovery
from incomplete recordings. Throughput acceptance should use useful retained
readings and visible loss rather than demand universal zero loss.

Controlled storage-stall testing and known-voltage/MUX analog validation remain
explicitly deferred evidence, not completed qualifications. General admission
thresholds and less demanding IMU profiles remain later decisions. Do not enlarge
queues or remove clock/identity/CRC checks as a substitute for those decisions.

Standards: 10 findings, most urgent unattended boot and lifecycle fences.
Spec: 8 findings, most urgent usable release admission, truthful UI/catalog and
normal analysis integration; the raw START format/rate hole is partially addressed
in the concurrent r121 trial as described above. No issues were published, no
production cleanup was applied, and no release was declared qualified.
