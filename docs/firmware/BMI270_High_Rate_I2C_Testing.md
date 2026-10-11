# BMI270 high-rate I2C test plan

Status: scheduling experiments closed on 2026-10-10. Whole-FIFO service and the
fixed two-deferral policy are restored. Hardware qualification remains pending.
See the [experiment summary and rollback](I2C_Scheduling_Experiment_Summary_2026-10-10.md).
The experimental build instructions below are retained as historical evidence;
their extra-deferral and sliced-service targets and controls have been retired.

## Purpose

Characterize how far the existing A8 I2C architecture can support four BMI270
accel/gyro streams before choosing whether any production configuration can
remain on I2C. This is a transport and timing test; it does not qualify the
BMI270 for a 1 kHz measurement bandwidth.

## Configuration controls

- `profile`: `orientation_200`, `orientation_400`, `orientation_800`,
  `orientation_1600`, or the BDQ-v2-only `accel_800_gyro_200` and
  `accel_1600_gyro_200`. The orientation profiles use equal accel/gyro ODRs;
  the mixed profiles use 800 or 1600 Hz accel and 200 Hz gyro. Range and
  current filter/performance selections remain unchanged from
  `orientation_200`.
- `fifo_poll_rate_hz`: 25, 50, 100, 200, or 400 Hz generally. An experimental
  10 Hz selection is accepted only with `accel_800_gyro_200`. This controls how
  often the FIFO is serviced, not the IMU sample rate.
- `max_output_rate_hz`: legacy CSV/BDQ-v1 row materialisation only. It is
  retained in saved configurations but hidden from the IMU web editor. Use
  BDQ v2 to retain each IMU at its selected native rate.

The stable default is `orientation_200` with `fifo_poll_rate_hz=200`.

## Capacity expectation

A combined accel/gyro FIFO frame occupies 13 bytes. Ignoring sensor-time and
transaction overhead, one IMU therefore produces 2.6, 5.2, 10.4, or 20.8 kB/s
at the four supported rates. The scheduler's conservative 400 kbit/s model
allows about 40 kB/s per bus (10 wire bits per transferred byte). Consequently,
two 800 sample/s IMUs consume roughly 52% of a bus before overhead, while two
1600 sample/s IMUs require 41.6 kB/s and cannot be sustained by that model.

The 1600/200 mixed profile produces at most about 12.6 kB/s per IMU under the
planner's conservative accounting (single-sensor headers counted separately),
versus 20.8 kB/s for `orientation_1600`. The 800/200 profile is a lower-load
comparison point. Two 1600/200 IMUs remain an intentional ceiling experiment
at 400 kbit/s, but are materially more plausible than two full six-axis
1600 Hz streams.

This calculation is an expected boundary, not a substitute for the cable test.

## Shared-bus AS5600 priority

The AS5600 has no FIFO, so a late read loses timing quality in a way that a
late BMI270 FIFO drain normally does not. The bus scheduler therefore treats
AS5600 angle acquisitions as latency-sensitive. Before beginning a potentially
long BMI270 drain, it looks ahead to the next AS5600 deadline. If that deadline
would fall inside the drain, the scheduler may service the AS5600 first.

This is bounded priority, not unconditional priority. A pending BMI270 drain
may yield at most twice, only after that IMU has completed an initial successful
drain, and only when the estimated deferral remains inside a profile- and
poll-rate-dependent service gap. The normal gap is capped at 70 ms. The
experimental 10 Hz 800/200 case permits 140 ms. Both are further limited to the
time required to fill 60% of the 2048-byte FIFO; the remaining space is reserved
for samples arriving while the eventual drain is in progress. Transactions
already in progress are never pre-empted. The final summary reports
`latency_sensitive`, `maximum_service_gap_us`, `priority_yield_limit`,
`priority_service_count`, `priority_deferral_count`, and
`priority_deferral_maximum_us` for each scheduler client. The last value is the
maximum cumulative AS5600 deferral applied before one buffered service.
`maximum_successful_service_interval_us` records the largest observed interval
between successful client completions.

For the first comparison run, use a 200 Hz primary stream, an AS5600 asynchronous
rate of zero (meaning follow the 200 Hz primary rate), the 800/200 IMU profile,
and 25 Hz FIFO polling. Compare AS5600 achieved rate and start lateness against
the previous run, while confirming that IMU FIFO high-water marks, service gaps,
overflows, sequence gaps, and discontinuities remain acceptable.

The final mixed-bus experiment uses `accel_800_gyro_200`, 10 Hz FIFO polling,
an explicit 500 Hz AS5600 asynchronous target, and a 200 Hz primary stream.
BMI270 temperature is sampled at 2 Hz and held between reads; the short
sensor-time observation remains at 10 Hz. At 10 Hz the acquisition recovery
threshold is reduced from three consecutive failures to two so that recovery
begins before the FIFO's nominal coverage can be exhausted.

That experiment established a baseline for the fixed two-yield policy. The
10 October 2026 experiment below replaces that policy in a separate RC3 build.
FIFO service below 10 Hz and 10 Hz service for higher-throughput profiles remain
outside this experiment. If bounded deferral is insufficient, options include a
separate bus, electrically qualified Fast-mode Plus, a buffered rotary sensor,
or acquisition on a satellite node.

## Bench sequence

Use BDQ v2, disable radio/UI activity, and retain the intended two-IMUs-per-bus
wiring and 600-1200 mm trunks.

1. Establish a clean four-IMU baseline at 200 sample/s and 200 Hz FIFO service.
2. For 400 and 800 sample/s, test FIFO service at 200, 100, then 50 Hz. Lower
   service rates reduce transaction setup overhead but increase batch latency
   and the consequence of a delayed drain.
3. At 1600 sample/s, first test one active IMU on each bus. Four IMUs at
   `accel_1600_gyro_200` have produced complete short-cable bench runs of about
   13 minutes, but this is still near the measured bus ceiling and is not yet
   qualified with full-length cabling or motion.
4. Repeat the limiting cases at realistic cable length, then with the proposed
   I2C accelerators only if electrical errors or edge quality are the limiting
   mechanism.
5. Repeat each viable point for at least 10 minutes and include representative
   auxiliary I2C and analogue sensor activity up to its expected 200 Hz ceiling.

## Evidence to retain

For each run preserve the BDQ v2 file and final summary, configuration, cable
length/topology, supply voltage at each node, pull-up/accelerator arrangement,
and oscilloscope captures for marginal electrical cases. Review at minimum:

- achieved FIFO service and native record rates per IMU;
- I2C bus occupancy, transaction duration/failure counts, service deadline
  misses, missed slots, and maximum start lateness;
- FIFO full/skip events, queue high-water marks and drops, parser drops, stream
  sequence gaps, and timing-degraded samples split by accel, gyro, and other
  causes; accel/gyro native-time discontinuities and gyro association fallback;
- short sensor-time register-read attempts, failures, drops, duration, and the
  resulting host-time observation windows; these 10 Hz reads add bus load and
  should be included when comparing runs;
