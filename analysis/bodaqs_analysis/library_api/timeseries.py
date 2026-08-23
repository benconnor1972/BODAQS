"""Time-series window helpers for the BODAQS Library API adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from bodaqs_analysis.artifacts import ArtifactStore, list_event_types

from .catalog import _signal_display_name, _signal_id
from .errors import InvalidRequestError, SessionNotFoundError, SignalNotFoundError, TimeseriesUnavailableError
from .ids import make_session_key, make_session_ref_id


TIMESERIES_WINDOW_SCHEMA = "bodaqs.timeseries_window"
TIMESERIES_WINDOW_VERSION = 1
MULTISTREAM_TIMESERIES_WINDOW_SCHEMA = "bodaqs.multistream_timeseries_window"
MULTISTREAM_TIMESERIES_WINDOW_VERSION = 1
DEFAULT_TARGET_POINTS = 2000
WINDOW_BOUNDARY_WARNING_TOLERANCE_S = 0.25


def get_timeseries_window(
    library_root: str | Path,
    request: Mapping[str, Any],
    *,
    library_id: str | None = None,
) -> dict[str, Any]:
    """Return a JSON-serializable, one-session time-series window payload."""

    if not isinstance(request, Mapping):
        raise InvalidRequestError("Time-series window request must be an object.")

    store = ArtifactStore(Path(library_root))
    session_ref = _parse_session_ref(request.get("session"))
    request_library_id = session_ref.get("library_id")
    if library_id is not None and request_library_id is not None and request_library_id != library_id:
        raise InvalidRequestError(
            "session.library_id does not match the request library.",
            details={"library_id": library_id, "session_library_id": request_library_id},
        )
    run_id = session_ref["run_id"]
    session_id = session_ref["session_id"]
    session_key = session_ref["session_key"]

    session_dir = store.session_dir(run_id, session_id)
    if not session_dir.exists():
        raise SessionNotFoundError(
            "Session was not found.",
            details={"run_id": run_id, "session_id": session_id, "session_key": session_key},
        )

    meta = _read_json_object(store.path_session_meta(run_id, session_id))
    df_path = store.path_session_df(run_id, session_id)
    if not df_path.exists():
        raise TimeseriesUnavailableError(
            "Session dataframe was not found.",
            details={"run_id": run_id, "session_id": session_id, "path": str(df_path)},
        )

    available_columns = _parquet_columns(df_path)
    time_column, time_unit = _resolve_time_column(meta, available_columns)
    signal_specs = _resolve_signal_requests(
        request.get("signals"),
        meta=meta,
        available_columns=available_columns,
    )
    include_marks = bool(request.get("include_marks", False))
    mark_column = _resolve_mark_column(meta, available_columns) if include_marks else None

    read_columns = [time_column, *[spec["column"] for spec in signal_specs]]
    if mark_column is not None:
        read_columns.append(mark_column)
    read_columns = list(dict.fromkeys(read_columns))
    try:
        df = pd.read_parquet(df_path, columns=read_columns)
    except Exception as exc:
        raise TimeseriesUnavailableError(
            "Session dataframe could not be read.",
            details={"path": str(df_path), "error": f"{type(exc).__name__}: {exc}"},
        ) from exc

    window_request = _parse_window(request.get("window"))
    target_points = _parse_target_points(request.get("resolution"))
    windowed = _window_dataframe(
        df,
        time_column=time_column,
        requested_start_s=window_request["start_s"],
        requested_end_s=window_request["end_s"],
    )
    if windowed.empty:
        raise TimeseriesUnavailableError(
            "Requested window contains no samples.",
            details={
                "session_key": session_key,
                "requested_start_s": window_request["start_s"],
                "requested_end_s": window_request["end_s"],
            },
        )

    signal_windowed = _rows_with_selected_signal_data(
        windowed,
        signal_columns=[spec["column"] for spec in signal_specs],
    )
    if signal_windowed.empty:
        raise TimeseriesUnavailableError(
            "Requested window contains no finite samples for the selected signals.",
            details={
                "session_key": session_key,
                "requested_start_s": window_request["start_s"],
                "requested_end_s": window_request["end_s"],
            },
        )

    selected, sampling_mode = _downsample_min_max(
        signal_windowed,
        time_column=time_column,
        signal_columns=[spec["column"] for spec in signal_specs],
        target_points=target_points,
    )
    time_values = _numeric_values(selected[time_column])
    warnings = _window_warnings(
        source_df=df,
        returned_df=selected,
        time_column=time_column,
        requested_start_s=window_request["start_s"],
        requested_end_s=window_request["end_s"],
    )

    response_session = {
        "library_id": library_id or request_library_id,
        "session_key": session_key,
        "run_id": run_id,
        "session_id": session_id,
    }
    if response_session["library_id"] is not None:
        response_session["session_ref_id"] = make_session_ref_id(response_session["library_id"], session_key)

    return {
        "schema": TIMESERIES_WINDOW_SCHEMA,
        "version": TIMESERIES_WINDOW_VERSION,
        "encoding": "json_arrays",
        "session": response_session,
        "window": {
            "requested_start_s": window_request["start_s"],
            "requested_end_s": window_request["end_s"],
            "returned_start_s": time_values[0] if time_values else None,
            "returned_end_s": time_values[-1] if time_values else None,
        },
        "sampling": {
            "mode": sampling_mode,
            "source_points": int(len(signal_windowed)),
            "returned_points": int(len(selected)),
            "target_points": int(target_points),
        },
        "time": {
            "column": time_column,
            "unit": time_unit,
            "values": time_values,
        },
        "signals": [
            {
                **_signal_payload(spec),
                "values": _numeric_values(selected[spec["column"]]),
            }
            for spec in signal_specs
        ],
        "events": (
            _event_overlays(
                store,
                run_id=run_id,
                session_id=session_id,
                requested_start_s=window_request["start_s"],
                requested_end_s=window_request["end_s"],
                returned_start_s=time_values[0] if time_values else None,
                returned_end_s=time_values[-1] if time_values else None,
            )
            if bool(request.get("include_events", False))
            else []
        ),
        "marks": _mark_overlays(windowed, time_column=time_column, mark_column=mark_column) if mark_column else [],
        "warnings": warnings,
    }


def get_multistream_timeseries_window(
    library_root: str | Path,
    request: Mapping[str, Any],
    *,
    library_id: str | None = None,
) -> dict[str, Any]:
    """Return independently sampled, stream-scoped time-series groups.

    Unlike :func:`get_timeseries_window`, this endpoint never resamples one
    materialised stream onto another stream's timebase.  Each returned group
    carries its own native timestamps and signals.
    """
    if not isinstance(request, Mapping):
        raise InvalidRequestError("Time-series request must be an object.")

    store = ArtifactStore(Path(library_root))
    session_ref = _parse_session_ref(request.get("session"))
    request_library_id = session_ref.get("library_id")
    if library_id is not None and request_library_id is not None and request_library_id != library_id:
        raise InvalidRequestError(
            "session.library_id does not match the request library.",
            details={"library_id": library_id, "session_library_id": request_library_id},
        )
    run_id = session_ref["run_id"]
    session_id = session_ref["session_id"]
    session_key = session_ref["session_key"]
    session_dir = store.session_dir(run_id, session_id)
    if not session_dir.exists():
        raise SessionNotFoundError(
            "Session was not found.",
            details={"run_id": run_id, "session_id": session_id, "session_key": session_key},
        )
    session_meta = _read_json_object(store.path_session_meta(run_id, session_id))
    grouped_requests = _group_stream_signal_requests(request.get("signals"))
    window_request = _parse_window(request.get("window"))
    target_points = _parse_target_points(request.get("resolution"))

    groups: list[dict[str, Any]] = []
    for stream_name, stream_requests in grouped_requests.items():
        stream_meta, dataframe_path, stream_kind = _stream_source(
            store,
            run_id=run_id,
            session_id=session_id,
            session_meta=session_meta,
            stream_name=stream_name,
        )
        groups.append(
            _stream_window_group(
                dataframe_path=dataframe_path,
                metadata=stream_meta,
                stream_name=stream_name,
                stream_kind=stream_kind,
                signal_requests=stream_requests,
                window_request=window_request,
                target_points=target_points,
            )
        )

    response_session = {
        "library_id": library_id or request_library_id,
        "session_key": session_key,
        "run_id": run_id,
        "session_id": session_id,
    }
    if response_session["library_id"] is not None:
        response_session["session_ref_id"] = make_session_ref_id(response_session["library_id"], session_key)
    returned_times = [
        value
        for group in groups
        for value in (group["time"].get("values") or [])
        if isinstance(value, (int, float)) and np.isfinite(value)
    ]
    primary_meta, primary_path, _ = _stream_source(
        store,
        run_id=run_id,
        session_id=session_id,
        session_meta=session_meta,
        stream_name="primary",
    )
    return {
        "schema": MULTISTREAM_TIMESERIES_WINDOW_SCHEMA,
        "version": MULTISTREAM_TIMESERIES_WINDOW_VERSION,
        "encoding": "json_arrays",
        "session": response_session,
        "window": {
            "requested_start_s": window_request["start_s"],
            "requested_end_s": window_request["end_s"],
            "returned_start_s": min(returned_times) if returned_times else None,
            "returned_end_s": max(returned_times) if returned_times else None,
        },
        "groups": groups,
        "events": (
            _event_overlays(
                store,
                run_id=run_id,
                session_id=session_id,
                requested_start_s=window_request["start_s"],
                requested_end_s=window_request["end_s"],
                returned_start_s=min(returned_times) if returned_times else None,
                returned_end_s=max(returned_times) if returned_times else None,
            )
            if bool(request.get("include_events", False))
            else []
        ),
        "marks": _primary_marks(
            primary_path,
            primary_meta,
            window_request=window_request,
        ) if bool(request.get("include_marks", False)) else [],
        "warnings": [],
    }


def _group_stream_signal_requests(value: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(value, list) or not value:
        raise InvalidRequestError("Time-series request must include at least one signal.")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise InvalidRequestError("Each requested signal must be an object.", details={"index": index})
        stream_name = _optional_text(item.get("stream_name"))
        if stream_name is None:
            raise InvalidRequestError(
                "Multi-stream signal requests must include stream_name.", details={"index": index}
            )
        request_item = {str(key): raw for key, raw in item.items() if str(key) != "stream_name"}
        if request_item.get("column") is None and request_item.get("selector") is None:
            raise InvalidRequestError(
                "Requested signal must include column or selector.", details={"index": index}
            )
        grouped.setdefault(stream_name, []).append(request_item)
    return grouped


def _stream_source(
    store: ArtifactStore,
    *,
    run_id: str,
    session_id: str,
    session_meta: Mapping[str, Any],
    stream_name: str,
) -> tuple[dict[str, Any], Path, str]:
    if stream_name == "primary":
        path = store.path_session_df(run_id, session_id)
        if not path.exists():
            raise TimeseriesUnavailableError("Session dataframe was not found.", details={"path": str(path)})
        return dict(session_meta), path, "primary"
    secondary = session_meta.get("secondary_streams")
    registered = secondary.get(stream_name) if isinstance(secondary, Mapping) else None
    if not isinstance(registered, Mapping):
        raise SignalNotFoundError(
            "Requested stream is not registered for the session.", details={"stream_name": stream_name}
        )
    path = store.path_session_stream_df(run_id, session_id, stream_name)
    if not path.exists():
        raise TimeseriesUnavailableError(
            "Requested stream dataframe was not found.", details={"stream_name": stream_name, "path": str(path)}
        )
    persisted = _read_json_object(store.path_session_stream_meta(run_id, session_id, stream_name))
    metadata = dict(registered)
    metadata.update(persisted)
    return metadata, path, _optional_text(metadata.get("kind")) or "secondary"


def _stream_window_group(
    *,
    dataframe_path: Path,
    metadata: Mapping[str, Any],
    stream_name: str,
    stream_kind: str,
    signal_requests: list[dict[str, Any]],
    window_request: Mapping[str, float | None],
    target_points: int,
) -> dict[str, Any]:
    available_columns = _parquet_columns(dataframe_path)
    time_column, time_unit = _resolve_time_column(metadata, available_columns)
    signal_specs = _resolve_signal_requests(
        signal_requests, meta=metadata, available_columns=available_columns
    )
    read_columns = list(dict.fromkeys([time_column, *[spec["column"] for spec in signal_specs]]))
    try:
        df = pd.read_parquet(dataframe_path, columns=read_columns)
    except Exception as exc:
        raise TimeseriesUnavailableError(
            "Stream dataframe could not be read.", details={"path": str(dataframe_path), "error": f"{type(exc).__name__}: {exc}"}
        ) from exc
    windowed = _window_dataframe(
        df,
        time_column=time_column,
        requested_start_s=window_request["start_s"],
        requested_end_s=window_request["end_s"],
    )
    if windowed.empty:
        raise TimeseriesUnavailableError(
            "Requested window contains no stream samples.",
            details={"stream_name": stream_name, **dict(window_request)},
        )
    signal_windowed = _rows_with_selected_signal_data(
        windowed, signal_columns=[spec["column"] for spec in signal_specs]
    )
    if signal_windowed.empty:
        raise TimeseriesUnavailableError(
            "Requested window contains no finite stream signal samples.",
            details={"stream_name": stream_name, **dict(window_request)},
        )
    selected, sampling_mode = _downsample_min_max(
        signal_windowed,
        time_column=time_column,
        signal_columns=[spec["column"] for spec in signal_specs],
        target_points=target_points,
    )
    time_values = _numeric_values(selected[time_column])
    return {
        "stream": {"stream_name": stream_name, "stream_kind": stream_kind, "time_column": time_column},
        "sampling": {
            "mode": sampling_mode,
            "source_points": int(len(signal_windowed)),
            "returned_points": int(len(selected)),
            "target_points": int(target_points),
        },
        "time": {"column": time_column, "unit": time_unit, "values": time_values},
        "signals": [
            {
                **_signal_payload(spec),
                "stream_name": stream_name,
                "stream_kind": stream_kind,
                "time_column": time_column,
                "values": _numeric_values(selected[spec["column"]]),
            }
            for spec in signal_specs
        ],
    }


def _primary_marks(
    dataframe_path: Path,
    metadata: Mapping[str, Any],
    *,
    window_request: Mapping[str, float | None],
) -> list[dict[str, Any]]:
    available_columns = _parquet_columns(dataframe_path)
    time_column, _ = _resolve_time_column(metadata, available_columns)
    mark_column = _resolve_mark_column(metadata, available_columns)
    if mark_column is None:
        return []
    try:
        df = pd.read_parquet(dataframe_path, columns=[time_column, mark_column])
    except Exception:
        return []
    windowed = _window_dataframe(
        df,
        time_column=time_column,
        requested_start_s=window_request["start_s"],
        requested_end_s=window_request["end_s"],
    )
    return _mark_overlays(windowed, time_column=time_column, mark_column=mark_column)


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {str(key): value for key, value in raw.items()} if isinstance(raw, Mapping) else {}


def _parse_session_ref(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise InvalidRequestError("Time-series request must include a session object.")
    run_id = _required_text(value.get("run_id"), field_name="session.run_id")
    session_id = _required_text(value.get("session_id"), field_name="session.session_id")
    expected_key = make_session_key(run_id, session_id)
    session_key = _optional_text(value.get("session_key")) or expected_key
    if session_key != expected_key:
        raise InvalidRequestError(
            "session_key does not match run_id/session_id.",
            details={"session_key": session_key, "expected_session_key": expected_key},
        )
    library_id = _optional_text(value.get("library_id"))
    out = {"run_id": run_id, "session_id": session_id, "session_key": session_key}
    if library_id is not None:
        out["library_id"] = library_id
    return out


def _resolve_time_column(meta: Mapping[str, Any], available_columns: Sequence[str]) -> tuple[str, str]:
    for key in ("time_column", "time_col", "primary_time_column"):
        candidate = _optional_text(meta.get(key))
        if candidate in available_columns:
            return candidate, _time_unit(meta, candidate)

    signals = meta.get("signals")
    if isinstance(signals, Mapping):
        for column, info in signals.items():
            if str(column) not in available_columns or not isinstance(info, Mapping):
                continue
            if _norm(info.get("quantity")) == "time" or _norm(info.get("domain")) == "time":
                return str(column), _time_unit(meta, str(column))

    for candidate in ("time_s", "elapsed_time_s", "timestamp_s", "timestamp", "time"):
        if candidate in available_columns:
            return candidate, _time_unit(meta, candidate)

    raise TimeseriesUnavailableError(
        "Could not resolve a usable time column.",
        details={"available_columns": list(available_columns)},
    )


def _time_unit(meta: Mapping[str, Any], column: str) -> str:
    signals = meta.get("signals")
    if isinstance(signals, Mapping) and isinstance(signals.get(column), Mapping):
        unit = _optional_text(signals[column].get("unit"))
        if unit:
            return unit
    return "s"


def _resolve_signal_requests(
    value: Any,
    *,
    meta: Mapping[str, Any],
    available_columns: Sequence[str],
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise InvalidRequestError("Time-series request must include at least one signal.")

    out: list[dict[str, Any]] = []
    used_columns: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise InvalidRequestError(
                "Each requested signal must be an object.",
                details={"index": index},
            )
        if item.get("column") is not None:
            spec = _resolve_column_request(item.get("column"), meta=meta, available_columns=available_columns)
        elif item.get("selector") is not None:
            spec = _resolve_selector_request(item.get("selector"), meta=meta, available_columns=available_columns)
        else:
            raise InvalidRequestError(
                "Requested signal must include column or selector.",
                details={"index": index},
            )
        if spec["column"] not in used_columns:
            used_columns.add(spec["column"])
            out.append(spec)
    return out


def _resolve_column_request(
    value: Any,
    *,
    meta: Mapping[str, Any],
    available_columns: Sequence[str],
) -> dict[str, Any]:
    column = _required_text(value, field_name="signal.column")
    if column not in available_columns:
        raise SignalNotFoundError(
            "Requested signal column was not found.",
            details={"column": column},
        )
    info = _signal_info(meta, column)
    return {"column": column, "info": info}


def _resolve_selector_request(
    value: Any,
    *,
    meta: Mapping[str, Any],
    available_columns: Sequence[str],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidRequestError("Signal selector must be an object.")
    selector = {str(k): v for k, v in dict(value).items() if v is not None}
    if not selector:
        raise InvalidRequestError("Signal selector must not be empty.")

    signals = meta.get("signals")
    signals = signals if isinstance(signals, Mapping) else {}
    matches: list[tuple[tuple[int, str], str, Mapping[str, Any]]] = []
    for column, info in signals.items():
        column_text = str(column)
        if column_text not in available_columns or not isinstance(info, Mapping):
            continue
        if _selector_matches(info, selector):
            matches.append((_selector_rank(info, column_text), column_text, info))

    if not matches:
        fallback = _activity_mask_selector_fallback(selector, available_columns)
        if fallback is not None:
            return fallback
        raise SignalNotFoundError(
            "Signal selector did not match any available signal.",
            details={"selector": selector},
        )
    matches.sort(key=lambda item: item[0])
    if len(matches) > 1 and matches[0][0][0] == matches[1][0][0]:
        raise InvalidRequestError(
            "Signal selector matched multiple equivalent signals.",
            details={"selector": selector, "matches": [item[1] for item in matches]},
        )
    return {"column": matches[0][1], "info": dict(matches[0][2])}


def _activity_mask_selector_fallback(
    selector: Mapping[str, Any],
    available_columns: Sequence[str],
) -> dict[str, Any] | None:
    if _norm(selector.get("kind")) != "qc" or _norm(selector.get("quantity")) != "mask":
        return None
    available = {str(column) for column in available_columns}
    for column in ("active_mask_qc", "inactive_mask_qc", "inactive_mask"):
        if column in available:
            return {
                "column": column,
                "info": {
                    "kind": "qc",
                    "quantity": "mask",
                    "unit": None,
                    "processing_role": "activity_mask",
                },
            }
    return None


def _selector_matches(info: Mapping[str, Any], selector: Mapping[str, Any]) -> bool:
    for key, expected in selector.items():
        if _norm(info.get(key)) != _norm(expected):
            return False
    return True


def _selector_rank(info: Mapping[str, Any], column: str) -> tuple[int, str]:
    role_score = 0 if _norm(info.get("processing_role")) == "primary_analysis" else 1
    kind = _norm(info.get("kind"))
    kind_score = 0 if kind not in {"raw", "qc"} else 1
    if kind == "qc" and _norm(info.get("quantity")) == "mask":
        return (activity_mask_column_rank(column), column)
    return (role_score * 10 + kind_score, column)


def activity_mask_column_rank(column: str) -> int:
    ranks = {
        "active_mask_qc": -3,
        "inactive_mask_qc": -2,
        "inactive_mask": -1,
    }
    return ranks.get(column, 1)


def _parse_window(value: Any) -> dict[str, float | None]:
    if value is None:
        return {"start_s": None, "end_s": None}
    if not isinstance(value, Mapping):
        raise InvalidRequestError("window must be an object when provided.")
    start_s = _optional_float(value.get("start_s"), field_name="window.start_s")
    end_s = _optional_float(value.get("end_s"), field_name="window.end_s")
    if start_s is not None and end_s is not None and end_s < start_s:
        raise InvalidRequestError("window.end_s must be >= window.start_s.")
    return {"start_s": start_s, "end_s": end_s}


def _parse_target_points(value: Any) -> int:
    if value is None:
        return DEFAULT_TARGET_POINTS
    if not isinstance(value, Mapping):
        raise InvalidRequestError("resolution must be an object when provided.")
    raw = value.get("target_points", DEFAULT_TARGET_POINTS)
    if isinstance(raw, bool):
        raise InvalidRequestError("resolution.target_points must be a positive integer.")
    try:
        target = int(raw)
    except Exception as exc:
        raise InvalidRequestError("resolution.target_points must be a positive integer.") from exc
    if target < 2:
        raise InvalidRequestError("resolution.target_points must be >= 2.")
    return target


def _window_dataframe(
    df: pd.DataFrame,
    *,
    time_column: str,
    requested_start_s: float | None,
    requested_end_s: float | None,
) -> pd.DataFrame:
    out = df.copy()
    out[time_column] = pd.to_numeric(out[time_column], errors="coerce")
    out = out[out[time_column].notna()]
    if requested_start_s is not None:
        out = out[out[time_column] >= float(requested_start_s)]
    if requested_end_s is not None:
        out = out[out[time_column] <= float(requested_end_s)]
    return out.reset_index(drop=True)


def _downsample_min_max(
    df: pd.DataFrame,
    *,
    time_column: str,
    signal_columns: Sequence[str],
    target_points: int,
) -> tuple[pd.DataFrame, str]:
    if len(df) <= target_points:
        return df.reset_index(drop=True), "raw"

    bucket_count = max(1, target_points // 2)
    positions = np.arange(len(df))
    bucket_ids = np.floor(positions * bucket_count / len(df)).astype(int)
    bucket_ids = np.minimum(bucket_ids, bucket_count - 1)

    selected_positions: set[int] = {0, len(df) - 1}
    for bucket in range(bucket_count):
        bucket_positions = positions[bucket_ids == bucket]
        if bucket_positions.size == 0:
            continue
        selected_positions.add(int(bucket_positions[0]))
        selected_positions.add(int(bucket_positions[-1]))
        for column in signal_columns:
            values = pd.to_numeric(df.iloc[bucket_positions][column], errors="coerce").to_numpy(dtype=float)
            finite = np.isfinite(values)
            if not finite.any():
                continue
            finite_positions = bucket_positions[finite]
            finite_values = values[finite]
            selected_positions.add(int(finite_positions[int(np.argmin(finite_values))]))
            selected_positions.add(int(finite_positions[int(np.argmax(finite_values))]))

    selected = df.iloc[sorted(selected_positions)].reset_index(drop=True)
    return selected, "min_max_bucket"


def _rows_with_selected_signal_data(
    df: pd.DataFrame,
    *,
    signal_columns: Sequence[str],
) -> pd.DataFrame:
    """Drop carrier rows where every requested signal is missing."""
    if df.empty or not signal_columns:
        return df.reset_index(drop=True)
    finite = np.zeros(len(df), dtype=bool)
    for column in signal_columns:
        values = pd.to_numeric(df[column], errors="coerce").to_numpy(dtype=float)
        finite |= np.isfinite(values)
    return df.loc[finite].reset_index(drop=True)


def _event_overlays(
    store: ArtifactStore,
    *,
    run_id: str,
    session_id: str,
    requested_start_s: float | None,
    requested_end_s: float | None,
    returned_start_s: float | None,
    returned_end_s: float | None,
) -> list[dict[str, Any]]:
    start_s = requested_start_s if requested_start_s is not None else returned_start_s
    end_s = requested_end_s if requested_end_s is not None else returned_end_s
    out: list[dict[str, Any]] = []
    for schema_id in list_event_types(store, run_id, session_id):
        path = store.path_events_df(run_id, session_id, schema_id)
        try:
            df = pd.read_parquet(path)
        except Exception:
            continue
        metrics_by_event_id = _metrics_by_event_id(store, run_id=run_id, session_id=session_id, schema_id=schema_id)
        for _, row in df.iterrows():
            event = _event_row_payload(row)
            event_start = event.get("start_s")
            event_end = event.get("end_s")
            if _event_overlaps_window(event_start, event_end, start_s=start_s, end_s=end_s):
                metrics = metrics_by_event_id.get(str(event.get("event_id") or ""))
                if metrics:
                    event["metrics"] = metrics
                out.append(event)
    return sorted(out, key=lambda item: (float(item.get("start_s") or 0.0), str(item.get("event_id") or "")))


def _event_row_payload(row: pd.Series) -> dict[str, Any]:
    event_type = _first_text(row.get("schema_id"), row.get("event_type"), row.get("event_name"))
    start_s = _first_float(row.get("start_time_s"), row.get("start_s"), row.get("time_s"))
    end_s = _first_float(row.get("end_time_s"), row.get("end_s"), start_s)
    return {
        "event_id": _first_text(row.get("event_id"), row.get("id")),
        "event_type": event_type,
        "display_name": _first_text(row.get("event_name"), row.get("display_name"), event_type),
        "start_s": start_s,
        "end_s": end_s,
        "peak_time_s": _first_float(row.get("peak_time_s"), row.get("trigger_time_s"), start_s),
        "end": _first_text(row.get("end"), row.get("signal"), row.get("signal_col")),
    }


def _metrics_by_event_id(
    store: ArtifactStore,
    *,
    run_id: str,
    session_id: str,
    schema_id: str,
) -> dict[str, dict[str, Any]]:
    path = store.path_metrics_df(run_id, session_id, schema_id)
    if not path.exists():
        return {}
    try:
        df = pd.read_parquet(path)
    except Exception:
        return {}
    if "event_id" not in df.columns or df.empty:
        return {}
    metric_columns = [
        str(column)
        for column in df.columns
        if str(column) not in {"event_id", "session_id", "schema_id"}
    ]
    out: dict[str, dict[str, Any]] = {}
    for _, row in df.iterrows():
        event_id = _first_text(row.get("event_id"))
        if event_id is None:
            continue
        metrics: dict[str, Any] = {}
        for column in metric_columns:
            value = _json_metric_value(row.get(column))
            if value is not None:
                metrics[column] = value
        if metrics:
            out[event_id] = metrics
    return out


def _json_metric_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.generic):
        return _json_metric_value(value.item())
    return str(value)


def _event_overlaps_window(
    event_start: float | None,
    event_end: float | None,
    *,
    start_s: float | None,
    end_s: float | None,
) -> bool:
    if event_start is None and event_end is None:
        return True
    event_start = event_start if event_start is not None else event_end
    event_end = event_end if event_end is not None else event_start
    if event_start is None or event_end is None:
        return True
    if start_s is not None and event_end < start_s:
        return False
    if end_s is not None and event_start > end_s:
        return False
    return True


def _resolve_mark_column(meta: Mapping[str, Any], available_columns: Sequence[str]) -> str | None:
    available = {str(column) for column in available_columns}
    if "mark" in available:
        return "mark"

    signals = meta.get("signals")
    if isinstance(signals, Mapping):
        for column, info in signals.items():
            column_text = str(column)
            if column_text not in available or not isinstance(info, Mapping):
                continue
            if _norm(column_text) == "mark":
                return column_text
            if _norm(info.get("field")) == "mark" or _norm(info.get("quantity")) == "mark":
                return column_text
            if _norm(info.get("class")) == "event_flag" and "mark" in _norm(info.get("source")):
                return column_text

    for candidate in ("logger_mark", "sample_mark", "marked"):
        if candidate in available:
            return candidate
    return None


def _mark_overlays(
    df: pd.DataFrame,
    *,
    time_column: str,
    mark_column: str,
) -> list[dict[str, Any]]:
    if mark_column not in df.columns or time_column not in df.columns:
        return []

    times = pd.to_numeric(df[time_column], errors="coerce")
    mask = _mark_mask(df[mark_column]) & times.notna()
    if not bool(mask.any()):
        return []

    out: list[dict[str, Any]] = []
    for index, time_s in enumerate(times.loc[mask].to_numpy(dtype=float), start=1):
        if not np.isfinite(time_s):
            continue
        out.append(
            {
                "mark_id": f"mark-{index}",
                "time_s": float(time_s),
                "display_name": f"Mark {index}",
                "column": mark_column,
            }
        )
    return out


def _mark_mask(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)

    numeric = pd.to_numeric(series, errors="coerce")
    if bool(numeric.notna().any()):
        return numeric.fillna(0) != 0

    text = series.astype(str).str.strip().str.lower()
    return text.isin({"1", "true", "t", "yes", "y", "mark", "marked"})


def _signal_payload(spec: Mapping[str, Any]) -> dict[str, Any]:
    column = str(spec["column"])
    info = spec.get("info") if isinstance(spec.get("info"), Mapping) else {}
    payload = {
        "signal_id": _signal_id(column, info),
        "column": column,
        "display_name": _signal_display_name(column, info),
    }
    for key in ("end", "domain", "quantity", "unit", "processing_role", "kind", "sensor", "motion_source_id", "origin"):
        value = info.get(key) if isinstance(info, Mapping) else None
        if value is not None:
            payload[key] = value
    derivation = info.get("derivation") if isinstance(info, Mapping) else None
    if isinstance(derivation, Mapping):
        payload["derivation"] = {str(k): v for k, v in dict(derivation).items()}
    return payload


def _window_warnings(
    *,
    source_df: pd.DataFrame,
    returned_df: pd.DataFrame,
    time_column: str,
    requested_start_s: float | None,
    requested_end_s: float | None,
) -> list[str]:
    if source_df.empty or returned_df.empty:
        return []
    source_time = pd.to_numeric(source_df[time_column], errors="coerce").dropna()
    returned_time = pd.to_numeric(returned_df[time_column], errors="coerce").dropna()
    if source_time.empty or returned_time.empty:
        return []
    warnings: list[str] = []
    tolerance_s = _window_warning_tolerance_s(source_time)
    if requested_start_s is not None and float(requested_start_s) < float(source_time.min()) - tolerance_s:
        warnings.append("requested_window_starts_before_session")
    if requested_end_s is not None and float(requested_end_s) > float(source_time.max()) + tolerance_s:
        warnings.append("requested_window_ends_after_session")
    return warnings


def _window_warning_tolerance_s(source_time: pd.Series) -> float:
    ordered = source_time.sort_values()
    deltas = ordered.diff().dropna()
    positive_deltas = deltas[deltas > 0]
    if positive_deltas.empty:
        return WINDOW_BOUNDARY_WARNING_TOLERANCE_S
    median_delta = float(positive_deltas.median())
    if not np.isfinite(median_delta):
        return WINDOW_BOUNDARY_WARNING_TOLERANCE_S
    return max(WINDOW_BOUNDARY_WARNING_TOLERANCE_S, median_delta * 2.0)


def _numeric_values(series: pd.Series) -> list[float | None]:
    numeric = pd.to_numeric(series, errors="coerce")
    out: list[float | None] = []
    for value in numeric.to_numpy(dtype=float):
        if np.isfinite(value):
            out.append(float(value))
        else:
            out.append(None)
    return out


def _signal_info(meta: Mapping[str, Any], column: str) -> dict[str, Any]:
    signals = meta.get("signals")
    if isinstance(signals, Mapping) and isinstance(signals.get(column), Mapping):
        return {str(k): v for k, v in dict(signals[column]).items()}
    return {}


def _parquet_columns(path: Path) -> list[str]:
    try:
        import pyarrow.parquet as pq

        return [str(name) for name in pq.read_schema(path).names]
    except Exception:
        try:
            return [str(name) for name in pd.read_parquet(path).columns]
        except Exception as exc:
            raise TimeseriesUnavailableError(
                "Session dataframe schema could not be read.",
                details={"path": str(path), "error": f"{type(exc).__name__}: {exc}"},
            ) from exc


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(data) if isinstance(data, Mapping) else {}


def _required_text(value: Any, *, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise InvalidRequestError(f"Missing non-empty {field_name}.")
    return text


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _optional_float(value: Any, *, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise InvalidRequestError(f"{field_name} must be numeric.")
    try:
        return float(value)
    except Exception as exc:
        raise InvalidRequestError(f"{field_name} must be numeric.") from exc


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _optional_text(value)
        if text is not None:
            return text
    return None


def _first_float(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            if isinstance(value, bool) or pd.isna(value):
                continue
            return float(value)
        except Exception:
            continue
    return None


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()
