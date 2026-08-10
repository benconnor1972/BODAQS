# BMI270 IMU extraction and quality control

- Contract: `bodaqs.imu_stream.v1` and `bodaqs.imu_qc.v1`
- Scope: valid-only native IMU extraction, scaling, mounting transform, and collection QC
- Excluded: orientation fusion, gravity removal, bias application, and resampling across loss

## Integration

`load_session()` and `load_bdq_session()` automatically identify BMI270 columns from logger semantic metadata. Each complete IMU is added to `session["stream_dfs"]` as `imu_<sensor>`. Its descriptive metadata is stored in `session["meta"]["secondary_streams"]`.

QC is available at both `session["qc"]["imu"]` for the live pipeline and `session["meta"]["imu_qc"]` so it is retained in persisted session metadata. The two representations contain the same deterministic report.

The public functions are:

```python
from bodaqs_analysis import build_imu_streams, extract_imu_stream, imu_qc_report
```

`extract_imu_stream(session, sensor, strict=True)` fails clearly when the effective range, native rate, sensor-time scale, or mounting transform is unavailable. `strict=False` preserves a raw valid-only stream and marks its QC result as degraded when safe derived channels cannot be produced.

## Stream time and columns

The stream contains one row for each primary logger row whose IMU `sample_valid` value is one. It does not synthesize samples across a gap.

Core columns include:

- `time_s`: monotonic native-slot time reconstructed from unwrapped firmware sequence and effective IMU rate; gaps remain visible as longer intervals;
- `logger_time_s` and `logger_row_index`: the primary-row emission observation;
- `host_sample_time_s`: logger time less recorded acquisition age when available;
- wrapped and unwrapped sequence and sensor-time values;
- `continuity_segment`, which changes at loss, timing inconsistency, or a localized FIFO, queue, recovery, or degraded-timing incident;
- raw signed accelerometer, gyro, and temperature counts;
- acquisition age and status flags;
- temperature in degrees Celsius;
- sensor-native acceleration in metres per second squared and angular velocity in radians per second when effective ranges are available; and
- `body_local` acceleration and angular velocity when a valid signed-axis-permutation mounting transform is available.

The raw columns are authoritative and are never replaced by scaled or transformed values. For a frame-mounted IMU, `body_local` is the bicycle body frame. For steering or unsprung IMUs it remains the local frame of that articulated assembly.

A clean sequence is registered as a uniform stream at the effective IMU rate. A stream with gaps, duplicates, out-of-order values, or localized timing incidents is registered as intermittent. Either form is directly usable for plotting. Spectrum preparation can group by `continuity_segment` and select regions of adequate duration without silently interpolating across loss.

## QC report

Each sensor report includes:

- decoded sample count, nominal and measured native rate, duration, file size, and byte rate;
- sequence gap events, missing-sample total, duplicates, out-of-order values, and coverage;
- sensor-time discontinuities and a linear clock fit against acquisition-age-corrected logger time, including drift and residual statistics;
- localized ranges for FIFO, queue, recovery, degraded-timing, temperature-stale, and near-rail status flags;
- independently calculated per-axis near-rail fractions and event ranges;
- acquisition-age distribution and temperature range;
- the firmware startup stationary observation and selected firmware counters when present; and
- explicit warnings or degraded/failure status.

Event locations are represented as contiguous dense-stream ranges. At most 64 ranges are retained per flag or axis; the complete affected-sample and event counts remain available when this compact location list is truncated.

## Post-processing boundary

The extracted stream is a collection-evidence product. It intentionally does not:

- subtract the recorded startup gyro mean;
- estimate attitude or a world frame;
- remove gravity from acceleration;
- fill missing samples automatically; or
- claim that `body_local` for an articulated sensor is the main bicycle frame.

Those operations remain reversible, versioned post-processing decisions built on this stream.
