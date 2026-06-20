# Specification: Widgets & Dashboards

**Created**: 2025-07-11
**Status**: Draft
**Design Docs**: `docs/design/widgets-dashboards.md`

## Scope

**What part of the design is being implemented:**
This spec documents the existing widgets & dashboards sphere in
`analysis/bodaqs_analysis/`. It covers the contract layer, entity scope system,
session selector, data loaders, six consumer widgets, two dashboard builders,
and seven UI modules. All components are already implemented — this spec
documents their as-built behavior.

**Out of scope for this spec:**
- Artifact ingestion and storage (`bodaqs_analysis.artifacts`)
- Library API and Study Set management (`bodaqs_analysis.library_api`)
- Preprocessing pipeline (`bodaqs_analysis.preprocess*`)
- Segment extraction engine (`bodaqs_analysis.segment`)
- GPS semantics resolution (`bodaqs_analysis.gps_semantics`)
- Session notes and catalog (`bodaqs_analysis.session_notes`)
- Bookmark persistence (`bodaqs_analysis.bookmarks`)
- Sensor alias canonicalization (`bodaqs_analysis.sensor_aliases`)
- Signal selectors (`bodaqs_analysis.signal_selectors`)

---

## Design Context

### Relevant Invariants

- **INV-1**: `session_key` format is `{run_id}::{session_id}`
- **INV-2**: `get_events_index_df()` consistent with `get_key_to_ref()`
- **INV-3**: Explicit sessions take precedence over grouped entities in overlap dedup
- **INV-4**: Widget constructors are pure (no implicit display)
- **INV-5**: Time-series widgets accept exactly one entity at a time
- **INV-6**: Events/metrics joins use `(session_key, schema_id, event_id)`
- **INV-7**: Registry policy must be `union|intersection|strict`
- **INV-8**: Aggregations persisted in `artifacts/library/aggregations_v1.json`
- **INV-9**: Persisted scope stores entity keys at `~/.bodaqs/entity_scope_selection_v1.json`
- **INV-10**: Frozen per-session schemas are authoritative
- **INV-11**: Rebuilder pattern recreates widgets from fresh scope
- **INV-12**: `attach_refresh` uses re-entrancy guard
- **INV-13**: `SessionTimeSelection` uses traitlets with source field
- **INV-14**: Entity scope store uses schema v1 with atomic writes
- **INV-15**: `aggregation` entity kind is legacy

### Relevant Contracts

- `SessionSelectorHandle` — selector return shape with live getters
- `WidgetHandle` — widget constructor return shape
- `RebuilderHandle` — rebuilder return shape
- `EntitySelectionSnapshot` — resolved entity selection for widget scope
- `SessionLoader` — `session_key -> {df, meta}` protocol
- `ArtifactStoreLike` — minimal store protocol for loaders

### Relevant Failure Modes

- Empty selector scope → empty grid, empty getters
- Missing events/metrics directories → silently skipped
- Registry/schema policy mismatch (strict) → `ValueError`
- Persisted scope references missing entities → dropped with warnings
- Corrupt entity scope store → backed up, reset to empty
- No GPS data → status message, cleared visuals
- Observer loops → re-entrancy guards

---

## Component Specifications

### contracts.py — Typed Contracts — `analysis/bodaqs_analysis/widgets/contracts.py`