- primary logger wake lateness, missed slots, queue drops, and storage timing;
- supply droop and SDA/SCL rise time at the furthest node.
- bus-recovery attempts/successes/failures and before/after SDA/SCL levels in
  `i2c_scheduler_timing.buses`, plus the serial `[I2C] busN recovery` line.

After failed device-level recovery caused by an I2C communication error, the
firmware can detach and reinitialize that bus. If SDA remains low while SCL is
free, it tries up to nine open-drain clock pulses and a STOP. The bus mutex
excludes other users during this operation, and each BMI270 on that bus marks
its next samples as a discontinuity. Attempts are bounded and rate-limited;
if SCL or SDA remains held low, software cannot guarantee recovery without a
separately switchable sensor supply or physical intervention. A recovery does
not make lost samples or their timing reconstructible.

A point is not viable if it has silent or unexplained loss. Numerical acceptance
limits for timing and error rate should be set after the first clean baseline;
all raw counters remain available so that decision does not need to be embedded
in firmware.

## Measurement-bandwidth caveat

Sampling at 1600 sample/s limits unaliased content to below 800 Hz even before
allowing transition band and amplitude/phase tolerances. The user's required
1 kHz acceleration band therefore needs an IMU sampling above 2 ksample/s and a
verified filter response; the BMI270 I2C trials can still establish the A8's
practical multi-device transport ceiling.

## FIFO margin deferral experiment (10 October 2026)

Original firmware identity: `0.6.1-alpha-i2c-deferral-q2` (archived in
`firmware/dist/0.6.1-alpha-i2c-deferral-q2/`). The build environment now produces
the refinement described below.
Enable flag: `BODAQS_I2C_FIFO_DEFERRAL=1`; ordinary environments retain the
fixed two-yield policy. The experiment retains transfer priority 2, the
increased primary/AS5600 queues, normal RC3 startup, and no CHIP_ID startup probe.
No configuration file changes or new scheduler settings are required.

Each BMI270 supplies a local FIFO estimate corrected by the length reads already
performed during normal draining. Complete parsed frame counts are subtracted;
partial frames remain in the estimate because the device retransmits them.
Growth uses the configured profile's byte rate plus 10%, with a 32-byte frame
phase allowance. No extra bus transactions are used for scheduling decisions.
Errors, FIFO-full/skip observations, parser uncertainty, flushes, recovery, and
new sessions invalidate the estimate. A subsequent clean service restores it.
An active peer with unknown state prevents extra deferrals. The wire-time model
is qualified only for the existing 400 kHz bus configuration.

Before granting an AS5600 acquisition, the scheduler forecasts one full service
for the selected FIFO and every other active FIFO on that bus, in normal
oldest-deadline order. It includes waiting, serialized drain costs, a possible
AS5600 service between drains, and a 1 ms decision allowance. Every projected
completion must fit the existing profile/poll-dependent service-gap budget.
This is stricter than the former check of the selected FIFO's start time.
The existing 60% FIFO capacity reserve is retained.

Intentional deferral also stops when predicted backlog exceeds one poll period
of guarded production (capped at the existing reserve), or predicted acquisition
duration exceeds the former one-poll estimate plus 2 ms. Whole-drain cost uses
conservative wire time and recent measured non-wire overhead: an eight-service
maximum plus 1 ms, with a 6 ms floor. AS5600 admission cost similarly uses its
configured estimate or its recent eight-service maximum plus 1 ms, whichever is
larger. Timing tails therefore temporarily suppress yields rather than changing
estimates permanently. The finite secondary count guard is derived from FIFO
and AS5600 periods, between 2 and 16 yields per pending drain (8 for 25 Hz FIFO /
200 Hz AS5600, 16 for 25 Hz / 500 Hz). Margin checks remain the main restriction.

These are admission estimates, not guarantees against task preemption or faults.
When a bound is already exceeded the scheduler services the FIFO normally;
it never truncates a required drain to meet the estimate. Complete FIFO reads,
parsing, timestamp reconstruction, sample queues, polling rates, and missed-slot
handling are unchanged. Added diagnostics are optional JSON fields, compatible
with readers that ignore unknown fields; this does not change the BDQ format.

The scheduler's serial start line includes `fifo_deferral=1`. BDQ v1/v2 final
summaries and CSV sidecars add the following per-FIFO scheduler fields:

- `fifo_deferral`, `fifo_production_bound_bytes_per_second`,
  `fifo_backlog_limit_bytes`, and `fifo_drain_limit_us` identify the policy.
- `maximum_yields_per_service` reports the largest actual count; the existing
  `priority_yield_limit` reports the absolute ceiling of 16.
- `fifo_predicted_backlog_maximum_bytes` and `fifo_predicted_acquire_maximum_us`
  are the largest predictions across peers in admitted decisions for this client.
- `fifo_deferral_rejected_unknown`, `_capacity`, `_gap`, `_drain`, and `_count`
  count rejected candidate admissions by their first blocking condition. They
  are not acquisition errors or lost samples, and do not count decisions with
  no AS5600 deadline inside the predicted blocking interval.

Start with 200 Hz AS5600 and equal 800/800 Hz IMUs at 25 Hz FIFO polling, then
500 Hz AS5600 and equal 400/400 Hz IMUs at 25 Hz polling. Match the primary rate
to AS5600 for each test. Compare with the preceding priority firmware using the
same wiring, card, and configuration: AS5600 achieved rate, interval distribution
and long gaps; IMU FIFO high water, skips/full events, service intervals,
sequence continuity, queue drops, transport errors, and primary/storage losses.
Several successful start/stop cycles and a long log remain hardware acceptance
requirements. Improvement is not presumed, and 500 Hz AS5600 / 800 Hz IMUs is
outside the intended target. If drain/gap rejections dominate, increasing the
count ceiling alone will not help.

Implementation validation: the full host suite passed, including 29 new policy
checks, and the experimental and ordinary RC3 builds passed. The experimental
ELF uses 175,748 bytes of static RAM and 1,843,449 bytes of program flash; the
scheduler worker has a 256-byte compiled frame. This does not establish the
runtime stack watermark or hardware scheduling performance.

## FIFO cost-model refinement (10 October 2026)

Build environment: `bodaqs_s3_mini_n4r2_rc3_i2c_deferral`.
Firmware identity: `0.6.1-alpha-i2c-deferral2-q2`.
Images: `firmware/dist/0.6.1-alpha-i2c-deferral2-q2/`.

The first two margin-policy logs retained complete IMU streams without FIFO
overflows or queue drops. However, drain-bound rejections dominated the 800/800
Hz run: the AS5600 achieved 69.512 Hz against its 200 Hz target. With 400/400 Hz
IMUs it achieved 283.578 Hz against a 500 Hz target. Both recordings actually
used a 500 Hz primary stream and 25 Hz FIFO polling. Their respective files are
`261010_083038.bdq` and `261010_085930.bdq`.

