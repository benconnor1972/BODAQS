"""Schema-aware Event segment queries for browser consumers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from bodaqs_analysis.artifacts import ArtifactStore
from bodaqs_analysis.schema import parse_event_schema
from bodaqs_analysis.segment import RoleSpec, SegmentRequest, WindowSpec, extract_segments

from .errors import InvalidRequestError, SessionNotFoundError, TimeseriesUnavailableError
from .ids import make_session_ref_id
from .timeseries import _parse_session_ref, _read_json_object


EVENT_SEGMENTS_SCHEMA = "bodaqs.event_segments"
EVENT_SEGMENTS_VERSION = 1
MAX_EVENT_SEGMENTS = 12


def query_event_segments(
    library_root: str | Path,
    request: Mapping[str, Any],
    *,
    library_id: str,
) -> dict[str, Any]:
    """Return event-relative signal segments resolved through the frozen schema."""

    if not isinstance(request, Mapping):
        raise InvalidRequestError("Event-segment query must be an object.")
    raw_events = request.get("events")
    if not isinstance(raw_events, list) or not raw_events:
        raise InvalidRequestError("events must be a non-empty list.")
    if len(raw_events) > MAX_EVENT_SEGMENTS:
        raise InvalidRequestError(
            f"Event-segment queries support at most {MAX_EVENT_SEGMENTS} events.",
            details={"event_count": len(raw_events), "maximum": MAX_EVENT_SEGMENTS},
        )

    store = ArtifactStore(Path(library_root))
    segments: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for index, raw_event in enumerate(raw_events):
        try:
            segments.append(
                _query_one_event(
                    store,
                    raw_event,
                    request=request,
                    library_id=library_id,
                )
            )
        except Exception as exc:
            if isinstance(exc, (InvalidRequestError, SessionNotFoundError, TimeseriesUnavailableError)) and len(raw_events) == 1:
                raise
            warnings.append(
                {
                    "event_index": index,
                    "event_id": raw_event.get("event_id") if isinstance(raw_event, Mapping) else None,
                    "code": getattr(exc, "code", "event_segment_failed"),
                    "message": getattr(exc, "message", f"{type(exc).__name__}: {exc}"),
                }
            )

    return {
        "schema": EVENT_SEGMENTS_SCHEMA,
        "version": EVENT_SEGMENTS_VERSION,
        "segments": segments,
        "warnings": warnings,
    }


def _query_one_event(
    store: ArtifactStore,
    raw_event: Any,
    *,
    request: Mapping[str, Any],
    library_id: str,
) -> dict[str, Any]:
    if not isinstance(raw_event, Mapping):
        raise InvalidRequestError("Each event reference must be an object.")
    session_value = raw_event.get("session") if isinstance(raw_event.get("session"), Mapping) else raw_event
    session = _parse_session_ref(session_value)
    requested_library = str(session.get("library_id") or library_id)
    if requested_library != library_id:
        raise InvalidRequestError("Event session library_id does not match the request library.")
    run_id = session["run_id"]
    session_id = session["session_id"]
    if not store.session_dir(run_id, session_id).exists():
        raise SessionNotFoundError("Event session was not found.", details={"session_key": session["session_key"]})

    event_set_id = _required_text(raw_event.get("event_set_id") or raw_event.get("set_id"), "event_set_id")
    event_id = _required_text(raw_event.get("event_id"), "event_id")
    event_path = store.path_events_df(run_id, session_id, event_set_id)
    if not event_path.exists():
        raise TimeseriesUnavailableError("Event table was not found.", details={"event_set_id": event_set_id})
    try:
        events_df = pd.read_parquet(event_path)
    except Exception as exc:
        raise TimeseriesUnavailableError(
            "Event table could not be read.", details={"path": str(event_path), "error": f"{type(exc).__name__}: {exc}"}
        ) from exc
    if "event_id" not in events_df.columns:
        raise TimeseriesUnavailableError("Event table has no event_id column.", details={"path": str(event_path)})
    selected = events_df[events_df["event_id"].astype(str) == event_id].reset_index(drop=True)
    if len(selected) != 1:
        raise TimeseriesUnavailableError(
            "Event reference did not resolve to exactly one Event row.",
            details={"event_id": event_id, "matches": len(selected)},
        )
    row = selected.iloc[0]

    schema_path = store.path_events_schema(run_id, session_id, event_set_id)
    schema: Mapping[str, Any] | None = None
    schema_digest = ""
    if schema_path.exists():
        parsed, schema_meta = parse_event_schema(schema_path, return_meta=True)
        schema = parsed
        schema_digest = f"sha256:{schema_meta['sha256']}"

    df_path = store.path_session_df(run_id, session_id)
    meta_path = store.path_session_meta(run_id, session_id)
    if not df_path.exists() or not meta_path.exists():
        raise TimeseriesUnavailableError("Processed session dataframe or metadata was not found.")
    try:
        session_df = pd.read_parquet(df_path)
    except Exception as exc:
        raise TimeseriesUnavailableError(
            "Processed session dataframe could not be read.",
            details={"path": str(df_path), "error": f"{type(exc).__name__}: {exc}"},
        ) from exc
    meta = _read_json_object(meta_path)

    window = _window_spec(request.get("window"))
    schema_id = str(row.get("schema_id") or event_set_id)
    roles = _role_specs(request.get("roles"), schema=schema, schema_id=schema_id)
    if roles is None and not _default_role_selectors(schema, schema_id):
        roles = [_fallback_primary_role(row, meta)]
    segment_request = SegmentRequest(
        schema_id=schema_id,
        window=window,
        roles=roles,
    )
    try:
        bundle = extract_segments(session_df, selected, meta=meta, schema=schema, request=segment_request)
    except Exception as exc:
        raise TimeseriesUnavailableError(
            "Event segment could not be extracted.", details={"event_id": event_id, "error": f"{type(exc).__name__}: {exc}"}
        ) from exc

    segment_rows = bundle.get("segments")
    if not isinstance(segment_rows, pd.DataFrame) or segment_rows.empty or not bool(segment_rows.iloc[0].get("valid", False)):
        reason = segment_rows.iloc[0].get("reason") if isinstance(segment_rows, pd.DataFrame) and not segment_rows.empty else "unknown"
        raise TimeseriesUnavailableError("Event segment is invalid.", details={"event_id": event_id, "reason": reason})

    data = bundle.get("data") if isinstance(bundle.get("data"), Mapping) else {}
    time_values = _first_array(data.get("t_rel_s"))
    signals = _signal_payloads(data, bundle.get("spec"), meta, segment_rows.iloc[0].get("role_to_col"))
    metrics = _metrics_for_event(store, run_id=run_id, session_id=session_id, event_set_id=event_set_id, event_id=event_id)
    trigger_time = _finite_or_none(row.get("trigger_time_s"))
    return {
        "event_ref": {
            "library_id": library_id,
            "run_id": run_id,
            "session_id": session_id,
            "session_key": session["session_key"],
            "session_ref_id": make_session_ref_id(library_id, session["session_key"]),
            "event_set_id": event_set_id,
            "event_id": event_id,
            "schema_id": str(row.get("schema_id") or event_set_id),
            "schema_version": str(row.get("schema_version") or ""),
            "schema_digest": schema_digest,
            "params_hash": str(row.get("params_hash") or ""),
            "trigger_time_s": trigger_time,
        },
        "window": {
            "returned_start_rel_s": time_values[0] if time_values else None,
            "returned_end_rel_s": time_values[-1] if time_values else None,
        },
        "time_rel_s": time_values,
        "signals": signals,
        "triggers": _triggers(row, schema=schema, schema_id=str(row.get("schema_id") or event_set_id)),
        "metrics": metrics,
        "qc": {"flags": _json_value(row.get("qc_flags")), "score": _json_value(row.get("score"))},
        "warnings": [],
    }


def _window_spec(value: Any) -> WindowSpec | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise InvalidRequestError("window must be an object.")
    try:
        pre_s = float(value.get("pre_s", 0.0))
        post_s = float(value.get("post_s", 0.0))
    except (TypeError, ValueError) as exc:
        raise InvalidRequestError("window.pre_s and window.post_s must be numbers.") from exc
    if not np.isfinite(pre_s) or not np.isfinite(post_s) or pre_s < 0 or post_s < 0:
        raise InvalidRequestError("window.pre_s and window.post_s must be finite and non-negative.")
    return WindowSpec(mode="time", pre_s=pre_s, post_s=post_s)


def _role_specs(value: Any, *, schema: Mapping[str, Any] | None, schema_id: str) -> list[RoleSpec] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise InvalidRequestError("roles must be a non-empty list when supplied.")
    defaults = _default_role_selectors(schema, schema_id)
    out: list[RoleSpec] = []
    for item in value:
        if isinstance(item, str):
            role = item.strip()
            selector = defaults.get(role)
        elif isinstance(item, Mapping):
            role = str(item.get("role") or "").strip()
            selector_value = item.get("selector") or item.get("prefer")
            selector = dict(selector_value) if isinstance(selector_value, Mapping) else defaults.get(role)
        else:
            raise InvalidRequestError("Each role must be a role name or object.")
        if not role or not selector:
            raise InvalidRequestError("Requested role is missing a schema/default semantic selector.", details={"role": role})
        out.append(RoleSpec(role=role, prefer=selector))
    return out


def _default_role_selectors(schema: Mapping[str, Any] | None, schema_id: str) -> dict[str, dict[str, Any]]:
    block = _event_block(schema, schema_id)
    segment = block.get("segment_defaults") if isinstance(block, Mapping) else None
    roles = segment.get("roles") if isinstance(segment, Mapping) else None
    return {
        str(item.get("role")): dict(item.get("prefer"))
        for item in roles or []
        if isinstance(item, Mapping) and str(item.get("role") or "").strip() and isinstance(item.get("prefer"), Mapping)
    }


def _fallback_primary_role(row: pd.Series, meta: Mapping[str, Any]) -> RoleSpec:
    """Resolve a useful single trace for historical Events without segment defaults."""

    column = str(row.get("signal_col") or "").strip()
    registry = meta.get("signals") if isinstance(meta.get("signals"), Mapping) else {}
    info = registry.get(column) if column else None
    info = info if isinstance(info, Mapping) else {}
    quantity = str(info.get("quantity") or "").strip()
    if not column or not quantity:
        raise TimeseriesUnavailableError(
            "Historical Event has no schema roles and its primary signal cannot be resolved.",
            details={"signal_col": column or None},
        )
    selector = {key: info[key] for key in ("end", "domain", "quantity", "unit", "processing_role", "kind") if info.get(key) not in (None, "")}
    return RoleSpec(role="primary", prefer=selector)


def _signal_payloads(
    data: Mapping[str, Any],
    spec_value: Any,
    meta: Mapping[str, Any],
    resolved_roles: Any,
) -> list[dict[str, Any]]:
    spec = spec_value if isinstance(spec_value, Mapping) else {}
    roles = spec.get("roles") if isinstance(spec.get("roles"), (list, tuple)) else []
    role_to_col_by_event = resolved_roles if isinstance(resolved_roles, Mapping) else {}
    signal_registry = meta.get("signals") if isinstance(meta.get("signals"), Mapping) else {}
    out = []
    for role_spec in roles:
        role = getattr(role_spec, "role", None)
        if not isinstance(role, str) or role not in data:
            continue
        values = _first_array(data.get(role))
        column = str(role_to_col_by_event.get(role) or "")
        info = signal_registry.get(column) if column else None
        info = info if isinstance(info, Mapping) else {}
        out.append(
            {
                "role": role,
                "column": column,
                "display_name": str(info.get("display_name") or role.replace("_", " ").title()),
                "end": str(info.get("end") or ""),
                "domain": str(info.get("domain") or ""),
                "quantity": str(info.get("quantity") or getattr(role_spec, "prefer", {}).get("quantity") or ""),
                "unit": str(info.get("unit") or getattr(role_spec, "prefer", {}).get("unit") or ""),
                "values": values,
            }
        )
    return out


def _triggers(row: pd.Series, *, schema: Mapping[str, Any] | None, schema_id: str) -> list[dict[str, Any]]:
    primary_time = _finite_or_none(row.get("trigger_time_s"))
    out = [{"id": "trigger", "kind": "primary", "time_rel_s": 0.0}]
    block = _event_block(schema, schema_id)
    if isinstance(block, Mapping):
        trigger = block.get("trigger")
        if isinstance(trigger, Mapping) and str(trigger.get("id") or "").strip():
            out[0]["id"] = str(trigger.get("id")).strip()
        for item in block.get("secondary_triggers") or []:
            if not isinstance(item, Mapping):
                continue
            trigger_id = str(item.get("id") or "").strip()
            value = _finite_or_none(row.get(f"{trigger_id}_time_s")) if trigger_id else None
            if trigger_id and value is not None and primary_time is not None:
                out.append({"id": trigger_id, "kind": "secondary", "time_rel_s": value - primary_time})
    meta = row.get("meta")
    secondary = meta.get("secondary_triggers") if isinstance(meta, Mapping) else None
    if isinstance(secondary, Mapping) and primary_time is not None:
        known = {str(item["id"]) for item in out}
        for trigger_id, payload in secondary.items():
            if str(trigger_id) in known or not isinstance(payload, Mapping):
                continue
            value = _finite_or_none(payload.get("trigger_time_s"))
            if value is not None:
                out.append({"id": str(trigger_id), "kind": "secondary", "time_rel_s": value - primary_time})
    return out


def _event_block(schema: Mapping[str, Any] | None, schema_id: str) -> Mapping[str, Any] | None:
    events = schema.get("events") if isinstance(schema, Mapping) else None
    for item in events or []:
        if isinstance(item, Mapping) and str(item.get("id") or "") == schema_id:
            return item
    return None


def _metrics_for_event(store: ArtifactStore, *, run_id: str, session_id: str, event_set_id: str, event_id: str) -> dict[str, Any]:
    path = store.path_metrics_df(run_id, session_id, event_set_id)
    if not path.exists():
        return {}
    try:
        df = pd.read_parquet(path)
    except Exception:
        return {}
    if "event_id" not in df.columns:
        return {}
    rows = df[df["event_id"].astype(str) == event_id]
    if rows.empty:
        return {}
    row = rows.iloc[0]
    return {str(column): _json_value(row[column]) for column in df.columns if str(column).startswith("m_") and _json_value(row[column]) is not None}


def _first_array(value: Any) -> list[float | None]:
    if value is None:
        return []
    array = np.asarray(value)
    if array.ndim > 1:
        array = array[0]
    return [_json_value(item) for item in array.tolist()]


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, float):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return str(value)


def _finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise InvalidRequestError(f"{field_name} is required.")
    return text