**Design doc reference:** [contracts.py Component Contract](../design/widgets-dashboards.md#contractspy--typed-contracts)
**Depends on:** None (foundational module)

#### Interface Signatures

```python
# Identity types
SessionKey = str
SessionRef = tuple[str, str]
KeyToRef = Mapping[SessionKey, SessionRef]
EntityKey = str
EntityKind = Literal["session", "aggregation", "study_set_grouping"]
RegistryPolicy = Literal["union", "intersection", "strict"]

# Column name constants
SESSION_KEY_COL = "session_key"
RUN_ID_COL = "run_id"
SESSION_ID_COL = "session_id"
ENTITY_KEY_COL = "entity_key"
ENTITY_KIND_COL = "entity_kind"
SOURCE_SESSION_KEY_COL = "source_session_key"
SCHEMA_ID_COL = "schema_id"
EVENT_ID_COL = "event_id"
SIGNAL_COL = "signal_col"
METRIC_PREFIX = "m_"

# Frozen dataclasses
@dataclass(frozen=True)
class SelectionSnapshot:
    key_to_ref: MutableKeyToRef
    events_index_df: pd.DataFrame
    def session_keys(self) -> list[str]: ...

@dataclass(frozen=True)
class ScopeEntity:
    entity_key: EntityKey
    kind: EntityKind
    label: str
    member_session_keys: tuple[SessionKey, ...]

@dataclass(frozen=True)
class EntitySelectionSnapshot:
    selected_entities: list[ScopeEntity]
    entity_to_effective_members: Dict[EntityKey, list[SessionKey]]
    expanded_session_keys: list[SessionKey]
    key_to_ref: MutableKeyToRef
    events_index_df: pd.DataFrame
    def selected_entity_keys(self) -> list[EntityKey]: ...

@dataclass(frozen=True)
class AggregationDefinition:
    aggregation_key: AggregationKey
    title: str
    member_session_keys: tuple[SessionKey, ...]
    registry_policy: RegistryPolicy = "union"
    event_schema_policy: EventSchemaPolicy = "union"
    created_at_utc: str = ""
    updated_at_utc: str = ""
    note: str | None = None

@dataclass(frozen=True)
class PersistedEntityScopeSelection:
    artifacts_root: str
    saved_at_utc: str
    selected_entity_keys: tuple[EntityKey, ...]
    selected_entity_kinds: Dict[EntityKey, EntityKind]
    selected_labels: Dict[EntityKey, str]

@dataclass(frozen=True)
class PersistedEntityScopeLoadResult:
    snapshot: EntitySelectionSnapshot
    warnings: list[str]
    source: PersistedEntityScopeSelection

# Protocols
@runtime_checkable
class ArtifactStoreLike(Protocol):
    def session_dir(self, run_id: str, session_id: str) -> Any: ...
    def read_df(self, path: Any, *, columns: list[str] | None = None) -> pd.DataFrame: ...
    def read_json(self, path: Any) -> Dict[str, Any]: ...

@runtime_checkable
class SessionLoader(Protocol):
    def __call__(self, session_key: str) -> SessionArtifacts: ...

# Handle types
class SessionSelectorCoreHandle(TypedDict):
    ui: Any
    store: ArtifactStoreLike
    get_selected: Callable[[], list[SessionSelection]]
    get_key_to_ref: Callable[[], MutableKeyToRef]
    get_events_index_df: Callable[[], pd.DataFrame]

class SessionSelectorHandle(SessionSelectorCoreHandle, total=False):
    # ... optional keys
    get_selected_entities: Callable[[], list[ScopeEntity]]
    get_entity_snapshot: Callable[[], EntitySelectionSnapshot]
    save_selection: Callable[[], PersistedEntityScopeSelection]
    load_selection: Callable[[], PersistedEntityScopeLoadResult]

class WidgetHandle(TypedDict, total=False):
    ui: Any; root: Any; out: Any; controls: Dict[str, Any]
    cache: Dict[str, Any]; state: Dict[str, Any]
    viz_df: pd.DataFrame; refresh: RebuildFn

class RebuilderHandle(TypedDict):
    out: Any; rebuild: RebuildFn; state: Dict[str, Any]

class RefreshHandle(TypedDict):
    detach: Callable[[], None]
    trigger: RebuildFn

# Helper functions
def entity_snapshot_from_handle(sel: Mapping[str, Any]) -> EntitySelectionSnapshot: ...
def selection_snapshot_from_handle(sel: Mapping[str, Any]) -> SelectionSnapshot: ...
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `sel` (to `entity_snapshot_from_handle`) | Must have `get_entity_snapshot` callable OR `get_key_to_ref` + `get_events_index_df` callables | `ValueError` |
| `get_entity_snapshot()` return | Must be `EntitySelectionSnapshot` instance | `ValueError` |
| `get_events_index_df()` return | Must be `pd.DataFrame` | `ValueError` |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| `ValueError` | Missing required callables in handle | Message string | Provide required callables |
| `ValueError` | `get_entity_snapshot()` returns wrong type | Message string | Fix selector implementation |

#### Acceptance Criteria

- **AC1:** Given a handle with `get_entity_snapshot`, when `entity_snapshot_from_handle` is called, then it returns a deep-copied `EntitySelectionSnapshot` with string-coerced keys.
- **AC2:** Given a handle without `get_entity_snapshot` but with `get_key_to_ref` and `get_events_index_df`, when `entity_snapshot_from_handle` is called, then it projects session selection to session entities as fallback.
- **AC3:** Given a handle without any required callables, when `selection_snapshot_from_handle` is called, then it raises `ValueError`.

#### Integration Points

| Dependency | Call | Expected response | Error handling |
|------------|------|-------------------|----------------|
| Selector handle | `sel.get("get_entity_snapshot")()` | `EntitySelectionSnapshot` | `ValueError` if wrong type |
| Selector handle | `sel.get("get_key_to_ref")()` | `dict[str, tuple[str, str]]` | `ValueError` if not callable |
| Selector handle | `sel.get("get_events_index_df")()` | `pd.DataFrame` | `ValueError` if not DataFrame |

---

### session_selector.py — Session Selector — `analysis/bodaqs_analysis/widgets/session_selector.py`

**Design doc reference:** [session_selector.py Component Contract](../design/widgets-dashboards.md#session_selectorpy--session-selector)
**Depends on:** contracts.py, entity_scope.py, entity_scope_store.py, loaders.py

#### Interface Signatures

```python
def make_session_key(run_id: str, session_id: str) -> SessionKey: ...

def make_session_aggregation_editor(
    *,
    artifacts_dir: str | Path = "artifacts",
    aggregation_store: AggregationStore | None = None,
    default_run_id: str = "__ALL__",
    rows: int = 12,
    show_ids_default: bool = False,
) -> dict[str, Any]: ...

def make_session_selector(
    *,
    artifacts_dir: str | Path = "artifacts",
    aggregation_store: AggregationStore | None = None,
    include_aggregations: bool = True,
    default_run_id: str = "__ALL__",
    select_first_by_default: bool = True,
    rows: int = 12,
    show_ids_default: bool = False,
    autosave_default: bool = True,
) -> SessionSelectorHandle: ...

def attach_refresh(
    sel: Mapping[str, Any],
    rebuild_fns: list[RebuildFn],
) -> RefreshHandle: ...
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `artifacts_dir` | Must be a valid path containing run/session directories | Empty grid if invalid |
| `aggregation_store` | Must implement AggregationStore interface | Default store created if None |
| `member_session_keys` (aggregation) | Must be non-empty and all exist in key_to_ref | `ValueError` |
| `registry_policy` (aggregation) | Must pass `validate_registry_policy_for_sessions` | `ValueError` |
| `event_schema_policy` (aggregation) | Must pass `resolve_event_schema_sets_for_sessions` | `ValueError` |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| `ValueError` | Aggregation members include unknown sessions | Message with sample | Fix member selection |
| `ValueError` | Registry policy validation fails | Policy error message | Fix policy or session selection |
| `ValueError` | Event schema policy validation fails | Schema error message | Fix policy or session selection |
| Display error | Aggregation CRUD operation fails | Error string in output | Fix input and retry |

#### Acceptance Criteria

- **AC1:** Given an artifacts directory with runs and sessions, when `make_session_selector` is called, then it returns a handle with `ui`, `store`, and all required getters.
- **AC2:** Given `select_first_by_default=True`, when the selector is created, then at least one entity is selected initially.
- **AC3:** Given both session and aggregation entities selected, when `get_entity_snapshot` is called, then explicit session members take precedence and overlapping aggregation members are removed with a warning.
- **AC4:** Given `autosave_default=True`, when the selection changes, then the selection is persisted to `~/.bodaqs/entity_scope_selection_v1.json`.
- **AC5:** Given `attach_refresh` is called with rebuild functions, when a selector control changes, then all rebuild functions are called with re-entrancy protection.
- **AC6:** Given a persisted scope handle (no live widgets), when `attach_refresh` is called, then it returns a no-op detach and working trigger.

#### Integration Points

| Dependency | Call | Expected response | Error handling |
|------------|------|-------------------|----------------|
| `ArtifactStore` | `list_runs(store)`, `list_sessions(store, run_id)` | List of run/session IDs | Empty grid if none |
| `AggregationStore` | `load()`, `list()`, `get(key)`, `create()`, `update()`, `delete()`, `save()` | Aggregation definitions | Errors caught and displayed |
| `entity_scope` | `expand_selected_entities(...)` | `ExpandedEntityScope` | No error handling (pure) |
| `entity_scope_store` | `save_entity_scope_selection(...)`, `load_entity_scope_selection(...)` | Persisted selection | Errors caught and displayed |

---

### entity_scope.py — Entity Scope Expansion — `analysis/bodaqs_analysis/widgets/entity_scope.py`

**Design doc reference:** [entity_scope.py Component Contract](../design/widgets-dashboards.md#entity_scopepy--entity-scope-expansion)
**Depends on:** contracts.py, registry_scope.py

#### Interface Signatures

```python
@dataclass(frozen=True)
class ExpandedEntityScope:
    entity_to_effective_members: Dict[EntityKey, list[SessionKey]]
    expanded_session_keys: list[SessionKey]
    reduced_members_by_entity: Dict[EntityKey, list[SessionKey]]

def expand_selected_entities(
    *,
    selected_entities: Sequence[ScopeEntity],
    key_to_ref: KeyToRef,
    reduce_grouped_overlaps: bool = True,
) -> ExpandedEntityScope: ...

def build_entity_selection_snapshot(
    *,
    selected_entities: Sequence[ScopeEntity],
    key_to_ref: KeyToRef,
    events_index_df: pd.DataFrame,
    reduce_grouped_overlaps: bool = True,
) -> EntitySelectionSnapshot: ...

def validate_registry_policy_for_sessions(
    *,
    session_keys: Sequence[str],
    session_loader: SessionLoader,
    policy: RegistryPolicy,
) -> dict[str, dict[str, Mapping[str, Any]]]: ...

def resolve_event_schema_sets_for_sessions(
    *,
    session_keys: Sequence[str],
    key_to_ref: KeyToRef,
    store: Any,
    session_loader: SessionLoader,
    policy: EventSchemaPolicy,
) -> list[str]: ...
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `selected_entities` | Can be empty (returns empty expansion) | No error |
| `key_to_ref` | Session keys not in `key_to_ref` are silently filtered | No error |
| `policy` (registry) | Must be `union\|intersection\|strict` | `ValueError` from `validate_registry_policy` |
| `policy` (schema, strict) | All sessions must have identical schema-id sets and matching hashes | `ValueError` |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| `ValueError` | `registry_policy='strict'` and signal sets differ | Message with sample mismatched sessions | Fix session selection or use different policy |
| `ValueError` | `event_schema_policy='strict'` and schema-id sets differ | Message with sample mismatched sessions | Fix session selection or use different policy |
| `ValueError` | `event_schema_policy='strict'` and schema hash missing | Message with schema_id and sessions | Persist schema hashes in metadata |
| `ValueError` | `event_schema_policy='strict'` and schema hashes differ | Message with schema_id | Fix session selection or use different policy |

#### Acceptance Criteria

- **AC1:** Given explicit session entities and aggregation entities with overlapping members, when `expand_selected_entities` is called, then overlapping members are removed from aggregation effective sets and recorded in `reduced_members_by_entity`.
- **AC2:** Given entities with session keys not in `key_to_ref`, when `expand_selected_entities` is called, then those keys are silently filtered out.
- **AC3:** Given `registry_policy='strict'` with mismatched signal sets, when `validate_registry_policy_for_sessions` is called, then it raises `ValueError` with sample mismatched sessions.
- **AC4:** Given `event_schema_policy='strict'` with matching schema-id sets but differing hashes, when `resolve_event_schema_sets_for_sessions` is called, then it raises `ValueError`.

#### Integration Points

| Dependency | Call | Expected response | Error handling |
|------------|------|-------------------|----------------|
| `registry_scope` | `load_signal_registries_for_sessions(...)`, `apply_registry_policy_to_registries(...)` | Registries dict | `ValueError` propagated |
| `bodaqs_analysis.artifacts` | `list_event_types(store, run_id, session_id)` | List of schema IDs | Empty set if none |
| `SessionLoader` | `session_loader(session_key)` | `{"df", "meta"}` | Empty meta if None |

---

### entity_scope_store.py — Persisted Entity Scope — `analysis/bodaqs_analysis/widgets/entity_scope_store.py`

**Design doc reference:** [entity_scope_store.py Component Contract](../design/widgets-dashboards.md#entity_scope_storepy--persisted-entity-scope)
**Depends on:** contracts.py, entity_scope.py, `bodaqs_analysis.artifacts`, `bodaqs_analysis.library.aggregations`

#### Interface Signatures

```python
class EntityScopeStoreError(ValueError): ...
class EntityScopeStoreValidationError(EntityScopeStoreError): ...

class EntityScopeStore:
    def __init__(self, path: Optional[Path] = None): ...
    def load(self) -> None: ...
    def save(self) -> None: ...
    def get_selection(self) -> Optional[PersistedEntityScopeSelection]: ...
    def set_selection(self, selection: PersistedEntityScopeSelection) -> PersistedEntityScopeSelection: ...

def save_entity_scope_selection(
    *, sel: Mapping[str, Any], artifacts_root: str | Path,
    store_path: Optional[Path] = None,
) -> PersistedEntityScopeSelection: ...

def load_entity_scope_selection(
    *, artifacts_dir: str | Path = "artifacts",
    store_path: Optional[Path] = None,
    aggregation_store: AggregationProvider | None = None,
    strict: bool = False,
) -> PersistedEntityScopeLoadResult: ...

def make_persisted_entity_scope_handle(
    *, artifacts_dir: str | Path = "artifacts",
    aggregation_store: AggregationProvider | None = None,
    strict: bool = False,
    auto_display: bool = False,
) -> SessionSelectorHandle: ...
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `selection.artifacts_root` | Must be non-empty string | `EntityScopeStoreValidationError` |
| `selection.saved_at_utc` | Must be non-empty string | `EntityScopeStoreValidationError` |
| `selection.selected_entity_keys` | Must be non-empty list, no blanks, no duplicates | `EntityScopeStoreValidationError` |
| `selection.selected_entity_kinds` | Values must be `session\|aggregation\|study_set_grouping` | `EntityScopeStoreValidationError` |
| Store schema | Must be `bodaqs.entity_scope_selection.store` | `EntityScopeStoreValidationError` |
| Store version | Must be `1` | `EntityScopeStoreValidationError` |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| `EntityScopeStoreError` | Corrupt store file on load | Message string | Reset to empty (automatic) |
| `EntityScopeStoreError` | No persisted selection saved | Message string | Save a selection first |
| `EntityScopeStoreError` | All persisted entities unresolved | Message string | Fix artifacts or save new selection |
| `EntityScopeStoreError` | Artifacts root mismatch (strict mode) | Message with roots | Use correct artifacts dir or non-strict |
| `EntityScopeStoreValidationError` | Invalid selection/store shape | Message string | Fix selection shape |

#### Acceptance Criteria

- **AC1:** Given a valid selection, when `save_entity_scope_selection` is called, then it writes to `~/.bodaqs/entity_scope_selection_v1.json` with atomic write and backup.
- **AC2:** Given a corrupt store file, when `EntityScopeStore.load()` is called, then the file is backed up to `.corrupt` and the store resets to empty.
- **AC3:** Given a persisted selection with some missing entities, when `load_entity_scope_selection` is called, then missing entities are dropped with warnings and the result includes valid entities.
- **AC4:** Given a persisted selection where all entities are missing, when `load_entity_scope_selection` is called, then it raises `EntityScopeStoreError`.
- **AC5:** Given `make_persisted_entity_scope_handle` is called, then it returns a `SessionSelectorHandle` with all required getters and a reload button.

#### Integration Points

| Dependency | Call | Expected response | Error handling |
|------------|------|-------------------|----------------|
| `ArtifactStore` | `list_runs(store)`, `list_sessions(store, run_id)` | Run/session IDs | Empty if none |
| `AggregationProvider` | `load()`, `list()` | Aggregation definitions | Empty list if load fails |
| `entity_scope` | `build_entity_selection_snapshot(...)` | `EntitySelectionSnapshot` | No error handling (pure) |

---

### loaders.py — Data Loaders — `analysis/bodaqs_analysis/widgets/loaders.py`

**Design doc reference:** [loaders.py Component Contract](../design/widgets-dashboards.md#loaderspy--data-loaders)
**Depends on:** contracts.py, `bodaqs_analysis.artifacts`

#### Interface Signatures

```python
def make_session_loader(
    *, store: ArtifactStoreLike, key_to_ref: KeyToRef,
) -> SessionLoader: ...

def load_all_events_for_selected(
    store: ArtifactStoreLike, *, key_to_ref: KeyToRef,
) -> pd.DataFrame: ...

def load_all_metrics_for_selected(
    store: ArtifactStoreLike, *, key_to_ref: KeyToRef,
) -> pd.DataFrame: ...

def load_all_events_for_entities(
    store: ArtifactStoreLike, *, snapshot: EntitySelectionSnapshot,
) -> pd.DataFrame: ...

def load_all_metrics_for_entities(
    store: ArtifactStoreLike, *, snapshot: EntitySelectionSnapshot,
) -> pd.DataFrame: ...
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `key_to_ref` | Can be empty (returns empty DataFrame) | No error |
| `session_key` | Must exist in `key_to_ref` for entity loaders | Silently skipped if not found |
| Events parquet path | `events/<schema_id>/events.parquet` must exist | Silently skipped |
| Metrics parquet path | `metrics/<schema_id>/metrics.parquet` must exist | Silently skipped |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| `TypeError` (NAType) | fastparquet fails on integer columns with pd.NA | Original exception re-raised if fallback fails | Fix parquet file or exclude problematic columns |
| No error | Missing events/metrics directory | Empty DataFrame returned | Handle empty downstream |

#### Acceptance Criteria

- **AC1:** Given a `key_to_ref` with sessions that have events, when `load_all_events_for_selected` is called, then it returns a concatenated DataFrame with `session_key`, `run_id`, `session_id` columns stamped.
- **AC2:** Given an `EntitySelectionSnapshot`, when `load_all_events_for_entities` is called, then it returns a DataFrame with `entity_key`, `entity_kind`, `source_session_key` provenance columns in addition to identity columns.
- **AC3:** Given a session with no `events/` directory, when `load_all_events_for_selected` is called, then that session is silently skipped.
- **AC4:** Given a parquet file that raises `TypeError` with "NAType", when `_read_events_df_robust` is called, then it retries excluding known problematic columns.
- **AC5:** Given an empty `key_to_ref`, when `load_all_events_for_selected` is called, then it returns an empty DataFrame.

#### Integration Points

| Dependency | Call | Expected response | Error handling |
|------------|------|-------------------|----------------|
| `ArtifactStoreLike` | `store.session_dir(run_id, session_id)` | Path object | Silently skipped if not exists |
| `ArtifactStoreLike` | `store.read_df(path)` | `pd.DataFrame` | NAType fallback for events |
| `bodaqs_analysis.artifacts` | `load_session_artifacts(store, run_id, session_id)` | `{"df", "meta"}` | Propagated |

---

### event_browser.py — Event Browser Widget — `analysis/bodaqs_analysis/widgets/event_browser.py`

**Design doc reference:** [event_browser.py Component Contract](../design/widgets-dashboards.md#event_browserpy--event-browser-widget)
**Depends on:** contracts.py, loaders.py, registry_scope.py, event_browser_scope.py, event_browser_options.py, event_browser_render.py, event_semantics.py, `bodaqs_analysis.segment`, `bodaqs_analysis.sensor_aliases`

#### Interface Signatures

```python
def make_event_browser_widget_for_loader(
    schema: Mapping[str, Any],
    events_df: pd.DataFrame,
    *,
    session_loader: SessionLoader,
    metrics_df: pd.DataFrame | None = None,
    session_key_col: str = SESSION_KEY_COL,
    registry_policy: RegistryPolicy = "union",
    default_quantities: Sequence[str] = ("disp", "vel"),
    default_pre_s: float = 0.8,
    default_post_s: float = 0.8,
    auto_display: bool = False,
) -> WidgetHandle: ...

def make_event_browser_rebuilder(
    *, sel: SessionSelectorHandle, schema: Mapping[str, Any],
    out: Optional[W.Output] = None,
    session_key_col: str = SESSION_KEY_COL,
    registry_policy: RegistryPolicy = "union",
    **kwargs,
) -> RebuilderHandle: ...
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `events_df` | Must be non-empty | `ValueError` |
| `events_df` columns | Must contain `session_key_col`, `session_id`, `event_id`, `signal_col`, `trigger_time_s` | `ValueError` |
| `registry_policy` | Must be `union\|intersection\|strict` | `ValueError` from `validate_registry_policy` |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| `ValueError` | Empty events_df | Message string | Provide non-empty events |
| `ValueError` | Missing required columns | Message with missing column list | Fix events_df |
| Display error | Scope resolution fails | Error message in output | Fix registry/schema |
| Display message | No event selected | "No event selected." | Select an event |
| Display message | Segment invalid | "Segment invalid: {reason}" | Check signal/registry compatibility |

#### Acceptance Criteria

- **AC1:** Given events_df with multiple sessions, when the widget is created, then all sessions appear in the multi-select.
- **AC2:** Given a selected event, when signals are resolved, then the signal list is populated from the event's registry filtered by the active sensor/end.
- **AC3:** Given a selected event and signals, when render is called, then time-windowed segments are extracted and plotted with trigger at t=0.
- **AC4:** Given secondary trigger time columns in the event row, when `show_secondary` is checked, then secondary trigger markers are drawn on the plot.
- **AC5:** Given prev/next button clicks, when navigating events, then the event dropdown updates and downstream observers fire.
- **AC6:** Given a rebuilder with an empty selector scope, when `rebuild` is called, then "No sessions available" is displayed and no widget is created.

#### Integration Points

| Dependency | Call | Expected response | Error handling |
|------------|------|-------------------|----------------|
| `SessionLoader` | `session_loader(session_key)` | `{"df", "meta"}` | Cached in `_session_cache` |
| `bodaqs_analysis.segment` | `extract_segments(df, event_df, meta, schema, request)` | `{"data", "spec", "segments"}` | Invalid segment shows reason |
| `event_browser_scope` | `rebuild_scope_resolution(...)`, `filter_events(...)` | `ScopeResolution`, filtered DF | Error stored in `ScopeResolution.error` |
| `event_semantics` | `registry_signal_options_for_context(...)` | `list[tuple[str, SemanticKey]]` | Empty list if no match |

---

### metric_scatter_widget.py — Metric Scatter Widget — `analysis/bodaqs_analysis/widgets/metric_scatter_widget.py`

**Design doc reference:** [metric_scatter_widget.py Component Contract](../design/widgets-dashboards.md#metric_scatter_widgetpy--metric-scatter-widget)
**Depends on:** contracts.py, loaders.py, metric_widget_data.py, registry_scope.py, `bodaqs_analysis.sensor_aliases`, `bodaqs_analysis.signal_selectors`

#### Interface Signatures

```python
def make_metric_scatter_widget_for_loader(
    *, store: ArtifactStoreLike, schema: Mapping[str, Any],
    key_to_ref: KeyToRef, events_index_df: pd.DataFrame,
    session_loader: SessionLoader,
    entity_snapshot: Optional[EntitySelectionSnapshot] = None,
    session_key_col: str = SESSION_KEY_COL,
    event_type_col: str = SCHEMA_ID_COL,
    signal_col: str = SIGNAL_COL,
    registry_policy: RegistryPolicy = "union",
    default_alpha: float = 0.6,
    default_size: int = 18,
    auto_display: bool = False,
) -> WidgetHandle: ...

def make_metric_scatter_rebuilder(
    *, sel: SessionSelectorHandle, schema: Mapping[str, Any],
    out: Optional[W.Output] = None,
    event_type_col: str = SCHEMA_ID_COL,
    signal_col: str = SIGNAL_COL,
    registry_policy: RegistryPolicy = "union",
    **kwargs: Any,
) -> RebuilderHandle: ...

def prepare_metric_scatter_consumer_data(
    *, events_df: pd.DataFrame, metrics_df: pd.DataFrame,
    session_keys: Sequence[str], session_loader: SessionLoader,
    schema: Optional[Mapping[str, Any]] = None,
    registry_policy: RegistryPolicy = "union",
    require_schema: bool = True,
) -> Dict[str, Any]: ...
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `events_index_df` | Must be non-empty | `ValueError` |
| `key_to_ref` | Must be non-empty | `ValueError` |
| `schema` | Must be non-empty Mapping (if `require_schema=True`) | `ValueError` |
| `registry_policy` | Must be `union\|intersection\|strict` | `ValueError` |
| Resolved sensors | Must have at least one | `ValueError` |
| Resolved entities | Must have at least one | `ValueError` |
| Resolved event types | Must have at least one | `ValueError` |
| Resolved metrics | Must have at least one (`m_` prefix) | `ValueError` |

#### Acceptance Criteria

- **AC1:** Given events and metrics for multiple entities, when the widget is created, then all entities are selected by default and scatter series are built per entity per sensor.
- **AC2:** Given a regression checkbox is checked, when the plot is rendered, then a linear fit line is drawn per series with equation and R² displayed.
- **AC3:** Given event type changes, when sensor and metric options rebuild, then previous selections are preserved if still valid.
- **AC4:** Given no numeric x/y pairs after filtering, when the plot is rendered, then "No numeric x/y pairs after filtering" is displayed.

#### Integration Points

| Dependency | Call | Expected response | Error handling |
|------------|------|-------------------|----------------|
| `loaders` | `load_all_events_for_entities/selected`, `load_all_metrics_for_entities/selected` | DataFrames | `ValueError` if empty |
| `metric_widget_data` | `build_metric_viz_df(...)`, `registry_maps_for_sessions(...)`, `assign_sensor_column(...)` | viz_df, registries, sensor column | `ValueError` if no sensors resolved |
| `bodaqs_analysis.signal_selectors` | `selector_matches_signal(...)` | bool | No error handling |

---

### metric_histogram_widget.py — Metric Histogram Widget — `analysis/bodaqs_analysis/widgets/metric_histogram_widget.py`

**Design doc reference:** [metric_histogram_widget.py Component Contract](../design/widgets-dashboards.md#metric_histogram_widgetpy--metric-histogram-widget)
**Depends on:** contracts.py, loaders.py, metric_widget_data.py, histogram_core.py, registry_scope.py, `bodaqs_analysis.sensor_aliases`

#### Interface Signatures

```python
def make_metric_histogram_widget_for_loader(
    *, store: ArtifactStoreLike, schema: Mapping[str, Any],
    key_to_ref: KeyToRef, events_index_df: pd.DataFrame,
    session_loader: SessionLoader,
    entity_snapshot: Optional[EntitySelectionSnapshot] = None,
    session_key_col: str = SESSION_KEY_COL,
    event_type_col: str = SCHEMA_ID_COL,
    signal_col: str = SIGNAL_COL,
    registry_policy: RegistryPolicy = "union",
    default_bins: int = 10,
    max_bins: int = 200,
    auto_display: bool = False,
) -> WidgetHandle: ...

def make_metric_histogram_rebuilder(
    *, sel: SessionSelectorHandle, schema: Mapping[str, Any],
    out: Optional[W.Output] = None,
    **kwargs,
) -> RebuilderHandle: ...
```

#### Acceptance Criteria

- **AC1:** Given events and metrics, when the widget is created, then histogram series are built per entity per sensor for the selected metric.
- **AC2:** Given CDF mode is checked, when the plot is rendered, then a cumulative step plot is drawn instead of a histogram.
- **AC3:** Given `show_stats` is checked, when the plot is rendered, then summary stats (count, min, max, mean, median) are printed per series.
- **AC4:** Given no numeric values after filtering, when the plot is rendered, then "No numeric values after filtering" is displayed.

#### Integration Points

| Dependency | Call | Expected response | Error handling |
|------------|------|-------------------|----------------|
| `loaders` | `load_all_events_for_entities/selected`, `load_all_metrics_for_entities/selected` | DataFrames | `ValueError` if empty |
| `metric_widget_data` | `build_metric_viz_df(...)`, `registry_maps_for_sessions(...)`, `assign_sensor_column(...)` | viz_df, registries, sensor column | `ValueError` if no sensors |
| `histogram_core` | `plot_hist_or_cdf(...)`, `series_stats_line(...)` | Plot rendered, stats string | No error handling |

---

### signal_histogram_widget.py — Signal Histogram Widget — `analysis/bodaqs_analysis/widgets/signal_histogram_widget.py`

**Design doc reference:** [signal_histogram_widget.py Component Contract](../design/widgets-dashboards.md#signal_histogram_widgetpy--signal-histogram-widget)
**Depends on:** contracts.py, loaders.py, histogram_core.py, registry_scope.py, signal_histogram_scope.py

#### Interface Signatures

```python
def make_signal_histogram_widget_for_loader(
    events_df: pd.DataFrame,
    *,
    session_loader: SessionLoader,
    session_key_col: str = SESSION_KEY_COL,
    entity_to_members: Optional[Dict[str, List[str]]] = None,
    entity_labels: Optional[Dict[str, str]] = None,
    registry_policy: RegistryPolicy = "union",
    default_bins: int = 50,
    max_bins: int = 500,
    auto_display: bool = False,
    loader_key_resolver: Optional[Callable[[str], str]] = None,
) -> WidgetHandle: ...

def make_signal_histogram_rebuilder(
    *, sel: SessionSelectorHandle,
    out: Optional[W.Output] = None,
    session_key_col: str = SESSION_KEY_COL,
    **kwargs,
) -> RebuilderHandle: ...
```

#### Acceptance Criteria

- **AC1:** Given events_df with entity IDs, when the widget is created, then all entities are selected by default.
- **AC2:** Given `registry_policy='strict'` with mismatched signal sets, when signal options are rebuilt, then the error is displayed in the output area.
- **AC3:** Given `show_metrics` is checked, when the plot is rendered, then trimmed quantile metrics (Q25, Q50, Q75, Q90, Q95, IQR, skew) are displayed in a table.
- **AC4:** Given `active_mask_qc` column in session df and `include_inactive` is unchecked, when signal values are extracted, then only active samples are included.
- **AC5:** Given multiple selected entities, when signal options are rebuilt, then the default signal prefers one common to all selected entities.

#### Integration Points

| Dependency | Call | Expected response | Error handling |
|------------|------|-------------------|----------------|
| `SessionLoader` | `session_loader(session_key)` | `{"df", "meta"}` | Cached in `session_cache` |
| `signal_histogram_scope` | `resolve_scope_signal_options(...)`, `signal_values(...)` | Signal options, values array | Error stored in state |
| `histogram_core` | `plot_hist_or_cdf(...)`, `compute_trimmed_quantile_metrics(...)` | Plot, metrics | No error handling |

---

### session_window_browser_widget.py — Session Window Browser — `analysis/bodaqs_analysis/widgets/session_window_browser_widget.py`

**Design doc reference:** [session_window_browser_widget.py Component Contract](../design/widgets-dashboards.md#session_window_browser_widgetpy--session-window-browser)
**Depends on:** contracts.py, session_window_data.py, session_window_plot.py, session_window_bookmarks.py, time_selection.py, `bodaqs_analysis.bookmarks`

#### Interface Signatures

```python
def make_session_window_browser_widget_for_loader(
    *,
    events_index_df: pd.DataFrame,
    session_loader: SessionLoader,
    events_loader: Optional[Callable[[str], pd.DataFrame]] = None,
    metrics_loader: Optional[Callable[[str], pd.DataFrame]] = None,
    session_key_col: str = SESSION_KEY_COL,
    session_id_col: str = SESSION_ID_COL,
    event_id_col: str = EVENT_ID_COL,
    event_type_col: str = SCHEMA_ID_COL,
    trigger_time_col: str = "trigger_time_s",
    time_col: str = "time_s",
    selection_model: Optional[SessionTimeSelection] = None,
    detail_max_points: int = 8000,
    auto_display: bool = False,
) -> WidgetHandle: ...

def make_session_window_browser_rebuilder(
    *, sel: SessionSelectorHandle,
    out: Optional[W.Output] = None,
    **kwargs,
) -> RebuilderHandle: ...
```

#### Acceptance Criteria

- **AC1:** Given events_index_df with multiple sessions, when the widget is created, then the first session is active and its signals are plotted.
- **AC2:** Given a session with >8000 samples, when `auto_downsample` is checked, then min/max downsampling is applied preserving narrow peaks.
- **AC3:** Given event type pairs are selected, when the plot is rendered, then event markers are drawn on a fixed lane with hover text showing trigger time and metrics.
- **AC4:** Given a bookmark is saved, when the bookmark list is rebuilt, then it appears with title and time range.
- **AC5:** Given a bookmark is loaded, when the view is restored, then detail signals, event types, show_marks, and window range are restored (with safe intersections).
- **AC6:** Given the x-axis range changes, when the user pans/zooms, then `SessionTimeSelection.window_t0_s/t1_s` is updated.
- **AC7:** Given a point is clicked on a detail trace, when the click fires, then `SessionTimeSelection.selected_time_s` is updated and a vertical line is drawn.

#### Integration Points

| Dependency | Call | Expected response | Error handling |
|------------|------|-------------------|----------------|
| `SessionLoader` | `session_loader(session_key)` | `{"df", "meta"}` | `ValueError` from `require_session` |
| `SessionTimeSelection` | `observe(...)`, `update_state(...)`, `snapshot()` | Trait notifications | Echo prevention via `source` field |
| `bodaqs_analysis.bookmarks` | `BookmarkStore.load/save/list/get/add_from_view/update/delete` | Bookmark entries | Errors caught and displayed |
| `session_window_data` | `derive_signal_options(...)`, `merge_events_metrics(...)`, `compute_detail_y_range(...)` | Signal options, merged DF, y-range | No error handling |

---

### gps_browser_widget.py — GPS Browser Widget — `analysis/bodaqs_analysis/widgets/gps_browser_widget.py`

**Design doc reference:** [gps_browser_widget.py Component Contract](../design/widgets-dashboards.md#gps_browser_widgetpy--gps-browser-widget)
**Depends on:** contracts.py, gps_data.py, time_selection.py, `bodaqs_analysis.gps_semantics`, `ipyleaflet`, `plotly`

#### Interface Signatures

```python
def make_gps_browser_widget_for_loader(
    *,
    session_keys: Sequence[str],
    session_loader: SessionLoader,
    selection_model: Optional[SessionTimeSelection] = None,
    preferred_stream_name: str = "gps_fit",
    time_col: str = "time_s",
    show_session_control: bool = True,
    map_height_px: int = 420,
    chart_height_px: int = 300,
    max_route_points: int = 8000,
    auto_display: bool = False,
) -> WidgetHandle: ...

def make_gps_browser_rebuilder(
    *, sel: SessionSelectorHandle,
    out: Optional[W.Output] = None,
    selection_model: Optional[SessionTimeSelection] = None,
    preferred_stream_name: str = "gps_fit",
    time_col: str = "time_s",
    **kwargs: Any,
) -> RebuilderHandle: ...
```

#### Acceptance Criteria

- **AC1:** Given a session with GPS data in `gps_fit` stream, when the widget loads, then the route is drawn on the map and altitude is plotted.
- **AC2:** Given `color_by_speed` is checked, when the route is rendered, then segments are colored by speed bins (0-10, 10-20, 20-30, 30-40, 40+ km/h).
- **AC3:** Given a route with >8000 points, when the widget loads, then the route is downsampled and a "preview downsampled" message is shown.
- **AC4:** Given a session without GPS data, when the widget loads, then "No GPS route is available" is shown and visuals are cleared.
- **AC5:** Given the altitude chart x-axis range changes, when the user pans/zooms, then `SessionTimeSelection.window_t0_s/t1_s` is updated.
- **AC6:** Given a point is clicked on the altitude chart, when the click fires, then `SessionTimeSelection.selected_time_s` is updated and the map marker moves.
- **AC7:** Given `SessionTimeSelection.session_key` changes from another widget, when the GPS browser observes it, then it loads the new session and fits map bounds.

#### Integration Points

| Dependency | Call | Expected response | Error handling |
|------------|------|-------------------|----------------|
| `SessionLoader` | `session_loader(session_key)` | `{"df", "meta", "stream_dfs"}` | No GPS data → cleared visuals |
| `gps_data` | `extract_gps_view_data(...)`, `build_route_segments(...)`, `build_line_runs_from_segments(...)` | GPSViewData, segment DF, LineRuns | None → cleared visuals |
| `bodaqs_analysis.gps_semantics` | `preferred_gps_source_name(...)`, `resolve_gps_columns(...)` | Stream name, GPSColumnSet | None if no GPS columns |
| `SessionTimeSelection` | `observe(...)`, `update_state(...)`, `snapshot()` | Trait notifications | Echo prevention via `source` field |

---

### time_selection.py — Session Time Selection — `analysis/bodaqs_analysis/widgets/time_selection.py`

**Design doc reference:** [time_selection.py Component Contract](../design/widgets-dashboards.md#time_selectionpy--session-time-selection)
**Depends on:** `traitlets`

#### Interface Signatures

```python
class SessionTimeSelection(HasTraits):
    session_key: str | None
    window_t0_s: float | None
    window_t1_s: float | None
    selected_time_s: Any  # float | None
    source: str

    def update_state(
        self, *,
        session_key: Optional[str] = None,
        window_t0_s: Optional[float] = None,
        window_t1_s: Optional[float] = None,
        selected_time_s: Any = None,
        set_selected_time: bool = False,
        source: Optional[str] = None,
    ) -> None: ...

    def set_session(self, session_key: str, *, source: Optional[str] = None) -> None: ...
    def set_window(self, t0_s: float, t1_s: float, *, source: Optional[str] = None) -> None: ...
    def set_selected_time(self, time_s: Optional[float], *, source: Optional[str] = None) -> None: ...
    def clear_selected_time(self, *, source: Optional[str] = None) -> None: ...
    def snapshot(self) -> dict[str, Any]: ...

def make_session_time_selection() -> SessionTimeSelection: ...
```

#### Acceptance Criteria

- **AC1:** Given `update_state` is called with window values, when the values are set, then they are normalized (min/max ordered) and batched with `hold_trait_notifications`.
- **AC2:** Given `set_selected_time=False`, when `update_state` is called with `selected_time_s`, then `selected_time_s` is NOT updated.
- **AC3:** Given `snapshot()` is called, when the current state is read, then it returns a dict with all five traits.

---

### dashboards/gps_browser.py — GPS Dashboard — `analysis/bodaqs_analysis/dashboards/gps_browser.py`

**Design doc reference:** [gps_browser.py Component Contract](../design/widgets-dashboards.md#dashboards_gps_browserpy--gps-dashboard)
**Depends on:** session_window_browser_widget.py, gps_browser_widget.py, session_selector.py, time_selection.py

#### Interface Signatures

```python
class DashboardHandle(dict[str, Any]):
    def mark_displayed(self) -> None: ...

def make_session_gps_dashboard(
    sel: Mapping[str, Any],
    *,
    selection_model: SessionTimeSelection | None = None,
    session_browser_kwargs: Mapping[str, Any] | None = None,
    gps_browser_kwargs: Mapping[str, Any] | None = None,
    auto_display: bool = False,
) -> DashboardHandle: ...
```

#### Acceptance Criteria

- **AC1:** Given a selector handle, when `make_session_gps_dashboard` is called, then both sub-widgets are created with a shared `SessionTimeSelection`.
- **AC2:** Given the GPS browser's `show_session_control` defaults to False, when the dashboard is displayed, then the GPS browser's session dropdown is hidden.
- **AC3:** Given the selector changes, when `attach_refresh` fires, then both sub-widgets rebuild.
- **AC4:** Given `auto_display=True`, when the dashboard is created, then the root is displayed and `mark_displayed` is called to prevent double-display.

---

### dashboards/simple_suspension_metrics.py — Suspension Metrics Dashboard — `analysis/bodaqs_analysis/dashboards/simple_suspension_metrics.py`

**Design doc reference:** [simple_suspension_metrics.py Component Contract](../design/widgets-dashboards.md#dashboards_simple_suspension_metricspy--suspension-metrics-dashboard)
**Depends on:** contracts.py, loaders.py, metric_scatter_widget.py, session_selector.py, `bodaqs_analysis.sensor_aliases`, `bodaqs_analysis.signal_selectors`

#### Interface Signatures

```python
def make_simple_suspension_metrics_dashboard(
    sel: Mapping[str, Any],
    *,
    compression_event_type: str = "compressions_all>25",
    rebound_event_type: str = "rebounds_all>25",
    scatter_x_metric: str = "m_peak_disp_max",
    compression_y_metric: str = "m_interval_vel_max",
    rebound_y_metric: str = "m_interval_vel_min",
    front_signal_selector: Mapping[str, Any] | None = None,
    rear_signal_selector: Mapping[str, Any] | None = None,
    # ... additional selector overrides
    auto_display: bool = False,
) -> DashboardHandle: ...
```

#### Acceptance Criteria

- **AC1:** Given a selector with selected entities, when the dashboard is created, then 10 tiles are built (5 rows × 2 columns: displacement, velocity, events, compression scatter, rebound scatter for front/rear).
- **AC2:** Given `show_engineering` is unchecked, when displacement tiles rebuild, then normalized displacement signals are used and x-axis is [0, 1].
- **AC3:** Given `show_engineering` is checked, when displacement tiles rebuild, then engineering-unit (mm) displacement signals are used.
- **AC4:** Given displacement tiles are rebuilt, when shared y-axis is computed, then both front and rear tiles use the same y-axis maximum.
- **AC5:** Given scatter tiles are rebuilt, when regression fits are computed, then the opposite side's fit line is overlaid as a dashed line.
- **AC6:** Given event tiles are rebuilt, when event counts are computed, then events are filtered by side (front/rear) and grouped by schema_id.

---

### ui/aggregation_manager.py — Aggregation Library Manager — `analysis/bodaqs_analysis/ui/aggregation_manager.py`

**Design doc reference:** [aggregation_manager.py Component Contract](../design/widgets-dashboards.md#ui_aggregation_managerpy--aggregation-library-manager)
**Depends on:** `bodaqs_analysis.artifacts`, `bodaqs_analysis.library.aggregations`, `bodaqs_analysis.session_notes`, entity_scope.py, loaders.py

#### Interface Signatures

```python
def make_aggregation_library_manager(
    *,
    artifacts_dir: str | Path = "artifacts",
    aggregation_store: AggregationStore | None = None,
    rows: int = 12,
    show_ids_default: bool = False,
    auto_display: bool = False,
) -> dict[str, Any]: ...
```

#### Acceptance Criteria

- **AC1:** Given an artifacts directory, when the manager is created, then the session grid is populated from the session catalog with filter support.
- **AC2:** Given sessions are selected and "Create" is clicked, when validation passes, then a new aggregation is created and saved.
- **AC3:** Given an aggregation is selected in the grid, when "Load" is clicked, then its member sessions are loaded into the session selection.
- **AC4:** Given the aggregation grid, when an aggregation is selected, then its title, note, registry policy, and schema policy are loaded into the editor fields.

---

### ui/fit_bindings_editor.py — FIT Bindings Editor — `analysis/bodaqs_analysis/ui/fit_bindings_editor.py`

**Design doc reference:** [fit_bindings_editor.py Component Contract](../design/widgets-dashboards.md#ui_fit_bindings_editorpy--fit-bindings-editor)
**Depends on:** `bodaqs_analysis.io_fit`

#### Interface Signatures

```python
def build_fit_candidate_summary(
    sessions_by_id: Mapping[str, Mapping[str, Any]],
    *,
    fit_import: Optional[Mapping[str, Any]],
) -> pd.DataFrame: ...

def make_fit_bindings_editor(
    sessions_by_id: Mapping[str, Mapping[str, Any]],
    *,
    fit_import: Optional[Mapping[str, Any]],
) -> Dict[str, Any]: ...
```

#### Acceptance Criteria

- **AC1:** Given FIT import is disabled, when `build_fit_candidate_summary` is called, then all sessions have status "disabled".
- **AC2:** Given sessions with overlapping FIT files, when the editor is created, then ambiguous sessions appear in the dropdown with candidate files.
- **AC3:** Given a binding is saved, when "Save Binding" is clicked, then the binding is persisted to the bindings JSON file.

---

### ui/library_manager.py — Library Manager — `analysis/bodaqs_analysis/ui/library_manager.py`

**Design doc reference:** [library_manager.py Component Contract](../design/widgets-dashboards.md#ui_library_managerpy--library-manager)
**Depends on:** `bodaqs_analysis.artifacts`, `bodaqs_analysis.library_api`, `bodaqs_analysis.session_notes`

#### Interface Signatures

```python
def make_library_manager(
    *,
    libraries_root: str | Path | None = None,
    library_id: str | None = None,
    artifacts_dir: str | Path = "artifacts",
    selector: Mapping[str, Any] | None = None,
    artifact_store: ArtifactStore | None = None,
    library_adapter: LibraryAdapter | None = None,
    template_root: str | Path | None = None,
    aggregation_store: Any | None = None,
    projection_configs: Sequence[CatalogProjectionConfig] = (),
    rows: int = 14,
    show_ids_default: bool = False,
    auto_display: bool = False,
) -> dict[str, Any]: ...
```

#### Acceptance Criteria

- **AC1:** Given a libraries root and library ID, when the manager is created, then the session grid is populated from the library adapter catalog.
- **AC2:** Given a session is selected, when the note editor refreshes, then the existing note (if any) is loaded into the template fields.
- **AC3:** Given note fields are edited and "Save note" is clicked, when a single session is selected, then the note is saved directly.
- **AC4:** Given multiple sessions are selected and "Save note" is clicked, when a confirmation dialog appears, then the user must confirm before notes are applied to all selected sessions.
- **AC5:** Given a Study Set is created from selected sessions, when "Create from selected" is clicked, then the Study Set is persisted via the library adapter.

---

### ui/preprocess_controls.py — Preprocess Controls — `analysis/bodaqs_analysis/ui/preprocess_controls.py`

**Design doc reference:** [preprocess_controls.py Component Contract](../design/widgets-dashboards.md#ui_preprocess_controlspy--preprocess-controls)
**Depends on:** `bodaqs_analysis.va`, `bodaqs_analysis.preprocess_filters`

#### Interface Signatures

```python
@dataclass
class PreprocessDefaults:
    schema_path: str
    ingestion_mode: str  # "tolerant" or "strict"
    fit_import: Optional[Dict[str, Any]]
    zeroing_enabled: bool
    zero_window_s: float
    zero_min_samples: int
    clip_0_1: bool
    prefer_postprocessing_transformations: bool
    butterworth_smoothing: Optional[List[Dict[str, Any]]]
    butterworth_generate_residuals: bool
    active_enabled: bool
    active_disp_thresh: float
    active_vel_thresh: float
    active_window: str
    active_padding: str
    active_min_seg: str
    prompt_for_descriptions: bool

class PreprocessControls:
    def __init__(
        self, disp_cols_all: List[str], sessions_by_id: Dict[str, Any],
        *, defaults: Optional[PreprocessDefaults] = None,
        default_ranges: Optional[Dict[str, float]] = None,
    ) -> None: ...
    def get_config(self) -> Dict[str, Any]: ...
```

#### Acceptance Criteria

- **AC1:** Given displacement columns and sessions, when `PreprocessControls` is created, then an Accordion UI is built with all preprocessing parameter sections.
- **AC2:** Given `get_config()` is called, when the current widget values are read, then a validated config dict suitable for `preprocess_session()` is returned.

---

### ui/preprocess_file_selector.py — Preprocess Log Selector — `analysis/bodaqs_analysis/ui/preprocess_file_selector.py`

**Design doc reference:** [preprocess_file_selector.py Component Contract](../design/widgets-dashboards.md#ui_preprocess_file_selectorpy--preprocess-log-selector)
**Depends on:** `bodaqs_analysis.session_archive`

#### Interface Signatures

```python
def load_processed_sha256_set(artifacts_dir: Path) -> Set[str]: ...

class PreprocessLogSelector:
    def __init__(self, *, ...) -> None: ...
    def get_selected_files(self) -> List[Path]: ...
    def select_all_visible(self) -> None: ...
    def clear_selection(self) -> None: ...
    def refresh(self) -> None: ...
```

#### Acceptance Criteria

- **AC1:** Given an artifacts directory with processed sessions, when `load_processed_sha256_set` is called, then SHA256 hashes are extracted from manifest JSON files.
- **AC2:** Given a directory of log files, when the selector is created, then files are displayed with processed/unprocessed status.
- **AC3:** Given `select_all_visible` is called, when visible files are selected, then all visible file rows are marked as selected.

---

### ui/preprocess_profile_editor.py — Preprocess Profile Editor — `analysis/bodaqs_analysis/ui/preprocess_profile_editor.py`

**Design doc reference:** [preprocess_profile_editor.py Component Contract](../design/widgets-dashboards.md#ui_preprocess_profile_editorpy--preprocess-profile-editor)
**Depends on:** `bodaqs_analysis.preprocess_filters`, `bodaqs_analysis.preprocess_profile`

#### Interface Signatures

```python
class PreprocessProfileEditor:
    def __init__(self, ...) -> None: ...
    def refresh_profile_list(self) -> None: ...
    def set_profile(self, profile_id: str) -> None: ...
    def load_profile(self) -> None: ...
    def get_config(self) -> Dict[str, Any]: ...
    def get_profile(self) -> Optional[Dict[str, Any]]: ...
    def save_profile(self) -> None: ...

def make_preprocess_profile_editor(...) -> dict[str, Any]: ...
```

#### Acceptance Criteria

- **AC1:** Given a profile directory, when the editor is created, then available profiles are discovered and listed.
- **AC2:** Given a profile is selected, when `load_profile` is called, then its configuration is loaded into the editor fields.
- **AC3:** Given fields are edited and `save_profile` is called, when validation passes, then the profile is persisted to JSON.

---

### ui/runtime_settings_editor.py — Runtime Settings Editor — `analysis/bodaqs_analysis/ui/runtime_settings_editor.py`

**Design doc reference:** [runtime_settings_editor.py Component Contract](../design/widgets-dashboards.md#ui_runtime_settings_editorpy--runtime-settings-editor)
**Depends on:** None (standalone)

#### Interface Signatures

```python
class PreprocessRuntimeSettingsEditor:
    def __init__(self, ...) -> None: ...
    def get_settings(self) -> Dict[str, Any]: ...
    def bind_log_selector(self, selector: Any) -> None: ...

def make_preprocess_runtime_settings_editor(...) -> dict[str, Any]: ...
```

#### Acceptance Criteria

- **AC1:** Given the editor is created, when settings are entered, then they are persisted to `.bodaqs_preprocess_runtime_settings.json`.
- **AC2:** Given `get_settings` is called, when the current widget values are read, then a settings dict is returned.
- **AC3:** Given a log selector is bound, when files are selected, then the file count is displayed in the settings editor.

---

## Implementation Approach

### High-Level Architecture

The system follows a layered architecture:

1. **Contract Layer** (`contracts.py`) — typed interfaces, dataclasses, protocols
2. **Selection Layer** — session selector, entity scope, persisted scope store
3. **Scope Resolution** — registry policy, event schema resolution
4. **Data Loading** — session/events/metrics loaders with identity stamping
5. **Consumer Widgets** — six interactive widgets, each with constructor + rebuilder
6. **Shared Helpers** — histogram core, metric data, event browser helpers, etc.
7. **Dashboards** — compose widgets with shared state
8. **UI Modules** — preprocessing and library management widgets

The rebuilder pattern is central: each widget has a `make_<widget>_rebuilder` that
recreates the widget from fresh selector scope on each selection change. This
avoids fragile observer loops inside widgets at the cost of not preserving
widget-local selections across rebuilds.

### Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Widget update strategy | Rebuild-on-change (not live observers) | Robustness over selection preservation |
| Identity model | `session_key = "{run_id}::{session_id}"` | Globally unique across runs |
| Entity model | Sessions + aggregations + study_set_grouping | Supports both individual and grouped session analysis |
| Sensor resolution | Schema-mediated (event → schema → registry → end) | Handles varying signal column names across sessions |
| Cross-widget linking | `traitlets.HasTraits` (SessionTimeSelection) | Native ipywidgets observable pattern |
| Map rendering | ipyleaflet | Interactive zoom/pan, multiple basemaps |
| Time-series rendering | Plotly FigureWidget | Native rangeslider, click events, batch updates |
| Histogram rendering | matplotlib | Simpler, sufficient for static histograms |
| Persistence | Per-user JSON files with atomic writes | No database dependency, notebook-friendly |

### Alternatives Considered

| Alternative | Why not chosen |
|-------------|----------------|
| Live observer-based widget updates | Fragile observer loops, complex state management |
| Database-backed persistence | Overkill for notebook-local workflow |
| Bokeh for time-series | Plotly FigureWidget has better JupyterLab integration |
| folium for maps | ipyleaflet has better widget integration |

## Dependencies

### Design Dependencies
- `docs/design/widgets-dashboards.md` (this spec's design doc)

### Spec Dependencies
- None — this is a backfill of existing code

### Package Dependencies
- `ipywidgets` — widget framework
- `ipydatagrid` — data grid widget (selector, aggregation manager, library manager)
- `plotly` — FigureWidget for session window browser and GPS browser
- `ipyleaflet` — map widget for GPS browser
- `matplotlib` — histogram and scatter plotting
- `pandas` — data manipulation
- `numpy` — numerical operations
- `traitlets` — observable state for SessionTimeSelection
- `bodaqs_analysis.artifacts` — artifact store and session loading
- `bodaqs_analysis.library.aggregations` — canonical aggregation store
- `bodaqs_analysis.library_api` — library adapter for library manager
- `bodaqs_analysis.segment` — segment extraction for event browser
- `bodaqs_analysis.gps_semantics` — GPS column resolution
- `bodaqs_analysis.sensor_aliases` — canonical end resolution
- `bodaqs_analysis.signal_selectors` — signal selector matching
- `bodaqs_analysis.session_notes` — session note templates and catalog
- `bodaqs_analysis.bookmarks` — bookmark persistence
- `bodaqs_analysis.io_fit` — FIT file handling
- `bodaqs_analysis.preprocess_filters` — Butterworth smoothing config
- `bodaqs_analysis.preprocess_profile` — preprocess profile management
- `bodaqs_analysis.session_archive` — session input identity
- `bodaqs_analysis.va` — velocity naming

## Open Questions

| # | Question | Blocks | Resolution |
|---|----------|--------|------------|
| 1 | `study_set_grouping` entity kind defined but unused by selector | Nothing | UNRESOLVED — defined for future use |
| 2 | `RegistryResolutionConfig.include_qc` field unused | Nothing | UNRESOLVED — may be future feature |
| 3 | `SnapshotWidgetBuilder` protocol defined but unused | Nothing | UNRESOLVED — may be future pattern |
| 4 | `SelectedEventsLoader`/`SelectedMetricsLoader` protocol signature mismatch | Nothing | UNRESOLVED — protocols don't match actual function signatures |
| 5 | `show_ids_cb` always None in selector handle | Nothing | UNRESOLVED — selector uses show_ids=True internally but doesn't expose toggle |

## Risks

| Risk | Mitigation |
|------|------------|
| Plotly/ipyleaflet/ipydatagrid version incompatibility | No version pinning in spec; notebook smoke tests exist |
| Large session datasets cause kernel hangs | Downsampling in session window and GPS browser |
| Observer loops from cross-widget linking | Re-entrancy guards and source field in SessionTimeSelection |
| Persisted scope stale after artifact changes | Validation on restore with warnings for missing entities |
| Schema hash missing in session metadata (strict mode) | Clear error message with schema_id and sessions |

## Success Criteria

- [ ] All 26 widget files, 3 dashboard files, and 8 UI files are documented in the design doc
- [ ] All 15 system invariants are numbered and documented
- [ ] All failure modes are captured in the failure modes table
- [ ] Entity scope system (expansion, dedup, persistence) is fully documented
- [ ] Session selector contract (getters, autosave, refresh) is fully documented
- [ ] Each consumer widget's constructor and rebuilder signatures are documented
- [ ] Dashboard composition pattern (shared SessionTimeSelection) is documented
- [ ] Schema-mediated sensor resolution flow is documented
- [ ] Registry policy (union/intersection/strict) behavior is documented
- [ ] Event schema resolution (frozen/fallback/strict) behavior is documented
- [ ] Cross-widget time selection linking is documented
- [ ] Rebuilder pattern and attach_refresh wiring are documented
