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
            local_values = _values_with_continuity_breaks(stream_df, local_column)
            figure.add_trace(
                go.Scattergl(
                    x=distance,
                    y=local_values,
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
                y=_values_with_continuity_breaks(stream_df, column),
                mode="lines",
                name=f"{label} (smoothed)",
                legendgroup=column,
                line={"width": 2},
            ),
            row=row,
            col=1,
        )
        yaxis_options: dict[str, Any] = {"title_text": unit}
        if column == "twistiness_rad_per_m":
            yaxis_options["range"] = [0.0, 0.5]
        figure.update_yaxes(row=row, col=1, **yaxis_options)

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


def make_spatial_context_histogram_figure(
    stream_df: pd.DataFrame,
    *,
    metrics: Optional[Iterable[str]] = None,
    bin_count: int = 10,
    selected_distance_range_m: Optional[Sequence[float]] = None,
    gradient_range: Optional[Sequence[float]] = None,
    twistiness_maximum: Optional[float] = None,
    suspension_activity_maximum: Optional[float] = None,
) -> go.Figure:
    """Build one exact-bin histogram for each selected smoothed metric."""

    if not isinstance(stream_df, pd.DataFrame) or stream_df.empty:
        raise ValueError("stream_df must be a non-empty DataFrame")
    if "distance_m" not in stream_df.columns:
        raise ValueError("stream_df must contain distance_m")
    if isinstance(bin_count, bool) or not isinstance(bin_count, (int, np.integer)):
        raise ValueError("bin_count must be an integer")
    if int(bin_count) < 1:
        raise ValueError("bin_count must be at least 1")
    gradient_bounds = _optional_histogram_range(
        gradient_range,
        name="gradient_range",
    )
    twistiness_bounds = _optional_zero_based_histogram_range(
        twistiness_maximum,
        name="twistiness_maximum",
    )
    activity_bounds = _optional_zero_based_histogram_range(
        suspension_activity_maximum,
        name="suspension_activity_maximum",
    )

    supported = {name: (label, unit) for name, label, unit in _METRIC_ROWS}
    requested = list(metrics) if metrics is not None else available_spatial_context_metrics(stream_df)
    selected = [name for name in requested if name in supported and name in stream_df.columns]
    if not selected:
        raise ValueError("No supported spatial-context metrics are available to plot")

    view = stream_df
    if selected_distance_range_m is not None:
        if len(selected_distance_range_m) != 2:
            raise ValueError("selected_distance_range_m must contain start and end")
        start_m, end_m = sorted(float(value) for value in selected_distance_range_m)
        distance = pd.to_numeric(stream_df["distance_m"], errors="coerce")
        view = stream_df.loc[distance.between(start_m, end_m, inclusive="both")]

    figure = make_subplots(
        rows=len(selected),
        cols=1,
        vertical_spacing=min(0.10, 0.24 / max(1, len(selected))),
        subplot_titles=[supported[name][0] for name in selected],
    )
    for row, column in enumerate(selected, start=1):
        label, unit = supported[column]
        values = pd.to_numeric(view[column], errors="coerce")
        values = values[np.isfinite(values)]
        forced_range: Optional[tuple[float, float]] = None
        include_underflow = False
        include_overflow = False
        if column == "gradient_fraction":
            forced_range = gradient_bounds
            include_underflow = forced_range is not None
            include_overflow = forced_range is not None
        elif column == "twistiness_rad_per_m":
            forced_range = twistiness_bounds
            include_overflow = forced_range is not None
        elif column.endswith("_suspension_activity"):
            forced_range = activity_bounds
            include_overflow = forced_range is not None
        labels, counts, categories = _exact_histogram_counts(
            values.to_numpy(float),
            int(bin_count),
            forced_range=forced_range,
            include_underflow=include_underflow,
            include_overflow=include_overflow,
        )
        figure.add_trace(
            go.Bar(
                x=labels,
                y=counts,
                name=label,
                showlegend=False,
                marker_color=[
                    "darkorange" if category != "in_range" else "#636efa"
                    for category in categories
                ],
                customdata=np.asarray(categories, dtype=object),
                hovertemplate="%{x}<br>Samples: %{y}<extra></extra>",
            ),
            row=row,
            col=1,
        )
        figure.update_xaxes(title_text=unit, row=row, col=1)
        figure.update_yaxes(title_text="Samples", row=row, col=1)

    figure.update_layout(
        height=max(330, 230 * len(selected)),
        title=f"Selected spatial-context distributions ({int(bin_count)} in-range bins)",
        bargap=0.05,
        margin={"t": 90},
    )
    return figure


