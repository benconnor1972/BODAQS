# bodaqs_analysis/widgets/session_window_browser_widget.py
# -*- coding: utf-8 -*-
"""
Session Window Browser (v0+) — single Plotly FigureWidget with x-axis rangeslider driving a linked detail view,
with event trigger overlays (hover metrics) and selector-driven rebuilding.

Key features:
- Consumes selector scope but enforces a SINGLE active session within the widget.
- Single figure:
  - One x-axis with native rangeslider.
- Detail y-axis can be frozen (computed per session + selected detail signals).
- Events: multi-select event types (schema_id/event_type), markers on fixed lane,
  hover shows trigger time + selected numeric metrics (events<->metrics joined 1:1).
- Marks: optional overlay from session df column 'mark' as cross markers with stable color.
- Bookmarks: persisted to a per-user local JSON store via BookmarkStore.

Requires:
  - plotly (FigureWidget requires anywidget + jupyterlab widget manager configured)
  - ipywidgets, pandas, numpy
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import ipywidgets as W
from IPython.display import display, clear_output, Javascript

import plotly.graph_objects as go

# Local per-user bookmark persistence
from bodaqs_analysis.bookmarks import BookmarkStore, check_drift, coerce_restore_view
from bodaqs_analysis.widgets.contracts import (
    EVENT_ID_COL,
    SCHEMA_ID_COL,
    SESSION_ID_COL,
    SESSION_KEY_COL,
    RebuilderHandle,
    SessionLoader,
    SessionSelectorHandle,
    WidgetHandle,
    selection_snapshot_from_handle,
)
from bodaqs_analysis.widgets.session_window_bookmarks import (
    build_bookmark_options,
    deep_get,
    next_default_bookmark_title,
)
from bodaqs_analysis.widgets.session_window_data import (
    build_event_type_pair_options,
    compute_detail_y_range,
    derive_signal_options,
    load_optional_df,
    merge_events_metrics,
    require_session,
)
from bodaqs_analysis.widgets.session_window_plot import (
    build_event_hovertext,
    event_color_for_pair,
    init_session_window_figure,
)
from bodaqs_analysis.widgets.time_selection import SessionTimeSelection, make_session_time_selection

EVENT_SIGNAL_COL = "signal_col"  # required by events table contract

# -----------------------------
# Utilities
# -----------------------------

def _coerce_list(x) -> List[Any]:
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]


def _downsample_indices(n: int, max_points: int) -> np.ndarray:
    """Evenly spaced indices (simple, robust)."""
    if max_points <= 0 or n <= max_points:
        return np.arange(n, dtype=int)
    return np.linspace(0, n - 1, num=int(max_points), dtype=int)


def _to_numeric_series(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(df[col], errors="coerce")


_SIGNAL_PALETTE = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]


def _stable_color_for_signal(sig: str) -> str:
    """
    Deterministic mapping from signal name -> palette color.
    Stable across runs within a Python process and across add/remove of traces.
    """
    # FNV-1a 32-bit (stable, unlike Python's built-in hash which is salted)
    h = 2166136261
    for ch in (sig or ""):
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return _SIGNAL_PALETTE[h % len(_SIGNAL_PALETTE)]

def _event_key(et: str, sig: str) -> str:
    # stable string key for widget selection value
    return f"{et}||{sig}"

def _split_event_key(k: str) -> Tuple[str, str]:
    # safe split for "et||sig"
    if not isinstance(k, str) or "||" not in k:
        return ("", "")
    et, sig = k.split("||", 1)
    return (et, sig)
    
# -----------------------------
# Main widget
# -----------------------------

def make_session_window_browser_widget_for_loader(
    *,
    events_index_df: pd.DataFrame,
    session_loader: SessionLoader,
    # optional loaders for events/metrics
    events_loader: Optional[Callable[[str], pd.DataFrame]] = None,
    metrics_loader: Optional[Callable[[str], pd.DataFrame]] = None,
    # keys / columns
    session_key_col: str = SESSION_KEY_COL,
    session_id_col: str = SESSION_ID_COL,
    event_id_col: str = EVENT_ID_COL,
    event_type_col: str = SCHEMA_ID_COL,
    trigger_time_col: str = "trigger_time_s",
    time_col: str = "time_s",
    selection_model: Optional[SessionTimeSelection] = None,
    # perf
    detail_max_points: int = 8000,
    auto_display: bool = False,
) -> WidgetHandle:
    """
    Build the Session Window Browser widget.

    - sessions discovered from events_index_df[session_key_col]
    - session_loader loads a single session dict with keys: "df", "meta"
    - events_loader / metrics_loader return per-session frames
    - bookmarks are persisted via BookmarkStore (per-user local file)
    """
    if events_index_df is None or len(events_index_df) == 0:
        raise ValueError("events_index_df is empty")
    if session_key_col not in events_index_df.columns:
        raise ValueError(f"events_index_df must contain {session_key_col!r} column")

    session_keys = sorted(events_index_df[session_key_col].dropna().astype(str).unique().tolist())
    if not session_keys:
        raise ValueError("No session keys found in events_index_df")

    # ---------------- UI controls ----------------
    session_title = W.HTML("Session")
    w_session = W.Dropdown(
        options=session_keys,
        value=session_keys[0],
        description="",
        layout=W.Layout(width="380px"),
    )

    event_types_title = W.HTML("Event types")
    w_event_types = W.SelectMultiple(
        options=[],
        value=(),
        description="",
        rows=6,
        layout=W.Layout(width="380px"),
    )
    event_types_hint = W.HTML("<span style='color:#666; font-size: 90%'>Select one or more</span>")

    # Marks toggle (default True)
    w_show_marks = W.Checkbox(value=True, description="Show marks", layout=W.Layout(width="220px"))

    detail_title = W.HTML("Detail signals")
    w_detail_signals = W.SelectMultiple(options=[], value=(), description="", rows=8, layout=W.Layout(width="380px"))
    w_detail_autodown = W.Checkbox(value=True, description="Auto downsample detail", layout=W.Layout(width="220px"))

    # Bookmark controls (persisted)
    w_bm_name = W.Text(value="", description="Name:", layout=W.Layout(width="450px"))
    w_bm_comment = W.Text(value="", description="Comment:", layout=W.Layout(width="450px"))
    b_save = W.Button(description="Save", button_style="", layout=W.Layout(width="120px"))
    b_delete = W.Button(description="Delete", button_style="", layout=W.Layout(width="120px"))
    b_load = W.Button(description="Load", button_style="", layout=W.Layout(width="120px"))
    w_bm_list = W.Select(
        options=[("(New bookmark…)", "")],
        value="",
        description="Saved:",
        rows=8,
        layout=W.Layout(width="450px"),
    )

    bm_status = W.Output(layout=W.Layout(width="450px"))

    DESC_PAD = "90px"

    # ---------------- Bookmark store ----------------
    bm_store = BookmarkStore()
    try:
        bm_store.load()
    except Exception as e:
        with bm_status:
            print(f"[bookmarks] Failed to load store: {e!r}")

    # ---------------- state ----------------
    state: Dict[str, Any] = {
        "session": None,
        "df": None,
        "registry_cols": None,
        "numeric_cols": None,
        "detail_y_range": None,
        # events/metrics (per current session)
        "events_df": None,
        "metrics_df": None,
        "events_merged": None,
        "event_color_map": {},
        # bookmarks persistence
        "bookmark_store": bm_store,
        "updating": False,  # guard recursion
        "fig": None,
        # marks
        "mark_col": "mark",
        "selection_model": selection_model or make_session_time_selection(),
        "selection_sync_active": False,
    }

    # stable mark styling
    MARK_COLOR = "#111111"  # stable / fixed
    MARK_SYMBOL = "x"       # cross
    MARK_SIZE = 7

    # ---------------- Plotly figure ----------------
    fig = go.FigureWidget()
    state["fig"] = fig
    init_session_window_figure(fig)

    # ---------------- data loading ----------------

    def _load_session(session_key: str) -> Dict[str, Any]:
        return require_session(
            session_loader=session_loader,
            session_key=str(session_key),
            time_col=time_col,
        )

    def _load_events_for_session(session_key: str) -> pd.DataFrame:
        return load_optional_df(loader=events_loader, session_key=str(session_key))

    def _load_metrics_for_session(session_key: str) -> pd.DataFrame:
        return load_optional_df(loader=metrics_loader, session_key=str(session_key))

    def _merge_events_metrics(events_df: pd.DataFrame, metrics_df: pd.DataFrame) -> pd.DataFrame:
        return merge_events_metrics(
            events_df=events_df,
            metrics_df=metrics_df,
            session_id_col=session_id_col,
            event_id_col=event_id_col,
        )

    # ---------------- signal dropdown rebuild ----------------

    def _rebuild_signal_dropdowns(sess: dict):
        prev_detail = tuple(map(str, _coerce_list(w_detail_signals.value)))
        result = derive_signal_options(
            session=sess,
            prev_detail=prev_detail,
            time_col=time_col,
            preferred_unit="mm",
        )

        state["_registry"] = result.registry
        state["registry_cols"] = result.registry_cols
        state["numeric_cols"] = result.numeric_cols_sorted
        state["detail_y_range"] = result.detail_y_range

        w_detail_signals.options = result.numeric_cols_sorted
        w_detail_signals.value = result.selected_detail

    # ---------------- event UI rebuild ----------------

    def _rebuild_event_type_options(merged: pd.DataFrame):
        opts = build_event_type_pair_options(
            merged=merged,
            event_type_col=event_type_col,
            event_signal_col=EVENT_SIGNAL_COL,
            key_builder=_event_key,
        )
        if not opts:
            w_event_types.options = []
            w_event_types.value = ()
            return

        prev = tuple(map(str, _coerce_list(w_event_types.value)))
        w_event_types.options = opts

        valid = {v for _, v in opts}
        kept = tuple([v for v in prev if v in valid])
        w_event_types.value = kept


    def _build_event_hovertext(row: pd.Series, *, max_metrics: int = 10) -> str:
        return build_event_hovertext(
            row=row,
            event_type_col=event_type_col,
            event_signal_col=EVENT_SIGNAL_COL,
            trigger_time_col=trigger_time_col,
            max_metrics=max_metrics,
        )

    def _event_color_for_pair(et: str, sig: str) -> str:
        cmap = state.get("event_color_map") or {}
        color = event_color_for_pair(
            color_map=cmap,
            event_type=str(et),
            signal=str(sig),
        )
        state["event_color_map"] = cmap
        return color


    # ---------------- plotting ----------------

    def _get_current_window() -> Tuple[float, float]:
        r = fig.layout.xaxis.range
        if r is None or len(r) != 2:
            df_ = state["df"]
            t = _to_numeric_series(df_, time_col).to_numpy(dtype=float)
            t = t[np.isfinite(t)]
            if len(t) == 0:
                return (0.0, 0.0)
            return (float(t.min()), float(t.max()))
        return (float(r[0]), float(r[1]))

    def _current_lane_y() -> float:
        """
        Fixed y position based on current y-range (or frozen range).
        """
        yr = fig.layout.yaxis.range
        if yr is None or len(yr) != 2:
            yr2 = state.get("detail_y_range")
            if yr2 is not None:
                yr = list(yr2)
        if yr is None or len(yr) != 2:
            yr = [0.0, 1.0]

        y0, y1 = float(yr[0]), float(yr[1])
        if y1 == y0:
            y1 = y0 + 1.0
        span = y1 - y0
        return y0 + 0.03 * span

    def _add_event_markers(*, t0: Optional[float], t1: Optional[float], for_detail: bool):
        merged = state.get("events_merged")
        if merged is None or merged.empty:
            return
        if trigger_time_col not in merged.columns or event_type_col not in merged.columns:
            return

        sel_keys = set(map(str, _coerce_list(w_event_types.value)))
        if not sel_keys:
            return

        sel_pairs = set()
        for k in sel_keys:
            et, sig = _split_event_key(k)
            if et and sig:
                sel_pairs.add((et, sig))

        if not sel_pairs:
            return

        m = merged.copy()
        m[event_type_col] = m[event_type_col].astype(str)
        m[EVENT_SIGNAL_COL] = m[EVENT_SIGNAL_COL].astype(str)

        tt = pd.to_numeric(m[trigger_time_col], errors="coerce")
        m = m[np.isfinite(tt)]
        m["_tt"] = tt.astype(float)

        # window filter for detail
        if for_detail and (t0 is not None) and (t1 is not None):
            a, b = float(t0), float(t1)
            if b < a:
                a, b = b, a
            m = m[(m["_tt"] >= a) & (m["_tt"] <= b)]

            # keep within full session extents
            t_full = _to_numeric_series(state["df"], time_col).to_numpy(dtype=float) if state.get("df") is not None else None
            if t_full is not None:
                t_full = t_full[np.isfinite(t_full)]
                if t_full.size:
                    tmin, tmax = float(t_full.min()), float(t_full.max())
                    m = m[(m["_tt"] >= tmin) & (m["_tt"] <= tmax)]

        # pair filter
        m = m[m.apply(lambda r: (r[event_type_col], r[EVENT_SIGNAL_COL]) in sel_pairs, axis=1)]
        if m.empty:
            return

        y_mark = _current_lane_y()

        # group keys sorted for stable trace ordering
        keys = sorted(set(zip(m[event_type_col], m[EVENT_SIGNAL_COL])))

        for et, sig in keys:
            sub = m[(m[event_type_col] == et) & (m[EVENT_SIGNAL_COL] == sig)]
            xs = sub["_tt"].to_numpy(dtype=float)
            ys = np.full_like(xs, y_mark, dtype=float)

            hover = [_build_event_hovertext(r) for _, r in sub.iterrows()]

            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    mode="markers",
                    marker=dict(size=7, color=_event_color_for_pair(et, sig), symbol="circle"),
                    hovertemplate="%{text}<extra></extra>",
                    text=hover,
                    showlegend=True,
                    name=f"event: {et} — {sig}",
                    cliponaxis=False,
                )
            )

    def _add_mark_markers(*, t0: Optional[float], t1: Optional[float], for_detail: bool):
        """
        Marks come from session df column 'mark' (truthy/non-zero).
        Render as cross markers with stable colour.
        """
        if not bool(w_show_marks.value):
            return

        df_ = state.get("df")
        if df_ is None or df_.empty:
            return

        mark_col = state.get("mark_col") or "mark"
        if mark_col not in df_.columns:
            return
        if time_col not in df_.columns:
            return

        mk = pd.to_numeric(df_[mark_col], errors="coerce").to_numpy(dtype=float)
        tt = pd.to_numeric(df_[time_col], errors="coerce").to_numpy(dtype=float)

        m = np.isfinite(tt) & np.isfinite(mk) & (mk != 0)
        if for_detail and (t0 is not None) and (t1 is not None):
            a, b = float(t0), float(t1)
            if b < a:
                a, b = b, a
            m = m & (tt >= a) & (tt <= b)

        if not m.any():
            return

        xs = tt[m].astype(float)
        y_mark = _current_lane_y()
        ys = np.full_like(xs, y_mark, dtype=float)

        text = [f"mark<br>t: {x:.3f}s" for x in xs]

        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="markers",
                marker=dict(size=MARK_SIZE, color=MARK_COLOR, symbol=MARK_SYMBOL),
                hovertemplate="%{text}<extra></extra>",
                text=text,
                showlegend=True,
                name="mark",
                cliponaxis=False,
            )
        )

    def _selection_snapshot() -> dict[str, Any]:
        selection = state.get("selection_model")
        return selection.snapshot() if isinstance(selection, SessionTimeSelection) else {}

    def _set_selection(
        *,
        session_key: Optional[str] = None,
        window: Optional[Tuple[Optional[float], Optional[float]]] = None,
        selected_time_s: Any = None,
        set_selected_time: bool = False,
    ) -> None:
        selection = state.get("selection_model")
        if not isinstance(selection, SessionTimeSelection):
            return
        state["selection_sync_active"] = True
        try:
            selection.update_state(
                session_key=session_key,
                window_t0_s=None if window is None else window[0],
                window_t1_s=None if window is None else window[1],
                selected_time_s=selected_time_s,
                set_selected_time=set_selected_time,
                source="session_window_browser",
            )
        finally:
            state["selection_sync_active"] = False

    def _apply_selection_shapes() -> None:
        snap = _selection_snapshot()
        selected_time = snap.get("selected_time_s") if snap.get("session_key") == str(w_session.value) else None
        shapes = []
        if selected_time is not None and np.isfinite(float(selected_time)):
            x = float(selected_time)
            shapes.append(
                {
                    "type": "line",
                    "xref": "x",
                    "yref": "paper",
                    "x0": x,
                    "x1": x,
                    "y0": 0.0,
                    "y1": 1.0,
                    "line": {"color": "#f59e0b", "width": 2},
                }
            )
        fig.layout.shapes = tuple(shapes)

    def _attach_point_pick_callback(trace: go.Scatter) -> None:
        def _on_click(this_trace: go.Scatter, points: Any, _state: Any) -> None:
            if not points.point_inds:
                return
            idx = int(points.point_inds[0])
            if idx < 0 or idx >= len(this_trace.x):
                return
            try:
                picked_t = float(this_trace.x[idx])
            except Exception:
                return
            _set_selection(session_key=str(w_session.value), selected_time_s=picked_t, set_selected_time=True)
            _apply_selection_shapes()

        trace.on_click(_on_click, append=False)

    def _apply_all_traces(df_: pd.DataFrame, *, preserve_current_window: bool = True):
        if df_ is None or len(df_) == 0:
            with fig.batch_update():
                fig.data = ()
                fig.layout.shapes = ()
            return

        # Full-session extent (used to pin rangeslider to full session)
        full_range = None
        try:
            t_full2 = _to_numeric_series(df_, time_col).to_numpy(dtype=float)
            t_full2 = t_full2[np.isfinite(t_full2)]
            if t_full2.size:
                full_range = (float(t_full2.min()), float(t_full2.max()))
        except Exception:
            full_range = None

        prev_range = None
        if preserve_current_window:
            try:
                r = fig.layout.xaxis.range
                if r is not None and len(r) == 2 and r[0] is not None and r[1] is not None:
                    prev_range = (float(r[0]), float(r[1]))
            except Exception:
                prev_range = None
        if prev_range is None:
            prev_range = full_range


        sel = tuple(map(str, _coerce_list(w_detail_signals.value)))
        sel = tuple([c for c in sel if c in df_.columns])

        df_plot = df_
        if w_detail_autodown.value and len(df_plot) > detail_max_points:
            idx = _downsample_indices(len(df_plot), detail_max_points)
            df_plot = df_plot.iloc[idx].copy()

        t = _to_numeric_series(df_plot, time_col).to_numpy(dtype=float)

        with fig.batch_update():
            fig.data = ()  # rebuild once per control change

            for sig in sel:
                y = _to_numeric_series(df_plot, sig).to_numpy(dtype=float)
                fig.add_trace(
                    go.Scatter(
                        x=t,
                        y=y,
                        mode="lines",
                        name=sig,
                        line=dict(width=1.3, color=_stable_color_for_signal(sig)),
                        showlegend=True,
                    )
                )
                _attach_point_pick_callback(fig.data[-1])

            yr = state.get("detail_y_range")
            if yr is not None:
                fig.layout.yaxis.range = list(yr)
                fig.layout.yaxis.autorange = False
            else:
                fig.layout.yaxis.autorange = True

            _add_event_markers(t0=None, t1=None, for_detail=False)
            _add_mark_markers(t0=None, t1=None, for_detail=False)

            # Keep the current visible window (xaxis.range) if it was set,
            # but ALWAYS keep the rangeslider showing the FULL session time range.
            if prev_range is not None:
                a, b = prev_range
                fig.layout.xaxis.autorange = False
                fig.layout.xaxis.range = [a, b]

            # Full-session extent for the rangeslider "mini-map"
            if full_range is not None:
                fa, fb = full_range
                if hasattr(fig.layout.xaxis, "rangeslider") and fig.layout.xaxis.rangeslider is not None:
                    fig.layout.xaxis.rangeslider.range = [fa, fb]

            _apply_selection_shapes()

    # ---------------- session refresh ----------------

    def _refresh_all_for_session(session_key: str):
        sess = _load_session(session_key)
        df_ = sess["df"]
        state["session"] = sess
        state["df"] = df_

        _rebuild_signal_dropdowns(sess)

        ev = _load_events_for_session(session_key)
        met = _load_metrics_for_session(session_key)
        merged = _merge_events_metrics(ev, met)

        state["events_df"] = ev
        state["metrics_df"] = met
        state["events_merged"] = merged

        _rebuild_event_type_options(merged)

        sel = tuple(map(str, _coerce_list(w_detail_signals.value)))
        state["detail_y_range"] = compute_detail_y_range(df_, sel)

        snap = _selection_snapshot()
        session_changed = snap.get("session_key") != str(session_key)
        df_time = _to_numeric_series(df_, time_col).to_numpy(dtype=float)
        df_time = df_time[np.isfinite(df_time)]
        default_window = None
        if df_time.size:
            default_window = (float(df_time.min()), float(df_time.max()))

        _apply_all_traces(df_, preserve_current_window=not session_changed)

        if snap.get("session_key") != str(session_key):
            _set_selection(
                session_key=str(session_key),
                window=default_window,
                selected_time_s=None,
                set_selected_time=True,
            )
        elif snap.get("window_t0_s") is None or snap.get("window_t1_s") is None:
            _set_selection(session_key=str(session_key), window=default_window)

        _rebuild_bookmark_list()  # refresh list on session change

    # ---------------- callbacks ----------------

    def _on_session_change(*_):
        if state["updating"]:
            return
        state["updating"] = True
        try:
            _refresh_all_for_session(str(w_session.value))
        finally:
            state["updating"] = False

    def _on_controls_change(*_):
        if state["updating"]:
            return
        df_ = state["df"]
        if df_ is None:
            return

        sel = tuple(map(str, _coerce_list(w_detail_signals.value)))
        state["detail_y_range"] = compute_detail_y_range(df_, sel)

        _apply_all_traces(df_)

    w_session.observe(_on_session_change, names="value")
    for w in (w_detail_signals, w_detail_autodown, w_event_types, w_show_marks):
        w.observe(_on_controls_change, names="value")

    def _on_xaxis_range_change(_layout: Any, xrange: Any) -> None:
        if state["selection_sync_active"]:
            return
        if xrange is None or len(xrange) != 2 or xrange[0] is None or xrange[1] is None:
            t0, t1 = _get_current_window()
        else:
            try:
                t0, t1 = float(xrange[0]), float(xrange[1])
            except Exception:
                return
        _set_selection(session_key=str(w_session.value), window=(t0, t1))

    fig.layout.on_change(_on_xaxis_range_change, ("xaxis", "range"))

    def _on_selection_model_change(change: Dict[str, Any]) -> None:
        if state["selection_sync_active"]:
            return
        owner = change.get("owner")
        source = str(getattr(owner, "source", "") or "")
        if source == "session_window_browser":
            return

        selection = state.get("selection_model")
        if not isinstance(selection, SessionTimeSelection):
            return

        target_session = selection.session_key
        if isinstance(target_session, str) and target_session in set(map(str, w_session.options)) and target_session != str(w_session.value):
            state["updating"] = True
            try:
                w_session.value = target_session
            finally:
                state["updating"] = False
            _refresh_all_for_session(str(w_session.value))
            return

        if selection.session_key == str(w_session.value):
            t0 = selection.window_t0_s
            t1 = selection.window_t1_s
            if t0 is not None and t1 is not None:
                state["selection_sync_active"] = True
                try:
                    fig.layout.xaxis.range = [float(t0), float(t1)]
                finally:
                    state["selection_sync_active"] = False
            _apply_selection_shapes()

    selection = state.get("selection_model")
    if isinstance(selection, SessionTimeSelection):
        for trait_name in ("session_key", "window_t0_s", "window_t1_s", "selected_time_s"):
            selection.observe(_on_selection_model_change, names=trait_name)

    # ---------------- bookmarks (persisted) ----------------

    def _deep_get(d: Dict[str, Any], path: Tuple[str, ...], default=None):
        return deep_get(d, path, default)

    def _next_default_bookmark_title(entries: List[Dict[str, Any]]) -> str:
        return next_default_bookmark_title(entries)


    def _rebuild_bookmark_list():
        store: BookmarkStore = state["bookmark_store"]
        sk = str(w_session.value)
        opts = build_bookmark_options(store=store, session_key=sk)
        w_bm_list.options = opts

        # keep current selection if still valid; else default to "new"
        cur = w_bm_list.value
        valid_ids = {v for _, v in opts}
        w_bm_list.value = cur if cur in valid_ids else ""


    def _selected_bookmark_entry() -> Optional[Dict[str, Any]]:
        bid = w_bm_list.value
        if not bid:
            return None
        store: BookmarkStore = state["bookmark_store"]
        return store.get(str(bid))


    def _save_bookmark(_btn):
        sess = state.get("session")
        df_ = state.get("df")
        if sess is None or df_ is None:
            return

        store: BookmarkStore = state["bookmark_store"]
        sk = str(w_session.value)

        # Current window + view state
        t0, t1 = _get_current_window()
        view = {
            "detail_signals": list(map(str, _coerce_list(w_detail_signals.value))),
            "event_types": list(map(str, _coerce_list(w_event_types.value))),
            "show_marks": bool(w_show_marks.value),
        }
        yr = state.get("detail_y_range")
        if yr is not None:
            view["y_lock"] = {"enabled": True, "range": [float(yr[0]), float(yr[1])]}

        # Determine save mode
        selected_id = w_bm_list.value  # if set => edit mode

        # Name/comment
        name = str(w_bm_name.value or "").strip()
        note = str(w_bm_comment.value or "").strip()

        try:
            entries = store.list(session_key=sk)

            if selected_id:
                # EDIT MODE: update the selected bookmark id
                bid = str(selected_id)
                patch = {
                    "title": name if name else None,
                    "note": note if note else None,
                    "window": {"t0": float(min(t0, t1)), "t1": float(max(t0, t1)), "units": "s"},
                    "view": dict(view),
                    "scope": dict((_selected_bookmark_entry() or {}).get("scope") or {}),
                }
                # Clean Nones
                if patch["title"] is None:
                    patch.pop("title")
                if patch["note"] is None:
                    patch.pop("note")

                store.update(bid, patch=patch)
                store.save()

                _rebuild_bookmark_list()
                w_bm_list.value = bid  # keep selection

                with bm_status:
                    clear_output(wait=True)
                    print("Updated.")
                return

            # NEW MODE: create new (or update-by-name if name exists)
            if not name:
                name = _next_default_bookmark_title(entries)

            # If name matches existing within this session, update that existing one instead of creating dup
            existing = None
            for e in entries:
                if str(e.get("title") or "").strip() == name:
                    existing = e
                    break

            if existing is not None and isinstance(existing.get("bookmark_id"), str):
                bid = existing["bookmark_id"]
                patch = {
                    "title": name,
                    "note": note if note else None,
                    "window": {"t0": float(min(t0, t1)), "t1": float(max(t0, t1)), "units": "s"},
                    "view": dict(view),
                }
                if patch["note"] is None:
                    patch.pop("note")
                store.update(bid, patch=patch)
                store.save()

                _rebuild_bookmark_list()
                w_bm_list.value = bid  # select it => now editing that bookmark

                with bm_status:
                    clear_output(wait=True)
                    print("Updated (matched name).")
                return

            # Otherwise: create a new bookmark
            bid = store.add_from_view(
                session=sess,
                session_key=sk,
                t0=float(t0),
                t1=float(t1),
                view=view,
                title=name,
                note=note,
                private=True,
                time_col=time_col,
            )
            store.save()

            _rebuild_bookmark_list()
            w_bm_list.value = bid

            # After NEW save: clear fields + deselect to encourage next "new" capture
            state["updating"] = True
            try:
                w_bm_name.value = ""
                w_bm_comment.value = ""
                w_bm_list.value = ""
            finally:
                state["updating"] = False

            with bm_status:
                clear_output(wait=True)
                print(f"Saved as {name!r}.")

        except Exception as e:
            with bm_status:
                clear_output(wait=True)
                print(f"[bookmarks] Save failed: {e!r}")


    def _load_bookmark(_btn):
        entry = _selected_bookmark_entry()
        if entry is None:
            return

        target_session_key = str(_deep_get(entry, ("scope", "session_key"), ""))
        if target_session_key and str(w_session.value) != target_session_key:
            state["updating"] = True
            try:
                w_session.value = target_session_key
            finally:
                state["updating"] = False
            _refresh_all_for_session(target_session_key)

        sess = state.get("session")
        if sess is None:
            return

        # Drift warnings
        warns = []
        try:
            warns = check_drift(entry, session=sess, time_col_default=time_col)
        except Exception:
            warns = []
        with bm_status:
            clear_output(wait=True)
            if warns:
                print("Warnings:")
                for w in warns:
                    print(" -", w)

        # Restore view (safe intersections)
        avail_signals = list(map(str, w_detail_signals.options))
        avail_event_types = list(map(str, w_event_types.options))
        view = coerce_restore_view(entry, available_signals=avail_signals, available_event_types=avail_event_types)

        state["updating"] = True
        try:
            ds = view.get("detail_signals")
            if isinstance(ds, list):
                kept = tuple([s for s in ds if s in avail_signals])
                w_detail_signals.value = kept if kept else ()

            et = view.get("event_types")
            if isinstance(et, list):
                kept_et = tuple([s for s in et if s in avail_event_types])
                w_event_types.value = kept_et if kept_et else ()

            sm = view.get("show_marks")
            if isinstance(sm, bool):
                w_show_marks.value = sm

            t0 = float(_deep_get(entry, ("window", "t0"), 0.0))
            t1 = float(_deep_get(entry, ("window", "t1"), 0.0))
            fig.layout.xaxis.range = [t0, t1]
        finally:
            state["updating"] = False

        df_ = state["df"]
        sel = tuple(map(str, _coerce_list(w_detail_signals.value)))
        state["detail_y_range"] = compute_detail_y_range(df_, sel) if df_ is not None else None
        _apply_all_traces(df_)

    def _delete_bookmark(_btn):
        bid = w_bm_list.value
        if not bid:
            return
        store: BookmarkStore = state["bookmark_store"]
        try:
            ok = store.delete(str(bid))
            if ok:
                store.save()
            _rebuild_bookmark_list()
            with bm_status:
                clear_output(wait=True)
                print("Deleted." if ok else "Not found.")
        except Exception as e:
            with bm_status:
                clear_output(wait=True)
                print(f"[bookmarks] Delete failed: {e!r}")

    def _on_bookmark_select(change):
        if state.get("updating"):
            return

        bid = change.get("new")

        if not bid:
            # "" => New mode
            state["updating"] = True
            try:
                w_bm_name.value = ""
                w_bm_comment.value = ""
            finally:
                state["updating"] = False

            with bm_status:
                clear_output(wait=True)
            return

        entry = _selected_bookmark_entry()
        if not entry:
            return

        state["updating"] = True
        try:
            w_bm_name.value = str(entry.get("title") or "")
            w_bm_comment.value = str(entry.get("note") or "")
        finally:
            state["updating"] = False


    w_bm_list.observe(_on_bookmark_select, names="value")

    b_save.on_click(_save_bookmark)
    b_load.on_click(_load_bookmark)
    b_delete.on_click(_delete_bookmark)

    # ---------------- layout ----------------

    session_box = W.VBox([session_title, w_session], layout=W.Layout(gap="6px", width="450px"))

    top_controls_row = W.HBox(
        [session_box],
        layout=W.Layout(gap="40px", align_items="flex-start", justify_content="space-between", width="1200px"),
    )

    detail_box = W.VBox([detail_title, w_detail_signals, w_detail_autodown], layout=W.Layout(gap="6px", width="520px"))

    events_box = W.VBox(
        [event_types_title, event_types_hint, w_event_types, w_show_marks],
        layout=W.Layout(gap="6px", width="450px"),
    )

    bookmarks_box = W.VBox(
        [
            W.HTML("Bookmarks (per-user store)", layout=W.Layout(padding=f"0 0 0 {DESC_PAD}")),
            w_bm_name,
            w_bm_comment,
            W.HBox([b_save, b_load, b_delete], layout=W.Layout(gap="8px", padding=f"0 0 0 {DESC_PAD}")),
            w_bm_list,
            bm_status,
        ],
        layout=W.Layout(gap="6px"),
    )

    bottom_row = W.HBox([detail_box, events_box, bookmarks_box],
                        layout=W.Layout(gap="16px", align_items="flex-start", width="100%"))

    plot_row = W.VBox([fig], layout=W.Layout(width="100%"))

    root = W.VBox([top_controls_row, bottom_row, plot_row],
                  layout=W.Layout(gap="10px", width="100%"))

    def _force_plotly_resize(*, delays_ms: Optional[List[int]] = None) -> None:
        delays = [75, 250, 750] if delays_ms is None else [int(x) for x in delays_ms]
        display(Javascript(f"""
        (function() {{
            const delays = {delays!r};
            const resizeAll = function() {{
                try {{
                    const plots = document.querySelectorAll('.js-plotly-plot');
                    plots.forEach((gd) => {{
                        if (!window.Plotly) {{
                            return;
                        }}
                        Plotly.relayout(gd, {{'xaxis.rangeslider.visible': true}});
                        if (Plotly.Plots && Plotly.Plots.resize) {{
                            Plotly.Plots.resize(gd);
                        }}
                    }});
                }} catch (e) {{
                    console.warn("plotly resize failed", e);
                }}
            }};
            delays.forEach((delay) => setTimeout(resizeAll, delay));
        }})();
        """))

    def refresh() -> None:
        _refresh_all_for_session(str(w_session.value))

    refresh()

    if auto_display:
        display(root)
        _force_plotly_resize(delays_ms=[150, 450, 900])

    return {
        "root": root,
        "state": state,
        "fig": fig,
        "selection_model": state.get("selection_model"),
        "bookmark_store": bm_store,
        "refresh": refresh,
        "controls": {
            "session": w_session,
            "event_types": w_event_types,
            "show_marks": w_show_marks,
            "detail_signals": w_detail_signals,
            "detail_autodown": w_detail_autodown,
            "bookmark_name": w_bm_name,
            "bookmark_comment": w_bm_comment,
            "bookmark_list": w_bm_list,
        },
        "post_display": lambda: _force_plotly_resize(),
    }


def make_session_window_browser_rebuilder(
    *,
    sel: SessionSelectorHandle,
    out: Optional[W.Output] = None,
    session_key_col: str = SESSION_KEY_COL,
    session_id_col: str = SESSION_ID_COL,
    event_id_col: str = EVENT_ID_COL,
    event_type_col: str = SCHEMA_ID_COL,
    trigger_time_col: str = "trigger_time_s",
    time_col: str = "time_s",
    selection_model: Optional[SessionTimeSelection] = None,
    detail_max_points: int = 8000,
) -> RebuilderHandle:
    """
    Rebuild-on-selector-change wrapper (thin notebook cell pattern).
    """
    if out is None:
        out = W.Output()

    state: Dict[str, Any] = {"handles": None, "selection_model": selection_model or make_session_time_selection()}

    def rebuild() -> None:
        from bodaqs_analysis.widgets.loaders import (
            make_session_loader,
            load_all_events_for_selected,
            load_all_metrics_for_selected,
        )

        snapshot = selection_snapshot_from_handle(sel)
        store = sel["store"]
        key_to_ref = snapshot.key_to_ref
        events_index_df = snapshot.events_index_df

        if not key_to_ref:
            with out:
                clear_output(wait=True)
                print("No sessions available for the current selector scope.")
            state["handles"] = None
            return

        session_loader = make_session_loader(store=store, key_to_ref=key_to_ref)

        events_all = load_all_events_for_selected(store, key_to_ref=key_to_ref)
        metrics_all = load_all_metrics_for_selected(store, key_to_ref=key_to_ref)

        def _filter_by_session(df: pd.DataFrame, session_key: str) -> pd.DataFrame:
            if df is None or df.empty:
                return pd.DataFrame()
            if session_key_col in df.columns:
                return df[df[session_key_col].astype(str) == str(session_key)].copy()
            if session_id_col in df.columns:
                return df[df[session_id_col].astype(str) == str(session_key)].copy()
            return pd.DataFrame()

        def events_loader(session_key: str) -> pd.DataFrame:
            return _filter_by_session(events_all, session_key)

        def metrics_loader(session_key: str) -> pd.DataFrame:
            return _filter_by_session(metrics_all, session_key)

        with out:
            clear_output(wait=True)
            state["handles"] = make_session_window_browser_widget_for_loader(
                events_index_df=events_index_df,
                session_loader=session_loader,
                events_loader=events_loader,
                metrics_loader=metrics_loader,
                session_key_col=session_key_col,
                session_id_col=session_id_col,
                event_id_col=event_id_col,
                event_type_col=event_type_col,
                trigger_time_col=trigger_time_col,
                time_col=time_col,
                selection_model=state["selection_model"],
                detail_max_points=detail_max_points,
                auto_display=False,
            )
            h = state["handles"]
            root = h.get("root") or h.get("ui")
            if root is not None:
                display(root)
            post_display = h.get("post_display")
            if callable(post_display):
                post_display()

    rebuild()
    return {"out": out, "rebuild": rebuild, "state": state}



