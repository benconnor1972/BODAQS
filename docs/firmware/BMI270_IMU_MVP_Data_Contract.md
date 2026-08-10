# BMI270 IMU MVP Data Contract

- Status: Accepted
- Contract ID: bodaqs.bmi270_imu_mvp.v1
- Scope: Normative data contract for the accepted BMI270 IMU MVP plan
- Related plan: [BMI270 IMU MVP Implementation Plan](BMI270_IMU_MVP_Implementation_Plan.md)

## 1. Purpose

This contract fixes the externally observable data and configuration semantics needed before BMI270 acquisition is implemented. Phase 2 and later code may change internal structures, but must not change these meanings without revising the contract ID and recording the revision in session metadata.

The MVP stores sensor-native evidence. Mounting transforms, scaling, calibration, and orientation are derived operations; they do not replace the raw log.

## 2. Reference implementation

The integrated driver is the Bosch Sensortec BMI270 SensorAPI:

- upstream: https://github.com/boschsensortec/BMI270_SensorAPI
- pinned revision: 41129fcfe39c583ee5462d79195741945d51c1fe
- BMI270 API version declared by the pinned header: 2.86.1
- licence: BSD-3-Clause, from the upstream `LICENSE` at the pinned revision

PlatformIO downloads the exact Git revision. A generated-package manifest limits compilation to the official `bmi2.c` and `bmi270.c` sources because the upstream repository has no PlatformIO manifest and otherwise exposes hardware-specific examples as library sources. The firmware must record the revision or release identifier in session metadata when the sensor adapter is added in Phase 4.

## 3. Coordinate and mounting contract

The BODAQS bicycle body frame is right-handed:

- positive X: forward;
- positive Y: left;
- positive Z: up.

Configuration fields mount_x, mount_y, and mount_z define each local mounted-body axis as one signed sensor-native axis. For example:

    mount_x=+y
    mount_y=-x
    mount_z=+z

means:

    body_local_x = sensor_y
    body_local_y = -sensor_x
    body_local_z = sensor_z

A valid transform uses each of x, y, and z exactly once and has determinant +1. Invalid, duplicate, missing, or left-handed mappings are configuration errors.

Raw columns remain in BMI270 sensor-native axes. The transform is stored as metadata and applied by host processing.

For a frame-mounted IMU, `body_local` coincides with the bicycle body frame. For steering and unsprung installations, a static installation transform does not account for steering or suspension articulation; transforming those values into `bike_body` requires additional post-processing evidence.

## 4. orientation_200 profile

The named orientation_200 profile expands to:

| Setting | Required value |
|---|---|
| Accelerometer ODR | 200 Hz |
| Accelerometer range | plus or minus 16 g |
| Accelerometer bandwidth | BMI2_ACC_NORMAL_AVG4 |
| Accelerometer filter performance | BMI2_PERF_OPT_MODE |
| Gyroscope ODR | 200 Hz |
| Gyroscope range | plus or minus 2000 degrees per second |
| Gyroscope bandwidth | BMI2_GYR_NORMAL_MODE |
| Gyroscope noise performance | BMI2_POWER_OPT_MODE initially |
| Gyroscope filter performance | BMI2_PERF_OPT_MODE |
| FIFO mode | Header mode |
| FIFO content | Accelerometer, gyroscope, and sensor-time information |
| Sensor-time tick | 39.0625 microseconds |
| Sensor-time modulus | 2^24 ticks |
| I2C clock | 400 kHz |
| Acquisition service | Polling, initially scheduled at 200 Hz |
| Temperature observation | 10 Hz register read, held between observations |
| Temperature freshness limit | 250 milliseconds |
| Logger row rate | 500 Hz |

Phase 2 must read back effective sensor configuration. Both requested profile name and effective values are recorded. If the Bosch API or device rejects a required value, initialization fails visibly rather than silently substituting another profile.

The initial gyroscope noise-performance choice follows the Bosch example default and is deliberately recorded. Bench data may justify a revised named profile; it must not silently alter orientation_200.

## 5. Scale contract

Raw accelerometer and gyroscope values are signed 16-bit counts.

For orientation_200:

    accel_g = accel_raw * 16 / 32768
    accel_m_s2 = accel_g * 9.80665
    gyro_deg_s = gyro_raw * 2000 / 32768
    gyro_rad_s = gyro_deg_s * pi / 180