The original prediction used the full non-wire acquisition overhead to estimate
FIFO growth before the data transfer, as well as to estimate total service
duration. That overhead includes parsing, queueing and ancillary reads after
FIFO_DATA. It could therefore enlarge the predicted burst unnecessarily and
reject otherwise admissible yields.

Revision 2 measures setup separately, from the start of the normal FIFO_LENGTH
read to the start of FIFO_DATA. It uses the maximum of the last eight successful
length/data passes plus 500 us, with a 2 ms floor. Only this setup estimate feeds
pre-transfer FIFO growth. The lifetime observed setup maximum is retained for
diagnostics even after a timing tail ages out. Empty passes do not add setup
samples because they have no FIFO_DATA transfer.

Full acquisition overhead still uses its separate eight-service maximum plus
1 ms and 6 ms floor. Whole-service prediction adds conservative wire time to
the larger of full overhead and setup, so setup cannot exceed its own service
allowance and is not added twice. No extra I2C transactions are introduced.
Peer forecasts, FIFO reserve, service-gap, one-poll backlog and drain-duration
bounds, finite yield guard, rates, parsing, timestamps and queues are retained.
Ordinary builds retain the fixed two-yield policy; the startup probe stays off.

The scheduler start line identifies `fifo_cost_model=2`. All three summary
writers (BDQ v1, BDQ v2 and CSV sidecars) add these optional per-FIFO fields:

- `fifo_cost_model_revision`, `fifo_setup_estimate_us`,
  `fifo_overhead_estimate_us`, and `fifo_setup_observed_maximum_us` describe the
  cost estimates. The estimates are snapshots at summary time, not lifetime
  maxima; the observed setup maximum is a lifetime maximum within the session.
- `fifo_deferral_rejected_backlog` counts one-poll backlog-bound rejections.
- `fifo_deferral_rejected_duration` counts total service-duration rejections.
- `fifo_deferral_rejected_read_plan` counts predictions without a bounded burst
  solution. The existing `fifo_deferral_rejected_drain` remains the aggregate
  of these three reasons for compatibility. Other rejection counters retain
  their meanings. Rejections count blocked admissions, not lost samples.

For a controlled comparison, repeat the actual earlier configurations: **500 Hz
primary in both tests**, AS5600 target 200 Hz with equal 800/800 Hz IMUs, then
AS5600 target 500 Hz with equal 400/400 Hz IMUs. Use 25 Hz FIFO polling, the same
wiring/card and BDQ v2; include start/stop cycles. Compare AS5600 achieved rate,
interval tails and gaps, the new rejection split and cost estimates, and IMU
continuity/FIFO high water, errors, skips, service gaps and all queue drops.
Check primary missed slots and storage as well. A later 200 Hz primary test is
useful but should be identified separately rather than changing the matched
comparison. An AS5600 cadence improvement is not established by host checks.

Implementation validation: the full host suite passes, including 42 policy
checks covering the setup/duration split, estimator ageing and saturation,
rejection aggregation, unknown peers, peer service gaps and finite yields.
The experimental and ordinary RC3 builds pass. The experimental ELF uses
176,516 bytes of static RAM and 1,845,753 bytes of program flash; its scheduler
worker has a 272-byte compiled frame within the unchanged 4096-byte task stack.
Experimental FIFO peer scratch is absent from the ordinary ELF. Packaged image
identity, startup-probe absence, combined offsets and SHA-256 hashes were
verified. Runtime stack watermark and hardware performance remain to be checked.

## Relaxed bench policy (10 October 2026)

Build environment: `bodaqs_s3_mini_n4r2_rc3_i2c_relaxed`.
Firmware identity: `0.6.1-alpha-i2c-deferral3-q2`.
Images: `firmware/dist/0.6.1-alpha-i2c-deferral3-q2/`.
Flags: `BODAQS_I2C_FIFO_DEFERRAL=1`, `BODAQS_I2C_FIFO_RELAXED=1`.
The existing deferral environment still builds revision 2; ordinary environments
retain the two-deferral rule. This is an intentionally less conservative bench
experiment, authorized to trade FIFO margin and timing tails for AS5600 cadence.

The matched 500 Hz primary/AS5600, 800/800 Hz IMU comparison
(`261010_063703.bdq` versus `261010_102422.bdq`, both at 25 Hz FIFO polling)
showed AS5600 throughput falling from 177.15 to 126.31 Hz under revision 2.
The one-poll backlog bound accounted for 97.3% of admission rejections.
Revision 2 improved Bus 1 IMU service gaps and timing-degraded fractions, so the
result was a timing tradeoff rather than transport or storage loss. Both files
had continuous sequences and no FIFO overflows, skips or queue drops.

Revision 3 changes several admission parameters together:

| Admission control | Revision 2 | Relaxed bench revision 3 |
| --- | --- | --- |
| Backlog ceiling | One guarded polling period, capped at 60% FIFO | 85% FIFO: 1740 bytes, independent of polling |
| Separate drain-duration ceiling | One-poll estimate plus 2 ms | Disabled (`fifo_drain_limit_us=0`) |
| Production allowance | Configured byte rate plus 10% | Configured byte rate plus 5% |
| FIFO service-age check | Projected completion within 70 ms normally | Projected start within 120 ms normally |
| Experimental mixed-profile 10 Hz age limit | 140 ms | 200 ms, checked at start |
| Yield count | Derived from periods, 2 to 16 | Fixed ceiling 64 per pending FIFO service |
| Decision allowance | 1 ms | 100 us |
| Full non-wire overhead | Recent eight-service maximum + 1 ms, floor 6 ms | Recent eight-service mean + 250 us, floor 1.5 ms |
| Length-to-data setup | Recent eight-pass maximum + 500 us, floor 2 ms | Recent eight-pass mean + 100 us, floor 800 us |
| AS5600 cost | Configured floor or recent maximum + 1 ms | Configured estimate while cold; then recent mean + 100 us, floor 250 us |

The scheduler still forecasts the selected FIFO followed by every other active
FIFO on that bus, including a possible AS5600 service between drains. Each
forecast checks FIFO capacity including arrivals during setup, a bounded read
plan, and the start-age limit. The old additional capacity check that counted
all arrivals during a drain without subtracting any consumed bytes is omitted.
Complete FIFO transfers, their existing wire/read planner and buffer bounds,
FIFO follow-up handling, parsing, timestamps, queues and recovery are retained.
Timing measurements use existing transactions; the policy adds no I2C reads.
Unknown or invalid FIFO state still prevents extra deferrals until clean service.

The 120/200 ms values are admission limits for projected starts, not guaranteed
completion gaps. Recent means deliberately tolerate timing outliers that the
earlier maximum-based estimates rejected. Longer actual service gaps, FIFO
skips/full events, read-plan rejections, longer AS5600 gaps and increased queue
depths are possible outcomes to measure. No deterministic cadence is promised.
The same larger gap budget also relaxes admission of low-priority bus work;
existing display throttling remains in effect.

