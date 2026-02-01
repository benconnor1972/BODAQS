# bodaqs_analysis/widgets/session_window_browser_widget.py
# -*- coding: utf-8 -*-
"""
Session Window Browser (v0) — Plotly overview + linked detail window.

- Consumes selector scope (list of sessions) but enforces a SINGLE active session within the widget.
- Overview uses Plotly x-axis rangeslider (Option A) to select a time window.
- Detail plot updates dynamically as the window changes.
- Marks overlay from a boolean-ish column in session['df'] (auto-detected, user-selectable).
- Bookmarks stored in memory only (not persisted).

Requires: plotly, ipywidgets, pandas, numpy
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import ipywidgets as W
from IPython.display import display, clear_output

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
    This assumes registry keys are df columns.
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
        # consider numeric-ish if coercion yields any finite values
        v = _to_numeric_series(df, c).to_numpy(dtype=float)
        if np.isfinite(v).any():
            out.append(c)
    return out

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


# -----------------------------
# Main widget
# -----------------------------

def make_session_window_browser_widget_for_loader(
    *,
    events_index_df: pd.DataFrame,
    session_loader: Callable[[str], Dict[str, Any]],
    session_key_col: str = "session_key",
    time_col: str = "time_s",
    overview_max_points: int = 3000,
    detail_max_points: int = 8000,
) -> Dict[str, Any]:
    """
    Build the Session Window Browser widget (v0).

    - sessions discovered from events_index_df[session_key_col]
    - session_loader loads a single session dict with keys: "df", "meta"
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
    w_session = W.Dropdown(options=session_keys, value=session_keys[0], description="Session:", layout=W.Layout(width="520px"))

    w_overview_signal = W.Dropdown(options=[], description="Overview:", layout=W.Layout(width="520px"))
    w_detail_signals = W.SelectMultiple(options=[], value=(), description="Detail:", rows=10, layout=W.Layout(width="520px"))

    w_detail_autodown = W.Checkbox(value=True, description="Auto downsample detail", layout=W.Layout(width="220px"))

    # Bookmark controls
    w_bm_name = W.Text(value="", description="Name:", layout=W.Layout(width="520px"))
    w_bm_comment = W.Text(value="", description="Comment:", layout=W.Layout(width="520px"))
    b_save = W.Button(description="Save window", button_style="success", layout=W.Layout(width="140px"))
    b_delete = W.Button(description="Delete", button_style="danger", layout=W.Layout(width="120px"))
    b_load = W.Button(description="Load", button_style="", layout=W.Layout(width="120px"))
    w_bm_list = W.Select(options=[], value=None, description="Saved:", rows=8, layout=W.Layout(width="520px"))

    out = W.Output()

    # ---------------- state ----------------
    state: Dict[str, Any] = {
        "session": None,
        "df": None,
        "registry_cols": None,
        "numeric_cols": None,
        "bookmarks": [],  # List[WindowBookmark]
        "updating": False,  # guard recursion
        "overview_fig": None,
        "detail_fig": None,
    }

    # ---------------- Plotly figures ----------------
    # Use FigureWidget to attach Python callbacks.
    fig_overview = go.FigureWidget()
    fig_detail = go.FigureWidget()
    state["overview_fig"] = fig_overview
    state["detail_fig"] = fig_detail

    def _init_figs():
        # Overview: thin/wide, with rangeslider
        fig_overview.layout = go.Layout(
            height=220,
            margin=dict(l=50, r=20, t=30, b=30),
            xaxis=dict(title="time (s)", rangeslider=dict(visible=True)),
            yaxis=dict(title="overview"),
            showlegend=False,
        )
        fig_overview.data = []  # clear traces

        # Detail: taller
        fig_detail.layout = go.Layout(
            height=420,
            margin=dict(l=50, r=20, t=30, b=40),
            xaxis=dict(title="time (s)"),
            yaxis=dict(title="value"),
            legend=dict(orientation="h"),
        )
        fig_detail.data = []
        fig_detail.layout.shapes = ()

    _init_figs()

    # ---------------- data + dropdown rebuild ----------------

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

    def _rebuild_signal_dropdowns(sess: dict):
        df = sess["df"]

        registry_cols = _infer_signal_cols_from_registry(sess)
        # Fall back to df columns if registry is missing
        if not registry_cols:
            registry_cols = [c for c in df.columns if isinstance(c, str)]

        numeric_cols = _filter_numeric_cols(df, registry_cols, time_col=time_col)
        if not numeric_cols:
            # last-resort: any numeric df columns
            numeric_cols = [c for c in df.columns if c != time_col and pd.api.types.is_numeric_dtype(df[c])]

        # Update overview signal options
        prev_ov = w_overview_signal.value
        w_overview_signal.options = numeric_cols
        w_overview_signal.value = prev_ov if (prev_ov in numeric_cols) else (numeric_cols[0] if numeric_cols else None)

        # Update detail signals options
        prev_detail = tuple(map(str, _coerce_list(w_detail_signals.value)))
        w_detail_signals.options = numeric_cols
        kept = tuple([c for c in prev_detail if c in numeric_cols])
        if kept:
            w_detail_signals.value = kept
        else:
            # default to overview signal
            w_detail_signals.value = (w_overview_signal.value,) if w_overview_signal.value else ()

        state["registry_cols"] = registry_cols
        state["numeric_cols"] = numeric_cols

    # ---------------- plot updates ----------------

    def _set_overview_trace(df: pd.DataFrame, sig: str):
        t = _to_numeric_series(df, time_col).to_numpy(dtype=float)
        y = _to_numeric_series(df, sig).to_numpy(dtype=float)

        # downsample for overview
        idx = _downsample_indices(len(df), overview_max_points)
        t2 = t[idx]
        y2 = y[idx]

        # remove non-finite for plotting
        mask = np.isfinite(t2) & np.isfinite(y2)
        t2 = t2[mask]
        y2 = y2[mask]

        with fig_overview.batch_update():
            fig_overview.data = []
            fig_overview.add_trace(go.Scatter(x=t2, y=y2, mode="lines", line=dict(width=1)))
            fig_overview.layout.yaxis.title = sig

            # Initialize window to middle-ish if no range set
            if fig_overview.layout.xaxis.range is None:
                if len(t2) >= 2:
                    lo = float(np.nanmin(t2))
                    hi = float(np.nanmax(t2))
                    span = hi - lo
                    t0 = lo + 0.10 * span
                    t1 = lo + 0.20 * span
                    fig_overview.layout.xaxis.range = [t0, t1]

    def _get_current_window() -> Tuple[float, float]:
        r = fig_overview.layout.xaxis.range
        if r is None or len(r) != 2:
            # fallback to full range
            df = state["df"]
            t = _to_numeric_series(df, time_col).to_numpy(dtype=float)
            t = t[np.isfinite(t)]
            if len(t) == 0:
                return (0.0, 0.0)
            return (float(t.min()), float(t.max()))
        return (float(r[0]), float(r[1]))

    def _apply_detail(df: pd.DataFrame, t0: float, t1: float):
        if df is None or len(df) == 0:
            return

        # Ensure increasing
        if t1 < t0:
            t0, t1 = t1, t0

        t = _to_numeric_series(df, time_col).to_numpy(dtype=float)
        mask = np.isfinite(t) & (t >= t0) & (t <= t1)
        if not mask.any():
            with fig_detail.batch_update():
                fig_detail.data = []
                fig_detail.layout.shapes = ()
                fig_detail.layout.xaxis.range = [t0, t1]
            return

        df_win = df.loc[mask].copy()

        # Optional downsample detail if huge
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
            fig_detail.layout.shapes = ()

    def _refresh_all_for_session(session_key: str):
        sess = _load_session(session_key)
        df = sess["df"]

        state["session"] = sess
        state["df"] = df

        _rebuild_signal_dropdowns(sess)
        _set_overview_trace(df, str(w_overview_signal.value))
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
            _set_overview_trace(df, str(w_overview_signal.value))
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
            # Avoid hard-crashing callbacks; user can still interact.
            pass

    # FigureWidget: listen to xaxis.range changes
    fig_overview.layout.xaxis.on_change(_on_overview_range_change, "range")

    # Wire widget observers
    w_session.observe(_on_session_change, names="value")
    w_overview_signal.observe(_on_overview_signal_change, names="value")
    for w in (w_detail_signals, w_detail_autodown):
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
        # match by label
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

        # Apply settings
        state["updating"] = True
        try:
            if bm.overview_signal in list(w_overview_signal.options):
                w_overview_signal.value = bm.overview_signal
            # detail signals
            opts = set(map(str, w_detail_signals.options))
            kept = tuple([s for s in bm.detail_signals if s in opts])
            w_detail_signals.value = kept if kept else (w_overview_signal.value,)
            # set window on overview (drives detail)
            fig_overview.layout.xaxis.range = [bm.t0, bm.t1]
        finally:
            state["updating"] = False

        # Ensure plots update
        df = state["df"]
        _set_overview_trace(df, str(w_overview_signal.value))
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
            w_session,
            w_overview_signal,
            w_detail_signals,
            W.HBox([w_detail_autodown]),
        ],
        layout=W.Layout(gap="6px"),
    )

    bookmarks_box = W.VBox(
        [
            W.HTML("<b>Bookmarks (memory only)</b>"),
            w_bm_name,
            w_bm_comment,
            W.HBox([b_save, b_load, b_delete], layout=W.Layout(gap="8px")),
            w_bm_list,
        ],
        layout=W.Layout(gap="6px"),
    )

    plots_box = W.VBox(
        [
            W.HTML("<b>Overview</b>"),
            fig_overview,
            W.HTML("<b>Detail</b>"),
            fig_detail,
        ],
        layout=W.Layout(gap="6px"),
    )

    root = W.VBox(
        [
            W.HBox([controls_left, bookmarks_box], layout=W.Layout(gap="16px", align_items="flex-start")),
            plots_box,
            out,
        ],
        layout=W.Layout(gap="10px"),
    )

    display(root)

    # Initial load
    _refresh_all_for_session(str(w_session.value))
    _rebuild_bookmark_list()

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
    time_col: str = "time_s",
    overview_max_points: int = 3000,
    detail_max_points: int = 8000,
) -> Dict[str, Any]:
    """
    Rebuild-on-selector-change wrapper (thin notebook cell pattern).

    Expects sel to provide:
      - sel["get_events_index_df"]() -> pd.DataFrame with session_key_col
      - sel["store"]
      - sel["get_key_to_ref"]()
    And that your loaders module provides make_session_loader(store=..., key_to_ref=...)
    """
    if out is None:
        out = W.Output()

    state: Dict[str, Any] = {"handles": None}

    def rebuild():
        from IPython.display import clear_output
        from bodaqs_analysis.widgets.loaders import make_session_loader

        store = sel["store"]
        key_to_ref = sel["get_key_to_ref"]()
        events_index_df = sel["get_events_index_df"]()

        session_loader = make_session_loader(store=store, key_to_ref=key_to_ref)

        with out:
            clear_output(wait=True)
            state["handles"] = make_session_window_browser_widget_for_loader(
                events_index_df=events_index_df,
                session_loader=session_loader,
                session_key_col=session_key_col,
                time_col=time_col,
                overview_max_points=overview_max_points,
                detail_max_points=detail_max_points,
            )

    rebuild()
    return {"out": out, "rebuild": rebuild, "state": state}
