# -*- coding: utf-8 -*-
"""Shared data/service helpers for metric consumer widgets."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd

from bodaqs_analysis.widgets.contracts import RegistryPolicy, SessionLoader
from bodaqs_analysis.widgets.registry_scope import (
    apply_registry_policy_to_registries,
    load_signal_registries_for_sessions,
)


def require_cols(df: pd.DataFrame, cols: Sequence[str], *, name: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{name} missing required column(s): {missing}")


def metric_cols(metrics_df: pd.DataFrame) -> list[str]:
    return [c for c in metrics_df.columns if isinstance(c, str) and c.startswith("m_")]


def build_metric_viz_df(
    *,
    events_df: pd.DataFrame,
    metrics_df: pd.DataFrame,
    session_key_col: str,
    event_id_col: str,
    schema_id_col: str,
    event_type_col: str,
    signal_col: str,
    include_optional_event_cols: Sequence[str] = ("run_id", "session_id"),
    require_event_type_col: bool = False,
) -> tuple[pd.DataFrame, list[str]]:
    if events_df is None or events_df.empty:
        raise ValueError("No events found for selected sessions.")
    if metrics_df is None or metrics_df.empty:
        raise ValueError("No metrics found for selected sessions.")

    event_required = [session_key_col, event_id_col, schema_id_col, signal_col]
    if require_event_type_col and event_type_col not in event_required:
        event_required.append(event_type_col)
    require_cols(events_df, tuple(event_required), name="events_df")
    require_cols(metrics_df, (session_key_col, event_id_col, schema_id_col), name="metrics_df")

    mcols = metric_cols(metrics_df)
    if not mcols:
        raise ValueError("No metric columns found in metrics_df (expected 'm_' prefix)")

    left_cols = [session_key_col, schema_id_col, event_id_col, signal_col]
    for c in list(include_optional_event_cols) + [event_type_col]:
        if c in events_df.columns and c not in left_cols:
            left_cols.append(c)

    right_cols = [session_key_col, schema_id_col, event_id_col] + mcols
    viz_df = events_df[left_cols].merge(
        metrics_df[right_cols],
        on=[session_key_col, schema_id_col, event_id_col],
        how="inner",
        validate="one_to_one",
    )

    if event_type_col not in viz_df.columns:
        viz_df[event_type_col] = viz_df[schema_id_col].astype(str)
    if viz_df.empty:
        raise ValueError("No rows after building viz_df (events/metrics join produced nothing)")

    return viz_df, mcols


def _build_schema_sensor_maps(
    schema_obj: Mapping[str, Any],
    registry_obj: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    if not isinstance(schema_obj, Mapping):
        return out

    for sid, sch in schema_obj.items():
        if not isinstance(sid, str) or not isinstance(sch, Mapping):
            continue
        triggers = sch.get("triggers") or {}
        if not isinstance(triggers, Mapping):
            continue

        m: dict[str, str] = {}
        for role, trig in triggers.items():
            if not isinstance(trig, Mapping):
                continue

            sigcol = trig.get("signal_col")
            if not isinstance(sigcol, str) or not sigcol.strip():
                continue
            sigcol = sigcol.strip()

            info = registry_obj.get(sigcol)
            if not isinstance(info, Mapping):
                continue
            sensor = info.get("sensor")
            if not isinstance(sensor, str) or not sensor.strip():
                continue
            sensor = sensor.strip()

            if isinstance(role, str) and role.strip():
                m[role.strip()] = sensor
            m[sigcol] = sensor

        if m:
            out[sid] = m
    return out


def _resolve_sensor(
    *,
    schema_sensor_map_by_schema: Mapping[str, Mapping[str, str]],
    registry: Mapping[str, Mapping[str, Any]],
    schema_id_val: object,
    token_val: object,
) -> str:
    sid = str(schema_id_val) if schema_id_val is not None else ""
    tok = str(token_val) if token_val is not None else ""
    sid = sid.strip()
    tok = tok.strip()
    if not sid or not tok:
        return ""

    m = schema_sensor_map_by_schema.get(sid)
    if isinstance(m, Mapping):
        s = m.get(tok)
        if isinstance(s, str) and s.strip():
            return s.strip()

    info = registry.get(tok)
    if isinstance(info, Mapping):
        s2 = info.get("sensor")
        if isinstance(s2, str) and s2.strip():
            return s2.strip()
    return ""


def registry_maps_for_sessions(
    *,
    session_keys: Sequence[str],
    session_loader: SessionLoader,
    schema: Mapping[str, Any],
    registry_policy: RegistryPolicy,
) -> tuple[dict[str, dict[str, Mapping[str, Any]]], dict[str, dict[str, dict[str, str]]]]:
    registries = load_signal_registries_for_sessions(
        session_keys=session_keys,
        session_loader=session_loader,
    )
    if not registries:
        raise ValueError("No session registries available for sensor resolution")

    nonempty = [sk for sk, r in registries.items() if r]
    if not nonempty:
        raise ValueError(
            "Signal registry not found or empty in selected sessions "
            "(expected session_loader(session_key)['meta']['signals'])"
        )

    effective_registries = apply_registry_policy_to_registries(
        registries_by_session=registries,
        policy=registry_policy,
        session_order=session_keys,
    )

    schema_maps_by_session: dict[str, dict[str, dict[str, str]]] = {}
    for sk, eff in effective_registries.items():
        schema_maps_by_session[sk] = _build_schema_sensor_maps(schema, eff)

    return effective_registries, schema_maps_by_session


def assign_sensor_column(
    *,
    viz_df: pd.DataFrame,
    session_key_col: str,
    schema_id_col: str,
    signal_col: str,
    registries_by_session: Mapping[str, Mapping[str, Mapping[str, Any]]],
    schema_maps_by_session: Mapping[str, Mapping[str, Mapping[str, str]]],
) -> pd.Series:
    def _resolve_for_row(session_key: object, schema_id_val: object, token_val: object) -> str:
        sk = str(session_key) if session_key is not None else ""
        reg = registries_by_session.get(sk, {})
        maps = schema_maps_by_session.get(sk, {})
        return _resolve_sensor(
            schema_sensor_map_by_schema=maps,
            registry=reg,
            schema_id_val=schema_id_val,
            token_val=token_val,
        )

    return pd.Series(
        [
            _resolve_for_row(sk, sid, tok)
            for sk, sid, tok in zip(
                viz_df[session_key_col].astype(str),
                viz_df[schema_id_col].astype(str),
                viz_df[signal_col].astype(str),
            )
        ],
        index=viz_df.index,
    )