Serial identifies `fifo_cost_model=3`. BDQ v1/v2 final summaries and CSV sidecars
add these optional scheduler-client fields:

- `fifo_relaxed_policy` identifies the bench policy, and
  `fifo_capacity_limit_bytes` and `fifo_decision_guard_us` describe admission.
- `fifo_service_gap_checks_completion` is false/zero in this build; the existing
  `maximum_service_gap_us` reports the active start-age budget.
- `fifo_deferral_rejected_peer` counts candidate rejections whose first blocking
  condition belonged to another FIFO. It is a subset of existing rejection
  totals, not an additional reason to add to them. The remaining rejections
  concern the selected FIFO or a global count/missing-cost condition.

Queue sizes, transfer priority 2, RC3 board behavior and disabled startup probe
are retained. No new configuration keys are required. Polling remains selected
by the existing `fifo_poll_rate_hz` setting; flash this firmware and first repeat
the ongoing 50 Hz case with the same primary rate, AS5600 rate and IMU profile.
Then repeat at 25 Hz if useful. The intended targets remain AS5600 500 Hz with
400/400 Hz IMUs, and AS5600 200 Hz with 800/800 Hz IMUs. A 500/800 run is a stress
comparison, not a newly qualified operating point.

Review achieved AS5600 rate and interval distribution together with IMU native
sequence/tick continuity, timing-degraded fractions, service gaps, FIFO high
water, skips/full events, recovery and queue drops. Retain primary/storage
diagnostics and the policy/rejection split, including the peer subset. Several
start/stop cycles and long bench logs remain necessary to establish behavior.

Host validation: the full suite passes with each policy selected. The existing
42 conservative policy checks remain passing; 32 relaxed checks cover multiple
yields followed by forced service, peer/selected rejection attribution, unknown
state, age/capacity/read-plan limits, estimator ageing, saturation and whole-read
forecast bounds. An aged two-IMU fixture admits 22 consecutive yields before a
margin check forces service; this is a model check, not measured hardware cadence.

Build validation: relaxed revision 3, conservative revision 2 and ordinary RC3
environments all pass. The relaxed ELF uses 176,772 bytes of static RAM and
1,846,757 bytes of program flash. Its scheduler worker has a 256-byte compiled
frame within the unchanged 4096-byte task stack; FIFO peer scratch remains
static per bus and is absent from the ordinary ELF. Packaged image identity,
startup-probe absence, combined offsets, erased gaps and all four SHA-256 hashes
were verified. Runtime stack headroom and hardware behavior remain bench checks.

## Interruptible FIFO service bench build (10 October 2026)

Build environment: `bodaqs_s3_mini_n4r2_rc3_i2c_sliced`.
Firmware identity: `0.6.1-alpha-i2c-sliced-q2`.
Images: `firmware/dist/0.6.1-alpha-i2c-sliced-q2/`.
This retains the enlarged producer queues, transfer priority 2 and RC3 board
profile. The startup CHIP_ID probe remains disabled. This environment does not
enable the revision 2/3 extra-deferral policy.

The 50 Hz comparison (`261010_111510.bdq` and `261010_113146.bdq`) showed why
allowing more deferrals was insufficient. The relaxed build improved average
AS5600 throughput from 101.47 to 171.20 Hz, but 6.66% of its intervals exceeded
40 ms and those gaps occupied 64.31% of elapsed time. Its IMU services averaged
about 53 ms each. This experiment instead lets other clients run during a
logical FIFO drain, between complete I2C transactions.

Two per-IMU settings are available in the web configuration's Acquisition group
and in saved sensor parameters:

| Parameter | Default | Meaning |
| --- | --- | --- |
| `fifo_service_mode` | `whole` | `whole` retains existing complete-drain service; `sliced` enables resumable service |
| `fifo_slice_bytes` | `0` | Automatic payload ceiling of 128 bytes; an explicit 32..256 sets a different ceiling |

Sliced mode currently requires `orientation_400` or `orientation_800`, with equal
accelerometer and gyroscope rates. Explicit sliced selections for other
profiles are rejected. Existing configurations keep whole-drain behavior.
Select sliced mode for **each** IMU on the bus being tested. A remaining
whole-drain IMU can still block the bus for its complete acquisition.
Both settings are locked during logging and can change between sessions.

For example, for an IMU at sensor index 6 (substitute its actual index):

```ini
sensor6.profile=orientation_800
sensor6.fifo_poll_rate_hz=50
sensor6.fifo_service_mode=sliced
sensor6.fifo_slice_bytes=0
```

The sensor section and its name/address/bus must retain the normal configuration
syntax. The existing poll rate starts logical drain cycles; continuations are
eligible immediately, rather than waiting for another polling deadline. The
deadline advances once when a cycle completes. Missed periods are skipped using
the existing schedule rule. FIFO pressure can also start a cycle early.

There remains one worker per I2C bus. At each step boundary, it chooses FIFO
pressure first, a due latency-sensitive client next, then the FIFO continuation
with the oldest previous step, new due work, and optional IMU observations.
Unlike the earlier policies, a future AS5600 deadline does not make the worker
wait while useful FIFO work is available. Transactions release the bus mutex
and temporary priority boost before parsing or another client's service.

The automatic FIFO payload estimate uses the time remaining to the next active
latency-sensitive deadline, a 500 us overhead allowance, and the existing
400 kHz transfer estimate of 25 us per payload/protocol byte. A 32-byte minimum
guarantees progress when a deadline cannot accommodate a useful read. Explicit
payload settings are ceilings, not fixed transfer lengths; the deadline estimate
can choose a smaller transfer. These are scheduling estimates, not hard bounds
on driver latency. Recovery and transport timeout handling remain exceptional
blocking operations.

FIFO length is read at cycle start. Subsequent slices subtract only complete
stored frames from a cached backlog estimate and account for production during
elapsed time. A pressure-triggered length refresh is limited to once per 10 ms;
the tail's sensor-time/overread frame identifies an empty FIFO without a length
transaction after every short burst. Pressure means estimated headroom below
12 ms to the internal 1536-byte threshold, leaving margin within the 2048-byte
hardware FIFO. These controls are internal policy, not additional user settings.

Bosch repeats a partially read stored frame in full on the next FIFO access.
Partial trailing bytes are therefore discarded rather than concatenated with
the next read. Complete frames remain in the existing bounded parsed workspace
until a tail sensor-time anchor is received. Native ticks are then assigned to
the group, and at most 16 records are materialised per scheduler turn. Host
anchor interpolation uses the actual tail slice's transfer interval; it does
not stretch an interval across time spent serving the AS5600 or another IMU.
BDQ record layouts and native-rate selection remain unchanged.

A 120 ms anchor wait or impending workspace exhaustion publishes a confirmed
prefix with timing-degraded flags instead of retaining it indefinitely. An
uncertain transfer, malformed header or reported skip invalidates the cached
state: previously confirmed frames are published as degraded, and recovery
flushes the uncertain remainder with a discontinuity marker. A failure during
publication resumes at the existing cursor. Stop suspends sensor production,
finishes a retained group at step boundaries, then performs the existing final
empty check. An exceptional one-second/512-step stop limit reports a failed
drain and publishes any remaining confirmed prefix as degraded.

