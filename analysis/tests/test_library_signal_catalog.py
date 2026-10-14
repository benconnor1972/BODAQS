import json
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bodaqs_analysis.artifacts import ArtifactStore
from bodaqs_analysis.library_api import LibraryAdapter
from bodaqs_analysis.library_api.catalog_revision import touch_catalog_revision
from bodaqs_analysis.library_api.signal_catalog import build_library_signal_catalog
from bodaqs_analysis.library_api_service import create_app
import bodaqs_analysis.library_api.adapter as adapter_module


def _signal(**changes):
    return {
        "stream_name": "primary", "column": "travel", "unit": "mm",
        "display_name": "Wheel travel", "signal_id": "wheel-travel",
        "domain": "wheel", "quantity": "disp", "end": "rear", **changes,
    }


def _catalog(*rows):
    return {"library_id": "test", "rows": list(rows)}


def test_counts_distinct_sessions_and_keeps_streams_and_units_separate():
    a = _signal()
    result = build_library_signal_catalog(_catalog(
        {"session_key": "a", "available_signals": [a, a, _signal(end="front"), _signal(stream_name="native")]},
        {"session_key": "b", "available_signals": [a, _signal(unit="m")]},
        {"session_key": "c", "available_signals": []},
    ))
    by_key = {(s["stream_name"], s["column"], s["unit"]): s for s in result["signals"]}
    assert result["session_count"] == 3
    assert result["sessions_with_catalogued_signals"] == 2
    assert result["signal_count"] == 3
    assert by_key[("primary", "travel", "mm")]["session_count"] == 2
    assert by_key[("primary", "travel", "mm")]["session_fraction"] == pytest.approx(2 / 3)
    assert sum(v["session_count"] for v in by_key[("primary", "travel", "mm")]["metadata_variants"]) == 3
    assert by_key[("native", "travel", "mm")]["session_count"] == 1
    assert by_key[("primary", "travel", "m")]["session_count"] == 1


def test_aliases_and_conflicting_metadata_are_retained_without_guessing():
    result = build_library_signal_catalog(_catalog(
        {"session_key": "a", "available_signals": [_signal(display_name="Rear travel")]},
        {"session_key": "b", "available_signals": [_signal(end="front", signal_id="other")]},
    ))
    signal = result["signals"][0]
    assert signal["display_names"] == ["Rear travel", "Wheel travel"]
    assert signal["signal_ids"] == ["other", "wheel-travel"]
    assert "end" not in signal["metadata"]
    assert signal["metadata"]["quantity"] == "disp"
    assert {v["metadata"]["end"] for v in signal["metadata_variants"]} == {"front", "rear"}
    assert all(v["session_count"] == 1 and v["session_fraction"] == 0.5 for v in signal["metadata_variants"])


def test_empty_and_legacy_catalogs_and_duplicate_rows():
    empty = build_library_signal_catalog(_catalog())
    assert empty["session_count"] == empty["signal_count"] == 0
    assert empty["signals"] == []
    legacy = {"session_key": "a", "available_signals": [{"column": "raw"}]}
    result = build_library_signal_catalog(_catalog(legacy, legacy, {"session_key": "b"}))
    signal = result["signals"][0]
    assert result["session_count"] == 2
    assert signal["stream_name"] == "primary" and signal["unit"] is None
    assert signal["metadata"] == {}
    assert signal["session_count"] == 1 and signal["session_fraction"] == 0.5


def test_entry_ids_and_order_are_stable_when_catalog_order_changes():
    rows = [
        {"session_key": "a", "available_signals": [_signal(), _signal(column="altitude")]},
        {"session_key": "b", "available_signals": [_signal(end="front")]},
    ]
    assert build_library_signal_catalog(_catalog(*rows)) == build_library_signal_catalog(_catalog(*reversed(rows)))


def _library(root, library_id="test"):
    library = root / library_id
    library.mkdir(parents=True)
    (library / "library_definition.json").write_text(json.dumps({
        "library_id": library_id, "display_name": library_id,
    }), encoding="utf-8")
    return library


def _session(library, session_id, column="travel"):
    store = ArtifactStore(library)
    path = store.path_session_df("run", session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"time_s": [0.0, 1.0], column: [None, None]}).to_parquet(path)
    store.path_session_meta("run", session_id).write_text(json.dumps({
        "time_col": "time_s", "signals": {column: {"unit": "mm", "domain": "wheel", "quantity": "disp"}},
    }), encoding="utf-8")


def test_summary_reuses_catalog_and_refreshes_on_revision_and_explicit_refresh(tmp_path, monkeypatch):
    library = _library(tmp_path)
    _session(library, "a")
    adapter = LibraryAdapter(tmp_path)
    adapter.get_catalog("test")
    calls = []
    original = adapter_module.build_library_signal_catalog
    def build(catalog):
        calls.append(1)
        return original(catalog)
    monkeypatch.setattr(adapter_module, "build_library_signal_catalog", build)
    with monkeypatch.context() as context:
        context.setattr(pd, "read_parquet", lambda *args, **kwargs: pytest.fail("Summary read sample data"))
        first = adapter.get_signal_catalog("test")
        assert first["signals"][0]["session_count"] == 1
        first["signals"].clear()
        assert adapter.get_signal_catalog("test")["signal_count"] == 1
        assert len(calls) == 1
    _session(library, "b", "other")
    touch_catalog_revision(library, reason="test_import", actor="test")
    updated = adapter.get_signal_catalog("test")
    assert updated["session_count"] == 2 and updated["signal_count"] == 2
    assert updated["catalog_revision"] > first["catalog_revision"]
    _session(library, "c")
    assert adapter.get_signal_catalog("test")["session_count"] == 2
    adapter.get_catalog("test", refresh=True)
    refreshed = adapter.get_signal_catalog("test")
    assert refreshed["session_count"] == 3
    assert len(calls) == 3
    assert refreshed["signals"][1]["session_count"] == 2


def test_http_catalog_is_library_scoped_and_supports_read_only_service(tmp_path):
    first = _library(tmp_path, "first")
    second = _library(tmp_path, "second")
    _session(first, "a")
    _session(second, "b", "other")
    client = TestClient(create_app(tmp_path, read_only=True))
    response = client.get("/api/v1/libraries/first/signal-catalog")
    assert response.status_code == 200
    result = response.json()
    assert result["schema"] == "bodaqs.library_signal_catalog"
    assert result["scope"] == "whole_library" and result["availability_basis"] == "catalog_presence"
    assert result["library_id"] == "first" and result["signals"][0]["column"] == "travel"
    assert client.get("/api/v1/libraries/second/signal-catalog").json()["signals"][0]["column"] == "other"
    assert client.get("/api/v1/libraries/missing/signal-catalog").status_code == 404
    assert client.get("/api/v1/capabilities").json()["features"]["read_library_signal_catalog"] is True
