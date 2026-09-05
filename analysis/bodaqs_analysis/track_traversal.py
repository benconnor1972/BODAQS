"""Sequence-aware matching of a session GPS path to a directed track."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any, Mapping, Optional

import numpy as np


EARTH_RADIUS_M = 6_371_000.0

DEFAULT_TRACK_TRAVERSAL_MATCH_CONFIG: dict[str, Any] = {
    "maximum_lateral_distance_m": 8.0,
    "maximum_match_gap_s": 5.0,
    "endpoint_tolerance_m": 15.0,
    "minimum_track_coverage_ratio": 0.85,
    "minimum_forward_fraction": 0.60,
    "projection_candidate_count": 8,
    "projection_station_separation_m": 5.0,
    "transition_distance_weight": 0.5,
    "heading_alignment_weight": 2.0,
}


@dataclass(frozen=True)
class TrackTraversalMatch:
    time_s: np.ndarray
    station_m: np.ndarray
    lateral_distance_m: np.ndarray
    matched: np.ndarray
    track_length_m: float
    traversals: list[dict[str, Any]]
    diagnostics: dict[str, Any]


def normalize_track_traversal_match_config(
    config: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return normalized sequence-matching parameters."""

    out = copy.deepcopy(DEFAULT_TRACK_TRAVERSAL_MATCH_CONFIG)
    if config is None:
        return out
    if not isinstance(config, Mapping):
        raise ValueError("track traversal match config must be an object or null")
    unknown = sorted(set(config) - set(out))
    if unknown:
        raise ValueError(f"Unsupported track traversal match config fields: {', '.join(unknown)}")
    out.update(config)
    for field in (
        "maximum_lateral_distance_m",
        "maximum_match_gap_s",
        "endpoint_tolerance_m",
        "projection_station_separation_m",
    ):
        if not _positive_number(out.get(field)):
            raise ValueError(f"track traversal match config {field!r} must be greater than zero")
    for field in ("minimum_track_coverage_ratio", "minimum_forward_fraction"):
        if not _unit_interval(out.get(field)) or float(out[field]) <= 0.0:
            raise ValueError(f"track traversal match config {field!r} must lie in (0, 1]")
    candidate_count = out.get("projection_candidate_count")
    if isinstance(candidate_count, bool) or not isinstance(candidate_count, (int, np.integer)):
        raise ValueError("track traversal match config 'projection_candidate_count' must be an integer")
    if int(candidate_count) < 1:
        raise ValueError("track traversal match config 'projection_candidate_count' must be at least 1")
    for field in ("transition_distance_weight", "heading_alignment_weight"):
        if not _nonnegative_number(out.get(field)):
            raise ValueError(f"track traversal match config {field!r} must be non-negative")
    return out


