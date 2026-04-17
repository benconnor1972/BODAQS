# BODAQS Analysis Notebook Overview

This document summarizes the main notebooks in `analysis/` and explains what each one does in practice.

The focus is operational rather than aspirational:

- what the notebook is for
- the major steps it performs
- the inputs each step expects
- the outputs each step produces in memory
- any persisted artifacts or local state it writes
- the contracts and reference documents it relies on

The notebooks are listed in the working order requested for the overview.

## Shared context

The current notebook set falls into two broad groups:

- **Producer notebooks** write canonical analysis artifacts under `analysis/artifacts/`.
- **Consumer notebooks** discover and reuse those artifacts rather than recomputing them.

The canonical artifact model is documented in
[`BODAQS_analysis_artifacts_specification_v0_2.md`](./BODAQS_analysis_artifacts_specification_v0_2.md).
At a high level, producer notebooks write data under:

```text
analysis/artifacts/runs/<run_id>/sessions/<session_id>/
```

Important supporting state is also written outside the canonical artifact tree:

- local preprocess helper state in `.bodaqs_preprocess_last_dir.json` and `.bodaqs_preprocess_sha_cache.json`
- per-user entity-scope selection in `~/.bodaqs/entity_scope_selection_v1.json`
- per-user session-window bookmarks in `~/.bodaqs/bookmarks_v1.json`

## `bodaqs_batch_preprocessing_pipeline.ipynb`

Notebook: [`bodaqs_batch_preprocessing_pipeline.ipynb`](../bodaqs_batch_preprocessing_pipeline.ipynb)

**Role**

This is the main batch ingestion and preprocessing notebook. It turns one or more raw logger CSV files into canonical BODAQS session, event, and metric artifacts that downstream notebooks can consume.

### Step 1. Select input CSV files

- **Inputs:** a directory of raw logger CSV files and the existing `analysis/artifacts/` tree.
- **Outputs:** the selected file list (`CSV_FILES`) and a visible file-selection UI.
- **Persisted artifacts:** no canonical analysis artifacts yet. The selector does update local helper files:
  - `.bodaqs_preprocess_last_dir.json`
  - `.bodaqs_preprocess_sha_cache.json`
- **Contracts / documentation:** the selector behavior is aligned with the artifact discovery model in [`BODAQS_analysis_artifacts_specification_v0_2.md`](./BODAQS_analysis_artifacts_specification_v0_2.md).

### Step 2. Load each CSV and canonicalize signals for preview

- **Inputs:** each selected CSV path.
- **Outputs:** an in-memory preview of each session via `load_and_canonicalize(...)`, including:
  - canonicalized session dataframe and metadata
  - `session["meta"]["signals"]`
  - the union of detected displacement channels (`disp_cols_all`)
  - optional reporting of unclassified numeric columns
- **Persisted artifacts:** none.
- **Contracts / documentation:**
  - [`BODAQS_Session_Schema_v0_1.md`](./BODAQS_Session_Schema_v0_1.md)
  - [`BODAQS_Minimum_Signal_Registry_Semantics_v0_1_1.md`](./BODAQS_Minimum_Signal_Registry_Semantics_v0_1_1.md)
  - [`MTB_Logger_CSV_JSON_Interchange_Contract_v0_1_draft.md`](./MTB_Logger_CSV_JSON_Interchange_Contract_v0_1_draft.md)

### Step 3. Collect preprocessing and event-detection configuration

- **Inputs:** the discovered displacement channels plus user-entered configuration:
  - schema path
  - normalization ranges
  - zeroing settings
  - activity-mask settings
  - clipping and smoothing settings
  - ingestion mode
  - whether to prompt for descriptions
- **Outputs:** a validated config dict suitable for `run_macro(...)`.
- **Persisted artifacts:** none.
- **Contracts / documentation:**
  - [`BODAQS_Public_API_Contract_v0.md`](./BODAQS_Public_API_Contract_v0.md)
  - [`BODAQS_event_schema_specification_v0_1_2.md`](./BODAQS_event_schema_specification_v0_1_2.md)
  - [`BODAQS_Time_Handling_Contract_v0.md`](./BODAQS_Time_Handling_Contract_v0.md)

### Step 4. Run the macro pipeline for each selected session

