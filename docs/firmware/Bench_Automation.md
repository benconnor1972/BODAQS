# Real-acquisition bench automation

These tools prepare and assess an experiment offline. They do not qualify
production admission or change the existing r5 hardware experiment. Preserve the
sealed r5 bundle for its pending scope capture. Physical first-byte SPI diagnosis,
known-input ADC switching and controlled storage stalls remain outstanding.

## Build and review

Use `firmware/tools/build_imu_software_candidate.py`. Existing `production` and
`first-recording` profiles remain; `mixed-diagnostic` selects the exact A8 mixed
environment, measurement v2/256 bytes/requested16MHz,500us CAN-CS spacing,5us
CS setup, four rejected replies/FLOW, and an RX2 master with phase/queue timing.
The setup delay remains an unproven diagnostic setting, not a claimed fix.

```text
python firmware/tools/build_imu_software_candidate.py --mode host --profile mixed-diagnostic --output-dir ABSOLUTE_FRESH_DIRECTORY
python firmware/tools/build_imu_software_candidate.py --mode candidate --profile mixed-diagnostic --review-base BASE_COMMIT --review-result REVIEW_JSON --output-dir ABSOLUTE_FRESH_DIRECTORY
```

Candidate mode requires committed clean source. Full scope runs existing logger,
common (including independent CRC), master, node, control, integrated and analysis
suites. `--validation-scope logger --reuse-peers PEERS_JSON` declares a narrow
logger-only check; omitted suites are not claimed as passed. The peer declaration
can also reuse unchanged peers with full host checks. It requires exactly one
master and node acquisition image, verified hashes, source commits and explicit
master settings. Reuse is declared provenance, not runtime image attestation.

```json
{
  "schema": "bodaqs.peer-images.v1", "profile": "mixed-diagnostic",
  "images": [
    {"role":"master", "path":"master.out", "sha256":"64_HEX_DIGITS", "source_commit":"40_HEX_DIGITS", "can_link_profile":"acquisition", "settings":{"spi_rx_capacity":2,"measurement_version":2,"phase_timing":true,"queue_timing":true}},
    {"role":"node", "path":"node.out", "sha256":"64_HEX_DIGITS", "source_commit":"40_HEX_DIGITS", "can_link_profile":"acquisition"}
  ]
}
```

Typed review JSON replaces prose matching. Schema `bodaqs.review.v1` contains
exact40-digit `base`/`head`, `outcome:"passed"`, a `findings` array whose entries
have `resolution:"resolved"` or `"accepted"`, and a nonempty `evidence` array of
`{path,sha256}`. Paths resolve relative to the declaration. The runner verifies
source binding and evidence hashes. Do not manufacture a review result from test
success: the reviewer supplies the decision. Archive/source guards and failure
logs remain active.

Each PlatformIO build emits `identity/build-recipe.json` and a generated header.
`[BUILD] recipe=...` and BDQ v1/v2 `firmware_recipe_id` identify normalized relevant
firmware sources and resolved project options. Tests and unrelated project files
are excluded. The fingerprint is a recipe identity; external SHA256 identifies
the binary. Arduino/non-PlatformIO and historical images explicitly report
`unknown`. Logger identity does not attest the installed master/node.

The manifest stores recipe, selected settings, compiled A8 pins/mode and literal
buffer/transfer declarations, review provenance, scope, artifact hashes and
logger flash offsets. `bootloader.bin` is at0x0, partitions at0x8000, boot_app0
at0xe000 and application at0x10000 for these selected S3 profiles. No tool flashes
them. Candidate packaging copies this guide for mixed work; create the run-specific
operator packet below before a physical run.

## One offline operator packet

```text
python firmware/tools/bench.py packet --manifest BUNDLE/BUILD_MANIFEST.json --config CONFIGURATION.txt --run-id mixed-001 --adc-column ADC_FIELD_1 --adc-column ADC_FIELD_2 --output-dir FRESH_PACKET
```

Use exact BDQ channel field names for `--adc-column`, not display labels. With no
ADC columns the spec is IMU-only. All three selected image hashes are required.
The packet contains a versioned run spec, immutable config/manifest copies,
readiness template, complete snapshot helper, argv arrays and a runbook. A spec
can also be generated alone with the `spec` subcommand.

Readiness is checked from explicit operator-installed image/config hashes and the
live `/api/v1/sensors` entries. It requires a unique unmuted `can:0`/`imu` endpoint,
compatible CAN links and current reconciled effective configuration. It does not
require `acquisition_ready` before the unqualified smoke-mode admission step.
Readiness alone cannot prove actual participation: intake separately requires
IMU samples and rows containing every declared ADC field.

```text
python firmware/tools/bench.py gate --spec PACKET/run-spec.json --observations PACKET/readiness.json
python firmware/tools/bench.py ingest --spec PACKET/run-spec.json --output-dir EVIDENCE_ROOT --input bdq=FINALIZED.bdq --input serial=serial.log --input manifest=PACKET/candidate-manifest.json --input readiness=PACKET/readiness.json --input snapshot1=snapshot.json
```

Inputs are explicit; no Downloads/drive/attachment search is performed. Snapshots
are optional. Missing attachments and partial BDQs are retained as incomplete
evidence. Input and assessment-engine hashes identify the owned evidence directory;
repeat intake verifies all preserved files and never overwrites them. A changed
input or reader creates a new result. Copy-time changes fail without promoting the
temporary intake directory. `report.json`, `REPORT.md` and `inventory.json` preserve
the provenance. Rejects and unknown identities cannot become comparison-ready.