Temperature, standalone clock reads and optional IOC snapshots each get
separate lower-priority turns. FIFO pressure can postpone them to a later cycle.
The first sliced group can have stale temperature because no cached reading
exists yet; stale flags retain their existing meaning. Whole OLED transfers
are excluded on a bus with active sliced clients for the logging session.

BDQ v1/v2 summaries and CSV sidecars include `stepped_acquisition`,
`acquisition_steps` and `step_us`. For sliced clients they additionally report
`progress_steps`, `fifo_bytes_consumed`, `samples_published`, `pressure_overrides`,
`impossible_slice_windows`, `continuation_wait_maximum_us`,
`cycle_wall_maximum_us`, `fifo_slices`, `fifo_length_refreshes`,
`partial_slice_boundaries`, `anchor_timeouts`, `fifo_state_invalidations`,
`pending_frames_maximum`, `anchor_wait_maximum_us`, `fifo_slice_bytes`,
`fifo_slice_bytes_maximum` and `cycle_pending_at_scheduler_stop`.

`acquire_ok/fail`, achieved service rate and scheduler `acquire_us` count logical
cycles and their accumulated worker time. `step_us` and bus occupancy count
actual turns; `cycle_wall_maximum_us` includes intervening work/waits.
The IMU's `drain_call_us` is cycle wall time in sliced mode. Pressure overrides
count turns selected under the pressure rule; impossible slice windows count
sliced turns whose remaining AS5600 window is below the 1.5 ms minimum-read
estimate. Partial boundaries are expected and do not by themselves indicate
lost samples. Slice diagnostics include stop work; scheduler step/progress
totals stop with the worker, and a pending-at-stop cycle can finish afterward.
Session FIFO metadata and the logging-start serial line record service mode
and configured payload ceiling.

Start with automatic payload sizing and the existing 50 Hz FIFO polling rate.
Compare AS5600 200 Hz / IMUs 800/800 Hz, then AS5600 500 Hz / IMUs 400/400 Hz.
Keep primary rate, storage card, wiring and sensor configuration matched to
the comparison log. Review AS5600 interval tails as well as average rate, IMU
sequence/tick continuity, degraded timing, anchor waits, pressure steps, FIFO
skips/full events, recoveries, queue drops and storage stalls. Include repeated
start/stop cycles. Hardware improvement and runtime stack margin remain bench
acceptance checks; a successful build or host check does not establish cadence.

Validation: the full host suite passes under ordinary and relaxed policy
selections, including 497 sliced-service checks and the existing 42/32 policy
checks. New checks exercise every payload cap from 32 to 256, frame replay,
native tick wrap, anchor interval selection, cached backlog, pressure/fairness,
and publication/abort classification. Valid startup unpaired frames retain the
parser's quality flags without forcing a device restart; partial unpaired and
configuration frames do not double-count events when replayed.

The parameter store now allows 36 entries: room for up to 32 previously saved
parameters, both new FIFO settings and the web editor's temporary markers.
A compile-time check keeps the canonical BMI270 schema within that capacity.
Sliced RC3, ordinary RC3 and relaxed RC3 builds pass. The sliced ELF uses
182,916 bytes of static RAM and 1,856,717 bytes of program flash. Its worker,
sliced state-machine, publication and anchor-preparation frames use 192, 208,
192 and 80 bytes respectively, within the existing 4096-byte worker stack.
These individual compiled frames are not a measured runtime stack watermark.
Packaged identities, component offsets, erased gaps, startup-probe absence
and all four SHA-256 hashes were verified.

## Sliced FIFO revision 2: progress evidence and bounded catch-up

The 10 October first sliced bench run exposed firmware-induced no-progress
recoveries, despite successful transport and valid operational registers. A
peer's blocking restart could delay a client's first read beyond the 120 ms
anchor deadline. That client then published an empty group and checked a wall
watchdog in optional work, without giving its FIFO another read opportunity.
Repeated successful restarts could consequently exhaust the three-attempt
recovery budget. Cached pre-restart pressure also survived a successful flush.

RC3 test firmware `0.6.1-alpha-i2c-sliced2-q2` corrects that interaction:

- The anchor deadline starts when the first complete sample is retained. A
  delayed first read is always allowed; workspace bounds still apply.
- Sliced no-progress recovery requires fresh, repeated empty FIFO observations
  spanning 250 ms. A gap exceeding the greater of 100 ms and three configured
  FIFO polling periods breaks that evidence, as does real sample progress or
  positive FIFO length. Optional observation completion/skipping cannot cause
  a no-progress restart. Wall-time diagnostics remain available.
- Successful flushes clear sliced phase, publication cursors, anchor wait and
  empty evidence, and seed an empty backlog estimate at flush completion.
  Failed restart/flush leaves backlog unknown. Confirmed data is published
  before a fault-triggered flush, retaining existing discontinuity semantics.
- Known FIFO pressure uses the configured payload ceiling (128 bytes in auto
  mode), even if the next AS5600 deadline is overdue. Acquiring the initial
  native-time anchor also uses that ceiling for a known nonempty FIFO. Once
  anchored and clear of pressure, ordinary deadline-based sizing resumes.
- Pressure priority yields after four turns or 6 ms, whichever comes first.
  An overdue unbuffered client gets the next turn; otherwise the oldest pending
  non-auxiliary FIFO continuation does. The burst budget resets after that turn
  or ordinary non-pressure work. Ties retain rotating fairness.

The time bound is checked between turns and can be exceeded by one in-flight
transaction. Blocking recovery, driver timeouts and other exceptional work can
exceed it further. Useful catch-up deliberately increases individual FIFO read
duration and can miss AS5600 slots; bounded yielding can in turn increase FIFO
pressure or overflow under unsustainable load. This is a throughput/fairness
tradeoff, not a guarantee that every requested cadence fits the bus.

No new configuration is required. Slicing remains opt-in with existing
`fifo_service_mode=sliced` and `fifo_slice_bytes=0` settings. Explicit 32..256
byte ceilings remain ceilings during catch-up. The pressure burst and empty
evidence thresholds are internal policy for this trial. Ordinary whole FIFO
service retains its existing wall watchdog and scheduling behavior. The startup
probe remains disabled and enlarged queues remain enabled.

All three runtime-summary formats additionally record `pressure_yields` for
every scheduler client, including AS5600. Sliced clients also record
`catchup_slices`, `empty_fifo_observations` and `empty_progress_recoveries`.
These distinguish catch-up, fairness turns and genuine observed empty-FIFO
recovery from scheduling lateness.

