# GPS Signal Semantics Downstream Work

Firmware GPS support now emits DAN-F10N columns using the general signal
metadata model rather than treating GPS as a special side channel. Position and
motion columns are described as world-frame signals, while status and quality
columns are described as QC metadata.

## Firmware Metadata

The DAN-F10N GPS sensor uses:

- `domain=world`
- `source=async_snapshot`
- Quantities: `position_latitude`, `position_longitude`, `altitude`, `speed`,
  `heading`
- QC quantities: `valid`, `age`, `seq`, `fresh`, `fix_type`, `satellites`,
  `horizontal_accuracy`, `vertical_accuracy`

The firmware log metadata can now include these optional per-channel fields:

- `kind`
- `source`
- `processing_role`
- `semantic_selection_excluded`

GPS QC/status columns are emitted with `kind=qc`,
`processing_role=qc_metric`, and `semantic_selection_excluded=true` so they can
remain available without being selected as ordinary engineering signals.

## Analysis Touch Points

Downstream import should copy the new per-channel fields from logger JSON
metadata into `meta.channel_info`, especially in
`pipeline._build_channel_info_from_sidecar`.

BDQ ingestion should copy the same fields from embedded channel schemas in
`io_bdq.bdq_to_log_metadata` and any direct BDQ-to-dataframe metadata path.

`signal_registry.build_signals_registry` should honor logger-supplied `kind`
values and `semantic_selection_excluded`. In particular, QC channels should be
discoverable but excluded from default semantic signal selection.

The GPS browser should resolve logger GPS columns semantically from
`meta.signals` instead of relying on hardcoded FIT-derived column names. The
minimum selector for logger GPS should be `domain=world` plus
`quantity=position_latitude` and `quantity=position_longitude`.

If both FIT enrichment and logger GPS are present, the UI should use an explicit
source preference policy rather than whichever column names happen to exist
first.

Session GPS summaries should include the GPS source, point count, valid/fresh
coverage, gaps, and whether the row values are cached async snapshots.

## Logging Semantics

The primary firmware row stream remains fixed-rate. GPS values in each row are
cached async snapshots of the most recent receiver update, not proof that the
GPS produced a new fix at that exact row timestamp. Downstream code should use
the `valid`, `fresh`, `age`, and `seq` columns when reconstructing GPS points or
calculating coverage.

Add fixtures/tests for:

- CSV plus sidecar JSON logs containing DAN-F10N GPS columns.
- BDQ logs containing DAN-F10N GPS channel schema entries.
- Mixed sessions with both logger GPS and FIT-derived GPS.

## Downstream Preprocessing Notes

The firmware CSV headers are intentionally compact and sensor-instance based,
for example `gps0_lat [deg]`, `gps0_lon [deg]`, `gps0_alt [m]`,
`gps0_speed [m/s]`, and optional QC columns such as `gps0_valid`,
`gps0_age [ms]`, `gps0_seq`, `gps0_fresh`, `gps0_fix_type`, `gps0_sats`,
`gps0_hacc [m]`, and `gps0_vacc [m]`. Downstream code should not parse GPS
meaning from these names if log metadata is present. Prefer the sidecar or BDQ
channel schema fields: `domain`, `quantity`, `unit`, `source`, `kind`,
`processing_role`, and `semantic_selection_excluded`.

Preprocessing should build a logger-GPS route stream from semantic selectors,
not FIT-style hardcoded column names. A minimal selector is:

- latitude: `domain=world`, `quantity=position_latitude`, `unit=deg`
- longitude: `domain=world`, `quantity=position_longitude`, `unit=deg`
- optional altitude: `domain=world`, `quantity=altitude`, `unit=m`
- optional speed: `domain=world`, `quantity=speed`, `unit=m/s`
- optional heading: `domain=world`, `quantity=heading`, `unit=deg`

QC selectors should resolve the corresponding `kind=qc` channels from the same
sensor/source where possible. In particular, `valid`, `age`, `seq`, and
`fresh` are the fields that distinguish a real GPS update from a repeated cached
snapshot in the synchronous logger row stream.

