RC3 bench firmware: 0.6.1-alpha-i2c-sliced3-q2
PlatformIO environment: bodaqs_s3_mini_n4r2_rc3_i2c_sliced
Board profile: BODAQS_V1RC3
Built: 10 October 2026

Flashing:
- bodaqs_v1RC3-i2c-sliced3-q2.bin at 0x10000 (application update).
- bodaqs_v1RC3-i2c-sliced3-q2-full.bin at 0x00000 (combined image).
- Separate offsets: bootloader 0x00000, partitions 0x08000, application 0x10000.
- SHA256SUMS.txt covers all four images.

Configuration:
- EACH tested IMU: fifo_service_mode=sliced, fifo_slice_bytes=0,
  fifo_poll_rate_hz=50. Slicing supports orientation_400/orientation_800.
- First comparison: primary/AS5600 200 Hz / IMUs 800/800 Hz.
- Second comparison: primary/AS5600 500 Hz / IMUs 400/400 Hz.
- Match card, wiring and other configuration to the previous comparison.
- Confirm logging-start serial lines show mode=sliced slice_bytes=0.
- No new configuration fields; existing saved settings remain valid.

Revision 3 changes:
- A complete valid skip report records loss/discontinuity and degraded timing
  while preserving retained frames and continuing acquisition. It no longer
  triggers a flush/restart solely because it reports loss. Saturated counts
  (255) are retained as reported, with timing marked degraded.
- Refresh actual FIFO length after a skip unless that read reached the tail.
- Begin catch-up at 20 ms of known backlog (104 bytes at 400/400 Hz, 208 bytes
  at 800/800 Hz), or after a retained sample waits 20 ms for an anchor.
- Keep catch-up latched until the FIFO tail/empty observation or fault/session
  reset. A degraded publication at the existing 120 ms limit keeps the latch.
- Auto ceiling remains 128 bytes; explicit 32..256 byte ceilings remain caps.
- Earlier catch-up increases payload, not scheduler priority. Existing critical
  pressure and four-turn/6 ms yielding remain. Larger reads can delay AS5600;
  cadence and timing quality still require bench acceptance.
- Malformed headers, output loss and failed transport retain fault recovery.

New BDQ v1/v2 and CSV summary counters: catchup_entries (latch admissions) and
fifo_skip_reports_handled (valid complete skip reports without invalidation).
Review native sequences/ticks, timing degradation, sensor-time anchors,
anchor timeouts, skips/full reports, recoveries and AS5600 interval tails.
Include repeated start/stop and warm restart checks.

Retained: opt-in sliced service, transfer priority 2, enlarged queues, 16 KiB
storage buffer and stack/ADC fixes. Startup probe disabled. Ordinary whole
FIFO policy retains its prior behavior.

Validation: ordinary and relaxed host suites pass (528 sliced helper/parser
checks each); 419 production-method runtime checks pass with the real parser
and scheduler selector. Normal continuous-producer simulations reach repeated
anchors without timeouts/restarts for both profiles. Induced 800 Hz overflow
reports loss and initial anchor timeouts but keeps reaching fresh anchors
without restarting either peer. Register transactions, electrical behavior
and record materialisation remain mocked; simulations do not prove cadence.

Build resources: static RAM 183724 bytes; program flash 1860233 bytes.
Compiled state-machine/publication/preparation frames: 208/192/80 bytes;
empty-observation helper 32 bytes. Worker stack remains 4096 bytes; these
individual sizes are not a runtime watermark. Startup probe absent from ELF;
package identities, component offsets, erased gaps and hashes verified.
Sliced RC3, ordinary RC3 and relaxed RC3 environments compile.
Detailed notes: docs/firmware/BMI270_High_Rate_I2C_Testing.md.
