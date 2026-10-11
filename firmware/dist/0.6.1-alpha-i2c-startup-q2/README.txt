RC3 bench firmware: 0.6.1-alpha-i2c-startup-q2
PlatformIO environment: bodaqs_s3_mini_n4r2_rc3_i2c_startup
Board profile: BODAQS_V1RC3
Built: 10 October 2026

Flashing:
- bodaqs_v1RC3-i2c-startup-q2.bin at 0x10000 (application update).
- bodaqs_v1RC3-i2c-startup-q2-full.bin at 0x00000 (combined image).
- Separate offsets: bootloader 0x00000, partitions 0x08000, application 0x10000.
- SHA256SUMS.txt covers all four images.

Use the existing sensor and logging configuration. Sliced FIFO revision 3,
transfer priority 2, enlarged queues and storage buffer, and stack/ADC fixes
are retained. The earlier long IMU-PROBE startup sweep remains disabled.
No new configuration fields or recording format changes are introduced.

Shared recovery changes:
- Check controller begin, clock setup and mutex allocation; fail closed.
- AS5600 initial address probe: three attempts, 10 ms gaps, optionally one
  controller recovery followed by another three attempts.
- A wrong received BMI270 chip ID can request one controller recovery, as
  transport failures already could. Required ID remains exactly 0x24.
- Add one coordinated 250 ms delayed retry after normal startup for failed
  BMI270/AS5600 sensors. Healthy peers are not reinitialized.
- Recovery logs distinguish controller_ready from valid device response;
  device_response=unchecked and *_low boolean fields explain the distinction.

This diagnostic image separates explicit application-level stages:
1. Delayed retry with no explicit controller reset.
2. One forced controller reinitialization per affected bus, then retries.
3. Temporary 100 kHz clock per still-affected bus, then retries.
Each stage performs three register probes per failed sensor. At least one
valid read is required before full reinitialization. A missing AS5600 magnet
does not make a complete register transfer invalid.
Only failures progress to later stages. Configured clock is restored before
normal acquisition; restoration failure leaves that bus unavailable.
The experiment runs once at the end of setup, before acquisition workers.
Failed boots may take longer; no periodic startup experiment runs in logging.

Capture serial output from BEFORE the reset through [I2C-STARTUP] DONE.
Individual imu_attempt and as5600_probe lines precede the START marker.
Initial snapshots include local recovery already performed during normal
initialization. Save matched cold-boot and warm-restart logs, with recordings.
Review raw chip bytes, probe_received, probe_esp_known/probe_esp, staged
register_probe ESP errors and received lengths, retries and final readiness.
If 100 kHz was used, expect clock_restore normal_hz=400000 ok=1 for the
current board profile. A restoration failure appears explicitly in the log.

Diagnostic limitation: identity_path=arduino_hal means BMI270 identity reads
and staged probes use the same i2cWriteReadNonStop HAL called by Wire, directly
under the manager mutex to retain the original ESP error. Other configuration
and FIFO transfers still use Wire. This wrapper bypass is a diagnostic
variable; recovery success alone does not prove the physical root cause.
The IDF driver can also recover internally, independently of explicit stages.
No sensor power cycling, CSB changes or clocks forced onto a released bus.
Controller reset affects healthy peers' shared bus, despite preserving their
initialization. The always-on sensor supply remains powered throughout.

Validation: full host suite passes, including 27 startup coordinator/probe
checks, 46 injected-fault production recovery checks and 419 existing sliced
production-runtime checks. Diagnostic RC3, ordinary RC3, A8 and Prototype F
builds pass. Static RAM 183732 bytes; program flash 1865597 bytes.
Hardware/driver behavior is mocked in host checks; intermittent fault recovery
and subsequent acquisition still require bench acceptance.

Detailed notes: docs/firmware/BMI270_High_Rate_I2C_Testing.md,
section "Startup recovery and diagnostics trial".
