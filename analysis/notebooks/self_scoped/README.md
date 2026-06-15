# Self-scoped Notebooks

Remediated notebooks here include their own in-notebook session selector or
single-session target configuration.

Prefer persisted-scope notebooks for workflows that should open Study Sets
created by the web application.

Current self-scoped notebooks:

- `bodaqs_data_explorer_self_scoped.ipynb`
- `bodaqs_session_browser_self_scoped.ipynb`
- `bodaqs_simple_suspension_metrics_self_scoped.ipynb`
- `bodaqs_data_syn_bike_export_self_scoped.ipynb`
- `bodaqs_event_schema_test_harness_self_scoped.ipynb`

Conventions:

- Configure `LIBRARIES_ROOT` and `LIBRARY_ID` in the first code cell.
- Session selectors show physical sessions only; legacy aggregations are not
  exposed.
- Schema-driven notebooks validate that selected sessions use one matching
  frozen event schema, with central-schema fallback warnings for old artifacts.
- The data.syn.bike export notebook has an explicit `OUTPUT_DIR`.
