# Restricted IMU and ADC servicing candidate

This bench candidate follows the physical r2 ADC setup check. That check saved
16.9%/20.5% in setup/start cost but only about0.7-0.9% in worker-loop time. Further
ADC tuning is deferred. The next question is whether the tested IMU path and two
ADC workers can coexist without sustained sensor loss or unacceptable cached-row
reuse. This is evidence gathering for future admission work, not an admission
policy or a qualified capacity profile.

## Scope and implementation

Environment `bodaqs_s3_mini_n4r2_imu_adc_smoke` sets both the existing single-node
smoke flag and new `BODAQS_SINGLE_NODE_IMU_ADC_SMOKE=1`. Its distinct firmware name
is `bodaqs_a8_imu_adc_bench` for r1 and `bodaqs_a8_imu_adc_bench_r2` for the
pacing correction below; metadata admission mode is
`single_node_adc_smoke_unqualified`. The existing production and IMU-only smoke
environments retain their previous admission behavior.

Remote admission in this image requires requested500Hz, exactly two unmuted
AnalogPot sensors on A8 ain0 and ain4, one channel per ADC, each configured1000SPS
at1MHz SPI. RAW or LINEAR output is allowed, with `include_raw=false`; extra
sensors, duplicate inputs, other channels, transformations and rates are outside
scope. Zero remote IMUs is allowed for an ADC-only control using the same image.
At most one CAN IMU is allowed, retaining the existing configuration
reconciliation, link-profile and allocation-before-PREPARE checks. A rejected
remote scope can still use the existing local-only logging fallback: a file
being created is not proof that the IMU participated. Check the saved admission
report and streams. No measured scheduling costs are installed as qualified.

The ADC conversion commands remain the physically checked r2 full WREG followed
by explicit START in one six-byte CS span, then RDATA after readiness. IMU
transport remains256-byte measurement v2, requested16MHz,25us guard and500us
minimum start spacing with FLOW diagnostics. Keep the tested two-cell master
image and original acquisition node unchanged.

## Saved ADC diagnostics

The v2 final summary adds optional `external_adc_timing` with the same ADC/channel
keys and timing/freshness fields as compact binary. `config_us` includes WREG
and START; `start_us.count=0` means no separate START transaction. Values are
aggregate counters and durations, not per-reading native ADC timestamps.

The row producer stops before finalization. An atomic worker bitset is set before
task creation and release-cleared only after each worker's last statistics write.
Finalization acquire-loads this proof before exposing the statistics pointer.
If the existing100ms stop wait expires with a worker outstanding, the v2 footer
omits ADC totals and sets `external_adc_timing_status=worker_not_retired`.
Otherwise it records `complete`. This status describes diagnostic availability,
not successful acquisition or complete data delivery. Finalization remains
bounded; task creation failure also clears its bit. No allocations or counter
locks are added to each conversion; the bitset changes only at worker lifecycle
boundaries. Existing live preview/v1 diagnostic APIs are unchanged.

## Small physical comparison

Use the new image for both recordings,500Hz and multistream binary throughout:

1. ADC-only control, roughly30seconds: ain0/4 active, IMU muted.
2. Mixed recording, roughly30seconds: unmute exactly one nominal3333Hz IMU;
   retain all ADC/output/format/rate settings. CAN master must be enabled.

Use unique primary field IDs (clear `end` or assign correct distinct tags).
No sensors are connected: retain the current LINEAR settings for comparison, or
choose RAW before both recordings. All-zero scaled values and floating RAW values
cannot qualify analog accuracy, source settling or mux/channel association.
Those tests remain deferred until suitable known inputs are available.

Stop normally and await `[Storage] Log file closed.` Preserve each finalized BDQ
and serial start/STOP/FLOW output. Compare ADC success/timeouts, fresh/reused/
no-sample counts and row-age distributions against the same-image control. Check
primary sequence coverage, effective500Hz cadence, storage errors/queue peaks,
independently decoded IMU axes/sequence/loss, control progress, source terminal
boundary and cleanup/restart. Do not use retryable SPI request drops as a sensor
loss count. Aggregate reuse counters cannot identify which individual rows were
reused. The control has fewer remote queues/streams, so its memory load differs
despite sharing an image and format.

Earlier single-IMU tests retained STOP-time failure/terminal-tail evidence debt;
do not label that complete delivery if it recurs. Stop after a few seconds if
repeated DRDY timeouts return. Do not increase rates, add sensors, force storage
stalls or extend the test matrix before assessing these two files.

## Offline evidence and limits

The host suite runs exact mixed admission/lifecycle rejections before remote
authorization, successful mixed lifecycle and ADC-only control, allocation,
STOP/fence/retry regressions, the real ADC manager against both conversion-trigger
models, delayed-worker diagnostic unavailability and actual v2 ADC footer adapter
serialization with64-bit totals. Existing integrated IMU node-to-BDQ tests remain
in the suite. Hardware SPI/DRDY and ADC demand are simulated in lifecycle tests;
these tests do not establish shared-SPI timing or a physically integrated mixed
recording. Target compilation checks integration only. The external test bundle
records source/artifact hashes, build logs and fresh boundary review.

