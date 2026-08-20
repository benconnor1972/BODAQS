"""Library discovery and catalog helpers for the BODAQS Library API adapter."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from bodaqs_analysis.artifacts import (
    ArtifactStore,
    list_event_types,
    list_metric_event_types,
    list_runs,
    list_sessions,
)
from bodaqs_analysis.gps_semantics import resolve_gps_columns

from .errors import InvalidRequestError
from .ids import derive_object_id, make_session_key, make_session_ref_id
from .models import library_payload


LIBRARY_DEFINITION_FILENAME = "library_definition.json"
LIBRARIES_DIRNAME = "libraries"
RUNS_DIRNAME = "runs"
SESSION_CATALOG_SCHEMA = "bodaqs.session_catalog"
SESSION_CATALOG_VERSION = 3
SESSION_CATALOG_ROW_SCHEMA = "bodaqs.session_catalog_row"
SESSION_CATALOG_ROW_VERSION = 3
SESSION_GPS_SUMMARY_SCHEMA = "bodaqs.session_gps_summary"
SESSION_GPS_SUMMARY_VERSION = 1
SESSION_GPS_POINTS_SCHEMA = "bodaqs.session_gps_points"
SESSION_GPS_POINTS_VERSION = 1
GPS_GAP_THRESHOLD_S = 5.0
DEFAULT_GPS_POINTS_MAX_POINTS = 2000


def discover_libraries(libraries_root: str | Path) -> list[dict[str, Any]]:
    """Discover processed BODAQS libraries under one libraries root."""

    root = Path(libraries_root).expanduser()
    if not root.exists():
        raise InvalidRequestError(
            "Libraries root does not exist.",
            details={"libraries_root": str(root)},
        )
    if not root.is_dir():
        raise InvalidRequestError(
            "Libraries root is not a directory.",
            details={"libraries_root": str(root)},
        )

    libraries: list[dict[str, Any]] = []
    seen_ids: dict[str, Path] = {}
    for child in _iter_library_candidate_dirs(root):
        discovered = _discover_library_dir(child)
        if discovered is None:
            continue

        library_id = str(discovered["library_id"])
        previous = seen_ids.get(library_id)
        if previous is not None:
            raise InvalidRequestError(
                "Duplicate library_id discovered under libraries root.",
                details={
                    "library_id": library_id,
                    "first_root": str(previous),
                    "second_root": str(child),
                },
            )
        seen_ids[library_id] = child
        libraries.append(discovered)

    return libraries


def _iter_library_candidate_dirs(root: Path) -> list[Path]:
    candidates: list[Path] = []
    seen_paths: set[Path] = set()
    for search_root in (root / LIBRARIES_DIRNAME, root):
        if not search_root.exists() or not search_root.is_dir():
            continue
        for child in sorted((p for p in search_root.iterdir() if p.is_dir()), key=lambda p: p.name.lower()):
            resolved = child.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            candidates.append(child)
    return candidates


def build_session_catalog(
    library_root: str | Path,
    *,
    library_id: str | None = None,
) -> dict[str, Any]:
    """Build a compact JSON-serializable catalog for one processed library."""

    root = Path(library_root).expanduser()
    if not root.exists() or not root.is_dir():
        raise InvalidRequestError(
            "Library root does not exist or is not a directory.",
            details={"library_root": str(root)},
        )

    store = ArtifactStore(root)
    rows: list[dict[str, Any]] = []
    for run_id in list_runs(store):
        run_manifest = _read_json_object(store.path_run_manifest(run_id)) or {}
        for session_id in list_sessions(store, run_id):
            rows.append(
                _build_session_catalog_row(
                    store,
                    library_id=library_id,
                    run_id=str(run_id),
                    session_id=str(session_id),
                    run_manifest=run_manifest,
                )
            )

    return {
        "schema": SESSION_CATALOG_SCHEMA,
        "version": SESSION_CATALOG_VERSION,
        "library_id": library_id,
        "generated_at": _utcnow_iso(),
        "row_count": len(rows),
        "rows": rows,
    }


def _discover_library_dir(path: Path) -> dict[str, Any] | None:
    definition_path = path / LIBRARY_DEFINITION_FILENAME
    definition = _read_json_object(definition_path)
    has_definition = definition is not None
    has_runs = _has_runs(path)
    if not has_definition and not has_runs:
        return None

    library_id = _metadata_text(definition, "library_id") if definition else None
    display_name = _metadata_text(definition, "display_name") if definition else None

    if not library_id:
        library_id = derive_object_id(path.name, fallback="library")
    if not display_name:
        display_name = _display_name_from_id(library_id)

    return library_payload(
        library_id=library_id,
        display_name=display_name,
        root=path.resolve(),
        definition=definition,
    )


def _build_session_catalog_row(
    store: ArtifactStore,
    *,
    library_id: str | None,
    run_id: str,
    session_id: str,
    run_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    session_key = make_session_key(run_id, session_id)
    session_manifest = _read_json_object(store.path_session_manifest(run_id, session_id)) or {}
    session_meta = _read_json_object(store.path_session_meta(run_id, session_id)) or {}

    note_status, note_fields = _note_summary(store, run_id=run_id, session_id=session_id)
    event_summary, event_schema = _event_summary(store, run_id=run_id, session_id=session_id)
    metric_summary = _metric_summary(store, run_id=run_id, session_id=session_id)
    provenance = _provenance_summary(
        run_manifest=run_manifest,
        session_manifest=session_manifest,
        session_id=session_id,
    )

    run_description = _optional_text(run_manifest.get("description"))
    session_description = _optional_text(session_manifest.get("description"))
    session_label = session_description or session_id
    display_label = session_label or session_key

    gps_summary = _gps_summary(
        store,
        run_id=run_id,
        session_id=session_id,
        session_meta=session_meta,
        session_manifest=session_manifest,
    )
    row = {
        "schema": SESSION_CATALOG_ROW_SCHEMA,
        "version": SESSION_CATALOG_ROW_VERSION,
        "library_id": library_id,
        "session_ref_id": make_session_ref_id(library_id, session_key) if library_id else None,
        "session_key": session_key,
        "run_id": run_id,
        "session_id": session_id,
        "display": {
            "label": display_label,
            "run_label": run_description or run_id,
            "session_label": session_label,
        },
        "timestamps": _timestamp_summary(run_manifest, session_meta),
        "note_status": note_status,
        "note_fields": note_fields,
        "qc_summary": _qc_summary(session_meta, session_manifest),
        "summary": _session_summary(session_manifest, gps_summary=gps_summary),
        "provenance": provenance,
        "event_schema": event_schema,
        "available_signals": _available_signals(
            store,
            run_id=run_id,
            session_id=session_id,
            session_meta=session_meta,
        ),
        "gps_summary": gps_summary,
        "video_summary": _video_summary(store, run_id=run_id, session_id=session_id),
        "event_summary": event_summary,
        "metric_summary": metric_summary,
    }
    return row


def _gps_summary(
    store: ArtifactStore,
    *,
    run_id: str,
    session_id: str,
    session_meta: Mapping[str, Any],
    session_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    session_start_s, session_end_s = _session_time_bounds(
        session_manifest,
        dataframe_path=store.path_session_df(run_id, session_id),
    )
    session_duration_s = _duration_from_bounds(session_start_s, session_end_s)
    session_window = (session_start_s, session_end_s)
    warnings: list[str] = []
    sources: list[dict[str, Any]] = []
    source_descriptors, source_selection = _gps_source_descriptors(
        store,
        run_id=run_id,
        session_id=session_id,
        session_meta=session_meta,
    )

    for descriptor in source_descriptors:
        source = _gps_source_summary(
            source_id=descriptor["source_id"],
            stream_name=descriptor["stream_name"],
            metadata=descriptor["metadata"],
            source_info=descriptor["source_info"],
            dataframe_path=descriptor["dataframe_path"],
            session_duration_s=session_duration_s,
            window_range=session_window,
        )
        if source is not None:
            warnings.extend(source.pop("_warnings", []))
            sources.append(source)

    if not sources:
        return {
            "schema": SESSION_GPS_SUMMARY_SCHEMA,
            "version": SESSION_GPS_SUMMARY_VERSION,
            "present": False,
            "preferred_source": None,
            "preferred_source_id": None,
            "preferred_source_kind": None,
            "source_selection_method": source_selection["method"],
            "gps_source_policy": source_selection.get("policy"),
            "sources": [],
            "session_duration_s": session_duration_s,
            "time_coverage_ratio": 0.0,
            "position_point_count": 0,
            "quality": "absent",
            "warnings": [],
        }

    preferred = _preferred_gps_source(sources, source_selection)
    position_point_count = int(preferred.get("point_count") or 0)
    time_coverage_ratio = min(1.0, max(0.0, float(preferred.get("_coverage_ratio") or 0.0)))
    max_gap_s = preferred.get("max_gap_s")
    position_bbox = preferred.get("position_bbox") if isinstance(preferred.get("position_bbox"), Mapping) else None

    if position_point_count <= 0:
        quality = "absent"
    elif position_point_count < 3:
        quality = "limited"
        warnings.append("gps_low_point_count")
    elif time_coverage_ratio >= 0.85:
        quality = "usable"
    else:
        quality = "limited"
        warnings.append("gps_coverage_limited")
    if isinstance(max_gap_s, (int, float)) and max_gap_s > GPS_GAP_THRESHOLD_S:
        warnings.append("gps_max_gap_exceeds_threshold")

    public_sources = []
    for source in sources:
        public_source = dict(source)
        public_source.pop("_coverage_ratio", None)
        public_sources.append(public_source)

    return {
        "schema": SESSION_GPS_SUMMARY_SCHEMA,
        "version": SESSION_GPS_SUMMARY_VERSION,
        "present": position_point_count > 0,
        "preferred_source": preferred.get("source_id"),
        "preferred_source_id": preferred.get("source_id"),
        "preferred_source_kind": preferred.get("kind"),
        "source_selection_method": source_selection["method"],
        "gps_source_policy": source_selection.get("policy"),
        "sources": public_sources,
        "session_duration_s": session_duration_s,
        "time_coverage_ratio": time_coverage_ratio,
        "position_point_count": position_point_count,
        "position_bbox": dict(position_bbox) if position_bbox else None,
        "quality": quality,
        "warnings": sorted(set(str(warning) for warning in warnings if warning)),
    }


def get_session_gps_points(
    library_root: str | Path,
    session_ref: Mapping[str, Any],
    *,
    library_id: str | None = None,
    max_points: int | None = None,
    window: Mapping[str, Any] | None = None,
    source_id: str | None = None,
) -> dict[str, Any]:
    """Return an on-demand GPS point set for one processed session."""

    store = ArtifactStore(Path(library_root).expanduser())
    run_id = _required_text(session_ref.get("run_id"), field_name="run_id")
    session_id = _required_text(session_ref.get("session_id"), field_name="session_id")
    session_manifest = _read_json_object(store.path_session_manifest(run_id, session_id)) or {}
    session_meta = _read_json_object(store.path_session_meta(run_id, session_id)) or {}
    session_start_s, session_end_s = _session_time_bounds(
        session_manifest,
        dataframe_path=store.path_session_df(run_id, session_id),
    )
    session_duration_s = _duration_from_bounds(session_start_s, session_end_s)
    max_points = _normalized_max_points(max_points)
    window_range = _normalized_time_window(window, default_range=(session_start_s, session_end_s))

    candidates: list[dict[str, Any]] = []
    source_descriptors, source_selection = _gps_source_descriptors(
        store,
        run_id=run_id,
        session_id=session_id,
        session_meta=session_meta,
    )
    requested_source_id = _optional_text(source_id)
    for descriptor in source_descriptors:
        if requested_source_id and requested_source_id not in {
            descriptor["source_id"],
            descriptor["stream_name"],
        }:
            continue
        candidate = _gps_point_source_candidate(
            source_id=descriptor["source_id"],
            stream_name=descriptor["stream_name"],
            metadata=descriptor["metadata"],
            source_info=descriptor["source_info"],
            dataframe_path=descriptor["dataframe_path"],
            max_points=max_points,
            window_range=window_range,
            session_duration_s=session_duration_s,
        )
        if candidate is not None:
            candidates.append(candidate)

    if not candidates:
        warnings = ["gps_points_unavailable"]
        if requested_source_id:
            warnings.append("gps_requested_source_unavailable")
        return {
            "schema": SESSION_GPS_POINTS_SCHEMA,
            "version": SESSION_GPS_POINTS_VERSION,
            "library_id": library_id,
            "session": dict(session_ref),
            "present": False,
            "source": None,
            "sampling": {
                "mode": "none",
                "source_points": 0,
                "returned_points": 0,
                "max_points": max_points,
                "stride": None,
                "window": _sampling_window(window_range),
            },
            "points": [],
            "warnings": warnings,
        }

    best = _preferred_gps_point_candidate(candidates, source_selection, requested_source_id=requested_source_id)
    if isinstance(best.get("source"), dict):
        best["source"]["source_selection_method"] = source_selection["method"]
        best["source"]["gps_source_policy"] = source_selection.get("policy")
    return {
        "schema": SESSION_GPS_POINTS_SCHEMA,
        "version": SESSION_GPS_POINTS_VERSION,
        "library_id": library_id,
        "session": dict(session_ref),
        "present": bool(best["points"]),
        "source": best["source"],
        "sampling": best["sampling"],
        "points": best["points"],
        "warnings": best["warnings"],
    }


def _gps_source_summary(
    *,
    source_id: str,
    stream_name: str,
    metadata: Mapping[str, Any],
    source_info: Mapping[str, Any],
    dataframe_path: Path,
    session_duration_s: float,
    window_range: tuple[float | None, float | None],
) -> dict[str, Any] | None:
    known_columns = _parquet_columns(dataframe_path)
    if known_columns is not None and not known_columns:
        return None

    time_col = _optional_text(metadata.get("time_col")) or "time_s"
    if known_columns is not None and time_col not in known_columns and "time_s" in known_columns:
        time_col = "time_s"

    latitude_col, longitude_col, elevation_col = _gps_columns(metadata, known_columns)
    if latitude_col is None or longitude_col is None:
        return None

    columns = [time_col, latitude_col, longitude_col]
    if elevation_col:
        columns.append(elevation_col)
    columns = [column for column in dict.fromkeys(columns) if known_columns is None or column in known_columns]
    warnings: list[str] = []
    try:
        df = pd.read_parquet(dataframe_path, columns=columns)
    except Exception as exc:
        return {
            "source_id": source_id,
            "kind": _gps_source_kind(source_id, metadata, source_info=source_info, latitude_col=latitude_col),
            "stream_name": stream_name,
            "timebase": _gps_timebase(metadata),
            "position_columns": {
                "latitude": latitude_col,
                "longitude": longitude_col,
            },
            "elevation_column": elevation_col,
            "quality_columns": _gps_quality_columns(metadata, source_info),
            "route_reconstruction": _gps_route_reconstruction(metadata, source_info),
            **_gps_quality_summary(metadata, source_info),
            "point_count": 0,
            "nominal_sample_rate_hz": None,
            "median_gap_s": None,
            "max_gap_s": None,
            "gap_count_over_threshold": 0,
            "gap_threshold_s": GPS_GAP_THRESHOLD_S,
            "_coverage_ratio": 0.0,
            "_warnings": [f"gps_source_read_failed:{type(exc).__name__}"],
        }

    if latitude_col not in df.columns or longitude_col not in df.columns:
        return None

    lat = pd.to_numeric(df[latitude_col], errors="coerce")
    lon = pd.to_numeric(df[longitude_col], errors="coerce")
    valid_position = lat.notna() & lon.notna()
    if time_col in df.columns:
        time_values_all = pd.to_numeric(df[time_col], errors="coerce")
        valid_position = valid_position & time_values_all.notna()
        start_s, end_s = window_range
        if start_s is not None:
            valid_position = valid_position & (time_values_all >= start_s)
        if end_s is not None:
            valid_position = valid_position & (time_values_all <= end_s)
    else:
        warnings.append("gps_time_column_missing")
    point_count = int(valid_position.sum())
    route_distance_m = _gps_route_distance_m(
        lat.loc[valid_position].to_list(),
        lon.loc[valid_position].to_list(),
    )
    position_bbox = _gps_position_bbox(
        lat.loc[valid_position].to_list(),
        lon.loc[valid_position].to_list(),
    )

    times: list[float] = []
    if time_col in df.columns:
        time_values = pd.to_numeric(df.loc[valid_position, time_col], errors="coerce").dropna()
        times = sorted(float(value) for value in time_values.to_list() if math.isfinite(float(value)))

    gaps = [b - a for a, b in zip(times, times[1:]) if b > a]
    median_gap_s = float(pd.Series(gaps).median()) if gaps else None
    max_gap_s = max(gaps) if gaps else None
    nominal_sample_rate_hz = (1.0 / median_gap_s) if median_gap_s and median_gap_s > 0 else None
    coverage_ratio = _gps_coverage_ratio(times, session_duration_s, gap_threshold_s=GPS_GAP_THRESHOLD_S)
    gap_count_over_threshold = sum(1 for gap in gaps if gap > GPS_GAP_THRESHOLD_S)

    return {
        "source_id": source_id,
        "kind": _gps_source_kind(source_id, metadata, source_info=source_info, latitude_col=latitude_col),
        "stream_name": stream_name,
        "timebase": _gps_timebase(metadata),
        "position_columns": {
            "latitude": latitude_col,
            "longitude": longitude_col,
        },
        "elevation_column": elevation_col,
        "quality_columns": _gps_quality_columns(metadata, source_info),
        "route_reconstruction": _gps_route_reconstruction(metadata, source_info),
        **_gps_quality_summary(metadata, source_info),
        "point_count": point_count,
        "position_bbox": position_bbox,
        "route_distance_m": route_distance_m,
        "nominal_sample_rate_hz": nominal_sample_rate_hz,
        "median_gap_s": median_gap_s,
        "max_gap_s": max_gap_s,
        "gap_count_over_threshold": gap_count_over_threshold,
        "gap_threshold_s": GPS_GAP_THRESHOLD_S,
        "_coverage_ratio": coverage_ratio,
        "_warnings": warnings,
    }


def _gps_point_source_candidate(
    *,
    source_id: str,
    stream_name: str,
    metadata: Mapping[str, Any],
    source_info: Mapping[str, Any],
    dataframe_path: Path,
    max_points: int,
    window_range: tuple[float | None, float | None],
    session_duration_s: float,
) -> dict[str, Any] | None:
    known_columns = _parquet_columns(dataframe_path)
    if known_columns is not None and not known_columns:
        return None
    time_col = _optional_text(metadata.get("time_col")) or "time_s"
    if known_columns is not None and time_col not in known_columns and "time_s" in known_columns:
        time_col = "time_s"
    latitude_col, longitude_col, elevation_col = _gps_columns(metadata, known_columns)
    if latitude_col is None or longitude_col is None:
        return None

    read_columns = [time_col, latitude_col, longitude_col]
    if elevation_col:
        read_columns.append(elevation_col)
    read_columns = [
        column
        for column in dict.fromkeys(read_columns)
        if known_columns is None or column in known_columns
    ]
    warnings: list[str] = []
    try:
        df = pd.read_parquet(dataframe_path, columns=read_columns)
    except Exception as exc:
        return {
                "source": {
                    "source_id": source_id,
                    "kind": _gps_source_kind(source_id, metadata, source_info=source_info, latitude_col=latitude_col),
                    "stream_name": stream_name,
                    "timebase": _gps_timebase(metadata),
                    "position_columns": {
                    "latitude": latitude_col,
                    "longitude": longitude_col,
                    },
                    "elevation_column": elevation_col,
                    "quality_columns": _gps_quality_columns(metadata, source_info),
                    "route_reconstruction": _gps_route_reconstruction(metadata, source_info),
                    **_gps_quality_summary(metadata, source_info),
                },
            "sampling": {
                "mode": "error",
                "source_points": 0,
                "returned_points": 0,
                "max_points": max_points,
                "stride": None,
                "window": _sampling_window(window_range),
            },
            "points": [],
            "warnings": [f"gps_points_read_failed:{type(exc).__name__}"],
        }

    if latitude_col not in df.columns or longitude_col not in df.columns:
        return None

    lat = pd.to_numeric(df[latitude_col], errors="coerce")
    lon = pd.to_numeric(df[longitude_col], errors="coerce")
    valid = lat.notna() & lon.notna()
    if time_col in df.columns:
        time_values = pd.to_numeric(df[time_col], errors="coerce")
        valid = valid & time_values.notna()
    else:
        time_values = pd.Series([None] * len(df), index=df.index)
        warnings.append("gps_time_column_missing")

    start_s, end_s = window_range
    if time_col in df.columns:
        if start_s is not None:
            valid = valid & (time_values >= start_s)
        if end_s is not None:
            valid = valid & (time_values <= end_s)

    filtered = df.loc[valid].copy()
    if filtered.empty:
        return {
                "source": {
                    "source_id": source_id,
                    "kind": _gps_source_kind(source_id, metadata, source_info=source_info, latitude_col=latitude_col),
                    "stream_name": stream_name,
                    "timebase": _gps_timebase(metadata),
                    "position_columns": {
                    "latitude": latitude_col,
                    "longitude": longitude_col,
                    },
                    "elevation_column": elevation_col,
                    "quality_columns": _gps_quality_columns(metadata, source_info),
                    "route_reconstruction": _gps_route_reconstruction(metadata, source_info),
                    **_gps_quality_summary(metadata, source_info),
                },
            "sampling": {
                "mode": "none",
                "source_points": 0,
                "returned_points": 0,
                "max_points": max_points,
                "stride": None,
                "window": _sampling_window(window_range),
            },
            "points": [],
            "warnings": warnings + ["gps_points_empty"],
        }

    if time_col in filtered.columns:
        filtered[time_col] = pd.to_numeric(filtered[time_col], errors="coerce")
        filtered = filtered.sort_values(time_col)
    filtered[latitude_col] = pd.to_numeric(filtered[latitude_col], errors="coerce")
    filtered[longitude_col] = pd.to_numeric(filtered[longitude_col], errors="coerce")
    if elevation_col and elevation_col in filtered.columns:
        filtered[elevation_col] = pd.to_numeric(filtered[elevation_col], errors="coerce")

    source_points = int(len(filtered))
    stride = max(1, math.ceil(source_points / max_points)) if max_points > 0 else 1
    if stride > 1:
        sampled = filtered.iloc[::stride].copy()
        if sampled.index[-1] != filtered.index[-1]:
            sampled = pd.concat([sampled, filtered.tail(1)])
        sampled = sampled.drop_duplicates()
    else:
        sampled = filtered

    points = []
    for _, row in sampled.iterrows():
        time_s = _number_or_none(row.get(time_col)) if time_col in sampled.columns else None
        elevation_m = _number_or_none(row.get(elevation_col)) if elevation_col and elevation_col in sampled.columns else None
        points.append(
            {
                "time_s": time_s,
                "longitude": float(row[longitude_col]),
                "latitude": float(row[latitude_col]),
                "elevation_m": elevation_m,
            }
        )

    return {
        "source": {
            "source_id": source_id,
            "kind": _gps_source_kind(source_id, metadata, source_info=source_info, latitude_col=latitude_col),
            "stream_name": stream_name,
            "timebase": _gps_timebase(metadata),
            "position_columns": {
                "latitude": latitude_col,
                "longitude": longitude_col,
            },
            "elevation_column": elevation_col,
            "quality_columns": _gps_quality_columns(metadata, source_info),
            "route_reconstruction": _gps_route_reconstruction(metadata, source_info),
            **_gps_quality_summary(metadata, source_info),
        },
        "sampling": {
            "mode": "stride" if stride > 1 else "raw",
            "source_points": source_points,
            "returned_points": len(points),
            "max_points": max_points,
            "stride": stride,
            "session_duration_s": session_duration_s,
            "window": _sampling_window(window_range),
        },
        "points": points,
        "warnings": warnings,
    }


def _gps_stream_names(
    store: ArtifactStore,
    *,
    run_id: str,
    session_id: str,
    session_meta: Mapping[str, Any],
) -> list[str]:
    names: set[str] = set()
    streams = session_meta.get("streams")
    if isinstance(streams, Mapping):
        names.update(str(name) for name in streams.keys() if "gps" in str(name).lower())
    streams_dir = store.session_dir(run_id, session_id) / "session" / "streams"
    if streams_dir.exists():
        names.update(child.name for child in streams_dir.iterdir() if child.is_dir() and "gps" in child.name.lower())
    return sorted(names)


def _gps_source_descriptors(
    store: ArtifactStore,
    *,
    run_id: str,
    session_id: str,
    session_meta: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    gps_sources = session_meta.get("gps_sources") if isinstance(session_meta.get("gps_sources"), Mapping) else None
    if isinstance(gps_sources, Mapping):
        descriptors: list[dict[str, Any]] = []
        for raw_source in gps_sources.get("sources") or []:
            if not isinstance(raw_source, Mapping):
                continue
            descriptor = _gps_source_descriptor(
                store,
                run_id=run_id,
                session_id=session_id,
                session_meta=session_meta,
                source_info=raw_source,
            )
            if descriptor is not None:
                descriptors.append(descriptor)
        if descriptors:
            policy = gps_sources.get("policy") if isinstance(gps_sources.get("policy"), Mapping) else {}
            return descriptors, {
                "method": "gps_sources",
                "preferred_source_id": _optional_text(gps_sources.get("preferred_source")),
                "preferred_source_kind": _optional_text(gps_sources.get("preferred_source_kind")),
                "policy": dict(policy),
            }

    descriptors = [
        _gps_source_descriptor(
            store,
            run_id=run_id,
            session_id=session_id,
            session_meta=session_meta,
            source_info={"source_id": stream_name, "stream_name": stream_name},
        )
        for stream_name in _gps_stream_names(store, run_id=run_id, session_id=session_id, session_meta=session_meta)
    ]
    descriptors = [descriptor for descriptor in descriptors if descriptor is not None]
    if not descriptors:
        primary = _gps_source_descriptor(
            store,
            run_id=run_id,
            session_id=session_id,
            session_meta=session_meta,
            source_info={"source_id": "primary", "stream_name": "primary"},
        )
        if primary is not None:
            descriptors.append(primary)
    return descriptors, {
        "method": "legacy_heuristic",
        "preferred_source_id": None,
        "preferred_source_kind": None,
        "policy": {"preferred_source": "legacy_heuristic"},
    }


def _gps_source_descriptor(
    store: ArtifactStore,
    *,
    run_id: str,
    session_id: str,
    session_meta: Mapping[str, Any],
    source_info: Mapping[str, Any],
) -> dict[str, Any] | None:
    source_id = _first_text(source_info.get("source_id"), source_info.get("stream_name"))
    if source_id is None:
        return None
    stream_name = _first_text(source_info.get("stream_name"), source_id) or source_id
    if source_id == "primary" or stream_name == "primary":
        return {
            "source_id": source_id,
            "stream_name": "primary",
            "metadata": _merge_metadata(session_meta, source_info),
            "source_info": dict(source_info),
            "dataframe_path": store.path_session_df(run_id, session_id),
        }

    stream_meta = _gps_stream_metadata(store, run_id=run_id, session_id=session_id, stream_name=stream_name, session_meta=session_meta)
    return {
        "source_id": source_id,
        "stream_name": stream_name,
        "metadata": _merge_metadata(stream_meta, source_info),
        "source_info": dict(source_info),
        "dataframe_path": store.path_session_stream_df(run_id, session_id, stream_name),
    }


def _gps_stream_metadata(
    store: ArtifactStore,
    *,
    run_id: str,
    session_id: str,
    stream_name: str,
    session_meta: Mapping[str, Any],
) -> dict[str, Any]:
    streams_meta = session_meta.get("streams") if isinstance(session_meta.get("streams"), Mapping) else {}
    secondary_streams = session_meta.get("secondary_streams") if isinstance(session_meta.get("secondary_streams"), Mapping) else {}
    stream_meta = _read_json_object(store.path_session_stream_meta(run_id, session_id, stream_name)) or {}
    raw_stream_meta = streams_meta.get(stream_name) if isinstance(streams_meta, Mapping) else None
    raw_secondary_meta = secondary_streams.get(stream_name) if isinstance(secondary_streams, Mapping) else None
    return _merge_metadata(
        raw_stream_meta if isinstance(raw_stream_meta, Mapping) else {},
        raw_secondary_meta if isinstance(raw_secondary_meta, Mapping) else {},
        stream_meta,
    )


def _merge_metadata(*values: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for value in values:
        if not isinstance(value, Mapping):
            continue
        for key, raw in value.items():
            out[str(key)] = raw
    return out


def _preferred_gps_source(sources: list[dict[str, Any]], source_selection: Mapping[str, Any]) -> dict[str, Any]:
    preferred_source_id = _optional_text(source_selection.get("preferred_source_id"))
    if preferred_source_id:
        for source in sources:
            if preferred_source_id in {source.get("source_id"), source.get("stream_name")}:
                return source
    preferred_source_kind = _optional_text(source_selection.get("preferred_source_kind"))
    if preferred_source_kind:
        matching_kind = [source for source in sources if source.get("kind") == preferred_source_kind]
        if matching_kind:
            return max(matching_kind, key=lambda source: (float(source.get("_coverage_ratio") or 0.0), int(source.get("point_count") or 0)))
    return max(
        sources,
        key=lambda source: (
            float(source.get("_coverage_ratio") or 0.0),
            int(source.get("point_count") or 0),
        ),
    )


def _preferred_gps_point_candidate(
    candidates: list[dict[str, Any]],
    source_selection: Mapping[str, Any],
    *,
    requested_source_id: str | None,
) -> dict[str, Any]:
    if requested_source_id:
        for candidate in candidates:
            source = candidate.get("source") if isinstance(candidate.get("source"), Mapping) else {}
            if requested_source_id in {source.get("source_id"), source.get("stream_name")}:
                return candidate
    preferred_source_id = _optional_text(source_selection.get("preferred_source_id"))
    if preferred_source_id:
        for candidate in candidates:
            source = candidate.get("source") if isinstance(candidate.get("source"), Mapping) else {}
            if preferred_source_id in {source.get("source_id"), source.get("stream_name")}:
                return candidate
    preferred_source_kind = _optional_text(source_selection.get("preferred_source_kind"))
    if preferred_source_kind:
        matching_kind = [
            candidate
            for candidate in candidates
            if isinstance(candidate.get("source"), Mapping)
            and candidate["source"].get("kind") == preferred_source_kind
        ]
        if matching_kind:
            return max(
                matching_kind,
                key=lambda candidate: (
                    int(candidate["sampling"].get("source_points") or 0),
                    int(candidate["sampling"].get("returned_points") or 0),
                ),
            )
    return max(
        candidates,
        key=lambda candidate: (
            int(candidate["sampling"].get("source_points") or 0),
            int(candidate["sampling"].get("returned_points") or 0),
        ),
    )


def _gps_columns(metadata: Mapping[str, Any], known_columns: set[str] | None) -> tuple[str | None, str | None, str | None]:
    position_columns = metadata.get("position_columns") if isinstance(metadata.get("position_columns"), Mapping) else {}
    latitude = _known_column(_first_text(position_columns.get("latitude"), metadata.get("latitude_column")), known_columns)
    longitude = _known_column(_first_text(position_columns.get("longitude"), metadata.get("longitude_column")), known_columns)
    elevation = _known_column(_first_text(metadata.get("elevation_column"), position_columns.get("elevation")), known_columns)
    if latitude and longitude:
        if elevation is None:
            resolved = resolve_gps_columns(metadata, known_columns=known_columns)
            if resolved is not None:
                elevation = resolved.altitude
        if elevation is None:
            elevation = _matching_gps_elevation_column(metadata, known_columns)
        return latitude, longitude, elevation

    resolved = resolve_gps_columns(metadata, known_columns=known_columns)
    if resolved is not None:
        return resolved.latitude, resolved.longitude, resolved.altitude

    column_info: dict[str, Mapping[str, Any]] = {}
    for key in ("channel_info", "signals"):
        raw = metadata.get(key)
        if isinstance(raw, Mapping):
            column_info.update(
                {
                    str(column): info if isinstance(info, Mapping) else {}
                    for column, info in raw.items()
                }
            )
    if known_columns is not None:
        for column in known_columns:
            column_info.setdefault(column, {})

    latitude = _first_matching_column(column_info, known_columns, _is_latitude_column)
    longitude = _first_matching_column(column_info, known_columns, _is_longitude_column)
    elevation = _first_matching_column(column_info, known_columns, _is_elevation_column)
    return latitude, longitude, elevation


def _matching_gps_elevation_column(metadata: Mapping[str, Any], known_columns: set[str] | None) -> str | None:
    column_info: dict[str, Mapping[str, Any]] = {}
    for key in ("channel_info", "signals"):
        raw = metadata.get(key)
        if isinstance(raw, Mapping):
            column_info.update(
                {
                    str(column): info if isinstance(info, Mapping) else {}
                    for column, info in raw.items()
                }
            )
    if known_columns is not None:
        for column in known_columns:
            column_info.setdefault(column, {})
    return _first_matching_column(column_info, known_columns, _is_elevation_column)


def _known_column(value: str | None, known_columns: set[str] | None) -> str | None:
    if value is None:
        return None
    if known_columns is not None and value not in known_columns:
        return None
    return value


def _first_matching_column(
    column_info: Mapping[str, Mapping[str, Any]],
    known_columns: set[str] | None,
    predicate: Any,
) -> str | None:
    candidates = []
    for column, info in column_info.items():
        if known_columns is not None and column not in known_columns:
            continue
        if predicate(column, info):
            candidates.append(column)
    if not candidates:
        return None
    return sorted(candidates, key=_gps_column_sort_key)[0]


def _gps_column_sort_key(value: str) -> tuple[int, str]:
    lower = value.lower()
    if "gps_logger" in lower:
        return (0, lower)
    if "gps_fit" in lower:
        return (2, lower)
    return (1, lower)


def _is_latitude_column(column: str, info: Mapping[str, Any]) -> bool:
    text = _column_semantic_text(column, info)
    return "latitude" in text or " lat " in f" {text} " or "_lat" in text


def _is_longitude_column(column: str, info: Mapping[str, Any]) -> bool:
    text = _column_semantic_text(column, info)
    return "longitude" in text or " lon " in f" {text} " or "_lon" in text


def _is_elevation_column(column: str, info: Mapping[str, Any]) -> bool:
    text = _column_semantic_text(column, info)
    return "altitude" in text or "elevation" in text


def _column_semantic_text(column: str, info: Mapping[str, Any]) -> str:
    parts = [column]
    for key in ("role", "quantity", "domain", "sensor", "origin", "display_name", "processing_role"):
        value = info.get(key)
        if value is not None:
            parts.append(str(value))
    return " ".join(parts).replace("-", "_").lower()


def _gps_source_kind(
    source_id: str,
    metadata: Mapping[str, Any],
    *,
    source_info: Mapping[str, Any],
    latitude_col: str,
) -> str:
    explicit = _first_text(source_info.get("kind"), source_info.get("source_kind"), metadata.get("source_kind"))
    if explicit in {"logger_sensor", "fit_enrichment", "imported_route", "unknown"}:
        return explicit
    text_parts = [source_id, latitude_col]
    for key in ("source_kind", "source", "sensor", "filename", "fit_filename"):
        value = metadata.get(key)
        if value is not None:
            text_parts.append(str(value))
    text = " ".join(text_parts).lower()
    if "fit" in text:
        return "fit_enrichment"
    if "gps" in text:
        return "logger_sensor"
    return "unknown"


def _gps_timebase(metadata: Mapping[str, Any]) -> str:
    value = _first_text(metadata.get("timebase"), metadata.get("kind"))
    if value in {"uniform", "intermittent"}:
        return value
    return "unknown"


def _gps_quality_columns(metadata: Mapping[str, Any], source_info: Mapping[str, Any]) -> dict[str, str]:
    raw = source_info.get("quality_columns")
    if not isinstance(raw, Mapping):
        raw = metadata.get("quality_columns")
    if not isinstance(raw, Mapping):
        return {}
    return {str(key): str(value) for key, value in raw.items() if value is not None}


def _gps_route_reconstruction(metadata: Mapping[str, Any], source_info: Mapping[str, Any]) -> dict[str, Any]:
    raw = source_info.get("route_reconstruction")
    if not isinstance(raw, Mapping):
        raw = metadata.get("route_reconstruction")
    return dict(raw) if isinstance(raw, Mapping) else {}


def _gps_quality_summary(metadata: Mapping[str, Any], source_info: Mapping[str, Any]) -> dict[str, Any]:
    route = _gps_route_reconstruction(metadata, source_info)
    out: dict[str, Any] = {}
    for source_key, public_key in (
        ("valid_filter_applied", "valid_filter_applied"),
        ("dedupe_method", "dedupe_method"),
        ("cached_async_snapshots", "cached_async_snapshots"),
        ("duplicate_snapshot_rows_removed", "duplicate_snapshot_rows_removed"),
        ("age_ms_median", "age_ms_median"),
        ("age_ms_max", "age_ms_max"),
        ("gap_s_median", "route_gap_s_median"),
        ("gap_s_max", "route_gap_s_max"),
    ):
        value = route.get(source_key)
        if value is not None:
            out[public_key] = value
    for key in ("valid_coverage_ratio", "fresh_coverage_ratio"):
        value = source_info.get(key, metadata.get(key))
        if value is not None:
            out[key] = value
    return out


def _gps_coverage_ratio(times: list[float], session_duration_s: float, *, gap_threshold_s: float) -> float:
    if session_duration_s <= 0 or not times:
        return 0.0
    if len(times) == 1:
        return min(1.0, gap_threshold_s / session_duration_s)
    gaps = [b - a for a, b in zip(times, times[1:]) if b > a]
    if not gaps:
        return 0.0
    covered_s = sum(min(gap, gap_threshold_s) for gap in gaps)
    return min(1.0, max(0.0, covered_s / session_duration_s))


def _session_duration_s(session_manifest: Mapping[str, Any], *, dataframe_path: Path) -> float:
    start_s, end_s = _session_time_bounds(session_manifest, dataframe_path=dataframe_path)
    return _duration_from_bounds(start_s, end_s)


def _session_time_bounds(
    session_manifest: Mapping[str, Any],
    *,
    dataframe_path: Path,
) -> tuple[float | None, float | None]:
    summary = session_manifest.get("summary")
    if isinstance(summary, Mapping):
        start = _number_or_none(summary.get("t_start_s"))
        end = _number_or_none(summary.get("t_end_s"))
        if start is not None and end is not None and end >= start:
            return float(start), float(end)

    try:
        df = pd.read_parquet(dataframe_path, columns=["time_s"])
    except Exception:
        return None, None
    if "time_s" not in df.columns or df.empty:
        return None, None
    times = pd.to_numeric(df["time_s"], errors="coerce").dropna()
    if times.empty:
        return None, None
    return float(times.min()), float(times.max())


def _duration_from_bounds(start_s: float | None, end_s: float | None) -> float:
    if start_s is None or end_s is None or end_s < start_s:
        return 0.0
    return float(end_s - start_s)


def _normalized_max_points(value: int | None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return DEFAULT_GPS_POINTS_MAX_POINTS
    return max(2, min(25_000, value))


def _normalized_time_window(
    window: Mapping[str, Any] | None,
    *,
    default_range: tuple[float | None, float | None],
) -> tuple[float | None, float | None]:
    if not isinstance(window, Mapping):
        return default_range
    start_s = _number_or_none(window.get("start_s"))
    end_s = _number_or_none(window.get("end_s"))
    if start_s is not None and end_s is not None and end_s < start_s:
        start_s, end_s = end_s, start_s
    return start_s, end_s


def _sampling_window(window_range: tuple[float | None, float | None]) -> dict[str, Any]:
    start_s, end_s = window_range
    return {
        "start_s": start_s,
        "end_s": end_s,
    }


def _required_text(value: Any, *, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise InvalidRequestError(f"Missing non-empty {field_name!r}.")
    return text


def _available_signals(
    store: ArtifactStore,
    *,
    run_id: str,
    session_id: str,
    session_meta: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return registry-defined selectable signals from primary and secondary streams.

    Column names are intentionally scoped to their materialised stream.  This
    catalog is discovery-only for now: the v1 time-series endpoint continues
    to serve the primary dataframe until its multi-stream response contract is
    implemented.
    """
    out: list[dict[str, Any]] = []
    _append_stream_signals(
        out,
        metadata=session_meta,
        dataframe_path=store.path_session_df(run_id, session_id),
        stream_name="primary",
        stream_kind="primary",
    )

    secondary = session_meta.get("secondary_streams")
    if not isinstance(secondary, Mapping):
        return sorted(out, key=_signal_sort_key)
    for raw_name, raw_metadata in secondary.items():
        stream_name = _optional_text(raw_name)
        if stream_name is None or not isinstance(raw_metadata, Mapping):
            continue
        dataframe_path = store.path_session_stream_df(run_id, session_id, stream_name)
        if not dataframe_path.exists():
            continue
        disk_metadata = _read_json_object(
            store.path_session_stream_meta(run_id, session_id, stream_name)
        ) or {}
        metadata = _merge_metadata(raw_metadata, disk_metadata)
        _append_stream_signals(
            out,
            metadata=metadata,
            dataframe_path=dataframe_path,
            stream_name=stream_name,
            stream_kind=_optional_text(metadata.get("kind")) or "secondary",
        )
    return sorted(out, key=_signal_sort_key)