Nominal scale factors are therefore:

- accelerometer: 0.00048828125 g/count;
- accelerometer: approximately 0.00478840332 m/s^2/count;
- gyroscope: 0.06103515625 degree/s/count;
- gyroscope: approximately 0.00106526444 rad/s/count.

Temperature is signed 16-bit raw data. Host conversion is:

    temperature_deg_c = temperature_raw / 512 + 23

The Phase 3 implementation reads die temperature independently at 10 Hz and holds the most recent raw value across FIFO samples. A value older than 250 milliseconds, or the placeholder used before any successful observation, carries `TEMPERATURE_STALE`. Metadata must preserve this cadence, freshness limit, and held-value policy.

## 6. Row and channel contract

The logger row rate is 500 Hz. The IMU native rate is 200 Hz.

- Each successfully queued native sample is emitted into exactly one logger row.
- sample_valid is 1 only when that row contains a new native IMU sample.
- No IMU sample is repeated to fill later rows.
- An invalid row contains the placeholders specified below.
- Consumers must filter sample_valid before interpreting any other IMU sample column.

For a configured sensor name frame_imu, the fields are:

| Field | BDQ storage | Invalid value | Meaning |
|---|---|---:|---|
| frame_imu_accel_x_raw | int16 | 0 | Sensor-native acceleration X |
| frame_imu_accel_y_raw | int16 | 0 | Sensor-native acceleration Y |
| frame_imu_accel_z_raw | int16 | 0 | Sensor-native acceleration Z |
| frame_imu_gyro_x_raw | int16 | 0 | Sensor-native angular rate X |
| frame_imu_gyro_y_raw | int16 | 0 | Sensor-native angular rate Y |
| frame_imu_gyro_z_raw | int16 | 0 | Sensor-native angular rate Z |
| frame_imu_sensor_time_u24 | uint32 | 0 | Estimated sample tick on the low-24-bit BMI270 sensor-time grid |
| frame_imu_seq_u24 | uint32 | 0 | Low 24 bits of firmware native-sample sequence |
| frame_imu_temperature_raw | int16 | 0 | Associated or most recent die temperature |
| frame_imu_sample_age_us | float32 | NaN | Estimated sample age at logger-row emission |
| frame_imu_status_flags | uint16 | 0 | Per-sample status bitfield |
| frame_imu_sample_valid | uint16 | 0 | 1 for a new native sample; otherwise 0 |

The column IDs above are canonical. CSV headers may add unit labels according to existing firmware conventions, but BDQ field IDs must remain stable.

All integer-valued IMU fields carried through the current float32 row buffer are at most 24 significant bits. Signed 16-bit values, uint16 flags, the 24-bit sensor clock, and the modulo-2^24 sequence are therefore exact.

## 7. Column semantic metadata

| Field group | domain | quantity | component | coordinate_frame | vector_group | unit | source | class |
|---|---|---|---|---|---|---|---|---|
| accel_*_raw | configured mount domain | linear_acceleration_raw | x/y/z | sensor_native | accel_raw | count | async_fifo_once | signal |
| gyro_*_raw | configured mount domain | angular_velocity_raw | x/y/z | sensor_native | gyro_raw | count | async_fifo_once | signal |
| sensor_time_u24 | configured mount domain | sensor_time | - | - | - | tick | bmi270_sensor_time | diagnostic |
| seq_u24 | configured mount domain | sample_sequence | - | - | - | count | firmware_sequence | diagnostic |
| temperature_raw | configured mount domain | temperature_raw | - | - | - | count | bmi270_temperature | diagnostic |
| sample_age_us | configured mount domain | sample_age | - | - | - | us | native_to_row_timing | diagnostic |
| status_flags | configured mount domain | status | - | - | - | bitfield | imu_status | diagnostic |
| sample_valid | configured mount domain | sample_valid | - | - | - | boolean | async_fifo_once | diagnostic |

All diagnostic columns are excluded from automatic physical-signal selection. Axis identity is explicit metadata; consumers must not depend on parsing the canonical field/column ID.

The configured mounting semantics are:

| domain | permitted end | meaning |
|---|---|---|
| unsprung | front, rear | Assembly moving predominantly with the corresponding axle, including caliper, fork-lower, or rear-triangle mounting |
| frame | front, rear, null | Main sprung frame; front/rear describes the coarse mounting region |
| steering | front | Sprung assembly rotating about the steering axis |

