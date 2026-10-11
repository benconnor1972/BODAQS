# I2C scheduling experiments: findings and rollback

Date: 10 October 2026  
Status: experiments closed at the user's request; whole-FIFO service and the
fixed two-deferral policy restored. The restored build still needs a hardware run.

## Decision

The additional scheduling complexity did not establish either desired operating
point with all four IMUs active: AS5600 at 500 Hz alongside 400/400 Hz IMUs, or
AS5600 at 200 Hz alongside 800/800 Hz IMUs. Some revisions improved average
throughput or individual timing metrics, but none demonstrated the combined
AS5600 cadence, IMU continuity and timestamp quality needed to justify keeping
the experimental machinery. The 500 Hz AS5600 / 800 Hz IMU combination was a
stress comparison, rather than an accepted target.

The firmware returns to the simpler bounded-priority scheduler. This is a
complexity and reliability decision, not a claim that the original scheduler
achieves every requested rate. There was no matched original-policy repeat for
every later configuration, so the evidence cannot rank all policies at all
operating points.

## Setup and measurement

The relevant bench load was two BMI270s on each I2C bus, with the AS5600 sharing
Bus 1. I2C ran at 400 kHz. BDQ v2 retained the primary stream, independently
acquired AS5600 records and native IMU streams. The primary row rate, AS5600
acquisition target, IMU ODR and FIFO polling rate are separate quantities;
raising the primary rate does not itself raise sensor acquisition throughput.

Raw recordings are retained in
`C:\Users\benco\OneDrive\BODAQS-private\Test\I2C`. Run names below identify
those `.bdq` files. Analysis used their recorded configuration, final summaries,
native sequence numbers, sensor-time increments, status flags and acquisition
interval distributions. Detailed historical build notes are in
[BMI270 high-rate I2C testing](BMI270_High_Rate_I2C_Testing.md).

The AS5600 was tested without a magnet. Magnetic status errors were expected;
successful transport and fresh records do not establish valid angle measurements.
The bench wiring evolved during earlier troubleshooting: CSB tied to VDDIO,
signal/ground twisted pairs, fewer connectors and series damping resistors.
The LTC4311 accelerators were subsequently physically disconnected. Sensors
used the logger's always-on 3.3 V rail.

## What changed during the trials

**Original bounded priority.** One worker services each bus. Equal-rate clients
are staggered and equal-deadline selection rotates. Before starting a whole
FIFO acquisition, the worker may service an AS5600 deadline that would otherwise
fall inside it. Each pending FIFO service can yield at most twice, after its
first successful acquisition and within its declared maximum service gap.
Normal gaps are capped at 70 ms and further limited by FIFO production and a
60% capacity allowance. An existing experimental 10 Hz mixed-profile case
allows up to 140 ms. A transfer already on the wire is never interrupted.

**Transfer priority.** Acquisition workers temporarily raised their FreeRTOS
priority during I2C transfers, then returned to their normal priority. This
modest change remained separate from FIFO admission policy and is retained in
the restored RC3 build.

**More deferrals using a FIFO model.** Cached FIFO length, configured production
rate, predicted drain cost and the needs of other FIFO clients determined whether
additional AS5600 services were safe. These estimates used configuration and
existing observations, without extra bus transactions solely for scheduling.
The first model and a refined setup/overhead model still rejected many deferrals.
The refined policy particularly tightened admission once a backlog approached
one polling period; more allowed yields were ineffective when other guards
refused them.

**Relaxed admission.** A deliberately aggressive bench revision raised the FIFO
allowance from 60% to 85%, used a 120 ms projected-start limit, removed the
separate one-poll drain-duration ceiling, allowed up to 64 yields and replaced
recent maximum cost estimates with less conservative means. It improved average
AS5600 throughput relative to the conservative revision at 50 Hz polling, but
allowed large bursts and long gaps.

**Interruptible logical FIFO service.** Subsequent revisions split acquisition
into complete I2C transactions and bounded processing steps. The scheduler
could service the AS5600 between length reads, FIFO payload reads, parsing,
publication and optional observations. Transfers themselves remained atomic.
Per-IMU settings selected whole or sliced service and a payload ceiling, with
128 bytes automatic and explicit ceilings of 32–256 bytes. Sliced service was
limited to the equal-rate 400 and 800 Hz profiles.

