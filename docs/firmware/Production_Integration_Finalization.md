# Production integration finalization (#226)

Requirements: confirmed Q12?Q16 in
[production integration decisions](Logger_Production_Integration_Decisions_2026-11-23.md).
Software implementation is on the production integration branch; physical
qualification and representative supplied incomplete-recording evidence remain
pending. Host models and a target compile do not establish physical SD timing.

## Retirement and fault ownership

The control task owns lifecycle changes. A source-local fault still retires only
that participant; healthy independent participants continue. Malformed shared
clock/bridge evidence, loss of the shared master identity/session, or unavailable
shared measurement transport requests controlled session STOP. The first source
failure, stop trigger, missing/uncertain tail window and retained sequence bounds
remain operational evidence.

STOP first retires the sampler/ADC row callback and I2C acquisition callbacks.
The added nonblocking `I2CBusScheduler::requestStop()` / `stopped()` interface
uses a release/acquire retirement acknowledgement published after the final
client callback. A scheduler timeout is never permission to stop sensors or
reset their queues. Existing synchronous scheduler `stop()` remains available
for other callers. An outstanding callback retains its state and blocks the next
START. This change fixes the former bounded-wait fallthrough into sensor STOP.

Cancellation during storage preparation follows the same local retirement
barrier before requesting file finalization: initialized native sensors can
still have a final FIFO tail before sampling starts. Producers stop before the
storage owner drains queues and captures footer diagnostics. Native string-pot,
rotary and BMI queues/diagnostics remain owned through the storage completion
barrier; post-log recovery cannot reset the evidence while I/O is outstanding.

The persistent storage worker retains exclusive ownership of open/write/close,
DMA buffers and file handles. Its existing 5000 ms observation deadline exposes
`storage_unresponsive`; control requests STOP and retains the outstanding
operation. The deadline does not cancel the driver or prove durability. A
returned error closes the failed file without a successful summary/archive.
No forced task deletion, handle reuse or automatic old-file resume is added.
Recovery requires a new explicit START and the existing health probe.

A closed file with remote administrative ownership still retained enters visible
`uncertain` cleanup. Native finalization occurs once. Later verified handoff
retirement advances to `completed` or `failed`, without replaying queue cleanup
or peripheral restoration. Until then configuration and START remain locked;
uncertainty is never a successful ownership release.

## Bounded operational footer

Production builds use the existing BDQ-v2 final-summary chunk/schema with
`diagnostics_scope: bounded_operational`. The footer retains stop cause, dropped
rows/marks, skipped slots, per-stream retained sequence/count information,
known native producer loss/rejection/final depth, and remote first failures,
STOP confirmation/source-final boundaries and uncertain tails. Source identity,
CRC and source boundaries remain in the ordinary catalog/data/evidence stream;
optional profiling JSON is not a correctness dependency.

The serializer builds one small JSON object at a time with an **8192-byte heap
budget**, including allocator bookkeeping. It writes into the already reserved,
drained chunk workspace. There is no whole-session profiling tree or second
large serialized `String` allocation. No pending stream may still need that
workspace when serialization begins. The existing profiling footer remains for
nonproduction diagnostic builds.

A failed JSON allocation or insufficient existing workspace emits no partial
successful footer: finalization reports failure and the valid prefix remains
recoverable. The fault fixture containing four failed nodes and nine streams
serializes to 3389 bytes in its 8192-byte workspace. A forced 1024-byte workspace
and the fixture's 37-stream maximal request fail honestly; this is a bounded
failure policy, not a claim to support every catalog in a reduced workspace.
Existing START allocation/admission policy and physical fragmented-heap coverage
remain separate release gates.

## Import behavior

Normal BDQ-v2 metadata now adds `qc.run_stats.bdq_finalization` with footer
presence, file status, tail status and `delivery_scope: retained_records_only`.
A missing footer adds `bdq_missing_final_summary:tail_unknown`, including when
EOF lands exactly at a valid chunk boundary and no parser error exists. Raw
prefix rows and available recorded calibration remain usable. File closure is
separate from complete source delivery; source-local expected/missing counts
still require the existing identity and START/STOP boundary proofs.

## Focused software evidence

- `firmware/tools/test_logging_start_runtime.py`: normal START/configuration and
  late handoff recovery, 136 checks.
- The same runner with `--async-storage`: 52 checks, including blocked open/close,
  cancellation, native acquisition retention, shared-integrity STOP, file closure
  before remote cleanup and exactly-once finalization after late recovery.
- `firmware/tools/test_storage_worker_runtime.py`: blocked write/close ownership,
  deadline visibility, explicit health-gated recovery and 500 command races.
- `firmware/tools/test_remote_imu_lifecycle_runtime.py`: actual control/master
  composition, four-node isolation, shared-clock corruption, node versus master
  reboot classification, uncertain STOP, retained tails and late exit recovery.
- `firmware/tools/test_operational_finalization_runtime.py`: production serializer
  with ArduinoJson 7.4.3, four-node failure footer, allocation/growth failures,
  pending-data rejection and bounded workspace exhaustion. Defaults to ArduinoJson
  installed by the `bodaqs_a8_production` build; `--arduinojson` overrides its path.
- `analysis/tests/test_io_bdq_v2.py`: 21 normal-import tests including the missing
  footer prefix with preserved raw/engineering rows and explicit unknown tail.
- `firmware/tools/test_i2c_startup_runtime.py`: 46 checks.
- `bodaqs_a8_production` target compilation passes; no upload or flashing.

The isolated checkout has no `Examples/logs` folder and no representative supplied
incomplete BDQ was available during this slice. Independent synthetic incomplete
recordings cover the software import contract. Controlled card full/removal,
persistent driver stall, four physical node faults, fragmented heap under device
load, no-console responsiveness, and supplied real incomplete recordings remain
unclaimed physical/evidence gates. No full test suite, destination merge, push or
issue closure is performed by this slice.