def _append_stream_signals(
    out: list[dict[str, Any]],
    *,
    metadata: Mapping[str, Any],
    dataframe_path: Path,
    stream_name: str,
    stream_kind: str,
) -> None:
    signals = metadata.get("signals")
    if not isinstance(signals, Mapping):
        return
    known_columns = _parquet_columns(dataframe_path)
    time_column = _stream_time_column(metadata, known_columns)
    if time_column is None:
        return
    for column, raw_info in signals.items():
        column_text = str(column)
        if known_columns is not None and column_text not in known_columns:
            continue
        if not isinstance(raw_info, Mapping):
            continue
        info = {str(k): v for k, v in dict(raw_info).items()}
        if str(info.get("kind") or "").strip().lower() == "qc":
            continue
        if bool(info.get("semantic_selection_excluded")):
            continue

        signal = {
            "signal_id": _signal_id(column_text, info),
            "column": column_text,
            "display_name": _signal_display_name(column_text, info),
            "stream_name": stream_name,
            "stream_kind": stream_kind,
            "time_column": time_column,
        }
        for key in (
            "end",
            "domain",
            "quantity",
            "unit",
            "processing_role",
            "kind",
            "sensor",
            "motion_source_id",
            "origin",
        ):
            value = info.get(key)
            if value is not None:
                signal[key] = value
        derivation = info.get("derivation")
        if isinstance(derivation, Mapping):
            signal["derivation"] = {str(k): v for k, v in dict(derivation).items()}
        out.append(signal)


