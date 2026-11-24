# Production path retirement (#228)

This slice retires superseded release paths after the native-source, migration,
readiness and finalization replacements. Requirements remain the confirmed
[production integration decisions](Logger_Production_Integration_Decisions_2026-11-23.md).
The work starts at `50f9b8e5` and incorporates reviewed readiness fixes
`afc25a40` and `d7ca5b62`; the retirement commit follows those fixes.

## Environment and operational feature boundary

`bodaqs_a8_production` now extends the ordinary A8 board environment directly.
It carries an explicit selected configuration, without the historical smoke,
two-/four-node bench, concentrated-scan, fixed RAW geometry, rate sweep,
force-timer or backlog-bench admission flags. No qualification profile is
installed implicitly. Production therefore refuses START without trusted
qualification coverage, as required by #227.

`bodaqs_a8_integration_candidate` extends that same operational configuration and
adds only `BODAQS_UNQUALIFIED_INTEGRATION_CANDIDATE=1`. This is a separate build
for qualification work, never a runtime bypass or a production fallback.

`RecordingFeatures.h` separates operational capability from experiment names:

| Operational guard | Production behavior | Retained diagnostic trigger |
|---|---|---|
| `BODAQS_SCANNED_ADC_ACQUISITION` | Enabled | Concentrated-scan bench |
| `BODAQS_VARIABLE_ADC_SCAN` | Enabled | Boundary bench |
| `BODAQS_MULTI_ADC_SCAN` | Enabled | Dual-scan bench |
| `BODAQS_RAW_COUNT_RECORDING` | Enabled | RAW-recording bench |
| `BODAQS_ADAPTIVE_DRAIN_OWNER` | Enabled | Backlog-balance bench |

The existing diagnostic environment hierarchy and its eligibility rules remain.
Production uses the admitted acquisition plan, typed count rows and independent
native streams. The ADC tick alternative is unavailable in production;
absolute timer cadence remains selected. Historical diagnostic cadence remains
available. Startup configuration checks and mandatory PREPARE/source snapshot
proofs remain; this slice does not delete protocol evidence as a supposed
redundant read. Previously integrated reconciliation caching remains in force.

Selected functional settings are preserved: bulk512/version5 custody, 1200 us
exchange-start spacing, 5 us CS setup, ordinary-fetch interval 20 ms, health
interval 4000 ms, packed exchange/progress/batching/command templates, early and
segmented receiver reservation with PSRAM payloads, and the 512-entry sample
queue. ADC scan remains at 2 MHz with the inline combined row owner. ADC task
priority remains 4/core0; storage remains priority 2/core1; acquisition affinity
and the adaptive owner's existing priority2/3 policy remain unchanged.

The adaptive owner still uses the same pressure thresholds, eight-call/6000 us
healthy burst, one-call recovery and one-tick sleep. Its pressure API is now
available independently of FLOW diagnostics. Merely removing FLOW previously
would have removed an API required by this functional policy.

The linker `--wrap=sdmmc_write_sectors` option remains mandatory: it implements
owner-only DMA staging, rather than just profiling. ROM payload CRC and the
existing synchronous 4096-byte staging/batching path remain. Bounded startup
resource diagnostics remain useful; large FLOW/pressure/timeline/control-poll/
acquisition/transport profiling banks and optional timing instrumentation are
outside both operational environments. CPU/cost/storage benchmark gates and
retired-session benchmark JSON are outside the production image.

## One new-recording route

Production storage's format selectors are compile-time BDQ-v2-only, and the
owner refuses an unmigrated recording format. A stale public CSV writer entry
cannot write a production CSV. This allows the linker to discard CSV/v1 writers,
the profiling footer, CSV metadata/archive creation, their large static buffers
and startup archive promotion. Diagnostic builds retain these routes.

Production does not instantiate the transform registry or register its legacy
selection/reload routes. The generic complex-transform hook is identity-only;
recorded calibration, raw/native acquisition processing, linear engineering
previews and supported sensor families remain. Persisted migration fields and
nonproduction transform support remain intact. No analysis readers or offline
CSV exporters are removed. Ordinary imports of old BDQ-v1 files remain tested.

A diagnostic target exposed an existing unconditional reference to an optional
startup-diagnostics API in the storage worker. The reference now belongs only to
the storage probe; probes without startup diagnostics use context zero. This
keeps builds without either diagnostic feature valid.

## Software evidence and measured image impact

Focused checks cover resolved flags and compiled operational guards, the actual
ADC owner without bench flags, dynamic-width RAW queue/marks/loss evidence,
owner-only DMA/CRC/storage recovery, pure BMI readiness and admitted local plans,
normal and production lifecycle, remote control/fault cleanup, recorded membership
metadata, migration and native string-pot/rotary/GPS/BMI previews. The focused
legacy-v1/v2 importer files pass 32 tests; no full suite is run here.

Target builds:

| Environment | Result | Static DRAM bytes | Loadable flash bytes |
|---|---|---:|---:|
| `bodaqs_a8_production` | Pass | 237092 | 2033325 |
| `bodaqs_a8_integration_candidate` | Pass | 237092 | 2033365 |
| `bodaqs_s3_mini_n4r2_imu_smoke` | Pass | 267956 | 2114457 |

The read-only baseline ELF was copied from the integration worktree before this
slice, at `50f9b8e5`, before the two readiness review fixes. Its static DRAM is
286484 bytes and its loadable flash sections total 2178169 bytes. The production
image after retirement and those readiness fixes uses **49392 fewer static DRAM
bytes** and **144844 fewer loadable flash bytes**. These are ELF section totals,
not measured free heap, maximum contiguous allocation or physical throughput.

`check_production_image.py` verifies linked ELF symbols: legacy CSV/v1 writers,
transform registry, boot gates, archive creation and large profiling banks are
absent; BDQ-v2, raw counts, adaptive owner, the DMA wrapper and every supported
native sensor family remain linked. The retained diagnostic ELF still contains
CSV/v1 writers and its transform registry. Baseline/symbol/build logs are local
scratch evidence and are not source artifacts.

Useful commands (from repository root):

```text
python firmware/tools/test_production_path_selection.py
python firmware/tools/test_production_adc_runtime.py
python firmware/tools/test_recording_readiness_runtime.py
python firmware/tools/test_logging_start_runtime.py --production-readiness
python firmware/tools/check_production_image.py <production.elf> --nm <xtensa-nm> --size <xtensa-size> --baseline <baseline.elf> --diagnostic <diagnostic.elf>
python -m platformio run -d firmware -e bodaqs_a8_production -e bodaqs_a8_integration_candidate -e bodaqs_s3_mini_n4r2_imu_smoke
```

Physical mixed-load timing, free/fragmented heap, no-console responsiveness,
storage stalls/removal/full-card recovery and final board-specific packaging
remain explicit release gates. No flashing, physical measurements, issue closure,
push or destination merge is performed by this slice.
