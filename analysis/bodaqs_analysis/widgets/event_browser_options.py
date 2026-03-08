# -*- coding: utf-8 -*-
"""Option/list building helpers for the event browser widget."""

from __future__ import annotations

from typing import Callable, Sequence

import pandas as pd


def build_event_type_options(
    *,
    events_df: pd.DataFrame,
    scope_sessions: Sequence[str],
    session_key_col: str,
    event_type_col: str,
) -> list[str]:
    if not scope_sessions:
        return []
    sub = events_df[events_df[session_key_col].astype(str).isin(map(str, scope_sessions))].copy()
    return sorted(sub[event_type_col].dropna().astype(str).unique().tolist())


def build_sensor_options(
    *,
    events_df: pd.DataFrame,
    scope_sessions: Sequence[str],
    selected_event_type: str | None,
    session_key_col: str,
    event_type_col: str,
    resolve_sensor_for_row_fn: Callable[[pd.Series], str],
    exclude_sensors: Sequence[str] = ("active",),
) -> list[str]:
    if not scope_sessions:
        return []

    sub = events_df[events_df[session_key_col].astype(str).isin(map(str, scope_sessions))].copy()
    if selected_event_type:
        sub = sub[sub[event_type_col].astype(str) == str(selected_event_type)].copy()

    sensors = set()
    excluded = {str(s) for s in exclude_sensors}
    for _, row in sub.iterrows():
        s = resolve_sensor_for_row_fn(row)
        if s and s not in excluded:
            sensors.add(s)
    return sorted(sensors)


def build_event_labels(
    *,
    filtered_events_df: pd.DataFrame,
    session_id_col: str,
    event_id_col: str,
    trigger_time_col: str,
) -> list[str]:
    if filtered_events_df is None or filtered_events_df.empty:
        return []
    labels: list[str] = []
    for _, r in filtered_events_df.sort_values([session_id_col, trigger_time_col]).iterrows():
        labels.append(
            f"{r[session_id_col]} :: {r[event_id_col]}  |  t={float(r[trigger_time_col]):.3f}s"
        )
    return labels


def parse_event_label(label: str) -> tuple[str, str]:
    left, rest = str(label).split(" :: ", 1)
    event_id = rest.split("  |  ", 1)[0].strip()
    session_id = left.strip()
    return session_id, event_id

