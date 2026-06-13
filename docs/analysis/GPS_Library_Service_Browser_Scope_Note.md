# GPS Library Service And Browser Scope Note

Status: draft  
Audience: library service / browser / study-set builder implementation agent

Preprocessing can now preserve both logger-derived GPS and FIT-derived GPS in a
processed session. The default policy is to preserve all GPS sources and prefer
logger GPS when both logger GPS and FIT enrichment are present.

## Preprocessing Contract To Consume

Processed sessions may include:

- `meta.gps_sources`
- `stream_dfs["gps_logger"]`
- `stream_dfs["gps_fit"]`
- `meta.secondary_streams["gps_logger"]`
- `meta.secondary_streams["gps_fit"]`

`meta.gps_sources` has:

- `schema`: `bodaqs.gps_sources`
- `version`: `1`
- `policy`: the applied source-selection policy
- `preferred_source`: stream/source id to use by default
- `preferred_source_kind`: usually `logger_sensor` or `fit_enrichment`
- `sources`: all detected GPS sources with source kind, stream name, position
  columns, quality columns, point count, and sensor where available

Logger GPS route streams use canonical route columns:

- `time_s`
- `latitude_deg`
- `longitude_deg`
- optional `altitude_m`
- optional `speed_mps`
- optional `heading_deg`
- optional `distance_m`
- optional QC columns such as `valid`, `age_ms`, `seq`, `fresh`, `fix_type`,
  `satellites`, `horizontal_accuracy`, and `vertical_accuracy`

FIT GPS streams remain `gps_fit` and usually use existing FIT-derived column
names, but their metadata now includes `source_kind=fit_enrichment`,
`domain=world`, and semantic `quantity` fields.

## Required Service Review

- Use `meta.gps_sources.preferred_source` as the default source for catalog GPS
  summaries, GPS point endpoints, track creation, and study-set GPS previews.
- Do not sort or prefer sources by stream name such as `gps_fit`.
- Preserve the ability to inspect alternate GPS sources when more than one
  exists.
- Include source kind in public responses: `logger_sensor`, `fit_enrichment`,
  or `unknown`.
- Include logger GPS quality/provenance fields where available, especially
  valid/fresh coverage, age summaries, dedupe method, and cached async snapshot
  status.
- Ensure cache keys for track matching include GPS source identity, source kind,
  and policy/reconstruction details where those affect results.

## Required Browser / Study-Set Review

- Default route previews to the preferred GPS source.
- Add UI affordance for selecting alternate GPS sources when a session contains
  both logger GPS and FIT GPS.
- Keep `gps.source` filters working for both source kinds.
- When creating tracks from session GPS, record the selected GPS source in track
  provenance.
- When building study sets, avoid assuming FIT enrichment is the only GPS
  source.

## Compatibility Notes

Older sessions may not have `meta.gps_sources`. In that case, service/browser
code should continue to fall back to existing GPS discovery behavior, but it
should prefer semantic metadata over column-name heuristics whenever available.
