RC3 bench firmware: 0.6.1-alpha-i2c-deferral3-q2
PlatformIO environment: bodaqs_s3_mini_n4r2_rc3_i2c_relaxed
Board profile: BODAQS_V1RC3
Built: 10 October 2026

Relaxed policies (cost-model revision 3):
- Remove the one-poll backlog and acquisition-duration ceilings.
- Admission backlog and setup-growth limit: 85% FIFO, 1740 bytes.
- Production estimate: configured byte rate + 5%, formerly + 10%.
- Projected FIFO start age: at most 120 ms (200 ms for the supported 10 Hz
  mixed profile). These are start-age admission limits, not completion limits.
- Allow up to 64 latency deferrals per pending FIFO service, independent of
  polling rate. Peer forecasting and unknown-state inhibition retained.
- Full non-wire overhead: recent eight-service mean + 250 us; floor 1500 us.
- FIFO length-to-data setup: recent eight-pass mean + 100 us; floor 800 us.
- AS5600 cost: configured estimate while cold, then recent eight-service mean
  + 100 us; floor 250 us. It can fall below the former configured 2000 us floor.
- Decision guard reduced from 1000 us to 100 us.
- Omit the old capacity check which counted all arrivals during a drain without
  subtracting consumed bytes. Setup growth and bounded read plans still checked.
- Whole FIFO transfers, wire/read planner, parsing, follow-up handling,
  timestamp reconstruction, queues and recovery retained. No extra I2C reads.
- Explicit bench experiment: means tolerate outliers, so larger actual gaps,
  FIFO skips/full events, deeper queues and longer AS5600 gaps are possible.
  Hardware cadence improvement is not established by host checks.
- The larger service-gap budget also relaxes low-priority bus admission;
  existing display throttling remains in effect.

No new configuration keys. Use existing fifo_poll_rate_hz to choose polling.
Transfer priority 2 retained; no CHIP_ID startup probe.
Existing deferral environment still builds revision 2; ordinary builds retain
fixed two-deferral behavior. Earlier packaged comparison images are preserved.

Queues retained:
- Primary BDQ v2 coverage target: 5120 ms, capped at 4096 records.
  Capacity 1024 at 200 Hz; 4096 at 500 Hz.
- AS5600 angle queue: 2048 records.
- BMI270 rate-dependent queues: 2048 at 400 Hz; 4096 at 800 Hz.
- Storage write buffer: 16 KiB. Earlier ADC wait and loop-stack fixes retained.

Flashing (RC3 only):
- bodaqs_v1RC3-i2c-deferral3-q2.bin at 0x10000 (application update).
- bodaqs_v1RC3-i2c-deferral3-q2-full.bin at 0x00000 (combined image).
- Components: bootloader 0x00000, partitions 0x08000, application 0x10000.
SHA256SUMS.txt covers all four images.

Bench sequence:
- First repeat the ongoing 50 Hz FIFO case with identical primary/AS5600 rates,
  IMU profiles, wiring, card and BDQ v2 settings. Then compare 25 Hz if useful.
- Intended targets: AS5600 500 Hz / IMUs 400/400 Hz; AS5600 200 Hz / IMUs 800/800.
- Primary/AS5600 500 Hz with IMUs 800/800 Hz is a stress comparison; the prior
  two-deferral run 261010_063703.bdq achieved AS5600 177.15 Hz, revision 2's
  matched 261010_102422.bdq achieved 126.31 Hz. Both used FIFO polling 25 Hz.
- Review achieved cadence and interval tails/gaps, IMU native continuity and
  timing-degraded fractions, FIFO peaks, skips/full events, service intervals,
  transport failures/recovery, all queue drops and primary/storage losses.
- Include repeated start/stop cycles and long logs.

At logging start expect:
[I2CSched] busN scheduler started base_priority=1 transfer_priority=2 fifo_deferral=1 fifo_cost_model=3

Optional scheduler-client fields in BDQ v1/v2 final summaries and CSV sidecars:
- fifo_cost_model_revision=3; fifo_relaxed_policy=true/1.
- fifo_capacity_limit_bytes=1740; fifo_decision_guard_us=100.
- fifo_service_gap_checks_completion=false/0.
- maximum_service_gap_us=120000 normally (200000 for mixed-profile 10 Hz).
- priority_yield_limit=64; fifo_backlog_limit_bytes=1740; fifo_drain_limit_us=0.
- fifo_deferral_rejected_peer: subset of rejected candidates whose first
  blocking condition belonged to another FIFO. Do not add it to reason totals.
Existing estimates, observed maxima and reason counters remain available.
Rejections are admission decisions, not lost samples.

Host validation:
- Full host suite passes with both conservative and relaxed selections.
- Existing 42 conservative policy checks pass; 32 relaxed policy checks pass.
- An aged two-IMU fixture admits 22 consecutive yields then forces service.
  This demonstrates changed admission behavior, not hardware performance.

Build and package validation:
- Relaxed revision 3, conservative revision 2 and ordinary RC3 builds pass.
- Relaxed ELF: static RAM 176772 bytes; program flash 1846757 bytes.
- Scheduler worker compiled frame: 256 bytes; task stack remains 4096 bytes.
  FIFO peer scratch is static per bus and absent from the ordinary ELF.
- Image identity, startup-probe absence, combined offsets, erased gaps and
  all SHA-256 hashes verified. Application file size: 1847168 bytes.
- Hardware cadence and runtime stack headroom still require bench testing.

Detailed policy and test instructions:
../../../docs/firmware/BMI270_High_Rate_I2C_Testing.md