`comparison_ready` concerns input association, participation and file integrity.
`strict_delivery_accepted` separately preserves the existing delivery decision;
an informative diagnostic recording can fail delivery. Neither field qualifies
production capacity or admission.

Serial joins require exact FLOW finished context and STOP-request evidence.
Snapshot joins require exact context/recording/master boot. A first-loss snapshot
is labelled first-loss and never used as a final cumulative total. Installed peer
hashes and snapshot master boot remain operator declarations; no runtime binary
attestation or signed provenance is implied. Old missing recipe IDs stay unknown.

## Exact CCS snapshots

```text
python firmware/tools/bench.py snapshot-script --version 5 --output export-snapshot.js
python firmware/tools/bench.py check-snapshot snapshot.json
```

The generated helper targets the already-selected CCS DSS `debugSession` and
never connects, halts, resumes, writes memory or loads an image. The operator
must halt the selected master, then call
`exportBodaqsSnapshot(debugSession, "EXACT_MASTER_BOOT", true)` and save the
returned JSON. Select `--without-phase`/`--without-queue` for the actual image;
legacy version2/3/4 layouts are supported with matching flags. DSS expression
evaluation follows TI's shipped `ccs_base/scripting/examples/DebugServerExamples`
examples. The helper itself has only been exercised offline, not in a live CCS
session in this implementation.

Every scalar/array element is exported, including phase totals. Each uint64 is
read as two uint32 halves and emitted as a hex string; context, recording and
boot must never pass through a floating-point number. Unsupported versions,
missing elements and JSON numeric uint64 fields are rejected. Master v5 adds
`layout_flags` (phase bit0, queue bit1) and `size_bytes` because optional timing
blocks change its layout. Snapshot scope is frozen first loss, STOP admission or
identity change, not necessarily physical cessation or final cleanup.

## Results, contrast and status

`assess_first_imu_recording` retains its strict existing `file_outcome`. Additive
`verdicts` distinguish file integrity/footer, control STOP, cleanup, source terminal,
sample identity, source/capture/evidence loss and physical qualification. Metrics
carry units, window, baseline/endpoints and denominator. Whole-run missing percent
is null without exact bounded source extent and identity. Reported loss categories
may overlap; their sum is not unique lost samples. Cumulative counter subtraction
requires a stable identity/epoch and nondecreasing values; reset/wrap is unknown.

```text
python firmware/tools/bench.py compare BASELINE/BUILD_MANIFEST.json CANDIDATE/BUILD_MANIFEST.json
python firmware/tools/bench.py status --manifest BUNDLE/BUILD_MANIFEST.json --evidence EVIDENCE_ROOT
```

Contrast prints source/profile/settings/artifact differences and, when commits
are locally available, relevant source hunks before proposing another experiment.
Missing historical facts stay unknown. Supporting/contradicting observations and
the next discriminating measurement remain reviewer decisions. Status distinguishes
local evidence, branch workflow presence, remotely exercised and default-branch
adoption; unverified remote/default fields remain null. Windows entry point
`Tools/Invoke-Bench.ps1 -Python PATH_TO_PYTHON ...` loads the existing UTF-8 helper.

## Later device stages

`device-plan --spec SPEC --scope SCOPE` validates a dry-run authority contract:
`bodaqs.bench-device-scope.v1`, run ID, exact expected images, selected port,
`action:serial_observe` or `bounded_cases`, duration1..3600 seconds and timezone-
qualified future `expires_utc`. Observation has no commands. Case control declares
at most32 literal single-line `case` commands and identical unique `case_ids`.
No arbitrary terminal/debugger/flash actions are accepted. Plans stop for identity
mismatch, timeout, failed/missing outcome or operator interruption; partial data
is retained rather than control being retried. Device adapters are deliberately
not executed or enabled here. Implement/exercise each later stage only with a
specific authorized physical session. Build permission does not imply flash or
remote publication/provisioning. Controlled storage-stall testing remains deferred.

## Boundary contract inventory

| Contract | Executable seam / independent check |
|---|---|
| Vendor/HAL buffer extent | Existing actual Arduino HAL bounds fixture and saved pre-fix negative controls |
| ACK_FETCH predecessor retired once | Actual master receive queue/adapter: invalid proof, cross-class successor, cached retry; RX2/RX4 and legacy profiles |
| Decoder rejection/output contract | Actual v1/v2 header with independent Python CRC/byte vectors, untouched/partial output and bool compatibility |
| Coherent preceding SPI operation | Actual shared-bus body with mutex/clock/ADC interleave, command/length/CS, timeout, wrap; capture on/off |
| Retired capture/footer ownership | Actual logger manager/lifecycle and footer adapter: cap, context, freeze/reset and independently parsed JSON |
| Evidence joins/metrics | Real canonical BDQ reader with independent complete/gap/torn/wrong-context and exact uint64/array vectors |
| Candidate source/archive/review | Existing candidate runner failure/source guards plus profile/reuse/review tests |

Branch CI invokes the same full mixed host plan, including common CRC/native
adapters and analysis. The target job stays manual/default-off. Local equivalents
do not establish a live remote guardrail. Optional larger master reply tracing
still requires a concrete unresolved question and RAM/timing budget.