def match_track_traversals(
    time_s: np.ndarray,
    latitude_deg: np.ndarray,
    longitude_deg: np.ndarray,
    track: Mapping[str, Any],
    config: Optional[Mapping[str, Any]] = None,
) -> TrackTraversalMatch:
    """Project an ordered GPS path onto a track and identify forward traversals.

    Multiple projection candidates are retained at crossings and close parallel
    sections. A dynamic-programming pass then prefers a station sequence whose
    movement is consistent with the observed GPS movement, avoiding isolated
    nearest-segment jumps between distant parts of the track.
    """

    cfg = normalize_track_traversal_match_config(config)
    time = np.asarray(time_s, dtype=float)
    latitude = np.asarray(latitude_deg, dtype=float)
    longitude = np.asarray(longitude_deg, dtype=float)
    if not (time.shape == latitude.shape == longitude.shape):
        raise ValueError("track traversal time, latitude, and longitude arrays must have equal shape")

    valid = np.isfinite(time) & np.isfinite(latitude) & np.isfinite(longitude)
    order = np.flatnonzero(valid)
    if order.size:
        order = order[np.argsort(time[order], kind="stable")]
        order = order[np.r_[True, np.diff(time[order]) > 1.0e-9]]
    time = time[order]
    latitude = latitude[order]
    longitude = longitude[order]

    track_rows = _track_coordinates(track)
    declared_length_m = _track_declared_length(track)
    if len(track_rows) < 2 or time.size < 2:
        return _empty_match(time, declared_length_m, "insufficient_track_or_gps_points", cfg)

    all_latitude = np.r_[latitude, np.asarray([row[1] for row in track_rows], dtype=float)]
    latitude_origin = float(np.nanmedian(np.radians(all_latitude)))
    longitude_origin = math.radians(float(track_rows[0][0]))
    latitude_start = math.radians(float(track_rows[0][1]))

    gps_x, gps_y = _project_positions(
        latitude,
        longitude,
        latitude_origin=latitude_origin,
        longitude_origin=longitude_origin,
        latitude_start=latitude_start,
    )
    track_longitude = np.asarray([row[0] for row in track_rows], dtype=float)
    track_latitude = np.asarray([row[1] for row in track_rows], dtype=float)
    track_x, track_y = _project_positions(
        track_latitude,
        track_longitude,
        latitude_origin=latitude_origin,
        longitude_origin=longitude_origin,
        latitude_start=latitude_start,
    )
    segment_dx = np.diff(track_x)
    segment_dy = np.diff(track_y)
    segment_length_sq = np.square(segment_dx) + np.square(segment_dy)
    usable_segments = segment_length_sq > 1.0e-12
    if not usable_segments.any():
        return _empty_match(time, declared_length_m, "non_positive_track_length", cfg)
    projected_stations = np.r_[0.0, np.cumsum(np.hypot(segment_dx, segment_dy))]
    projected_length_m = float(projected_stations[-1])
    track_length_m = declared_length_m if declared_length_m > 0 else projected_length_m
    station_scale = track_length_m / projected_length_m

    candidate_sets = [
        _projection_candidates(
            point_x,
            point_y,
            track_x=track_x,
            track_y=track_y,
            segment_dx=segment_dx,
            segment_dy=segment_dy,
            segment_length_sq=segment_length_sq,
            usable_segments=usable_segments,
            projected_stations=projected_stations,
            station_scale=station_scale,
            candidate_count=int(cfg["projection_candidate_count"]),
            station_separation_m=float(cfg["projection_station_separation_m"]),
        )
        for point_x, point_y in zip(gps_x, gps_y)
    ]
    station, lateral = _continuous_projection_path(
        candidate_sets,
        time=time,
        x_m=gps_x,
        y_m=gps_y,
        maximum_gap_s=float(cfg["maximum_match_gap_s"]),
        transition_weight=float(cfg["transition_distance_weight"]),
        heading_weight=float(cfg["heading_alignment_weight"]),
    )
    matched = np.isfinite(station) & np.isfinite(lateral) & (
        lateral <= float(cfg["maximum_lateral_distance_m"])
    )
    traversals = _forward_traversals(
        time,
        station,
        lateral,
        matched,
        track_length_m=track_length_m,
        config=cfg,
    )
    matched_count = int(np.count_nonzero(matched))
    diagnostics = {
        "algorithm": "sequence_aware_track_projection",
        "algorithm_version": 1,
        "effective_config": copy.deepcopy(cfg),
        "gps_point_count": int(time.size),
        "matched_gps_point_count": matched_count,
        "matched_gps_fraction": matched_count / int(time.size) if time.size else 0.0,
        "track_length_m": track_length_m,
        "forward_traversal_count": len(traversals),
    }
    return TrackTraversalMatch(
        time_s=time,
        station_m=station,
        lateral_distance_m=lateral,
        matched=matched,
        track_length_m=track_length_m,
        traversals=traversals,
        diagnostics=diagnostics,
    )


