# BODAQS Analysis Package 0.3.0 Release Notes Draft

Status: draft  
Release date: TBD  
Comparison base: git tag `analysis-0.2.0`

BODAQS Analysis Package `0.3.0` is a local-first analysis and library workflow
release. It keeps the existing BODAQS artifact contract as the central handoff
between notebooks, while adding archive-based session input, improved logger
metadata handling, calibrated raw-signal materialisation, draft session-note
state, and improved data.syn.bike export support.

This package is intended to include:

- `bodaqs_batch_preprocessor.ipynb`
- `bodaqs_session_browser.ipynb`
- `bodaqs_data_explorer.ipynb`
- `bodaqs_data_syn_bike_export.ipynb`
- `bodaqs_simple_suspension_metrics.ipynb`
- `bodaqs_one_step_suspension_metrics.ipynb`
- `BODAQS_library_manager.ipynb`
- the full `bodaqs_analysis` module package

## Highlights

- Session ZIP archives are now first-class analysis inputs alongside legacy CSV
  files.
- Batch preprocessing and one-step suspension metrics workflows can process
  archive inputs.
- Processed-input detection now uses stable source identities, including raw
  session identity for CSV+metadata archives.
- FIT enrichment remains best-effort and can use configured FIT directories
  without blocking otherwise successful preprocessing.
- data.syn.bike export support now includes manual-settings helper generation
  and calibrated raw-to-full-ADC scaling.
- Session notes now support draft state and source provenance.
- The library manager can display draft-note state and clear the draft flag
  when a user saves a note.
- Logger metadata handling now prefers `started_at_utc` when available.
- Logger raw linear calibrations can materialize engineering-unit signals when
  only raw count channels are present.
- Top-level `bodaqs_analysis` exports are now lazy-loaded, reducing import
  side effects from optional feature modules.

## Included Notebooks

### Batch Pre-processor

`bodaqs_batch_preprocessor.ipynb` remains the primary notebook for turning raw
logger sessions into canonical BODAQS artifacts.

Changes since `0.2.0`:

- Accepts completed session ZIP archives as inputs in addition to legacy CSV
  files.
- Uses `prepare_session_input(...)` and the session-archive contract to extract
  archive CSV/JSON pairs safely.
- Hides already-processed archive inputs using source identity, not only raw CSV
  SHA-256.
- Carries archive provenance into persisted source manifests, including archive
  filename, archive hash, member names, member hashes, and raw session identity.
- Continues to support preprocess profiles, bike profiles, event schemas, FIT
  enrichment, run descriptions, and session descriptions.

### Session Browser

`bodaqs_session_browser.ipynb` is included as the focused single-session browser
for already-processed library artifacts.

There are no major functional changes to call out since `0.2.0`; it benefits
from the shared package-level artifact, event, metric, and widget modules.

### Data Explorer

`bodaqs_data_explorer.ipynb` remains the broader interactive exploration
notebook for processed libraries.

It continues to provide:

- session selection
- signal histogram browsing
- event browsing
- metric scatter plots
- metric histograms

The notebook benefits from the shared runtime-settings and selector modules,
plus the updated artifact/session-note model underneath.

### data.syn.bike Export

`bodaqs_data_syn_bike_export.ipynb` is included as the notebook workflow for
exporting processed BODAQS sessions into a data.syn.bike-compatible CSV shape.

Changes since `0.2.0`:

- Uses the updated data.syn.bike exporter module.
- Supports calibrated raw-to-full-ADC scaling for logger raw channels.
- Supports ADC bit-count settings in the export configuration.
- Produces helper text for the manual data.syn.bike settings that are not
  carried in the CSV itself.
- Derives bike/profile helper values such as front travel, rear shock travel,
  rear wheel travel, max shock, and average leverage rate where available.

### Simple Suspension Metrics

`bodaqs_simple_suspension_metrics.ipynb` is now a slimmer consumer notebook
built around the shared suspension dashboard and selector stack.

Changes since `0.2.0`:

- Reduces duplicated notebook-local dashboard code.
- Uses the shared simple-suspension dashboard implementation.
- Keeps front/rear suspension selectors explicit in the notebook so they can be
  adjusted without editing package code.
- Assumes input sessions have already been preprocessed into a BODAQS library.

### One-step Suspension Metrics

`bodaqs_one_step_suspension_metrics.ipynb` remains the combined workflow for
preprocessing and immediately browsing suspension metrics.

Changes since `0.2.0`:

- Accepts session ZIP archives as well as legacy CSV inputs.
- Uses the same archive preparation and source-identity logic as the batch
  preprocessor.
- Reuses shared artifact-writing and dashboard code rather than maintaining a
  separate copy of the full dashboard workflow.
- Supports the same preprocess-profile, bike-profile, FIT, event-schema, and
  description-prompt settings expected by the batch workflow.

### Library Manager

`BODAQS_library_manager.ipynb` remains the notebook UI for curating processed
libraries.

Changes since `0.2.0`:

- Displays whether a session note is a draft or a saved/reviewed note.
- Loads note templates from the library-local template store, with fallback to
  packaged/default templates.
- Clears the draft flag when a user saves a note from the library manager.
- Surfaces note-source provenance in the catalog model where available.

