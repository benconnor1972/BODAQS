"""Chart-oriented query helpers for the BODAQS Library API adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from bodaqs_analysis.artifacts import ArtifactStore, list_event_types, list_metric_event_types

from .errors import InvalidRequestError, LibraryApiError, SessionNotFoundError, TimeseriesUnavailableError
from .ids import make_session_ref_id
from .timeseries import (
    _numeric_values,
    _optional_text,
    _parse_session_ref,
    _parquet_columns,
    _read_json_object,
    _resolve_column_request,
    _resolve_selector_request,
    _resolve_time_column,
    _signal_payload,
)


SIGNAL_QUERY_SCHEMA = "bodaqs.signal_query"
EVENT_QUERY_SCHEMA = "bodaqs.events_query"
METRIC_QUERY_SCHEMA = "bodaqs.metrics_query"
QUERY_VERSION = 1


def query_signals(
    library_root: str | Path,
    request: Mapping[str, Any],
    *,
    library_id: str | None = None,
) -> dict[str, Any]:
    """Return raw, distribution-correct samples for selected session signals."""

    if not isinstance(request, Mapping):
        raise InvalidRequestError("Signal query request must be an object.")

    signal_requests = _parse_signal_requests(request.get("signals"))
    sessions = _parse_session_refs(request.get("sessions"), field_name="sessions")
    store = ArtifactStore(Path(library_root))

    response_sessions: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for session_ref in sessions:
        _validate_library_id(library_id, session_ref)
        session_key = session_ref["session_key"]
        run_id = session_ref["run_id"]
        session_id = session_ref["session_id"]
        _require_session_dir(store, run_id=run_id, session_id=session_id, session_key=session_key)

        meta = _read_json_object(store.path_session_meta(run_id, session_id))
        df_path = store.path_session_df(run_id, session_id)
        if not df_path.exists():
            raise TimeseriesUnavailableError(
                "Session dataframe was not found.",
                details={"run_id": run_id, "session_id": session_id, "path": str(df_path)},
            )
        available_columns = _parquet_columns(df_path)
        time_column = _optional_time_column(meta, available_columns)
        resolved = []
        for index, item in enumerate(signal_requests):
            role = _optional_text(item.get("role")) or _optional_text(item.get("signal_role")) or f"signal_{index + 1}"
            try:
                spec = _resolve_signal_request(item, meta=meta, available_columns=available_columns)
            except LibraryApiError as exc:
                warnings.append(
                    {
                        "session_key": session_key,
                        "role": role,
                        "code": exc.code,
                        "message": exc.message,
                        "details": exc.details,
                    }
                )
                continue
            resolved.append((role, spec))

        read_columns = [spec["column"] for _role, spec in resolved]
        if time_column:
            read_columns.insert(0, time_column)
        read_columns = list(dict.fromkeys(read_columns))

        if read_columns:
            try:
                df = pd.read_parquet(df_path, columns=read_columns)
            except Exception as exc:
                raise TimeseriesUnavailableError(
                    "Session dataframe could not be read.",
                    details={"path": str(df_path), "error": f"{type(exc).__name__}: {exc}"},
                ) from exc
        else:
            df = pd.DataFrame()

        response_sessions.append(
            {
                "session": _response_session(session_ref, library_id=library_id),
                "time": (
                    {
                        "column": time_column,
                        "unit": "s",
                        "values": _numeric_values(df[time_column]),
                    }
                    if time_column and time_column in df.columns
                    else None
                ),
                "sampling": {
                    "mode": "raw",
                    "source_points": int(len(df)),
                    "returned_points": int(len(df)),
                    "distribution_correct": True,
                },
                "signals": [
                    {
                        "role": role,
                        **_signal_payload(spec),
                        "values": _numeric_values(df[spec["column"]]) if spec["column"] in df.columns else [],
                    }
                    for role, spec in resolved
                ],
            }
        )

    return {
        "schema": SIGNAL_QUERY_SCHEMA,
        "version": QUERY_VERSION,
        "encoding": "json_arrays",
        "sessions": response_sessions,
        "warnings": warnings,
    }


def query_events(
    library_root: str | Path,
    request: Mapping[str, Any],
    *,
    library_id: str | None = None,
) -> dict[str, Any]:
    """Return event rows for selected sessions."""

    return _query_table_rows(
        library_root,
        request,
        library_id=library_id,
        schema=EVENT_QUERY_SCHEMA,
        row_kind="event",
        list_sets=list_event_types,
        path_for_set=lambda store, run_id, session_id, set_id: store.path_events_df(run_id, session_id, set_id),
        set_id_key="event_set_id",
    )


def query_metrics(
    library_root: str | Path,
    request: Mapping[str, Any],
    *,
    library_id: str | None = None,
) -> dict[str, Any]:
    """Return metric rows for selected sessions."""

    return _query_table_rows(
        library_root,
        request,
        library_id=library_id,
        schema=METRIC_QUERY_SCHEMA,
        row_kind="metric",
        list_sets=list_metric_event_types,
        path_for_set=lambda store, run_id, session_id, set_id: store.path_metrics_df(run_id, session_id, set_id),
        set_id_key="metric_set_id",
    )


def _query_table_rows(
    library_root: str | Path,
    request: Mapping[str, Any],
    *,
    library_id: str | None,
    schema: str,
    row_kind: str,
    list_sets: Any,
    path_for_set: Any,
    set_id_key: str,
) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise InvalidRequestError(f"{row_kind.title()} query request must be an object.")

    sessions = _parse_session_refs(request.get("sessions"), field_name="sessions")
    requested_sets = _optional_text_set(request.get("event_types") or request.get("schema_ids") or request.get("sets"))
    store = ArtifactStore(Path(library_root))
    rows: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for session_ref in sessions:
        _validate_library_id(library_id, session_ref)
        session_key = session_ref["session_key"]
        run_id = session_ref["run_id"]
        session_id = session_ref["session_id"]
        _require_session_dir(store, run_id=run_id, session_id=session_id, session_key=session_key)
        for set_id in list_sets(store, run_id, session_id):
            if requested_sets and str(set_id) not in requested_sets:
                continue
            path = path_for_set(store, run_id, session_id, set_id)
            try:
                df = pd.read_parquet(path)
            except Exception as exc:
                warnings.append(
                    {
                        "session_key": session_key,
                        set_id_key: str(set_id),
                        "message": f"{type(exc).__name__}: {exc}",
                    }
                )
                continue
            for row_index, row in df.reset_index(drop=True).iterrows():
                fields = _row_fields(row)
                event_type = _first_text(fields.get("schema_id"), fields.get("event_type"), fields.get("event_name"), set_id)
                signal_role = _signal_role_from_fields(fields)
                rows.append(
                    {
                        "session": _response_session(session_ref, library_id=library_id),
                        set_id_key: str(set_id),
                        "row_index": int(row_index),
                        "event_type": event_type,
                        "signal_role": signal_role,
                        "fields": fields,
                    }
                )

    return {
        "schema": schema,
        "version": QUERY_VERSION,
        "row_kind": row_kind,
        "row_count": len(rows),
        "rows": rows,
        "warnings": warnings,
    }


def _parse_signal_requests(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not value:
        raise InvalidRequestError("Signal query request must include a non-empty signals list.")
    out: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise InvalidRequestError("Each signal query item must be an object.", details={"index": index})
        out.append(item)
    return out


def _resolve_signal_request(
    item: Mapping[str, Any],
    *,
    meta: Mapping[str, Any],
    available_columns: Sequence[str],
) -> dict[str, Any]:
    if item.get("column") is not None:
        return _resolve_column_request(item.get("column"), meta=meta, available_columns=available_columns)
    if item.get("selector") is not None:
        return _resolve_selector_request(item.get("selector"), meta=meta, available_columns=available_columns)
    raise InvalidRequestError("Requested signal must include column or selector.")


def _parse_session_refs(value: Any, *, field_name: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise InvalidRequestError(f"{field_name} must be a non-empty list.")
    return [_parse_session_ref(item) for item in value]


def _validate_library_id(library_id: str | None, session_ref: Mapping[str, str]) -> None:
    request_library_id = session_ref.get("library_id")
    if library_id is not None and request_library_id is not None and request_library_id != library_id:
        raise InvalidRequestError(
            "session.library_id does not match the request library.",
            details={"library_id": library_id, "session_library_id": request_library_id},
        )


def _require_session_dir(store: ArtifactStore, *, run_id: str, session_id: str, session_key: str) -> None:
    if not store.session_dir(run_id, session_id).exists():
        raise SessionNotFoundError(
            "Session was not found.",
            details={"run_id": run_id, "session_id": session_id, "session_key": session_key},
        )


def _optional_time_column(meta: Mapping[str, Any], available_columns: Sequence[str]) -> str | None:
    try:
        return _resolve_time_column(meta, available_columns)[0]
    except LibraryApiError:
        return None


def _response_session(session_ref: Mapping[str, str], *, library_id: str | None) -> dict[str, Any]:
    response = {
        "library_id": library_id or session_ref.get("library_id"),
        "session_key": session_ref["session_key"],
        "run_id": session_ref["run_id"],
        "session_id": session_ref["session_id"],
    }
    if response["library_id"] is not None:
        response["session_ref_id"] = make_session_ref_id(str(response["library_id"]), session_ref["session_key"])
    return response


def _optional_text_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value.strip()} if value.strip() else set()
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return {str(item).strip() for item in value if str(item).strip()}
    raise InvalidRequestError("event_types/schema_ids/sets must be a string list when provided.")


def _row_fields(row: pd.Series) -> dict[str, Any]:
    return {str(key): _json_value(value) for key, value in row.items()}


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    return value


def _signal_role_from_fields(fields: Mapping[str, Any]) -> str | None:
    for key in ("end", "signal_role"):
        value = _first_text(fields.get(key))
        if value:
            lowered = value.lower()
            if lowered in {"front", "rear"}:
                return lowered
    haystack = " ".join(
        str(fields.get(key) or "")
        for key in ("signal", "signal_col", "signals", "event_name", "schema_id", "event_type")
    ).lower()
    if "front" in haystack:
        return "front"
    if "rear" in haystack:
        return "rear"
    return None


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is not None and not isinstance(value, (dict, list, tuple)):
            text = str(value).strip()
            if text:
                return text
    return ""