`mount_point` is optional descriptive detail and is not a primary signal selector. The legacy configuration field `location` is accepted as an alias for `domain`; new metadata uses `domain` and `end` while retaining `location` temporarily for reader compatibility.

## 8. Status flag contract

frame_imu_status_flags is a uint16 bitfield:

| Bit | Mask | Name | Meaning |
|---:|---:|---|---|
| 0 | 0x0001 | FIFO_DISCONTINUITY_BEFORE | FIFO skip/overflow or an unexplained native-time discontinuity precedes this sample |
| 1 | 0x0002 | QUEUE_DROP_BEFORE | One or more samples were dropped by the firmware queue before this sample |
| 2 | 0x0004 | SENSOR_RECOVERY_BEFORE | I2C or sensor recovery occurred before this sample |
| 3 | 0x0008 | TIMING_DEGRADED | sample_age_us or native timing has degraded confidence |
| 4 | 0x0010 | SENSOR_TIME_ESTIMATED | Native tick was back-filled/interpolated rather than directly anchored |
| 5 | 0x0020 | TEMPERATURE_STALE | Temperature is older than the metadata-declared freshness limit |
| 6 | 0x0040 | ACCEL_NEAR_RAIL | At least one accelerometer axis is at or beyond plus/minus 32760 counts |
| 7 | 0x0080 | GYRO_NEAR_RAIL | At least one gyroscope axis is at or beyond plus/minus 32760 counts |
| 8-15 | 0xFF00 | RESERVED | Must be written as zero in contract v1 |

A discontinuity/recovery flag applies to the first stored sample after the event. Cumulative counts and exact loss counts belong in final session diagnostics.

## 9. Timing contract

BMI270 sensor time is a 24-bit counter with a nominal 39.0625 microsecond tick and an approximately 655.36 second wrap interval.

Firmware:

1. stores an estimated low-24-bit BMI270 tick for every valid sample when an anchor or valid continuation is available;
2. treats the FIFO sensor-time control frame as a raw observation taken when the FIFO empties, then aligns sample ticks to the 200 Hz grid at 128-tick intervals;
3. marks back-filled/interpolated values with SENSOR_TIME_ESTIMATED;
4. correlates the raw sensor-time observation with the sensor-time frame's byte position within the host-observed FIFO transfer;
5. estimates sample_age_us as:

       logger_row_monotonic_us - estimated_native_sample_monotonic_us

6. stores NaN and sets TIMING_DEGRADED when the estimate is unavailable, including an initial batch with no sensor-time anchor, or fails consistency checks.

The host:

1. filters valid rows;
2. unwraps sensor_time_u24 and seq_u24 modulo 2^24;
3. checks both for gaps, duplicates, reversals, and inconsistent increments;
4. reconstructs the 200 Hz native timeline from sensor ticks;
5. treats the 500 Hz row time as an emission observation, not the sample time.

## 10. Session identity and configuration metadata

The sensor metadata object must include:

- contract_id;
- sensor instance name;
- stable imu_id;
- domain and end;
- optional mount_point;
- sensor type;
- I2C bus and address;
- chip ID and initialization result;
- requested profile;
- effective accelerometer ODR, range, bandwidth, and filter-performance setting;
- effective gyro ODR, range, bandwidth, noise-performance, and filter-performance settings;
- FIFO mode, enabled content, polling rate, and selected watermark;
- sensor-time tick and modulus;
- temperature sampling semantics and freshness limit;
- mounting transform;
- calibration_ref, including an empty value when none is selected;
- Bosch driver revision;
- firmware version.

Metadata field names should use lower snake case. Session data remains usable if optional descriptive fields are absent, but contract_id, effective ranges/rates, timing constants, mounting transform, and validity semantics are required.

## 11. Startup stationary observation

The default startup observation window is 5 seconds. The observation is valid only if:

- at least 800 valid native samples are present;
- no FIFO, queue, recovery, or timing-degraded event occurs in the window;
- mean acceleration magnitude is within 0.15 g of 1 g;
- standard deviation of acceleration magnitude is no greater than 0.03 g;
- gyroscope standard deviation is no greater than 0.5 degree/s on every axis; and
- maximum gyroscope vector magnitude is no greater than 5 degree/s.

The session summary records:

