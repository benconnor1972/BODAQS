RC3 firmware: 0.6.1-alpha-i2c-priority-q2
PlatformIO environment: bodaqs_s3_mini_n4r2_rc3_i2c_priority
Board profile: BODAQS_V1RC3

Experiment:
- BMI270 and both AS5600 I2C drivers temporarily raise the bus worker's
  FreeRTOS priority from 1 to 2 during transfers and completion handling.
- Scope exit restores the previous priority on success and error paths.
  Nested scopes preserve the outer boost; higher priorities are not lowered.
- Only I2C scheduler workers are eligible. Startup, loopTask, display work,
  FIFO parsing/enqueueing, retry delays and scheduler waits are not boosted.
- The boost is opt-in through BODAQS_I2C_TRANSFER_PRIORITY=2. Ordinary
  production environments compile it out.
- The startup CHIP_ID probe is absent from this image. Its earlier build
  environments and guarded source remain available for historical comparison.
- The existing scheduling policy, polling rates, bus clock, timestamp
  semantics and log formats are retained. No FIFO drain splitting is added.

Queue sizes retained from the previous q2 build:
- Primary BDQ v2 coverage target: 5120 ms, capped at 4096 records.
  Capacity is 1024 at 200 Hz and 4096 at 500 Hz.
- AS5600 angle BDQ v2 queue: 2048 records.
- IMU queues and the 16 KiB storage write buffer are retained.
- Includes the current workspace's earlier ADC wait and stack fixes.

Flashing (RC3 board only):
- Application update: bodaqs_v1RC3-i2c-priority-q2.bin at 0x10000.
- Combined image: bodaqs_v1RC3-i2c-priority-q2-full.bin at 0x00000.
- Separate bootloader: 0x00000; partitions: 0x08000; application: 0x10000.
No logger was flashed automatically.

Validation:
- Experimental RC3 and ordinary RC3 PlatformIO builds passed.
- Rebuilt host suite passed, including 11 priority-scope checks covering
  restoration, errors, nesting, higher priority, non-workers and disabled boost.
- Library versions and Bosch driver sources match the previous q2 build.
- Compiled BMI270 transfer code references priority get/set only in the
  experimental target. Startup probe symbol and strings are absent.
- Combined-image component offsets and SHA-256 hashes verified.
- Experimental build: 172164 bytes static RAM; 1836545 bytes program flash.
  Host checks do not establish hardware wake-up latency or storage fairness.

Bench comparison:
Keep the wiring, SD card and sensor configuration the same as the comparison
run. Start with 500 Hz primary/AS5600, two IMUs per bus, orientation_800 and
25 Hz FIFO service, matching 261009_202038. Repeat with accel_800_gyro_200
if useful. Do not change FIFO service rate during this first experiment.

At log start, serial should report:
[I2CSched] busN scheduler started base_priority=1 transfer_priority=2

In the BDQ v2 final summary, compare:
- sensor_runtime: AS5600 raw_read_duration_us (previous average ~673 us).
- i2c_scheduler.clients: achieved_service_rate_hz, acquire_average_us,
  maximum_successful_service_interval_us and missed_service_slots.
- AS5600 native sample interval percentiles and maximum gap.
- IMU FIFO length/data transfer times, timing-degraded records and overflows.
- Primary and native producer queue high-water/drop counts, missed primary
  sample slots, and storage write/flush stalls.

The 800/800 comparison run achieved ~157 AS5600 reads/s from a 500 Hz target.
A useful result improves latency/rate without introducing storage or IMU loss.
Hardware results remain to be measured; improved cadence is not guaranteed.
