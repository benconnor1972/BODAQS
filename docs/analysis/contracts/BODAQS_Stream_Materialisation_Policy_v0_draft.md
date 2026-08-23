# BODAQS stream materialisation policy (v0 draft)

This policy defines where preprocessing materialises a derived signal. It is
about timebase, evidence, and product boundaries; it is not a rule of one
sensor per stream.

## Core rule

Materialise a signal on its natural source or analysis timebase. Append it to
an existing stream when it shares that timebase and interpretation boundary;
create a secondary stream when it has an independent timebase, is raw evidence
that must remain distinct, or is a reusable fused/analysis product.

The primary dataframe is the canonical logger grid. Compatible bicycle-profile
transforms therefore remain primary signals: for example, transformed wheel or
suspension displacement, velocity, and acceleration. They do not become a
secondary stream merely because their source data were transformed.

## Secondary streams

Secondary streams live in `session["stream_dfs"]`; their metadata, timebase,
and per-stream signal registry live in `meta.secondary_streams[<name>]`.
Every numeric signal a consumer may select must have a registry entry in that
stream's `signals` mapping. Consumers resolve signals from this registry, not
from column-name semantics. Across streams, the concrete reference is always
`{stream_name, column}`; a column name alone is only stream-local.

Current examples are:

- `imu_<sensor>`: reconstructed high-rate IMU evidence on its native clock;
- `gps_logger`: reconstructed GPS observations on their native cadence; and
- `inertial_<sensor>`: fused, high-rate orientation and inertial dynamics,
  derived from a frame IMU and optionally GPS course-over-ground.

The inertial stream is deliberately separate from `imu_<sensor>` despite
sharing its sample grid: it is an inferred product with its own correction,
smoothing, and confidence provenance. It never overwrites the raw/reconstructed
IMU evidence.

## Compatibility and selection

New preprocessing writes `inertial_<sensor>` with schema
`bodaqs.inertial_stream.v1`. Readers should continue to recognise already
persisted `attitude_<sensor>` streams with schema `bodaqs.attitude_stream.v1`.
Their contents are legacy orientation products, not aliases to be silently
rewritten.

The policy does not prescribe a visualisation. A g-g view may select either
body-frame specific force (including gravity) or gravity-compensated linear
acceleration through their registry quantities and coordinate-frame fields.
