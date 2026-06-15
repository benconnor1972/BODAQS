# BODAQS Analysis Notebooks

Status: working structure for notebook remediation.

This directory separates notebooks by how their analysis scope is chosen.

## Persisted Scope Notebooks

Location:

```text
persisted_scope/
```

Persisted-scope notebooks load an already-saved Study Set or other persisted
analysis scope. They do not provide their own session selector. They are the
preferred direction for notebooks that should interoperate with the web app.

Naming convention:

```text
bodaqs_<workflow>_study_set.ipynb
```

Use this path when the user starts from a Study Set created in the web app or
another library-aware tool.

Current persisted-scope consumers:

- `persisted_scope/bodaqs_data_explorer_study_set.ipynb`
- `persisted_scope/bodaqs_session_browser_study_set.ipynb`
- `persisted_scope/bodaqs_simple_suspension_metrics_study_set.ipynb`

## Self-scoped Notebooks

Location:

```text
self_scoped/
```

Self-scoped notebooks include their own in-notebook selector or scope builder.
They are useful for ad-hoc exploration, but they should not be the canonical
path for saved analysis scopes.

Naming convention:

```text
bodaqs_<workflow>_self_scoped.ipynb
```

## Legacy Root-level Notebooks

The existing root-level notebooks are left in place during remediation so
existing workflows are not broken. As notebooks are remediated, create clean
copies under `persisted_scope/` or `self_scoped/` rather than mixing both scope
models in one notebook.

## Aggregation Deprecation

Legacy aggregation compatibility is deprecated for new notebook work. Recreate
old aggregations as Study Sets instead of extending the aggregation model.
