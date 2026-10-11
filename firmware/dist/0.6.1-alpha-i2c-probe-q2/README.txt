RC3 firmware: 0.6.1-alpha-i2c-probe-q2
Built: 9 October 2026
PlatformIO environment: bodaqs_s3_mini_n4r2_rc3_i2c_probe_q2
Board profile: BODAQS_V1RC3

Changes relative to the previous I2C probe build:
- BDQ v2 primary queue coverage target: 2560 -> 5120 milliseconds.
  At 200 Hz: 512 -> 1024 records (5.12 seconds).
  At 500 Hz: 2048 -> 4096 records (8.192 seconds).
  Existing minimum of 64 and maximum of 4096 records are retained.
- AS5600 BDQ v2 native queue: 1024 -> 2048 records (40 KiB record storage,
  an additional 20 KiB per AS5600 angle sensor).
  Nominal coverage: 10.24 seconds at 200 Hz; 4.096 seconds at 500 Hz.
- Retains the normal startup and the existing 400/100/400 kHz CHIP_ID probe.
- Uses the current workspace, including the earlier ADC wait and stack fixes.
- Log format, sensor acquisition rates, IMU queues and 16 KiB write buffer
  are unchanged. The queue changes also apply to other builds of these sources.

Flashing (RC3 board only):
- Application update: bodaqs_v1RC3-i2c-probe-q2.bin at 0x10000.
- Combined image: bodaqs_v1RC3-i2c-probe-q2-full.bin at 0x00000.
- Separate bootloader: 0x00000; partitions: 0x08000; application: 0x10000.
No device was flashed automatically.

Validation:
- PlatformIO RC3 build passed.
- Existing host suite was rebuilt and passed, including FIFO and BDQ v2
  queue/writer checks. These do not simulate physical SD-card stalls.
- Dependencies match the previous probe build.
- Combined-image component offsets and SHA-256 hashes verified.

Next bench run:
Use the same configuration for comparison. Check the final BDQ v2 summary for
primary_queue_capacity, each stream's producer_queue_capacity/high_water/drop
count, and storage maximum write time and stall count. Expected primary
capacities are 1024 at 200 Hz and 4096 at 500 Hz; AS5600 capacity is 2048.
Larger queues provide margin for stalls; they do not shorten SD write latency.