Validation includes the full host suite under ordinary and relaxed policies
(518 sliced helper/parser checks each), and 195 production state-machine
checks. `python tools/test_sliced_runtime.py` extracts the actual production
methods verbatim and executes them against a controlled clock and fake device,
using the production FIFO parser and scheduler selector. It covers delayed
first reads, repeated peer restart delays, persistent fresh emptiness and
bounded terminal recovery, successful/failed flush state, transfer failures,
bus-generation change during publication, and two pressured FIFO clients with
an overdue AS5600. Register setup and record materialisation are mocked; this
does not establish hardware cadence, electrical reliability or stack watermark.
The runtime fixture is also included in `make -C test test`.

Bench comparison: retain the same card, wiring and primary rate; use sliced
service with automatic ceiling and 50 Hz FIFO polling on every tested IMU.
First compare AS5600 200 Hz with 800/800 Hz IMUs, then AS5600 500 Hz with
400/400 Hz IMUs. Inspect serial recovery lines, all native sequences and ticks,
anchor timeouts/degradation, FIFO skips/overflows, AS5600 interval tails and
the new counters. Include repeated start/stop and warm restart checks.

Sliced RC3, ordinary RC3 and relaxed RC3 builds pass. The revision 2 sliced ELF
uses 183,468 bytes of static RAM and 1,859,105 bytes of program flash. Compiled
worker/state-machine/publication/preparation frames are 208/208/192/80 bytes;
the new empty-observation helper uses 32 bytes. These sizes are not a runtime
stack watermark. The package at `firmware/dist/0.6.1-alpha-i2c-sliced2-q2/`
contains RC3 application, bootloader, partition and combined images, with
verified identity, offsets, erased gaps and SHA-256 hashes; the startup probe
has no symbol in the ELF.

## Sliced FIFO revision 3: retain valid skip reports and reach anchors earlier

The revision 2 comparison had two distinct problems. In the 200 Hz primary/
AS5600, 800/800 Hz IMU run, each IMU performed about 703 full recoveries despite
zero reported I2C transport failures. A complete FIFO skip report was treated
as uncertain alignment and triggered a restart. The restart could block peer
service longer than their FIFO capacity, causing further overflows and
restarts. The initial cause of overflow is not established by that log.
In the 500 Hz primary/AS5600, 400/400 Hz IMU run, all IMUs retained their sample
cadence without recoveries, but Bus 1 repeatedly hit the 120 ms anchor deadline
and published almost entirely degraded timing. Useful catch-up started too late.

RC3 bench firmware `0.6.1-alpha-i2c-sliced3-q2` changes sliced service as follows:

- A complete, valid skip control frame preserves parser alignment. Confirmed
  samples remain retained and draining continues; there is no flush or restart
  solely because a skip report occurred. The reported loss and discontinuity
  remain attached to the first subsequent sample. The affected retained group
  is marked as having degraded timing, including when the count saturates at
  255 and cannot establish the full loss. A trailing report carries its loss
  and timing flag into the next group. Malformed headers, output capacity loss
  and failed transport still follow the existing recovery path.
- A skip report invalidates the estimated residual byte count. Unless that
  same read reached the tail, the next turn reads the actual FIFO length before
  continuing catch-up. This avoids estimating pressure from already lost data.
- Catch-up begins with a known backlog representing at least 20 ms of samples
  (104 bytes at 400/400 Hz; 208 bytes at 800/800 Hz), or when the first retained
  sample has waited 20 ms for an anchor. Initial-anchor acquisition retains its
  earlier catch-up behavior. Once active, catch-up keeps using the configured
  payload ceiling until sensor time/overread establishes the tail, an empty
  FIFO is confirmed, or the state is reset after a fault/session change. A
  degraded publication at the existing 120 ms bound does not clear this latch.
- The useful payload remains 128 bytes in auto mode, with explicit 32..256
  byte ceilings respected. Catch-up starts earlier; it does not introduce a
  new scheduler priority. Critical pressure remains the 12 ms headroom rule,
  with the revision 2 yield after four turns or 6 ms checked between turns.

The [Bosch BMI270 datasheet](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmi270-ds000.pdf)
describes overflow loss through skip control frames. This change uses the
existing parser's complete-frame and loss-boundary handling; it does not treat
an arbitrary malformed byte as an overflow report.

Earlier, larger FIFO reads can increase individual AS5600 delays. Continuing
catch-up after degraded publication also uses more bus time when overloaded.
This trial aims to preserve useful FIFO acquisition and timestamps without
amplifying overflow into blocking restarts; it cannot guarantee loss-free
service when aggregate demand exceeds bus throughput. The timing/loss flags
remain visible for analysis rather than concealing overflow.

No new configuration is required. Use `fifo_service_mode=sliced`,
`fifo_slice_bytes=0` and `fifo_poll_rate_hz=50` on every tested IMU. Repeat the
matched 200/800 and 500/400 comparisons with the same card and wiring; include
start/stop and warm restart checks. Ordinary whole FIFO service, startup-probe
disablement and enlarged queues retain their previous behavior.

BDQ v1/v2 summaries and CSV sidecars add `catchup_entries` (transitions into
latched catch-up) and `fifo_skip_reports_handled` (complete skip reports handled
without invalidating alignment). Existing catch-up slice, pressure, anchor,
loss, recovery and timing counters remain available. Compare AS5600 interval
tails, IMU native tick/sequence gaps, timing degradation, fresh sensor-time
anchors and storage stalls, as well as average sample rates.

Validation: the ordinary and relaxed host suites pass, including 528 sliced
helper/parser checks each. The production-method runtime fixture passes 419
checks. It exercises early and age-based catch-up, latching and explicit
ceilings, valid skip counts of 3 and 255, loss-boundary preservation without
duplication, and malformed-header recovery. Two continuously producing FIFOs
with an unbuffered client reach repeated anchors without anchor timeouts or
recoveries at both comparison profiles in the controlled simulation. A
separate 800/800 Hz stress case delays both clients by one second to overflow
their FIFOs: loss and initial anchor timeouts remain, but both resume reaching
anchors during the second half of the four-second simulation, without a
restart. Register transactions, electrical behavior and record materialisation
remain mocked; these checks do not establish hardware cadence or stack margin.

Sliced RC3, ordinary RC3 and relaxed RC3 builds pass. The revision 3 sliced ELF
uses 183,724 bytes of static RAM and 1,860,233 bytes of program flash. Compiled
state-machine/publication/preparation frames remain 208/192/80 bytes; the
empty-observation helper uses 32 bytes. The package at
`firmware/dist/0.6.1-alpha-i2c-sliced3-q2/` contains the RC3 application,
bootloader, partitions and combined images, with verified identity, offsets,
erased gaps and SHA-256 hashes. The startup probe is absent from the ELF.

## Startup recovery and diagnostics trial

RC3 bench firmware `0.6.1-alpha-i2c-startup-q2` retains sliced revision 3
acquisition and adds bounded startup recovery. The new PlatformIO environment
is `bodaqs_s3_mini_n4r2_rc3_i2c_startup`. Existing sensor configuration remains
valid; this trial introduces no configuration fields or recording format changes.

