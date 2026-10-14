"""Compact library-wide signal discovery derived from session catalogs."""

from __future__ import annotations

from typing import Any, Mapping

from .cache import stable_cache_digest


LIBRARY_SIGNAL_CATALOG_SCHEMA = "bodaqs.library_signal_catalog"
LIBRARY_SIGNAL_CATALOG_VERSION = 1
_METADATA_FIELDS = (
    "stream_kind", "time_column", "end", "domain", "quantity",
    "processing_role", "inspection_visibility", "analysis_variant", "kind",
    "sensor", "component", "coordinate_frame", "vector_group",
    "motion_source_id", "origin",
)


def build_library_signal_catalog(catalog: Mapping[str, Any]) -> dict[str, Any]:
    """Count distinct sessions per concrete stream/column/unit reference.

    Only registry/catalog evidence is used: no sample reads, semantic resolution,
    or quality inference. Missing metadata remains missing rather than guessed.
    """
    sessions: set[str] = set()
    sessions_with_signals: set[str] = set()
    entries: dict[tuple[str, str, str | None], dict[str, Any]] = {}
    for row in catalog.get("rows") or []:
        if not isinstance(row, Mapping):
            continue
        session_key = str(row["session_key"])
        sessions.add(session_key)
        for signal in row.get("available_signals") or []:
            if not isinstance(signal, Mapping):
                continue
            column = _text(signal.get("column"))
            if not column:
                continue
            stream = _text(signal.get("stream_name")) or "primary"
            unit = _text(signal.get("unit"))
            identity = (stream, column, unit)
            entry = entries.setdefault(identity, {
                "sessions": set(), "display_names": set(), "signal_ids": set(),
                "variants": {},
            })
            entry["sessions"].add(session_key)
            sessions_with_signals.add(session_key)
            entry["display_names"].add(_text(signal.get("display_name")) or column)
            signal_id = _text(signal.get("signal_id"))
            if signal_id:
                entry["signal_ids"].add(signal_id)
            metadata = {
                key: signal[key] for key in _METADATA_FIELDS
                if signal.get(key) is not None
            }
            variant_key = stable_cache_digest(metadata)
            variant = entry["variants"].setdefault(variant_key, {
                "metadata": metadata, "sessions": set(),
            })
            variant["sessions"].add(session_key)

    total = len(sessions)
    signals = []
    for (stream, column, unit), entry in sorted(
        entries.items(), key=lambda item: (item[0][0], item[0][1], item[0][2] or ""),
    ):
        display_names = sorted(entry["display_names"], key=lambda name: (name.casefold(), name))
        variants = [
            {
                "metadata": variant["metadata"],
                "session_count": len(variant["sessions"]),
                "session_fraction": len(variant["sessions"]) / total,
            }
            for _, variant in sorted(entry["variants"].items())
        ]
        common = dict(variants[0]["metadata"])
        for variant in variants[1:]:
            common = {
                key: value for key, value in common.items()
                if key in variant["metadata"] and variant["metadata"][key] == value
            }
        signals.append({
            "entry_id": "signal-" + stable_cache_digest([stream, column, unit])[:20],
            "stream_name": stream,
            "column": column,
            "unit": unit,
            "display_name": display_names[0],
            "display_names": display_names,
            "signal_ids": sorted(entry["signal_ids"]),
            "metadata": common,
            "metadata_variants": variants,
            "session_count": len(entry["sessions"]),
            "session_fraction": len(entry["sessions"]) / total,
        })
    return {
        "schema": LIBRARY_SIGNAL_CATALOG_SCHEMA,
        "version": LIBRARY_SIGNAL_CATALOG_VERSION,
        "library_id": catalog.get("library_id"),
        "scope": "whole_library",
        "availability_basis": "catalog_presence",
        "catalog_generated_at": catalog.get("generated_at"),
        "session_count": total,
        "sessions_with_catalogued_signals": len(sessions_with_signals),
        "signal_count": len(signals),
        "signals": signals,
    }


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    return None