def _projection_candidates(
    point_x: float,
    point_y: float,
    *,
    track_x: np.ndarray,
    track_y: np.ndarray,
    segment_dx: np.ndarray,
    segment_dy: np.ndarray,
    segment_length_sq: np.ndarray,
    usable_segments: np.ndarray,
    projected_stations: np.ndarray,
    station_scale: float,
    candidate_count: int,
    station_separation_m: float,
) -> list[tuple[float, float, float, float]]:
    relative_x = point_x - track_x[:-1]
    relative_y = point_y - track_y[:-1]
    fraction = np.divide(
        relative_x * segment_dx + relative_y * segment_dy,
        segment_length_sq,
        out=np.zeros(segment_length_sq.shape, dtype=float),
        where=usable_segments,
    )
    fraction = np.clip(fraction, 0.0, 1.0)
    projection_x = track_x[:-1] + fraction * segment_dx
    projection_y = track_y[:-1] + fraction * segment_dy
    distance_sq = np.square(point_x - projection_x) + np.square(point_y - projection_y)
    distance_sq[~usable_segments] = np.inf
    local_minimum = np.ones(distance_sq.shape, dtype=bool)
    if distance_sq.size > 1:
        comparison_tolerance_m2 = 1.0e-6
        local_minimum[1:] &= distance_sq[1:] <= distance_sq[:-1] + comparison_tolerance_m2
        local_minimum[:-1] &= distance_sq[:-1] <= distance_sq[1:] + comparison_tolerance_m2
    candidate_indices = np.flatnonzero(local_minimum & np.isfinite(distance_sq))
    if candidate_indices.size == 0:
        candidate_indices = np.asarray([int(np.argmin(distance_sq))], dtype=int)
    candidate_indices = candidate_indices[np.argsort(distance_sq[candidate_indices], kind="stable")]

    candidates: list[tuple[float, float, float, float]] = []
    for segment_index in candidate_indices:
        segment_length = math.sqrt(float(segment_length_sq[segment_index]))
        projected_station = (
            float(projected_stations[segment_index])
            + segment_length * float(fraction[segment_index])
        ) * station_scale
        if any(abs(projected_station - existing[0]) < station_separation_m for existing in candidates):
            continue
        candidates.append(
            (
                projected_station,
                math.sqrt(float(distance_sq[segment_index])),
                float(segment_dx[segment_index]) / segment_length,
                float(segment_dy[segment_index]) / segment_length,
            )
        )
        if len(candidates) >= candidate_count:
            break
    return candidates


def _continuous_projection_path(
    candidate_sets: list[list[tuple[float, float, float, float]]],
    *,
    time: np.ndarray,
    x_m: np.ndarray,
    y_m: np.ndarray,
    maximum_gap_s: float,
    transition_weight: float,
    heading_weight: float,
) -> tuple[np.ndarray, np.ndarray]:
    station = np.full(time.shape, np.nan, dtype=float)
    lateral = np.full(time.shape, np.nan, dtype=float)
    if not candidate_sets:
        return station, lateral

    chunk_start = 0
    for index in range(1, len(candidate_sets) + 1):
        chunk_end = index == len(candidate_sets)
        if not chunk_end:
            dt = float(time[index] - time[index - 1])
            chunk_end = not np.isfinite(dt) or dt <= 0.0 or dt > maximum_gap_s
        if chunk_end:
            _solve_projection_chunk(
                candidate_sets,
                start=chunk_start,
                stop=index,
                x_m=x_m,
                y_m=y_m,
                station_out=station,
                lateral_out=lateral,
                transition_weight=transition_weight,
                heading_weight=heading_weight,
            )
            chunk_start = index
    return station, lateral


