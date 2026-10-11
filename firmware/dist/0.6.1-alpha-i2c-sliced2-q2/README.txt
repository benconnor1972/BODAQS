RC3 bench firmware: 0.6.1-alpha-i2c-sliced2-q2
PlatformIO environment: bodaqs_s3_mini_n4r2_rc3_i2c_sliced
Board profile: BODAQS_V1RC3
Built: 10 October 2026

Flashing:
- bodaqs_v1RC3-i2c-sliced2-q2.bin at 0x10000 (application update).
- bodaqs_v1RC3-i2c-sliced2-q2-full.bin at 0x00000 (combined image).
- Separate offsets: bootloader 0x00000, partitions 0x08000, application 0x10000.
- SHA256SUMS.txt covers all four images.

Configuration before logging:
- EACH tested IMU: fifo_service_mode=sliced, fifo_slice_bytes=0,
  fifo_poll_rate_hz=50. Only equal-rate orientation_400/orientation_800 support
  slicing. Existing saved sliced settings remain valid.
- First comparison: AS5600 200 Hz / IMUs 800/800 Hz.
- Second comparison: AS5600 500 Hz / IMUs 400/400 Hz.
- Match primary rate, card, wiring and other configuration to the comparison.
- Confirm the logging-start serial lines show mode=sliced slice_bytes=0.

Revision 2 changes:
- A delayed first FIFO read is allowed; the 120 ms anchor deadline starts with
  the first retained sample rather than the cycle start.
- Sliced no-progress restart needs repeated fresh empty-FIFO observations over
  250 ms. Service gaps above max(100 ms, three polling periods) break evidence.
  Optional work cannot trigger recovery solely because of scheduling delay.
- Flush resets pending state, publication cursors and empty evidence; seeds
  fresh zero backlog on success, leaves backlog unknown on failure.
- Known pressure and initial-anchor acquisition use the payload ceiling even
  with an overdue AS5600 deadline: auto 128 bytes, explicit ceilings 32..256.
- Pressure bursts yield after four turns or 6 ms to an overdue AS5600, otherwise
  the oldest pending non-auxiliary FIFO. Bounds are checked between turns;
  one transfer or exceptional blocking recovery may exceed the time bound.
- Useful catch-up may miss AS slots; fairness can increase FIFO pressure under
  unsustainable load. Bench measurements must establish achievable cadence.

Retained: opt-in sliced service, transfer priority 2, enlarged queues, 16 KiB
storage buffer and stack/ADC fixes. Startup CHIP_ID probe disabled. Ordinary
whole FIFO service keeps its prior watchdog and scheduling behavior.

New summaries (BDQ v1/v2 and CSV): pressure_yields per scheduler client;
catchup_slices, empty_fifo_observations, empty_progress_recoveries per sliced
client. Existing step/anchor/backlog/publication diagnostics remain available.

Validation: full host suite passes under ordinary and relaxed policies,
including 518 sliced helper/parser checks; 195 production-method runtime
checks pass with fake device/clock and production parser/selector. They cover
peer restart delays, empty-evidence recovery, flush state, fault-prefix and
publication-cursor preservation, and combined FIFO/AS arbitration.
Register setup and record materialisation are mocked in the runtime fixture.
Check IMU tick/sequence continuity, degraded timing, anchor waits, FIFO skips,
recovery and AS5600 interval tails; include repeated start/stop and restart.

Detailed notes: docs/firmware/BMI270_High_Rate_I2C_Testing.md.

RC3 sliced, ordinary RC3 and relaxed RC3 environments compile.
Build resources: static RAM 183468 bytes; program flash 1859105 bytes.
Compiled worker/state-machine/publication/preparation frames: 208/208/192/80
bytes; empty-observation helper 32 bytes. Worker stack remains 4096 bytes;
these sizes do not establish a runtime stack watermark. Startup probe absent
from the compiled ELF; package identities, offsets, erased gaps and hashes
verified.
