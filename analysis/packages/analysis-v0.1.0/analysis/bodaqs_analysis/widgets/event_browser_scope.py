# -*- coding: utf-8 -*-
"""Scope and sensor-resolution helpers for the event browser widget."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from bodaqs_analysis.sensor_aliases import canonical_sensor_id
from bodaqs_analysis.widgets.contracts import RegistryPolicy
from bodaqs_analysis.widgets.registry_scope import apply_registry_policy_to_registries


@dataclass(frozen=True)
class ScopeConfig:
    session_key_col: str
    event_type_col: str
    signal_col: str
    registry_policy: RegistryPolicy


@dataclass
class ScopeResolution:
    registries_by_session: dict[str, dict[str, Mapping[str, Any]]]
    schema_maps_by_session: dict[str, dict[str, dict[str, str]]]
    error: str | None = None


def get_registry_from_session_meta(session: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    meta = (session or {}).get("meta") or {}
    sigs = meta.get("signals")
    if not isinstance(sigs, dict) or not sigs:
        raise ValueError("session['meta']['signals'] missing/empty (required for segment extraction)")
    return sigs


def build_schema_sensor_maps(
    schema_obj: Mapping[str, Any],
    registry_obj: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    if not isinstance(schema_obj, Mapping) or not schema_obj:
        return out

    for sid, sch in schema_obj.items():
        if not isinstance(sch, Mapping):
            continue
        sid_s = str(sid).strip()
        if not sid_s:
            continue

        triggers = sch.get("triggers") or {}
        if not isinstance(triggers, Mapping):
            continue

        m: dict[str, str] = {}
        for role, trig in triggers.items():
            if not isinstance(trig, Mapping):
                continue

            sigcol = trig.get("signal_col")
            sigcol = sigcol.strip() if isinstance(sigcol, str) else ""
            if not sigcol:
                continue

            info = registry_obj.get(sigcol)
            if not isinstance(info, Mapping):
                continue
            sensor = info.get("sensor")
            sensor = sensor.strip() if isinstance(sensor, str) else ""
            if not sensor:
                continue
            sensor = canonical_sensor_id(sensor)

            if isinstance(role, str) and role.strip():
                m[role.strip()] = sensor
            m[sigcol] = sensor

        if m:
            out[sid_s] = m
    return out


def rebuild_scope_resolution(
    *,
    scope_sessions: Sequence[str],
    get_session: Callable[[str], Mapping[str, Any]],
    schema: Mapping[str, Any],
    config: ScopeConfig,
) -> ScopeResolution:
    registries_by_session: dict[str, dict[str, Mapping[str, Any]]] = {}
    for sk in scope_sessions:
        try:
            sess = get_session(str(sk))
            reg = get_registry_from_session_meta(sess)
            registries_by_session[str(sk)] = reg
        except Exception as exc:
            return ScopeResolution({}, {}, f"Failed to load registry for {sk}: {exc!r}")

    if not registries_by_session:
        return ScopeResolution({}, {}, "No registries available for selected sessions.")

    try:
        registries_by_session = apply_registry_policy_to_registries(
            registries_by_session=registries_by_session,
            policy=config.registry_policy,
            session_order=[str(s) for s in scope_sessions],
        )
    except Exception as exc:
        return ScopeResolution({}, {}, str(exc))

    schema_maps_by_session: dict[str, dict[str, dict[str, str]]] = {}
    for sk, reg in registries_by_session.items():
        schema_maps_by_session[sk] = build_schema_sensor_maps(schema, reg)

    return ScopeResolution(
        registries_by_session=registries_by_session,
        schema_maps_by_session=schema_maps_by_session,
        error=None,
    )


def resolve_sensor_for_row(
    *,
    session_key: object,
    schema_id_val: object,
    token_val: object,
    resolution: ScopeResolution,
) -> str:
    sid = str(schema_id_val).strip() if schema_id_val is not None else ""
    tok = str(token_val).strip() if token_val is not None else ""
    sk = str(session_key).strip() if session_key is not None else ""
    if not sid or not tok or not sk:
        return ""

    maps = resolution.schema_maps_by_session.get(sk, {})
    reg = resolution.registries_by_session.get(sk, {})

    m = maps.get(sid)
    if isinstance(m, Mapping):
        s = m.get(tok)
        if isinstance(s, str) and s.strip():
            return canonical_sensor_id(s)

    info = reg.get(tok)
    if isinstance(info, Mapping):
        s2 = info.get("sensor")
        if isinstance(s2, str) and s2.strip():
            return canonical_sensor_id(s2)
    return ""


def infer_event_sensor(
    *,
    ev_row: pd.Series,
    candidate_token_cols: Sequence[str],
    config: ScopeConfig,
    resolution: ScopeResolution,
) -> str | None:
    if ev_row is None:
        return None

    sk = ev_row.get(config.session_key_col, None)
    schema_id_val = ev_row.get(config.event_type_col, None)
    for col in candidate_token_cols:
        tok = ev_row.get(col, None)
        s = resolve_sensor_for_row(
            session_key=sk,
            schema_id_val=schema_id_val,
            token_val=tok,
            resolution=resolution,
        )
        if s:
            return s
    return None


def filter_events(
    *,
    events_df: pd.DataFrame,
    scope_sessions: Sequence[str],
    selected_event_type: str | None,
    selected_sensors: Sequence[str],
    config: ScopeConfig,
    resolution: ScopeResolution,
) -> pd.DataFrame:
    if not scope_sessions:
        return events_df.iloc[0:0].copy()
    if resolution.error:
        return events_df.iloc[0:0].copy()

    sub = events_df[events_df[config.session_key_col].astype(str).isin(map(str, scope_sessions))].copy()
    if selected_event_type:
        sub = sub[sub[config.event_type_col].astype(str) == str(selected_event_type)].copy()

    sensors = tuple(canonical_sensor_id(s) for s in selected_sensors or () if canonical_sensor_id(s))
    if not sensors:
        return sub

    sel_set = set(sensors)
    mask = []
    for _, r in sub.iterrows():
        s = resolve_sensor_for_row(
            session_key=r.get(config.session_key_col),
            schema_id_val=r.get(config.event_type_col),
            token_val=r.get(config.signal_col),
            resolution=resolution,
        )
        mask.append(bool(s) and (s in sel_set))
    return sub.loc[pd.Series(mask, index=sub.index)].copy()