Controlled storage-stall testing remains deferred to the intended SD card. General
admission development, multiple IMUs, analog accuracy/mux settling and per-reading
ADC timing/freshness representation are not qualified by this candidate.

## r2: release the shared bus during per-device pacing

The actual r1 mixed recording `261110_103428.bdq` contained three streams but
reused24.4%/24.7% of ADC rows and missed79.23% of IMU positions within the resolved
prefix. Full-session IMU loss is unknown because terminal evidence is absent.
Storage had no primary drops and queue peak102/4096. The master retained ingress
queue filled128/128 after445899us; CAN receive drops and malformed SPI requests
were zero. These results do not qualify the mixed workload or establish a physical
capacity ceiling. See the preserved `imu-adc-mixed-r1-repeat-report` evidence.

Previously,500us pacing referenced the most recent transaction on any shared CS
and waited while holding the bus mutex and SPI transaction. r2 maintains a
separate start timestamp for each nonnegative int8 CS value. Only the same
device's starts affect its deadline; unpaced calls to that CS also count. The
pacing wait releases the mutex before starting a SPI transaction, then rechecks
the deadline under the mutex before asserting CS. ADC traffic can occupy this
interval. The CAN master's own500us start spacing and25us inter-CS guard remain.
The interface signature is unchanged; optional pacing semantics intentionally
change from whole-bus to per-device. Unpaced callers retain their behavior.
The fixed128-entry history cannot evict another device's origin; no allocation
is added to a transfer. `lockTimeoutMs` bounds each mutex acquisition. A paced CS
has one logical owner; competing same-CS traffic can extend its pacing wait.

Measurement diagnostics now split failed exchanges into `transfer_failed_slots`
(the shared-bus transfer returned false) and `decode_failed_slots` (transfer
completed but measurement reply validation failed). Neither is a sensor-loss
counter; decode failure alone does not distinguish CRC, framing or physical
causes. The split is saved alongside the existing first-failure DRAIN snapshot.
Its `available` flag establishes matching scope only: that existing live
multi-field observation is not atomic. Use the owner-frozen final split for
correlated totals; a failed early entry leaves first-failure timing unavailable.

The acquisition owner freezes final split counts into FLOW before releasing
ownership. Timing is tagged with its context when reset at actual mode entry;
an entry precondition failure cannot relabel old counts as current. Finalization
uses the matching immutable finished snapshot only after owner retirement, with
`remote_measurement_failures.available=false` if unavailable. Its scope is
`measurement_mode_through_cleanup`, distinct from the first-failure snapshot and
FLOW's data-request-only `wire_failed` counter. The finished split also prints
as `measurement_transfer_failed` and `measurement_decode_failed`. These optional
JSON diagnostics do not change binary records or wire protocols.

New tests exercise the actual shared-bus adapter with ADC work during the wait,
different CS origins, concurrent same-CS rechecking, lock failure and clock wrap.
The interleave test fails on the preserved r1 implementation. The actual
measurement adapter distinguishes failed transfer from corrupted reply. Tests
also cover final-snapshot scope/retirement, stale failed entry, release/reset,
and the production footer adapter's available/unavailable serialization.
The simulated hardware/RTOS clock does not establish electrical behavior or
physical arbitration fairness.

For the next check, upload only the r2 logger and repeat the same mixed load for
about45seconds. The existing ADC-only control remains useful; no repeat is
required first. Verify current enabled configuration reconciliation while stopped
and `streams=3` at start. Preserve final BDQ, serial STOP/FLOW and existing master
snapshots. Keep ADC rates/channels/output, node, two-cell master, SD card, CAN
profile and transport unchanged. Review normalized ADC freshness, independent
IMU sequence coverage, queues, split failures and STOP/terminal evidence before
any further change. No general admission margin or percentage improvement is
promised. Known-input/mux checks and controlled storage stalls remain deferred.

## r3: bounded rejected-reply evidence

The r2 recording `261110_115614.bdq` improved ADC reuse to12.9%/13.1% but still
missed72.77% of the fully bounded IMU sequence. The owner-frozen final counters
were0 failed bus transfers and6932 rejected measurement replies. Storage reported
no primary drops or write failures. This justifies inspecting actual rejected
MISO bytes before changing timing again; it does not establish an electrical
cause. CRC-valid invalid producer fields remain possible.

The same mixed bench environment now identifies itself as
`bodaqs_a8_imu_adc_capture_r3` and enables `BODAQS_MEASUREMENT_REPLY_CAPTURE=1`.
It requires FLOW and measurement v2. Pacing, SPI settings, ADC commands, admission
scope, binary records and reply acceptance rules are unchanged. Production builds
do not allocate capture buffers. Only optional final-summary JSON is extended.

