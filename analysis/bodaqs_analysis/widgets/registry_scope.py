# -*- coding: utf-8 -*-
"""Shared helpers for registry-policy handling across widget scope."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from bodaqs_analysis.widgets.contracts import RegistryPolicy, SessionLoader


def validate_registry_policy(policy: RegistryPolicy) -> None:
    if policy not in {"union", "intersection", "strict"}:
        raise ValueError("registry_policy must be one of: 'union', 'intersection', 'strict'")


def merge_registries_by_session(
    registry_by_session: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for session_key in sorted(registry_by_session.keys()):
        reg = registry_by_session[session_key]
        for signal_col, info in reg.items():
            if signal_col not in merged and isinstance(info, Mapping):
                merged[signal_col] = dict(info)
    return merged


def sort_signals_by_unit(
    signal_cols: Sequence[str],
    registry: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    def key(sig: str) -> tuple[str, str]:
        info = registry.get(sig, {})
        unit = info.get("unit") if isinstance(info, Mapping) else None
        unit_s = unit if isinstance(unit, str) and unit.strip() else "~"
        return (unit_s, sig)

    return sorted(list(signal_cols), key=key)


def _reduce_signal_sets(
    *,
    session_order: Sequence[str],
    signal_sets: Mapping[str, set[str]],
    policy: RegistryPolicy,
) -> set[str]:
    ordered = [str(s) for s in session_order if str(s) in signal_sets]
    sets = [signal_sets[sk] for sk in ordered]
    if not sets:
        return set()

    if policy == "strict":
        first_set = sets[0]
        mismatched = [sk for sk, s in zip(ordered, sets) if s != first_set]
        if mismatched:
            sample = ", ".join(mismatched[:3])
            raise ValueError(
                "registry_policy='strict' requires identical signal sets across selected sessions; "
                f"mismatched sessions include: {sample}"
            )
        return set(first_set)

    if policy == "intersection":
        return set.intersection(*sets)

    return set.union(*sets)


def compute_signal_universe(
    *,
    session_ids: Sequence[str],
    session_signal_cols: Mapping[str, Sequence[str]],
    registry_by_session: Mapping[str, Mapping[str, Mapping[str, Any]]],
    policy: RegistryPolicy,
) -> list[str]:
    signal_sets = {str(sk): set(map(str, session_signal_cols.get(sk, []))) for sk in session_ids}
    base = sorted(_reduce_signal_sets(session_order=session_ids, signal_sets=signal_sets, policy=policy))
    merged_registry = merge_registries_by_session(registry_by_session)
    return sort_signals_by_unit(base, merged_registry)


def load_signal_registries_for_sessions(
    *,
    session_keys: Sequence[str],
    session_loader: SessionLoader,
) -> dict[str, dict[str, Mapping[str, Any]]]:
    registries: dict[str, dict[str, Mapping[str, Any]]] = {}
    for session_key in session_keys:
        sess = session_loader(str(session_key))
        meta = (sess or {}).get("meta") or {}
        reg = meta.get("signals") or {}
        registries[str(session_key)] = reg if isinstance(reg, dict) else {}
    return registries


def apply_registry_policy_to_registries(
    *,
    registries_by_session: Mapping[str, Mapping[str, Mapping[str, Any]]],
    policy: RegistryPolicy,
    session_order: Sequence[str],
) -> dict[str, dict[str, Mapping[str, Any]]]:
    signal_sets = {str(sk): set(reg.keys()) for sk, reg in registries_by_session.items()}
    common_keys = _reduce_signal_sets(
        session_order=session_order,
        signal_sets=signal_sets,
        policy=policy,
    )

    if policy in {"union", "strict"}:
        return {str(sk): dict(registries_by_session[str(sk)]) for sk in session_order if str(sk) in registries_by_session}

    return {
        str(sk): {k: v for k, v in registries_by_session[str(sk)].items() if k in common_keys}
        for sk in session_order
        if str(sk) in registries_by_session
    }

