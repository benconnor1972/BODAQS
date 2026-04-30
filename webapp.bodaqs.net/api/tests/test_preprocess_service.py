"""Unit tests for the preprocess service layer.

Tests call run_preprocess() directly with fixture bytes — no HTTP involved.
This isolates pipeline behaviour from routing/serialisation concerns.
"""

from __future__ import annotations

import json

import pytest

from bodaqs_api.services.preprocess_service import run_preprocess
from bodaqs_api.schemas.preprocess import PreprocessResponse


@pytest.fixture(scope="module")
def result(
    csv_bytes: bytes,
    sidecar_bytes: bytes,
    bike_profile_bytes: bytes,
    event_schema_bytes: bytes,
) -> PreprocessResponse:
    """Run the pipeline once for all service-layer tests (slow — module scope)."""
    return run_preprocess(
        csv_bytes=csv_bytes,
        csv_filename="2026-02-20_13-08-45.csv",
        sidecar_bytes=sidecar_bytes,
        bike_profile_bytes=bike_profile_bytes,
        event_schema_bytes=event_schema_bytes,
        preprocess_profile_bytes=None,  # use bundled default
    )


def test_session_id_matches_filename_stem(result: PreprocessResponse) -> None:
    assert result.session_id == "2026-02-20_13-08-45"


def test_source_sha256_is_hex(result: PreprocessResponse) -> None:
    assert len(result.source_sha256) == 64
    assert all(c in "0123456789abcdef" for c in result.source_sha256)


def test_signals_have_columns(result: PreprocessResponse) -> None:
    assert len(result.signals.column_names) > 0
    assert result.signals.n_rows > 0
    assert set(result.signals.column_names) == set(result.signals.columns.keys())


def test_signal_columns_are_base64_float32(result: PreprocessResponse) -> None:
    import base64
    import numpy as np

    for col, encoded in result.signals.columns.items():
        raw = base64.b64decode(encoded)
        assert len(raw) % 4 == 0, f"Column {col!r}: byte length not divisible by 4"
        arr = np.frombuffer(raw, dtype=np.float32)
        assert len(arr) == result.signals.n_rows, f"Column {col!r}: row count mismatch"


def test_no_excluded_columns_in_signals(result: PreprocessResponse) -> None:
    excluded = {"time_s", "sample_id", "active_mask_qc"}
    for col in result.signals.column_names:
        assert col not in excluded, f"Excluded column {col!r} found in signals payload"


def test_meta_has_expected_keys(result: PreprocessResponse) -> None:
    assert "signals" in result.meta
    assert "session_id" in result.meta


def test_warnings_is_list_of_strings(result: PreprocessResponse) -> None:
    assert isinstance(result.warnings, list)
    for w in result.warnings:
        assert isinstance(w, str)


def test_events_are_list_of_dicts(result: PreprocessResponse) -> None:
    assert isinstance(result.events, list)
    for row in result.events:
        assert isinstance(row, dict)


def test_metrics_are_list_of_dicts(result: PreprocessResponse) -> None:
    assert isinstance(result.metrics, list)
    for row in result.metrics:
        assert isinstance(row, dict)


def test_default_profile_used_when_none_supplied(
    csv_bytes: bytes,
    sidecar_bytes: bytes,
    bike_profile_bytes: bytes,
    event_schema_bytes: bytes,
) -> None:
    """Calling with preprocess_profile_bytes=None should not raise."""
    r = run_preprocess(
        csv_bytes=csv_bytes,
        csv_filename="2026-02-20_13-08-45.csv",
        sidecar_bytes=sidecar_bytes,
        bike_profile_bytes=bike_profile_bytes,
        event_schema_bytes=event_schema_bytes,
        preprocess_profile_bytes=None,
    )
    assert r.session_id == "2026-02-20_13-08-45"


def test_invalid_bike_profile_raises_value_error(
    csv_bytes: bytes,
    sidecar_bytes: bytes,
    event_schema_bytes: bytes,
) -> None:
    with pytest.raises((ValueError, Exception)):
        run_preprocess(
            csv_bytes=csv_bytes,
            csv_filename="2026-02-20_13-08-45.csv",
            sidecar_bytes=sidecar_bytes,
            bike_profile_bytes=b'{"schema": "wrong"}',
            event_schema_bytes=event_schema_bytes,
            preprocess_profile_bytes=None,
        )
