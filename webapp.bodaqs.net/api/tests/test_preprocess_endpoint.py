"""Integration tests for POST /api/preprocess.

Tests exercise the full HTTP stack via FastAPI's TestClient.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bodaqs_api.main import app

client = TestClient(app)
FIXTURES = Path(__file__).parent / "fixtures"


def _multipart(
    *,
    csv_bytes: bytes,
    sidecar_bytes: bytes,
    bike_profile_bytes: bytes,
    event_schema_bytes: bytes,
    preprocess_profile_bytes: bytes | None = None,
) -> dict:
    files: dict = {
        "csv_file": ("2026-02-20_13-08-45.csv", csv_bytes, "text/csv"),
        "sidecar_json": ("ride_sidecar.json", sidecar_bytes, "application/json"),
        "bike_profile_json": ("test_bike_profile.json", bike_profile_bytes, "application/json"),
        "event_schema_yaml": ("event_schema.yaml", event_schema_bytes, "application/yaml"),
    }
    if preprocess_profile_bytes is not None:
        files["preprocess_profile_json"] = (
            "preprocess_profile.json",
            preprocess_profile_bytes,
            "application/json",
        )
    return files


def test_preprocess_success(
    csv_bytes: bytes,
    sidecar_bytes: bytes,
    bike_profile_bytes: bytes,
    event_schema_bytes: bytes,
) -> None:
    response = client.post(
        "/api/preprocess",
        files=_multipart(
            csv_bytes=csv_bytes,
            sidecar_bytes=sidecar_bytes,
            bike_profile_bytes=bike_profile_bytes,
            event_schema_bytes=event_schema_bytes,
        ),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"] == "2026-02-20_13-08-45"
    assert "signals" in body
    assert "events" in body
    assert "metrics" in body
    assert "warnings" in body
    assert isinstance(body["warnings"], list)


def test_preprocess_with_explicit_profile(
    csv_bytes: bytes,
    sidecar_bytes: bytes,
    bike_profile_bytes: bytes,
    event_schema_bytes: bytes,
    preprocess_profile_bytes: bytes,
) -> None:
    response = client.post(
        "/api/preprocess",
        files=_multipart(
            csv_bytes=csv_bytes,
            sidecar_bytes=sidecar_bytes,
            bike_profile_bytes=bike_profile_bytes,
            event_schema_bytes=event_schema_bytes,
            preprocess_profile_bytes=preprocess_profile_bytes,
        ),
    )
    assert response.status_code == 200, response.text


def test_preprocess_missing_csv_returns_422(
    sidecar_bytes: bytes,
    bike_profile_bytes: bytes,
    event_schema_bytes: bytes,
) -> None:
    response = client.post(
        "/api/preprocess",
        files={
            "sidecar_json": ("ride_sidecar.json", sidecar_bytes, "application/json"),
            "bike_profile_json": ("test_bike_profile.json", bike_profile_bytes, "application/json"),
            "event_schema_yaml": ("event_schema.yaml", event_schema_bytes, "application/yaml"),
        },
    )
    assert response.status_code == 422


def test_preprocess_missing_bike_profile_returns_422(
    csv_bytes: bytes,
    sidecar_bytes: bytes,
    event_schema_bytes: bytes,
) -> None:
    response = client.post(
        "/api/preprocess",
        files={
            "csv_file": ("ride.csv", csv_bytes, "text/csv"),
            "sidecar_json": ("ride_sidecar.json", sidecar_bytes, "application/json"),
            "event_schema_yaml": ("event_schema.yaml", event_schema_bytes, "application/yaml"),
        },
    )
    assert response.status_code == 422


def test_preprocess_missing_sidecar_returns_422(
    csv_bytes: bytes,
    bike_profile_bytes: bytes,
    event_schema_bytes: bytes,
) -> None:
    response = client.post(
        "/api/preprocess",
        files={
            "csv_file": ("ride.csv", csv_bytes, "text/csv"),
            "bike_profile_json": ("test_bike_profile.json", bike_profile_bytes, "application/json"),
            "event_schema_yaml": ("event_schema.yaml", event_schema_bytes, "application/yaml"),
        },
    )
    assert response.status_code == 422


def test_preprocess_missing_schema_returns_422(
    csv_bytes: bytes,
    sidecar_bytes: bytes,
    bike_profile_bytes: bytes,
) -> None:
    response = client.post(
        "/api/preprocess",
        files={
            "csv_file": ("ride.csv", csv_bytes, "text/csv"),
            "sidecar_json": ("ride_sidecar.json", sidecar_bytes, "application/json"),
            "bike_profile_json": ("test_bike_profile.json", bike_profile_bytes, "application/json"),
        },
    )
    assert response.status_code == 422


def test_preprocess_invalid_bike_profile_returns_422_or_500(
    csv_bytes: bytes,
    sidecar_bytes: bytes,
    event_schema_bytes: bytes,
) -> None:
    response = client.post(
        "/api/preprocess",
        files={
            "csv_file": ("ride.csv", csv_bytes, "text/csv"),
            "sidecar_json": ("ride_sidecar.json", sidecar_bytes, "application/json"),
            "bike_profile_json": ("bad.json", b'{"schema": "wrong"}', "application/json"),
            "event_schema_yaml": ("event_schema.yaml", event_schema_bytes, "application/yaml"),
        },
    )
    assert response.status_code in (422, 500)
