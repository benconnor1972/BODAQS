# CAN IMU timing interpretation (#170)

The [acquisition contract](../firmware/CAN-FD_Acquisition_Transport_Contract.md)
defines the sample and 224-byte companion payloads. `bdq_to_stream_dataframes`
now interprets their timing separately from the legacy BMI path. The raw
sample/companion columns and complete descriptors remain available, including
unknown numeric kinds, validity masks, original flags, low/high bounds and
reception ordinals. Companion prefix creation ticks never anchor sample time.

Source positions unwrap within each explicit source segment. Models are selected
by that position, retain their canonical rational phase, and require native
association, input-range validity and matching provider/boot/segment identities.
Declared applicability must be at most 500 source steps and 150,000 us;
the inclusive endpoint must satisfy both limits. Revisions do not reset clocks.
Conflicting definitions at an applicable origin produce `model_conflict`.
Ambiguous associations across repeated complete source cycles remain unknown.
Only explicit model clock epochs distinguish resets; raw backwards ticks do not
invent a reset or establish an epoch.

`modeled_node_tick`, `clock_epoch`, `sensor_clock_epoch`,
`source_sequence_unwrapped`, `timing_model_id` and `timing_status` accompany raw
samples. `native_time_s` is nominal elapsed node time within an established
epoch. It is not a logger alignment guarantee. Nullable `logger_lower_us` and
`logger_upper_us` retain conservative intervals as integers. `time_s`, when
available, is the interval midpoint relative to the primary logger origin.

Shared master SYNC and causal bridge copies are keyed by original master UID,
boot, clock epoch, kind and SYNC sequence/token. Identical copies contribute once;
inconsistent copies increment `shared_conflict_count` and cannot establish a
mapping. Raw copies remain in their per-node frames. Method 1 bridges use raw
L0/L1 and M; node SYNC provides the node/master relation. Both observation ages
are limited to 150 ms. Known model uncertainty alone cannot bound either
cross-clock relation, and nominal oscillator rate is not a measured bound.

For qualified offline evidence, a companion acquisition descriptor can supply
`timing_bounds` with nonnegative finite `node_sync_capture_us`,
`master_sync_capture_us`, `bridge_quantization_us`, `node_master_drift_ppm` and
`master_logger_drift_ppm`. These are conservative externally established bounds,
including capture/quantization effects, not fit residuals. Every component and
the model's own uncertainty must be known before composition. Integer interval
endpoints round outward. Missing components, identities, validity or contradictory
intervals preserve unknown alignment. Production firmware currently declares
physical bounds unknown; these optional analysis declarations do not qualify it.

Full-vector adaptation preserves valid raw axes even without logger bounds,
uses explicitly bound native sensitivities and mount transforms when available,
and retains timing/status/identity columns. Its canonical time is native epoch
time when logger alignment is incomplete; `logger_time_s` remains unknown for
unmapped samples. Stream metadata identifies this clock and does not advertise
a logger-relative sample rate. Unknown samples survive primary-interval trimming
because their alignment cannot prove they fall outside that interval.

Session artifact export/load retains all supplied secondary sample/evidence
frames and their descriptor metadata. The legacy primary-only CSV projection
does not become an all-stream evidence export. Legacy BMI interpretation and
temperature/mixed-rate behavior remain unchanged.

## Software evidence

Independent parser fixtures in `analysis/tests/test_can_timing.py` exercise
rational 10/3 mapping, inclusive applicability endpoints, duration rejection,
retained revisions, source/tick wrap, repeated sequences in explicit reset
segments, conflicting models, shared-copy deduplication/conflicts, a worked
logger interval [9995, 10025] us, unknown bounds, full-vector scaling and artifact
round trips. The existing schema tests cover complete literal 224-byte payloads,
reserved bytes and raw unknown numeric fields.

Validation on 5 November 2026:

- Full analysis suite: 584 passed, 1 skipped (before two additional artifact and
  unknown-bound cases were added); only existing dependency warnings.
- Final focused BDQ/CAN/attitude regression run: 58 passed. After source-position
  lookup indexing was tightened, the nine new parser/adapter/export cases passed.
- `git diff --check` clean for analysis changes.

Physical association, capture/drift bounds, throughput and the 10 us relative
target remain unqualified under deferred #175/#176. No hardware was flashed.
