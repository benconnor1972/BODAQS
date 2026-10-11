RC3 bench firmware: 0.6.1-alpha-i2c-sliced-q2
PlatformIO environment: bodaqs_s3_mini_n4r2_rc3_i2c_sliced
Board profile: BODAQS_V1RC3
Built: 10 October 2026

Enable the experiment before logging:
- On EACH IMU being tested, select FIFO service mode = sliced in the web
  configuration's Acquisition group. Leave FIFO slice bytes = 0 initially.
- Only orientation_400 (400/400) and orientation_800 (800/800) support slicing.
- Existing configurations default to whole; flashing alone does not enable it.
- Keep FIFO polling at 50 Hz for the first comparison with the recent runs.
- Settings can change between sessions and are locked during logging.
- Example saved configuration for an IMU at index 6 (use the actual index):
    sensor6.profile=orientation_800
    sensor6.fifo_poll_rate_hz=50
    sensor6.fifo_service_mode=sliced
    sensor6.fifo_slice_bytes=0
- A nonzero fifo_slice_bytes must be 32..256. It sets a maximum payload; the
  deadline estimate can still select a smaller read. Automatic maximum is 128.

Behavior:
- One worker per bus; logical FIFO drains resume immediately between polling
  deadlines. Due AS5600 acquisition can run between complete FIFO transactions.
- FIFO pressure overrides due unbuffered reads when necessary. Continuations
  are fair; optional temperature, clock and IOC work has lower priority.
- Read-only FIFO bursts are bounded; no interruption inside an I2C transaction.
- Discard partial tails: Bosch repeats partial stored frames on the next read.
- Retain complete frames until a sensor-time anchor; publish up to 16 records
  per turn. Anchor interpolation uses only the actual tail transfer interval.
- Bounded workspace and 120 ms anchor wait; fallback data is timing-degraded.
- Transport/alignment uncertainty preserves confirmed data, marks the boundary
  and recovers the uncertain remainder. Stop finishes retained prefixes without
  re-publishing records already queued.
- Whole OLED writes are excluded from a bus running sliced clients during logs.
- Temperature can initially be stale; temperature/clock/IOC reads can be late.
- Whole mode retains prior behavior; no revision 2/3 extra-deferral policy in
  this environment. Slicing is cooperative and does not guarantee deadlines.

Retained: transfer priority 2, enlarged primary/AS5600/IMU queues, 16 KiB
storage write buffer, ADC wait and loop-stack fixes. Startup CHIP_ID probe off.

Flashing (RC3 only):
- bodaqs_v1RC3-i2c-sliced-q2.bin at 0x10000 (application update).
- bodaqs_v1RC3-i2c-sliced-q2-full.bin at 0x00000 (combined image).
- Components: bootloader 0x00000, partitions 0x08000, application 0x10000.
- SHA256SUMS.txt covers all four images.

At logging start expect one line per available IMU:
[BMI270] FIFO service sensor=... mode=sliced slice_bytes=0

Bench checks:
- AS5600 200 Hz / equal-rate 800 Hz IMUs, then AS5600 500 Hz / 400 Hz IMUs.
- Match primary rate, wiring, card and BDQ v2 settings to the comparison run.
- Review AS5600 interval tails AND average cadence; IMU sequence/tick continuity,
  degraded timing, anchor waits, FIFO pressure/full/skip events, recovery,
  queue drops and storage performance. Include repeated start/stop cycles.
- Runtime summaries identify stepped_acquisition and include actual step costs,
  logical cycle costs, continuation waits, slices/length refreshes, progress,
  payload maxima, anchor timeouts and FIFO state invalidations.
- cycle_pending_at_scheduler_stop can be true when stop subsequently finishes
  the retained group. Scheduler totals exclude work after its worker stops.

Validation: full host suite passes with ordinary and relaxed policies selected;
497 new checks cover slicing/replay, anchors, backlog, arbitration and bounded
publication/abort classification. RC3 sliced, ordinary RC3 and prior relaxed
environments compile. Hardware cadence, runtime stack watermark, transport
fault handling and repeated physical start/stop behavior require bench testing.

Detailed notes: docs/firmware/BMI270_High_Rate_I2C_Testing.md in the repository.

Build resources: 182916 bytes static RAM; 1856717 bytes program flash.
Compiled worker frame: 192 bytes within its 4096-byte stack. Individual
state-machine/publication/anchor-preparation frames: 208/192/80 bytes.
These frame sizes do not establish the runtime stack watermark.
