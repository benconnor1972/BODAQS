import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import bodaqs_analysis.library_api.adapter as adapter_module
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
            "secondary_streams": {
                "gps_logger": {
                    "stream_name": "gps_logger",
                    "kind": "intermittent",
                    "signals": {
                        "speed_mps": {"quantity": "speed", "source": "logger_gps", "unit": "m/s"},
                    },
                },
            },
        },
    )
    store.write_df(
        store.path_session_stream_df("run-1", "session-1", "gps_logger"),
        pd.DataFrame({"time_s": [0.0, 2.0, 4.0], "speed_mps": [1.0, 4.0, 1.0]}),
    )
    store.write_json(
        store.path_session_stream_meta("run-1", "session-1", "gps_logger"),
        {
            "stream_name": "gps_logger",
            "kind": "intermittent",
            "signals": {
                "speed_mps": {"quantity": "speed", "source": "logger_gps", "unit": "m/s"},
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


def test_scenario_evaluation_uses_native_registered_gps_stream(tmp_path: Path) -> None:
    libraries_root, _, ref = _library(tmp_path)
    scenario = {
        "display_name": "Fast GPS",
        "predicate": {
            "criterion_id": "fast",
            "series": {"stream_name": "gps_logger", "column": "speed_mps"},
            "op": "gte",
            "value": 2.0,
        },
        "eligibility_policy": {"activity": "ignore"},
    }

    response = LibraryAdapter(libraries_root).evaluate_scenario({"scenario": scenario, "sessions": [ref]})

    result = response["sessions"][0]
    assert result["status"] == "succeeded"
    assert result["episode_count"] == 1
    assert result["episodes"][0]["start_time_s"] == pytest.approx(1.0)
    assert result["episodes"][0]["end_time_s"] == pytest.approx(3.0)
    assert result["criteria"][0]["resolved_series"] == {
        "stream_name": "gps_logger",
        "column": "speed_mps",
        "unit": "m/s",
        "coordinate_column": "time_s",
        "coordinate_unit": "s",
    }


def test_scenario_evaluation_reuses_activity_index_across_scenarios(tmp_path: Path) -> None:
    libraries_root, _, ref = _library(tmp_path)
    adapter = LibraryAdapter(libraries_root)
    adapter.evaluate_scenario({"scenario": _scenario(), "sessions": [ref]})
    slower = _scenario()
    slower["display_name"] = "Slower riding"
    slower["predicate"]["value"] = 1.0
    adapter.evaluate_scenario({"scenario": slower, "sessions": [ref]})

    events = adapter.cache_diagnostics()["activity_index_cache"]["event_counts"]
    assert events["built"] == 1
    assert events["memory_hit"] == 1


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


def test_scenario_evaluation_reuses_cached_sessions_when_scope_grows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    libraries_root, library_root, first_ref = _library(tmp_path)
    store = ArtifactStore(library_root)
    shutil.copytree(
        store.session_dir("run-1", "session-1"),
        store.session_dir("run-1", "session-2"),
    )
    second_ref = {
        "library_id": "default-library",
        "run_id": "run-1",
        "session_id": "session-2",
        "session_key": "run-1::session-2",
    }
    direct_evaluate = adapter_module.evaluate_scenario
    evaluated_sessions: list[str] = []

    def counted_evaluate(request: dict, **kwargs: object) -> dict:
        evaluated_sessions.extend(str(item["session_id"]) for item in request["sessions"])
        return direct_evaluate(request, **kwargs)

    monkeypatch.setattr(adapter_module, "evaluate_scenario", counted_evaluate)
    adapter = LibraryAdapter(libraries_root)
    first = adapter.evaluate_scenario({"scenario": _scenario(), "sessions": [first_ref]})
    adapter = LibraryAdapter(libraries_root)
    expanded = adapter.evaluate_scenario({"scenario": _scenario(), "sessions": [first_ref, second_ref]})

    assert first["summary"]["requested_session_count"] == 1
    assert expanded["summary"]["requested_session_count"] == 2
    assert [item["session_ref"]["session_id"] for item in expanded["sessions"]] == ["session-1", "session-2"]
    assert first["sessions"][0]["episodes"][0]["episode_id"] != expanded["sessions"][0]["episodes"][0]["episode_id"]
    assert evaluated_sessions == ["session-1", "session-2"]
    expanded_timing = next(
        item for item in reversed(adapter.cache_diagnostics()["timings"])
        if item["operation"] == "scenario_evaluation"
    )
    assert expanded_timing["session_persistent_hits"] == 1
    assert expanded_timing["session_misses"] == 1

    second_meta_path = store.path_session_meta("run-1", "session-2")
    second_metadata = json.loads(second_meta_path.read_text(encoding="utf-8"))
    second_metadata["test_revision"] = 2
    _write_json(second_meta_path, second_metadata)
    refreshed = adapter.evaluate_scenario({"scenario": _scenario(), "sessions": [first_ref, second_ref]})

    assert refreshed["evaluation_id"] != expanded["evaluation_id"]
    assert evaluated_sessions == ["session-1", "session-2", "session-2"]
    scenario_timings = [
        item for item in adapter.cache_diagnostics()["timings"]
        if item["operation"] == "scenario_evaluation"
    ]
    assert scenario_timings[-1]["cache_status"] == "composed"
    assert scenario_timings[-1]["session_memory_hits"] == 1
    assert scenario_timings[-1]["session_misses"] == 1


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
