"""Disposable per-session indexes derived from canonical activity masks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from bodaqs_analysis.artifacts import ArtifactStore

from .cache import stable_cache_digest
from .timeseries import _parquet_columns, _resolve_time_column


ACTIVITY_INDEX_SCHEMA = "bodaqs.activity_index"
ACTIVITY_INDEX_VERSION = 1
ACTIVITY_INDEX_ALGORITHM_VERSION = 2
ACTIVITY_COLUMNS = ("active_mask_qc", "inactive_mask_qc", "inactive_mask")
SAMPLE_CONTINUITY_GAP_FACTOR = 3.0
SAMPLE_CONTINUITY_TOLERANCE_S = 1e-6
Interval = tuple[float, float]


def activity_index_cache_key(library_root: Path, ref: Mapping[str, str]) -> str:
    store = ArtifactStore(library_root)
    paths = (
        store.path_session_df(ref["run_id"], ref["session_id"]),
        store.path_session_meta(ref["run_id"], ref["session_id"]),
    )
    return stable_cache_digest(
        {
            "schema": ACTIVITY_INDEX_SCHEMA,
            "version": ACTIVITY_INDEX_VERSION,
            "algorithm_version": ACTIVITY_INDEX_ALGORITHM_VERSION,
            "session": dict(ref),
            "input_artifacts": [_artifact_identity(path) for path in paths],
        }
    )


def build_activity_index(library_root: Path, ref: Mapping[str, str]) -> dict[str, Any]:
    store = ArtifactStore(library_root)
    data_path = store.path_session_df(ref["run_id"], ref["session_id"])
    metadata_path = store.path_session_meta(ref["run_id"], ref["session_id"])
    if not data_path.exists():
        return unavailable_activity_index(ref, "session_data_unavailable")
    metadata = _read_json_object(metadata_path)
    columns = _parquet_columns(data_path)
    activity_column = next((column for column in ACTIVITY_COLUMNS if column in columns), None)
    if activity_column is None:
        return unavailable_activity_index(ref, "activity_mask_unavailable")
    time_column, _ = _resolve_time_column(metadata, columns)
    frame = pd.read_parquet(data_path, columns=[time_column, activity_column])
    return build_activity_index_from_frame(
        frame,
        session_ref=ref,
        time_column=time_column,
        activity_column=activity_column,
        input_artifacts=[_artifact_identity(data_path), _artifact_identity(metadata_path)],
    )


def build_activity_index_from_frame(
    frame: pd.DataFrame,
    *,
    session_ref: Mapping[str, str] | None = None,
    time_column: str,
    activity_column: str,
    input_artifacts: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    times = pd.to_numeric(frame[time_column], errors="coerce").to_numpy(dtype=float)
    raw = pd.to_numeric(frame[activity_column], errors="coerce").to_numpy(dtype=float)
    known = np.isfinite(times) & np.isfinite(raw)
    active = known & ((raw > 0) if activity_column == "active_mask_qc" else (raw <= 0))
    inactive = known & ~active
    active_intervals = sample_cell_intervals(times, active)
    known_intervals = sample_cell_intervals(times, known)
    active_runs = _mask_runs(times, active)
    inactive_runs = _mask_runs(times, inactive)
    nominal_interval_s, maximum_continuous_gap_s = _sample_timing(times)
    sample_count = int(len(times))
    known_count = int(np.count_nonzero(known))
    active_count = int(np.count_nonzero(active))
    inactive_count = int(np.count_nonzero(inactive))
    run_count = len(active_runs) + len(inactive_runs)
    return {
        "schema": ACTIVITY_INDEX_SCHEMA,
        "version": ACTIVITY_INDEX_VERSION,
        "algorithm_version": ACTIVITY_INDEX_ALGORITHM_VERSION,
        "status": "succeeded",
        "session_ref": dict(session_ref or {}),
        "source": {
            "stream_name": "primary",
            "time_column": time_column,
            "activity_column": activity_column,
            "activity_semantics": "positive_is_active" if activity_column == "active_mask_qc" else "nonpositive_is_active",
            "continuity": {
                "policy": "jitter_tolerant_conservative_sample_cells",
                "nominal_interval_s": nominal_interval_s,
                "maximum_continuous_gap_s": maximum_continuous_gap_s,
                "maximum_gap_factor": SAMPLE_CONTINUITY_GAP_FACTOR,
            },
        },
        "sample_count": sample_count,
        "known_sample_count": known_count,
        "active_sample_count": active_count,
        "inactive_sample_count": inactive_count,
        "unknown_sample_count": sample_count - known_count,
        "active_runs": active_runs,
        "inactive_runs": inactive_runs,
        "active_intervals_s": [[start, end] for start, end in active_intervals],
        "known_intervals_s": [[start, end] for start, end in known_intervals],
        "summary": {
            "active_duration_s": interval_duration(active_intervals),
            "known_duration_s": interval_duration(known_intervals),
            "encoded_run_count": run_count,
            "runs_per_sample": run_count / sample_count if sample_count else 0.0,
            "active_interval_count": len(active_intervals),
            "known_interval_count": len(known_intervals),
            "intervals_per_sample": len(known_intervals) / sample_count if sample_count else 0.0,
        },
        "provenance": {"input_artifacts": [dict(item) for item in input_artifacts]},
        "warnings": [],
    }


def unavailable_activity_index(ref: Mapping[str, str], code: str) -> dict[str, Any]:
    return {
        "schema": ACTIVITY_INDEX_SCHEMA,
        "version": ACTIVITY_INDEX_VERSION,
        "algorithm_version": ACTIVITY_INDEX_ALGORITHM_VERSION,
        "status": "unavailable",
        "session_ref": dict(ref),
        "active_runs": [],
        "inactive_runs": [],
        "active_intervals_s": [],
        "known_intervals_s": [],
        "summary": {"active_duration_s": 0.0, "known_duration_s": 0.0, "encoded_run_count": 0, "runs_per_sample": 0.0},
        "warnings": [{"code": code}],
    }


def activity_regions(index: Mapping[str, Any]) -> tuple[list[Interval], list[Interval], dict[str, Any]]:
    if index.get("status") != "succeeded":
        warnings = index.get("warnings") if isinstance(index.get("warnings"), list) else []
        return [], [], {"criterion_id": "$activity", "status": "unavailable", "warnings": warnings}
    truth = _intervals(index.get("active_intervals_s"))
    known = _intervals(index.get("known_intervals_s"))
    source = index.get("source") if isinstance(index.get("source"), Mapping) else {}
    return truth, known, {
        "criterion_id": "$activity",
        "status": "succeeded",
        "resolved_series": {
            "stream_name": "primary",
            "column": source.get("activity_column"),
            "coordinate_column": source.get("time_column"),
            "coordinate_unit": "s",
        },
        "true_duration_s": interval_duration(truth),
        "unknown_duration_s": None,
        "warnings": [],
    }


def sample_cell_intervals(times: np.ndarray, selected: np.ndarray) -> list[Interval]:
    raw_times = np.asarray(times, dtype=float)
    raw_selected = np.asarray(selected, dtype=bool)
    if raw_times.shape != raw_selected.shape:
        raise ValueError("times and selected must have the same shape")
    finite = np.isfinite(raw_times)
    if not np.any(finite):
        return []

    ordered_times = raw_times[finite]
    ordered_selected = raw_selected[finite]
    order = np.argsort(ordered_times, kind="stable")
    ordered_times = ordered_times[order]
    ordered_selected = ordered_selected[order]
    valid_times, first_indices = np.unique(ordered_times, return_index=True)
    selected_times = np.logical_or.reduceat(ordered_selected, first_indices)
    nominal, maximum_gap = _sample_timing(valid_times)
    half = nominal / 2.0
    starts = np.maximum(0.0, valid_times - half)
    ends = valid_times + half
    if valid_times.size > 1:
        gaps = np.diff(valid_times)
        continuous = gaps <= maximum_gap + 1e-9
        midpoints = (valid_times[:-1] + valid_times[1:]) / 2.0
        ends[:-1] = np.where(continuous, midpoints, ends[:-1])
        starts[1:] = np.where(continuous, midpoints, starts[1:])

    selected_rows = np.flatnonzero(selected_times)
    if selected_rows.size == 0:
        return []
    selected_starts = starts[selected_rows]
    selected_ends = ends[selected_rows]
    split_at = np.flatnonzero(selected_starts[1:] > selected_ends[:-1] + 1e-9) + 1
    groups = np.split(np.arange(selected_rows.size), split_at)
    return [(float(selected_starts[group[0]]), float(selected_ends[group[-1]])) for group in groups]


def _sample_timing(times: np.ndarray) -> tuple[float, float]:
    valid_times = np.sort(np.unique(np.asarray(times, dtype=float)[np.isfinite(times)]))
    positive = np.diff(valid_times)
    positive = positive[positive > 1e-9]
    nominal = (
        float(np.median(positive))
        if positive.size >= 2
        else (min(float(positive[0]), 0.1) if positive.size else 0.001)
    )
    maximum_gap = max(
        SAMPLE_CONTINUITY_GAP_FACTOR * nominal,
        nominal + SAMPLE_CONTINUITY_TOLERANCE_S,
    )
    return nominal, maximum_gap


def interval_duration(intervals: Sequence[Interval]) -> float:
    return sum(end - start for start, end in intervals)


def _mask_runs(times: np.ndarray, selected: np.ndarray) -> list[dict[str, Any]]:
    indexes = np.flatnonzero(np.asarray(selected, dtype=bool))
    if indexes.size == 0:
        return []
    split_at = np.flatnonzero(np.diff(indexes) > 1) + 1
    runs: list[dict[str, Any]] = []
    for run in np.split(indexes, split_at):
        start_index = int(run[0])
        end_index = int(run[-1]) + 1
        runs.append(
            {
                "start_index": start_index,
                "end_index": end_index,
                "start_time_s": float(times[start_index]),
                "end_time_s": float(times[end_index - 1]),
            }
        )
    return runs


def _intervals(value: Any) -> list[Interval]:
    if not isinstance(value, list):
        return []
    return [
        (float(item[0]), float(item[1]))
        for item in value
        if isinstance(item, list) and len(item) == 2 and float(item[1]) > float(item[0])
    ]


def _artifact_identity(path: Path) -> dict[str, Any]:
    stat = path.stat() if path.exists() else None
    return {
        "path": str(path),
        "exists": stat is not None,
        "size_bytes": stat.st_size if stat is not None else None,
        "modified_ns": stat.st_mtime_ns if stat is not None else None,
    }


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}
