"""Typed contracts for selector-driven widget composition.

This module defines stable interface shapes used by:
- session selector handles,
- session/events/metrics loaders,
- widget constructors and rebuilders,
- refresh wiring.

It is intentionally lightweight and can be adopted incrementally.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Literal, Mapping, Protocol, TypedDict, runtime_checkable

import pandas as pd

# ---------------------------------------------------------------------------
# Identity and table contracts
# ---------------------------------------------------------------------------

SessionKey = str
RunId = str
SessionId = str
SessionRef = tuple[RunId, SessionId]
KeyToRef = Mapping[SessionKey, SessionRef]
MutableKeyToRef = Dict[SessionKey, SessionRef]
EntityKey = str
AggregationKey = str

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

EVENTS_REQUIRED_COLUMNS = (
    SESSION_KEY_COL,
    RUN_ID_COL,
    SESSION_ID_COL,
    SCHEMA_ID_COL,
    EVENT_ID_COL,
    SIGNAL_COL,
)

METRICS_REQUIRED_ID_COLUMNS = (
    SESSION_KEY_COL,
    RUN_ID_COL,
    SESSION_ID_COL,
    SCHEMA_ID_COL,
    EVENT_ID_COL,
)


class SessionSelection(TypedDict):
    """One selected session reference from the selector."""

    run_id: str
    session_id: str


class SessionArtifacts(TypedDict):
    """Minimal per-session artifact payload used by widgets."""

    df: pd.DataFrame
    meta: Dict[str, Any]


@dataclass(frozen=True)
class SelectionSnapshot:
    """Stable snapshot of selector scope consumed by widget builders."""

    key_to_ref: MutableKeyToRef
    events_index_df: pd.DataFrame

    def session_keys(self) -> list[str]:
        return sorted(map(str, self.key_to_ref.keys()))


# ---------------------------------------------------------------------------
# Registry variability contracts
# ---------------------------------------------------------------------------

RegistryPolicy = Literal["union", "intersection", "strict"]
EventSchemaPolicy = RegistryPolicy
EntityKind = Literal["session", "aggregation"]


@dataclass(frozen=True)
class RegistryResolutionConfig:
    """Policy for handling registry differences across selected sessions."""

    policy: RegistryPolicy = "union"
    include_qc: bool = False


class SignalUniverse(TypedDict):
    """Resolved signal availability across selected sessions."""

    by_session: Dict[SessionKey, list[str]]
    union: list[str]
    intersection: list[str]


# ---------------------------------------------------------------------------
# Entity scope contracts (sessions + persisted aggregations)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AggregationDefinition:
    """Persisted aggregation definition."""

    aggregation_key: AggregationKey
    title: str
    member_session_keys: tuple[SessionKey, ...]
    registry_policy: RegistryPolicy = "union"
    event_schema_policy: EventSchemaPolicy = "union"
    created_at_utc: str = ""
    updated_at_utc: str = ""
    note: str | None = None


@dataclass(frozen=True)
class ScopeEntity:
    """Selectable scope entity: physical session or aggregation."""

    entity_key: EntityKey
    kind: EntityKind
    label: str
    member_session_keys: tuple[SessionKey, ...]


@dataclass(frozen=True)
class EntitySelectionSnapshot:
    """Resolved entity selection for widget scope consumers."""

    selected_entities: list[ScopeEntity]
    entity_to_effective_members: Dict[EntityKey, list[SessionKey]]
    expanded_session_keys: list[SessionKey]
    key_to_ref: MutableKeyToRef
    events_index_df: pd.DataFrame

    def selected_entity_keys(self) -> list[EntityKey]:
        return [str(e.entity_key) for e in self.selected_entities]


@dataclass(frozen=True)
class PersistedEntityScopeSelection:
    """Persisted user selection of scope entities."""

    artifacts_root: str
    saved_at_utc: str
    selected_entity_keys: tuple[EntityKey, ...]
    selected_entity_kinds: Dict[EntityKey, EntityKind]
    selected_labels: Dict[EntityKey, str]


@dataclass(frozen=True)
class PersistedEntityScopeLoadResult:
    """Resolved persisted scope selection against current artifacts/aggregations."""

    snapshot: EntitySelectionSnapshot
    warnings: list[str]
    source: PersistedEntityScopeSelection


# ---------------------------------------------------------------------------
# Loader and selector interfaces
# ---------------------------------------------------------------------------


@runtime_checkable
class ArtifactStoreLike(Protocol):
    """Minimal store protocol required by widget loaders."""

    def session_dir(self, run_id: str, session_id: str) -> Any: ...

    def read_df(self, path: Any, *, columns: list[str] | None = None) -> pd.DataFrame: ...

    def read_json(self, path: Any) -> Dict[str, Any]: ...


@runtime_checkable
class SessionLoader(Protocol):
    """Session loader contract: session_key -> {df, meta}."""

    def __call__(self, session_key: str) -> SessionArtifacts: ...


@runtime_checkable
class SelectedEventsLoader(Protocol):
    """Load events across selected sessions, stamping identity columns."""

    def __call__(self, store: ArtifactStoreLike, *, key_to_ref: KeyToRef) -> pd.DataFrame: ...


@runtime_checkable
class SelectedMetricsLoader(Protocol):
    """Load metrics across selected sessions, stamping identity columns."""

    def __call__(self, store: ArtifactStoreLike, *, key_to_ref: KeyToRef) -> pd.DataFrame: ...


class SessionSelectorCoreHandle(TypedDict):
    """Required selector handle contract consumed by widgets/rebuilders."""

    ui: Any
    store: ArtifactStoreLike
    get_selected: Callable[[], list[SessionSelection]]
    get_key_to_ref: Callable[[], MutableKeyToRef]
    get_events_index_df: Callable[[], pd.DataFrame]


class SessionSelectorHandle(SessionSelectorCoreHandle, total=False):
    """Optional selector extras used by attach/detach refresh wiring."""

    run_dd: Any
    sessions_sel: Any
    out: Any
    entities_sel: Any
    show_ids_cb: Any
    autosave_cb: Any
    refresh_signal: Any
    get_selected_entities: Callable[[], list[ScopeEntity]]
    get_entity_snapshot: Callable[[], EntitySelectionSnapshot]
    save_selection: Callable[[], PersistedEntityScopeSelection]
    load_selection: Callable[[], PersistedEntityScopeLoadResult]


def entity_snapshot_from_handle(sel: Mapping[str, Any]) -> EntitySelectionSnapshot:
    """Create an EntitySelectionSnapshot from a selector handle dict."""

    get_entity_snapshot = sel.get("get_entity_snapshot")
    if callable(get_entity_snapshot):
        snapshot = get_entity_snapshot()
        if isinstance(snapshot, EntitySelectionSnapshot):
            return EntitySelectionSnapshot(
                selected_entities=list(snapshot.selected_entities),
                entity_to_effective_members={
                    str(k): list(map(str, v))
                    for k, v in dict(snapshot.entity_to_effective_members).items()
                },
                expanded_session_keys=list(map(str, snapshot.expanded_session_keys)),
                key_to_ref=dict(snapshot.key_to_ref),
                events_index_df=snapshot.events_index_df.copy(),
            )
        raise ValueError("get_entity_snapshot() must return an EntitySelectionSnapshot")

    # Backwards-compatible fallback: project session selection to session entities.
    core = selection_snapshot_from_handle(sel)
    entities = [
        ScopeEntity(
            entity_key=str(sk),
            kind="session",
            label=str(sk),
            member_session_keys=(str(sk),),
        )
        for sk in core.session_keys()
    ]
    members = {str(sk): [str(sk)] for sk in core.session_keys()}
    return EntitySelectionSnapshot(
        selected_entities=entities,
        entity_to_effective_members=members,
        expanded_session_keys=core.session_keys(),
        key_to_ref=dict(core.key_to_ref),
        events_index_df=core.events_index_df.copy(),
    )


def selection_snapshot_from_handle(sel: Mapping[str, Any]) -> SelectionSnapshot:
    """Create a SelectionSnapshot from a selector handle dict."""

    get_entity_snapshot = sel.get("get_entity_snapshot")
    if callable(get_entity_snapshot):
        entity_snapshot = entity_snapshot_from_handle(sel)
        return SelectionSnapshot(
            key_to_ref=dict(entity_snapshot.key_to_ref),
            events_index_df=entity_snapshot.events_index_df.copy(),
        )

    get_key_to_ref = sel.get("get_key_to_ref")
    get_events_index_df = sel.get("get_events_index_df")
    if not callable(get_key_to_ref) or not callable(get_events_index_df):
        raise ValueError(
            "selector handle must provide callable 'get_key_to_ref' and 'get_events_index_df'"
        )

    key_to_ref = dict(get_key_to_ref())
    events_index_df = get_events_index_df()
    if not isinstance(events_index_df, pd.DataFrame):
        raise ValueError("get_events_index_df() must return a pandas DataFrame")

    return SelectionSnapshot(key_to_ref=key_to_ref, events_index_df=events_index_df.copy())


# ---------------------------------------------------------------------------
# Widget/rebuild contracts
# ---------------------------------------------------------------------------

RebuildFn = Callable[[], None]


class WidgetHandle(TypedDict, total=False):
    """Notebook-facing widget constructor return shape."""

    ui: Any
    root: Any
    out: Any
    controls: Dict[str, Any]
    cache: Dict[str, Any]
    state: Dict[str, Any]
    viz_df: pd.DataFrame
    refresh: RebuildFn


class RebuilderHandle(TypedDict):
    """Notebook-facing rebuilder return shape."""

    out: Any
    rebuild: RebuildFn
    state: Dict[str, Any]


class RefreshHandle(TypedDict):
    """Handle returned by selector-to-widget refresh attachment."""

    detach: Callable[[], None]
    trigger: RebuildFn


@runtime_checkable
class SnapshotWidgetBuilder(Protocol):
    """Builder that constructs a widget from a selector snapshot."""

    def __call__(self, *, sel: SessionSelectorHandle, snapshot: SelectionSnapshot) -> WidgetHandle: ...