The acquisition owner copies the first four rejected256-byte replies received
while measurement mode is confirmed. Failed bus transfers have undefined RX and
are excluded. Pre-confirmation entry can receive a legacy-width pipeline reply
and is also excluded. Entries retain every raw byte, the one-based physical slot
ordinal within measurement timing and the outgoing request kind. MISO has its own
pipelined identity; the outgoing kind is not the identity of the returned reply.
Two fixed1060-byte buffers hold live and finished evidence (2120bytes total on
the host/A8 ABI). Only four bounded copies occur; no per-slot allocation, serial
output or JSON work is added. The extra static memory is included in FLOW's
reservation accounting. A new context clears both buffers. Normal and unavailable
cleanup freeze before acquisition ownership is released; unavailable timing never
publishes stale capture as current. Readers require stopped ownership and matching
finished context. Borrowed evidence is consumed before release/new configuration.

The finalized footer adds
`remote_measurement_failures.rejected_replies` with `available`, `capacity`,
`captured`, `selection=first_decode_failures_while_confirmed` and `entries`.
Each entry contains `slot`, `request_kind` and512 lowercase hex characters in
`reply_hex`. Available with an empty entries array is a valid zero-capture result;
unavailable is not zero failures. The final failure counter still includes the
whole measurement-mode-through-cleanup scope and may exceed the captured count.
No raw bytes are printed during acquisition. If owner retirement/file finalization
cannot complete, this diagnostic intentionally remains unavailable.

`firmware/tools/replay_measurement_replies.py` accepts a finalized BDQ or extracted
final-summary JSON and compiles the actual canonical v2 C decoder. Its acceptance
verdict is authoritative. Independent header/CRC observations classify framing,
CRC mismatch or CRC-valid protocol-field rejection; header offsets are evidence,
not proof of byte displacement. Four initial failures are a small diagnostic
sample, not an estimate of all failure modes or their proportions.

Host tests inject rejected bytes at the actual shared-bus/manager seam, check the
cap, exact byte retention, exclusion of failed transfers, freeze/reset/scope,
owner-live unavailability and successful lifecycle publication. Footer roundtrip
tests verify all512 hex digits survive temporary-buffer reuse. Offline replay
tests independently construct framing, CRC and CRC-valid reserved/body-padding
failures and a valid slot. These establish diagnostic behavior only; no physical
mixed-load failure is claimed fixed. Repeat the same approximately45-second mixed
recording, finalize normally, and preserve its BDQ/serial evidence before deciding
whether a wire/configuration investigation is worthwhile.

## r4: CAN-only CS setup trial

The r3 capture `261110_122214.bdq` retained four replies beginning004d rather
than424d. Replacing only byte0 with42 in offline copies made every unchanged
stored CRC match and the canonical decoder accept all four. This identifies a
first-byte pattern in that small sample, not its physical cause or the pattern
of all603 rejected replies. The same run rejected IMU PREPARE with reason35
(node timing/clock-integrity checks) and recorded no IMU samples; its mostly
ADC-only freshness cannot qualify mixed throughput.

The restricted bench image is now `bodaqs_a8_imu_adc_cs5_r4`, with
`BODAQS_MEASUREMENT_CS_SETUP_US=5`. Only256-byte CAN measurement exchanges pass
this value; legacy CAN transfers and ADC calls use0. All other builds default0.
`SharedSpiBus::transfer` adds an optional final `csSetupUs` argument, default0,
so existing call sites retain their behavior. Setup waits after CAN CS assertion
and its start timestamp, before any transferBytes clocks, while retaining the
bus mutex and SPI transaction. This prevents another device clocking in the
selected interval. The existing500us per-CAN-CS start spacing still includes
setup, and its pacing wait still releases the mutex. The25us CAN inter-CS guard,
SPI mode/rate, reply capture, strict decoder and ADC commands remain unchanged.
The additional selected-bus wait requests5us per measurement exchange; target
preemption may lengthen it. It does not promise a measured5us electrical interval
or a throughput improvement.

Actual-bus host tests observe first-clock time relative to selected CS, use a
synthetic first-byte readiness threshold, check lock/selection throughout setup,
zero delay for ordinary callers, independent pacing, lock failure and micros wrap.
Removing only the setup wait makes the test fail at first-byte readiness.
That model validates the software seam, not a reproduction of the physical fault.
The actual CAN manager fixture checks5us propagation for measurement and0 for
legacy calls. Mixed lifecycle/retry/cleanup tests run with this flag; existing
ADC fixtures reject accidental nonzero setup. Wire representation and raw
capture publication are unchanged from r3.

Before the next hardware trial freshly restart both CAN boards and the logger,
then reconcile stopped IMU configuration. If the early first-failure line again
shows phase2/reason35, stop that attempt and retain the existing node runtime
timing/clock diagnostics rather than recording ADC-only for45seconds. A fresh
restart only avoids carrying possibly stale state; reason35 remains unexplained.
For a real mixed run retain final BDQ and serial start/STOP/FLOW. Compare reply
rejects, captured bytes, independent IMU sequence coverage and ADC freshness with
the actual r2 mixed run, not r3's failed-start result. If the first-byte pattern
persists, inspect the preloaded master byte or a short physical trace before
another timing/protocol change. No received bytes are repaired or admitted by
this experiment. General admission and controlled storage-stall testing remain
deferred.
