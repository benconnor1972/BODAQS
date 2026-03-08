# -*- coding: utf-8 -*-
"""Plot/trace helpers for session window browser widget."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go


def init_session_window_figure(fig: go.FigureWidget) -> None:
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


def build_event_hovertext(
    *,
    row: pd.Series,
    event_type_col: str,
    event_signal_col: str,
    trigger_time_col: str,
    max_metrics: int = 10,
) -> str:
    et = str(row.get(event_type_col, ""))
    sig = str(row.get(event_signal_col, ""))
    t_ = row.get(trigger_time_col, None)
    bits = [f"type: {et}"]
    if sig:
        bits.append(f"signal: {sig}")
    if t_ is not None and np.isfinite(pd.to_numeric(t_, errors="coerce")):
        bits.append(f"t: {float(t_):.3f}s")

    metric_items: list[tuple[str, float]] = []
    for c, v in row.items():
        if not isinstance(c, str) or not c.startswith("m_"):
            continue
        if isinstance(v, (int, float, np.integer, np.floating)) and np.isfinite(v):
            metric_items.append((c, float(v)))
    metric_items.sort(key=lambda x: x[0])
    for c, v in metric_items[:max_metrics]:
        bits.append(f"{c}: {v:.3g}")
    return "<br>".join(bits)


def event_color_for_pair(
    *,
    color_map: dict[str, str],
    event_type: str,
    signal: str,
) -> str:
    key = f"{event_type}||{signal}"
    palette = [
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
        "#bcbd22",
        "#17becf",
    ]
    if key not in color_map:
        color_map[key] = palette[len(color_map) % len(palette)]
    return color_map[key]

