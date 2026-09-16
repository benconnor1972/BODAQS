# BMI270 high-rate I2C test plan

Status: experimental firmware test contract, 2026-09-14.

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
- `fifo_poll_rate_hz`: 25, 50, 100, 200, or 400 Hz. This controls how often the
  FIFO is serviced, not the IMU sample rate.
- `max_output_rate_hz`: legacy CSV/BDQ-v1 row materialisation only. Use BDQ v2
  to retain each IMU at its selected native rate.

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

## Bench sequence

Use BDQ v2, disable radio/UI activity, and retain the intended two-IMUs-per-bus
wiring and 600-1200 mm trunks.

1. Establish a clean four-IMU baseline at 200 sample/s and 200 Hz FIFO service.
2. For 400 and 800 sample/s, test FIFO service at 200, 100, then 50 Hz. Lower
   service rates reduce transaction setup overhead but increase batch latency
   and the consequence of a delayed drain.
3. At 1600 sample/s, first test one active IMU on each bus. A four-IMU run is an
   overload characterization, not an expected viable configuration.
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