- **Inputs:** one CSV file plus the validated preprocessing config and event schema.
- **Outputs:** the `run_macro(...)` result per session, including:
  - `session`
  - `schema`
  - `events`
  - `segments`
  - `metrics`
- **Persisted artifacts:** none at the moment this step returns; persistence happens in the next step.
- **Contracts / documentation:**
  - [`BODAQS_Public_API_Contract_v0.md`](./BODAQS_Public_API_Contract_v0.md)
  - [`BODAQS_Event_Table_Contract_v0_1_3_draft.md`](./BODAQS_Event_Table_Contract_v0_1_3_draft.md)
  - [`BODAQS_Metrics_Table_Contract_v0_2.md`](./BODAQS_Metrics_Table_Contract_v0_2.md)
  - [`BODAQS_Time_Handling_Contract_v0.md`](./BODAQS_Time_Handling_Contract_v0.md)

### Step 5. Persist canonical artifacts for the batch run

- **Inputs:** the processed session dataframe and metadata, raw input CSV, detected events, computed metrics, and the schema path used for detection.
- **Outputs:** a complete run folder under `analysis/artifacts/runs/<run_id>/`.
- **Persisted artifacts:**
  - `runs/<run_id>/manifest.json`
  - `runs/<run_id>/sessions/<session_id>/manifest.json`
  - `runs/<run_id>/sessions/<session_id>/source/input.csv`
  - `runs/<run_id>/sessions/<session_id>/source/input.sha256`
  - `runs/<run_id>/sessions/<session_id>/session/df.parquet`
  - `runs/<run_id>/sessions/<session_id>/session/meta.json`
  - `runs/<run_id>/sessions/<session_id>/events/<schema_id>/events.parquet`
  - `runs/<run_id>/sessions/<session_id>/events/<schema_id>/schema.yaml`
  - `runs/<run_id>/sessions/<session_id>/metrics/<schema_id>/metrics.parquet`
- **Contracts / documentation:**
  - [`BODAQS_analysis_artifacts_specification_v0_2.md`](./BODAQS_analysis_artifacts_specification_v0_2.md)
  - [`BODAQS_Event_Table_Contract_v0_1_3_draft.md`](./BODAQS_Event_Table_Contract_v0_1_3_draft.md)
  - [`BODAQS_Metrics_Table_Contract_v0_2.md`](./BODAQS_Metrics_Table_Contract_v0_2.md)

### Step 6. Optionally annotate the run and sessions with descriptions

- **Inputs:** operator-entered run and session descriptions.
- **Outputs:** updated manifest metadata.
- **Persisted artifacts:** the existing run and session manifests are updated in place with `description` fields.
- **Contracts / documentation:** [`BODAQS_analysis_artifacts_specification_v0_2.md`](./BODAQS_analysis_artifacts_specification_v0_2.md)

## `BODAQS_library_manager.ipynb`

Notebook: [`BODAQS_library_manager.ipynb`](../BODAQS_library_manager.ipynb)

**Role**

This notebook is the library-facing metadata management surface. It does not run the analysis pipeline itself; instead, it lets you browse existing sessions, edit descriptions, manage canonical session notes, and manage canonical aggregations.

### Step 1. Build and browse the session catalog

- **Inputs:** the existing `analysis/artifacts/` tree and the available session-note templates under `analysis/templates/session_note_templates/`.
- **Outputs:** a catalog of sessions with run metadata, session metadata, and note projection status.
- **Persisted artifacts:** none.
- **Contracts / documentation:**
  - [`BODAQS_analysis_artifacts_specification_v0_2.md`](./BODAQS_analysis_artifacts_specification_v0_2.md)
  - [`BODAQS_session_notes_and_catalog_contract_draft.md`](./BODAQS_session_notes_and_catalog_contract_draft.md)
  - [`../templates/session_note_templates/README.md`](../templates/session_note_templates/README.md)

### Step 2. Edit run and session descriptions

- **Inputs:** the selected run/session and the description text entered in the UI.
- **Outputs:** updated description fields visible in the catalog and manifests.
- **Persisted artifacts:**
  - `runs/<run_id>/manifest.json`
  - `runs/<run_id>/sessions/<session_id>/manifest.json`
- **Contracts / documentation:**
  - [`BODAQS_analysis_artifacts_specification_v0_2.md`](./BODAQS_analysis_artifacts_specification_v0_2.md)