def _exact_histogram_counts(
    values: np.ndarray,
    bin_count: int,
    *,
    forced_range: Optional[tuple[float, float]],
    include_underflow: bool,
    include_overflow: bool,
) -> tuple[list[str], np.ndarray, list[str]]:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if forced_range is not None:
        start, end = forced_range
    elif finite.size == 0:
        start = 0.0
        end = 1.0
    else:
        start = float(np.min(finite))
        maximum = float(np.max(finite))
        if maximum > start:
            span = maximum - start
            end = maximum + max(span * 1.0e-9, np.finfo(float).eps * max(1.0, abs(maximum)))
        else:
            half_span = max(abs(start) * 0.005, 0.5)
            start -= half_span
            end = maximum + half_span
    in_range = finite[(finite >= start) & (finite <= end)]
    counts, edges = np.histogram(in_range, bins=bin_count, range=(start, end))
    labels = [
        _histogram_interval_label(edges[index], edges[index + 1], index == bin_count - 1)
        for index in range(bin_count)
    ]
    categories = ["in_range"] * bin_count
    output_counts = counts.astype(np.int64)
    if include_underflow:
        labels.insert(0, f"< {_format_histogram_edge(start)}")
        output_counts = np.r_[int(np.count_nonzero(finite < start)), output_counts]
        categories.insert(0, "underflow")
    if include_overflow:
        labels.append(f"> {_format_histogram_edge(end)}")
        output_counts = np.r_[output_counts, int(np.count_nonzero(finite > end))]
        categories.append("overflow")
    return labels, output_counts, categories


def _optional_histogram_range(
    value: Optional[Sequence[float]],
    *,
    name: str,
) -> Optional[tuple[float, float]]:
    if value is None:
        return None
    if len(value) != 2:
        raise ValueError(f"{name} must contain a lower and upper limit")
    lower, upper = (float(item) for item in value)
    if not np.isfinite(lower) or not np.isfinite(upper) or upper <= lower:
        raise ValueError(f"{name} limits must be finite and strictly increasing")
    return lower, upper


def _optional_zero_based_histogram_range(
    maximum: Optional[float],
    *,
    name: str,
) -> Optional[tuple[float, float]]:
    if maximum is None:
        return None
    upper = float(maximum)
    if not np.isfinite(upper) or upper <= 0.0:
        raise ValueError(f"{name} must be finite and greater than zero")
    return 0.0, upper


def _histogram_interval_label(start: float, end: float, final: bool) -> str:
    closing = "]" if final else ")"
    return f"[{_format_histogram_edge(start)}, {_format_histogram_edge(end)}{closing}"


def _format_histogram_edge(value: float) -> str:
    return f"{value:.4g}"


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
    continuity_break = np.zeros(max(0, len(view.index) - 1), dtype=bool)
    if "continuity_segment" in stream_df.columns:
        source_segments = pd.to_numeric(
            stream_df["continuity_segment"], errors="coerce"
        ).to_numpy(float)
        selected_segments = source_segments[source_rows]
        continuity_break = np.diff(selected_segments) != 0.0
    split_indices = np.flatnonzero(
        (np.diff(times) <= 0.0)
        | (np.diff(times) > max_time_gap_s)
        | (np.diff(source_rows) > 1)
        | continuity_break
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


def _values_with_continuity_breaks(stream_df: pd.DataFrame, column: str) -> pd.Series:
    values = pd.to_numeric(stream_df[column], errors="coerce").copy()
    if "continuity_segment" not in stream_df.columns or len(values.index) < 2:
        return values
    segments = pd.to_numeric(stream_df["continuity_segment"], errors="coerce").to_numpy(float)
    break_rows = np.flatnonzero(np.diff(segments) != 0.0) + 1
    values.iloc[break_rows] = np.nan
    return values
