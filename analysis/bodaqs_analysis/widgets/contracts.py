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

SESSION_KEY_COL = "session_key"
RUN_ID_COL = "run_id"
SESSION_ID_COL = "session_id"
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


def selection_snapshot_from_handle(sel: Mapping[str, Any]) -> SelectionSnapshot:
    """Create a SelectionSnapshot from a selector handle dict."""

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

