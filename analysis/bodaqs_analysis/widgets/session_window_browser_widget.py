# bodaqs_analysis/widgets/session_window_browser_widget.py
# -*- coding: utf-8 -*-
"""
Session Window Browser (v0+) — Plotly FigureWidget overview + linked detail window,
with event trigger overlays (hover metrics) and selector-driven rebuilding.

Key features:
- Consumes selector scope but enforces a SINGLE active session within the widget.
- Overview uses Plotly x-axis rangeslider (Option A) to select a time window.
- Detail plot updates dynamically as the window changes.
- Detail y-axis is frozen (computed per session + selected detail signals).
- Events: multi-select event types (schema_id/event_type), markers on fixed lane (yaxis2),
  hover shows trigger time + selected numeric metrics (events<->metrics joined 1:1).
- Bookmarks stored in memory only (not persisted).

Requires:
  - plotly (FigureWidget requires anywidget + jupyterlab widget manager configured)
  - ipywidgets, pandas, numpy
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import ipywidgets as W
from IPython.display import display, clear_output, Javascript

import plotly.graph_objects as go


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


def _infer_signal_cols_from_registry(session: dict) -> List[str]:
    """
    Pull candidate signal columns from session['meta']['signals'] keys.
    Assumes registry keys are df columns.
    """
    meta = (session or {}).get("meta") or {}
    reg = meta.get("signals") or {}
    if not isinstance(reg, dict):
        return []
    cols = []
    for k in reg.keys():
        if isinstance(k, str) and k.strip():
            cols.append(k.strip())
    return cols


def _filter_numeric_cols(df: pd.DataFrame, cols: Sequence[str], *, time_col: str) -> List[str]:
    out = []
    for c in cols:
        if c == time_col:
            continue
        if c not in df.columns:
            continue
        v = _to_numeric_series(df, c).to_numpy(dtype=float)
        if np.isfinite(v).any():
            out.append(c)
    return out


def _sort_cols_by_unit(cols: Sequence[str], registry: dict) -> List[str]:
    """Sort by registry unit, then by column name. Unknown units sort last."""
    def key(c: str):
        info = registry.get(c, {}) if isinstance(registry, dict) else {}
        unit = info.get("unit")
        unit = unit.strip() if isinstance(unit, str) else ""
        unit_sort = unit if unit else "~"
        return (unit_sort, c)
    return sorted(list(cols), key=key)


def _compute_y_range(df: pd.DataFrame, cols: Sequence[str]) -> Optional[Tuple[float, float]]:
    """Compute a stable y-range across the full session df for the selected columns."""
    vals = []
    for c in cols:
        if c not in df.columns:
            continue
        v = pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float)
        v = v[np.isfinite(v)]
        if v.size:
            vals.append(v)
    if not vals:
        return None
    lo = float(np.min([v.min() for v in vals]))
    hi = float(np.max([v.max() for v in vals]))
    if lo == hi:
        lo -= 1.0
        hi += 1.0
    # add a small pad
    span = hi - lo
    pad = 0.03 * span
    return (lo - pad, hi + pad)


# -----------------------------
# Bookmarks
# -----------------------------

@dataclass
class WindowBookmark:
    name: str
    comment: str
    session_key: str
    t0: float
    t1: float
    overview_signal: str
    detail_signals: Tuple[str, ...]
    selected_event_types: Tuple[str, ...]
    show_events_overview: bool
    show_events_detail: bool


# -----------------------------
# Main widget
# -----------------------------

def make_session_window_browser_widget_for_loader(
    *,
    events_index_df: pd.DataFrame,
    session_loader: Callable[[str], Dict[str, Any]],
    # optional loaders for events/metrics
    events_loader: Optional[Callable[[str], pd.DataFrame]] = None,
    metrics_loader: Optional[Callable[[str], pd.DataFrame]] = None,
    # keys / columns
    session_key_col: str = "session_key",
    session_id_col: str = "session_id",
    event_id_col: str = "event_id",
    event_type_col: str = "schema_id",
    trigger_time_col: str = "trigger_time_s",
    time_col: str = "time_s",
    # perf
    overview_max_points: int = 3000,
    detail_max_points: int = 8000,
) -> Dict[str, Any]:
    """
    Build the Session Window Browser widget.

    - sessions discovered from events_index_df[session_key_col]
    - session_loader loads a single session dict with keys: "df", "meta"
    - events_loader / metrics_loader return per-session frames
    - bookmarks stored in-memory only
    """
    if events_index_df is None or len(events_index_df) == 0:
        raise ValueError("events_index_df is empty")
    if session_key_col not in events_index_df.columns:
        raise ValueError(f"events_index_df must contain {session_key_col!r} column")

    session_keys = sorted(events_index_df[session_key_col].dropna().astype(str).unique().tolist())
    if not session_keys:
        raise ValueError("No session keys found in events_index_df")

    # ---------------- UI controls ----------------
    # Titles above (no description gutter)
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
    w_show_events_overview = W.Checkbox(value=True, description="Show events on overview", layout=W.Layout(width="350px"))
    w_show_events_detail = W.Checkbox(value=True, description="Show events on detail", layout=W.Layout(width="350px"))

    overview_title = W.HTML("Overview signal")
    w_overview_signal = W.Dropdown(options=[], description="", layout=W.Layout(width="380px"))

    detail_title = W.HTML("Detail signals")
    w_detail_signals = W.SelectMultiple(options=[], value=(), description="", rows=8, layout=W.Layout(width="380px"))
    w_detail_autodown = W.Checkbox(value=True, description="Auto downsample detail", layout=W.Layout(width="220px"))

    # Bookmark controls
    w_bm_name = W.Text(value="", description="Name:", layout=W.Layout(width="520px"))
    w_bm_comment = W.Text(value="", description="Comment:", layout=W.Layout(width="520px"))
    b_save = W.Button(description="Save", button_style="", layout=W.Layout(width="120px"))
    b_delete = W.Button(description="Delete", button_style="", layout=W.Layout(width="120px"))
    b_load = W.Button(description="Load", button_style="", layout=W.Layout(width="120px"))
    w_bm_list = W.Select(options=[], value=None, description="Saved:", rows=8, layout=W.Layout(width="520px"))

    # Align header/buttons with the Text input area (past the description gutter).
    DESC_PAD = "90px"

    out = W.Output()

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
        # bookmarks
        "bookmarks": [],  # List[WindowBookmark]
        "updating": False,  # guard recursion
        "overview_fig": None,
        "detail_fig": None,
    }

    # ---------------- Plotly figures ----------------
    fig_overview = go.FigureWidget()
    fig_detail = go.FigureWidget()
    state["overview_fig"] = fig_overview
    state["detail_fig"] = fig_detail

    def _init_figs():
        # Overview: thin/wide, with rangeslider
        fig_overview.layout = go.Layout(
            height=420,
            margin=dict(l=50, r=20, t=30, b=30),
            xaxis=dict(title="time (s)", rangeslider=dict(visible=True)),
            yaxis=dict(title="overview"),
            # Event lane: invisible secondary axis overlaid on y (0..1)
            yaxis2=dict(overlaying="y", range=[0, 1], visible=False),
            showlegend=False,
        )
        fig_overview.data = []
        fig_overview.layout.autosize = True

        # Detail: taller
        fig_detail.layout = go.Layout(
            height=420,
            margin=dict(l=50, r=20, t=30, b=40),
            xaxis=dict(title="time (s)"),
            yaxis=dict(title="value"),
            yaxis2=dict(overlaying="y", range=[0, 1], visible=False),
            legend=dict(orientation="h"),
        )
        fig_detail.data = []
        
        # ensure no hard width is set
        fig_overview.layout.width = None
        fig_detail.layout.width = None

        # ask plotly to be responsive (works in many setups; safe to try)
        try:
            fig_overview._config = dict(getattr(fig_overview, "_config", {}) or {}, responsive=True)
            fig_detail._config = dict(getattr(fig_detail, "_config", {}) or {}, responsive=True)
        except Exception:
            pass

    _init_figs()

    # ---------------- data loading ----------------

    def _load_session(session_key: str) -> Dict[str, Any]:
        sess = session_loader(str(session_key))
        if not isinstance(sess, dict):
            raise ValueError("session_loader must return a dict-like session")
        if "df" not in sess:
            raise ValueError("session missing required key 'df'")
        df = sess["df"]
        if not isinstance(df, pd.DataFrame):
            raise ValueError("session['df'] must be a pandas DataFrame")
        if time_col not in df.columns:
            raise ValueError(f"session['df'] must contain {time_col!r} column")
        return sess

    def _load_events_for_session(session_key: str) -> pd.DataFrame:
        if events_loader is None:
            return pd.DataFrame()
        df = events_loader(str(session_key))
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()

    def _load_metrics_for_session(session_key: str) -> pd.DataFrame:
        if metrics_loader is None:
            return pd.DataFrame()
        df = metrics_loader(str(session_key))
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()

    def _merge_events_metrics(events_df: pd.DataFrame, metrics_df: pd.DataFrame) -> pd.DataFrame:
        """
        1:1 join via (session_id, event_id) per metrics contract.
        """
        if events_df is None or events_df.empty:
            return pd.DataFrame()
        if metrics_df is None or metrics_df.empty:
            return events_df.copy()

        if session_id_col not in events_df.columns or event_id_col not in events_df.columns:
            return events_df.copy()
        if session_id_col not in metrics_df.columns or event_id_col not in metrics_df.columns:
            return events_df.copy()

        join_keys = [session_id_col, event_id_col]

        # Keep only non-duplicative metric cols
        metric_cols = [c for c in metrics_df.columns if c not in join_keys]
        merged = events_df.merge(metrics_df[join_keys + metric_cols], on=join_keys, how="left", suffixes=("", "_m"))
        return merged

    # ---------------- signal dropdown rebuild ----------------

    def _rebuild_signal_dropdowns(sess: dict):
        df = sess["df"]
        meta = (sess or {}).get("meta") or {}
        registry = meta.get("signals") or {}
        if not isinstance(registry, dict):
            registry = {}

        registry_cols = _infer_signal_cols_from_registry(sess)
        if not registry_cols:
            registry_cols = [c for c in df.columns if isinstance(c, str)]

        numeric_cols = _filter_numeric_cols(df, registry_cols, time_col=time_col)
        if not numeric_cols:
            numeric_cols = [c for c in df.columns if c != time_col and pd.api.types.is_numeric_dtype(df[c])]

        numeric_cols_sorted = _sort_cols_by_unit(numeric_cols, registry)

        # Overview: default to first unit == "mm" if possible
        prev_ov = w_overview_signal.value
        w_overview_signal.options = numeric_cols_sorted
        if prev_ov in numeric_cols_sorted:
            w_overview_signal.value = prev_ov
        else:
            mm_cols = [c for c in numeric_cols_sorted if (registry.get(c, {}).get("unit") == "mm")]
            w_overview_signal.value = (mm_cols[0] if mm_cols else (numeric_cols_sorted[0] if numeric_cols_sorted else None))

        # Detail: keep selected if possible; else default to overview
        prev_detail = tuple(map(str, _coerce_list(w_detail_signals.value)))
        w_detail_signals.options = numeric_cols_sorted
        kept = tuple([c for c in prev_detail if c in numeric_cols_sorted])
        w_detail_signals.value = kept if kept else ((w_overview_signal.value,) if w_overview_signal.value else ())

        state["registry_cols"] = registry_cols
        state["numeric_cols"] = numeric_cols_sorted

        # detail y-range based on selected signals (full session)
        sel = tuple(map(str, _coerce_list(w_detail_signals.value)))
        state["detail_y_range"] = _compute_y_range(df, sel)

    # ---------------- event UI rebuild ----------------

    def _rebuild_event_type_options(merged: pd.DataFrame):
        if merged is None or merged.empty or event_type_col not in merged.columns:
            w_event_types.options = []
            w_event_types.value = ()
            return

        opts = sorted(merged[event_type_col].dropna().astype(str).unique().tolist())
        prev = tuple(map(str, _coerce_list(w_event_types.value)))
        w_event_types.options = opts
        kept = tuple([x for x in prev if x in opts])
        # default: all selected
        w_event_types.value = kept if kept else tuple(opts)

    # ---------------- plotting ----------------

    def _set_overview_trace(df: pd.DataFrame, sig: str, *, registry: dict):
        t = _to_numeric_series(df, time_col).to_numpy(dtype=float)
        y = _to_numeric_series(df, sig).to_numpy(dtype=float)

        idx = _downsample_indices(len(df), overview_max_points)
        t2 = t[idx]
        y2 = y[idx]

        mask = np.isfinite(t2) & np.isfinite(y2)
        t2 = t2[mask]
        y2 = y2[mask]

        with fig_overview.batch_update():
            fig_overview.data = []
            fig_overview.add_trace(go.Scatter(x=t2, y=y2, mode="lines", line=dict(width=1), name=sig))
            fig_overview.layout.showlegend = False

            unit = ""
            info = registry.get(sig, {}) if isinstance(registry, dict) else {}
            u = info.get("unit")
            if isinstance(u, str) and u.strip():
                unit = u.strip()

            fig_overview.layout.yaxis.title = unit if unit else "value"

            # Initialize window if not set
            if fig_overview.layout.xaxis.range is None and len(t2) >= 2:
                lo = float(np.nanmin(t2))
                hi = float(np.nanmax(t2))
                span = hi - lo
                fig_overview.layout.xaxis.range = [lo + 0.10 * span, lo + 0.20 * span]

            # Events overlay
            if w_show_events_overview.value:
                _add_event_markers(fig_overview, t0=None, t1=None, for_detail=False)

    def _get_current_window() -> Tuple[float, float]:
        r = fig_overview.layout.xaxis.range
        if r is None or len(r) != 2:
            df = state["df"]
            t = _to_numeric_series(df, time_col).to_numpy(dtype=float)
            t = t[np.isfinite(t)]
            if len(t) == 0:
                return (0.0, 0.0)
            return (float(t.min()), float(t.max()))
        return (float(r[0]), float(r[1]))

    def _build_event_hovertext(row: pd.Series, *, max_metrics: int = 10) -> str:
        et = str(row.get(event_type_col, ""))
        t = row.get(trigger_time_col, None)
        bits = [f"type: {et}"]
        if t is not None and np.isfinite(pd.to_numeric(t, errors="coerce")):
            bits.append(f"t: {float(t):.3f}s")

        # Prefer metric columns by contract prefix m_
        metric_items: List[Tuple[str, float]] = []
        for c, v in row.items():
            if not isinstance(c, str):
                continue
            if not c.startswith("m_"):
                continue
            if isinstance(v, (int, float, np.integer, np.floating)) and np.isfinite(v):
                metric_items.append((c, float(v)))
        metric_items.sort(key=lambda x: x[0])

        for c, v in metric_items[:max_metrics]:
            bits.append(f"{c}: {v:.3g}")

        return "<br>".join(bits)

    def _event_color_for(et: str) -> str:
        cmap = state.get("event_color_map") or {}
        palette = [
            "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
            "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
        ]
        if et not in cmap:
            cmap[et] = palette[len(cmap) % len(palette)]
        state["event_color_map"] = cmap
        return cmap[et]

    def _add_event_markers(fig: go.FigureWidget, *, t0: Optional[float], t1: Optional[float], for_detail: bool):
        merged = state.get("events_merged")
        if merged is None or merged.empty:
            return
        if trigger_time_col not in merged.columns or event_type_col not in merged.columns:
            return

        sel_types = set(map(str, _coerce_list(w_event_types.value)))
        if not sel_types:
            return

        m = merged.copy()
        m[event_type_col] = m[event_type_col].astype(str)

        tt = pd.to_numeric(m[trigger_time_col], errors="coerce")
        m = m[np.isfinite(tt)]
        m["_tt"] = tt.astype(float)

        if for_detail and (t0 is not None) and (t1 is not None):
            a, b = float(t0), float(t1)
            if b < a:
                a, b = b, a
            m = m[(m["_tt"] >= a) & (m["_tt"] <= b)]

        m = m[m[event_type_col].isin(sel_types)]
        if m.empty:
            return

        # One trace per event type (clean legend, stable color)
        for et in sorted(m[event_type_col].unique()):
            sub = m[m[event_type_col] == et]
            xs = sub["_tt"].to_numpy(dtype=float)
            ys = np.full_like(xs, 0.02, dtype=float)  # fixed lane position below baseline
            hover = [_build_event_hovertext(r) for _, r in sub.iterrows()]

            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    yaxis="y2",
                    mode="markers",
                    name=f"event: {et}" if for_detail else et,
                    marker=dict(size=7, color=_event_color_for(et)),
                    hovertemplate="%{text}<extra></extra>",
                    text=hover,
                    showlegend=True,
                )
            )

    def _apply_detail(df: pd.DataFrame, t0: float, t1: float):
        if df is None or len(df) == 0:
            return

        if t1 < t0:
            t0, t1 = t1, t0

        t = _to_numeric_series(df, time_col).to_numpy(dtype=float)
        mask = np.isfinite(t) & (t >= t0) & (t <= t1)
        if not mask.any():
            with fig_detail.batch_update():
                fig_detail.data = []
                fig_detail.layout.xaxis.range = [t0, t1]
                fig_detail.layout.yaxis.autorange = True
            return

        df_win = df.loc[mask].copy()

        if w_detail_autodown.value and len(df_win) > detail_max_points:
            idx = _downsample_indices(len(df_win), detail_max_points)
            df_win = df_win.iloc[idx].copy()

        t_win = _to_numeric_series(df_win, time_col).to_numpy(dtype=float)

        sel = tuple(map(str, _coerce_list(w_detail_signals.value)))
        sel = tuple([c for c in sel if c in df_win.columns])

        with fig_detail.batch_update():
            fig_detail.data = []
            for sig in sel:
                y = _to_numeric_series(df_win, sig).to_numpy(dtype=float)
                fig_detail.add_trace(go.Scatter(x=t_win, y=y, mode="lines", name=sig, line=dict(width=1.3)))

            fig_detail.layout.xaxis.range = [t0, t1]

            # Freeze Y scale
            yr = state.get("detail_y_range")
            if yr is not None:
                fig_detail.layout.yaxis.range = list(yr)
                fig_detail.layout.yaxis.autorange = False
            else:
                fig_detail.layout.yaxis.autorange = True

            # Events overlay
            if w_show_events_detail.value:
                _add_event_markers(fig_detail, t0=t0, t1=t1, for_detail=True)

    def _refresh_all_for_session(session_key: str):
        sess = _load_session(session_key)
        df = sess["df"]
        state["session"] = sess
        state["df"] = df

        _rebuild_signal_dropdowns(sess)

        meta = (sess or {}).get("meta") or {}
        registry = meta.get("signals") or {}
        if not isinstance(registry, dict):
            registry = {}
        state["_registry"] = registry

        # Load events/metrics and populate event types
        ev = _load_events_for_session(session_key)
        met = _load_metrics_for_session(session_key)
        merged = _merge_events_metrics(ev, met)

        state["events_df"] = ev
        state["metrics_df"] = met
        state["events_merged"] = merged

        _rebuild_event_type_options(merged)

        _set_overview_trace(df, str(w_overview_signal.value), registry=state.get("_registry") or {})
        t0, t1 = _get_current_window()
        _apply_detail(df, t0, t1)

    # ---------------- callbacks ----------------

    def _on_session_change(*_):
        if state["updating"]:
            return
        state["updating"] = True
        try:
            _refresh_all_for_session(str(w_session.value))
        finally:
            state["updating"] = False

    def _on_overview_signal_change(*_):
        if state["updating"]:
            return
        df = state["df"]
        if df is None:
            return
        state["updating"] = True
        try:
            _set_overview_trace(df, str(w_overview_signal.value), registry=state.get("_registry") or {})
            t0, t1 = _get_current_window()
            _apply_detail(df, t0, t1)
        finally:
            state["updating"] = False

    def _on_detail_controls_change(*_):
        if state["updating"]:
            return
        df = state["df"]
        if df is None:
            return

        # refresh frozen y-range when detail signals change (or on general control changes)
        sel = tuple(map(str, _coerce_list(w_detail_signals.value)))
        state["detail_y_range"] = _compute_y_range(df, sel)

        # update overview (because event toggles/types affect it)
        _set_overview_trace(df, str(w_overview_signal.value), registry=state.get("_registry") or {})

        t0, t1 = _get_current_window()
        _apply_detail(df, t0, t1)

    # Overview window change via relayout (xaxis.range)
    def _on_overview_range_change(layout, xrange_):
        if state["updating"]:
            return
        df = state["df"]
        if df is None:
            return
        try:
            t0, t1 = _get_current_window()
            _apply_detail(df, t0, t1)
        except Exception:
            pass

    fig_overview.layout.xaxis.on_change(_on_overview_range_change, "range")

    # Observers
    w_session.observe(_on_session_change, names="value")
    w_overview_signal.observe(_on_overview_signal_change, names="value")
    for w in (w_detail_signals, w_detail_autodown, w_event_types, w_show_events_overview, w_show_events_detail):
        w.observe(_on_detail_controls_change, names="value")

    # ---------------- bookmarks ----------------

    def _bookmark_label(bm: WindowBookmark) -> str:
        nm = bm.name.strip() if bm.name else ""
        base = nm if nm else f"{bm.t0:.2f}–{bm.t1:.2f}s"
        return f"{base}  ({bm.session_key})"

    def _rebuild_bookmark_list():
        bms: List[WindowBookmark] = state["bookmarks"]
        labels = [_bookmark_label(b) for b in bms]
        w_bm_list.options = labels
        if labels:
            if w_bm_list.value not in labels:
                w_bm_list.value = labels[-1]
        else:
            w_bm_list.value = None

    def _selected_bookmark() -> Optional[WindowBookmark]:
        val = w_bm_list.value
        if not val:
            return None
        for b in state["bookmarks"]:
            if _bookmark_label(b) == val:
                return b
        return None

    def _save_bookmark(_btn):
        df = state["df"]
        if df is None:
            return
        t0, t1 = _get_current_window()
        bm = WindowBookmark(
            name=str(w_bm_name.value or "").strip(),
            comment=str(w_bm_comment.value or "").strip(),
            session_key=str(w_session.value),
            t0=float(t0),
            t1=float(t1),
            overview_signal=str(w_overview_signal.value),
            detail_signals=tuple(map(str, _coerce_list(w_detail_signals.value))),
            selected_event_types=tuple(map(str, _coerce_list(w_event_types.value))),
            show_events_overview=bool(w_show_events_overview.value),
            show_events_detail=bool(w_show_events_detail.value),
        )
        state["bookmarks"].append(bm)
        _rebuild_bookmark_list()

    def _load_bookmark(_btn):
        bm = _selected_bookmark()
        if bm is None:
            return

        # Switch session if needed
        if str(w_session.value) != bm.session_key:
            state["updating"] = True
            try:
                w_session.value = bm.session_key
            finally:
                state["updating"] = False
            _refresh_all_for_session(bm.session_key)

        state["updating"] = True
        try:
            if bm.overview_signal in list(w_overview_signal.options):
                w_overview_signal.value = bm.overview_signal

            opts = set(map(str, w_detail_signals.options))
            kept = tuple([s for s in bm.detail_signals if s in opts])
            w_detail_signals.value = kept if kept else ((w_overview_signal.value,) if w_overview_signal.value else ())

            # events selection + toggles
            et_opts = set(map(str, w_event_types.options))
            kept_et = tuple([s for s in bm.selected_event_types if s in et_opts])
            w_event_types.value = kept_et if kept_et else tuple(map(str, w_event_types.options))
            w_show_events_overview.value = bm.show_events_overview
            w_show_events_detail.value = bm.show_events_detail

            # set window on overview (drives detail)
            fig_overview.layout.xaxis.range = [bm.t0, bm.t1]
        finally:
            state["updating"] = False

        df = state["df"]
        # refresh frozen y-range and redraw
        sel = tuple(map(str, _coerce_list(w_detail_signals.value)))
        state["detail_y_range"] = _compute_y_range(df, sel)

        _set_overview_trace(df, str(w_overview_signal.value), registry=state.get("_registry") or {})
        _apply_detail(df, bm.t0, bm.t1)

    def _delete_bookmark(_btn):
        bm = _selected_bookmark()
        if bm is None:
            return
        state["bookmarks"] = [b for b in state["bookmarks"] if b is not bm]
        _rebuild_bookmark_list()

    b_save.on_click(_save_bookmark)
    b_load.on_click(_load_bookmark)
    b_delete.on_click(_delete_bookmark)

    # ---------------- layout ----------------

    controls_left = W.VBox(
        [
            session_title, w_session,
            overview_title, w_overview_signal,   # <-- moved here
            event_types_title, w_event_types,
            W.HBox([w_show_events_overview, w_show_events_detail], layout=W.Layout(gap="8px")),
        ],
        layout=W.Layout(gap="6px"),
    )

    bookmarks_box = W.VBox(
        [
            W.HTML("Bookmarks (memory only)", layout=W.Layout(padding=f"0 0 0 {DESC_PAD}")),
            w_bm_name,
            w_bm_comment,
            W.HBox(
                [b_save, b_load, b_delete],
                layout=W.Layout(gap="8px", padding=f"0 0 0 {DESC_PAD}"),
            ),
            w_bm_list,
        ],
        layout=W.Layout(gap="6px"),
    )

    # Overview row: plot
    overview_row = W.HBox(
        [
            W.VBox(
                [fig_overview],
                layout=W.Layout(
                    flex="1 1 0%",
                    min_width="0",   # prevents overflow clipping
                ),
            ),
        ],
        layout=W.Layout(
            width="100%",
            gap="16px",
            align_items="stretch",
        ),
    )



    # Detail row: plot + selectors on right
    detail_row = W.HBox(
        [
            W.VBox([fig_detail], layout=W.Layout(flex="1 1 auto")),
            W.VBox([W.HTML("<br>"), w_detail_signals, w_detail_autodown], layout=W.Layout(width="520px")),
        ],
        layout=W.Layout(gap="16px", align_items="flex-start"),
    )

    plots_box = W.VBox(
        [overview_row, detail_row],
        layout=W.Layout(gap="10px", width="100%")
    )

    root = W.VBox(
        [
            W.HBox([controls_left, bookmarks_box], layout=W.Layout(gap="16px", align_items="flex-start")),
            plots_box,
            out,
        ],
        layout=W.Layout(gap="10px", width="100%")
    )

    def _force_plotly_resize(delay_ms: int = 150):
        # Resizes any plotly graphs currently in the output area.
        display(Javascript(f"""
        setTimeout(function() {{
            try {{
                // Resize any Plotly graphs on the page
                const plots = document.querySelectorAll('.js-plotly-plot');
                plots.forEach((gd) => {{
                    if (window.Plotly && Plotly.Plots && Plotly.Plots.resize) {{
                        Plotly.Plots.resize(gd);
                    }}
                }});
            }} catch (e) {{
                console.warn("plotly resize failed", e);
            }}
        }}, {int(delay_ms)});
        """))

    display(root)
    _refresh_all_for_session(str(w_session.value))
    _rebuild_bookmark_list()
    _force_plotly_resize(600)

    return {
        "root": root,
        "state": state,
        "fig_overview": fig_overview,
        "fig_detail": fig_detail,
        "bookmarks": state["bookmarks"],
    }


def make_session_window_browser_rebuilder(
    *,
    sel: Dict[str, Any],
    out: Optional[W.Output] = None,
    session_key_col: str = "session_key",
    session_id_col: str = "session_id",
    event_id_col: str = "event_id",
    event_type_col: str = "schema_id",
    trigger_time_col: str = "trigger_time_s",
    time_col: str = "time_s",
    overview_max_points: int = 3000,
    detail_max_points: int = 8000,
) -> Dict[str, Any]:
    """
    Rebuild-on-selector-change wrapper (thin notebook cell pattern).

    Expects sel to provide:
      - sel["store"]
      - sel["get_key_to_ref"]()
      - sel["get_events_index_df"]() -> df with session_key_col

    Uses existing loaders:
      - make_session_loader(store=..., key_to_ref=...)
      - load_all_events_for_selected(store, key_to_ref=...)
      - load_all_metrics_for_selected(store, key_to_ref=...)
    """
    if out is None:
        out = W.Output()

    state: Dict[str, Any] = {"handles": None}

    def rebuild():
        from bodaqs_analysis.widgets.loaders import (
            make_session_loader,
            load_all_events_for_selected,
            load_all_metrics_for_selected,
        )

        store = sel["store"]
        key_to_ref = sel["get_key_to_ref"]()
        events_index_df = sel["get_events_index_df"]()

        session_loader = make_session_loader(store=store, key_to_ref=key_to_ref)

        # Load once for scope; filter per-session in closures
        events_all = load_all_events_for_selected(store, key_to_ref=key_to_ref)
        metrics_all = load_all_metrics_for_selected(store, key_to_ref=key_to_ref)

        def _filter_by_session(df: pd.DataFrame, session_key: str) -> pd.DataFrame:
            if df is None or df.empty:
                return pd.DataFrame()
            # Prefer session_key_col if present, else session_id_col
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
                overview_max_points=overview_max_points,
                detail_max_points=detail_max_points,
            )

    rebuild()
    return {"out": out, "rebuild": rebuild, "state": state}
