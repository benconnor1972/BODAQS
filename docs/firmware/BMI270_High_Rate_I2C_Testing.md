# BMI270 high-rate I2C test plan

Status: exploratory mixed-bus endpoint; full-length bench runs completed and
bike qualification pending, 2026-09-19.

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

This is the endpoint for optimising buffered and unbuffered sensors on the same
400 kHz trunk. Do not add further AS5600 priority levels, reduce BMI270 FIFO
service below 10 Hz, or admit 10 Hz service for higher-throughput profiles. If
the final experiment is insufficient, change the transport architecture: use a
separate bus, qualify Fast-mode Plus electrically, choose a buffered rotary
sensor, or move acquisition to a satellite node.

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