## Package Module Changes

### Session Archive Support

New module:

- `bodaqs_analysis.session_archive`

The module defines the session archive contract used by notebooks and import
tools:

- archive input suffix is `.zip`
- archive must contain exactly one root `.csv` file and one root `.json` file
- CSV and JSON members must share the same stem
- nested paths and unsafe archive member paths are rejected
- archive member hashes and raw session identity are calculated
- archive inputs can be prepared through a context-managed extraction helper

Existing CSV workflows remain supported.

### Session Notes

Changed module:

- `bodaqs_analysis.session_notes`

Session notes now support:

- `draft` flag on note documents
- `source_context` provenance on note documents
- library-local note-template stores
- fallback to default packaged templates
- catalog columns for note draft state, origin, bike profile id, and setup
  preset id

### data.syn.bike Export

Changed module:

- `bodaqs_analysis.exporters.data_syn_bike`

Changes since `0.2.0`:

- Adds `adc_bit_count` to the export configuration.
- Adds raw scaling modes, including calibrated full-scale raw-count mapping.
- Adds `raw_full_scale_by_end` configuration for front/rear raw count scaling.
- Adds clipping to ADC range.
- Adds manual-settings helper generation for data.syn.bike.
- Adds bike-profile-derived values for helper text, including front travel,
  rear shock travel, rear wheel travel, max shock, and average leverage rate.
- Adds export summary metadata for raw scaling and ADC settings.

### Pipeline And Metadata Handling

Changed module:

- `bodaqs_analysis.pipeline`

Changes since `0.2.0`:

- Prefers `session.started_at_utc` from logger metadata when available.
- Keeps local start time as fallback/context rather than overriding UTC.
- Can materialize engineering-unit displacement signals from logger raw count
  channels when linear calibration metadata is available and no equivalent
  engineering-unit signal already exists.
- Carries materialization diagnostics in QC metadata.
- Integrates archive and FIT use cases while preserving the existing
  `preprocess_session(...)` artifact contract.

### Public Package Exports

Changed module:

- `bodaqs_analysis.__init__`

The top-level package now uses lazy exports. Existing high-level imports remain
available, while heavier optional submodules are not imported until their
symbols are requested.

This reduces incidental dependency loading for notebook users who only need the
core analysis pipeline.

## Configuration And Examples

New log-metadata example:

- `analysis/config/log_metadata_examples/syn_bike_raw_generic_log_metadata.json`

## Tests

New or expanded tests cover:

- session archive identity and validation
- archive-aware processed-input detection
- preprocessing archive inputs through the existing artifact writer
- data.syn.bike export scaling and helper text
- session-note draft/catalog behavior
- logger sidecar metadata handling

## Compatibility Notes

- Existing CSV-based preprocessing workflows remain supported.
- Existing BODAQS artifact readers should continue to work with core run and
  session artifacts.
- New manifests may contain additional source provenance, archive import,
  data.syn.bike export, and session-note metadata.
- Archive inputs require a strict two-file root archive: one CSV and one JSON
  with matching stems.
- Source identity for archive inputs is based on the CSV+metadata pair, not
  only the outer ZIP hash.
- data.syn.bike exports are optional library-side convenience outputs and are
  not part of the canonical BODAQS artifact contract.
- Draft notes remain drafts until reviewed/saved in the library manager.

## Known Limitations

- This is a development release of the analysis package.
- FIT enrichment is best-effort and should not be treated as required for a
  successful import.
- data.syn.bike helper files still require the user to enter settings manually
  in data.syn.bike.
- Old processed sessions are not automatically backfilled for draft notes or
  data.syn.bike outputs.

## Suggested Validation Checklist

Package checks:

- Install dependencies from `requirements.txt` in a clean environment.
- Confirm `import bodaqs_analysis` succeeds.
- Confirm lazy top-level imports still expose the expected public symbols.

Notebook checks:

- Open each included notebook in JupyterLab.
- Run the session browser against an existing artifact library.
- Run the data explorer against an existing artifact library.
- Run the data.syn.bike export notebook against an existing processed session.
- Run simple suspension metrics against an existing artifact library.
- Run one-step suspension metrics against one CSV and one ZIP archive.
- Run the batch preprocessor against a mixed folder of ZIP archives and legacy
  CSV files.
- Run the library manager and confirm draft-note state appears in the catalog.

Pipeline checks:

- Process a firmware `0.3.0` ZIP archive containing CSV+JSON metadata.
- Confirm archive provenance appears in the session manifest.
- Confirm `started_at_utc` is preferred when present in log metadata.
- Confirm a raw-count-only session with valid linear calibration metadata
  materializes compatible engineering-unit displacement signals.
- Confirm event detection and metrics still write under the selected schema id.

Optional-output checks:

- Enable FIT import and confirm a matching FIT file enriches the processed
  session without moving or deleting the FIT file.
- Confirm a FIT parse/match failure records a warning and does not block import.
- Run the data.syn.bike export helper and confirm CSV/helper/manifest files are
  written.
- Open a session with a draft note and confirm the library manager displays the
  draft state.
- Save that note in the library manager and confirm it becomes a reviewed/saved
  note.
