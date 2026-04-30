"""Shared pytest fixtures for the BODAQS API test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def csv_bytes() -> bytes:
    return (FIXTURES / "ride.csv").read_bytes()


@pytest.fixture(scope="session")
def sidecar_bytes() -> bytes:
    return (FIXTURES / "ride_sidecar.json").read_bytes()


@pytest.fixture(scope="session")
def bike_profile_bytes() -> bytes:
    return (FIXTURES / "test_bike_profile.json").read_bytes()


@pytest.fixture(scope="session")
def event_schema_bytes() -> bytes:
    return (FIXTURES / "event_schema.yaml").read_bytes()


@pytest.fixture(scope="session")
def preprocess_profile_bytes() -> bytes:
    """Real example preprocess profile (suspension_default_v1 from application/Examples)."""
    return (FIXTURES / "test_preprocess_profile.json").read_bytes()


@pytest.fixture(scope="session")
def bundled_profile_bytes() -> bytes:
    """The bundled default profile, loaded from the api package."""
    default = Path(__file__).parent.parent / "bodaqs_api" / "default_preprocess_profile.json"
    return default.read_bytes()
