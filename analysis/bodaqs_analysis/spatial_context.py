"""Session-scoped distance-domain context metrics.

The spatial stream is deliberately derived from existing processed evidence:
GPS/FIT supplies the distance/geometry mapping, while suspension activity is
accumulated from native-rate filtered wheel displacement before spatial
aggregation.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from .gps_semantics import gps_source_kind, resolve_gps_columns
from .route_geometry import (
    DEFAULT_ROUTE_GEOMETRY_DENOISING_CONFIG,
    denoise_route_positions,
    geodesic_segment_lengths,
    local_latitude_longitude,
    local_xy,
    weighted_local_polynomial_coefficients,
)
from .signal_selectors import resolve_signal_selector
from .track_traversal import (
    DEFAULT_TRACK_TRAVERSAL_MATCH_CONFIG,
    match_track_traversals,
    normalize_track_traversal_match_config,
)


SPATIAL_CONTEXT_STREAM_NAME = "spatial_context"
SPATIAL_CONTEXT_STREAM_SCHEMA = "bodaqs.spatial_context_stream"
SPATIAL_CONTEXT_STREAM_VERSION = 1
SPATIAL_CONTEXT_ALGORITHM_VERSION = 3
ACTIVE_MASK_COLUMN = "active_mask_qc"

DEFAULT_SPATIAL_CONTEXT_TRACK_SCOPE_CONFIG: dict[str, Any] = {
    "traversal_selection": "last_forward_traversal",
    "station_regression_tolerance_m": 3.0,
    "matching": copy.deepcopy(DEFAULT_TRACK_TRAVERSAL_MATCH_CONFIG),
}

_RECORDED_DISTANCE_REVERSAL_TOLERANCE_M = 0.5


DEFAULT_SPATIAL_CONTEXT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "algorithm_version": SPATIAL_CONTEXT_ALGORITHM_VERSION,
    "distance": {
        "source_priority": ["gps_geometry"],
        "grid_interval_m": 0.5,
        "distance_model": "geodesic",
        "max_interpolation_gap_s": 5.0,
        "minimum_nominal_gps_rate_hz": 1.0,
        "minimum_gps_coverage_ratio": 0.99,
        "minimum_distance_support_fraction": 0.5,
        "maximum_implied_speed_mps": 50.0,
        "quality_action": "warn",
        "geometry_denoising": copy.deepcopy(DEFAULT_ROUTE_GEOMETRY_DENOISING_CONFIG),
    },
    "gradient": {
        "enabled": True,
        "altitude_source": "gps",
        "estimator": "local_linear_regression",
        "regression_window_m": 20.0,
        "smoothing_kernel": "centred_exponential",
        "smoothing_distance_m": 15.0,
    },
    "twistiness": {
        "enabled": True,
        "estimator": "local_polynomial",
        "geometry_window_m": 20.0,
        "polynomial_order": 2,
        "require_full_window": True,
        "minimum_source_position_observations": 3,
        "fit_weighting": "tricube",
        "horizontal_accuracy_weighting": True,
        "horizontal_accuracy_floor_m": 0.5,
        "robust_iterations": 2,
        "robust_tuning_constant": 4.685,
        "smoothing_kernel": "centred_exponential",
        "smoothing_distance_m": 7.5,
    },
    "suspension_activity": {
        "enabled": True,
        "use_preprocess_active_mask": True,
        "front_selector": {
            "end": "front",
            "quantity": "disp",
            "domain": "wheel",
            "unit": "mm",
            "processing_role": "primary_analysis",
        },
        "rear_selector": {
            "end": "rear",
            "quantity": "disp",
            "domain": "wheel",
            "unit": "mm",
            "processing_role": "primary_analysis",
        },
        "minimum_support_fraction": 0.25,
        "smoothing_kernel": "centred_exponential",
        "smoothing_distance_m": 4.0,
        "combined_method": "mean_both_required",
    },
}


@dataclass(frozen=True)
class SpatialContextResult:
    stream_df: pd.DataFrame
    stream_meta: dict[str, Any]
    qc: dict[str, Any]


@dataclass(frozen=True)
class _GpsSource:
    source_id: str
    stream_name: str
    source_kind: str
    frame: pd.DataFrame
    metadata: Mapping[str, Any]
    time_column: str
    latitude_column: str
    longitude_column: str
    altitude_column: Optional[str]
    distance_column: Optional[str]
    valid_column: Optional[str]
    fresh_column: Optional[str]
    sequence_column: Optional[str]
    horizontal_accuracy_column: Optional[str]


@dataclass(frozen=True)
class _DistanceCandidate:
    kind: str
    source: _GpsSource
    time_s: np.ndarray
    distance_m: np.ndarray
    x_m: np.ndarray
    y_m: np.ndarray
    latitude_deg: np.ndarray
    longitude_deg: np.ndarray
    altitude_m: np.ndarray
    horizontal_accuracy_m: np.ndarray
    valid_pairs: np.ndarray
    continuous_pairs: np.ndarray
    diagnostics: dict[str, Any]


def normalize_spatial_context_config(config: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Return a deep, normalized spatial-context configuration."""

    out = copy.deepcopy(DEFAULT_SPATIAL_CONTEXT_CONFIG)
    if config is None:
        return out
    if not isinstance(config, Mapping):
        raise ValueError("spatial_context config must be an object or null")
    _deep_update(out, config)
    for block_name in ("gradient", "twistiness", "suspension_activity"):
        if block_name not in config:
            out[block_name]["enabled"] = False
    if not bool(out["suspension_activity"].get("use_preprocess_active_mask", True)):
        raise ValueError(
            "spatial_context suspension_activity.use_preprocess_active_mask must be true; "
            "active_mask_qc is mandatory for all spatial metrics"
        )
    return out