def _solve_projection_chunk(
    candidate_sets: list[list[tuple[float, float, float, float]]],
    *,
    start: int,
    stop: int,
    x_m: np.ndarray,
    y_m: np.ndarray,
    station_out: np.ndarray,
    lateral_out: np.ndarray,
    transition_weight: float,
    heading_weight: float,
) -> None:
    if stop <= start:
        return
    costs = np.asarray([candidate[1] for candidate in candidate_sets[start]], dtype=float)
    parents: list[np.ndarray] = []
    for index in range(start + 1, stop):
        previous = candidate_sets[index - 1]
        current = candidate_sets[index]
        gps_step_m = math.hypot(float(x_m[index] - x_m[index - 1]), float(y_m[index] - y_m[index - 1]))
        next_costs = np.full(len(current), np.inf, dtype=float)
        next_parents = np.zeros(len(current), dtype=int)
        for current_index, (current_station, current_lateral, unit_x, unit_y) in enumerate(current):
            transition = np.asarray(
                [
                    transition_weight * abs(abs(current_station - previous_station) - gps_step_m)
                    for previous_station, *_ in previous
                ],
                dtype=float,
            )
            alternatives = costs + transition
            parent = int(np.argmin(alternatives))
            next_parents[current_index] = parent
            if gps_step_m > 1.0e-9:
                movement_x = float(x_m[index] - x_m[index - 1]) / gps_step_m
                movement_y = float(y_m[index] - y_m[index - 1]) / gps_step_m
                heading_cost = heading_weight * gps_step_m * (
                    1.0 - max(-1.0, min(1.0, movement_x * unit_x + movement_y * unit_y))
                )
            else:
                heading_cost = 0.0
            next_costs[current_index] = float(alternatives[parent]) + current_lateral + heading_cost
        parents.append(next_parents)
        costs = next_costs

    chosen = int(np.argmin(costs))
    for index in range(stop - 1, start - 1, -1):
        station_out[index], lateral_out[index] = candidate_sets[index][chosen][:2]
        if index > start:
            chosen = int(parents[index - start - 1][chosen])