This introduced partial-frame replay, pending sample groups, delayed sensor-time
anchors and separate progress/recovery rules. The first hardware run exposed
FIFO configuration validation failures and terminal acquisition faults.
Follow-up revisions corrected the configuration/validation interaction, bounded
catch-up and required fresh progress observations. Another revision stopped
treating a complete, valid FIFO skip report as loss of parser alignment, and
started useful-size catch-up reads earlier so pending groups could reach their
time anchors. Those fixes addressed experiment-specific failures; they did not
remove the service-time and overhead tradeoff.

## Results that drove the decision

Unless marked otherwise, all four IMUs initialized and contributed data. Equal
IMU rates in this table mean both accelerometer and gyroscope rates. AS5600
rates are average achieved acquisition rates, not guaranteed periodic cadence.

| Run | Policy / main change | Primary / AS5600 target (Hz) | IMUs / FIFO polling (Hz) | AS5600 achieved (Hz) | Finding |
| --- | --- | --- | --- | --- | --- |
| `261009_211010` | Original two-deferral | 500 / 500 | 800 / 25 | 169.24 | Reference under full load; no reported skips or recoveries |
| `261010_063703` | Two-deferral + transfer priority | 500 / 500 | 800 / 25 | 177.15 | About 4.7% higher throughput; still far below target |
| `261010_085930` | FIFO model, revision 1 | 500 / 500 | 400 / 25 | 283.58 | No reported skips or recoveries; target unmet |
| `261010_094929` | FIFO model, revision 2 | 500 / 500 | 400 / 25 | 263.99 | Lower throughput than revision 1 |
| `261010_100042` | FIFO model, revision 2 | 200 / 200 | 800 / 25 | 82.52 | Target unmet |
| `261010_102422` | FIFO model, revision 2 | 500 / 500 | 800 / 25 | 126.31 | Matched full-load comparison worse than 177.15 Hz reference |
| `261010_111510` | FIFO model, revision 2 | 500 / 500 | 800 / 50 | 101.47 | More frequent FIFO service did not help |
| `261010_113146` | Relaxed FIFO model | 500 / 500 | 800 / 50 | 171.20 | Improved mean; p99 interval 59.08 ms, maximum 154.54 ms |
| `261010_123537` | First sliced build | 500 / 500 | 800 / 50 | 155.56 | Recovery/validation problems and early terminal faults |
| `261010_134541` | Sliced revision 2 | 200 / 200 | 800 / 50 | 2.93 | Recovery cascade: 2,812 recoveries and 717,084 hardware skips |
| `261010_141527` | Sliced revision 2 | 500 / 500 | 400 / 50 | 268.57 | No reported skips; approximately 99.92% of each Bus 1 IMU's samples timing-degraded |
| `261010_194252` | Sliced revision 3, automatic ceiling | 200 / 200 | 800 / 50 | 116.68 | Bus 1 lost 80,091 samples; approximately 97.6–97.8% timing-degraded |
| `261010_195943` | Sliced revision 3, automatic ceiling | 500 / 500 | 400 / 25 | 273.51 | Clean IMU continuity; timing-degraded fraction below 0.014% per IMU |
| `261010_203943` | Sliced revision 3, Bus 1 ceiling 64 bytes | 500 / 500 | 400 / 25 | 280.28 | Small throughput gain, substantial timestamp-quality regression |

The four runs `261010_150215`, `261010_151042`, `261010_152334` and
`261010_161757` initially looked promising: AS5600 achieved approximately
458–469 Hz at a 500 Hz target, and 195.7–195.8 Hz at a 200 Hz target. Both Bus 1
IMUs had failed initialization despite being connected and expected to work.
These were useful demonstrations of AS5600 throughput without the competing
Bus 1 FIFO load, not qualification of the intended configuration.

The last two fully connected 400 Hz IMU runs show the payload tradeoff clearly:

| Metric | Automatic ceiling, `195943` | 64-byte Bus 1 ceiling, `203943` |
| --- | --- | --- |
| AS5600 achieved rate | 273.51 Hz | 280.28 Hz |
| AS5600 p99 interval / maximum | 7.785 / 10.464 ms | 7.316 / 13.795 ms |
| Bus 1 worker acquisition occupancy | 80.57% | 89.00% |
| Bus 1 IMU timing-degraded fractions | 0.0138% / 0.0062% | 16.89% / 18.13% |
| Bus 1 sensor-time anchor timeouts | 0 / 0 | 400 / 438 |
| Reported FIFO skips, recoveries, transport failures | Zero | Zero |