def normalize_spatial_context_track_scope_config(
    config: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return normalized post-derivation track-scope configuration."""

    out = copy.deepcopy(DEFAULT_SPATIAL_CONTEXT_TRACK_SCOPE_CONFIG)
    if config is None:
        return out
    if not isinstance(config, Mapping):
        raise ValueError("spatial-context track scope config must be an object or null")
    unknown = sorted(
        set(config)
        - {"traversal_selection", "station_regression_tolerance_m", "matching"}
    )
    if unknown:
        raise ValueError(f"Unsupported spatial-context track scope fields: {', '.join(unknown)}")
    if "traversal_selection" in config:
        out["traversal_selection"] = str(config["traversal_selection"])
    selection = str(out["traversal_selection"])
    if selection not in {
        "first_forward_traversal",
        "last_forward_traversal",
        "longest_forward_traversal",
    }:
        raise ValueError(
            "spatial-context traversal_selection must be first_forward_traversal, "
            "last_forward_traversal, or longest_forward_traversal"
        )
    regression_tolerance = out.get("station_regression_tolerance_m")
    if (
        isinstance(regression_tolerance, bool)
        or not isinstance(regression_tolerance, (int, float, np.integer, np.floating))
        or not np.isfinite(regression_tolerance)
        or float(regression_tolerance) < 0.0
    ):
        raise ValueError(
            "spatial-context station_regression_tolerance_m must be finite and non-negative"
        )
    out["station_regression_tolerance_m"] = float(regression_tolerance)
    matching = config.get("matching") if "matching" in config else out["matching"]
    out["matching"] = normalize_track_traversal_match_config(matching)
    return out


def derive_spatial_context(
    session: Mapping[str, Any],
    config: Optional[Mapping[str, Any]],
) -> SpatialContextResult:
    """Derive one spatial-context stream without mutating ``session``."""

    cfg = normalize_spatial_context_config(config)
    base_meta = _base_stream_meta(cfg)
    if not bool(cfg.get("enabled", False)):
        return _empty_result(base_meta, status="disabled", warnings=[])

    primary = session.get("df")
    if not isinstance(primary, pd.DataFrame) or "time_s" not in primary.columns:
        return _empty_result(
            base_meta,
            status="unavailable",
            warnings=["spatial_context_primary_time_unavailable"],
        )

    primary_time = _numeric(primary["time_s"])
    finite_primary_time = primary_time[np.isfinite(primary_time)]
    if finite_primary_time.size < 2:
        return _empty_result(
            base_meta,
            status="unavailable",
            warnings=["spatial_context_primary_time_insufficient"],
        )
    session_bounds = (float(np.min(finite_primary_time)), float(np.max(finite_primary_time)))

    distance_cfg = cfg["distance"]
    sources = _gps_sources(session)
    candidate, evaluations = _select_distance_candidate(
        sources,
        session=session,
        session_bounds=session_bounds,
        config=distance_cfg,
    )
    base_meta["distance_source"] = {
        "source_priority": list(distance_cfg["source_priority"]),
        "evaluated_candidates": evaluations,
        "selected": None if candidate is None else _selected_candidate_metadata(candidate),
    }
    if candidate is None:
        return _empty_result(
            base_meta,
            status="unavailable",
            warnings=["spatial_context_distance_unavailable"],
        )

    warnings = _quality_warnings(candidate, distance_cfg)
    quality_action = str(distance_cfg.get("quality_action") or "warn").strip().lower()
    if warnings and quality_action == "error":
        raise ValueError("Spatial-context distance quality failed: " + ", ".join(warnings))
    if warnings and quality_action == "omit":
        return _empty_result(base_meta, status="unavailable", warnings=warnings)

    grid_interval_m = float(distance_cfg["grid_interval_m"])
    maximum_distance_m = float(candidate.distance_m[-1])
    bin_count = int(math.ceil(maximum_distance_m / grid_interval_m))
    if bin_count < 1:
        return _empty_result(
            base_meta,
            status="unavailable",
            warnings=[*warnings, "spatial_context_distance_too_short"],
        )
    edges = np.arange(bin_count + 1, dtype=float) * grid_interval_m
    centres = edges[:-1] + grid_interval_m * 0.5

    distance_support_m = _accumulate_interval_lengths(
        candidate.distance_m[:-1][candidate.valid_pairs],
        candidate.distance_m[1:][candidate.valid_pairs],
        edges,
    )
    distance_support_fraction = np.clip(distance_support_m / grid_interval_m, 0.0, 1.0)
    minimum_distance_support = float(distance_cfg.get("minimum_distance_support_fraction", 0.5))
    distance_eligible = distance_support_fraction >= minimum_distance_support

    representative_time = _interpolate_spatial_values(
        candidate.distance_m,
        candidate.time_s,
        centres,
        candidate.valid_pairs,
    )
    active_mask_available = ACTIVE_MASK_COLUMN in primary.columns
    spatial_active = (
        _step_boolean_values_at_times(
            primary_time,
            primary[ACTIVE_MASK_COLUMN].fillna(False).astype(bool).to_numpy(),
            representative_time,
        )
        if active_mask_available
        else np.zeros(centres.shape, dtype=bool)
    )
    metric_eligible = distance_eligible & spatial_active
    if not active_mask_available:
        warnings.append("spatial_context_activity_mask_unavailable")
    altitude_grid = _interpolate_spatial_values(
        candidate.distance_m,
        candidate.altitude_m,
        centres,
        candidate.valid_pairs,
    )

    stream = pd.DataFrame(
        {
            "distance_m": centres,
            "representative_time_s": representative_time,
            "distance_support_fraction": distance_support_fraction,
            ACTIVE_MASK_COLUMN: spatial_active,
        }
    )
    signals: dict[str, dict[str, Any]] = {}
    metric_provenance: dict[str, Any] = {}
    availability: dict[str, bool] = {}

    gradient_cfg = cfg.get("gradient") if isinstance(cfg.get("gradient"), Mapping) else {}
    if bool(gradient_cfg.get("enabled", False)):
        gradient_local = _local_linear_gradient(
            centres,
            altitude_grid,
            window_m=float(gradient_cfg["regression_window_m"]),
            eligible=metric_eligible,
        )
        gradient = _centred_exponential_smooth(
            gradient_local,
            spacing_m=grid_interval_m,
            smoothing_distance_m=float(gradient_cfg["smoothing_distance_m"]),
        )
        stream["gradient_fraction_local"] = gradient_local
        stream["gradient_fraction"] = gradient
        availability["gradient"] = bool(np.isfinite(gradient).any())
        metric_provenance["gradient"] = {
            **copy.deepcopy(dict(gradient_cfg)),
            "source_column": candidate.source.altitude_column,
            "source_id": candidate.source.source_id,
            "active_mask_column": ACTIVE_MASK_COLUMN,
            "active_mask": copy.deepcopy((session.get("qc") or {}).get("activity_mask")),
        }
        signals.update(_gradient_signal_registry(metric_provenance["gradient"]))
        if not availability["gradient"]:
            warnings.append("spatial_context_gradient_unavailable")

    twistiness_cfg = cfg.get("twistiness") if isinstance(cfg.get("twistiness"), Mapping) else {}
    if bool(twistiness_cfg.get("enabled", False)):
        geometry_window_m = float(twistiness_cfg["geometry_window_m"])
        polynomial_order = int(twistiness_cfg.get("polynomial_order", 2))
        geometry_window_points = _spatial_window_point_count(
            window_m=geometry_window_m,
            spacing_m=grid_interval_m,
            polynomial_order=polynomial_order,
        )
        minimum_source_observations = int(
            twistiness_cfg.get("minimum_source_position_observations", 3)
        )
        curvature_local, source_observation_count = _source_local_polynomial_curvature(
            candidate,
            centres,
            geometry_window_m=geometry_window_m,
            polynomial_order=polynomial_order,
            eligible=metric_eligible,
            require_full_window=bool(twistiness_cfg.get("require_full_window", True)),
            minimum_source_observations=minimum_source_observations,
            fit_weighting=str(twistiness_cfg.get("fit_weighting") or "tricube"),
            horizontal_accuracy_weighting=bool(
                twistiness_cfg.get("horizontal_accuracy_weighting", True)
            ),
            horizontal_accuracy_floor_m=float(
                twistiness_cfg.get("horizontal_accuracy_floor_m", 0.5)
            ),
            robust_iterations=int(twistiness_cfg.get("robust_iterations", 2)),
            robust_tuning_constant=float(
                twistiness_cfg.get("robust_tuning_constant", 4.685)
            ),
        )
        twistiness = _centred_exponential_smooth(
            curvature_local,
            spacing_m=grid_interval_m,
            smoothing_distance_m=float(twistiness_cfg["smoothing_distance_m"]),
        )
        stream["curvature_abs_rad_per_m_local"] = curvature_local
        stream["twistiness_rad_per_m"] = twistiness
        stream["twistiness_source_observation_count"] = source_observation_count
        availability["twistiness"] = bool(np.isfinite(twistiness).any())
        metric_provenance["twistiness"] = {
            **copy.deepcopy(dict(twistiness_cfg)),
            "fit_input": "independent_source_position_observations",
            "effective_geometry_window_samples": geometry_window_points,
            "edge_exclusion_distance_m": (
                geometry_window_points // 2 * grid_interval_m
                if bool(twistiness_cfg.get("require_full_window", True))
                else 0.0
            ),
            "coordinate_model": candidate.diagnostics.get("coordinate_model"),
            "source_id": candidate.source.source_id,
            "horizontal_accuracy_column": candidate.source.horizontal_accuracy_column,
            "active_mask_column": ACTIVE_MASK_COLUMN,
            "active_mask": copy.deepcopy((session.get("qc") or {}).get("activity_mask")),
        }
        signals.update(_twistiness_signal_registry(metric_provenance["twistiness"]))
        if not availability["twistiness"]:
            warnings.append("spatial_context_twistiness_unavailable")

    activity_cfg = (
        cfg.get("suspension_activity")
        if isinstance(cfg.get("suspension_activity"), Mapping)
        else {}
    )
    activity_results: dict[str, dict[str, Any]] = {}
    if bool(activity_cfg.get("enabled", False)):
        activity_primary = session.get("df")
        activity_mask_unavailable = not active_mask_available
        for end in ("front", "rear"):
            selector = activity_cfg.get(f"{end}_selector")
            if not isinstance(selector, Mapping):
                continue
            if activity_mask_unavailable:
                availability[f"{end}_suspension_activity"] = False
                continue
            activity = _suspension_activity(
                session,
                selector=selector,
                end=end,
                candidate=candidate,
                edges=edges,
                eligible=metric_eligible,
                config=activity_cfg,
            )
            if activity is None:
                availability[f"{end}_suspension_activity"] = False
                warnings.append(f"spatial_context_{end}_wheel_displacement_unavailable")
                continue
            local_column = f"{end}_suspension_activity_local"
            smooth_column = f"{end}_suspension_activity"
            support_column = f"{end}_activity_support_fraction"
            stream[local_column] = activity["local"]
            stream[smooth_column] = activity["smoothed"]
            stream[support_column] = activity["support_fraction"]
            availability[f"{end}_suspension_activity"] = bool(
                np.isfinite(activity["smoothed"]).any()
            )
            activity_results[end] = activity
            metric_provenance[f"{end}_suspension_activity"] = activity["provenance"]
            signals.update(
                _activity_signal_registry(
                    end,
                    provenance=activity["provenance"],
                )
            )

        if (
            str(activity_cfg.get("combined_method") or "mean_both_required")
            == "mean_both_required"
            and "front" in activity_results
            and "rear" in activity_results
        ):
            front = np.asarray(activity_results["front"]["smoothed"], dtype=float)
            rear = np.asarray(activity_results["rear"]["smoothed"], dtype=float)
            combined = np.full(front.shape, np.nan, dtype=float)
            both = np.isfinite(front) & np.isfinite(rear)
            combined[both] = (front[both] + rear[both]) * 0.5
            stream["combined_suspension_activity"] = combined
            availability["combined_suspension_activity"] = bool(both.any())
            combined_provenance = {
                "method": "mean_both_required",
                "source_quantities": [
                    "front_suspension_activity",
                    "rear_suspension_activity",
                ],
            }
            metric_provenance["combined_suspension_activity"] = combined_provenance
            signals.update(_combined_activity_signal_registry(combined_provenance))

    enabled_metrics = [
        name
        for name, block in (
            ("gradient", gradient_cfg),
            ("twistiness", twistiness_cfg),
            ("suspension_activity", activity_cfg),
        )
        if bool(block.get("enabled", False))
    ]
    any_available = any(availability.values())
    missing_enabled = any(
        not value
        for key, value in availability.items()
        if key != "combined_suspension_activity"
    )
    status = "succeeded" if any_available and not missing_enabled and not warnings else "partial"
    if not any_available and enabled_metrics:
        status = "unavailable"

    base_meta.update(
        {
            "status": status,
            "coordinate": {
                "column": "distance_m",
                "unit": "m",
                "spacing_m": grid_interval_m,
                "alignment": "bin_centres",
                "domain": "session_cumulative_distance",
            },
            "time_mapping": {
                "column": "representative_time_s",
                "interpolation": "piecewise_linear",
                "max_gap_s": float(distance_cfg["max_interpolation_gap_s"]),
                "valid_interval_count": int(np.count_nonzero(candidate.valid_pairs)),
                "coverage_ratio": candidate.diagnostics.get("time_coverage_ratio"),
            },
            "metric_provenance": metric_provenance,
            "quality": {
                **copy.deepcopy(candidate.diagnostics),
                "distance_grid_rows": int(len(stream.index)),
                "distance_supported_rows": int(np.count_nonzero(distance_eligible)),
                "active_mask_available": active_mask_available,
                "active_spatial_rows": int(np.count_nonzero(spatial_active)),
                "metric_availability": availability,
            },
            "signals": signals,
            "channel_info": copy.deepcopy(signals),
            "warnings": list(dict.fromkeys(warnings)),
        }
    )
    qc = {
        "schema": "bodaqs.spatial_context_qc",
        "version": 1,
        "status": status,
        "distance_source": copy.deepcopy(base_meta["distance_source"]),
        "quality": copy.deepcopy(base_meta["quality"]),
        "warnings": copy.deepcopy(base_meta["warnings"]),
    }
    return SpatialContextResult(stream_df=stream, stream_meta=base_meta, qc=qc)


def scope_spatial_context_to_track(
    result: SpatialContextResult,
    session: Mapping[str, Any],
    track: Mapping[str, Any],
    config: Optional[Mapping[str, Any]] = None,
) -> SpatialContextResult:
    """Return a session-derived spatial stream scoped to one track traversal.

    Metrics remain session-derived. The selected forward passage may comprise
    several retained time intervals when reverse excursions are removed. Local
    estimates that could cross a cut are invalidated, and smoothed fields are
    regenerated independently inside each retained continuity segment.
    """

    scope_cfg = normalize_spatial_context_track_scope_config(config)
    metadata = copy.deepcopy(result.stream_meta)
    track_ref = {
        "track_id": str(track.get("track_id") or ""),
        "revision": track.get("revision"),
    }
    scope_metadata: dict[str, Any] = {
        "mode": "track_traversal",
        "metric_source": "session",
        "coordinate_source": "compacted_session_distance",
        "track_ref": track_ref,
        "traversal_selection": scope_cfg["traversal_selection"],
        "effective_config": copy.deepcopy(scope_cfg),
        "status": "unavailable",
    }
    metadata["track_scope"] = scope_metadata
    if result.stream_df.empty:
        return _empty_track_scope_result(
            metadata,
            warning="spatial_context_track_scope_source_empty",
        )

    primary = session.get("df")
    if not isinstance(primary, pd.DataFrame) or "time_s" not in primary.columns:
        return _empty_track_scope_result(
            metadata,
            warning="spatial_context_track_scope_primary_time_unavailable",
        )
    primary_time = _numeric(primary["time_s"])
    finite_primary_time = primary_time[np.isfinite(primary_time)]
    if finite_primary_time.size < 2:
        return _empty_track_scope_result(
            metadata,
            warning="spatial_context_track_scope_primary_time_unavailable",
        )

    effective_config = metadata.get("effective_config")
    effective_config = effective_config if isinstance(effective_config, Mapping) else {}
    distance_cfg = effective_config.get("distance")
    distance_cfg = distance_cfg if isinstance(distance_cfg, Mapping) else {}
    candidate, evaluations = _select_distance_candidate(
        _gps_sources(session),
        session=session,
        session_bounds=(float(np.min(finite_primary_time)), float(np.max(finite_primary_time))),
        config=distance_cfg,
    )
    scope_metadata["distance_candidate_evaluations"] = evaluations
    if candidate is None:
        return _empty_track_scope_result(
            metadata,
            warning="spatial_context_track_scope_gps_unavailable",
        )

    match = match_track_traversals(
        candidate.time_s,
        candidate.latitude_deg,
        candidate.longitude_deg,
        track,
        scope_cfg["matching"],
    )
    scope_metadata["matching"] = copy.deepcopy(match.diagnostics)
    scope_metadata["traversals"] = copy.deepcopy(match.traversals)
    if not match.traversals:
        return _empty_track_scope_result(
            metadata,
            warning="spatial_context_forward_track_traversal_unavailable",
        )

    selection = str(scope_cfg["traversal_selection"])
    if selection == "first_forward_traversal":
        selected = match.traversals[0]
    elif selection == "longest_forward_traversal":
        selected = max(match.traversals, key=lambda item: float(item["duration_s"]))
    else:
        selected = match.traversals[-1]

    retained_intervals = _retained_forward_time_intervals(
        match,
        selected,
        selection=selection,
        station_regression_tolerance_m=float(
            scope_cfg["station_regression_tolerance_m"]
        ),
        maximum_match_gap_s=float(scope_cfg["matching"]["maximum_match_gap_s"]),
    )
    if not retained_intervals:
        return _empty_track_scope_result(
            metadata,
            warning="spatial_context_forward_track_passage_unavailable",
        )

    selected_with_passage = copy.deepcopy(selected)
    selected_with_passage["retained_time_intervals"] = copy.deepcopy(retained_intervals)
    selected_with_passage["removed_time_intervals"] = [
        {
            "start_time_s": float(left["end_time_s"]),
            "end_time_s": float(right["start_time_s"]),
        }
        for left, right in zip(retained_intervals[:-1], retained_intervals[1:])
        if float(right["start_time_s"]) > float(left["end_time_s"])
    ]
    scope_metadata["selected_traversal"] = selected_with_passage

    stream = result.stream_df.copy(deep=True)
    representative_time = _numeric(stream["representative_time_s"])
    start_time_s = float(selected["start_time_s"])
    end_time_s = float(selected["end_time_s"])
    continuity_segment = np.full(representative_time.shape, -1, dtype=int)
    for segment, interval in enumerate(retained_intervals):
        in_interval = (
            np.isfinite(representative_time)
            & (representative_time >= float(interval["start_time_s"]))
            & (representative_time <= float(interval["end_time_s"]))
        )
        continuity_segment[in_interval] = segment
    selected_rows = continuity_segment >= 0
    stream = stream.loc[selected_rows].copy()
    continuity_segment = continuity_segment[selected_rows]
    if stream.empty:
        return _empty_track_scope_result(
            metadata,
            warning="spatial_context_track_scope_has_no_spatial_rows",
        )

    session_distance = _numeric(stream["distance_m"])
    interval_times = np.asarray(
        [
            value
            for interval in retained_intervals
            for value in (float(interval["start_time_s"]), float(interval["end_time_s"]))
        ],
        dtype=float,
    )
    interval_distances = np.interp(
        interval_times,
        candidate.time_s,
        candidate.distance_m,
    ).reshape((-1, 2))
    retained_lengths = np.maximum(0.0, interval_distances[:, 1] - interval_distances[:, 0])
    retained_offsets = np.r_[0.0, np.cumsum(retained_lengths[:-1])]
    compacted_distance = np.full(session_distance.shape, np.nan, dtype=float)
    interval_metadata: list[dict[str, Any]] = []
    for segment, (interval, bounds, offset) in enumerate(
        zip(retained_intervals, interval_distances, retained_offsets)
    ):
        segment_rows = continuity_segment == segment
        compacted_distance[segment_rows] = (
            float(offset) + session_distance[segment_rows] - float(bounds[0])
        )
        interval_metadata.append(
            {
                **copy.deepcopy(interval),
                "session_distance_start_m": float(bounds[0]),
                "session_distance_end_m": float(bounds[1]),
                "compacted_distance_start_m": float(offset),
                "compacted_distance_end_m": float(offset + max(0.0, bounds[1] - bounds[0])),
            }
        )
    distance_origin_m = float(interval_distances[0, 0])
    stream.insert(0, "session_distance_m", session_distance)
    stream.insert(1, "continuity_segment", continuity_segment)
    stream["distance_m"] = compacted_distance

    match_pairs = (
        match.matched[:-1]
        & match.matched[1:]
        & (np.diff(match.time_s) > 0.0)
        & (np.diff(match.time_s) <= float(scope_cfg["matching"]["maximum_match_gap_s"]))
    )
    track_station = _interpolate_time_values(
        match.time_s,
        match.station_m,
        _numeric(stream["representative_time_s"]),
        match_pairs,
    )
    stream.insert(2, "track_station_m", track_station)
    stream.reset_index(drop=True, inplace=True)
    _apply_track_scope_metric_boundaries(stream, metadata)

    retained_distance_m = float(np.sum(retained_lengths))
    outer_distance_m = max(0.0, float(interval_distances[-1, 1] - interval_distances[0, 0]))
    scope_metadata["retained_time_intervals"] = interval_metadata
    scope_metadata["removed_time_intervals"] = copy.deepcopy(
        selected_with_passage["removed_time_intervals"]
    )

    scope_metadata.update(
        {
            "status": "matched",
            "session_distance_origin_m": distance_origin_m,
            "session_distance_end_m": (
                float(interval_distances[-1, 1])
                if np.isfinite(interval_distances[-1, 1])
                else float(session_distance[-1])
            ),
            "retained_session_distance_m": retained_distance_m,
            "removed_session_distance_m": max(0.0, outer_distance_m - retained_distance_m),
            "continuity_segment_count": len(retained_intervals),
            "spatial_row_count": int(len(stream.index)),
        }
    )
    coordinate = metadata.get("coordinate")
    coordinate = dict(coordinate) if isinstance(coordinate, Mapping) else {}
    coordinate.update(
        {
            "column": "distance_m",
            "domain": "selected_forward_passage_compacted_session_distance",
            "origin": "selected_traversal_start",
        }
    )
    metadata["coordinate"] = coordinate
    time_mapping = metadata.get("time_mapping")
    time_mapping = dict(time_mapping) if isinstance(time_mapping, Mapping) else {}
    time_mapping["selected_time_bounds_s"] = [start_time_s, end_time_s]
    time_mapping["retained_time_intervals"] = copy.deepcopy(interval_metadata)
    metadata["time_mapping"] = time_mapping
    quality = metadata.get("quality")
    quality = dict(quality) if isinstance(quality, Mapping) else {}
    quality["track_scoped_distance_grid_rows"] = int(len(stream.index))
    metadata["quality"] = quality

    qc = copy.deepcopy(result.qc)
    qc["track_scope"] = copy.deepcopy(scope_metadata)
    qc["status"] = metadata.get("status")
    return SpatialContextResult(stream_df=stream, stream_meta=metadata, qc=qc)


def _retained_forward_time_intervals(
    match: Any,
    selected: Mapping[str, Any],
    *,
    selection: str,
    station_regression_tolerance_m: float,
    maximum_match_gap_s: float,
) -> list[dict[str, Any]]:
    """Return chronological pieces of the selected monotonic forward passage."""

    start_time_s = float(selected["start_time_s"])
    end_time_s = float(selected["end_time_s"])
    selected_points = np.flatnonzero(
        match.matched
        & (match.time_s >= start_time_s)
        & (match.time_s <= end_time_s)
    )
    if selected_points.size < 2:
        return []
    station = match.station_m[selected_points]
    time_s = match.time_s[selected_points]

    if selection == "first_forward_traversal":
        kept_positions = _monotonic_passage_positions(
            station,
            bias="first",
            tolerance_m=station_regression_tolerance_m,
        )
    elif selection == "longest_forward_traversal":
        first = _monotonic_passage_positions(
            station,
            bias="first",
            tolerance_m=station_regression_tolerance_m,
        )
        last = _monotonic_passage_positions(
            station,
            bias="last",
            tolerance_m=station_regression_tolerance_m,
        )
        first_duration = _retained_adjacent_duration(time_s, first)
        last_duration = _retained_adjacent_duration(time_s, last)
        kept_positions = first if first_duration >= last_duration else last
    else:
        kept_positions = _monotonic_passage_positions(
            station,
            bias="last",
            tolerance_m=station_regression_tolerance_m,
        )
    if kept_positions.size < 2:
        return []

    split_at = np.flatnonzero(
        (np.diff(kept_positions) > 1)
        | (np.diff(time_s[kept_positions]) > maximum_match_gap_s)
    ) + 1
    groups = np.split(kept_positions, split_at)
    intervals: list[dict[str, Any]] = []
    for group in groups:
        if group.size == 0:
            continue
        first = int(group[0])
        last = int(group[-1])
        intervals.append(
            {
                "start_time_s": float(time_s[first]),
                "end_time_s": float(time_s[last]),
                "start_station_m": float(station[first]),
                "end_station_m": float(station[last]),
                "matched_point_count": int(group.size),
            }
        )
    return intervals


def _retained_adjacent_duration(time_s: np.ndarray, positions: np.ndarray) -> float:
    if positions.size < 2:
        return 0.0
    adjacent = np.diff(positions) == 1
    return float(np.sum(np.diff(time_s[positions])[adjacent]))


def _monotonic_passage_positions(
    station_m: np.ndarray,
    *,
    bias: str,
    tolerance_m: float,
) -> np.ndarray:
    """Remove significant regressions, preferring the first or last station pass."""

    station = np.asarray(station_m, dtype=float)
    kept = np.arange(station.size, dtype=int)
    while kept.size > 1:
        values = station[kept]
        if bias == "first":
            reference = np.maximum.accumulate(values)
            violations = np.flatnonzero(values < reference - tolerance_m)
            if violations.size == 0:
                break
            violation = int(violations[0])
            before = values[: violation + 1]
            target = float(np.max(before))
            target_error = np.abs(before - target)
            cut_start = int(np.flatnonzero(target_error == np.min(target_error))[-1])
            after = values[violation:]
            after_error = np.abs(after - target)
            cut_stop = violation + int(
                np.flatnonzero(after_error == np.min(after_error))[0]
            )
        else:
            reference = np.minimum.accumulate(values[::-1])[::-1]
            violations = np.flatnonzero(values > reference + tolerance_m)
            if violations.size == 0:
                break
            violation = int(violations[0])
            after = values[violation:]
            target = float(np.min(after))
            after_error = np.abs(after - target)
            cut_stop = violation + int(
                np.flatnonzero(after_error == np.min(after_error))[-1]
            )
            before = values[: violation + 1]
            before_error = np.abs(before - target)
            cut_start = int(
                np.flatnonzero(before_error == np.min(before_error))[-1]
            )
        if cut_stop <= cut_start + 1:
            break
        kept = np.r_[kept[: cut_start + 1], kept[cut_stop:]]
    return kept


def _apply_track_scope_metric_boundaries(
    stream: pd.DataFrame,
    metadata: dict[str, Any],
) -> None:
    """Remove cut-contaminated local estimates and smooth within retained pieces."""

    if stream.empty or "continuity_segment" not in stream.columns:
        return
    segments = stream["continuity_segment"].to_numpy(dtype=int)
    session_distance = _numeric(stream["session_distance_m"])
    provenance = metadata.get("metric_provenance")
    provenance = provenance if isinstance(provenance, dict) else {}

    metric_specs = (
        ("gradient", "gradient_fraction_local", "gradient_fraction", "regression_window_m"),
        (
            "twistiness",
            "curvature_abs_rad_per_m_local",
            "twistiness_rad_per_m",
            "geometry_window_m",
        ),
        (
            "front_suspension_activity",
            "front_suspension_activity_local",
            "front_suspension_activity",
            None,
        ),
        (
            "rear_suspension_activity",
            "rear_suspension_activity_local",
            "rear_suspension_activity",
            None,
        ),
    )
    spacing_m = float((metadata.get("coordinate") or {}).get("spacing_m") or 0.5)
    for metric_name, local_column, smooth_column, window_field in metric_specs:
        if local_column not in stream.columns or smooth_column not in stream.columns:
            continue
        metric_provenance = provenance.get(metric_name)
        metric_provenance = metric_provenance if isinstance(metric_provenance, dict) else {}
        exclusion_m = (
            float(metric_provenance.get(window_field) or 0.0) * 0.5
            if window_field is not None
            else 0.0
        )
        if exclusion_m > 0.0:
            local_values = _numeric(stream[local_column])
            for segment in np.unique(segments):
                rows = np.flatnonzero(segments == segment)
                if rows.size == 0:
                    continue
                lower = float(session_distance[rows[0]]) + exclusion_m
                upper = float(session_distance[rows[-1]]) - exclusion_m
                boundary_rows = rows[
                    (session_distance[rows] < lower) | (session_distance[rows] > upper)
                ]
                local_values[boundary_rows] = np.nan
            stream[local_column] = local_values
        smoothing_distance_m = float(metric_provenance.get("smoothing_distance_m") or 0.0)
        if smoothing_distance_m > 0.0:
            stream[smooth_column] = _smooth_within_segments(
                _numeric(stream[local_column]),
                segments,
                spacing_m=spacing_m,
                smoothing_distance_m=smoothing_distance_m,
            )
        metric_provenance["track_scope_boundary_handling"] = {
            "local_boundary_exclusion_m": exclusion_m,
            "smoothing_recomputed_within_continuity_segments": True,
        }
        provenance[metric_name] = metric_provenance

    if {
        "front_suspension_activity",
        "rear_suspension_activity",
        "combined_suspension_activity",
    }.issubset(stream.columns):
        front = _numeric(stream["front_suspension_activity"])
        rear = _numeric(stream["rear_suspension_activity"])
        combined = np.full(front.shape, np.nan, dtype=float)
        both = np.isfinite(front) & np.isfinite(rear)
        combined[both] = (front[both] + rear[both]) * 0.5
        stream["combined_suspension_activity"] = combined
    metadata["metric_provenance"] = provenance


def _smooth_within_segments(
    values: np.ndarray,
    segments: np.ndarray,
    *,
    spacing_m: float,
    smoothing_distance_m: float,
) -> np.ndarray:
    result = np.full(np.asarray(values).shape, np.nan, dtype=float)
    for segment in np.unique(segments):
        rows = np.flatnonzero(segments == segment)
        if rows.size == 0:
            continue
        result[rows] = _centred_exponential_smooth(
            np.asarray(values, dtype=float)[rows],
            spacing_m=spacing_m,
            smoothing_distance_m=smoothing_distance_m,
        )
    return result


def materialize_spatial_context(
    session: dict[str, Any],
    config: Optional[Mapping[str, Any]],
) -> SpatialContextResult:
    """Derive and register the optional spatial stream on ``session``."""

    result = derive_spatial_context(session, config)
    session.setdefault("qc", {})[SPATIAL_CONTEXT_STREAM_NAME] = copy.deepcopy(result.qc)
    meta = session.setdefault("meta", {})
    meta["spatial_context"] = {
        "schema": result.stream_meta.get("schema"),
        "version": result.stream_meta.get("version"),
        "stream_name": SPATIAL_CONTEXT_STREAM_NAME,
        "algorithm_version": result.stream_meta.get("algorithm_version"),
        "status": result.stream_meta.get("status"),
        "warnings": copy.deepcopy(result.stream_meta.get("warnings", [])),
    }
    session.setdefault("stream_dfs", {})[SPATIAL_CONTEXT_STREAM_NAME] = result.stream_df
    meta.setdefault("secondary_streams", {})[SPATIAL_CONTEXT_STREAM_NAME] = result.stream_meta
    coordinate = result.stream_meta.get("coordinate")
    coordinate = coordinate if isinstance(coordinate, Mapping) else {}
    effective_config = result.stream_meta.get("effective_config")
    effective_config = effective_config if isinstance(effective_config, Mapping) else {}
    distance_config = effective_config.get("distance")
    distance_config = distance_config if isinstance(distance_config, Mapping) else {}
    meta.setdefault("streams", {})[SPATIAL_CONTEXT_STREAM_NAME] = {
        "kind": "spatial_uniform",
        "coordinate_col": "distance_m",
        "coordinate_unit": "m",
        "spacing_m": coordinate.get("spacing_m", distance_config.get("grid_interval_m")),
        "time_col": "representative_time_s",
        "notes": "Session-scoped distance-domain spatial context product",
    }
    return result


def _empty_track_scope_result(
    metadata: dict[str, Any],
    *,
    warning: str,
) -> SpatialContextResult:
    metadata["status"] = "unavailable"
    warnings = [*metadata.get("warnings", []), warning]
    metadata["warnings"] = list(dict.fromkeys(str(item) for item in warnings))
    track_scope = metadata.get("track_scope")
    if isinstance(track_scope, dict):
        track_scope["status"] = "unavailable"
    qc = {
        "schema": "bodaqs.spatial_context_qc",
        "version": 1,
        "status": "unavailable",
        "distance_source": copy.deepcopy(metadata.get("distance_source", {})),
        "quality": copy.deepcopy(metadata.get("quality", {})),
        "track_scope": copy.deepcopy(metadata.get("track_scope", {})),
        "warnings": copy.deepcopy(metadata["warnings"]),
    }
    return SpatialContextResult(pd.DataFrame(), metadata, qc)


def _base_stream_meta(config: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": SPATIAL_CONTEXT_STREAM_SCHEMA,
        "version": SPATIAL_CONTEXT_STREAM_VERSION,
        "algorithm_version": int(config.get("algorithm_version", SPATIAL_CONTEXT_ALGORITHM_VERSION)),
        "stream_name": SPATIAL_CONTEXT_STREAM_NAME,
        "kind": "derived",
        "status": "unavailable",
        "effective_config": copy.deepcopy(dict(config)),
        "distance_source": {},
        "time_mapping": {},
        "metric_provenance": {},
        "quality": {},
        "signals": {},
        "channel_info": {},
        "warnings": [],
    }


def _empty_result(
    metadata: dict[str, Any],
    *,
    status: str,
    warnings: Sequence[str],
) -> SpatialContextResult:
    metadata["status"] = status
    metadata["warnings"] = list(dict.fromkeys(str(item) for item in warnings))
    qc = {
        "schema": "bodaqs.spatial_context_qc",
        "version": 1,
        "status": status,
        "distance_source": copy.deepcopy(metadata.get("distance_source", {})),
        "quality": copy.deepcopy(metadata.get("quality", {})),
        "warnings": copy.deepcopy(metadata["warnings"]),
    }
    return SpatialContextResult(pd.DataFrame(), metadata, qc)


def _gps_sources(session: Mapping[str, Any]) -> list[_GpsSource]:
    meta = session.get("meta") if isinstance(session.get("meta"), Mapping) else {}
    secondary_meta = meta.get("secondary_streams") if isinstance(meta.get("secondary_streams"), Mapping) else {}
    stream_dfs = session.get("stream_dfs") if isinstance(session.get("stream_dfs"), Mapping) else {}
    sources: list[_GpsSource] = []

    for stream_name, frame in stream_dfs.items():
        if not isinstance(stream_name, str) or not isinstance(frame, pd.DataFrame):
            continue
        stream_metadata = secondary_meta.get(stream_name)
        stream_metadata = stream_metadata if isinstance(stream_metadata, Mapping) else {}
        source = _gps_source_from_frame(stream_name, stream_name, frame, stream_metadata)
        if source is not None:
            sources.append(source)

    primary = session.get("df")
    if isinstance(primary, pd.DataFrame):
        source = _gps_source_from_frame("primary", "primary", primary, meta)
        if source is not None:
            sources.append(source)

    preferred = None
    gps_sources = meta.get("gps_sources") if isinstance(meta, Mapping) else None
    if isinstance(gps_sources, Mapping):
        preferred = str(gps_sources.get("preferred_source") or "").strip() or None
    return sorted(
        sources,
        key=lambda item: (
            0 if preferred and item.source_id == preferred else 1,
            1 if item.stream_name == "primary" else 0,
            item.source_id,
        ),
    )


def _gps_source_from_frame(
    source_id: str,
    stream_name: str,
    frame: pd.DataFrame,
    metadata: Mapping[str, Any],
) -> Optional[_GpsSource]:
    resolution_metadata = dict(metadata)
    if not isinstance(resolution_metadata.get("signals"), Mapping) and isinstance(
        resolution_metadata.get("channel_info"), Mapping
    ):
        resolution_metadata["signals"] = resolution_metadata["channel_info"]
    columns = resolve_gps_columns(
        resolution_metadata,
        known_columns=set(map(str, frame.columns)),
    )
    if columns is None:
        return None
    time_column = str(metadata.get("time_col") or "time_s")
    if time_column not in frame.columns:
        return None
    return _GpsSource(
        source_id=source_id,
        stream_name=stream_name,
        source_kind=gps_source_kind(source_id, metadata, latitude_col=columns.latitude),
        frame=frame,
        metadata=metadata,
        time_column=time_column,
        latitude_column=columns.latitude,
        longitude_column=columns.longitude,
        altitude_column=columns.altitude,
        distance_column=columns.distance,
        valid_column=columns.valid,
        fresh_column=columns.fresh,
        sequence_column=columns.seq,
        horizontal_accuracy_column=columns.horizontal_accuracy,
    )


def _select_distance_candidate(
    sources: Sequence[_GpsSource],
    *,
    session: Mapping[str, Any],
    session_bounds: tuple[float, float],
    config: Mapping[str, Any],
) -> tuple[Optional[_DistanceCandidate], list[dict[str, Any]]]:
    evaluations: list[dict[str, Any]] = []
    for candidate_kind in config.get("source_priority", []):
        for source in sources:
            candidate, diagnostics = _evaluate_distance_candidate(
                source,
                kind=str(candidate_kind),
                session_bounds=session_bounds,
                config=config,
            )
            evaluations.append(diagnostics)
            if candidate is not None:
                return candidate, evaluations
    if not sources:
        evaluations.append({"status": "rejected", "reason": "no_gps_sources"})
    return None, evaluations


def _evaluate_distance_candidate(
    source: _GpsSource,
    *,
    kind: str,
    session_bounds: tuple[float, float],
    config: Mapping[str, Any],
) -> tuple[Optional[_DistanceCandidate], dict[str, Any]]:
    diagnostic: dict[str, Any] = {
        "candidate_kind": kind,
        "source_id": source.source_id,
        "stream_name": source.stream_name,
        "source_kind": source.source_kind,
        "status": "rejected",
    }
    if kind == "recorded_gps_or_fit_distance" and source.distance_column is None:
        diagnostic["reason"] = "recorded_distance_unavailable"
        return None, diagnostic
    if kind not in {"recorded_gps_or_fit_distance", "gps_geometry"}:
        diagnostic["reason"] = "unsupported_candidate_kind"
        return None, diagnostic

    frame = source.frame
    time_s = _numeric(frame[source.time_column])
    latitude = _numeric(frame[source.latitude_column])
    longitude = _numeric(frame[source.longitude_column])
    valid = np.isfinite(time_s) & np.isfinite(latitude) & np.isfinite(longitude)
    if source.valid_column and source.valid_column in frame.columns:
        valid &= _numeric(frame[source.valid_column]) == 1.0
    if source.fresh_column and source.fresh_column in frame.columns:
        valid &= _numeric(frame[source.fresh_column]) == 1.0
    if kind == "recorded_gps_or_fit_distance":
        recorded = _numeric(frame[source.distance_column])  # type: ignore[index]
        valid &= np.isfinite(recorded)
    else:
        recorded = np.full(time_s.shape, np.nan, dtype=float)

    rows = np.flatnonzero(valid)
    if rows.size < 2:
        diagnostic["reason"] = "insufficient_valid_points"
        diagnostic["valid_points"] = int(rows.size)
        return None, diagnostic
    order = rows[np.argsort(time_s[rows], kind="stable")]
    unique = np.r_[True, np.diff(time_s[order]) > 1.0e-9]
    order = order[unique]
    if order.size < 2:
        diagnostic["reason"] = "insufficient_distinct_times"
        return None, diagnostic

    time_s = time_s[order]
    latitude = latitude[order]
    longitude = longitude[order]
    recorded_ordered = recorded[order]
    observation_filter = "fresh_flag" if source.fresh_column else "all_rows"
    if source.sequence_column and source.sequence_column in frame.columns:
        sequence = _numeric(frame[source.sequence_column])[order]
        keep_observation = np.r_[True, np.diff(sequence) != 0]
        observation_filter = "sequence_change"
    elif not source.fresh_column:
        position_changed = np.r_[
            True,
            (np.diff(latitude) != 0.0) | (np.diff(longitude) != 0.0),
        ]
        if kind == "recorded_gps_or_fit_distance":
            position_changed |= np.r_[True, np.diff(recorded_ordered) != 0.0]
        keep_observation = position_changed
        if not np.all(keep_observation):
            observation_filter = "consecutive_snapshot_values_collapsed"
    else:
        keep_observation = np.ones(time_s.shape, dtype=bool)
    collapsed_snapshot_rows = int(np.count_nonzero(~keep_observation))
    time_s = time_s[keep_observation]
    latitude = latitude[keep_observation]
    longitude = longitude[keep_observation]
    recorded_ordered = recorded_ordered[keep_observation]
    if len(time_s) < 2:
        diagnostic["reason"] = "insufficient_distinct_observations"
        return None, diagnostic
    x_m, y_m = local_xy(latitude, longitude)
    altitude = (
        _numeric(frame[source.altitude_column])[order][keep_observation]
        if source.altitude_column and source.altitude_column in frame.columns
        else np.full(time_s.shape, np.nan, dtype=float)
    )
    horizontal_accuracy = (
        _numeric(frame[source.horizontal_accuracy_column])[order][keep_observation]
        if source.horizontal_accuracy_column
        and source.horizontal_accuracy_column in frame.columns
        else np.full(time_s.shape, np.nan, dtype=float)
    )

    repairs: list[str] = []
    if kind == "recorded_gps_or_fit_distance":
        distance = recorded_ordered.astype(float)
        distance -= distance[0]
        delta = np.diff(distance)
        if np.any(delta < -_RECORDED_DISTANCE_REVERSAL_TOLERANCE_M):
            diagnostic["reason"] = "recorded_distance_reset_or_reversal"
            diagnostic["maximum_reversal_m"] = float(abs(np.min(delta)))
            return None, diagnostic
        if np.any(delta < 0):
            distance = np.maximum.accumulate(distance)
            repairs.append("small_distance_reversals_monotonized")
    else:
        distance_model = str(config.get("distance_model") or "local_projection")
        raw_increments = (
            geodesic_segment_lengths(latitude, longitude)
            if distance_model == "geodesic"
            else np.hypot(np.diff(x_m), np.diff(y_m))
        )
        raw_distance = np.r_[0.0, np.cumsum(raw_increments)]
        distance = raw_distance
        denoising = config.get("geometry_denoising")
        denoising = denoising if isinstance(denoising, Mapping) else {}
        if bool(denoising.get("enabled", False)):
            fitted_x, fitted_y = denoise_route_positions(
                raw_distance,
                x_m,
                y_m,
                config=denoising,
            )
            if distance_model == "geodesic":
                fitted_latitude, fitted_longitude = local_latitude_longitude(
                    fitted_x,
                    fitted_y,
                    source_latitude=latitude,
                    source_longitude=longitude,
                )
                increments = geodesic_segment_lengths(
                    fitted_latitude,
                    fitted_longitude,
                )
            else:
                increments = np.hypot(np.diff(fitted_x), np.diff(fitted_y))
            distance = np.r_[0.0, np.cumsum(increments)]
            repairs.append("gps_geometry_denoised_before_stationing")
            diagnostic["geometry_denoising"] = copy.deepcopy(dict(denoising))
            diagnostic["raw_geometry_distance_m"] = float(raw_distance[-1])

    if not np.isfinite(distance).all() or distance[-1] <= 0:
        diagnostic["reason"] = "non_positive_distance"
        return None, diagnostic

    dt = np.diff(time_s)
    ds = np.diff(distance)
    max_gap_s = float(config["max_interpolation_gap_s"])
    positive_gaps = dt[np.isfinite(dt) & (dt > 0)]
    median_gap_s = float(np.median(positive_gaps)) if positive_gaps.size else None
    nominal_rate_hz = 1.0 / median_gap_s if median_gap_s and median_gap_s > 0 else None
    duration_s = max(0.0, session_bounds[1] - session_bounds[0])
    covered_duration_s = float(np.sum(np.minimum(positive_gaps, max_gap_s)))
    coverage_ratio = min(1.0, covered_duration_s / duration_s) if duration_s > 0 else 0.0
    implied_speed = np.divide(
        ds,
        dt,
        out=np.full(ds.shape, np.nan, dtype=float),
        where=dt > 0,
    )
    maximum_speed = float(np.nanmax(implied_speed)) if np.isfinite(implied_speed).any() else None
    maximum_allowed_speed = float(config.get("maximum_implied_speed_mps", 50.0))
    continuous_pairs = (
        np.isfinite(dt)
        & np.isfinite(ds)
        & (dt > 0)
        & (dt <= max_gap_s)
        & (ds >= 0.0)
        & np.isfinite(implied_speed)
        & (implied_speed <= maximum_allowed_speed)
    )
    valid_pairs = continuous_pairs & (ds > 1.0e-9)
    if not valid_pairs.any():
        diagnostic["reason"] = "no_valid_distance_intervals"
        return None, diagnostic

    diagnostic.update(
        {
            "status": "selected",
            "reason": None,
            "valid_points": int(len(time_s)),
            "observation_filter": observation_filter,
            "collapsed_snapshot_rows": collapsed_snapshot_rows,
            "valid_interval_count": int(np.count_nonzero(valid_pairs)),
            "distance_m": float(distance[-1]),
            "nominal_sample_rate_hz": nominal_rate_hz,
            "median_gap_s": median_gap_s,
            "maximum_gap_s": float(np.max(positive_gaps)) if positive_gaps.size else None,
            "time_coverage_ratio": coverage_ratio,
            "maximum_implied_speed_mps": maximum_speed,
            "rejected_speed_interval_count": int(
                np.count_nonzero(np.isfinite(implied_speed) & (implied_speed > maximum_allowed_speed))
            ),
            "repairs": repairs,
            "distance_model": (
                "recorded_signal"
                if kind == "recorded_gps_or_fit_distance"
                else str(config.get("distance_model") or "local_projection")
            ),
            "coordinate_model": "local_equirectangular",
        }
    )
    return (
        _DistanceCandidate(
            kind=kind,
            source=source,
            time_s=time_s,
            distance_m=distance,
            x_m=x_m,
            y_m=y_m,
            latitude_deg=latitude,
            longitude_deg=longitude,
            altitude_m=altitude,
            horizontal_accuracy_m=horizontal_accuracy,
            valid_pairs=valid_pairs,
            continuous_pairs=continuous_pairs,
            diagnostics=diagnostic,
        ),
        diagnostic,
    )


def _selected_candidate_metadata(candidate: _DistanceCandidate) -> dict[str, Any]:
    return {
        "candidate_kind": candidate.kind,
        "source_id": candidate.source.source_id,
        "stream_name": candidate.source.stream_name,
        "source_kind": candidate.source.source_kind,
        "time_column": candidate.source.time_column,
        "distance_column": candidate.source.distance_column if candidate.kind == "recorded_gps_or_fit_distance" else None,
        "position_columns": {
            "latitude": candidate.source.latitude_column,
            "longitude": candidate.source.longitude_column,
        },
        "altitude_column": candidate.source.altitude_column,
        "diagnostics": copy.deepcopy(candidate.diagnostics),
    }


def _quality_warnings(candidate: _DistanceCandidate, config: Mapping[str, Any]) -> list[str]:
    warnings: list[str] = []
    rate = candidate.diagnostics.get("nominal_sample_rate_hz")
    if rate is None or float(rate) < float(config.get("minimum_nominal_gps_rate_hz", 1.0)):
        warnings.append("spatial_context_gps_rate_below_threshold")
    coverage = candidate.diagnostics.get("time_coverage_ratio")
    if coverage is None or float(coverage) < float(config.get("minimum_gps_coverage_ratio", 0.99)):
        warnings.append("spatial_context_gps_coverage_below_threshold")
    if int(candidate.diagnostics.get("rejected_speed_interval_count") or 0) > 0:
        warnings.append("spatial_context_implausible_distance_intervals_rejected")
    return warnings


def _suspension_activity(
    session: Mapping[str, Any],
    *,
    selector: Mapping[str, Any],
    end: str,
    candidate: _DistanceCandidate,
    edges: np.ndarray,
    eligible: np.ndarray,
    config: Mapping[str, Any],
) -> Optional[dict[str, Any]]:
    column = resolve_signal_selector(
        session,
        selector,
        purpose=f"{end} spatial suspension activity",
        allow_missing=True,
    )
    primary = session.get("df")
    signals = ((session.get("meta") or {}).get("signals") or {})
    if column is None or not isinstance(primary, pd.DataFrame) or column not in primary.columns:
        return None
    signal_info = signals.get(column) if isinstance(signals, Mapping) else None
    signal_info = signal_info if isinstance(signal_info, Mapping) else {}
    if str(signal_info.get("domain") or "").strip().lower() != "wheel":
        return None
    unit = str(signal_info.get("unit") or selector.get("unit") or "").strip()
    unit_scale = {"mm": 0.001, "m": 1.0}.get(unit)
    if unit_scale is None:
        return None

    primary_time = _numeric(primary["time_s"])
    displacement_m = _numeric(primary[column]) * unit_scale
    mapped_distance = _interpolate_time_values(
        candidate.time_s,
        candidate.distance_m,
        primary_time,
        candidate.valid_pairs,
    )
    active = primary[ACTIVE_MASK_COLUMN].fillna(False).astype(bool).to_numpy()

    start = mapped_distance[:-1]
    end_distance = mapped_distance[1:]
    movement = np.abs(np.diff(displacement_m))
    valid = (
        np.isfinite(primary_time[:-1])
        & np.isfinite(primary_time[1:])
        & (np.diff(primary_time) > 0)
        & np.isfinite(start)
        & np.isfinite(end_distance)
        & (end_distance > start)
        & np.isfinite(movement)
        & active[:-1]
        & active[1:]
    )
    starts = start[valid]
    ends = end_distance[valid]
    movement = movement[valid]
    movement_by_bin = _accumulate_interval_quantity(starts, ends, movement, edges)
    support_m = _accumulate_interval_lengths(starts, ends, edges)
    interval_m = float(edges[1] - edges[0])
    support_fraction = np.clip(support_m / interval_m, 0.0, 1.0)
    local = np.divide(
        movement_by_bin,
        support_m,
        out=np.full(support_m.shape, np.nan, dtype=float),
        where=support_m > 0,
    )
    minimum_support = float(config.get("minimum_support_fraction", 0.25))
    local[support_fraction < minimum_support] = np.nan
    local[~np.asarray(eligible, dtype=bool)] = np.nan
    smoothed = _centred_exponential_smooth(
        local,
        spacing_m=interval_m,
        smoothing_distance_m=float(config["smoothing_distance_m"]),
    )

    activity_mask_qc = (session.get("qc") or {}).get("activity_mask")
    provenance = {
        "method": "native_rate_absolute_movement_per_ground_distance",
        "selector": copy.deepcopy(dict(selector)),
        "resolved_column": column,
        "resolved_signal": copy.deepcopy(dict(signal_info)),
        "input_unit": unit,
        "input_to_metre_scale": unit_scale,
        "native_interval_count": int(np.count_nonzero(valid)),
        "use_preprocess_active_mask": True,
        "activity_mask": copy.deepcopy(activity_mask_qc) if isinstance(activity_mask_qc, Mapping) else None,
        "minimum_support_fraction": minimum_support,
        "smoothing_kernel": config.get("smoothing_kernel"),
        "smoothing_distance_m": float(config["smoothing_distance_m"]),
    }
    return {
        "local": local,
        "smoothed": smoothed,
        "support_fraction": support_fraction,
        "provenance": provenance,
    }


def _local_linear_gradient(
    distance: np.ndarray,
    altitude: np.ndarray,
    *,
    window_m: float,
    eligible: Optional[np.ndarray] = None,
) -> np.ndarray:
    result = np.full(distance.shape, np.nan, dtype=float)
    radius = window_m * 0.5
    allowed = np.isfinite(distance)
    if eligible is not None:
        allowed &= np.asarray(eligible, dtype=bool)
    for segment_start, segment_stop in _contiguous_true_ranges(allowed):
        for index in range(segment_start, segment_stop):
            centre = float(distance[index])
            start = max(
                segment_start,
                int(np.searchsorted(distance, centre - radius, side="left")),
            )
            stop = min(
                segment_stop,
                int(np.searchsorted(distance, centre + radius, side="right")),
            )
            mask = np.isfinite(altitude[start:stop])
            if np.count_nonzero(mask) < 3:
                continue
            x = distance[start:stop][mask]
            z = altitude[start:stop][mask]
            x_c = x - float(np.mean(x))
            denominator = float(np.dot(x_c, x_c))
            if denominator <= 0:
                continue
            result[index] = float(np.dot(x_c, z - float(np.mean(z))) / denominator)
    return result


def _source_local_polynomial_curvature(
    candidate: _DistanceCandidate,
    target_distance: np.ndarray,
    *,
    geometry_window_m: float,
    polynomial_order: int,
    eligible: np.ndarray,
    require_full_window: bool,
    minimum_source_observations: int,
    fit_weighting: str,
    horizontal_accuracy_weighting: bool,
    horizontal_accuracy_floor_m: float,
    robust_iterations: int,
    robust_tuning_constant: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Fit source GPS positions locally and evaluate analytic curvature.

    The interpolated spatial grid is deliberately not used as fitting evidence:
    it would turn a handful of independent GPS fixes into many pseudo-samples
    while retaining every short-scale zig-zag in the source polyline.
    """

    result = np.full(target_distance.shape, np.nan, dtype=float)
    observation_count = np.zeros(target_distance.shape, dtype=np.int64)
    radius_m = geometry_window_m * 0.5
    required_observations = max(minimum_source_observations, polynomial_order + 1)
    full_support = (
        _full_window_support_mask(target_distance, eligible, radius_m=radius_m)
        if require_full_window
        else np.asarray(eligible, dtype=bool)
    )
    eligible_array = np.asarray(eligible, dtype=bool)
    segment_start_for_target = np.full(target_distance.shape, -1, dtype=int)
    segment_stop_for_target = np.full(target_distance.shape, -1, dtype=int)
    for segment_start, segment_stop in _contiguous_true_ranges(eligible_array):
        segment_start_for_target[segment_start:segment_stop] = segment_start
        segment_stop_for_target[segment_start:segment_stop] = segment_stop
    target_spacing_m = (
        float(np.nanmedian(np.diff(target_distance))) if target_distance.size > 1 else 0.0
    )

    for pair_start, pair_stop in _contiguous_true_ranges(candidate.continuous_pairs):
        source_slice = slice(pair_start, pair_stop + 1)
        source_distance = candidate.distance_m[source_slice]
        source_x = candidate.x_m[source_slice]
        source_y = candidate.y_m[source_slice]
        source_accuracy = candidate.horizontal_accuracy_m[source_slice]
        finite = np.isfinite(source_distance) & np.isfinite(source_x) & np.isfinite(source_y)
        source_distance = source_distance[finite]
        source_x = source_x[finite]
        source_y = source_y[finite]
        source_accuracy = source_accuracy[finite]
        if source_distance.size < required_observations:
            continue

        distinct = np.r_[True, np.diff(source_distance) > 1.0e-9]
        source_distance = source_distance[distinct]
        source_x = source_x[distinct]
        source_y = source_y[distinct]
        source_accuracy = source_accuracy[distinct]
        if source_distance.size < required_observations:
            continue

        target_start = int(np.searchsorted(target_distance, source_distance[0], side="left"))
        target_stop = int(np.searchsorted(target_distance, source_distance[-1], side="right"))
        for target_index in range(target_start, target_stop):
            if not eligible_array[target_index]:
                continue
            centre = float(target_distance[target_index])
            segment_start = int(segment_start_for_target[target_index])
            segment_stop = int(segment_stop_for_target[target_index])
            segment_lower_m = float(target_distance[segment_start]) - target_spacing_m * 0.5
            segment_upper_m = float(target_distance[segment_stop - 1]) + target_spacing_m * 0.5
            fit_lower_m = max(centre - radius_m, segment_lower_m)
            fit_upper_m = min(centre + radius_m, segment_upper_m)
            left = int(np.searchsorted(source_distance, fit_lower_m, side="left"))
            right = int(np.searchsorted(source_distance, fit_upper_m, side="right"))
            count = right - left
            observation_count[target_index] = max(observation_count[target_index], count)
            if count < required_observations or not full_support[target_index]:
                continue
            if require_full_window and (
                centre - radius_m < source_distance[0]
                or centre + radius_m > source_distance[-1]
            ):
                continue

            curvature = _weighted_local_polynomial_curvature(
                source_distance[left:right],
                source_x[left:right],
                source_y[left:right],
                source_accuracy[left:right],
                centre=centre,
                radius_m=radius_m,
                polynomial_order=polynomial_order,
                fit_weighting=fit_weighting,
                horizontal_accuracy_weighting=horizontal_accuracy_weighting,
                horizontal_accuracy_floor_m=horizontal_accuracy_floor_m,
                robust_iterations=robust_iterations,
                robust_tuning_constant=robust_tuning_constant,
            )
            if curvature is not None:
                result[target_index] = curvature
    return result, observation_count


def _full_window_support_mask(
    distance: np.ndarray,
    eligible: np.ndarray,
    *,
    radius_m: float,
) -> np.ndarray:
    result = np.zeros(distance.shape, dtype=bool)
    valid = np.isfinite(distance) & np.asarray(eligible, dtype=bool)
    for start, stop in _contiguous_true_ranges(valid):
        first = int(np.searchsorted(distance, distance[start] + radius_m, side="left"))
        last = int(np.searchsorted(distance, distance[stop - 1] - radius_m, side="right"))
        first = max(first, start)
        last = min(last, stop)
        if last > first:
            result[first:last] = True
    return result


def _weighted_local_polynomial_curvature(
    distance: np.ndarray,
    x_m: np.ndarray,
    y_m: np.ndarray,
    horizontal_accuracy_m: np.ndarray,
    *,
    centre: float,
    radius_m: float,
    polynomial_order: int,
    fit_weighting: str,
    horizontal_accuracy_weighting: bool,
    horizontal_accuracy_floor_m: float,
    robust_iterations: int,
    robust_tuning_constant: float,
) -> Optional[float]:
    coefficients = weighted_local_polynomial_coefficients(
        distance,
        x_m,
        y_m,
        horizontal_accuracy_m,
        centre=centre,
        radius_m=radius_m,
        polynomial_order=polynomial_order,
        fit_weighting=fit_weighting,
        horizontal_accuracy_weighting=horizontal_accuracy_weighting,
        horizontal_accuracy_floor_m=horizontal_accuracy_floor_m,
        robust_iterations=robust_iterations,
        robust_tuning_constant=robust_tuning_constant,
    )
    if coefficients is None:
        return None
    x_coefficients, y_coefficients = coefficients
    dx = x_coefficients[1] / radius_m
    dy = y_coefficients[1] / radius_m
    ddx = 2.0 * x_coefficients[2] / (radius_m * radius_m)
    ddy = 2.0 * y_coefficients[2] / (radius_m * radius_m)
    denominator = float(np.power(dx * dx + dy * dy, 1.5))
    if denominator <= 1.0e-12:
        return None
    return float(abs(dx * ddy - dy * ddx) / denominator)


def _spatial_window_point_count(
    *,
    window_m: float,
    spacing_m: float,
    polynomial_order: int,
) -> int:
    distance_window_points = int(math.ceil(window_m / spacing_m)) + 1
    window_points = max(2 * polynomial_order + 1, distance_window_points)
    if window_points % 2 == 0:
        window_points += 1
    return window_points


def _centred_exponential_smooth(
    values: np.ndarray,
    *,
    spacing_m: float,
    smoothing_distance_m: float,
) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    result = np.full(values.shape, np.nan, dtype=float)
    finite = np.isfinite(values)
    radius_points = max(1, int(math.ceil(5.0 * smoothing_distance_m / spacing_m)))
    offsets = np.arange(-radius_points, radius_points + 1, dtype=float) * spacing_m
    kernel = np.exp(-np.abs(offsets) / smoothing_distance_m)
    for start, stop in _contiguous_true_ranges(finite):
        segment = values[start:stop]
        if segment.size == 0:
            continue
        numerator = np.convolve(segment, kernel, mode="full")
        denominator = np.convolve(np.ones(segment.shape, dtype=float), kernel, mode="full")
        offset = (len(kernel) - 1) // 2
        numerator = numerator[offset : offset + len(segment)]
        denominator = denominator[offset : offset + len(segment)]
        result[start:stop] = numerator / denominator
    return result


def _interpolate_spatial_values(
    source_distance: np.ndarray,
    source_values: np.ndarray,
    target_distance: np.ndarray,
    valid_pairs: np.ndarray,
) -> np.ndarray:
    result = np.full(target_distance.shape, np.nan, dtype=float)
    for index in np.flatnonzero(valid_pairs):
        s0 = float(source_distance[index])
        s1 = float(source_distance[index + 1])
        if s1 <= s0:
            continue
        v0 = float(source_values[index])
        v1 = float(source_values[index + 1])
        if not np.isfinite(v0) or not np.isfinite(v1):
            continue
        start = int(np.searchsorted(target_distance, s0, side="left"))
        stop = int(np.searchsorted(target_distance, s1, side="right"))
        if stop <= start:
            continue
        fraction = (target_distance[start:stop] - s0) / (s1 - s0)
        result[start:stop] = v0 + fraction * (v1 - v0)
    return result


def _interpolate_time_values(
    source_time: np.ndarray,
    source_values: np.ndarray,
    target_time: np.ndarray,
    valid_pairs: np.ndarray,
) -> np.ndarray:
    result = np.full(target_time.shape, np.nan, dtype=float)
    finite_targets = np.isfinite(target_time)
    for index in np.flatnonzero(valid_pairs):
        t0 = float(source_time[index])
        t1 = float(source_time[index + 1])
        if t1 <= t0:
            continue
        start = int(np.searchsorted(target_time, t0, side="left"))
        stop = int(np.searchsorted(target_time, t1, side="right"))
        if stop <= start:
            continue
        positions = np.arange(start, stop)
        positions = positions[finite_targets[positions]]
        fraction = (target_time[positions] - t0) / (t1 - t0)
        result[positions] = source_values[index] + fraction * (
            source_values[index + 1] - source_values[index]
        )
    return result


def _step_boolean_values_at_times(
    source_time: np.ndarray,
    source_values: np.ndarray,
    target_time: np.ndarray,
) -> np.ndarray:
    """Sample a time-domain boolean state without interpolating across transitions."""

    source_time = np.asarray(source_time, dtype=float)
    source_values = np.asarray(source_values, dtype=bool)
    target_time = np.asarray(target_time, dtype=float)
    result = np.zeros(target_time.shape, dtype=bool)
    valid_source = np.isfinite(source_time)
    order = np.flatnonzero(valid_source)
    if order.size == 0:
        return result
    order = order[np.argsort(source_time[order], kind="stable")]
    distinct = np.r_[True, np.diff(source_time[order]) > 1.0e-9]
    order = order[distinct]
    times = source_time[order]
    values = source_values[order]
    valid_target = np.isfinite(target_time)
    positions = np.searchsorted(times, target_time[valid_target], side="right") - 1
    within = (positions >= 0) & (target_time[valid_target] <= times[-1])
    sampled = np.zeros(positions.shape, dtype=bool)
    sampled[within] = values[positions[within]]
    result[valid_target] = sampled
    return result


def _accumulate_interval_lengths(starts: np.ndarray, ends: np.ndarray, edges: np.ndarray) -> np.ndarray:
    quantities = np.asarray(ends, dtype=float) - np.asarray(starts, dtype=float)
    return _accumulate_interval_quantity(starts, ends, quantities, edges)


def _accumulate_interval_quantity(
    starts: np.ndarray,
    ends: np.ndarray,
    quantities: np.ndarray,
    edges: np.ndarray,
) -> np.ndarray:
    bin_count = len(edges) - 1
    result = np.zeros(bin_count, dtype=float)
    if bin_count <= 0 or len(starts) == 0:
        return result
    width = float(edges[1] - edges[0])
    max_distance = float(edges[-1])
    starts = np.asarray(starts, dtype=float)
    ends = np.asarray(ends, dtype=float)
    quantities = np.asarray(quantities, dtype=float)
    valid = (
        np.isfinite(starts)
        & np.isfinite(ends)
        & np.isfinite(quantities)
        & (ends > starts)
        & (ends > 0)
        & (starts < max_distance)
    )
    starts = np.clip(starts[valid], 0.0, max_distance)
    ends = np.clip(ends[valid], 0.0, max_distance)
    quantities = quantities[valid]
    durations = ends - starts
    positive = durations > 0
    starts = starts[positive]
    ends = ends[positive]
    quantities = quantities[positive]
    durations = durations[positive]
    if starts.size == 0:
        return result

    start_bins = np.minimum((starts / width).astype(int), bin_count - 1)
    end_bins = np.minimum((np.nextafter(ends, -np.inf) / width).astype(int), bin_count - 1)
    same = start_bins == end_bins
    if np.any(same):
        np.add.at(result, start_bins[same], quantities[same])
    for start, end, quantity, duration, start_bin, end_bin in zip(
        starts[~same],
        ends[~same],
        quantities[~same],
        durations[~same],
        start_bins[~same],
        end_bins[~same],
    ):
        for bin_index in range(int(start_bin), int(end_bin) + 1):
            overlap = max(0.0, min(end, edges[bin_index + 1]) - max(start, edges[bin_index]))
            if overlap > 0:
                result[bin_index] += quantity * overlap / duration
    return result


def _contiguous_true_ranges(mask: np.ndarray) -> list[tuple[int, int]]:
    mask = np.asarray(mask, dtype=bool)
    if mask.size == 0:
        return []
    changes = np.diff(np.r_[False, mask, False].astype(np.int8))
    starts = np.flatnonzero(changes == 1)
    stops = np.flatnonzero(changes == -1)
    return list(zip(starts.tolist(), stops.tolist()))


def _numeric(series: Any) -> np.ndarray:
    return pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)


