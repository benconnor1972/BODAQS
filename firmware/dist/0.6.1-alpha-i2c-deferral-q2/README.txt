RC3 firmware: 0.6.1-alpha-i2c-deferral-q2
PlatformIO environment: bodaqs_s3_mini_n4r2_rc3_i2c_deferral
Board profile: BODAQS_V1RC3
Built: 10 October 2026

Experiment:
- Replaces fixed two-yield admission with cached FIFO backlog and service-margin
  checks for every active BMI270 on the same bus; no extra I2C reads.
- Includes estimated full-drain costs and recent measured timing tails.
- Bounds intentional backlog to one guarded poll period (and the 60% capacity
  reserve), and predicted drain duration to the old one-poll estimate + 2 ms.
- Secondary yield guard derives from FIFO and AS5600 periods, limited to 2..16.
  At 25 Hz polling: guard 8 for AS5600 200 Hz, 16 for AS5600 500 Hz.
- Unknown peer state, errors and recovery inhibit yields until a clean service.
- Forecast includes AS5600 work between FIFO services and checks completion
  within the existing service-age budget. Whole FIFO reads are retained.
- These are admission estimates; actual drains are not truncated when overdue
  or unexpectedly slow. This does not guarantee deterministic sensor cadence.
- Enable flag BODAQS_I2C_FIFO_DEFERRAL=1; ordinary builds keep the two-yield rule.
- Retains transfer priority 2 and q2 queue sizes; no CHIP_ID startup probe.
- No new configuration keys, polling-rate changes or timestamp changes.
- Runtime diagnostics add optional JSON fields to BDQ v1/v2 and CSV sidecars.

Queue sizes retained:
- Primary BDQ v2 coverage target: 5120 ms, capped at 4096 records.
  Capacity is 1024 at 200 Hz and 4096 at 500 Hz.
- AS5600 angle BDQ v2 queue: 2048 records; IMU queues: 4096 records.
- Storage write buffer: 16 KiB. Earlier ADC wait and loop stack fixes retained.

Flashing (RC3 board only):
- Application: bodaqs_v1RC3-i2c-deferral-q2.bin at 0x10000.
- Combined image: bodaqs_v1RC3-i2c-deferral-q2-full.bin at 0x00000.
- Separate components: bootloader 0x00000, partitions 0x08000, app 0x10000.
No logger was flashed automatically. SHA256SUMS.txt covers all four images.

Validation:
- Experimental and ordinary RC3 PlatformIO builds passed.
- Host suite passed, including all 29 new FIFO-policy checks: peer protection,
  more than two yields, finite guards, duration/capacity limits, unknown/error
  states, partial-frame consumption, timing tails, and 64-bit stale ages.
- Experimental build: 175748 bytes static RAM; 1843449 bytes program flash.
- Scheduler worker compiled stack frame: 256 bytes (task stack remains 4096).
  This is a frame check, not a measured runtime stack watermark.
- FIFO policy scratch is present only in the experimental ELF. Probe symbols
  and startup probe strings are absent. Combined offsets and hashes verified.
- Library versions match the preceding priority experiment: BusIO 1.17.4,
  GFX 1.12.6, SSD1306 2.5.17, ArduinoJson 7.4.3, GNSS 3.1.15;
  Bosch SensorAPI 41129fcfe39c583ee5462d79195741945d51c1fe.

Bench comparison (400 kHz buses):
1. Start with AS5600/main stream 200 Hz, equal 800/800 Hz IMUs, FIFO polling 25 Hz.
2. Then AS5600/main stream 500 Hz, equal 400/400 Hz IMUs, FIFO polling 25 Hz.
Use the same wiring, card and settings as the comparison runs. An AS5600 async
rate of zero follows the primary rate. Repeat start/stop cycles and a long run.
Keep the preceding priority-q2 build as the comparison/reversion image.

At logging start expect:
[I2CSched] busN scheduler started base_priority=1 transfer_priority=2 fifo_deferral=1

Compare AS5600 achieved rate and interval tails with IMU FIFO high water,
service gaps, skipped/full events, sequence continuity, errors, queue drops,
primary losses and storage stalls. Improvement is not presumed.

New per-FIFO scheduler summary fields:
- fifo_deferral: 1
- fifo_production_bound_bytes_per_second, fifo_backlog_limit_bytes,
  fifo_drain_limit_us: configuration-derived bounds.
- maximum_yields_per_service: largest actual count; priority_yield_limit is 16,
  the absolute ceiling rather than the smaller period-derived guard.
- fifo_predicted_backlog_maximum_bytes, fifo_predicted_acquire_maximum_us:
  largest predictions across all peers in decisions admitted for that client.
- fifo_deferral_rejected_unknown/capacity/gap/drain/count: first blocking reason
  for candidate admissions. These are not acquisition errors or lost samples.
  Decisions without an AS5600 deadline inside the predicted block are excluded.

Detailed policy and comparison instructions:
../../../docs/firmware/BMI270_High_Rate_I2C_Testing.md
