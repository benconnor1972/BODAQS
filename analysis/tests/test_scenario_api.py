import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from bodaqs_analysis.artifacts import ArtifactStore
from bodaqs_analysis.library_api import LibraryAdapter
from bodaqs_analysis.library_api.errors import InvalidScenarioError, RevisionConflictError
from bodaqs_analysis.library_api_service import create_app


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _library(tmp_path: Path) -> tuple[Path, Path, dict]:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default"
    _write_json(
        library_root / "library_definition.json",
        {
            "schema": "bodaqs.import_agent_library",
            "version": 1,
            "library_id": "default-library",
            "display_name": "Default",
            "artifacts_dir": str(library_root),
        },
    )
    ref = {
        "library_id": "default-library",
        "run_id": "run-1",
        "session_id": "session-1",
        "session_key": "run-1::session-1",
    }
    store = ArtifactStore(library_root)
    store.session_dir("run-1", "session-1").mkdir(parents=True, exist_ok=True)
    store.write_df(
        store.path_session_df("run-1", "session-1"),
        pd.DataFrame(
            {
                "time_s": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
                "gps_speed_mps": [1.0, 3.0, 4.0, 4.0, 1.0, 1.0],
                "active_mask_qc": [1, 1, 1, 0, 1, 1],
            }
        ),
    )
    store.write_json(
        store.path_session_meta("run-1", "session-1"),
        {
            "time_col": "time_s",
            "signals": {
                "gps_speed_mps": {"quantity": "speed", "source": "gps", "unit": "m/s"},
                "active_mask_qc": {"kind": "qc", "quantity": "mask"},
            },
        },
    )
    spatial = pd.DataFrame(
        {
            "distance_m": [0.0, 10.0, 20.0, 30.0, 40.0, 50.0],
            "representative_time_s": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
            "altitude_m": [100.0, 101.0, 102.0, None, 104.0, 105.0],
            "twistiness_rad_per_m": [0.0, 0.1, 0.2, None, 0.0, 0.0],
            "distance_support_fraction": [1.0, 1.0, 1.0, 0.0, 1.0, 1.0],
            "active_mask_qc": [1, 1, 1, 0, 1, 1],
        }
    )
    store.write_df(store.path_session_stream_df("run-1", "session-1", "spatial_context"), spatial)
    store.write_json(
        store.path_session_stream_meta("run-1", "session-1", "spatial_context"),
        {
            "schema": "bodaqs.spatial_context_stream",
            "version": 1,
            "status": "succeeded",
            "coordinate": {"column": "distance_m", "unit": "m", "spacing_m": 10.0},
            "time_mapping": {"column": "representative_time_s"},
            "signals": {
                "altitude_m": {"display_name": "Altitude", "quantity": "altitude", "unit": "m"},
                "twistiness_rad_per_m": {"display_name": "Twistiness", "unit": "rad/m"}
            },
            "warnings": [],
        },
    )
    return libraries_root, library_root, ref


def _scenario(column: str = "gps_speed_mps", stream: str = "primary") -> dict:
    return {
        "display_name": "Fast riding",
        "predicate": {
            "criterion_id": "fast",
            "series": {"stream_name": stream, "column": column},
            "op": "gte",
            "value": 2.0 if stream == "primary" else 0.1,
        },
    }


def test_scenario_crud_is_root_scoped_and_revision_safe(tmp_path: Path) -> None:
    libraries_root, _, _ = _library(tmp_path)
    adapter = LibraryAdapter(libraries_root)
    created = adapter.create_scenario(_scenario())
    assert created["scenario_id"] == "fast-riding"
    assert created["episode_policy"]["bridge_gap_s"] == 0.0
    assert adapter.list_scenarios()[0]["revision"] == 1

    updated = adapter.update_scenario(
        created["scenario_id"], expected_revision=1, payload={**created, "description": "Updated"}
    )
    assert updated["revision"] == 2
    with pytest.raises(RevisionConflictError):
        adapter.update_scenario(created["scenario_id"], expected_revision=1, payload=updated)