### Step 3. Load, create, and save canonical session notes

- **Inputs:** the selected session, a chosen note template, structured field values, custom JSON values, and free-text notes.
- **Outputs:** validated in-memory `SessionNoteDocument` instances and updated catalog projection status.
- **Persisted artifacts:**
  - `runs/<run_id>/sessions/<session_id>/annotations/session_notes.json`
- **Contracts / documentation:**
  - [`BODAQS_session_notes_and_catalog_contract_draft.md`](./BODAQS_session_notes_and_catalog_contract_draft.md)
  - [`../templates/session_note_templates/README.md`](../templates/session_note_templates/README.md)

### Step 4. Create, update, and delete canonical aggregations

- **Inputs:** selected sessions, aggregation title, optional note, and registry/schema policies.
- **Outputs:** canonical aggregation definitions that can be reused by selector-driven consumer notebooks.
- **Persisted artifacts:**
  - `artifacts/library/aggregations_v1.json`
- **Contracts / documentation:**
  - [`BODAQS_aggregation_library_contract_draft.md`](./BODAQS_aggregation_library_contract_draft.md)
  - [`BODAQS_session_selector_consumer_widgets_contract.md`](./BODAQS_session_selector_consumer_widgets_contract.md)

## `BODAQS_simple_suspension_metrics.ipynb`

Notebook: [`BODAQS_simple_suspension_metrics.ipynb`](../BODAQS_simple_suspension_metrics.ipynb)

**Role**

This notebook is a dashboard-style consumer of previously processed artifacts. It builds a reusable session-selection scope, then renders front/rear suspension summaries over that scope.

### Step 1. Build a live selection scope

- **Inputs:** canonical analysis artifacts under `analysis/artifacts/` plus any saved canonical aggregations.
- **Outputs:** a selector handle with:
  - selected entities
  - expanded physical sessions
  - `session_key -> (run_id, session_id)` mapping
  - `events_index_df`
- **Persisted artifacts:** no canonical analysis artifacts. By default, the selector may persist per-user scope state to:
  - `~/.bodaqs/entity_scope_selection_v1.json`
- **Contracts / documentation:**
  - [`BODAQS_session_selector_consumer_widgets_contract.md`](./BODAQS_session_selector_consumer_widgets_contract.md)
  - [`BODAQS_aggregation_library_contract_draft.md`](./BODAQS_aggregation_library_contract_draft.md)

### Step 2. Render the simple suspension metrics dashboard

- **Inputs:** the selector handle, selected sessions' `df/meta`, event tables, metric tables, and session descriptions from manifests.
- **Outputs:** a multi-panel dashboard with:
  - front and rear displacement views
  - front and rear velocity views
  - front and rear event summaries
  - a normalized-vs-engineering-units toggle
- **Persisted artifacts:** none in the canonical artifact tree.
- **Contracts / documentation:**
  - [`BODAQS_Metrics_Table_Contract_v0_2.md`](./BODAQS_Metrics_Table_Contract_v0_2.md)
  - [`BODAQS_Event_Table_Contract_v0_1_3_draft.md`](./BODAQS_Event_Table_Contract_v0_1_3_draft.md)
  - [`BODAQS_Minimum_Signal_Registry_Semantics_v0_1_1.md`](./BODAQS_Minimum_Signal_Registry_Semantics_v0_1_1.md)

### Step 3. Rebuild the dashboard when scope changes

- **Inputs:** selector refresh events and changes to the engineering-units toggle.
- **Outputs:** refreshed dashboard tiles driven by the current selected scope.
- **Persisted artifacts:** none beyond the selector's optional per-user autosave behavior.
- **Contracts / documentation:** [`BODAQS_session_selector_consumer_widgets_contract.md`](./BODAQS_session_selector_consumer_widgets_contract.md)

## `BODAQS_simple_suspension_metrics_persisted_scope.ipynb`

Notebook: [`BODAQS_simple_suspension_metrics_persisted_scope.ipynb`](../BODAQS_simple_suspension_metrics_persisted_scope.ipynb)

**Role**

This is the persisted-scope variant of the same dashboard. It is best understood as a cross-notebook consumer: another notebook establishes and saves the selection, and this notebook reuses that saved scope without rebuilding the live selector UI.

