"""Distance-domain reads for the canonical spatial-context stream."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from bodaqs_analysis.artifacts import ArtifactStore

from .errors import InvalidRequestError, SessionNotFoundError, TimeseriesUnavailableError
from .ids import make_session_ref_id
from .timeseries import (
    _downsample_min_max,
    _numeric_values,
    _optional_float,
    _optional_text,
    _parquet_columns,
    _parse_session_ref,
    _parse_target_points,
    _read_json_object,
    _resolve_signal_requests,
    _signal_payload,
)


SPATIAL_CONTEXT_WINDOW_SCHEMA = "bodaqs.spatial_context_window"
SPATIAL_CONTEXT_WINDOW_VERSION = 1
SPATIAL_CONTEXT_STREAM_NAME = "spatial_context"
DEFAULT_METRICS = (
    "altitude_m",
    "gradient_fraction",
    "twistiness_rad_per_m",
    "front_suspension_activity",
    "rear_suspension_activity",
    "combined_suspension_activity",
)


def get_spatial_context_window(
    library_root: str | Path,
    request: Mapping[str, Any],
    *,
    library_id: str | None = None,
) -> dict[str, Any]:
    """Return selected canonical metrics on their native distance grid."""
    if not isinstance(request, Mapping):
        raise InvalidRequestError("Spatial-context window request must be an object.")
    session_ref = _parse_session_ref(request.get("session"))
    request_library_id = session_ref.get("library_id")
    if library_id is not None and request_library_id not in {None, library_id}:
        raise InvalidRequestError("session.library_id does not match the request library.")

    store = ArtifactStore(Path(library_root))
    run_id = session_ref["run_id"]
    session_id = session_ref["session_id"]
    if not store.session_dir(run_id, session_id).exists():
        raise SessionNotFoundError(details={"run_id": run_id, "session_id": session_id})
    path = store.path_session_stream_df(run_id, session_id, SPATIAL_CONTEXT_STREAM_NAME)
    if not path.exists():
        raise TimeseriesUnavailableError(
            "Spatial-context stream was not found.",
            details={"run_id": run_id, "session_id": session_id},
        )
    metadata = _read_json_object(
        store.path_session_stream_meta(run_id, session_id, SPATIAL_CONTEXT_STREAM_NAME)
    )
    columns = _parquet_columns(path)
    coordinate = metadata.get("coordinate") if isinstance(metadata.get("coordinate"), Mapping) else {}
    time_mapping = metadata.get("time_mapping") if isinstance(metadata.get("time_mapping"), Mapping) else {}
    distance_column = _optional_text(coordinate.get("column")) or "distance_m"
    time_column = _optional_text(time_mapping.get("column")) or "representative_time_s"
    if distance_column not in columns:
        raise TimeseriesUnavailableError("Spatial-context distance coordinate was not found.")

    requested = request.get("metrics", request.get("signals"))
    if requested is None:
        requested = [{"column": column} for column in DEFAULT_METRICS if column in columns]
    elif isinstance(requested, list):
        requested = [{"column": item} if isinstance(item, str) else item for item in requested]
    signal_specs = _resolve_signal_requests(requested, meta=metadata, available_columns=columns)
    if not signal_specs:
        raise InvalidRequestError("No spatial-context metrics were selected.")

    window = _parse_distance_window(request.get("window"))
    target_points = _parse_target_points(request.get("resolution"))
    read_columns = [distance_column, *[item["column"] for item in signal_specs]]
    if time_column in columns:
        read_columns.append(time_column)
    for diagnostic in ("distance_support_fraction", "active_mask_qc", "continuity_segment"):
        if diagnostic in columns and diagnostic not in read_columns:
            read_columns.append(diagnostic)
    try:
        frame = pd.read_parquet(path, columns=list(dict.fromkeys(read_columns)))
    except Exception as exc:
        raise TimeseriesUnavailableError(
            "Spatial-context stream could not be read.", details={"path": str(path)}
        ) from exc
    frame[distance_column] = pd.to_numeric(frame[distance_column], errors="coerce")
    frame = frame[frame[distance_column].notna()]
    if window["start_m"] is not None:
        frame = frame[frame[distance_column] >= window["start_m"]]
    if window["end_m"] is not None:
        frame = frame[frame[distance_column] <= window["end_m"]]
    frame = frame.reset_index(drop=True)
    if frame.empty:
        raise TimeseriesUnavailableError("Requested distance window contains no spatial samples.")

    downsample_columns = [item["column"] for item in signal_specs]
    downsample_columns.extend(
        column
        for column in ("distance_support_fraction", "active_mask_qc", "continuity_segment")
        if column in frame.columns
    )
    selected, mode = _downsample_min_max(
        frame,
        time_column=distance_column,
        signal_columns=downsample_columns,
        target_points=target_points,
    )
    distance_values = _numeric_values(selected[distance_column])
    response_session: dict[str, Any] = {
        "library_id": library_id or request_library_id,
        "session_key": session_ref["session_key"],
        "run_id": run_id,
        "session_id": session_id,
    }
    if response_session["library_id"] is not None:
        response_session["session_ref_id"] = make_session_ref_id(
            response_session["library_id"], response_session["session_key"]
        )
    diagnostics = []
    for column in ("distance_support_fraction", "active_mask_qc", "continuity_segment"):
        if column in selected.columns:
            diagnostics.append({"column": column, "values": _numeric_values(selected[column])})
    response: dict[str, Any] = {
        "schema": SPATIAL_CONTEXT_WINDOW_SCHEMA,
        "version": SPATIAL_CONTEXT_WINDOW_VERSION,
        "encoding": "json_arrays",
        "session": response_session,
        "status": metadata.get("status", "succeeded"),
        "window": {
            "requested_start_m": window["start_m"],
            "requested_end_m": window["end_m"],
            "returned_start_m": distance_values[0] if distance_values else None,
            "returned_end_m": distance_values[-1] if distance_values else None,
        },
        "sampling": {
            "mode": mode,
            "source_points": len(frame),
            "returned_points": len(selected),
            "target_points": target_points,
        },
        "distance": {
            "column": distance_column,
            "unit": _optional_text(coordinate.get("unit")) or "m",
            "values": distance_values,
        },
        "time_mapping": {
            "column": time_column if time_column in selected.columns else None,
            "unit": "s",
            "values": _numeric_values(selected[time_column]) if time_column in selected.columns else [],
        },
        "metrics": [
            {**_signal_payload(spec), "values": _numeric_values(selected[spec["column"]])}
            for spec in signal_specs
        ],
        "diagnostics": diagnostics,
        "warnings": list(metadata.get("warnings") or []),
    }
    if bool(request.get("include_provenance", False)):
        response["provenance"] = {
            "algorithm_version": metadata.get("algorithm_version"),
            "effective_config": metadata.get("effective_config"),
            "evidence_provenance": metadata.get("evidence_provenance"),
            "metric_provenance": metadata.get("metric_provenance"),
            "quality": metadata.get("quality"),
        }
    return response


def _parse_distance_window(value: Any) -> dict[str, float | None]:
    if value is None:
        return {"start_m": None, "end_m": None}
    if not isinstance(value, Mapping):
        raise InvalidRequestError("window must be an object when provided.")
    start = _optional_float(value.get("start_m"), field_name="window.start_m")
    end = _optional_float(value.get("end_m"), field_name="window.end_m")
    if start is not None and end is not None and end < start:
        raise InvalidRequestError("window.end_m must be >= window.start_m.")
    return {"start_m": start, "end_m": end}
