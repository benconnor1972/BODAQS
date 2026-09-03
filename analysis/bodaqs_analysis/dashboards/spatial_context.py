"""Plotting and selection helpers for distance-domain spatial context."""

from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


_METRIC_ROWS: tuple[tuple[str, str, str], ...] = (
    ("gradient_fraction", "Gradient", "rise / run"),
    ("twistiness_rad_per_m", "Twistiness", "rad / m"),
    ("front_suspension_activity", "Front activity", "m / m"),
    ("rear_suspension_activity", "Rear activity", "m / m"),
    ("combined_suspension_activity", "Combined activity", "m / m"),
)


def available_spatial_context_metrics(stream_df: pd.DataFrame) -> list[str]:
    """Return supported plotted metrics that contain at least one finite value."""

    available: list[str] = []
    for column, _label, _unit in _METRIC_ROWS:
        if column not in stream_df.columns:
            continue
        values = pd.to_numeric(stream_df[column], errors="coerce").to_numpy(float)
        if np.isfinite(values).any():
            available.append(column)
    return available


def make_spatial_context_figure(
    stream_df: pd.DataFrame,
    *,
    metrics: Optional[Iterable[str]] = None,
    show_local: bool = True,
    selected_distance_range_m: Optional[Sequence[float]] = None,
) -> go.Figure:
    """Build a linked distance-axis Plotly figure for one spatial stream."""

    if not isinstance(stream_df, pd.DataFrame) or stream_df.empty:
        raise ValueError("stream_df must be a non-empty DataFrame")
    if "distance_m" not in stream_df.columns:
        raise ValueError("stream_df must contain distance_m")

    supported = {name: (label, unit) for name, label, unit in _METRIC_ROWS}
    requested = list(metrics) if metrics is not None else available_spatial_context_metrics(stream_df)
    selected = [name for name in requested if name in supported and name in stream_df.columns]
    if not selected:
        raise ValueError("No supported spatial-context metrics are available to plot")

    distance = pd.to_numeric(stream_df["distance_m"], errors="coerce")
    titles = [supported[name][0] for name in selected]
    figure = make_subplots(
        rows=len(selected),
        cols=1,
        shared_xaxes=True,
        vertical_spacing=min(0.08, 0.22 / max(1, len(selected))),
        subplot_titles=titles,
    )

    for row, column in enumerate(selected, start=1):
        label, unit = supported[column]
        local_column = _local_column_for(column)
        if show_local and local_column in stream_df.columns:
            figure.add_trace(
                go.Scattergl(
                    x=distance,
                    y=pd.to_numeric(stream_df[local_column], errors="coerce"),
                    mode="lines",
                    name=f"{label} (local)",
                    legendgroup=column,
                    line={"width": 1, "dash": "dot"},
                    opacity=0.45,
                ),
                row=row,
                col=1,
            )
        figure.add_trace(
            go.Scattergl(
                x=distance,
                y=pd.to_numeric(stream_df[column], errors="coerce"),
                mode="lines",
                name=f"{label} (smoothed)",
                legendgroup=column,
                line={"width": 2},
            ),
            row=row,
            col=1,
        )
        figure.update_yaxes(title_text=unit, row=row, col=1)

    if selected_distance_range_m is not None:
        if len(selected_distance_range_m) != 2:
            raise ValueError("selected_distance_range_m must contain start and end")
        start_m, end_m = sorted(float(value) for value in selected_distance_range_m)
        figure.add_vrect(
            x0=start_m,
            x1=end_m,
            fillcolor="gold",
            opacity=0.14,
            line_width=1,
            line_color="darkgoldenrod",
            row="all",
            col=1,
        )

    figure.update_xaxes(title_text="Distance [m]", row=len(selected), col=1)
    figure.update_layout(
        height=max(380, 245 * len(selected)),
        title="Spatial context",
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0.0},
        margin={"t": 110},
    )
    return figure


def spatial_selection_to_time_ranges(
    stream_df: pd.DataFrame,
    start_distance_m: float,
    end_distance_m: float,
    *,
    max_time_gap_s: float = 5.0,
) -> list[dict[str, float | int]]:
    """Map a distance selection to contiguous representative-time ranges.

    A distance selection can map to multiple time intervals when representative
    time has a gap. The result is intentionally explicit so a future Workbench
    consumer does not accidentally span missing evidence.
    """

    required = {"distance_m", "representative_time_s"}
    missing = sorted(required - set(stream_df.columns))
    if missing:
        raise ValueError(f"stream_df is missing required columns: {missing}")
    if not np.isfinite(max_time_gap_s) or max_time_gap_s <= 0:
        raise ValueError("max_time_gap_s must be finite and > 0")

    low_m, high_m = sorted((float(start_distance_m), float(end_distance_m)))
    view = pd.DataFrame(
        {
            "distance_m": pd.to_numeric(stream_df["distance_m"], errors="coerce"),
            "time_s": pd.to_numeric(stream_df["representative_time_s"], errors="coerce"),
            "source_row": np.arange(len(stream_df.index), dtype=int),
        }
    )
    valid = np.isfinite(view["distance_m"]) & np.isfinite(view["time_s"])
    if "distance_support_fraction" in stream_df.columns:
        support = pd.to_numeric(stream_df["distance_support_fraction"], errors="coerce")
        valid &= support > 0.0
    view = view.loc[valid & view["distance_m"].between(low_m, high_m, inclusive="both")]
    view = view.sort_values("distance_m", kind="stable").reset_index(drop=True)
    if view.empty:
        return []

    times = view["time_s"].to_numpy(float)
    source_rows = view["source_row"].to_numpy(int)
    split_indices = np.flatnonzero(
        (np.diff(times) <= 0.0)
        | (np.diff(times) > max_time_gap_s)
        | (np.diff(source_rows) > 1)
    ) + 1
    groups = np.split(np.arange(len(view)), split_indices)
    ranges: list[dict[str, float | int]] = []
    for indices in groups:
        if not len(indices):
            continue
        group = view.iloc[indices]
        ranges.append(
            {
                "start_time_s": float(group["time_s"].iloc[0]),
                "end_time_s": float(group["time_s"].iloc[-1]),
                "start_distance_m": float(group["distance_m"].iloc[0]),
                "end_distance_m": float(group["distance_m"].iloc[-1]),
                "representative_sample_count": int(len(group.index)),
            }
        )
    return ranges


def _local_column_for(column: str) -> str:
    if column == "gradient_fraction":
        return "gradient_fraction_local"
    if column == "twistiness_rad_per_m":
        return "curvature_abs_rad_per_m_local"
    if column.endswith("_suspension_activity"):
        return f"{column}_local"
    return ""
