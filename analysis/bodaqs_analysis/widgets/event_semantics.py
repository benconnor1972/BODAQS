# -*- coding: utf-8 -*-
"""Shared semantic signal-role helpers for segment/event widgets."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from bodaqs_analysis.sensor_aliases import canonical_end


SemanticKey = tuple[str, str, str, str]  # (quantity, unit, kind, op_chain_key)


def op_chain_key(op_chain: Any) -> str:
    if op_chain is None:
        return ""
    if isinstance(op_chain, (list, tuple)):
        return "|".join(str(x) for x in op_chain)
    return str(op_chain)


def registry_signal_options_for_context(
    *,
    registry: Mapping[str, Mapping[str, Any]],
    end: str | None,
    drop_kinds: Sequence[str] = ("qc",),
    primary_only: bool = False,
) -> list[tuple[str, SemanticKey]]:
    """
    Build semantic signal options for one event context from registry entries.

    Returns SelectMultiple-friendly pairs: (label, semantic_key)
    where semantic_key=(quantity, unit, kind, op_chain_key).
    """
    end_key = canonical_end(end)
    if not end_key:
        return []

    opts: list[tuple[str, SemanticKey]] = []
    seen: set[SemanticKey] = set()
    drop_set = set(map(str, drop_kinds))

    for _col, info in registry.items():
        if not isinstance(info, Mapping):
            continue
        if canonical_end(info.get("end")) != end_key:
            continue
        if primary_only and str(info.get("processing_role") or "").strip().lower() != "primary_analysis":
            continue

        kind = str(info.get("kind") or "").strip()
        if kind in drop_set:
            continue

        quantity = info.get("quantity")
        if not isinstance(quantity, str) or not quantity.strip():
            continue
        quantity = quantity.strip()

        unit = str(info.get("unit") or "")
        opk = op_chain_key(info.get("op_chain") or [])
        key: SemanticKey = (quantity, unit, kind, opk)
        if key in seen:
            continue
        seen.add(key)

        unit_s = f" [{unit}]" if unit else ""
        kind_s = f" ({kind})" if kind else ""
        op_s = f" -> {opk}" if opk else ""
        label = f"{quantity}{unit_s}{kind_s}{op_s}"
        opts.append((label, key))

    order = {"disp": 0, "disp_norm": 1, "vel": 2, "acc": 3, "raw": 4}
    opts.sort(key=lambda kv: (order.get(kv[1][0], 99), kv[0]))
    return opts


def role_spec_from_semantic_tuple(
    RoleSpecCls: Any,
    *,
    role: str,
    end: str | None,
    semantic: SemanticKey,
) -> Any:
    """
    Construct RoleSpec robustly across RoleSpec constructor variants.
    """
    quantity, unit, kind, opk = semantic
    op_chain = [p for p in opk.split("|") if p] if opk else []
    prefer = {
        "end": canonical_end(end) or end,
        "quantity": quantity,
        "unit": (unit or None),
        "kind": (kind or None),
        "op_chain": op_chain,
    }
    try:
        return RoleSpecCls(role=role, prefer=prefer)
    except TypeError:
        return RoleSpecCls(role=role)

