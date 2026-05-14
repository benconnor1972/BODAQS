# bodaqs_analysis/widgets/session_window_browser_widget.py
# -*- coding: utf-8 -*-
"""
Session Window Browser (v0+) — single Plotly FigureWidget with x-axis rangeslider driving a linked detail view,
with event trigger overlays (hover metrics) and selector-driven rebuilding.

Key features:
- Consumes selector scope but enforces a SINGLE active session within the widget.
- Single figure:
  - xaxis (with rangeslider) shows ONLY a normalized "overview" trace (one signal).
  - xaxis2 (matches xaxis) shows detail signals (multi-select) and event markers.
- Detail y-axis is frozen (computed per session + selected detail signals).
- Events: multi-select event types (schema_id/event_type), markers on fixed lane (yaxis2),
  hover shows trigger time + selected numeric metrics (events<->metrics joined 1:1).
- Marks: optional overlay from session df column 'mark' as cross markers with stable color.
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
import time

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
    span = hi - lo
    pad = 0.03 * span
    return (lo - pad, hi + pad)


def _normalize01(y: np.ndarray) -> np.ndarray:
    """Normalize finite values to [0,1] (robust for overview/rangeslider)."""
    y = y.astype(float, copy=False)
    m = np.isfinite(y)
    if not m.any():
        return np.full_like(y, np.nan, dtype=float)
    lo = float(np.nanmin(y[m]))
    hi = float(np.nanmax(y[m]))
    if hi == lo:
        return np.zeros_like(y, dtype=float)
    out = (y - lo) / (hi - lo)
    out[~m] = np.nan
    return out

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
    detail_signals: Tuple[str, ...]
    selected_event_types: Tuple[str, ...]


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
        layout=W.Layout(width="300px"),
    )
    event_types_hint = W.HTML(
        "<span style='color:#666; font-size: 90%'>Select one or more</span>"
    )

    # NEW: marks toggle (default True)
    w_show_marks = W.Checkbox(
        value=True,
        description="Show marks",
        layout=W.Layout(width="220px"),
    )

    detail_title = W.HTML("Detail signals")
    w_detail_signals = W.SelectMultiple(options=[], value=(), description="", rows=8, layout=W.Layout(width="380px"))
    w_detail_autodown = W.Checkbox(value=True, description="Auto downsample detail", layout=W.Layout(width="220px"))

    # Bookmark controls
    w_bm_name = W.Text(value="", description="Name:", layout=W.Layout(width="450px"))
    w_bm_comment = W.Text(value="", description="Comment:", layout=W.Layout(width="450px"))
    b_save = W.Button(description="Save", button_style="", layout=W.Layout(width="120px"))
    b_delete = W.Button(description="Delete", button_style="", layout=W.Layout(width="120px"))
    b_load = W.Button(description="Load", button_style="", layout=W.Layout(width="120px"))
    w_bm_list = W.Select(options=[], value=None, description="Saved:", rows=8, layout=W.Layout(width="450px"))

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
        "fig": None,
        # marks
        "mark_col": "mark",
    }

    # stable mark styling
    MARK_COLOR = "#111111"     # stable / fixed
    MARK_SYMBOL = "x"          # cross
    MARK_SIZE = 9

    # ---------------- Plotly figure ----------------
    fig = go.FigureWidget()
    state["fig"] = fig

    fig.update_layout(
        height=520,
        margin=dict(l=55, r=20, t=20, b=160),  # extra for slider + legend
        xaxis=dict(
            title="time (s)",
            rangeslider=dict(visible=True),
            showgrid=True,
        ),
        yaxis=dict(
            title="value",
            showgrid=True,
        ),
        showlegend=True,
        legend=dict(
            orientation="h",
            x=0.5, xanchor="center",
            y=-0.45, yanchor="top",
            yref="paper",
        ),
        uirevision="keep",
    )

    def _init_fig():
        fig.layout = go.Layout(
            height=520,
            margin=dict(l=55, r=20, t=20, b=90),
            xaxis=dict(
                title="time (s)",
                rangeslider=dict(visible=True),
                showgrid=True,
            ),
            yaxis=dict(
                title="value",
                showgrid=True,
            ),
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.2,
                xanchor="center",
                x=0.5,
            ),
        )

        fig.update_layout(
            showlegend=True,
            legend=dict(
                orientation="h",
                x=0.5,
                xanchor="center",
                y=-0.5,
                yanchor="top",
                yref="paper",
            ),
            margin=dict(l=55, r=20, t=20, b=200),
        )

        fig.layout.uirevision = "keep"
        fig.layout.xaxis.uirevision = "keep"
        fig.layout.yaxis.uirevision = "keep"

        fig.data = []

        fig.layout.autosize = True
        fig.layout.width = None

        try:
            fig._config = dict(getattr(fig, "_config", {}) or {}, responsive=True)
        except Exception:
            pass

    _init_fig()

    # ---------------- data loading ----------------

    def _load_session(session_key: str) -> Dict[str, Any]:
        sess = session_loader(str(session_key))
        if not isinstance(sess, dict):
            raise ValueError("session_loader must return a dict-like session")
        if "df" not in sess:
            raise ValueError("session missing required key 'df'")
        df_ = sess["df"]
        if not isinstance(df_, pd.DataFrame):
            raise ValueError("session['df'] must be a pandas DataFrame")
        if time_col not in df_.columns:
            raise ValueError(f"session['df'] must contain {time_col!r} column")
        return sess

    def _load_events_for_session(session_key: str) -> pd.DataFrame:
        if events_loader is None:
            return pd.DataFrame()
        df_ = events_loader(str(session_key))
        return df_.copy() if isinstance(df_, pd.DataFrame) else pd.DataFrame()

    def _load_metrics_for_session(session_key: str) -> pd.DataFrame:
        if metrics_loader is None:
            return pd.DataFrame()
        df_ = metrics_loader(str(session_key))
        return df_.copy() if isinstance(df_, pd.DataFrame) else pd.DataFrame()

    def _merge_events_metrics(events_df: pd.DataFrame, metrics_df: pd.DataFrame) -> pd.DataFrame:
        """1:1 join via (session_id, event_id) per metrics contract."""
        if events_df is None or events_df.empty:
            return pd.DataFrame()
        if metrics_df is None or metrics_df.empty:
            return events_df.copy()

        if session_id_col not in events_df.columns or event_id_col not in events_df.columns:
            return events_df.copy()
        if session_id_col not in metrics_df.columns or event_id_col not in metrics_df.columns:
            return events_df.copy()

        join_keys = [session_id_col, event_id_col]
        metric_cols = [c for c in metrics_df.columns if c not in join_keys]
        merged = events_df.merge(metrics_df[join_keys + metric_cols], on=join_keys, how="left", suffixes=("", "_m"))
        return merged

    # ---------------- signal dropdown rebuild ----------------

    def _rebuild_signal_dropdowns(sess: dict):
        df_ = sess["df"]
        meta = (sess or {}).get("meta") or {}
        registry = meta.get("signals") or {}
        if not isinstance(registry, dict):
            registry = {}
        state["_registry"] = registry

        registry_cols = _infer_signal_cols_from_registry(sess)
        if not registry_cols:
            registry_cols = [c for c in df_.columns if isinstance(c, str)]

        numeric_cols = _filter_numeric_cols(df_, registry_cols, time_col=time_col)
        if not numeric_cols:
            numeric_cols = [c for c in df_.columns if c != time_col and pd.api.types.is_numeric_dtype(df_[c])]

        numeric_cols_sorted = _sort_cols_by_unit(numeric_cols, registry)

        prev_detail = tuple(map(str, _coerce_list(w_detail_signals.value)))

        w_detail_signals.options = numeric_cols_sorted
        opts = list(map(str, numeric_cols_sorted))

        kept = tuple([c for c in prev_detail if c in opts])

        if kept:
            w_detail_signals.value = kept
        else:
            registry = state.get("_registry") or {}
            mm_cols = [
                c for c in opts
                if (isinstance(registry, dict) and isinstance(registry.get(c, {}), dict)
                    and str(registry.get(c, {}).get("unit", "")).strip() == "mm")
            ]

            chosen = mm_cols[0] if mm_cols else (opts[0] if opts else None)
            w_detail_signals.value = (chosen,) if chosen else ()

        state["registry_cols"] = registry_cols
        state["numeric_cols"] = numeric_cols_sorted

        sel = tuple(map(str, _coerce_list(w_detail_signals.value)))
        state["detail_y_range"] = _compute_y_range(df_, sel)

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
        w_event_types.value = kept

    # ---------------- events hover + colors ----------------

    def _build_event_hovertext(row: pd.Series, *, max_metrics: int = 10) -> str:
        et = str(row.get(event_type_col, ""))
        t_ = row.get(trigger_time_col, None)
        bits = [f"type: {et}"]
        if t_ is not None and np.isfinite(pd.to_numeric(t_, errors="coerce")):
            bits.append(f"t: {float(t_):.3f}s")

        metric_items: List[Tuple[str, float]] = []
        for c, v in row.items():
            if not isinstance(c, str) or not c.startswith("m_"):
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
        Fixed y position on main y-axis based on current y-range (or frozen range).
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

        sel_types = set(map(str, _coerce_list(w_event_types.value)))
        if not sel_types:
            return

        m = merged.copy()
        m[event_type_col] = m[event_type_col].astype(str)

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

        m = m[m[event_type_col].isin(sel_types)]
        if m.empty:
            return

        y_mark = _current_lane_y()

        for et in sorted(m[event_type_col].unique()):
            sub = m[m[event_type_col] == et]
            xs = sub["_tt"].to_numpy(dtype=float)
            ys = np.full_like(xs, y_mark, dtype=float)

            hover = [_build_event_hovertext(r) for _, r in sub.iterrows()]

            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    mode="markers",
                    marker=dict(size=7, color=_event_color_for(et), symbol="circle"),
                    hovertemplate="%{text}<extra></extra>",
                    text=hover,
                    showlegend=True,
                    name=f"event: {et}",
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

        # lightweight hover: time + mark value
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

    def _update_detail_only_for_window(*, t0: float, t1: float):
        """
        Update ONLY the detail signals + overlays for the given window,
        without touching the overview trace or clearing fig.data.
        """
        df_ = state["df"]
        if df_ is None:
            return

        if t1 < t0:
            t0, t1 = t1, t0

        # window df
        t = _to_numeric_series(df_, time_col).to_numpy(dtype=float)
        mask = np.isfinite(t) & (t >= t0) & (t <= t1)
        df_win = df_.loc[mask].copy() if mask.any() else df_.iloc[0:0].copy()

        if w_detail_autodown.value and len(df_win) > detail_max_points:
            idx = _downsample_indices(len(df_win), detail_max_points)
            df_win = df_win.iloc[idx].copy()

        t_win = _to_numeric_series(df_win, time_col).to_numpy(dtype=float)

        sel = tuple(map(str, _coerce_list(w_detail_signals.value)))
        sel = tuple([c for c in sel if c in df_win.columns])

        with fig.batch_update():
            # Trim everything after overview (if you still have an overview trace)
            if len(fig.data) > 1:
                fig.data = fig.data[:1]

            # Re-add detail traces
            for sig in sel:
                y = _to_numeric_series(df_win, sig).to_numpy(dtype=float)
                fig.add_trace(
                    go.Scatter(
                        x=t_win,
                        y=y,
                        xaxis="x2",
                        yaxis="y",
                        mode="lines",
                        name=sig,
                        line=dict(width=1.3),
                        showlegend=False,
                    )
                )

            # Ensure frozen y-range remains in effect
            yr = state.get("detail_y_range")
            if yr is not None:
                fig.layout.yaxis.range = list(yr)
                fig.layout.yaxis.autorange = False
            else:
                fig.layout.yaxis.autorange = True

            # Add overlays for this window
            _add_event_markers(t0=t0, t1=t1, for_detail=True)
            _add_mark_markers(t0=t0, t1=t1, for_detail=True)

    def _apply_all_traces(df_: pd.DataFrame):
        if df_ is None or len(df_) == 0:
            with fig.batch_update():
                fig.data = ()
            return

        prev_range = None
        try:
            r = fig.layout.xaxis.range
            if r is not None and len(r) == 2 and r[0] is not None and r[1] is not None:
                prev_range = (float(r[0]), float(r[1]))
        except Exception:
            prev_range = None
        if prev_range is None:
            try:
                t_full = _to_numeric_series(df_, time_col).to_numpy(dtype=float)
                t_full = t_full[np.isfinite(t_full)]
                if t_full.size:
                    prev_range = (float(t_full.min()), float(t_full.max()))
            except Exception:
                prev_range = None

        sel = tuple(map(str, _coerce_list(w_detail_signals.value)))
        sel = tuple([c for c in sel if c in df_.columns])

        df_plot = df_
        if w_detail_autodown.value and len(df_plot) > detail_max_points:
            idx = _downsample_indices(len(df_plot), detail_max_points)
            df_plot = df_plot.iloc[idx].copy()

        t = _to_numeric_series(df_plot, time_col).to_numpy(dtype=float)

        with fig.batch_update():
            fig.data = ()  # rebuild once per control change

            # Detail signal traces
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

            # y-axis freezing
            yr = state.get("detail_y_range")
            if yr is not None:
                fig.layout.yaxis.range = list(yr)
                fig.layout.yaxis.autorange = False
            else:
                fig.layout.yaxis.autorange = True

            # Overlays (add-only)
            _add_event_markers(t0=None, t1=None, for_detail=False)
            _add_mark_markers(t0=None, t1=None, for_detail=False)

            if prev_range is not None:
                a, b = prev_range
                fig.layout.xaxis.autorange = False
                fig.layout.xaxis.range = [a, b]
                if hasattr(fig.layout.xaxis, "rangeslider") and fig.layout.xaxis.rangeslider is not None:
                    fig.layout.xaxis.rangeslider.range = [a, b]

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
        state["detail_y_range"] = _compute_y_range(df_, sel)

        _apply_all_traces(df_)

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

        if state.get("in_slider_drag"):
            return

        sel = tuple(map(str, _coerce_list(w_detail_signals.value)))
        state["detail_y_range"] = _compute_y_range(df_, sel)

        _apply_all_traces(df_)

    # Observers
    w_session.observe(_on_session_change, names="value")
    for w in (
        w_detail_signals,
        w_detail_autodown,
        w_event_types,
        w_show_marks,   # NEW
    ):
        w.observe(_on_controls_change, names="value")

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
        df_ = state["df"]
        if df_ is None:
            return
        t0, t1 = _get_current_window()
        bm = WindowBookmark(
            name=str(w_bm_name.value or "").strip(),
            comment=str(w_bm_comment.value or "").strip(),
            session_key=str(w_session.value),
            t0=float(t0),
            t1=float(t1),
            detail_signals=tuple(map(str, _coerce_list(w_detail_signals.value))),
            selected_event_types=tuple(map(str, _coerce_list(w_event_types.value))),
        )
        state["bookmarks"].append(bm)
        _rebuild_bookmark_list()

    def _load_bookmark(_btn):
        bm = _selected_bookmark()
        if bm is None:
            return

        if str(w_session.value) != bm.session_key:
            state["updating"] = True
            try:
                w_session.value = bm.session_key
            finally:
                state["updating"] = False
            _refresh_all_for_session(bm.session_key)

        state["updating"] = True
        try:
            opts = set(map(str, w_detail_signals.options))
            kept = tuple([s for s in bm.detail_signals if s in opts])
            w_detail_signals.value = kept if kept else ()

            et_opts = set(map(str, w_event_types.options))
            kept_et = tuple([s for s in bm.selected_event_types if s in et_opts])
            w_event_types.value = kept_et if kept_et else tuple(map(str, w_event_types.options))

            fig.layout.xaxis.range = [bm.t0, bm.t1]
        finally:
            state["updating"] = False

        df_ = state["df"]
        sel = tuple(map(str, _coerce_list(w_detail_signals.value)))
        state["detail_y_range"] = _compute_y_range(df_, sel)
        _apply_all_traces(df_)

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

    session_box = W.VBox(
        [session_title, w_session],
        layout=W.Layout(gap="6px", width="450px"),
    )

    top_controls_row = W.HBox(
        [session_box],
        layout=W.Layout(gap="40px", align_items="flex-start", justify_content="space-between", width="1200px"),
    )

    detail_box = W.VBox(
        [detail_title, w_detail_signals, w_detail_autodown],
        layout=W.Layout(gap="6px", width="520px"),
    )

    # NEW: show-marks checkbox goes under event selector
    events_box = W.VBox(
        [event_types_title, event_types_hint, w_event_types, w_show_marks],
        layout=W.Layout(gap="6px", width="450px"),
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

    bottom_row = W.HBox(
        [detail_box, events_box, bookmarks_box],
        layout=W.Layout(gap="16px", align_items="flex-start", width="100%"),
    )

    plot_row = W.VBox([fig], layout=W.Layout(width="100%"))

    root = W.VBox(
        [
            top_controls_row,
            plot_row,
            bottom_row,
        ],
        layout=W.Layout(gap="10px", width="100%"),
    )
    display(root)

    def _force_plotly_resize(delay_ms: int = 150):
        display(Javascript(f"""
        setTimeout(function() {{
            try {{
                const plots = document.querySelectorAll('.js-plotly-plot');
                plots.forEach((gd) => {{
                    if (window.Plotly) {{
                        Plotly.relayout(gd, {{'xaxis.rangeslider.visible': true}});
                        if (Plotly.Plots && Plotly.Plots.resize) {{
                            Plotly.Plots.resize(gd);
                        }}
                    }}
                }});
            }} catch (e) {{
                console.warn("plotly resize failed", e);
            }}
        }}, {int(delay_ms)});
        """))

    _refresh_all_for_session(str(w_session.value))
    _rebuild_bookmark_list()
    _force_plotly_resize(600)

    return {
        "root": root,
        "state": state,
        "fig": fig,
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
    detail_max_points: int = 8000,
) -> Dict[str, Any]:
    """
    Rebuild-on-selector-change wrapper (thin notebook cell pattern).
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
                detail_max_points=detail_max_points,
            )

    rebuild()
    return {"out": out, "rebuild": rebuild, "state": state}
