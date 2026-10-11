RC3 bench firmware: 0.6.1-alpha-sensor-inputs-q2
PlatformIO environment: bodaqs_s3_mini_n4r2_rc3_sensor_inputs
Board profile: BODAQS_V1RC3
Built: 11 October 2026

Flashing:
- bodaqs_v1RC3-sensor-inputs-q2.bin at 0x10000 (application update).
- bodaqs_v1RC3-sensor-inputs-q2-full.bin at 0x00000 (combined image).
- Separate offsets: bootloader 0x00000, partitions 0x08000, application 0x10000.
- SHA256SUMS.txt covers all four images.

New behavior:
- Sensors page Input column after Type: I2C1 [0x68], AIN4, UART0.
  Shows configured inputs for active, muted and unavailable sensors.
  I2C addresses are hexadecimal. Omitted settings use sensor defaults.

Retained log-start behavior:
- Persistent Restart required / Press Enter home prompt for saved/live sensor
  differences. A fresh complete Enter press/release performs a warm restart.
- Config conflict / Please review takes priority. Checks cover active I2C,
  GPIO/ADC/UART assignments, duplicate names/IMU IDs and board I2C reservations.
  Muted sensors do not reserve inputs. Menu mute overrides remain effective.
- Invalid configuration/input settings show Sensor config / Please review.
- General, Sensors and sensor editor pages show details and update/clear their
  notice after saves. Serial records status changes and refused starts.
- Multiple active IMUs or mixed-rate profiles automatically select and save
  BDQ v2 at log start before sensor preparation or file creation. Failed saves
  refuse the start; compatible CSV/BDQ v1 selections stay selected.
- Successful live edits and reverted edits clear restart warnings.
- Existing power, upload, SD and sensor/session checks remain. BMI270
  initialization failures can still allow other sensors to record.

Retained:
- Original whole-FIFO two-deferral scheduler, transfer priority 2, enlarged
  primary/AS5600 queues, storage buffering, ADC/stack fixes.
- Optional startup SD reports (default off); latest 32 reports under /startup.
- Startup diagnostics/recovery, including controller reset and temporary
  100 kHz stages for failed devices, with the configured clock restored.
- Experimental arduino_hal identity path inherited from the previous bench
  image. Ordinary builds use Wire. Recovery does not cycle sensor power.
- No long IMU-PROBE sweep; retired FIFO slice settings remain ignored.

Validation:
- Full host suite passes, including 116 production log-start runtime checks,
  24 scheduler checks, 46 startup recovery checks and 70 startup-report checks.
- This RC3 bench image builds successfully.
- Combined-image component bytes, offsets and erased gaps verified.
- Physical browser acceptance pending. Detailed behavior and bench checklist:
  docs/firmware/BMI270_High_Rate_I2C_Testing.md, configuration warnings section.
