# BODAQS JupyterLab consumer widgets contract
*(Session selector outputs + common consumer-widget pattern)*

This document defines the **minimal, stable interface** between:

- a **session selector** (UI that chooses sessions across runs), and
- downstream **consumer widgets** (event browser, signal histogram, metric scatter, etc.)

The goal is that notebooks stay **thin**, while widgets remain **reusable** and operate on the same
selector outputs and loader contracts.

---

## Typed contracts module

Concrete type contracts are now drafted in:

- `analysis/bodaqs_analysis/widgets/contracts.py`

Key exported contracts/signatures (entity-aware):

```python
SessionKey = str
SessionRef = tuple[str, str]  # (run_id, session_id)
KeyToRef = Mapping[SessionKey, SessionRef]
EntityKind = Literal["session", "aggregation"]
EventSchemaPolicy = RegistryPolicy

@dataclass(frozen=True)
class SelectionSnapshot:
    key_to_ref: dict[str, tuple[str, str]]
    events_index_df: pd.DataFrame

@dataclass(frozen=True)
class AggregationDefinition:
    aggregation_key: str
    title: str
    member_session_keys: tuple[str, ...]
    registry_policy: RegistryPolicy
    event_schema_policy: EventSchemaPolicy
    created_at_utc: str
    updated_at_utc: str
    note: str | None

@dataclass(frozen=True)
class ScopeEntity:
    entity_key: str
    kind: EntityKind
    label: str
    member_session_keys: tuple[str, ...]

@dataclass(frozen=True)
class EntitySelectionSnapshot:
    selected_entities: list[ScopeEntity]
    entity_to_effective_members: dict[str, list[str]]
    expanded_session_keys: list[str]
    key_to_ref: dict[str, tuple[str, str]]
    events_index_df: pd.DataFrame

@dataclass(frozen=True)
class PersistedEntityScopeSelection:
    artifacts_root: str
    saved_at_utc: str
    selected_entity_keys: tuple[str, ...]
    selected_entity_kinds: dict[str, EntityKind]
    selected_labels: dict[str, str]

@dataclass(frozen=True)
class PersistedEntityScopeLoadResult:
    snapshot: EntitySelectionSnapshot
    warnings: list[str]
    source: PersistedEntityScopeSelection

class SessionLoader(Protocol):
    def __call__(self, session_key: str) -> SessionArtifacts: ...

class SessionSelectorCoreHandle(TypedDict):
    ui: Any
    store: ArtifactStoreLike
    get_selected: Callable[[], list[SessionSelection]]
    get_key_to_ref: Callable[[], dict[str, tuple[str, str]]]
    get_events_index_df: Callable[[], pd.DataFrame]
    get_selected_entities: Callable[[], list[ScopeEntity]]
    get_entity_snapshot: Callable[[], EntitySelectionSnapshot]

class WidgetHandle(TypedDict, total=False):
    ui: Any
    root: Any
    out: Any
    state: dict[str, Any]
    controls: dict[str, Any]
    viz_df: pd.DataFrame
    refresh: Callable[[], None]

class RebuilderHandle(TypedDict):
    out: Any
    rebuild: Callable[[], None]
    state: dict[str, Any]
```

Registry variability contract (multi-session):

```python
RegistryPolicy = Literal["union", "intersection", "strict"]
EventSchemaPolicy = RegistryPolicy

@dataclass(frozen=True)
class RegistryResolutionConfig:
    policy: RegistryPolicy = "union"
    include_qc: bool = False
```

`session_key` remains the canonical physical-session identity across widget/service boundaries.
`entity_key` adds a stable selection identity for session-aggregation workflows.

---

## Internal shared component boundaries (current)

These are **internal** helper modules to keep reusable behavior centralized while
keeping notebook-facing constructors stable:

- `analysis/bodaqs_analysis/widgets/histogram_core.py`
  - shared histogram/CDF plotting and summary/trimmed-quantile helpers
  - used by both signal and metric histogram widgets
- `analysis/bodaqs_analysis/widgets/metric_widget_data.py`
  - shared metric widget data prep: events/metrics join, schema/registry sensor resolution
  - used by metric histogram and metric scatter widgets
- `analysis/bodaqs_analysis/widgets/signal_histogram_scope.py`
  - signal-universe resolution and per-signal sample extraction for signal histogram
- `analysis/bodaqs_analysis/widgets/event_browser_scope.py`
  - scope-level registry/schema resolution and event filtering
