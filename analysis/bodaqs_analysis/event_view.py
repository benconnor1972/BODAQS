from __future__ import annotations
from typing import Any, Dict, Optional, Sequence, Tuple
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

def _require_data():
    if "EVENTS_DF" not in globals() or not isinstance(EVENTS_DF, pd.DataFrame) or EVENTS_DF.empty:
        raise RuntimeError("EVENTS_DF is missing or empty. Run detection first.")
    if "event_analysis_df" not in globals() or not isinstance(event_analysis_df, pd.DataFrame) or event_analysis_df.empty:
        raise RuntimeError("event_analysis_df is missing or empty. Run the analysis config cell first.")
    if "EVENT_SCHEMA" not in globals():
        raise RuntimeError("EVENT_SCHEMA not loaded.")
    return EVENTS_DF, event_analysis_df, EVENT_SCHEMA

def _get_event_row(events: pd.DataFrame,
                   event_id: Optional[str] = None,
                   occurrence: int = 0,
                   row_index: Optional[int] = None) -> pd.Series:
    """Pick a row from EVENTS_DF either by global row index or by (event_id, occurrence)."""
    if row_index is not None:
        if row_index < 0 or row_index >= len(events):
            raise IndexError(f"row_index {row_index} out of range (0..{len(events)-1})")
        return events.iloc[row_index]
    if not event_id:
        raise ValueError("Provide either row_index or (event_id, occurrence).")
    subset = events[events["event_id"] == event_id]
    if subset.empty:
        raise ValueError(f"No events with id='{event_id}' in EVENTS_DF.")
    if occurrence < 0 or occurrence >= len(subset):
        raise IndexError(f"occurrence {occurrence} out of range for id='{event_id}' (0..{len(subset)-1})")
    return subset.sort_values("t0_index").iloc[occurrence]

def _schema_event_block(event_id: str, schema: Dict[str, Any]) -> Dict[str, Any]:
    for ev in schema.get("events", []):
        if ev.get("id") == event_id:
            return ev
    return {}

def _resolve_inputs_for_row(row: pd.Series, schema: Dict[str, Any]) -> Dict[str, str]:
    """
    Resolve {disp: col, vel: col, acc: col, ...} using suffix-only mode.
    Detector uses the same logic (_resolve_inputs_for_sensor).
    """
    sensor = row.get("sensor")
    if not sensor:
        return {}

    naming = schema.get("naming", {}) or {}
    suffixes = naming.get("suffixes", {}) or {}
    if not suffixes:
        return {}

    return {kind: f"{sensor}{suf}" for kind, suf in suffixes.items()}

def _find_series_col(schema: Dict[str, Any], *, kind: str, base_sensor: Optional[str] = None) -> Optional[str]:
    """Optional helper used elsewhere; left unchanged but not used by plotter."""
    for s in schema.get("series", []):
        if s.get("kind") != kind:
            continue
        if base_sensor:
            base = s.get("base") or {}
            if base.get("sensor") != base_sensor:
                continue
        col = s.get("column")
        if col:
            return col
    return None

def _slice_event(df: pd.DataFrame, row: pd.Series, *, tol_s: float = 1e-9):
    import numpy as np
    import pandas as pd

    i0, i1 = int(row["start_index"]), int(row["end_index"])
    t0_idx = int(row["t0_index"])
    n = len(df)
    if not (0 <= i0 < n) or not (0 < i1 <= n) or not (i0 < i1):
        raise IndexError(f"Invalid slice bounds: [{i0},{i1}) (len={n})")
    if not (i0 <= t0_idx < i1):
        raise IndexError(f"t0_index {t0_idx} not inside [{i0},{i1}).")

    seg = df.iloc[i0:i1].copy()

    # use time index directly
    if isinstance(df.index, (pd.DatetimeIndex, pd.TimedeltaIndex)):
        seg = seg.sort_index(kind="mergesort")
        t = seg.index
        t0_time = df.index[t0_idx]
        rel_t = (t - t0_time).total_seconds()
    else:
        if "t" not in df.columns:
            raise RuntimeError("Need a time index or a 't' column.")
        seg = seg.sort_values("t", kind="mergesort").reset_index(drop=True)
        t0_time = float(df.iloc[t0_idx]["t"])
        rel_t = seg["t"].to_numpy() - t0_time

    t0_in_slice = int(np.argmin(np.abs(rel_t)))
    if abs(rel_t[t0_in_slice]) > tol_s:
        raise RuntimeError("Could not align t0 by time—check EVENTS_DF/source frame consistency.")

    return seg, rel_t, t0_in_slice