- configured window and thresholds;
- accepted/rejected state and rejection reason;
- valid sample count;
- raw gyro mean and standard deviation per axis;
- acceleration-magnitude mean and standard deviation;
- mean/minimum/maximum temperature.

These statistics are observations only. Firmware does not subtract the gyro mean or otherwise alter logged raw samples.

## 12. Session boundaries

At logging start:

1. suspend acquisition;
2. flush hardware FIFO and software queue;
3. count discarded pre-session frames separately;
4. reset session sequence and diagnostics;
5. establish the first timing anchor;
6. enable session acquisition.

At logging stop:

1. stop new accelerometer/gyro production;
2. perform a final FIFO drain;
3. emit all remaining queued samples;
4. publish final diagnostics;
5. finalize the BDQ file.

No queued sample may enter a later session. If final draining fails, the summary records the failure and any known discard count.

## 13. Required final diagnostics

The final summary must contain, per IMU:

- FIFO data frames parsed;
- FIFO drain calls, passes, bytes read, pass-limit hits, maximum observed fill, and maximum drain duration;
- sensor-time anchors parsed;
- missing-anchor batches and normal FIFO over-read markers;
- FIFO skip and overflow counts;
- partial or invalid FIFO frame count;
- samples enqueued and emitted;
- exact software queue drop count;
- queue capacity and high-water mark;
- I2C failure and recovery counts;
- I2C operation count, maximum failure streak, last failure detail, and failure counts by transport stage;
- I2C bus-lock attempt and timeout counts, cumulative lock wait, and maximum lock wait;
- timing-degraded sample count;
- acquisition-age minimum, median, 95th percentile, 99th percentile, and maximum where feasible;
- sequence and native-time discontinuity counts;
- near-rail counts per accelerometer and gyro axis;
- temperature minimum and maximum;
- pre-session discard and stop-drain failure counts;
- startup stationary observation.

No data-loss counter may saturate silently. If an exact count is unavailable, the corresponding diagnostic explicitly states that only an event count is known.

## 14. Synthetic acceptance cases

Phase 0/1 fixtures cover the file-format portions of these cases. FIFO/queue cases become executable driver tests in Phase 3.

| Case | Required evidence |
|---|---|
| Signed extrema | -32768, -1, 0, and 32767 round-trip through int16 |
| Exact 24-bit values | 0, 1, 0xFFFFFE, and 0xFFFFFF round-trip through uint32 |
| Legacy schema | Existing automatic raw/unwrapped/calibrated choices remain unchanged |
| Invalid row | sample_valid=0, raw placeholders zero, sample_age_us NaN |
| Normal sparse rows | Every valid sequence value appears once |
| Native-time wrap | 0xFFFFxx to 0x0000xx unwraps monotonically |
| FIFO discontinuity | First later sample carries FIFO_DISCONTINUITY_BEFORE |
| Queue overflow | Drop counter increments and first later sample carries QUEUE_DROP_BEFORE |
| Recovery | First sample after recovery carries SENSOR_RECOVERY_BEFORE |
| Missing timing | sample_age_us is NaN and TIMING_DEGRADED is set |
| Stationary start | Valid thresholds produce recorded means/variances |
| Moving start | Observation is rejected without changing raw data |
| Back-to-back sessions | No stale sample crosses the boundary |
| Unsupported storage | Host fails clearly without decoding misaligned later fields |

## 15. Compatibility

BDQ file magic, major/minor file header values, chunk headers, and fixed_mixed_v1 layout remain unchanged for Phase 1.

The channel schema gains int16 as an additive storage type. Existing descriptors use Automatic storage selection and therefore keep their current representation:

- non-raw columns: float32;
- raw unwrapped columns: int32;
- other raw columns: uint16.

New descriptors may explicitly request Int16, UInt16, Int32, UInt32, or Float32. A reader that does not understand a declared storage type must reject frame decoding clearly; it must not guess a size or continue at a shifted offset.

## 16. Firmware versioning

The stable sensor type key is bmi270_imu_i2c and its user-facing label is BMI270 IMU (I2C). The enum/key may exist before a factory is registered, but it must not be offered as a selectable UI option until the driver is usable.

The first release containing complete BMI270 acquisition is a backward-compatible feature addition and therefore requires a firmware MINOR version increase under the BODAQS firmware versioning policy. Phases 0 and 1 alone do not advertise the incomplete feature or change the current build version.