def test_scenario_rejects_more_than_four_criteria(tmp_path: Path) -> None:
    libraries_root, _, _ = _library(tmp_path)
    scenario = _scenario()
    scenario["predicate"] = {
        "op": "and",
        "children": [
            {"criterion_id": f"c{i}", "series": {"stream_name": "primary", "column": "gps_speed_mps"}, "op": "gte", "value": i}
            for i in range(5)
        ],
    }
    with pytest.raises(InvalidScenarioError):
        LibraryAdapter(libraries_root).create_scenario(scenario)


def test_spatial_context_window_returns_native_distance_and_gaps(tmp_path: Path) -> None:
    libraries_root, _, ref = _library(tmp_path)
    response = LibraryAdapter(libraries_root).get_spatial_context_window(
        "default-library",
        {"session": ref, "metrics": ["twistiness_rad_per_m"], "window": {"start_m": 10, "end_m": 40}},
    )
    assert response["distance"]["values"] == [10.0, 20.0, 30.0, 40.0]
    assert response["time_mapping"]["values"] == [1.0, 2.0, 3.0, 4.0]
    assert response["metrics"][0]["values"] == [0.1, 0.2, None, 0.0]


def test_spatial_context_window_returns_mapped_altitude(tmp_path: Path) -> None:
    libraries_root, _, ref = _library(tmp_path)
    response = LibraryAdapter(libraries_root).get_spatial_context_window(
        "default-library",
        {"session": ref, "metrics": ["altitude_m"]},
    )

    assert response["metrics"][0]["column"] == "altitude_m"
    assert response["metrics"][0]["values"] == [100.0, 101.0, 102.0, None, 104.0, 105.0]


def test_scenario_evaluation_respects_activity_and_support_gaps(tmp_path: Path) -> None:
    libraries_root, _, ref = _library(tmp_path)
    response = LibraryAdapter(libraries_root).evaluate_scenario(
        {"scenario": _scenario(), "sessions": [ref]}
    )
    assert response["status"] == "succeeded"
    assert response["summary"]["episode_count"] == 1
    episode = response["sessions"][0]["episodes"][0]
    assert episode["start_time_s"] == pytest.approx(0.5)
    assert episode["end_time_s"] == pytest.approx(2.5)

    spatial_response = LibraryAdapter(libraries_root).evaluate_scenario(
        {"scenario": _scenario("twistiness_rad_per_m", "spatial_context"), "sessions": [ref]}
    )
    assert spatial_response["summary"]["episode_count"] == 1
    assert spatial_response["sessions"][0]["episodes"][0]["end_time_s"] == pytest.approx(2.5)


def test_scenario_evaluation_cache_identity_tracks_input_artifacts(tmp_path: Path) -> None:
    libraries_root, library_root, ref = _library(tmp_path)
    request = {"scenario": _scenario(), "sessions": [ref]}
    first = LibraryAdapter(libraries_root).evaluate_scenario(request)
    meta_path = ArtifactStore(library_root).path_session_meta("run-1", "session-1")
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    metadata["test_revision"] = 2
    _write_json(meta_path, metadata)
    second = LibraryAdapter(libraries_root).evaluate_scenario(request)
    assert second["evaluation_id"] != first["evaluation_id"]
    assert second["provenance"]["input_artifacts"]


def test_scenario_http_routes(tmp_path: Path) -> None:
    libraries_root, _, ref = _library(tmp_path)
    client = TestClient(create_app(libraries_root))
    created = client.post("/api/v1/scenarios", json={"scenario": _scenario()})
    assert created.status_code == 200
    evaluated = client.post(
        "/api/v1/scenario-evaluations",
        json={"scenario_ref": {"scenario_id": created.json()["scenario_id"], "revision": 1}, "sessions": [ref]},
    )
    assert evaluated.status_code == 200
    spatial = client.post(
        "/api/v1/libraries/default-library/sessions/spatial-context/window",
        json={"session": ref, "metrics": ["twistiness_rad_per_m"]},
    )
    assert spatial.status_code == 200
