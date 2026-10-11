RC3 firmware: 0.6.1-alpha-i2c-deferral2-q2
PlatformIO environment: bodaqs_s3_mini_n4r2_rc3_i2c_deferral
Board profile: BODAQS_V1RC3
Built: 10 October 2026

Cost-model revision 2:
- Measure FIFO_LENGTH-to-FIFO_DATA setup independently from total acquisition.
- Pre-transfer FIFO growth uses setup only: recent eight successful passes'
  maximum + 500 us, with a 2000 us floor.
- Full service cost retains conservative wire time plus recent non-wire
  overhead (eight-service maximum + 1000 us, 6000 us floor). Use at least the
  setup allowance, without counting setup twice.
- No extra I2C reads; peer forecasts, reserve, gap/backlog/drain bounds and
  finite yield guard remain as in the first FIFO-margin experiment.
- Whole FIFO reads, parsing, timestamps, polling rates and config keys retained.
- Transfer priority 2 retained; no CHIP_ID startup probe.
- Ordinary environments retain the fixed two-yield policy.
- New optional summary fields identify cost model, setup/full overhead estimates,
  lifetime setup maximum, and backlog/duration/read-plan rejection counts.
  The existing drain-rejection field remains their aggregate.

Queues retained:
- Primary BDQ v2: coverage target 5120 ms, capped at 4096 records; capacity
  1024 at 200 Hz and 4096 at 500 Hz.
- AS5600 angle queue: 2048 records.
- BMI270 queues remain rate-dependent: 2048 at 400 Hz, 4096 at 800 Hz.
- Storage write buffer: 16 KiB; earlier ADC wait and loop-stack fixes retained.

Flashing (RC3 board only):
- Application: bodaqs_v1RC3-i2c-deferral2-q2.bin at 0x10000.
- Combined image: bodaqs_v1RC3-i2c-deferral2-q2-full.bin at 0x00000.
- Components: bootloader 0x00000, partitions 0x08000, application 0x10000.
SHA256SUMS.txt covers all four images.

Controlled bench comparison (400 kHz buses, BDQ v2):
1. Primary 500 Hz, AS5600 explicit 200 Hz, equal 800/800 Hz IMUs, FIFO poll 25 Hz.
   Compare with 261010_083038.bdq.
2. Primary 500 Hz, AS5600 500 Hz, equal 400/400 Hz IMUs, FIFO poll 25 Hz.
   Compare with 261010_085930.bdq.
Keep wiring, card and configuration fixed. Include repeated start/stop cycles
and long logs. A 200 Hz primary experiment can follow separately.
The previous deferral-q2 image is preserved in its original directory.

At logging start expect:
[I2CSched] busN scheduler started base_priority=1 transfer_priority=2 fifo_deferral=1 fifo_cost_model=2

Review AS5600 achieved cadence, interval tails/gaps and admission rejections,
alongside IMU FIFO peaks, service gaps, errors, skips, sequence continuity,
queue drops, primary losses and storage stalls. Hardware benefit is unproven;
the model does not guarantee deterministic cadence under preemption or faults.

Optional per-FIFO diagnostics (BDQ v1/v2 final summaries and CSV sidecars):
- fifo_cost_model_revision: 2
- fifo_setup_estimate_us, fifo_overhead_estimate_us: current guarded estimates.
- fifo_setup_observed_maximum_us: lifetime observed setup maximum in the session.
- fifo_deferral_rejected_backlog/duration/read_plan: first blocking sub-reason.
- fifo_deferral_rejected_drain: aggregate of the three sub-reasons.
Other existing policy and rejection fields retain their meanings. Rejections
are blocked candidate admissions, not acquisition errors or lost samples.

Detailed policy and comparison instructions:
../../../docs/firmware/BMI270_High_Rate_I2C_Testing.md

Validation:
- Full host suite passed, including 42 FIFO-policy checks.
- Experimental and ordinary RC3 PlatformIO builds passed.
- Experimental static RAM: 176516 bytes; program flash: 1845753 bytes.
- Scheduler worker compiled frame: 272 bytes; task stack remains 4096 bytes.
  This does not establish the runtime stack watermark.
- Binary identity, probe absence, combined offsets and SHA-256 hashes verified.
- Pinned libraries match the first deferral experiment: BusIO 1.17.4,
  GFX 1.12.6, SSD1306 2.5.17, ArduinoJson 7.4.3, GNSS 3.1.15,
  Bosch SensorAPI 41129fcfe39c583ee5462d79195741945d51c1fe.