### Step 1. Load the persisted selection

- **Inputs:** canonical analysis artifacts, canonical aggregations, and the per-user saved scope file.
- **Outputs:** a selector-compatible handle with the same getters expected by downstream dashboards and widget rebuilders.
- **Persisted artifacts:** none written by default. It reads:
  - `~/.bodaqs/entity_scope_selection_v1.json`
- **Contracts / documentation:** [`BODAQS_session_selector_consumer_widgets_contract.md`](./BODAQS_session_selector_consumer_widgets_contract.md)

### Step 2. Render the same simple suspension metrics dashboard

- **Inputs:** the loaded persisted scope plus the same session/event/metric artifacts used by the non-persisted notebook.
- **Outputs:** the same front/rear displacement, velocity, and event-summary dashboard.
- **Persisted artifacts:** none.
- **Contracts / documentation:** the same contracts as the main suspension dashboard:
  - [`BODAQS_session_selector_consumer_widgets_contract.md`](./BODAQS_session_selector_consumer_widgets_contract.md)
  - [`BODAQS_Metrics_Table_Contract_v0_2.md`](./BODAQS_Metrics_Table_Contract_v0_2.md)
  - [`BODAQS_Event_Table_Contract_v0_1_3_draft.md`](./BODAQS_Event_Table_Contract_v0_1_3_draft.md)

## `bodaqs_widget_test_notebook.ipynb`

Notebook: [`bodaqs_widget_test_notebook.ipynb`](../bodaqs_widget_test_notebook.ipynb)

**Role**

This is the broad smoke-test and exploratory integration notebook for the generic widget layer. It is the most complete consumer-notebook example in the current analysis folder.

### Step 1. Open the aggregation editor

- **Inputs:** the existing artifact library and current session inventory.
- **Outputs:** a standalone aggregation editor UI.
- **Persisted artifacts:**
  - `artifacts/library/aggregations_v1.json`
- **Contracts / documentation:**
  - [`BODAQS_aggregation_library_contract_draft.md`](./BODAQS_aggregation_library_contract_draft.md)
  - [`BODAQS_session_selector_consumer_widgets_contract.md`](./BODAQS_session_selector_consumer_widgets_contract.md)

### Step 2. Open the session selector and schema context

- **Inputs:** `analysis/artifacts/` and `event schema/event_schema.yaml`.
- **Outputs:** a selector handle, schema object, `events_index_df`, `key_to_ref`, and a `session_loader`.
- **Persisted artifacts:** no canonical analysis artifacts. The selector may persist per-user scope state to:
  - `~/.bodaqs/entity_scope_selection_v1.json`
- **Contracts / documentation:**
  - [`BODAQS_session_selector_consumer_widgets_contract.md`](./BODAQS_session_selector_consumer_widgets_contract.md)
  - [`BODAQS_event_schema_specification_v0_1_2.md`](./BODAQS_event_schema_specification_v0_1_2.md)

### Step 3. Exercise the signal histogram widget

- **Inputs:** the current selector scope and per-session `df/meta`.
- **Outputs:** an interactive signal histogram or CDF view.
- **Persisted artifacts:** none.
- **Contracts / documentation:**
  - [`BODAQS_session_selector_consumer_widgets_contract.md`](./BODAQS_session_selector_consumer_widgets_contract.md)
  - [`BODAQS_Minimum_Signal_Registry_Semantics_v0_1_1.md`](./BODAQS_Minimum_Signal_Registry_Semantics_v0_1_1.md)

### Step 4. Exercise the event browser widget

- **Inputs:** the current selector scope, selected-session events, selected-session metrics, the schema definition, and per-session `df/meta`.
- **Outputs:** an interactive event inspection surface that joins event rows to metrics where possible and resolves sensor semantics through the schema and signal registry.
- **Persisted artifacts:** none.
- **Contracts / documentation:**
  - [`BODAQS_Event_Table_Contract_v0_1_3_draft.md`](./BODAQS_Event_Table_Contract_v0_1_3_draft.md)
  - [`BODAQS_Metrics_Table_Contract_v0_2.md`](./BODAQS_Metrics_Table_Contract_v0_2.md)
  - [`BODAQS_event_schema_specification_v0_1_2.md`](./BODAQS_event_schema_specification_v0_1_2.md)

