# BODAQS Garmin FIT Integration Context

Last updated: 2026-04-22

## Goal

Add the ability for BODAQS analysis preprocessing to:

- discover Garmin `.FIT` files from a configured directory
- match one FIT file to one logger session by time overlap
- require a binding when multiple FIT files overlap the same session
- load continuous navigation fields from the FIT file
- persist the raw FIT stream as a secondary session stream
- resample selected FIT fields onto the primary session dataframe time grid

The intended architectural direction is:

- logger ingest supports `CSV` alone or `CSV + JSON sidecar`
- absolute session timing comes from firmware metadata / sidecar
- FIT import policy lives in preprocess config
- per-session multi-match choice lives in a separate bindings manifest

## Current Status

Implemented:

- optional same-stem logger sidecar ingest
- sidecar-driven absolute time anchor on sessions
- support for intermittent secondary streams in session validation
- backend FIT import pipeline
- FIT overlap discovery and ambiguity handling
- raw FIT stream attachment to `session["stream_dfs"]`
- resampled FIT columns onto `session["df"]`
- persistence of secondary streams in artifacts
- copying auxiliary FIT files into canonical session artifact storage
- preprocess-profile support for `fit_import`
- notebook producer paths updated to persist secondary streams and aux sources
- lightweight FIT bindings editor/helper for notebooks
- fallback from `ipydatagrid` to plain `ipywidgets` file selection in preprocess selector

Not yet fully validated:

- parsing and field behavior against real Garmin FIT fixtures from actual rides
- end-to-end notebook UX for interactive ambiguous FIT selection in the main preprocessing notebook
- firmware-side generation of logger sidecar JSON files

## Important Files

Core backend:

- [analysis/bodaqs_analysis/io_fit.py](</c:/Users/benco/dev/BODAQS/analysis/bodaqs_analysis/io_fit.py>)
- [analysis/bodaqs_analysis/pipeline.py](</c:/Users/benco/dev/BODAQS/analysis/bodaqs_analysis/pipeline.py>)
- [analysis/bodaqs_analysis/artifacts.py](</c:/Users/benco/dev/BODAQS/analysis/bodaqs_analysis/artifacts.py>)
- [analysis/bodaqs_analysis/timebase.py](</c:/Users/benco/dev/BODAQS/analysis/bodaqs_analysis/timebase.py>)
- [analysis/bodaqs_analysis/model.py](</c:/Users/benco/dev/BODAQS/analysis/bodaqs_analysis/model.py>)
- [analysis/bodaqs_analysis/io_logger.py](</c:/Users/benco/dev/BODAQS/analysis/bodaqs_analysis/io_logger.py>)
- [analysis/bodaqs_analysis/signal_registry.py](</c:/Users/benco/dev/BODAQS/analysis/bodaqs_analysis/signal_registry.py>)

UI / notebook support:

- [analysis/bodaqs_analysis/ui/preprocess_controls.py](</c:/Users/benco/dev/BODAQS/analysis/bodaqs_analysis/ui/preprocess_controls.py>)
- [analysis/bodaqs_analysis/ui/fit_bindings_editor.py](</c:/Users/benco/dev/BODAQS/analysis/bodaqs_analysis/ui/fit_bindings_editor.py>)
- [analysis/bodaqs_analysis/ui/preprocess_file_selector.py](</c:/Users/benco/dev/BODAQS/analysis/bodaqs_analysis/ui/preprocess_file_selector.py>)
- [analysis/bodaqs_batch_preprocessing_pipeline.ipynb](</c:/Users/benco/dev/BODAQS/analysis/bodaqs_batch_preprocessing_pipeline.ipynb>)
- [analysis/BODAQS_auto_preprocess_simple_suspension_metrics.ipynb](</c:/Users/benco/dev/BODAQS/analysis/BODAQS_auto_preprocess_simple_suspension_metrics.ipynb>)
- [analysis/bodaqs_event_schema_test_harness.ipynb](</c:/Users/benco/dev/BODAQS/analysis/bodaqs_event_schema_test_harness.ipynb>)

Config / manifests:

- [analysis/config/preprocess_profiles/suspension_default_v1.json](</c:/Users/benco/dev/BODAQS/analysis/config/preprocess_profiles/suspension_default_v1.json>)
- [analysis/config/fit_bindings_v1.json](</c:/Users/benco/dev/BODAQS/analysis/config/fit_bindings_v1.json>)

Docs:

