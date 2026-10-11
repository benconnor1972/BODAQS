RC3 bench firmware: 0.6.1-alpha-i2c-bootlog-q2
PlatformIO environment: bodaqs_s3_mini_n4r2_rc3_startup_log
Board profile: BODAQS_V1RC3
Built: 11 October 2026

Flashing:
- bodaqs_v1RC3-i2c-bootlog-q2.bin at 0x10000 (application update).
- bodaqs_v1RC3-i2c-bootlog-q2-full.bin at 0x00000 (combined image).
- Separate offsets: bootloader 0x00000, partitions 0x08000, application 0x10000.
- SHA256SUMS.txt covers all four images.

Enable startup reports:
- General page: check Save startup diagnostics to SD, Save, then Restart.
- Default is off; configuration key: startup_log_to_sd=true or false.
- One report per completed startup, including successful boots.
- Latest 32 successfully saved reports rotate in /startup/boot-00.txt through
  boot-31.txt. Sort by sequence header; filenames wrap around.
- Captures original BMI270 attempts, AS5600 probes, controller recovery,
  staged startup probes/retries and final readiness. Includes firmware,
  board, reset reason and relevant configuration context.
- Capture uses a 32 KiB RAM allocation only during enabled startup. It retains
  complete messages and marks overflow with dropped-message/byte counts.
  A reserved footer preserves final readiness even after overflow.
- SD work is deferred until startup recovery finishes; capture memory is freed
  afterward even if saving fails. SD/RAM failures are reported on serial.
- A boot interrupted before the deferred save produces no complete report;
  this is not a crash recorder. Interrupted saves may leave .tmp/.bak files.
- Disabling leaves existing reports intact. No periodic recording during logs.

Acquisition policy remains the restored original whole-FIFO, two-deferral policy.
Old fifo_service_mode and fifo_slice_bytes keys remain ignored. Enlarged primary
and AS5600 queues, storage buffering, ADC/stack fixes and transfer priority 2
remain in this image. No old long IMU-PROBE startup sweep.

Existing startup diagnostics remain enabled in this RC3 image: only failed
devices advance through delayed retry, controller-reset and temporary 100 kHz
stages. The configured clock is restored before normal acquisition. The image
retains identity_path=arduino_hal, an experimental variable; ordinary builds
use Wire. Controller recovery does not cycle the always-on sensor supply.
Enabling SD reports does not itself change the recovery policy.

Validation: full host suite passes, including 70 new production startup-report
checks, 24 production scheduler checks and 46 startup recovery checks.
RC3 diagnostic, ordinary RC3, A8 and Prototype F builds pass. Combined component
bytes, offsets and erased gaps are verified. Hardware acceptance is pending.

Usage and limits: docs/firmware/BMI270_High_Rate_I2C_Testing.md
Scheduler summary: docs/firmware/I2C_Scheduling_Experiment_Summary_2026-10-10.md