### Step 5. Exercise the metric scatter and metric histogram widgets

- **Inputs:** selected-session event tables, selected-session metric tables, the shared schema, and per-session registries resolved via the session loader.
- **Outputs:** interactive metric comparison views across entities, event types, and sensors.
- **Persisted artifacts:** none.
- **Contracts / documentation:**
  - [`BODAQS_Metrics_Table_Contract_v0_2.md`](./BODAQS_Metrics_Table_Contract_v0_2.md)
  - [`BODAQS_Event_Table_Contract_v0_1_3_draft.md`](./BODAQS_Event_Table_Contract_v0_1_3_draft.md)
  - [`BODAQS_session_selector_consumer_widgets_contract.md`](./BODAQS_session_selector_consumer_widgets_contract.md)

### Step 6. Exercise the session window browser and refresh wiring

- **Inputs:** the current selector scope, per-session events and metrics, and the selected session dataframe.
- **Outputs:** a single-session browser with event overlays, detail plots, and widget rebuild-on-selection-change behavior.
- **Persisted artifacts:**
  - per-user bookmarks in `~/.bodaqs/bookmarks_v1.json`
  - optional per-user selector scope autosave in `~/.bodaqs/entity_scope_selection_v1.json`
- **Contracts / documentation:**
  - [`BODAQS_session_selector_consumer_widgets_contract.md`](./BODAQS_session_selector_consumer_widgets_contract.md)
  - [`bodaqs_bookmarks_spec_v1.md`](./bodaqs_bookmarks_spec_v1.md)

## `bodaqs_session_test_notebook.ipynb`

Notebook: [`bodaqs_session_test_notebook.ipynb`](../bodaqs_session_test_notebook.ipynb)

**Role**

This is a narrower smoke-test notebook focused on the session window browser only. It is useful when you want to validate or iterate on that widget without the extra surface area of the full widget test notebook.

### Step 1. Build the selector and schema context

- **Inputs:** `analysis/artifacts/` and `event schema/event_schema.yaml`.
- **Outputs:** the selector handle, schema object, `events_index_df`, `key_to_ref`, and `session_loader`.
- **Persisted artifacts:** no canonical analysis artifacts. The selector may autosave per-user scope state to:
  - `~/.bodaqs/entity_scope_selection_v1.json`
- **Contracts / documentation:** [`BODAQS_session_selector_consumer_widgets_contract.md`](./BODAQS_session_selector_consumer_widgets_contract.md)

### Step 2. Build the session window browser

- **Inputs:** the selected scope plus the corresponding session/event/metric artifacts.
- **Outputs:** the session-window browser UI for a single active session at a time.
- **Persisted artifacts:** none in the canonical artifact tree.
- **Contracts / documentation:**
  - [`BODAQS_session_selector_consumer_widgets_contract.md`](./BODAQS_session_selector_consumer_widgets_contract.md)
  - [`bodaqs_bookmarks_spec_v1.md`](./bodaqs_bookmarks_spec_v1.md)

### Step 3. Attach rebuild-on-selection-change behavior

- **Inputs:** selector change notifications.
- **Outputs:** automatic browser rebuilds when the selection changes.
- **Persisted artifacts:**
  - per-user bookmarks in `~/.bodaqs/bookmarks_v1.json` when bookmarks are saved
- **Contracts / documentation:** [`BODAQS_session_selector_consumer_widgets_contract.md`](./BODAQS_session_selector_consumer_widgets_contract.md)

## `bodaqs_event_schema_test_harness.ipynb`

Notebook: [`bodaqs_event_schema_test_harness.ipynb`](../bodaqs_event_schema_test_harness.ipynb)

**Role**

This notebook is the single-file schema-tuning harness. It is designed for fast iteration on event-schema YAML against one representative CSV rather than for full-batch production preprocessing.

### Step 1. Set the single-session test inputs

- **Inputs:** explicit notebook variables for:
  - `CSV_PATH`
  - `SCHEMA_PATH`
  - `NORMALIZE_RANGES`
  - zeroing, smoothing, clipping, activity-mask, sample-rate, and ingestion settings
