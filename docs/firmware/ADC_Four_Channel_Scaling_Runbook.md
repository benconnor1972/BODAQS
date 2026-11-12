# r15: four analog channels with one real IMU

This logger-only bench candidate adds exactly AIN0/1/4/5 at200Hz or500Hz to the
retained r14 cases. It preserves production defaults, r14 commands, ADC3/storage2/
CAN2 priorities, phase diagnostics, SPI mode0/clocks,500us CAN start spacing,
readiness, retries, buffers and BDQ formats. No timing or capacity qualification
is claimed. `single_node_adc_scaling_unqualified` is the new diagnostic mode.

Select `variants.scaling`, environment `bodaqs_s3_mini_n4r2_imu_adc_scaling`,
firmware `bodaqs_a8_imu_adc_scaling_r15`. Upload only the selected application
at0x10000 after backup/identity/partition checks. Preserve NVS/settings and the
exact r10 master/node. r14 is the rollback logger. No peer flash is required.

## Existing prepared configurations

Full private configs/restoration copies and exact hashes live at:

`C:/Users/benco/dev/BODAQS-worktrees/drain-capacity-evidence/first-real-imu-implementation/adc-four-channel-scaling-preparation/private-configurations`

Use `four_channels_200Hz.txt` first, then `four_channels_500Hz.txt` after assessment.
Each has one active can:0/imu at the existing3333Hz profile plus AIN0/1/4/5,
two channels per ADC. Preserve existing LINEAR calibration/no extra RAW columns.
These are full configs containing private network settings; keep them local.
No physical sensors are connected; zero-travel LINEAR output tests scheduling,
not voltage accuracy, RAW values, channel identity or mux settling.

| Case | Row rate | Required SPS/ADC | Target SPS/ADC | Configured SPS/ADC | Period |
| --- | ---: | ---: | ---: | ---: | ---: |
| four_channels_200Hz |200|400|572|600|5000us|
| four_channels_500Hz |500|1000|1429|2000|2000us|

## Operator sequence

1. Install r15 logger only. Load/save the200Hz config through the usual workflow,
   and restart so saved settings are active. Restart all three boards before the
   first recording, following the known working startup sequence. This does not
   establish that the underlying occasional clock-trust failure is repaired.
2. Require both ADCs active_channels2 with the rates above, three streams,
   four primary columns and28-byte primary records. No IMU scope exclusion or
   clock_untrusted rejection. Stream count alone does not prove sample delivery;
   final offline assessment must find actual IMU samples.
3. Record about30s; STOP normally and wait for clean file closure plus finished
   FLOW/remote cleanup. Preserve finalized BDQ, complete start/STOP serial and a
   fresh exported config in a new mixed200Hz result folder.
4. Stop progression for startup exclusion, repeated DRDY timeouts, unexpected
   effective rate or cleanup pending15s. Preserve that capture rather than
   bypassing trust checks or repeatedly retrying. Submit200Hz before500Hz.
5. Repeat at500Hz only after the200Hz assessment. Restore original working
   settings afterward with `restore-original-working-private.txt`; restoring
   settings does not roll back the logger image.

The earlier `Results/4-ch-200hz/261112_092939.bdq` is a useful ADC-only baseline:
11416continuous rows, zero channel reuse/failures/timeouts, mean ageabout2.1ms.
It used r14, one stream and a1024-row primary queue; the gate rejected the IMU.
Do not overwrite it or compare its low storage load as a matched mixed result.

Assess per-channel new/reused conversions and ages/maxima, row continuity,
ADC errors/timeouts, actual IMU participation, source-bounded IMU gaps/tail,
queues/write durations and cleanup together. Finite benchmark acceptance is not
production admission. No agreed acceptable reuse threshold exists. Preserve the
small historical STOP-tail warning and unexplained39.7ms age maximum separately.
Controlled storage-stall testing remains deferred. More channels add continuous
acquisition work in discrete selected-rate steps, not simply proportional to
output rows/s. Four-channel500Hz freshness is not inferred from two-channel tests.