- `analysis/bodaqs_analysis/widgets/event_browser_options.py`
  - event/sensor option generation + event label parse/build
- `analysis/bodaqs_analysis/widgets/event_browser_render.py`
  - event-browser rendering-specific helpers
- `analysis/bodaqs_analysis/widgets/event_semantics.py`
  - semantic signal option + RoleSpec construction helpers
- `analysis/bodaqs_analysis/widgets/session_window_data.py`
  - session-window data loading/joining/option derivation helpers
- `analysis/bodaqs_analysis/widgets/session_window_plot.py`
  - session-window plot/hover/color helpers
- `analysis/bodaqs_analysis/widgets/session_window_bookmarks.py`
  - bookmark label/default/options helpers

Notebook-facing public API remains constructor/rebuilder functions in widget modules.

---

## Definitions

### Identity

- **run_id**: artifact batch identifier (one per “run” / ingestion batch).
- **session_id**: logger file/session identifier within a run.
- **session_key**: globally unique identifier for a session across runs.

#### `session_key` format

Canonical format:

```
{run_id}::{session_id}
```

(Generated by `make_session_key(run_id, session_id)`.)

---

## Session selector contract

The selector layer is split into two notebook-facing constructors:

1. `make_session_aggregation_editor(...)` for creating/updating/deleting persisted aggregations.
2. `make_session_selector(...)` for selecting entities (sessions + persisted aggregations) for downstream widgets.

This split allows aggregation management to run in a separate cell and to be skipped entirely when saved aggregations are already available.

### `make_session_aggregation_editor(...) -> dict`

Aggregation editor responsibilities:
- discovering available runs/sessions under `artifacts/`
- allowing the user to choose a **run scope**
- managing local persisted **session aggregations** (CRUD + validation)
- applying the same display-mode toggle used by selector:
  - default: description-first labels with ID fallback
  - optional: explicit IDs + descriptions (`Show run and session IDs`)
- persisting to the local aggregation store

Expected return keys:

| key | type | meaning |
|---|---|---|
| `ui` | ipywidgets widget/container | display this in the notebook |
| `store` | `ArtifactStore` | artifact store rooted at `artifacts_dir` |
| `run_dd` | widget | run dropdown control |
| `show_ids_cb` | widget | label-mode toggle |
| `sessions_sel` | widget | physical-session selection for aggregation membership |
| `out` | widget | status/debug output |
| `refresh` | `() -> None` | reload sessions + aggregation dropdown |

### `make_session_selector(...) -> dict`

Selection widget responsibilities:
- discovering available runs/sessions under `artifacts/`
- loading persisted local **session aggregations**
- allowing multi-select of **entities** (physical sessions + aggregations)
- providing *live* getters that reflect the current UI state

**Required return keys**

| key | type | meaning |
|---|---|---|
| `ui` | ipywidgets widget/container | display this in the notebook |
| `store` | `ArtifactStore` | artifact store rooted at `artifacts_dir` |
| `get_selected` | `() -> list[{"run_id": str, "session_id": str}]` | current expanded physical-session selection |
| `get_selected_entities` | `() -> list[ScopeEntity]` | currently selected entities |
| `get_entity_snapshot` | `() -> EntitySelectionSnapshot` | selected entities + effective member expansion |
| `get_key_to_ref` | `() -> dict[str, tuple[str,str]]` | mapping for expanded physical sessions only |
| `get_events_index_df` | `() -> pd.DataFrame` | expanded index DF with columns `session_key, run_id, session_id` |
| `save_selection` | `() -> PersistedEntityScopeSelection` | persist current entity selection for reuse in other notebooks |
| `load_selection` | `() -> PersistedEntityScopeLoadResult` | restore the last persisted entity selection into the selector UI |

**Optional return keys (recommended for debugging / advanced wiring)**

| key | type | meaning |
|---|---|---|
| `run_dd` | widget | run dropdown control |
| `entities_sel` | widget | entity multi-select control (session + aggregation) |
| `show_ids_cb` | widget | label-mode toggle |
| `autosave_cb` | widget | autosave toggle (default checked) |
| `refresh_signal` | widget | hidden refresh token observed by `attach_refresh(...)` |
| `out` | widget | debug output area |

### Invariants

The selector must maintain these invariants:

1) **Non-empty default selection (optional but recommended)**  
If `select_first_by_default=True`, the selector should ensure at least one session is selected initially,
so downstream "Run all cells" succeeds without manual interaction.