- **Outputs:** a fully explicit test configuration for one CSV and one schema revision.
- **Persisted artifacts:** none yet.
- **Contracts / documentation:**
  - [`BODAQS_event_schema_specification_v0_1_2.md`](./BODAQS_event_schema_specification_v0_1_2.md)
  - [`BODAQS_Public_API_Contract_v0.md`](./BODAQS_Public_API_Contract_v0.md)

### Step 2. Run preprocessing for one session and persist the results

- **Inputs:** the configured CSV path, schema path, normalization ranges, and preprocessing parameters.
- **Outputs:** in-memory `session`, `schema`, `events_df`, `metrics_df`, `run_id`, and `session_key`, plus a freshly written run folder.
- **Persisted artifacts:** the same canonical artifacts written by the batch preprocessing notebook, but for a single session:
  - `runs/<run_id>/manifest.json`
  - `runs/<run_id>/sessions/<session_id>/manifest.json`
  - `runs/<run_id>/sessions/<session_id>/source/input.csv`
  - `runs/<run_id>/sessions/<session_id>/source/input.sha256`
  - `runs/<run_id>/sessions/<session_id>/session/df.parquet`
  - `runs/<run_id>/sessions/<session_id>/session/meta.json`
  - `runs/<run_id>/sessions/<session_id>/events/<schema_id>/events.parquet`
  - `runs/<run_id>/sessions/<session_id>/events/<schema_id>/schema.yaml`
  - `runs/<run_id>/sessions/<session_id>/metrics/<schema_id>/metrics.parquet`
- **Contracts / documentation:**
  - [`BODAQS_analysis_artifacts_specification_v0_2.md`](./BODAQS_analysis_artifacts_specification_v0_2.md)
  - [`BODAQS_Event_Table_Contract_v0_1_3_draft.md`](./BODAQS_Event_Table_Contract_v0_1_3_draft.md)
  - [`BODAQS_Metrics_Table_Contract_v0_2.md`](./BODAQS_Metrics_Table_Contract_v0_2.md)

### Step 3. Inspect detections in the event browser

- **Inputs:** the freshly written artifacts, the in-memory schema object, and the derived single-session loader mapping.
- **Outputs:** an event browser configured against the latest processed single-session artifacts.
- **Persisted artifacts:** none beyond the preprocessing artifacts already written.
- **Contracts / documentation:**
  - [`BODAQS_event_schema_specification_v0_1_2.md`](./BODAQS_event_schema_specification_v0_1_2.md)
  - [`BODAQS_session_selector_consumer_widgets_contract.md`](./BODAQS_session_selector_consumer_widgets_contract.md)

### Step 4. Iterate on the schema revision

- **Inputs:** edits to the schema YAML and reruns of the preprocessing/browser cells.
- **Outputs:** repeatable schema-tuning feedback against a known CSV.
- **Persisted artifacts:** each rerun creates a fresh `run_id` under `analysis/artifacts/runs/`; this notebook intentionally does not reuse the preprocess selector SHA cache.
- **Contracts / documentation:** [`BODAQS_analysis_artifacts_specification_v0_2.md`](./BODAQS_analysis_artifacts_specification_v0_2.md)

## Summary

In the current workflow, the notebooks fit together as follows:

1. Use [`bodaqs_batch_preprocessing_pipeline.ipynb`](../bodaqs_batch_preprocessing_pipeline.ipynb) or [`bodaqs_event_schema_test_harness.ipynb`](../bodaqs_event_schema_test_harness.ipynb) to produce canonical artifacts.
2. Use [`BODAQS_library_manager.ipynb`](../BODAQS_library_manager.ipynb) to curate descriptions, notes, and aggregations around those artifacts.
3. Use the dashboard and widget notebooks to consume the artifact library:
   - [`BODAQS_simple_suspension_metrics.ipynb`](../BODAQS_simple_suspension_metrics.ipynb)
   - [`BODAQS_simple_suspension_metrics_persisted_scope.ipynb`](../BODAQS_simple_suspension_metrics_persisted_scope.ipynb)
   - [`bodaqs_widget_test_notebook.ipynb`](../bodaqs_widget_test_notebook.ipynb)
   - [`bodaqs_session_test_notebook.ipynb`](../bodaqs_session_test_notebook.ipynb)

That division is one of the clearer design choices in the current analysis folder: artifacts are the stable handoff between notebooks, while local per-user files hold notebook convenience state such as selections and bookmarks.
