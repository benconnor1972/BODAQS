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