2) **Live getters**  
`get_entity_snapshot()`, `get_key_to_ref()`, and `get_events_index_df()` must reflect the *current* selector state.
Implementations may maintain cached internal state, but **must update that state on UI changes**.

3) **Identity consistency**  
`get_events_index_df()` must be consistent with `get_key_to_ref()`:

- `sorted(get_events_index_df()["session_key"].unique()) == sorted(get_key_to_ref().keys())`

4) **Entity overlap dedupe policy**  
When both explicit session entities and aggregation entities are selected:
- explicit sessions take precedence
- overlapping members are removed from affected aggregation effective-member sets
- selector should surface a warning message in `out`

5) **Aggregation persistence**  
Aggregations are persisted locally per user in:
- `~/.bodaqs/session_aggregations_v1.json`

Store rules:
- schema/versioned JSON with atomic writes
- unique `aggregation_key`
- non-empty `member_session_keys`
- policies constrained to `union|intersection|strict`

6) **Persisted scope selection**  
Current selector scope may be persisted locally per user in:
- `~/.bodaqs/entity_scope_selection_v1.json`

Rules:
- schema/versioned JSON with atomic writes
- stores selected `entity_key`s, not pre-expanded physical-session sets
- restore is validated against the current artifacts root and current aggregation definitions
- missing entities are dropped with warnings; a fully unresolved restore is an error
- live selector may autosave on each valid selection change; default UI state is autosave enabled

---

## Persisted scope handle

To support multi-notebook workflows without introducing implicit widget fallback,
persisted scope is exposed as a second, explicit selector-shaped source:

- `analysis/bodaqs_analysis/widgets/entity_scope_store.py`

Notebook-facing factory:

```python
make_persisted_entity_scope_handle(
    *,
    artifacts_dir: str | Path = "artifacts",
    strict: bool = False,
) -> SessionSelectorHandle
```

Responsibilities:
- load the last saved entity selection from the local persisted-scope store
- resolve selected `entity_key`s against the current artifact inventory and aggregation store
- expose the same selector getters consumed by widget rebuilders:
  - `get_selected()`
  - `get_selected_entities()`
  - `get_entity_snapshot()`
  - `get_key_to_ref()`
  - `get_events_index_df()`
- provide a reload control for explicit re-sync when the persisted selection changes

This keeps widget contracts explicit: downstream widgets consume a selector-compatible handle,
whether the source is a live selector UI or a persisted scope handle.

---

## Loader contract (shared utility)

Consumer widgets should not open files directly or parse run/session manifests.
Instead, they consume:

- `store` (ArtifactStore), and/or
- higher-level loader callables.

### `make_session_loader(store, key_to_ref) -> session_loader`

**Signature**

```python
session_loader(session_key: str) -> dict
```

**Return value**

A dict containing at minimum:

- `df`: `pd.DataFrame` (time-series samples)
- `meta`: `dict` (session metadata)

This matches `load_session_artifacts(store, run_id, session_id)`.

> Notes  
> - `session_loader` is intentionally small: it is for **df/meta** and any per-session access a widget needs.  
> - Events/metrics are typically loaded as separate artifacts (see below).

---

## Artifact table access (events / metrics)

Artifacts are stored per session in the session directory:

- `events/<schema_id>/events.parquet`
- `metrics/<schema_id>/metrics.parquet`

A consumer widget that needs events/metrics should load them via store-based helpers.

### Events loader

```python
events_df_sel = load_all_events_for_selected(store, key_to_ref=key_to_ref)
```

Expected to return a concatenated DataFrame across selected sessions, including:

- `session_key`, `run_id`, `session_id` (stamped identity)
- `schema_id`, `event_id`
- `signal_col` (anchor signal column)

Entity-aware variant:

```python
events_df_sel = load_all_events_for_entities(store, snapshot=entity_snapshot)
```

Expected additional provenance columns:

- `entity_key`, `entity_kind`, `source_session_key`

### Metrics loader

```python
metrics_df_sel = load_all_metrics_for_selected(store, key_to_ref=key_to_ref)
```

Expected to return a concatenated DataFrame across selected sessions, including:

- `session_key`, `run_id`, `session_id` (stamped identity)
- `schema_id`, `event_id`
- metric columns prefixed by `m_...`

Entity-aware variant:

```python
metrics_df_sel = load_all_metrics_for_entities(store, snapshot=entity_snapshot)
```

Expected additional provenance columns:

- `entity_key`, `entity_kind`, `source_session_key`

---

## Consumer widget contract

A consumer widget is any widget that:

- operates over the selector’s current scope (multi-session)
- loads sessions lazily via `session_loader(session_key)`
- loads per-session derived tables (events/metrics) via `store` helpers
- renders a plot/UI and returns handles for programmatic access

### Recommended constructor signature

**Example (metric scatter)**

```python
make_<widget>_for_loader(
    *,
    store,
    key_to_ref: dict[session_key, (run_id, session_id)],
    events_index_df: pd.DataFrame,
    session_loader: Callable[[str], dict],
    auto_display: bool = False,
    ...
) -> dict
```

**Why include both `key_to_ref` and `events_index_df`?**

- `key_to_ref` is the “hard” identity mapping needed to load artifacts.
- `events_index_df` is a canonical, selector-produced index that widgets can use for UI scope lists.
- Both come from the selector; widgets should not derive them independently.

### Required behavior

1) **Scope = selector output**  
Widget scope is defined by selector outputs (`entity_snapshot`, `key_to_ref`, `events_index_df`).

2) **Identity columns preserved**  
When building internal working tables (e.g., `viz_df`), the widget should preserve:
- `session_key` (required)
- plus any other useful identity columns (`run_id`, `session_id`) for display/debugging.

3) **Joins use stable identity**  
When joining events and metrics, prefer a stable composite key:
- `(session_key, schema_id, event_id)` is the safest default.

4) **Entity compare-by-default**  
For non-time-series widgets, selected entities are compared by default.
Aggregation entities are treated as in-memory unions of effective member sessions.

5) **UI defaults must not over-filter**  
Defaults should avoid "empty intersection" states.
For example, defaulting entity selection to **all entities** in scope is generally safer than first-only.

6) **Registry differences are explicit**  
When a widget depends on per-session signal registries, it should expose or document a policy for
multi-session differences:
- `union`: allow any signal present in at least one selected session
- `intersection`: only signals present in every selected session
- `strict`: require identical signal sets and fail fast on mismatch

Event schema policy for aggregations uses the same values:
- `union`: allow all schema-id sets
- `intersection`: keep common schema-id set
- `strict`: require identical schema-id sets and identical schema hash per schema-id across all members
  - strict mode fails if any required schema hash is missing from session metadata

7) **Time-series v1 scope rule**  
`event_browser` and `session_window_browser` accept exactly one selected entity at a time.
If the selected entity is an aggregation, render faceted per-member views (no synthetic continuous timeline).

8) **Constructors are pure (no implicit display side effects)**  
`make_<widget>_for_loader(...)` should return a handle (including `root`/`ui`) and not call `display(...)`
internally. Notebook/rebuilder code decides where/how to display.

### Recommended return dict

| key | type | meaning |
|---|---|---|
| `ui` (optional) | widget/container | main widget UI if you want to return it |
| `root` (optional) | widget/container | preferred top-level UI handle for display |
| `out` | `ipywidgets.Output` | output area used for plotting/text |
| `viz_df` (optional) | `pd.DataFrame` | joined/filtered debugging DF |
| `refresh` (recommended) | `() -> None` | recompute internal state + rerender |

> Some widgets also return `controls` and `cache` dicts for testing/debug.

---

## Refresh contract (recommended)

Refreshing matters because selector scope changes after widgets are created.

Current recommended wiring:

- Rebuilder takes a `SessionSelectorHandle`
- Rebuilder pulls fresh scope with `entity_snapshot_from_handle(sel)` and/or `selection_snapshot_from_handle(sel)` each rebuild
- Constructor is called with snapshot-derived inputs
- Constructor returns a handle with `root` and optional `refresh`

`refresh()` should refresh widget-internal state from its current source.
For session-window-style widgets, this should refresh the currently selected session.

Guardrails:

- avoid observer loops by using an `updating` guard when callbacks set widget values
- preserve selections where still valid after option rebuilds
- prefer rebuilding data + rerendering rather than rewriting every control

---

## Worked example: selector cell (thin notebook glue)

