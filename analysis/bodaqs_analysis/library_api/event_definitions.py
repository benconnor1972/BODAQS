"""Event-definition discovery for Workbench analysis views."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd

from bodaqs_analysis.artifacts import ArtifactStore, list_event_types
from bodaqs_analysis.schema import parse_event_schema

from .errors import InvalidRequestError
from .timeseries import _parse_session_ref


EVENT_DEFINITIONS_SCHEMA = "bodaqs.event_definitions"
EVENT_DEFINITIONS_VERSION = 1


def query_event_definitions(
    request: Mapping[str, Any],
    *,
    resolve_library_root: Callable[[str], Path],
) -> dict[str, Any]:
    """Describe logical event definitions available in explicit sessions."""

    if not isinstance(request, Mapping):
        raise InvalidRequestError("Event-definition query must be an object.")
    raw_sessions = request.get("sessions")
    if not isinstance(raw_sessions, list) or not raw_sessions:
        raise InvalidRequestError("sessions must be a non-empty list.")

    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    warnings: list[dict[str, Any]] = []
    for raw_session in raw_sessions:
        session = _parse_session_ref(raw_session)
        library_id = str(session.get("library_id") or "").strip()
        if not library_id:
            raise InvalidRequestError("Each session must include library_id.")
        store = ArtifactStore(resolve_library_root(library_id))
        run_id = session["run_id"]
        session_id = session["session_id"]
        session_ref_id = str(session.get("session_ref_id") or f"{library_id}|||{session['session_key']}")

        for event_set_id in list_event_types(store, run_id, session_id):
            event_path = store.path_events_df(run_id, session_id, event_set_id)
            schema_path = store.path_events_schema(run_id, session_id, event_set_id)
            try:
                event_df = pd.read_parquet(event_path)
            except Exception as exc:
                warnings.append(_warning(session, event_set_id, "event_table_unreadable", exc))
                continue
            if event_df.empty:
                continue

            schema: Mapping[str, Any] | None = None
            schema_digest = ""
            if schema_path.exists():
                try:
                    parsed, meta = parse_event_schema(schema_path, return_meta=True)
                    schema = parsed
                    schema_digest = f"sha256:{meta['sha256']}"
                except Exception as exc:
                    warnings.append(_warning(session, event_set_id, "event_schema_unreadable", exc))

            for schema_id, rows in _rows_by_schema_id(event_df, event_set_id):
                schema_version = _first_text(rows.get("schema_version"))
                definition_key = (schema_id, schema_version, schema_digest or f"set:{event_set_id}")
                definition = groups.get(definition_key)
                block = _event_block(schema, schema_id)
                if definition is None:
                    definition = _definition_payload(
                        schema_id=schema_id,
                        schema_version=schema_version,
                        schema_digest=schema_digest,
                        event_set_id=event_set_id,
                        rows=rows,
                        block=block,
                    )
                    groups[definition_key] = definition
                definition["event_count"] += int(len(rows))
                definition["session_ref_ids"].add(session_ref_id)
                definition["event_set_ids"].add(str(event_set_id))
                definition["available_ends"].update(_event_ends(rows))
                definition["metric_fields"].update(
                    _metric_fields(store, run_id=run_id, session_id=session_id, event_set_id=event_set_id)
                )

    definitions = []
    for definition in groups.values():
        definition["session_ref_ids"] = sorted(definition["session_ref_ids"])
        definition["session_count"] = len(definition["session_ref_ids"])
        definition["event_set_ids"] = sorted(definition["event_set_ids"])
        definition["available_ends"] = sorted(definition["available_ends"])
        definition["metric_fields"] = [
            {"column": column, "display_name": _humanize_metric(column), "unit": ""}
            for column in sorted(definition["metric_fields"])
        ]
        definitions.append(definition)
    definitions.sort(key=lambda item: (str(item["display_name"]).lower(), str(item["definition_key"])))
    return {
        "schema": EVENT_DEFINITIONS_SCHEMA,
        "version": EVENT_DEFINITIONS_VERSION,
        "definitions": definitions,
        "warnings": warnings,
    }


def _rows_by_schema_id(df: pd.DataFrame, event_set_id: str) -> list[tuple[str, pd.DataFrame]]:
    if "schema_id" not in df.columns:
        return [(str(event_set_id), df)]
    out = []
    for value, rows in df.groupby("schema_id", dropna=False):
        schema_id = str(value).strip() if pd.notna(value) else str(event_set_id)
        out.append((schema_id or str(event_set_id), rows))
    return out


def _definition_payload(
    *,
    schema_id: str,
    schema_version: str,
    schema_digest: str,
    event_set_id: str,
    rows: pd.DataFrame,
    block: Mapping[str, Any] | None,
) -> dict[str, Any]:
    label = ""
    if block:
        label = str(block.get("label") or block.get("event_name") or block.get("name") or "").strip()
    if not label:
        label = _first_text(rows.get("event_name")) or schema_id.replace("_", " ")

    trigger = block.get("trigger") if isinstance(block, Mapping) else None
    primary_id = str(trigger.get("id") or "trigger").strip() if isinstance(trigger, Mapping) else "trigger"
    secondary = block.get("secondary_triggers") if isinstance(block, Mapping) else None
    secondary_ids = [
        {"id": str(item.get("id")).strip()}
        for item in secondary or []
        if isinstance(item, Mapping) and str(item.get("id") or "").strip()
    ]
    segment_defaults = block.get("segment_defaults") if isinstance(block, Mapping) else None
    segment_defaults = segment_defaults if isinstance(segment_defaults, Mapping) else {}
    window = segment_defaults.get("window") if isinstance(segment_defaults.get("window"), Mapping) else {}
    roles = segment_defaults.get("roles") if isinstance(segment_defaults.get("roles"), list) else []
    schema_tags = block.get("tags") if isinstance(block, Mapping) and isinstance(block.get("tags"), list) else []
    key_material = schema_digest or f"set:{event_set_id}"
    return {
        "definition_key": f"{key_material}:{schema_id}",
        "schema_id": schema_id,
        "schema_version": schema_version,
        "schema_digest": schema_digest,
        "display_name": label,
        "schema_tags": [str(tag).strip() for tag in schema_tags if str(tag).strip()],
        "event_set_ids": {str(event_set_id)},
        "available_ends": set(),
        "primary_trigger": {"id": primary_id},
        "secondary_triggers": secondary_ids,
        "default_window": {
            "pre_s": _finite_number(window.get("pre_s"), 0.8),
            "post_s": _finite_number(window.get("post_s"), 0.8),
            "anchor": str(segment_defaults.get("anchor") or "trigger_time_s"),
        },
        "default_roles": [
            {"role": str(item.get("role") or "").strip(), "selector": dict(item.get("prefer") or {})}
            for item in roles
            if isinstance(item, Mapping) and str(item.get("role") or "").strip()
        ],
        "metric_fields": set(),
        "event_count": 0,
        "session_ref_ids": set(),
        "session_count": 0,
    }


def _event_block(schema: Mapping[str, Any] | None, schema_id: str) -> Mapping[str, Any] | None:
    events = schema.get("events") if isinstance(schema, Mapping) else None
    for item in events or []:
        if isinstance(item, Mapping) and str(item.get("id") or "") == schema_id:
            return item
    return None


def _event_ends(rows: pd.DataFrame) -> set[str]:
    ends: set[str] = set()
    if "end" in rows.columns:
        ends.update(str(value).strip().lower() for value in rows["end"].dropna() if str(value).strip())
    if "meta" in rows.columns:
        for value in rows["meta"]:
            if isinstance(value, Mapping):
                end = str(value.get("event_context") or "").strip().lower()
                if end:
                    ends.add(end)
    if not ends and "signal_col" in rows.columns:
        for value in rows["signal_col"].dropna().astype(str):
            lowered = value.lower()
            if "front" in lowered:
                ends.add("front")
            if "rear" in lowered:
                ends.add("rear")
    return ends


def _metric_fields(store: ArtifactStore, *, run_id: str, session_id: str, event_set_id: str) -> set[str]:
    path = store.path_metrics_df(run_id, session_id, event_set_id)
    if not path.exists():
        return set()
    try:
        df = pd.read_parquet(path)
    except Exception:
        return set()
    out: set[str] = set()
    for column in df.columns:
        name = str(column)
        if not name.startswith("m_"):
            continue
        series = pd.to_numeric(df[column], errors="coerce")
        if np.isfinite(series.to_numpy(dtype=float)).any():
            out.add(name)
    return out


def _first_text(series: Any) -> str:
    if isinstance(series, pd.Series):
        for value in series:
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _finite_number(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if np.isfinite(number) else float(default)


def _humanize_metric(column: str) -> str:
    return column.removeprefix("m_").replace("_", " ").strip().title()


def _warning(session: Mapping[str, Any], event_set_id: str, code: str, exc: Exception) -> dict[str, Any]:
    return {
        "session_ref_id": session.get("session_ref_id"),
        "session_key": session.get("session_key"),
        "event_set_id": str(event_set_id),
        "code": code,
        "message": f"{type(exc).__name__}: {exc}",
    }