Recommended route reconstruction policy:

1. Start with rows where latitude and longitude are finite.
2. If a `valid` QC column exists, require `valid == 1` for default route
   construction. Keep invalid rows available for diagnostics, but do not draw
   them as normal route points.
3. If an `age` QC column exists, record it in the route stream and use it for
   coverage/gap metrics. Rows with high age are stale snapshots, not fresh GPS
   fixes.
4. If `seq` is present, collapse repeated cached rows by keeping the first row
   for each new sequence value. This produces a point-per-receiver-update
   route.
5. If `fresh` is present, `fresh == 1` can be used as an equivalent point
   selector, but `seq` is usually better for de-duplication and gap analysis.
6. If only minimal QC is logged (`valid` and `age`, no `seq` or `fresh`), do
   not report logger row count as GPS fix count. Either keep the fixed-rate
   cached stream explicitly labelled as cached, or downsample/segment it using
   time and coordinate changes with a clear lower-confidence provenance note.

Firmware validity policy affects what the numeric position/motion columns mean:

- `valid_only` (default): position and motion values are emitted only while the
  latest snapshot is valid and not stale; otherwise they are `NaN`.
- `fresh_only`: position and motion values are emitted only on the first logger
  row after a new valid, non-stale GPS update. This is easiest for route-point
  reconstruction but leaves sparse GPS columns in the primary row stream.
- `latest_with_status`: the latest snapshot may be emitted even when invalid or
  stale. Downstream code must apply `valid`/`age` policy before drawing routes
  or computing coverage.

The logger row timestamp remains the authoritative time axis for the row in
which a GPS snapshot was sampled. It is not currently a GPS receiver timestamp,
and GPS does not discipline the logger RTC in the current firmware. The firmware
does read GPS time internally, but it is not emitted as a log signal yet; if we
later emit GPS time-of-week or Unix time, that should become a separate
navigation timing/QC signal rather than silently replacing logger time.

Coordinate and motion semantics to preserve:

- Latitude/longitude are WGS84-style degrees from the receiver PVT solution.
- Altitude is MSL altitude in metres.
- Speed is ground speed in metres per second.
- Heading is heading of motion in degrees.
- Horizontal and vertical accuracy are receiver estimates in metres.
- `fix_type` follows the receiver PVT fix type; firmware treats fixes with
  `fix_type >= 2`, `fixOk`, and non-invalid LLH as valid.

Suggested preprocessing outputs:

- Add a semantically resolved logger GPS route stream, for example
  `stream_dfs["gps_logger"]` or `stream_dfs["gps_<sensor_id>"]`, rather than
  only adding columns to the primary fixed-rate dataframe.
- Keep the original primary-row GPS columns in `session["df"]` for correlation
  with suspension/brake/ADC data.
- Store route-stream provenance: `source=logger_gps`, sensor id, validity
  policy if available, QC column coverage, point count, valid coverage, fresh
  coverage, maximum/median age, and gap summary.
- If FIT GPS and logger GPS are both present, choose one using an explicit
  source-preference policy and record the chosen source. Do not silently merge
  or prefer whichever hardcoded column name is found first.

Current analysis code still has hardcoded FIT GPS column expectations in the GPS
browser path. The next practical change is to make that code resolve route
columns from `session["meta"]["signals"]`, while keeping FIT-derived streams as
one possible source. This is also the point to decide the canonical route stream
name and source-preference policy.

Additional fixtures/tests to add:

- Logger GPS with default `quality_columns=minimal` and `validity_policy=valid_only`.
- Logger GPS with `quality_columns=full`, verifying `seq` de-duplication and
  `fresh` coverage.
- Logger GPS with `validity_policy=fresh_only`, verifying sparse primary-row
  GPS values become a correct route stream.
- Logger GPS with `latest_with_status`, verifying invalid/stale points are
  excluded from the default route but retained for diagnostics.
- Sessions with both logger GPS and FIT GPS, verifying explicit source
  selection and provenance.