```python
from bodaqs_analysis.widgets.session_selector import (
    make_session_aggregation_editor,
    make_session_selector,
)
from bodaqs_analysis.widgets.loaders import make_session_loader

# Optional cell: run only when creating/editing persisted aggregations
agg = make_session_aggregation_editor(artifacts_dir="artifacts")
display(agg["ui"])

# Selection-only widget (can run even if aggregation editor cell is skipped)
sel = make_session_selector(artifacts_dir="artifacts", select_first_by_default=True)
display(sel["ui"])

store = sel["store"]

# Live snapshot (pull fresh whenever you build/refresh widgets)
entity_snapshot = sel["get_entity_snapshot"]()
key_to_ref = sel["get_key_to_ref"]()
events_index_df = sel["get_events_index_df"]()
session_loader = make_session_loader(store=store, key_to_ref=key_to_ref)
```

---

## Worked example: consumer widget cell (thin notebook glue)

```python
from bodaqs_analysis.widgets.metric_scatter_widget import make_metric_scatter_widget_for_loader

# Pull *fresh* selector state when running the cell
key_to_ref = sel["get_key_to_ref"]()
events_index_df = sel["get_events_index_df"]()
session_loader = make_session_loader(store=store, key_to_ref=key_to_ref)

handles = make_metric_scatter_widget_for_loader(
    store=store,
    key_to_ref=key_to_ref,
    events_index_df=events_index_df,
    session_loader=session_loader,
    event_type_col="schema_id",
    signal_col="signal_col",
    auto_display=False,
)

display(handles["root"])
viz_df = handles.get("viz_df")  # debug
```

---

## Notes on current implementations (consistency check)

- The selector provides `ui`, `store`, and the three getters: `get_selected`, `get_key_to_ref`, `get_events_index_df`.
- The selector and aggregation editor both expose `Show run and session IDs` (default unchecked).
- Default label mode is description-first with ID fallback when description is missing.
- The session loader (`make_session_loader`) returns `{"df","meta"}` from `load_session_artifacts`.
- Migrated widgets follow the “scope via selector, load via store helpers, preserve session_key” approach.


---

## Rebuild-on-selector-change pattern (current recommended wiring)

In the current notebooks, downstream widgets are refreshed by **recreating** them when the selector changes.
This keeps widget modules simple and avoids fragile observer loops inside widgets.

### Selector-side wiring helper

The session selector module provides:

- `attach_refresh(sel, rebuild_fns, ...) -> {"detach": ..., "trigger": ...}`

This attaches observers to available selector controls (`run_dd`, `entities_sel`, `show_ids_cb`, and
`sessions_sel` when present) and calls each rebuild function when selection/scope changes.

### Widget-side rebuilder helper

Each widget module provides a helper of the form:

```python
make_<widget>_rebuilder(*, sel, out=None, ...) -> {"out": Output, "rebuild": callable, "state": {...}}
```

- `out` is an `ipywidgets.Output()` that the widget renders into
- `rebuild()` clears the output and recreates the widget from the **current selector scope**
- `state["handles"]` holds the most recent widget handles returned by the constructor

### Worked example

```python
# selector cell
sel = make_session_selector(...)
display(sel["ui"])

# widget cells
scatter = make_metric_scatter_rebuilder(sel=sel); display(scatter["out"])
browser = make_event_browser_rebuilder(sel=sel, schema=schema); display(browser["out"])
hist = make_signal_histogram_rebuilder(sel=sel); display(hist["out"])
mhist = make_metric_histogram_rebuilder(sel=sel); display(mhist["out"])
swb = make_session_window_browser_rebuilder(sel=sel); display(swb["out"])

# wiring cell
refresh = attach_refresh(
    sel,
    rebuild_fns=[browser["rebuild"], hist["rebuild"], scatter["rebuild"], mhist["rebuild"], swb["rebuild"]],
)
```

> This approach intentionally trades preservation of widget-local selections for robustness and simplicity.
> If/when needed, rebuilders can be extended to reapply previous widget-local selections when still valid.

---

## Notebook smoke test command

Use the script below to execute the current notebook compatibility checks in a repeatable way:

```powershell
powershell -ExecutionPolicy Bypass -File .\Tools\run_widget_notebook_smoke_tests.ps1
```

Notes:

- Default run executes:
  - `analysis/bodaqs_widget_test_notebook.ipynb`
  - `analysis/bodaqs_event_schema_test_harness.ipynb`
- Include the session notebook as well:

```powershell
powershell -ExecutionPolicy Bypass -File .\Tools\run_widget_notebook_smoke_tests.ps1 -IncludeSessionNotebook
```