def plot_event(*,
               row_index: Optional[int] = None,
               event_id: Optional[str] = None,
               occurrence: int = 0,
               extra_series: Sequence[str] = (),
               show_metrics: bool = True,
               share_x: bool = True,
               ylimits: Dict[str, Tuple[Optional[float], Optional[float]]] = None,
               fig_width: float = DEFAULT_FIG_WIDTH,
               height_per_ax: float = DEFAULT_HEIGHT_PER_AX,
               save_path: Optional[str] = None):
    """
    Plot displacement, velocity, acceleration for the event's sensor, aligned at t=0 (trigger).
    """
    EVENTS, DF, SCHEMA = _require_data()
    row = _get_event_row(EVENTS, event_id=event_id, occurrence=occurrence, row_index=row_index)
    seg, rel_t, t0_in_slice = _slice_event(DF, row)

    # NEW: detector-consistent suffix resolver
    inputs = _resolve_inputs_for_row(row, SCHEMA)
    disp_col = inputs.get("disp")
    vel_col  = inputs.get("vel")
    acc_col  = inputs.get("acc")

    # NEW: find secondary triggers for this event and compute their time offsets
    ev_block = _schema_event_block(row["event_id"], SCHEMA)
    sec_trigs = (ev_block.get("secondary_triggers") or [])
    secondary_lines = []
    primary_t0 = float(row["t0_time"])

    for st in sec_trigs:
        if not isinstance(st, dict):
            continue
        sid = st.get("id")
        if not sid:
            continue
        col_time = f"trig_{sid}_t0_time"
        if (col_time in row) and pd.notna(row[col_time]):
            offset = float(row[col_time]) - primary_t0   # seconds relative to primary t0
            secondary_lines.append((sid, offset))
            
    # Build list of panels
    panels = []
    if disp_col and disp_col in seg.columns: panels.append(("disp", disp_col, "Displacement"))
    if vel_col  and vel_col  in seg.columns: panels.append(("vel",  vel_col,  "Velocity"))
    if acc_col  and acc_col  in seg.columns: panels.append(("acc",  acc_col,  "Acceleration"))
    if not panels:
        raise RuntimeError(f"No disp/vel/acc columns found for event '{row['event_id']}'.")

    n_axes = len(panels)
    fig, axes = plt.subplots(n_axes, 1, sharex=share_x, figsize=(fig_width, max(height_per_ax*n_axes, 2.5)))
    if n_axes == 1:
        axes = [axes]

    # Plot each primary series
    for ax, (kind, colname, title) in zip(axes, panels):
        y = seg[colname].to_numpy()
        #ax.plot(rel_t, y, ".")
        ax.plot(rel_t, y, linewidth=0.9)

        # ylimits
        if ylimits and kind in ylimits:
            ymin, ymax = ylimits[kind]
            if ymin is not None or ymax is not None:
                ax.set_ylim(ymin, ymax)

        # velocity/acc panels: ensure y=0 is visible
        if kind in ("vel", "acc"):
            ymin, ymax = ax.get_ylim()
            if not (ymin <= 0 <= ymax):
                ax.set_ylim(min(ymin, 0.0), max(ymax, 0.0))
            ax.axhline(0.0, color='k', linestyle='--', alpha=0.6, zorder=0)

        # enhanced overlays
        if isinstance(extra_series, dict):
            extras = [c for c in extra_series.get(kind, []) if c in seg.columns]
        else:
            extras = [c for c in (extra_series or []) if c in seg.columns]

        for extra in extras:
            ax.plot(rel_t, seg[extra].to_numpy(), linewidth=0.9, alpha=0.8, label=extra)

        # t0 reference
        if 0 <= t0_in_slice < len(rel_t):
            ax.axvline(x=0.0, linestyle="--", linewidth=1.0)

        # secondary triggers: dashed vertical lines at their relative offsets
        for sid, off in secondary_lines:
            ax.axvline(x=off, linestyle="--", linewidth=1.0, alpha=0.7)

        ax.set_ylabel(title)

        if extras:
            ax.legend(loc="best", frameon=False)

    axes[-1].set_xlabel("Time relative to event t0 (s)")
    fig.suptitle(
        f"{row['event_id']}  |  sensor={row.get('sensor','?')}  |  t0={row['t0_time']:.3f}s  "
        f"pre={row['win_pre_s']}s post={row['win_post_s']}s",
        y=0.98
    )

    plt.tight_layout(rect=[0, 0, 1, 0.96])

    # Metrics printout
    if show_metrics:
        metric_cols = [c for c in EVENTS.columns if c.startswith("m_")]
        vals = {c: row[c] for c in metric_cols if c in row and pd.notna(row[c])}
        if vals:
            print("Metrics:")
            for k, v in vals.items():
                if isinstance(v, float):
                    print(f"  {k}: {v:.6g}")
                else:
                    print(f"  {k}: {v}")

    if save_path:
        fig.savefig(save_path, dpi=150)
        print(f"Saved plot → {save_path}")
    plt.show()
    return row

def list_events(events: Optional[pd.DataFrame] = None, max_rows: int = 20):
    """Print a compact list of events (id, index, t0_time)."""
    EVENTS, _, _ = _require_data()
    ev = events if isinstance(events, pd.DataFrame) else EVENTS
    if ev.empty:
        print("(No events)")
        return
    print(ev[["event_id","t0_time","start_index","end_index"]].head(max_rows).to_string(index=True))