Smaller reads improved average AS5600 throughput by only 2.47%, while almost
doubling the number of FIFO reads per second and delaying the time anchors.
Even those smaller FIFO reads averaged about 2.39 ms, exceeding the AS5600's
2 ms target period. Transaction/setup overhead consumed more worker time.
Regular reconstructed IMU tick increments and zero sample-loss counters did
not cancel the recorded timing-degraded flags: sequence continuity and
timestamp quality are different acceptance criteria.

## What we learned

- **Whole-service deferral changes who waits; it does not shorten the eventual
  drain.** Allowing additional deferrals can accumulate larger FIFO batches and
  make the next AS5600 gap longer. More polling reduces batch size but increases
  setup and optional-observation overhead; it was not a reliable improvement.
- **Slicing can improve sharing but has a real cost.** Tiny payloads are not free
  time slots. They increase transaction count, parser/progress state and the time
  required to reach a FIFO-tail sensor-time anchor. The useful middle ground in
  one 400 Hz run still delivered only about 274 Hz on the AS5600.
- **Average rate alone hid unacceptable behavior.** Long gaps, terminal faults,
  hardware skips and timestamp degradation each appeared in different revisions.
  Full-load initialization must also be checked before interpreting a result.
- **The recorded bottleneck was broader than payload bandwidth.** Worker
  acquisition occupancy includes transfer and processing time, not just I2C
  wire occupancy. At the latest operating points it was high; actual service
  duration and repeated setup costs matter alongside nominal byte-rate estimates.
- **Storage and acquisition need separate diagnosis.** In the final three runs,
  the enlarged primary queues absorbed SD stalls without primary missed slots
  or queue drops. Maximum stalls were approximately 236, 245 and 252 ms. This
  supports retaining the queue/storage work, but does not qualify every card or
  logging duration. Healthy primary storage did not imply healthy native sensors.
- **Initialization faults remain a separate unresolved issue.** Historical
  failures affected different devices and groups. A nominal full power cycle did
  not always recover them; a later warm restart did. Electrical/startup/receive
  path investigations therefore remain relevant, but no cause was established.
  The latest startup log showed all devices initializing on their first attempt,
  so its recovery stages were not exercised by that successful boot.

The CAN-FD scheduler abstraction was considered conceptually, then deferred.
These experiments did not produce a reusable CAN acquisition implementation.
Host tests checked policy boundaries, frame handling and injected recovery
behavior; they could not establish physical bus timing or achieved cadence.

## Restored firmware and compatibility

The restored implementation uses original whole-FIFO acquisition and the fixed
two-yield deadline look-ahead. Model-based extra deferrals, stepped acquisition,
slice/catch-up state and their configuration editor controls are removed. The
original whole-FIFO parser and progress behavior are restored with them.

Saved `fifo_service_mode` and `fifo_slice_bytes` entries are ignored. There is
no requirement to edit the SD configuration before using this build. Existing
`profile`, `fifo_poll_rate_hz` and AS5600 rate settings still apply; rollback
does not change the configured operating point. Metadata reports whole service
and `fixed_two_deferral`, and serial identifies the restored policy.

The separate enlarged primary/AS5600 queues, ADC wait and stack-safety fixes,
transfer-priority support, startup diagnostics and startup/bus recovery
hardening remain. The delivered RC3 diagnostic build retains the staged
startup recovery and Arduino HAL identity-read path from the latest trial.
That transport difference remains an experimental variable; this is not a
byte-for-byte return to the old image. The earlier long startup speed probe is
not enabled.

RC3 build environment: `bodaqs_s3_mini_n4r2_rc3_i2c_startup`.  
Firmware identity: `0.6.1-alpha-i2c-simple2-q2`.  
Package: `firmware/dist/0.6.1-alpha-i2c-simple2-q2/`.

Validation: the host suite passes, including 24 checks of the production
scheduler's selection and fixed yield limit, and 46 injected-fault checks of
the retained startup recovery. RC3 diagnostic, ordinary RC3, A8 and Prototype F
builds pass. Hardware acceptance of the restored image remains outstanding;
the first log should confirm all expected devices initialized, native IMU
continuity/timing quality, actual AS5600 rate and storage queue behavior.