def _forward_traversals(
    time: np.ndarray,
    station: np.ndarray,
    lateral: np.ndarray,
    matched: np.ndarray,
    *,
    track_length_m: float,
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    matched_indices = np.flatnonzero(matched)
    if matched_indices.size < 2 or track_length_m <= 0.0:
        return []
    maximum_gap_s = float(config["maximum_match_gap_s"])
    split_at = np.flatnonzero(np.diff(time[matched_indices]) > maximum_gap_s) + 1
    runs = np.split(matched_indices, split_at)
    endpoint_tolerance_m = min(float(config["endpoint_tolerance_m"]), track_length_m * 0.25)
    end_zone_start_m = track_length_m - endpoint_tolerance_m
    minimum_coverage = float(config["minimum_track_coverage_ratio"])
    minimum_forward_fraction = float(config["minimum_forward_fraction"])
    traversals: list[dict[str, Any]] = []

    for run in runs:
        start_index: Optional[int] = None
        end_index: Optional[int] = None
        for point_index in run:
            point_station = float(station[point_index])
            if start_index is None:
                if point_station <= endpoint_tolerance_m:
                    start_index = int(point_index)
                continue
            if end_index is None and point_station <= endpoint_tolerance_m:
                if start_index is None or point_station < float(station[start_index]):
                    start_index = int(point_index)
                continue
            if end_index is None:
                if point_station >= end_zone_start_m:
                    end_index = int(point_index)
                continue
            if point_station >= end_zone_start_m:
                if point_station > float(station[end_index]):
                    end_index = int(point_index)
                continue
            _append_forward_traversal(
                traversals,
                start_index=start_index,
                end_index=end_index,
                time=time,
                station=station,
                lateral=lateral,
                track_length_m=track_length_m,
                minimum_coverage=minimum_coverage,
                minimum_forward_fraction=minimum_forward_fraction,
            )
            start_index = int(point_index) if point_station <= endpoint_tolerance_m else None
            end_index = None
        if start_index is not None and end_index is not None:
            _append_forward_traversal(
                traversals,
                start_index=start_index,
                end_index=end_index,
                time=time,
                station=station,
                lateral=lateral,
                track_length_m=track_length_m,
                minimum_coverage=minimum_coverage,
                minimum_forward_fraction=minimum_forward_fraction,
            )
    return traversals


def _append_forward_traversal(
    traversals: list[dict[str, Any]],
    *,
    start_index: int,
    end_index: int,
    time: np.ndarray,
    station: np.ndarray,
    lateral: np.ndarray,
    track_length_m: float,
    minimum_coverage: float,
    minimum_forward_fraction: float,
) -> None:
    if end_index <= start_index:
        return
    traversal_slice = np.arange(start_index, end_index + 1)
    traversal_station = station[traversal_slice]
    changes = np.diff(traversal_station)
    total_movement = float(np.sum(np.abs(changes)))
    forward_movement = float(np.sum(np.maximum(changes, 0.0)))
    forward_fraction = forward_movement / total_movement if total_movement > 0.0 else 0.0
    coverage_ratio = min(
        1.0,
        max(0.0, (float(np.max(traversal_station)) - float(np.min(traversal_station))) / track_length_m),
    )
    if coverage_ratio < minimum_coverage or forward_fraction < minimum_forward_fraction:
        return
    traversal_lateral = lateral[traversal_slice]
    traversals.append(
        {
            "direction": "forward",
            "start_time_s": float(time[start_index]),
            "end_time_s": float(time[end_index]),
            "duration_s": float(time[end_index] - time[start_index]),
            "start_station_m": float(station[start_index]),
            "end_station_m": float(station[end_index]),
            "coverage_ratio": coverage_ratio,
            "forward_fraction": forward_fraction,
            "matched_point_count": int(traversal_slice.size),
            "mean_lateral_distance_m": float(np.mean(traversal_lateral)),
            "maximum_lateral_distance_m": float(np.max(traversal_lateral)),
        }
    )


def _track_coordinates(track: Mapping[str, Any]) -> list[tuple[float, float]]:
    path = track.get("path") if isinstance(track.get("path"), Mapping) else {}
    rows: list[tuple[float, float]] = []
    for value in path.get("coordinates") or []:
        if not isinstance(value, (list, tuple)) or len(value) < 2:
            continue
        try:
            longitude = float(value[0])
            latitude = float(value[1])
        except (TypeError, ValueError):
            continue
        if np.isfinite(longitude) and np.isfinite(latitude):
            rows.append((longitude, latitude))
    return rows


def _track_declared_length(track: Mapping[str, Any]) -> float:
    path = track.get("path") if isinstance(track.get("path"), Mapping) else {}
    try:
        value = float(path.get("length_m"))
    except (TypeError, ValueError):
        return 0.0
    return value if np.isfinite(value) and value > 0.0 else 0.0


def _project_positions(
    latitude_deg: np.ndarray,
    longitude_deg: np.ndarray,
    *,
    latitude_origin: float,
    longitude_origin: float,
    latitude_start: float,
) -> tuple[np.ndarray, np.ndarray]:
    x_m = EARTH_RADIUS_M * (np.radians(longitude_deg) - longitude_origin) * math.cos(latitude_origin)
    y_m = EARTH_RADIUS_M * (np.radians(latitude_deg) - latitude_start)
    return x_m, y_m


def _empty_match(
    time: np.ndarray,
    track_length_m: float,
    reason: str,
    config: Mapping[str, Any],
) -> TrackTraversalMatch:
    empty = np.full(time.shape, np.nan, dtype=float)
    return TrackTraversalMatch(
        time_s=time,
        station_m=empty.copy(),
        lateral_distance_m=empty.copy(),
        matched=np.zeros(time.shape, dtype=bool),
        track_length_m=track_length_m,
        traversals=[],
        diagnostics={
            "algorithm": "sequence_aware_track_projection",
            "algorithm_version": 1,
            "effective_config": copy.deepcopy(dict(config)),
            "gps_point_count": int(time.size),
            "matched_gps_point_count": 0,
            "matched_gps_fraction": 0.0,
            "track_length_m": track_length_m,
            "forward_traversal_count": 0,
            "reason": reason,
        },
    )


def _positive_number(value: Any) -> bool:
    return _nonnegative_number(value) and float(value) > 0.0


def _nonnegative_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float, np.integer, np.floating))
        and np.isfinite(value)
        and float(value) >= 0.0
    )


def _unit_interval(value: Any) -> bool:
    return _nonnegative_number(value) and float(value) <= 1.0
