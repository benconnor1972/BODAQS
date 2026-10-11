RC3 bench firmware: 0.6.1-alpha-i2c-simple2-q2
PlatformIO environment: bodaqs_s3_mini_n4r2_rc3_i2c_startup
Board profile: BODAQS_V1RC3
Built: 10 October 2026

Flashing:
- bodaqs_v1RC3-i2c-simple2-q2.bin at 0x10000 (application update).
- bodaqs_v1RC3-i2c-simple2-q2-full.bin at 0x00000 (combined image).
- Separate offsets: bootloader 0x00000, partitions 0x08000, application 0x10000.
- SHA256SUMS.txt covers all four images.

Restored acquisition policy:
- Original whole-FIFO service; no sliced acquisition or catch-up state machine.
- Each pending BMI270 service may defer to a latency-sensitive client at most
  twice, after an initial successful service and within the original maximum
  service-gap guard. Transactions already on the wire remain uninterrupted.
- Model-based extra deferrals and the sliced editor controls are removed.
- Saved fifo_service_mode and fifo_slice_bytes keys are ignored. You can keep
  the existing SD configuration, including old sliced settings. Profile,
  fifo_poll_rate_hz and AS5600 async rate continue to apply normally.
- Serial and recording metadata identify fixed_two_deferral and whole service.

Retained separate improvements:
- Enlarged BDQ v2 primary/AS5600 producer queues and current storage buffering.
- ADC DRDY waits, finalization stack safety and the 16 KiB loopTask stack.
- Transfer-only priority 2 (worker base priority remains 1).
- Startup diagnostics and startup/controller recovery hardening.
- Earlier long IMU-PROBE startup speed sweep remains disabled.

Startup diagnostics run once at the end of setup. Only failed devices advance
through the delayed retry, controller-reset and temporary 100 kHz stages.
Configured clock is restored before normal acquisition. A clean boot runs no
fault-recovery stages. The diagnostic build retains identity_path=arduino_hal;
other configuration and FIFO transfers still use Wire. This wrapper bypass is
an experimental variable: the image is not identical to the old baseline.
Always-on sensor power is not cycled by controller recovery.

Validation: full host suite passes, including 24 production scheduler-selection
checks and 46 injected-fault production startup-recovery checks. RC3 diagnostic,
ordinary RC3, A8 and Prototype F builds pass. Static RAM is 175756 bytes; program flash is 1842545 bytes.
The combined image's component
bytes, offsets and erased gaps are verified. Hardware acceptance is pending.

Summary: docs/firmware/I2C_Scheduling_Experiment_Summary_2026-10-10.md
Historical trials: docs/firmware/BMI270_High_Rate_I2C_Testing.md
