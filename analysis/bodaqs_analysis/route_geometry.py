"""Canonical route-geometry denoising and stationing helpers.

This module is the single implementation used by preprocessing and by the
Library API when it supplies geometry for Workbench track creation.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Mapping, Optional, Sequence

import numpy as np


EARTH_RADIUS_M = 6_371_000.0

DEFAULT_ROUTE_GEOMETRY_DENOISING_CONFIG: dict[str, Any] = {
    "enabled": True,
    "estimator": "local_polynomial",
    "window_m": 20.0,
    "polynomial_order": 2,
    "fit_weighting": "tricube",
    "robust_iterations": 2,
    "robust_tuning_constant": 4.685,
}


def canonical_route_geometry_denoising_config() -> dict[str, Any]:
    """Return a mutable copy of the canonical route-denoising policy."""

    return copy.deepcopy(DEFAULT_ROUTE_GEOMETRY_DENOISING_CONFIG)


def local_xy(
    latitude_deg: np.ndarray,
    longitude_deg: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    latitude_rad = np.radians(latitude_deg)
    longitude_rad = np.radians(longitude_deg)
    latitude_origin = float(np.nanmedian(latitude_rad))
    longitude_origin = float(longitude_rad[0])
    x_m = EARTH_RADIUS_M * (longitude_rad - longitude_origin) * math.cos(latitude_origin)
    y_m = EARTH_RADIUS_M * (latitude_rad - latitude_rad[0])
    return x_m, y_m


def local_latitude_longitude(
    x_m: np.ndarray,
    y_m: np.ndarray,
    *,
    source_latitude: np.ndarray,
    source_longitude: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    source_latitude_rad = np.radians(source_latitude)
    latitude_origin = float(np.nanmedian(source_latitude_rad))
    longitude_origin = math.radians(float(source_longitude[0]))
    latitude_start = math.radians(float(source_latitude[0]))
    latitude = np.degrees(y_m / EARTH_RADIUS_M + latitude_start)
    longitude = np.degrees(
        x_m / (EARTH_RADIUS_M * math.cos(latitude_origin)) + longitude_origin
    )
    return latitude, longitude


def geodesic_segment_lengths(
    latitude_deg: np.ndarray,
    longitude_deg: np.ndarray,
) -> np.ndarray:
    latitude_rad = np.radians(latitude_deg)
    delta_latitude = np.diff(latitude_rad)
    delta_longitude = np.radians(np.diff(longitude_deg))
    haversine_a = (
        np.sin(delta_latitude * 0.5) ** 2
        + np.cos(latitude_rad[:-1])
        * np.cos(latitude_rad[1:])
        * np.sin(delta_longitude * 0.5) ** 2
    )
    haversine_a = np.clip(haversine_a, 0.0, 1.0)
    return 2.0 * EARTH_RADIUS_M * np.arctan2(
        np.sqrt(haversine_a),
        np.sqrt(1.0 - haversine_a),
    )


def weighted_local_polynomial_coefficients(
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
) -> Optional[tuple[np.ndarray, np.ndarray]]:
    normalized_distance = (distance - centre) / radius_m
    design = np.vander(normalized_distance, N=polynomial_order + 1, increasing=True)
    if fit_weighting == "tricube":
        scaled = np.minimum(np.abs(normalized_distance), 1.0)
        base_weight = np.power(1.0 - np.power(scaled, 3.0), 3.0)
    else:
        base_weight = np.ones(distance.shape, dtype=float)

    if horizontal_accuracy_weighting:
        accuracy = np.asarray(horizontal_accuracy_m, dtype=float)
        valid_accuracy = np.isfinite(accuracy) & (accuracy > 0.0)
        if valid_accuracy.any():
            fallback = float(np.median(accuracy[valid_accuracy]))
            accuracy = np.where(valid_accuracy, accuracy, fallback)
            accuracy = np.maximum(accuracy, horizontal_accuracy_floor_m)
            base_weight = base_weight / np.square(accuracy)

    robust_weight = np.ones(distance.shape, dtype=float)
    coefficients: Optional[tuple[np.ndarray, np.ndarray]] = None
    for iteration in range(robust_iterations + 1):
        weight = base_weight * robust_weight
        usable = np.isfinite(weight) & (weight > 0.0)
        if np.count_nonzero(usable) < polynomial_order + 1:
            return None
        weighted_design = design[usable] * np.sqrt(weight[usable])[:, None]
        if np.linalg.matrix_rank(weighted_design) < polynomial_order + 1:
            return None
        x_coefficients = np.linalg.lstsq(
            weighted_design,
            x_m[usable] * np.sqrt(weight[usable]),
            rcond=None,
        )[0]
        y_coefficients = np.linalg.lstsq(
            weighted_design,
            y_m[usable] * np.sqrt(weight[usable]),
            rcond=None,
        )[0]
        coefficients = (x_coefficients, y_coefficients)
        if iteration >= robust_iterations:
            break

        x_residual = x_m - design @ x_coefficients
        y_residual = y_m - design @ y_coefficients
        centred_x_residual = x_residual - np.median(x_residual)
        centred_y_residual = y_residual - np.median(y_residual)
        radial_residual = np.hypot(centred_x_residual, centred_y_residual)
        scale = 1.4826 * float(np.median(radial_residual))
        if not np.isfinite(scale) or scale <= 1.0e-9:
            break
        normalized_residual = radial_residual / (robust_tuning_constant * scale)
        robust_weight = np.where(
            normalized_residual < 1.0,
            np.square(1.0 - np.square(normalized_residual)),
            0.0,
        )

    return coefficients


def denoise_route_positions(
    distance: np.ndarray,
    x_m: np.ndarray,
    y_m: np.ndarray,
    *,
    config: Mapping[str, Any],
) -> tuple[np.ndarray, np.ndarray]:
    """Return locally fitted positions without treating repeats as evidence."""

    distinct = np.r_[True, np.diff(distance) > 1.0e-9]
    source_distance = distance[distinct]
    source_x = x_m[distinct]
    source_y = y_m[distinct]
    if source_distance.size < 3 or not bool(config.get("enabled", False)):
        return x_m.copy(), y_m.copy()

    window_m = float(config.get("window_m", 20.0))
    radius_m = window_m * 0.5
    polynomial_order = int(config.get("polynomial_order", 2))
    if radius_m <= 0.0:
        return x_m.copy(), y_m.copy()
    required = polynomial_order + 1
    fit_weighting = str(config.get("fit_weighting") or "tricube")
    robust_iterations = int(config.get("robust_iterations", 2))
    robust_tuning_constant = float(config.get("robust_tuning_constant", 4.685))
    no_accuracy = np.full(source_distance.shape, np.nan, dtype=float)
    fitted_x = source_x.copy()
    fitted_y = source_y.copy()

    left = 0
    right = 0
    for index, centre in enumerate(source_distance):
        while left < len(source_distance) and source_distance[left] < centre - radius_m:
            left += 1
        right = max(right, left)
        while right < len(source_distance) and source_distance[right] <= centre + radius_m:
            right += 1
        if right - left < required:
            continue
        coefficients = weighted_local_polynomial_coefficients(
            source_distance[left:right],
            source_x[left:right],
            source_y[left:right],
            no_accuracy[left:right],
            centre=float(centre),
            radius_m=radius_m,
            polynomial_order=polynomial_order,
            fit_weighting=fit_weighting,
            horizontal_accuracy_weighting=False,
            horizontal_accuracy_floor_m=1.0,
            robust_iterations=robust_iterations,
            robust_tuning_constant=robust_tuning_constant,
        )
        if coefficients is not None:
            fitted_x[index] = coefficients[0][0]
            fitted_y[index] = coefficients[1][0]

    return (
        np.interp(distance, source_distance, fitted_x),
        np.interp(distance, source_distance, fitted_y),
    )


def denoise_route_coordinates(
    points: Sequence[Mapping[str, Any]],
    *,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build authoritative denoised lon/lat geometry from API-style points."""

    policy = canonical_route_geometry_denoising_config()
    if config is not None:
        policy.update(dict(config))
    coordinates: list[tuple[float, float, float | None]] = []
    for point in points:
        try:
            longitude = float(point.get("longitude"))
            latitude = float(point.get("latitude"))
        except (TypeError, ValueError):
            continue
        if not np.isfinite(longitude) or not np.isfinite(latitude):
            continue
        elevation_value = point.get("elevation_m")
        try:
            elevation = float(elevation_value) if elevation_value is not None else None
        except (TypeError, ValueError):
            elevation = None
        if elevation is not None and not np.isfinite(elevation):
            elevation = None
        if coordinates and coordinates[-1][:2] == (longitude, latitude):
            continue
        coordinates.append((longitude, latitude, elevation))

    if not coordinates:
        return {
            "status": "unavailable",
            "coordinates": [],
            "point_count": 0,
            "length_m": 0.0,
            "geometry_denoising": policy,
        }

    longitude = np.asarray([point[0] for point in coordinates], dtype=float)
    latitude = np.asarray([point[1] for point in coordinates], dtype=float)
    x_m, y_m = local_xy(latitude, longitude)
    raw_distance = np.r_[0.0, np.cumsum(geodesic_segment_lengths(latitude, longitude))]
    fitted_x, fitted_y = denoise_route_positions(raw_distance, x_m, y_m, config=policy)
    fitted_latitude, fitted_longitude = local_latitude_longitude(
        fitted_x,
        fitted_y,
        source_latitude=latitude,
        source_longitude=longitude,
    )
    length_m = float(np.sum(geodesic_segment_lengths(fitted_latitude, fitted_longitude)))
    result_coordinates: list[list[float]] = []
    for index, (_, _, elevation) in enumerate(coordinates):
        result = [float(fitted_longitude[index]), float(fitted_latitude[index])]
        if elevation is not None:
            result.append(elevation)
        result_coordinates.append(result)
    return {
        "status": "succeeded" if len(result_coordinates) >= 2 else "insufficient_points",
        "coordinates": result_coordinates,
        "point_count": len(result_coordinates),
        "length_m": length_m,
        "geometry_denoising": policy,
    }
