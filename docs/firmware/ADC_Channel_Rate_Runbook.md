# r14: focused channel/rate round

This bench-only logger keeps r13 ADC3/storage2/CAN2, commands, clocks, mode0,
500us CAN start spacing, readiness, buffers, CRC and data formats unchanged.
It adds only a finite experimental mixed-admission scope. r13 permits AIN0/4
at500Hz only and would exclude the IMU in the other cases below. Production
admission and earlier bench defaults stay unchanged. This is not a new policy.

Use `variants.channel_rate` from the passed manifest, environment
`bodaqs_s3_mini_n4r2_imu_adc_channel_rate`, firmware
`bodaqs_a8_imu_adc_channel_rate_r14`. Logger application only at0x10000; preserve
settings and the exact r10 master/node. Sealed r13 is the rollback image.

## Cases

All cases retain the same active can:0/imu, profile, two analog sensor names,
calibration/output mode and two primary columns. Change only the row rate and
the input of the existing AIN4 analog sensor. AIN0/1 are two channels on ADC0;
AIN4 is channel0 on ADC1. No physical wiring changes are needed for scheduling.

| Order | Active inputs | Requested row Hz | Expected effective Hz | ADC setup | Duration |
| --- | --- | ---: | ---: | --- | ---: |
| A | AIN0, AIN4 | 500 | 500 | one channel/chip,1000SPS each | 30s |
| B | AIN0, AIN1 | 500 | 500 | two channels on ADC0,2000SPS | 30s |
| C | AIN0, AIN1 | 700 | 700 | same two channels,2000SPS | 30s |
| D | AIN0, AIN1 | 1000 | 700 | existing local cap; same physical load as C | 15s |

The global supported rates are10/20/50/100/200/500/700/1000Hz;250Hz per channel
is not selectable. With two channels on one2000SPS ADC, the current70% budget
caps row rate at700Hz. D checks that guard, not intentional physical overload.
Compare A/B with equal row shape and requested total conversions. A/B also
changes active worker count and configured ADC speed, so it is not a pure
measurement of mux-write time. B/C increases demand without changing ADC speed.

## Configuration preparation

Export the **current working configuration** from the logger before changing it.
Do not use the old Downloads `loggercfg (8).txt`: it predates the working setup.
Save the original for restoration. You can make the two edits through the usual
configuration interface, or generate exact full-file copies offline:

```powershell
python prepare_adc_channel_cases.py --config "PATH_TO_CURRENT_EXPORT.txt" --output-dir "FRESH_LOCAL_PRIVATE_DIRECTORY"
```

The helper finds the active AIN4 sensor rather than assuming an index. It requires
one active IMU and active analog AIN0/4 at500Hz/multistream, then changes only
`sample_rate_hz` and that sensor's `ain`. It preserves every other line, including
buttons, Wi-Fi and calibration, records hashes, and refuses an existing output
directory. Generated configs contain private settings; keep them local. It never
accesses or configures a device. Copy/load the selected full config through the
usual logger workflow and restart so the saved configuration is actually loaded.
Changing the file while running does not establish the active configuration.

## Operator sequence

1. Install the r14 logger only and restart the IMU node. Keep the same card,
   hardware and power arrangement. Run A first using the working configuration.
2. At each start require three streams, two primary columns and no IMU exclusion.
   Check `[AIN]` active-channel/required/configuredSPS output against the table.
   B requires1000SPS aggregate, C/D1400SPS after the cap; ADC0configured2000SPS.
   D must print the local cap from1000 to700. Its nominal integer period1428us
   gives approximately700.28Hz; do not demand mathematically exact700Hz.
3. STOP normally after the table duration. Wait for file closure and finished
   FLOW/cleanup before copying the finalized BDQ. Save full start/STOP serial
   with the case ID. Preserve each file before starting the next recording.
4. Stop progression and send that case immediately if the IMU is excluded,
   DRDY timeouts repeat, the effective rate is unexpected, or cleanup remains
   pending15seconds after STOP. Do not bypass the admission gate or local cap.
5. Assess A before B, B before C, and C before D. Send each finalized BDQ and
   serial; no CCS export or scope capture is required. Restore the original
   working configuration after the round; r13 remains available for rollback.

## Questions and acceptance

A checks behavior on the new image against r13. B measures concentrated load
and repeated channel switching; C measures freshness near the existing local
boundary. D tests requested-versus-effective rate behavior. Retained rows can
reuse earlier conversions; that is not equivalent to independent fresh samples
at the row rate. Assess per-channel reuse/age, acquisition failures/timeouts,
row continuity, actual participation, IMU source-bounded delivery/tail, storage
queues/writes and STOP/restart together. Preserve the known small STOP-tail
warning and unknown loss denominators rather than summing cumulative counters.

Floating inputs allow scheduling/readiness tests only. Numeric equality or zeros
cannot prove channel identity, accuracy or settling. Different known-safe levels
on two inputs are required for that separate check; no wiring instructions are
given without the exact connector/voltage arrangement. Controlled storage-stall
testing stays deferred. Do not extrapolate these four cases into a general
admission policy or claim overload recovery from the clamped D case.

The packet contains the config helper. Fresh full configurations can be generated
once a current export is available; partial overrides are not loadable configs.