The shared recovery policy now checks controller creation and clock setup before
advertising a bus as available. Mutex allocation failure also leaves the bus
unavailable. AS5600 address probes make three attempts with 10 ms gaps; when
permitted, one controller recovery allows another three attempts. BMI270 startup
can request one controller recovery for a successfully received but incorrect
chip ID as well as for transport failure. The required ID remains exactly
`0x24`; neither masking nor accepting a different ID is used. Configuration or
allocation failures alone do not request that recovery.

After the normal startup sequence, a coordinator records the initialization
state of every configured BMI270 and AS5600 instance. If any failed, it waits
250 ms and retries only those devices. Ordinary builds get this one delayed
retry, with the usual local recovery allowed. The diagnostic build separates
three application-level stages:

1. A delayed retry without an explicit controller reset.
2. One forced controller reinitialization per affected bus, followed by retries.
3. A temporary 100 kHz clock on each still-affected bus, followed by retries.

Each diagnostic stage reads the BMI270 chip-ID register or the AS5600 raw-angle
register three times, with 5 ms gaps. At least one valid read is required before
attempting full sensor initialization in that stage. BMI270 validity requires
`0x24`; AS5600 validity requires a complete successful transfer, not a magnet.
Successful peers are not reinitialized. A shared controller reset nevertheless
affects their bus, and its recovery generation changes. All stages run before
acquisition workers start; forced reset and clock overrides are rejected while
the scheduler is running. The configured clock is restored before normal
acquisition. Restoration failure leaves the bus unavailable and is included in
the final failed-device count, including previously healthy peers on that bus.

The coordinator runs after `[BOOT] SETUP: ALL DONE`. Capture serial output from
before the reset, because individual initialization-attempt diagnostics precede
that point. `[I2C-STARTUP] initial` describes the end of normal initialization,
including any local recovery already performed; it is not a snapshot before
the first recovery. The diagnostic image prints successful and failed BMI270
attempts, the raw chip byte, read length and ESP error, plus each staged probe,
retry and final health result. `[I2C] recovery controller_ready` means only that
the controller, buffers, clock and released lines passed their checks:
`device_response=unchecked` makes that limitation explicit. The `_low` fields
are booleans: zero means the line was not held low. Cooldown-skipped recovery
is reported explicitly; forced startup recovery bypasses the cooldown.

To preserve the original ESP error rather than Wire's collapsed return value,
the diagnostic build's BMI270 identity probes and staged register probes call
the same Arduino `i2cWriteReadNonStop` HAL used by `Wire.requestFrom()` directly,
under the manager's bus mutex. The START line identifies this as
`identity_path=arduino_hal`. Normal configuration and FIFO transfers still use
Wire, and ordinary builds retain Wire identity reads. This wrapper bypass is
itself a diagnostic variable: improved behavior would not alone prove that
delaying startup or resetting a controller caused the improvement. The IDF
driver can also perform internal error recovery during a transaction; the
stage names describe explicit application actions, not every driver action.

The trial does not cycle sensor power, change CSB or add forced clock pulses
to an otherwise released bus. Existing bus clear remains limited to at most
nine open-drain SCL pulses when SDA is held low and SCL can be released. Failed
boots can take longer because probe and full initialization attempts are
bounded but repeated. There is no periodic startup experiment during logging.

For bench acceptance, retain the same wiring, card and acquisition settings;
save complete cold-boot and warm-restart serial logs through
`[I2C-STARTUP] DONE`, alongside subsequent recordings. Check the earliest
`imu_attempt`/`as5600_probe` failures, which stage restored service, whether the
raw chip read was wrong or the transfer failed, and any `clock_restore` error.
An AS5600 with no magnet can pass initialization while still reporting magnetic
status errors during acquisition. The always-on sensor rail means controller
reinitialization is not a sensor power cycle.

Host validation passes 27 startup coordinator/probe checks and 46 checks of
the production manager and FIFO startup method with injected faults. These
cover temporary NACKs, persistent wrong IDs, shared buses, clock/lock/buffer
failures, active-acquisition guards, clock restoration, and bounded retries.
The existing full host suite, including 419 sliced production-runtime checks,
also passes. Hardware and driver behavior are mocked in these checks; they do
not establish that the intermittent bench fault is fixed.

The diagnostic RC3, ordinary RC3, A8 and Prototype F builds pass. The diagnostic
RC3 ELF uses 183,732 bytes of static RAM and 1,865,597 bytes of program flash.
The package at `firmware/dist/0.6.1-alpha-i2c-startup-q2/` contains application,
bootloader, partition and combined images with verified identity, component
offsets, erased gaps and SHA-256 hashes. The application image passes ESP image
checksum/hash validation. The new startup diagnostics are present in the ELF;
the old `BMI270I2CProbe::run` sweep is absent.

## Optional startup reports on SD (11 October 2026)

The General configuration page now has **Save startup diagnostics to SD**.
It defaults to off. Enable it, save the configuration, and restart; disabling
it also takes effect on the next restart. The corresponding configuration key
is `startup_log_to_sd=true` (or `false`). Existing configurations that omit the
key retain the disabled default.

When enabled, firmware allocates a 32 KiB capture buffer after loading the
configuration, before starting either I2C bus or initializing sensors. It
captures the existing BMI270 initialization-attempt and AS5600 probe messages,
local controller recovery, and the staged startup diagnostics through their
final device-readiness results. The header includes firmware and board identity,
reset reason, primary rate, log format, bus pins and rates, and relevant sensor
configuration. It does not copy the complete configuration or serial transcript.
Successful boots are saved too, so failed reports have a useful denominator.

Only after startup recovery finishes does firmware write one report to SD.
Files rotate through `/startup/boot-00.txt` to `boot-31.txt`, retaining the latest
32 successfully saved reports. The `sequence` header determines chronological
order; filenames wrap around. Sequence numbering does not depend on valid RTC
time. The footer records completion uptime, RTC validity and epoch time, plus
final I2C device and failure counts. If capture overflows, it retains a prefix of
complete messages, marks the loss with `capture_overflow=1` and dropped-message
and byte counts, and still reserves space for the final readiness summary.

The save uses the existing temporary-file/backup/rename mechanism. A short write
or failed final rename preserves the previous report in that slot. It is
best-effort: an unavailable card or RAM allocation failure is reported on serial
and startup continues. The capture allocation is released after saving, including
failed saves. Disabled capture allocates no buffer and accesses no report files;
existing reports remain on the card. Acquisition does not record or write these
reports. A crash or loss of power before the deferred save leaves no complete
report for that boot; interrupted filesystem operations can leave a `.tmp` or
`.bak` file. These reports are intended for initialization failures that still
allow startup to complete, rather than as a crash recorder.