- [analysis/Documentation/BODAQS_Preprocess_Profile_Contract_v0_draft.md](</c:/Users/benco/dev/BODAQS/analysis/Documentation/BODAQS_Preprocess_Profile_Contract_v0_draft.md>)
- [analysis/Documentation/BODAQS_Public_API_Contract_v0.md](</c:/Users/benco/dev/BODAQS/analysis/Documentation/BODAQS_Public_API_Contract_v0.md>)
- [analysis/Documentation/BODAQS_Session_Schema_v0_1.md](</c:/Users/benco/dev/BODAQS/analysis/Documentation/BODAQS_Session_Schema_v0_1.md>)
- [analysis/Documentation/BODAQS_Time_Handling_Contract_v0.md](</c:/Users/benco/dev/BODAQS/analysis/Documentation/BODAQS_Time_Handling_Contract_v0.md>)
- [analysis/Documentation/BODAQS_analysis_artifacts_specification_v0_2.md](</c:/Users/benco/dev/BODAQS/analysis/Documentation/BODAQS_analysis_artifacts_specification_v0_2.md>)

Tests:

- [analysis/tests/test_logger_sidecar.py](</c:/Users/benco/dev/BODAQS/analysis/tests/test_logger_sidecar.py>)

## Current FIT Config Shape

The preprocess config now supports a block like:

```json
{
  "fit_import": {
    "enabled": true,
    "fit_dir": "Garmin/FIT",
    "field_allowlist": [
      "position_lat",
      "position_long",
      "altitude",
      "enhanced_altitude",
      "speed",
      "enhanced_speed",
      "distance",
      "grade",
      "heading"
    ],
    "ambiguity_policy": "require_binding",
    "partial_overlap": "allow",
    "persist_raw_stream": true,
    "resample_to_primary": true,
    "resample_method": "linear",
    "raw_stream_name": "gps_fit",
    "bindings_path": "analysis/config/fit_bindings_v1.json"
  }
}
```

The bindings file shape is:

```json
{
  "schema": "bodaqs.fit_bindings",
  "version": 1,
  "bindings": []
}
```

## What the Backend Does Now

When `fit_import.enabled` is true and the session has an absolute time anchor:

- scans the configured FIT directory for overlapping `.fit` / `.FIT` files
- if one overlap exists, it auto-selects it
- if multiple overlaps exist:
  - `largest_overlap` and `latest_start` are supported
  - `require_binding` consults `fit_bindings_v1.json`
- loads Garmin `record` messages via `fitparse`
- converts selected fields into canonical BODAQS-style columns
- stores the raw stream in `session["stream_dfs"]["gps_fit"]`
- registers the stream as `kind == "intermittent"`
- resamples selected continuous fields onto `session["df"]["time_s"]`
- records FIT provenance in `session["source"]["aux_sources"]`

## Artifact Behavior

Canonical session artifacts now support:

- main dataframe at `session/df.parquet`
- main metadata at `session/meta.json`
- secondary streams at `session/streams/<stream_name>/df.parquet`
- secondary stream metadata at `session/streams/<stream_name>/meta.json`
- copied FIT files under `source_aux/`
- `aux_sources` entries in the session manifest

## Tests / Verification

Most recent verification state:

- `analysis/tests` passes: `38 passed`
- notebook JSON for the edited notebooks parses successfully
- current warnings are existing pandas warnings from `signal_legacy.py`, not from the FIT work

## Known Caveats

- `fitparse` is now required for FIT parsing. It was added to `requirements.txt`.
- `ipydatagrid` may be absent in some notebook environments. The preprocess file selector now falls back to a simpler widget rather than failing import.
- The FIT bindings editor exists as a helper module, but it is not yet fully embedded as a mandatory visible step in the main preprocessing notebook flow.
- Real-world validation with genuine Garmin FIT files is still needed.
- The logger firmware does not yet emit the sidecar JSON automatically.

## Sensible Next Steps

If resuming this task later, the most valuable next items are:

1. Run the preprocessing flow against one or more real Garmin FIT files.
2. Check actual Garmin field names/units and confirm the conversion assumptions.
3. Embed the FIT bindings editor into the main notebook UX if ambiguous matches are common.
4. Decide whether processed-file detection should explicitly include copied aux FIT hashes in any selector/cache logic beyond manifest scanning.
5. Implement firmware-side sidecar generation or a simpler CSV footer absolute-time fallback if desired.

## Practical Resume Notes

- Restart the Jupyter kernel after pulling these changes if notebook imports seem stale.
- If `ipydatagrid` is installed, the richer file grid will be used automatically.
- If it is not installed, the notebook should still work with the simpler selector fallback.
- For multi-match FIT sessions, populate `analysis/config/fit_bindings_v1.json` or use the bindings helper module.