def _stream_time_column(
    metadata: Mapping[str, Any],
    known_columns: set[str] | None,
) -> str | None:
    for key in ("time_col", "time_column", "primary_time_column"):
        candidate = _optional_text(metadata.get(key))
        if candidate and (known_columns is None or candidate in known_columns):
            return candidate
    if known_columns is None or "time_s" in known_columns:
        return "time_s"
    return None


def _signal_sort_key(signal: Mapping[str, Any]) -> tuple[str, str]:
    return (
        str(signal.get("stream_name") or "").lower(),
        str(signal.get("column") or "").lower(),
    )


def _event_summary(
    store: ArtifactStore,
    *,
    run_id: str,
    session_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    event_type_dirs = list_event_types(store, run_id, session_id)
    total_count = 0
    by_type: dict[str, int] = {}

    for event_type in event_type_dirs:
        path = store.path_events_df(run_id, session_id, event_type)
        try:
            df = pd.read_parquet(path)
        except Exception:
            continue
        total_count += int(len(df))
        if "schema_id" in df.columns:
            counts = df["schema_id"].astype(str).value_counts(dropna=False)
            for key, value in counts.items():
                by_type[str(key)] = by_type.get(str(key), 0) + int(value)
        else:
            by_type[str(event_type)] = by_type.get(str(event_type), 0) + int(len(df))

    schema_ids = sorted(set(event_type_dirs))
    schema_id = schema_ids[0] if len(schema_ids) == 1 else None
    event_schema = {
        "schema_id": schema_id,
        "schema_ids": schema_ids,
        "display_name": _display_name_from_id(schema_id) if schema_id else None,
    }
    return {"total_count": total_count, "by_type": by_type}, event_schema


def _metric_summary(
    store: ArtifactStore,
    *,
    run_id: str,
    session_id: str,
) -> dict[str, Any]:
    schema_ids = list_metric_event_types(store, run_id, session_id)
    metric_columns: set[str] = set()
    event_ids: set[str] = set()
    row_count = 0

    for schema_id in schema_ids:
        path = store.path_metrics_df(run_id, session_id, schema_id)
        try:
            df = pd.read_parquet(path)
        except Exception:
            continue
        row_count += int(len(df))
        metric_columns.update(str(col) for col in df.columns if str(col) not in _METRIC_ID_COLUMNS)
        if "event_id" in df.columns:
            event_ids.update(str(value) for value in df["event_id"].dropna().unique())

    return {
        "metric_count": len(metric_columns),
        "metric_columns": sorted(metric_columns),
        "event_count_with_metrics": len(event_ids) if event_ids else row_count,
        "schema_ids": sorted(set(schema_ids)),
    }


_METRIC_ID_COLUMNS = {
    "session_id",
    "event_id",
    "schema_id",
    "schema_version",
    "event_name",
    "signal",
    "signal_col",
    "signals",
    "start_idx",
    "end_idx",
    "start_time_s",
    "end_time_s",
    "trigger_idx",
    "trigger_time_s",
    "trigger_datetime",
    "detector_version",
    "params_hash",
    "qc_flags",
    "score",
    "meta",
}


def _note_summary(
    store: ArtifactStore,
    *,
    run_id: str,
    session_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = store.path_session_notes(run_id, session_id)
    base = {
        "status": "missing",
        "has_note": False,
        "draft": False,
        "template_id": None,
        "template_version": None,
    }
    if not path.exists():
        return base, {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        status = dict(base)
        status.update(
            {
                "status": "missing",
                "has_note": True,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        return status, {}

    if not isinstance(data, Mapping) or str(data.get("schema") or "") != "bodaqs.session_notes.document":
        status = dict(base)
        status.update({"status": "missing", "has_note": True, "error": "invalid_note_document"})
        return status, {}

    values = data.get("values") if isinstance(data.get("values"), Mapping) else {}
    custom_values = data.get("custom_values") if isinstance(data.get("custom_values"), Mapping) else {}
    draft = bool(data.get("draft", False))
    status = {
        "status": "draft" if draft else "edited",
        "has_note": True,
        "draft": draft,
        "template_id": _optional_text(data.get("template_id")),
        "template_version": _optional_text(data.get("template_version")),
    }
    projected = {}
    for field_id in ("bike", "rider"):
        value = values.get(field_id, custom_values.get(field_id))
        if value is not None:
            projected[field_id] = value
    return status, projected


def _video_summary(
    store: ArtifactStore,
    *,
    run_id: str,
    session_id: str,
) -> dict[str, Any]:
    base = {
        "present": False,
        "attachment_count": 0,
        "enabled_count": 0,
        "warnings": [],
    }
    path = store.path_session_videos(run_id, session_id)
    if not path.exists():
        return base

    data = _read_json_object(path)
    if data is None:
        return {
            **base,
            "present": True,
            "warnings": ["video_attachments_unreadable"],
        }

    attachments = data.get("attachments")
    if not isinstance(attachments, list):
        return {
            **base,
            "present": True,
            "warnings": ["video_attachments_invalid"],
        }

    attachment_count = sum(1 for item in attachments if isinstance(item, Mapping))
    enabled_count = sum(1 for item in attachments if isinstance(item, Mapping) and item.get("enabled") is not False)
    return {
        "present": attachment_count > 0,
        "attachment_count": attachment_count,
        "enabled_count": enabled_count,
        "warnings": [],
    }


def _timestamp_summary(
    run_manifest: Mapping[str, Any],
    session_meta: Mapping[str, Any],
) -> dict[str, Any]:
    started = _optional_text(session_meta.get("t0_datetime"))
    processed_at = _optional_text(run_manifest.get("created_at"))
    return {
        "started_at_utc": _utc_timestamp_or_none(started),
        "started_at_local": started,
        "processed_at": processed_at,
        "imported_at": processed_at,
    }


def _qc_summary(
    session_meta: Mapping[str, Any],
    session_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    qc = session_meta.get("qc")
    if not isinstance(qc, Mapping):
        summary = session_manifest.get("summary")
        qc = summary.get("qc") if isinstance(summary, Mapping) else {}
    if not isinstance(qc, Mapping):
        qc = {}

    warnings = qc.get("warnings")
    errors = qc.get("errors")
    warning_count = len(warnings) if isinstance(warnings, list) else 0
    error_count = len(errors) if isinstance(errors, list) else 0
    status = "alert" if error_count else ("warning" if warning_count else "ok")
    return {
        "status": status,
        "warning_count": warning_count,
        "error_count": error_count,
    }


def _session_summary(
    session_manifest: Mapping[str, Any],
    *,
    gps_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    summary = session_manifest.get("summary")
    summary = summary if isinstance(summary, Mapping) else {}
    out = dict(summary)
    start_s = _number_or_none(summary.get("t_start_s"))
    end_s = _number_or_none(summary.get("t_end_s"))
    duration_s = _number_or_none(summary.get("duration_s"))
    if duration_s is None and start_s is not None and end_s is not None and end_s >= start_s:
        duration_s = end_s - start_s
    if duration_s is not None:
        out.setdefault("duration_s", duration_s)
        out.setdefault("duration_min", duration_s / 60.0)
    distance_m = _first_number(
        summary.get("distance_m"),
        summary.get("gps_distance_m"),
        summary.get("route_distance_m"),
    )
    gps_distance_m = _gps_summary_distance_m(gps_summary or {})
    if (distance_m is None or distance_m <= 0) and gps_distance_m is not None:
        distance_m = gps_distance_m
    if distance_m is not None:
        current_distance_m = _number_or_none(out.get("distance_m"))
        current_distance_km = _number_or_none(out.get("distance_km"))
        if current_distance_m is None or current_distance_m <= 0:
            out["distance_m"] = distance_m
        if current_distance_km is None or current_distance_km <= 0:
            out["distance_km"] = distance_m / 1000.0
    return out


def _gps_summary_distance_m(gps_summary: Mapping[str, Any]) -> float | None:
    sources = gps_summary.get("sources")
    if not isinstance(sources, list):
        return None
    preferred_source_id = _optional_text(
        gps_summary.get("preferred_source_id") or gps_summary.get("preferred_source")
    )
    ordered_sources = [
        source
        for source in sources
        if isinstance(source, Mapping)
        and preferred_source_id
        and _optional_text(source.get("source_id")) == preferred_source_id
    ]
    ordered_sources.extend(
        source for source in sources if isinstance(source, Mapping) and source not in ordered_sources
    )
    for source in ordered_sources:
        distance_m = _first_number(source.get("route_distance_m"))
        if distance_m is not None and distance_m > 0:
            return distance_m
    return None


def _gps_route_distance_m(latitudes: list[Any], longitudes: list[Any]) -> float | None:
    points: list[tuple[float, float]] = []
    for lat, lon in zip(latitudes, longitudes):
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            continue
        if math.isfinite(lat_f) and math.isfinite(lon_f):
            points.append((lat_f, lon_f))
    if len(points) < 2:
        return None
    total = 0.0
    for (lat1, lon1), (lat2, lon2) in zip(points, points[1:]):
        total += _haversine_m(lat1, lon1, lat2, lon2)
    return total


def _gps_position_bbox(latitudes: list[Any], longitudes: list[Any]) -> dict[str, float] | None:
    points: list[tuple[float, float]] = []
    for lat, lon in zip(latitudes, longitudes):
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            continue
        if (
            math.isfinite(lat_f)
            and math.isfinite(lon_f)
            and -90.0 <= lat_f <= 90.0
            and -180.0 <= lon_f <= 180.0
        ):
            points.append((lat_f, lon_f))
    if not points:
        return None
    lat_values = [lat for lat, _ in points]
    lon_values = [lon for _, lon in points]
    return {
        "min_longitude": min(lon_values),
        "min_latitude": min(lat_values),
        "max_longitude": max(lon_values),
        "max_latitude": max(lat_values),
    }


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    a = min(1.0, max(0.0, a))
    return 2.0 * earth_radius_m * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def _provenance_summary(
    *,
    run_manifest: Mapping[str, Any],
    session_manifest: Mapping[str, Any],
    session_id: str,
) -> dict[str, Any]:
    source = session_manifest.get("source")
    source = source if isinstance(source, Mapping) else {}
    pipeline_config = run_manifest.get("pipeline_config")
    pipeline_config = pipeline_config if isinstance(pipeline_config, Mapping) else {}
    import_source = pipeline_config.get("import_source")
    import_source = import_source if isinstance(import_source, Mapping) else {}
    archive_import = pipeline_config.get("archive_import")
    archive_import = archive_import if isinstance(archive_import, Mapping) else {}
    archive_sessions = archive_import.get("sessions")
    archive_session = archive_sessions.get(session_id) if isinstance(archive_sessions, Mapping) else {}
    archive_session = archive_session if isinstance(archive_session, Mapping) else {}
    remote_source = source.get("remote_source")
    remote_source = remote_source if isinstance(remote_source, Mapping) else {}
    source_context = source.get("source_context") if isinstance(source.get("source_context"), Mapping) else {}

    out = {
        "source_type": _first_text(source.get("import_source_type"), import_source.get("source_type")),
        "source_id": _first_text(source.get("import_source_id"), import_source.get("source_id")),
        "logger_id": _first_text(remote_source.get("logger_id"), source.get("logger_id")),
        "archive_name": _optional_text(source.get("original_archive_filename")),
        "processing_key": _first_text(source.get("processing_key"), archive_import.get("processing_key")),
        "preprocessing_profile": _first_text(
            source.get("preprocess_profile_id"),
            archive_session.get("preprocess_profile_id"),
            archive_session.get("preprocess_profile_path"),
            archive_import.get("preprocess_profile_path"),
        ),
        "preprocess_profile_path": _first_text(
            source.get("preprocess_profile_path"),
            archive_session.get("preprocess_profile_path"),
            archive_import.get("preprocess_profile_path"),
        ),
        "firmware_version": _first_text(
            source.get("firmware_version"),
            source_context.get("firmware_version"),
            archive_session.get("firmware_version"),
        ),
        "bike_profile_id": _first_text(
            source.get("bike_profile_id"),
            source_context.get("bike_profile_id"),
            archive_session.get("bike_profile_id"),
        ),
        "bike_profile_path": _first_text(
            source.get("bike_profile_path"),
            source_context.get("bike_profile_path"),
            archive_session.get("bike_profile_path"),
            archive_import.get("bike_profile_path"),
        ),
    }
    return {key: value for key, value in out.items() if value is not None}


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return dict(value) if isinstance(value, Mapping) else None


def _has_runs(path: Path) -> bool:
    runs_dir = path / RUNS_DIRNAME
    if not runs_dir.is_dir():
        return False
    return any(child.is_dir() for child in runs_dir.iterdir())


def _metadata_text(definition: Mapping[str, Any] | None, key: str) -> str | None:
    if not isinstance(definition, Mapping):
        return None
    value = definition.get(key)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _display_name_from_id(value: str) -> str:
    words = str(value).replace("_", " ").replace("-", " ").strip()
    return words.title() if words else "Library"


def _parquet_columns(path: Path) -> set[str] | None:
    if not path.exists():
        return None
    try:
        import pyarrow.parquet as pq

        return {str(name) for name in pq.read_schema(path).names}
    except Exception:
        try:
            return {str(name) for name in pd.read_parquet(path).columns}
        except Exception:
            return None


def _signal_id(column: str, info: Mapping[str, Any]) -> str:
    explicit = _optional_text(info.get("signal_id"))
    if explicit:
        return explicit
    semantic_parts = [
        _optional_text(info.get("end")),
        _optional_text(info.get("domain")),
        _optional_text(info.get("quantity")),
        _optional_text(info.get("unit")),
    ]
    semantic = "-".join(part for part in semantic_parts if part)
    return derive_object_id(semantic or column, fallback="signal")


def _signal_display_name(column: str, info: Mapping[str, Any]) -> str:
    explicit = _optional_text(info.get("display_name"))
    if explicit:
        return explicit
    semantic_parts = [
        _optional_text(info.get("end")),
        _optional_text(info.get("domain")),
        _optional_text(info.get("quantity")),
    ]
    text = " ".join(part for part in semantic_parts if part)
    if text:
        return text.replace("_", " ").title()
    return str(column).split("[", 1)[0].replace("_", " ").strip().title() or str(column)


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _optional_text(value)
        if text is not None:
            return text
    return None


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _number_or_none(value)
        if number is not None:
            return number
    return None


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _utc_timestamp_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if text.endswith("Z") or "+00:00" in text:
        return text
    return None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
