# r13: Storage worker priority trial

Logger-only follow-up to r12 `261111_171512.bdq`, SHA-256 prefix `0af2deb09dd2`.
ADC priority3 improved row reuse from about17% to below0.4%, but r12 lost3763
primary rows (11.74%) and had substantial IMU gaps/backpressure. Measured write-call
rate declined about29%. Storage CPU contention versus SD variability remains
unresolved; this trial tests scheduling without a controlled storage-stall campaign.

The sole behavior change from r12 is storage worker priority1 to2. Keep ADC3,
CAN acquisition2/group8, task affinities and all buffering, commands, conversion
settings, readiness, SPI mode/clocks/pacing, CRC and data formats unchanged.
Ordinary build defaults remain storage1 and ADC2. Existing r11 phase diagnostics
remain enabled. ADC/sampler tasks are pinned to core0, storage to core1, CAN
acquisition is unpinned. No claim about actual CAN core residency is made.

## Installation

Use the passed manifest's `variants.storage_priority`, environment
`bodaqs_s3_mini_n4r2_imu_adc_storage_priority`, firmware name
`bodaqs_a8_imu_adc_storage_priority_r13`. Flash only this logger application at
`0x10000`, preserving partition table and NVS/settings. Exact r10 master and node
images are reused; do not flash them. The fixed r12 logger is the immediate
comparison/rollback image; the sealed r11 logger remains the fallback if the
scheduling experiment does not recover useful delivery.

## Recording

1. After the logger upload, restart the IMU node. Keep the same basic SD card,
   wiring and sensor configuration: one IMU and one500Hz analog channel on each
   ADC, multistream BDQv2. Floating analog inputs may remain.
2. Start normally and confirm three streams/two primary columns/no IMU exclusion
   at admission. If excluded, stop and preserve the file/serial rather than using
   an ADC-only result as a mixed-load comparison.
3. Record about60seconds, STOP normally and wait for file closure/cleanup. Provide
   finalized BDQ and full serial/FLOW output. No CCS export or scope capture is
   needed. Preserve evidence before another recording.

## Acceptance and limits

Assess primary sequence gaps against producer-drop counters and flags, IMU gaps,
identity resolution/source terminal boundary/STOP cleanup, queue peaks and consumer
waits. Compare write-call elapsed times/rates and ADC age/reuse/phase counters
against r12 and the r11 mixed baseline. A500Hz producer or clean file closure alone
does not establish delivery. Do not add repeated cumulative source-loss observations
or report whole-run IMU loss percentages without resolved source bounds.

The intended result is recovery of end-to-end delivery while retaining r12 ADC
freshness, not simply moving contention to CAN. A passing short run selects the
next action; it does not qualify sustained capacity or broaden admission.
If ineffective, return to sealed r11 before further scheduling experiments.
Controlled storage-stall testing, card comparisons and known-input accuracy/mux
checks remain deferred. Keep defaults unchanged pending physical evidence.