The RC3 package is `firmware/dist/0.6.1-alpha-i2c-bootlog-q2/`, built with
`bodaqs_s3_mini_n4r2_rc3_startup_log`. It retains the restored whole-FIFO,
two-deferral scheduler, enlarged producer queues, transfer priority and existing
startup recovery diagnostics. The logging option itself does not enable extra
recovery stages: ordinary builds retain their existing delayed-retry policy;
this diagnostic RC3 image retains controller-reset and 100 kHz stages, and the
`arduino_hal` identity path. The earlier long `IMU-PROBE` sweep stays disabled.

Bench acceptance: enable and save the checkbox, then restart with serial
connected. Confirm `[STARTUP-REPORT] saved /startup/boot-XX.txt` and read the
report from SD. Compare its earliest attempts, recovery actions and final state
with serial. Repeat a warm restart and a cold boot, then disable the option and
confirm subsequent restarts produce no new report. Include both healthy boots
and any naturally occurring initialization failures.

Validation: the full host suite passes, including 70 checks running the
production collector, buffer and SD rotation/save code with injected failures.
They cover preservation of early failures, overflow and final readiness,
disabled capture, rotation, short writes, failed renames, unavailable SD,
allocation failure and active-acquisition guards. Diagnostic RC3, ordinary
RC3, A8 and Prototype F builds pass. The RC3 image checksum and validation hash,
combined-image component offsets and erased gaps are verified; SHA-256 hashes
are included with the package. The General-page interaction and physical SD
behavior still need the bench acceptance above.

## Configuration warnings and automatic log-format selection (11 October 2026)

The RC3 bench image `0.6.1-alpha-log-start-q2` adds log-start feedback while
retaining the restored whole-FIFO, two-deferral acquisition policy and optional
SD startup reports. Its PlatformIO target is
`bodaqs_s3_mini_n4r2_rc3_log_start`; packaged images are under
`firmware/dist/0.6.1-alpha-log-start-q2/`.

While idle, the home screen displays a persistent two-line message:

- `Config conflict` / `Please review`: active sensors share an I2C bus/address,
  GPIO input, external ADC channel, or UART. Cross-type conflicts are included;
  logical AIN assignments resolve to their physical inputs. Differential ADC
  assignments also reserve their negative channel. Duplicate sensor names and
  active IMU identifiers are conflicts too. The configured fuel gauge, RTC and
  both OLED candidate addresses are reserved on their respective buses.
- `Restart required` / `Press Enter`: the saved sensor set or acquisition settings
  differ from the running objects and could not be applied live. Adding,
  removing, renaming or changing a sensor type/physical assignment can produce
  this condition. BMI270 comparisons include profile, FIFO/output rate, bias,
  orientation and metadata settings. Successfully applied edits, and edits
  reverted to match the running configuration, clear the warning automatically.
- `Sensor config` / `Please review`: an invalid sensor type, missing/invalid input
  or invalid BMI270 setting requires correction, rather than a restart.

Conflict detection precedes restart checks. Muted sensors do not reserve input
assignments or force a format upgrade; unique sensor names remain mandatory.
The menu's runtime mute overrides remain effective even when the saved default
is unchanged. A changed saved mute default that has not reached the live object
can itself require restart. Muting affects firmware use, not a physical device's
I2C address: electrically conflicting devices still need hardware correction.

A complete fresh press/release of physical Enter on the home screen acknowledges
the restart prompt, independent of configurable button bindings. It performs
the existing warm restart, including RTC invalidation; it does not start a
recording after reboot. Releasing the gesture that exposed an error or closed
a menu cannot acknowledge a new prompt. Recording and upload mode retain their
existing button behavior.

General, Sensors and individual sensor configuration pages show the specific
reason. Successful saves update or clear that notice without a page reload.
Serial records status changes and detailed start refusals. Idle checks run at
most four times per second, plus an immediate check at log start/Enter or a
configuration-page request; they perform no sensor reads or bus probes.

At log start, multiple active BMI270s or a mixed accel/gyro rate profile select
`bodaqs_multi_stream_binary` (BDQ v2) when CSV or BDQ v1 was selected. The
selection is saved before sensor preparation or file creation, announced on
serial and briefly on the OLED, and shown as the actual format on the recording
screen. A failed configuration save refuses the start rather than silently
recording a different format. Compatible CSV/BDQ v1 selections remain unchanged;
there is no automatic downgrade. Existing power, upload-mode, SD/file-open,
column-count and sensor/session checks still apply. BMI270 initialization
failure remains a diagnostic/unavailable-stream condition and can allow other
sensors to record; it is not automatically a restart prompt.

`ConfigManager::setLogFormat` now returns save success. Existing callers may
ignore the return value; automatic promotion checks it explicitly. No new
configuration keys or changes to the BDQ file schema were introduced.

The full host suite passes, including 116 checks of extracted production
preflight, BMI270 parameter comparisons, Enter dispatch, web notices, format
persistence and start control flow with hardware/filesystem calls mocked.
Checks cover conflict precedence, mixed sensor types, bus scope, analog aliases,
differential channels, board devices, runtime muting, missing/removed/changed
instances, reverted edits, failed saves, legacy-format preservation, HTML
escaping, notice clearing and session cleanup. The existing production scheduler,
startup recovery and startup-report checks also pass. RC3 bench, ordinary RC3,
A8 and Prototype F builds pass; the packaged image checksum and validation hash
are verified. Physical UI and SD acceptance still need the bench checks below.

Bench acceptance:

1. Save a BMI270 profile/address change requiring restart. Confirm the home
   prompt appears before attempting a log, and one fresh Enter press restarts
   the device. Confirm the normal channel view returns after startup.
2. Save a duplicate active assignment. Confirm the conflict prompt and web/serial
   detail. Correct it (or mute one sensor) and confirm the warning clears; a
   conflict must not cause automatic restart or a format change.
3. With multiple active IMUs, select CSV or BDQ v1 and start. Confirm automatic
   BDQ v2 selection, the recording-screen format, file/catalog contents and the
   selection persisting after restart. Repeat with one mixed-rate IMU.
4. With one equal-rate IMU (or no active IMUs), verify a compatible CSV/BDQ v1
   choice stays selected. Confirm ordinary menu navigation and stop/start work.
5. Revert a saved restart-requiring edit before restarting. Confirm the prompt
   clears, and releasing an already-held Enter cannot trigger a restart.


### Sensor-list Input column (11 October 2026)

The Sensors page now includes Input after Type, showing the configured input
for each sensor, including muted or unavailable sensors: `I2C1 [0x68]`, `AIN4`,
or `UART0`, for example. I2C addresses use hex; omitted I2C and UART settings
use their sensor defaults. Legacy GPIO assignments map to an AIN label when
that pin appears in the board profile; otherwise the GPIO is shown explicitly.
Missing assignments show `Unassigned`.

RC3 image: `0.6.1-alpha-sensor-inputs-q2`; target
`bodaqs_s3_mini_n4r2_rc3_sensor_inputs`; package
`firmware/dist/0.6.1-alpha-sensor-inputs-q2/`. This retains the preceding
log-start behavior, two-deferral scheduler and optional startup SD reports.
