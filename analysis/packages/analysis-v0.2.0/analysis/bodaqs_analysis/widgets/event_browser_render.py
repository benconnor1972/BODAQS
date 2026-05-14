# -*- coding: utf-8 -*-
"""Rendering helpers for the event browser widget."""

from __future__ import annotations

from typing import Sequence

import numpy as np

from bodaqs_analysis.sensor_aliases import canonical_end


def choose_active_sensor(
    *,
    inferred_sensor: str | None,
    selected_sensors: Sequence[str],
) -> str | None:
    sel = tuple(canonical_end(s) for s in selected_sensors or () if canonical_end(s))
    inferred = canonical_end(inferred_sensor) if inferred_sensor else ""
    if not sel:
        return inferred or inferred_sensor
    if len(sel) == 1:
        return sel[0]
    if inferred and inferred in sel:
        return inferred
    return sel[0]


def set_ylim_zero_at_frac(ax_i, data_min: float, data_max: float, frac0: float, pad: float = 0.05) -> None:
    """
    Choose y-lims [ymin, ymax] that contain [data_min, data_max] and place y=0 at frac0.
    frac0 in (0,1): 0 at ymin + frac0*(ymax-ymin).
    """
    if not np.isfinite(data_min) or not np.isfinite(data_max):
        return
    if data_min == data_max:
        span = abs(data_min) if data_min != 0 else 1.0
        data_min -= 0.5 * span
        data_max += 0.5 * span

    req = []
    if data_min < 0:
        req.append((-data_min) / max(frac0, 1e-6))
    if data_max > 0:
        req.append((data_max) / max(1.0 - frac0, 1e-6))
    if not req:
        req.append(max(abs(data_min), abs(data_max), 1.0))

    rng = max(req) * (1.0 + pad)
    ymin = -frac0 * rng
    ymax = (1.0 - frac0) * rng
    ax_i.set_ylim(ymin, ymax)