def _gradient_signal_registry(provenance: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        "gradient_fraction_local": _spatial_signal(
            quantity="gradient",
            unit="1",
            processing_role="local_analysis",
            provenance=provenance,
        ),
        "gradient_fraction": _spatial_signal(
            quantity="gradient",
            unit="1",
            processing_role="primary_analysis",
            provenance=provenance,
        ),
    }


def _twistiness_signal_registry(provenance: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        "curvature_abs_rad_per_m_local": _spatial_signal(
            quantity="curvature_abs",
            unit="rad/m",
            processing_role="local_analysis",
            provenance=provenance,
        ),
        "twistiness_rad_per_m": _spatial_signal(
            quantity="twistiness",
            unit="rad/m",
            processing_role="primary_analysis",
            provenance=provenance,
        ),
        "twistiness_source_observation_count": {
            "kind": "qc",
            "domain": "spatial_context",
            "quantity": "source_position_observation_count",
            "unit": "count",
            "processing_role": "qc_metric",
            "semantic_selection_excluded": True,
            "origin": "analysis",
            "derivation": copy.deepcopy(dict(provenance)),
        },
    }


def _activity_signal_registry(
    end: str,
    *,
    provenance: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    base = {
        "end": end,
        "source_columns": [provenance.get("resolved_column")],
    }
    return {
        f"{end}_suspension_activity_local": {
            **_spatial_signal(
                quantity="suspension_activity",
                unit="1",
                processing_role="local_analysis",
                provenance=provenance,
            ),
            **base,
        },
        f"{end}_suspension_activity": {
            **_spatial_signal(
                quantity="suspension_activity",
                unit="1",
                processing_role="primary_analysis",
                provenance=provenance,
            ),
            **base,
        },
    }


def _combined_activity_signal_registry(provenance: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        "combined_suspension_activity": _spatial_signal(
            quantity="combined_suspension_activity",
            unit="1",
            processing_role="derived_view",
            provenance=provenance,
        )
    }


def _spatial_signal(
    *,
    quantity: str,
    unit: str,
    processing_role: str,
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "kind": "derived",
        "domain": "spatial_context",
        "quantity": quantity,
        "unit": unit,
        "processing_role": processing_role,
        "origin": "analysis",
        "derivation": copy.deepcopy(dict(provenance)),
    }


def _deep_update(target: dict[str, Any], override: Mapping[str, Any]) -> None:
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = copy.deepcopy(value)
