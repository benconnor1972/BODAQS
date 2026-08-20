# BMI270 fused inertial derived product, first slice

- Stream schema: `bodaqs.inertial_stream.v1`
- QC schema: `bodaqs.attitude_qc.v1`
- Scope: offline orientation and attitude-dependent inertial vectors for an
  accepted frame-mounted BMI270
- Excluded: on-device fusion and position/velocity integration

## Inputs and authority

The product consumes the existing valid-only `bodaqs.imu_stream.v1` stream and
the reconstructed `gps_logger` stream. Raw IMU and GPS columns remain
authoritative and are never replaced or modified.

The IMU input must provide `body_local` acceleration and angular velocity from
an accepted `sensor_native -> body_local` mounting transform. The first slice
only admits `domain=frame`; steering and unsprung IMUs do not yet have the
kinematics needed to represent the main bicycle body in ENU.

GPS `course_over_ground` is explicitly distinct from direct bicycle heading.
It is used only as a conditional yaw observation.

## Output convention

`q_body_to_world_enu_[wxyz]` is a unit quaternion, scalar first, rotating a
vector from the right-handed bicycle `body_local` frame into local ENU:

- body X is forward, body Y left, body Z up;
- ENU X is east, Y north, Z up;
- `roll_rad`, `pitch_rad`, and `yaw_enu_rad` are intrinsic ZYX convenience
  values derived from that quaternion.

The product emits an explicit state for every sample:

- `gravity_aligned`: roll/pitch are gravity-referenced; yaw is arbitrary.
- `world_enu_constrained`: a sufficiently recent accepted GPS-course update
  establishes yaw in ENU.
- `world_enu_degraded`: yaw continues to propagate from a prior course update,
  with growing uncertainty.

No pre-course sample may be presented as a causal world-heading observation
merely because it has a numerical quaternion.

## Inertial dynamics output

The stream additionally exposes two g-g-chart input families, allowing the
view to choose its interpretation without re-running preprocessing:

- `specific_force_body_[xyz]_m_s2`: the measured accelerometer output in the
  bicycle body frame, including gravity;
- `linear_accel_body_[xyz]_m_s2`: specific force with the attitude-derived
  gravity vector removed; and
- their ENU equivalents where the offline world-yaw solution is available.

`gravity_body_[xyz]_m_s2`, body/world horizontal magnitudes, body angular
speed, ENU angular velocity, and world-up turn rate are also registered. ENU
quantities use the fixed-interval yaw solution, so they are intentionally
absent where no defensible world yaw can be inferred. Body-frame quantities
remain available from the causal gravity-aligned attitude.

The profile can omit costly optional families through
`imu_attitude.inertial_dynamics`: `enabled`, `include_world_frame`,
`include_angular_kinematics`, and `include_magnitudes`. The smoothed
orientation itself remains available when dynamics are disabled.

## Offline world-yaw smoother

The persisted stream also provides an acausal, fixed-interval yaw product:

- `yaw_world_enu_smoothed_rad`;
- `yaw_world_enu_smoothed_sigma_deg`;
- `yaw_world_enu_smoothed_state_code`; and
- `yaw_world_enu_smoothed_group` plus
  `yaw_world_enu_gap_bridged_before` provenance.

It first removes the causal world-Z course corrections to recover the
gravity/gyro-relative attitude, then uses every accepted GPS-course observation
in a logical continuity group to estimate a world-Z phase correction across
the whole group. This backfills samples preceding the first usable course and
extrapolates after the last one. Its state codes are `unobserved`,
`course_smoothed`, `course_backfilled`, and `course_extrapolated`.

Adjacent IMU continuity segments are joined only where the physical timestamp
gap is at most 250 ms and the nearby gyro samples imply no more than 45 degrees
of rotation across the gap. The bridge is recorded; it does not manufacture
missing IMU samples. Larger or implausible gaps remain separate, and a group
without an accepted GPS-course observation remains unobserved.

## First-slice estimator

The estimator is a conservative quaternion propagation/correction filter:

1. Start each IMU continuity segment by aligning measured acceleration to ENU
   up, leaving yaw arbitrary.
2. Propagate on actual reconstructed IMU timestamps using IOC-compensated gyro
   output plus the accepted startup stationary residual when available.
3. Apply a small gravity correction only when acceleration magnitude, local
   magnitude variance, and jerk pass the configured gates.
4. Apply a bounded world-Z correction from GPS course only when the observation
   is valid, fresh, above the speed threshold, and passes course/speed accuracy
   gates.
5. Keep causal yaw evidence separate from the offline smoother; the latter may
   bridge only conservative, explicitly recorded short continuity gaps.

The stream retains correction weights, innovation, rejection codes, yaw sigma,
and continuity segment so a consumer can distinguish evidence from inference.

## GPS evidence required for yaw correction

For attitude-capable logs, configure the DAN-F10N with a useful update rate
(initially 5 Hz) and `quality_columns=full`. Firmware v0.5.2-dev adds:

- `speed_accuracy` in m/s;
- `course_accuracy` in degrees; and
- `receiver_time_of_week` in centiseconds (`cs`), preserving 10 ms timing in
  the logger float carrier throughout a GPS week.

The host GPS stream exposes these as `speed_accuracy_mps`,
`course_accuracy_deg`, `receiver_time_of_week_s`, and
`snapshot_received_time_s`. The latter is logger time less the recorded
snapshot age: it is a reception-time observation, not yet a proven antenna
measurement timestamp. Timing residuals therefore remain a required field-test
and should be considered when interpreting yaw innovation during rapid turns.

## Integration

The public opt-in API is:

```python
from bodaqs_analysis import AttitudeConfig, build_attitude_streams

build_attitude_streams(session, sensors=["imu0"], config=AttitudeConfig())
```

It registers `inertial_<sensor>` as an intermittent secondary stream and
records its metadata and QC under `meta.secondary_streams` and `qc.attitude`.
It is disabled by default, but a preprocess profile can materialise it through
`imu_attitude: {"enabled": true, "required": false}`. `imu_attitude` and
the Python `build_attitude_streams` API retain their names for compatibility;
the persisted stream is the broader inertial product. Readers should accept
the legacy `attitude_<sensor>` / `bodaqs.attitude_stream.v1` artifact when
opening older runs, but new preprocessing writes only the inertial name and
schema. The preprocessing status is stored in `meta.attitude_preprocessing`;
per-sensor QC is retained in `meta.attitude_qc` and the derived stream metadata.
