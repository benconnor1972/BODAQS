from __future__ import annotations

import numpy as np
import pytest

from bodaqs_analysis.route_geometry import (
    DEFAULT_ROUTE_GEOMETRY_DENOISING_CONFIG,
    denoise_route_coordinates,
    geodesic_segment_lengths,
)
from bodaqs_analysis.spatial_context import DEFAULT_SPATIAL_CONTEXT_CONFIG


def test_spatial_context_uses_canonical_route_geometry_policy() -> None:
    assert DEFAULT_SPATIAL_CONTEXT_CONFIG["distance"]["geometry_denoising"] == (
        DEFAULT_ROUTE_GEOMETRY_DENOISING_CONFIG
    )
    assert (
        DEFAULT_SPATIAL_CONTEXT_CONFIG["distance"]["geometry_denoising"]
        is not DEFAULT_ROUTE_GEOMETRY_DENOISING_CONFIG
    )


def test_denoised_route_coordinates_remove_zigzag_distance_and_keep_elevation() -> None:
    east_m = np.linspace(0.0, 100.0, 101)
    lateral_m = np.random.default_rng(42).normal(0.0, 0.5, east_m.size)
    latitude_origin = -31.95
    points = [
        {
            "longitude": 115.85
            + np.degrees(east / (6_371_000.0 * np.cos(np.radians(latitude_origin)))),
            "latitude": latitude_origin + np.degrees(lateral / 6_371_000.0),
            "elevation_m": 200.0 + index,
        }
        for index, (east, lateral) in enumerate(zip(east_m, lateral_m))
    ]

    raw_latitude = np.asarray([point["latitude"] for point in points])
    raw_longitude = np.asarray([point["longitude"] for point in points])
    raw_length_m = float(np.sum(geodesic_segment_lengths(raw_latitude, raw_longitude)))
    result = denoise_route_coordinates(points)

    assert result["status"] == "succeeded"
    assert result["point_count"] == len(points)
    assert result["length_m"] == pytest.approx(100.0, abs=3.0)
    assert raw_length_m > result["length_m"] * 1.05
    assert result["coordinates"][0][2] == 200.0
    assert result["coordinates"][-1][2] == 300.0
    assert result["geometry_denoising"] == DEFAULT_ROUTE_GEOMETRY_DENOISING_CONFIG
