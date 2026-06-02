import json
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ANALYSIS_ROOT = _REPO_ROOT / "analysis"
if str(_ANALYSIS_ROOT) not in sys.path:
    sys.path.insert(0, str(_ANALYSIS_ROOT))

from bodaqs_analysis.library_api import (
    InvalidRequestError,
    InvalidStudySetError,
    LibraryAdapter,
    LibraryNotFoundError,
    RevisionConflictError,
    SignalNotFoundError,
    StudySetNotFoundError,
    TimeseriesUnavailableError,
    derive_object_id,
    export_library_fixture,
    make_session_key,
    make_session_ref_id,
    make_unique_object_id,
    parse_session_key,
)
from bodaqs_analysis.library_api.catalog import discover_libraries
from bodaqs_analysis.library_api_service import create_app
from bodaqs_analysis.widgets.contracts import EntitySelectionSnapshot, SelectionSnapshot


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _make_library_definition(
    library_root: Path,
    *,
    library_id: str,
    display_name: str,
) -> None:
    _write_json(
        library_root / "library_definition.json",
        {
            "schema": "bodaqs.import_agent_library",
            "version": 1,
            "library_id": library_id,
            "display_name": display_name,
            "artifacts_dir": str(library_root),
        },
    )


def _make_session(
    library_root: Path,
    run_id: str,
    session_id: str,
    *,
    library_id: str = "default-library",
) -> dict:
    (library_root / "runs" / run_id / "sessions" / session_id).mkdir(parents=True)
    session_key = make_session_key(run_id, session_id)
    return {
        "library_id": library_id,
        "run_id": run_id,
        "session_id": session_id,
        "session_key": session_key,
        "session_ref_id": make_session_ref_id(library_id, session_key),
    }


def _write_catalog_fixture_session(library_root: Path, *, library_id: str = "default-library") -> dict:
    run_id = "run_2026-05-25T13-57-10_LOCAL"
    session_id = "2026-05-18_13-27-14"
    session_ref = _make_session(library_root, run_id, session_id, library_id=library_id)
    session_root = library_root / "runs" / run_id / "sessions" / session_id

    _write_json(
        library_root / "runs" / run_id / "manifest.json",
        {
            "run_id": run_id,
            "created_at": "2026-05-25T13:57:10",
            "description": "Prototype F import",
            "pipeline_config": {
                "import_source": {
                    "source_id": "prototype-f",
                    "source_type": "logger_wifi",
                },
                "archive_import": {
                    "processing_key": "processing-key-1",
                },
            },
        },
    )
    _write_json(
        session_root / "manifest.json",
        {
            "session_id": session_id,
            "description": "Rough descent",
            "source": {
                "import_source_id": "prototype-f",
                "import_source_type": "logger_wifi",
                "original_archive_filename": "2026-02-19_09-43-31_3.zip",
                "processing_key": "processing-key-1",
                "remote_source": {"logger_id": "Prototype F"},
            },
            "summary": {"n_rows": 3, "t_start_s": 0.0, "t_end_s": 2.0},
        },
    )
    _write_json(
        session_root / "session" / "meta.json",
        {
            "t0_datetime": "2026-05-18T05:27:14Z",
            "qc": {"warnings": ["fit_import_failed"]},
            "signals": {
                "time_s": {
                    "quantity": "time",
                    "unit": "s",
                    "domain": "time",
                },
                "front_wheel_disp_dom_wheel [mm]": {
                    "end": "front",
                    "domain": "wheel",
                    "quantity": "disp",
                    "unit": "mm",
                    "processing_role": "primary_analysis",
                    "origin": "analysis",
                },
                "rear_wheel_disp_dom_wheel [mm]": {
                    "end": "rear",
                    "domain": "wheel",
                    "quantity": "disp",
                    "unit": "mm",
                    "processing_role": "primary_analysis",
                    "origin": "analysis",
                },
                "active_mask_qc": {
                    "kind": "qc",
                    "quantity": "mask",
                    "unit": None,
                },
            },
        },
    )
    (session_root / "session").mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "time_s": [0.0, 1.0, 2.0],
            "front_wheel_disp_dom_wheel [mm]": [0.0, 10.0, 20.0],
            "rear_wheel_disp_dom_wheel [mm]": [0.0, 12.0, 24.0],
            "active_mask_qc": [True, True, True],
        }
    ).to_parquet(session_root / "session" / "df.parquet", index=False)
    _write_json(
        session_root / "annotations" / "session_notes.json",
        {
            "schema": "bodaqs.session_notes.document",
            "version": 1,
            "run_id": run_id,
            "session_id": session_id,
            "session_key": session_ref["session_key"],
            "template_id": "suspension_setup",
            "template_version": "1.0",
            "title": "Setup notes",
            "values": {"bike": "Prototype F", "rider": "Ben"},
            "custom_values": {},
            "free_text_notes": None,
            "created_at_utc": "2026-05-25T05:57:10Z",
            "updated_at_utc": "2026-05-25T05:57:10Z",
            "draft": True,
        },
    )
    events_root = session_root / "events"
    (events_root / "bottom_out").mkdir(parents=True)
    (events_root / "jump").mkdir(parents=True)
    pd.DataFrame(
        {
            "event_id": ["bottom_out:front:1"],
            "schema_id": ["bottom_out"],
            "event_name": ["Bottom out"],
            "start_time_s": [0.5],
            "end_time_s": [0.7],
        }
    ).to_parquet(events_root / "bottom_out" / "events.parquet", index=False)
    pd.DataFrame(
        {
            "event_id": ["jump:front:1", "jump:rear:1"],
            "schema_id": ["jump", "jump"],
            "event_name": ["Jump", "Jump"],
            "start_time_s": [1.0, 1.5],
            "end_time_s": [1.2, 1.7],
        }
    ).to_parquet(events_root / "jump" / "events.parquet", index=False)
    metrics_root = session_root / "metrics" / "bottom_out"
    metrics_root.mkdir(parents=True)
    pd.DataFrame(
        {
            "session_id": [session_id],
            "event_id": ["bottom_out:front:1"],
            "schema_id": ["bottom_out"],
            "peak_force": [123.0],
            "duration_s": [0.2],
        }
    ).to_parquet(metrics_root / "metrics.parquet", index=False)
    return session_ref


def _write_gps_fit_stream(
    library_root: Path,
    session_ref: dict,
    *,
    times: list[float],
) -> None:
    stream_root = (
        library_root
        / "runs"
        / session_ref["run_id"]
        / "sessions"
        / session_ref["session_id"]
        / "session"
        / "streams"
        / "gps_fit"
    )
    _write_json(
        stream_root / "meta.json",
        {
            "kind": "intermittent",
            "stream_name": "gps_fit",
            "time_col": "time_s",
            "channel_info": {
                "gps_fit_position_latitude_dom_world [deg]": {
                    "role": "position_latitude",
                    "quantity": "latitude",
                    "unit": "deg",
                },
                "gps_fit_position_longitude_dom_world [deg]": {
                    "role": "position_longitude",
                    "quantity": "longitude",
                    "unit": "deg",
                },
                "gps_fit_altitude_dom_world [m]": {
                    "role": "altitude",
                    "quantity": "altitude",
                    "unit": "m",
                },
            },
        },
    )
    pd.DataFrame(
        {
            "time_s": times,
            "gps_fit_position_latitude_dom_world [deg]": [-31.95 - (index * 0.0001) for index, _ in enumerate(times)],
            "gps_fit_position_longitude_dom_world [deg]": [115.86 + (index * 0.0001) for index, _ in enumerate(times)],
            "gps_fit_altitude_dom_world [m]": [200.0 + index for index, _ in enumerate(times)],
        }
    ).to_parquet(stream_root / "df.parquet", index=False)


def test_derive_object_id_from_display_name() -> None:
    assert derive_object_id("Setup Comparison 1") == "setup-comparison-1"
    assert derive_object_id("Ben's Stévo / Prototype F!") == "ben-s-stevo-prototype-f"
    assert derive_object_id("!!!", fallback="Study Set") == "study-set"
    assert derive_object_id("A" * 100, max_length=12) == "a" * 12


def test_make_unique_object_id_adds_suffix() -> None:
    assert make_unique_object_id("Setup", {"setup", "setup-2"}) == "setup-3"
    assert make_unique_object_id("A" * 20, {"a" * 10}, max_length=10) == "aaaaaaaa-2"


def test_session_key_helpers() -> None:
    key = make_session_key("run_1", "session_2")
    assert key == "run_1::session_2"
    assert parse_session_key(key) == ("run_1", "session_2")
    with pytest.raises(ValueError):
        parse_session_key("not-a-session-key")


def test_discover_libraries_reads_library_definition(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )

    discovered = discover_libraries(libraries_root)

    assert len(discovered) == 1
    library = discovered[0]
    assert library["library_id"] == "default-library"
    assert library["display_name"] == "Default Library"
    assert library["root"] == str(library_root.resolve())
    assert library["definition_schema"] == "bodaqs.import_agent_library"
    assert library["capabilities"]["read_processed_library"] is True


def test_discover_libraries_falls_back_to_runs_directory(tmp_path: Path) -> None:
    library_root = tmp_path / "libraries" / "Loose Library"
    (library_root / "runs" / "run_1").mkdir(parents=True)
    (tmp_path / "libraries" / "not-a-library").mkdir(parents=True)

    discovered = discover_libraries(tmp_path / "libraries")

    assert [library["library_id"] for library in discovered] == ["loose-library"]
    assert discovered[0]["display_name"] == "Loose Library"


def test_discover_libraries_rejects_missing_root(tmp_path: Path) -> None:
    with pytest.raises(InvalidRequestError) as exc:
        discover_libraries(tmp_path / "missing")

    assert exc.value.code == "invalid_request"
    assert "libraries_root" in exc.value.details


def test_discover_libraries_rejects_duplicate_library_ids(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    _make_library_definition(
        libraries_root / "one",
        library_id="shared",
        display_name="One",
    )
    _make_library_definition(
        libraries_root / "two",
        library_id="shared",
        display_name="Two",
    )

    with pytest.raises(InvalidRequestError) as exc:
        discover_libraries(libraries_root)

    assert exc.value.details["library_id"] == "shared"


def test_library_adapter_capabilities_and_lookup(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    _make_library_definition(
        libraries_root / "default-library",
        library_id="default-library",
        display_name="Default Library",
    )

    adapter = LibraryAdapter(libraries_root)

    capabilities = adapter.capabilities()
    assert capabilities["schema"] == "bodaqs.library_api_capabilities"
    assert capabilities["required"]["read_parquet"] is True
    assert capabilities["features"]["run_processing_jobs"] is False

    libraries = adapter.list_libraries()
    assert [library["library_id"] for library in libraries] == ["default-library"]
    assert adapter.get_library("default-library")["display_name"] == "Default Library"

    with pytest.raises(LibraryNotFoundError) as exc:
        adapter.get_library("unknown")

    assert exc.value.code == "library_not_found"
    assert exc.value.details["library_id"] == "unknown"


def test_library_adapter_refresh_updates_library_cache(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    adapter = LibraryAdapter(libraries_root)

    (libraries_root).mkdir(parents=True)
    assert adapter.list_libraries() == []

    _make_library_definition(
        libraries_root / "new-library",
        library_id="new-library",
        display_name="New Library",
    )

    assert adapter.list_libraries() == []
    refreshed = adapter.list_libraries(refresh=True)
    assert [library["library_id"] for library in refreshed] == ["new-library"]


def test_library_adapter_creates_loads_lists_and_deletes_study_set(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _make_session(library_root, "run_1", "session_1")
    adapter = LibraryAdapter(libraries_root)

    created = adapter.create_study_set(
        "default-library",
        {
            "display_name": "Setup Comparison",
            "sessions": [session_ref],
        },
    )

    study_set_path = libraries_root / "study_sets" / "setup-comparison.json"
    assert created["schema"] == "bodaqs.study_set"
    assert created["version"] == 1
    assert created["study_set_id"] == "setup-comparison"
    assert created["revision"] == 1
    assert created["sessions"] == [session_ref]
    assert study_set_path.exists()

    assert adapter.list_study_sets("default-library") == [
        {
            "study_set_id": "setup-comparison",
            "display_name": "Setup Comparison",
            "revision": 1,
            "updated_at": created["provenance"]["updated_at"],
            "session_count": 1,
            "library_count": 1,
            "grouping_count": 0,
            "track_count": 0,
            "path": str(study_set_path),
        }
    ]
    assert adapter.load_study_set("default-library", "setup-comparison") == created

    assert adapter.delete_study_set("default-library", "setup-comparison") == {
        "deleted": True,
        "study_set_id": "setup-comparison",
    }
    with pytest.raises(StudySetNotFoundError):
        adapter.load_study_set("default-library", "setup-comparison")


def test_library_adapter_reads_and_migrates_legacy_study_set_location(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _make_session(library_root, "run_1", "session_1")
    legacy_path = libraries_root / "library" / "study_sets" / "legacy-study-set.json"
    _write_json(
        legacy_path,
        {
            "schema": "bodaqs.study_set",
            "version": 1,
            "study_set_id": "legacy-study-set",
            "display_name": "Legacy Study Set",
            "revision": 1,
            "sessions": [session_ref],
            "groupings": [],
            "bookmarks": [],
            "tracks": [],
            "provenance": {
                "created_at": "2026-06-01T00:00:00Z",
                "created_by": "test",
                "created_from": {"kind": "manual_selection", "details": {}},
                "updated_at": "2026-06-01T00:00:00Z",
            },
            "display_state": {"bodaqs_web_v1": {}},
        },
    )
    adapter = LibraryAdapter(libraries_root)

    assert adapter.list_study_sets()[0]["path"] == str(legacy_path)
    loaded = adapter.load_study_set("legacy-study-set")
    assert loaded["display_name"] == "Legacy Study Set"

    loaded["display_name"] = "Migrated Study Set"
    updated = adapter.update_study_set(
        "legacy-study-set",
        expected_revision=1,
        payload=loaded,
    )

    canonical_path = libraries_root / "study_sets" / "legacy-study-set.json"
    assert updated["revision"] == 2
    assert canonical_path.exists()
    assert not legacy_path.exists()


def test_library_adapter_creates_unique_study_set_ids(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _make_session(library_root, "run_1", "session_1")
    adapter = LibraryAdapter(libraries_root)

    first = adapter.create_study_set(
        "default-library",
        {"display_name": "Setup Comparison", "sessions": [session_ref]},
    )
    second = adapter.create_study_set(
        "default-library",
        {"display_name": "Setup Comparison", "sessions": [session_ref]},
    )

    assert first["study_set_id"] == "setup-comparison"
    assert second["study_set_id"] == "setup-comparison-2"


def test_library_adapter_study_sets_can_span_libraries(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    first_library = libraries_root / "default-library"
    second_library = libraries_root / "second-library"
    _make_library_definition(
        first_library,
        library_id="default-library",
        display_name="Default Library",
    )
    _make_library_definition(
        second_library,
        library_id="second-library",
        display_name="Second Library",
    )
    first_ref = _make_session(first_library, "run_1", "session_1", library_id="default-library")
    second_ref = _make_session(second_library, "run_2", "session_2", library_id="second-library")
    adapter = LibraryAdapter(libraries_root)

    created = adapter.create_study_set(
        {
            "display_name": "Cross Library Comparison",
            "sessions": [first_ref, second_ref],
            "groupings": [
                {
                    "grouping_id": "comparison",
                    "display_name": "Comparison",
                    "session_refs": [first_ref["session_ref_id"], second_ref["session_ref_id"]],
                }
            ],
        },
    )

    assert created["study_set_id"] == "cross-library-comparison"
    assert {session["library_id"] for session in created["sessions"]} == {
        "default-library",
        "second-library",
    }
    assert created["groupings"][0]["session_refs"] == [
        first_ref["session_ref_id"],
        second_ref["session_ref_id"],
    ]
    assert adapter.list_study_sets()[0]["library_count"] == 2


def test_library_adapter_updates_study_set_with_revision_check(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _make_session(library_root, "run_1", "session_1")
    adapter = LibraryAdapter(libraries_root)
    created = adapter.create_study_set(
        "default-library",
        {"display_name": "Setup Comparison", "sessions": [session_ref]},
    )

    updated = adapter.update_study_set(
        "default-library",
        "setup-comparison",
        expected_revision=1,
        payload={
            "display_name": "Setup Comparison Edited",
            "sessions": [session_ref],
            "groupings": [
                {
                    "grouping_id": "baseline",
                    "display_name": "Baseline",
                    "sessions": [session_ref],
                }
            ],
            "bookmarks": [
                {
                    "bookmark_id": "start",
                    "display_name": "Start",
                    "session": session_ref,
                    "time_s": 0.0,
                }
            ],
            "tracks": [
                {
                    "track_id": "test-track",
                    "from_point_id": "gate-a",
                    "to_point_id": "gate-b",
                }
            ],
        },
    )

    assert updated["revision"] == 2
    assert updated["display_name"] == "Setup Comparison Edited"
    assert updated["provenance"]["created_at"] == created["provenance"]["created_at"]
    assert updated["provenance"]["created_by"] == created["provenance"]["created_by"]

    with pytest.raises(RevisionConflictError) as exc:
        adapter.update_study_set(
            "default-library",
            "setup-comparison",
            expected_revision=1,
            payload={"display_name": "Stale Update", "sessions": [session_ref]},
        )

    assert exc.value.details["current_revision"] == 2


def test_create_study_set_rejects_missing_session(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    adapter = LibraryAdapter(libraries_root)
    missing_session = {
        "library_id": "default-library",
        "run_id": "run_missing",
        "session_id": "session_missing",
        "session_key": make_session_key("run_missing", "session_missing"),
    }
    missing_session["session_ref_id"] = make_session_ref_id(
        missing_session["library_id"],
        missing_session["session_key"],
    )

    with pytest.raises(InvalidStudySetError) as exc:
        adapter.create_study_set(
            "default-library",
            {"display_name": "Broken", "sessions": [missing_session]},
        )

    assert exc.value.code == "invalid_study_set"
    assert exc.value.details["session_key"] == "run_missing::session_missing"
    assert exc.value.details["session_ref_id"] == "default-library|||run_missing::session_missing"


def test_create_study_set_rejects_grouping_outside_top_level_sessions(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _make_session(library_root, "run_1", "session_1")
    other_session_ref = _make_session(library_root, "run_1", "session_2")
    adapter = LibraryAdapter(libraries_root)

    with pytest.raises(InvalidStudySetError) as exc:
        adapter.create_study_set(
            "default-library",
            {
                "display_name": "Broken Grouping",
                "sessions": [session_ref],
                "groupings": [
                    {
                        "grouping_id": "outside",
                        "display_name": "Outside",
                        "sessions": [other_session_ref],
                    }
                ],
            },
        )

    assert exc.value.details["session_ref_id"] == other_session_ref["session_ref_id"]


def test_create_study_set_validates_bookmark_shape(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _make_session(library_root, "run_1", "session_1")
    adapter = LibraryAdapter(libraries_root)

    with pytest.raises(InvalidStudySetError):
        adapter.create_study_set(
            "default-library",
            {
                "display_name": "Broken Bookmark",
                "sessions": [session_ref],
                "bookmarks": [
                    {
                        "bookmark_id": "ambiguous",
                        "display_name": "Ambiguous",
                        "session": session_ref,
                        "time_s": 1.0,
                        "time_window": {"start_s": 0.0, "end_s": 2.0},
                    }
                ],
            },
        )

    valid = adapter.create_study_set(
        "default-library",
        {
            "display_name": "Valid Bookmark",
            "sessions": [session_ref],
            "bookmarks": [
                {
                    "bookmark_id": "window",
                    "display_name": "Window",
                    "session": session_ref,
                    "time_window": {"start_s": 0.0, "end_s": 2.0},
                }
            ],
        },
    )

    assert valid["bookmarks"][0]["bookmark_id"] == "window"


def test_library_adapter_builds_catalog_rows_from_artifacts(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    adapter = LibraryAdapter(libraries_root)

    catalog = adapter.get_catalog("default-library")

    assert catalog["schema"] == "bodaqs.session_catalog"
    assert catalog["version"] == 1
    assert catalog["library_id"] == "default-library"
    assert catalog["row_count"] == 1
    row = catalog["rows"][0]
    assert row["schema"] == "bodaqs.session_catalog_row"
    assert row["library_id"] == "default-library"
    assert row["session_key"] == session_ref["session_key"]
    assert row["session_ref_id"] == session_ref["session_ref_id"]
    assert row["display"]["label"] == "Prototype F - Rough descent"
    assert row["timestamps"]["started_at_utc"] == "2026-05-18T05:27:14Z"
    assert row["timestamps"]["processed_at"] == "2026-05-25T13:57:10"
    assert row["note_status"]["status"] == "draft"
    assert row["note_status"]["template_id"] == "suspension_setup"
    assert row["note_fields"] == {"bike": "Prototype F", "rider": "Ben"}
    assert row["qc_summary"] == {
        "status": "warning",
        "warning_count": 1,
        "error_count": 0,
    }
    assert row["provenance"] == {
        "source_type": "logger_wifi",
        "source_id": "prototype-f",
        "logger_id": "Prototype F",
        "archive_name": "2026-02-19_09-43-31_3.zip",
        "processing_key": "processing-key-1",
    }
    assert row["event_schema"]["schema_id"] is None
    assert row["event_schema"]["schema_ids"] == ["bottom_out", "jump"]
    assert row["event_summary"]["total_count"] == 3
    assert row["event_summary"]["by_type"] == {"bottom_out": 1, "jump": 2}
    assert row["metric_summary"] == {
        "metric_count": 2,
        "event_count_with_metrics": 1,
        "schema_ids": ["bottom_out"],
    }

    signal_columns = {signal["column"] for signal in row["available_signals"]}
    assert signal_columns == {
        "front_wheel_disp_dom_wheel [mm]",
        "rear_wheel_disp_dom_wheel [mm]",
        "time_s",
    }
    front_signal = next(
        signal
        for signal in row["available_signals"]
        if signal["column"] == "front_wheel_disp_dom_wheel [mm]"
    )
    assert front_signal["signal_id"] == "front-wheel-disp-mm"
    assert front_signal["display_name"] == "Front Wheel Disp"
    assert front_signal["processing_role"] == "primary_analysis"


def test_library_adapter_catalog_reports_gps_summary_quality(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    _write_gps_fit_stream(library_root, session_ref, times=[-100.0, 0.0, 2.0, 100.0])
    adapter = LibraryAdapter(libraries_root)

    summary = adapter.get_catalog("default-library")["rows"][0]["gps_summary"]

    assert summary["schema"] == "bodaqs.session_gps_summary"
    assert summary["present"] is True
    assert summary["preferred_source"] == "fit_enrichment"
    assert summary["position_point_count"] == 2
    assert summary["quality"] == "limited"
    assert "gps_low_point_count" in summary["warnings"]
    assert summary == adapter.get_session_gps_summary("default-library", session_ref)

    points = adapter.get_session_gps_points(
        "default-library",
        {
            **session_ref,
            "max_points": 2,
        },
    )
    assert points["schema"] == "bodaqs.session_gps_points"
    assert points["present"] is True
    assert points["source"]["kind"] == "fit_enrichment"
    assert points["sampling"]["source_points"] == 2
    assert points["sampling"]["returned_points"] == 2
    assert [point["time_s"] for point in points["points"]] == [0.0, 2.0]
    assert points["sampling"]["window"] == {"start_s": 0.0, "end_s": 2.0}


def test_library_api_geospatial_endpoints_create_tracks_and_compute_matches(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    _write_gps_fit_stream(library_root, session_ref, times=[-100.0, 0.0, 1.0, 2.0, 100.0])
    client = TestClient(create_app(libraries_root))

    policy_response = client.get("/api/v1/geospatial-policies/default-geospatial-policy")
    assert policy_response.status_code == 200
    assert policy_response.json()["schema"] == "bodaqs.geospatial_policy"

    track_payload = {
        "track_id": "test-track",
        "display_name": "Test Track",
        "path": {
            "type": "LineString",
            "coordinates": [
                [115.86, -31.95, 200.0],
                [115.861, -31.951, 201.0],
            ],
        },
        "trackpoints": [
            {
                "trackpoint_id": "start-gate",
                "display_name": "Start gate",
                "station_m": 0.0,
                "position": {
                    "type": "Point",
                    "coordinates": [115.86, -31.95, 200.0],
                },
            }
        ],
    }
    create_response = client.post("/api/v1/tracks", json=track_payload)
    assert create_response.status_code == 200
    assert create_response.json()["track_id"] == "test-track"
    assert client.get("/api/v1/tracks").json()[0]["track_id"] == "test-track"

    gps_response = client.post(
        "/api/v1/libraries/default-library/sessions/gps-summary",
        json=session_ref,
    )
    assert gps_response.status_code == 200
    assert gps_response.json()["quality"] == "usable"

    points_response = client.post(
        "/api/v1/libraries/default-library/sessions/gps/points",
        json={**session_ref, "max_points": 2},
    )
    assert points_response.status_code == 200
    points = points_response.json()
    assert points["schema"] == "bodaqs.session_gps_points"
    assert points["sampling"]["source_points"] == 3
    assert points["sampling"]["returned_points"] == 2
    assert points["points"][0]["time_s"] == 0.0
    assert points["points"][-1]["time_s"] == 2.0

    match_response = client.post(
        "/api/v1/track-matches/compute",
        json={"track_id": "test-track", "session_ref": session_ref},
    )
    assert match_response.status_code == 200
    match = match_response.json()
    assert match["schema"] == "bodaqs.session_track_match"
    assert match["status"] == "matched"
    assert match["trackpoint_results"][0]["trackpoint_id"] == "start-gate"
    assert match["trackpoint_results"][0]["crossed"] is True


def test_library_adapter_catalog_cache_refreshes_explicitly(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    _write_catalog_fixture_session(library_root)
    adapter = LibraryAdapter(libraries_root)

    assert adapter.get_catalog("default-library")["row_count"] == 1

    _make_session(library_root, "run_2", "session_2")
    assert adapter.get_catalog("default-library")["row_count"] == 1
    assert adapter.get_catalog("default-library", refresh=True)["row_count"] == 2


def test_library_adapter_returns_timeseries_window_for_semantic_signals(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    adapter = LibraryAdapter(libraries_root)

    payload = adapter.get_timeseries_window(
        "default-library",
        {
            "session": session_ref,
            "signals": [
                {
                    "selector": {
                        "end": "front",
                        "domain": "wheel",
                        "quantity": "disp",
                        "unit": "mm",
                        "processing_role": "primary_analysis",
                    }
                },
                {
                    "selector": {
                        "end": "rear",
                        "domain": "wheel",
                        "quantity": "disp",
                        "unit": "mm",
                        "processing_role": "primary_analysis",
                    }
                },
            ],
            "window": {"start_s": 0.0, "end_s": 2.0},
            "resolution": {"target_points": 10},
            "include_events": True,
        },
    )

    assert payload["schema"] == "bodaqs.timeseries_window"
    assert payload["version"] == 1
    assert payload["session"] == session_ref
    assert payload["window"] == {
        "requested_start_s": 0.0,
        "requested_end_s": 2.0,
        "returned_start_s": 0.0,
        "returned_end_s": 2.0,
    }
    assert payload["sampling"] == {
        "mode": "raw",
        "source_points": 3,
        "returned_points": 3,
        "target_points": 10,
    }
    assert payload["time"]["column"] == "time_s"
    assert payload["time"]["values"] == [0.0, 1.0, 2.0]
    assert [signal["column"] for signal in payload["signals"]] == [
        "front_wheel_disp_dom_wheel [mm]",
        "rear_wheel_disp_dom_wheel [mm]",
    ]
    assert payload["signals"][0]["values"] == [0.0, 10.0, 20.0]
    assert payload["signals"][1]["values"] == [0.0, 12.0, 24.0]
    assert [event["event_type"] for event in payload["events"]] == [
        "bottom_out",
        "jump",
        "jump",
    ]
    assert payload["events"][0]["display_name"] == "Bottom out"
    assert payload["warnings"] == []


def test_library_adapter_timeseries_window_downsamples_concrete_columns(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    session_root = (
        library_root
        / "runs"
        / session_ref["run_id"]
        / "sessions"
        / session_ref["session_id"]
    )
    pd.DataFrame(
        {
            "time_s": [float(i) for i in range(20)],
            "front_wheel_disp_dom_wheel [mm]": [float(i) for i in range(20)],
            "rear_wheel_disp_dom_wheel [mm]": [float(20 - i) for i in range(20)],
            "active_mask_qc": [True] * 20,
        }
    ).to_parquet(session_root / "session" / "df.parquet", index=False)
    adapter = LibraryAdapter(libraries_root)

    payload = adapter.get_timeseries_window(
        "default-library",
        {
            "session": session_ref,
            "signals": [{"column": "front_wheel_disp_dom_wheel [mm]"}],
            "resolution": {"target_points": 6},
        },
    )

    assert payload["sampling"]["mode"] == "min_max_bucket"
    assert payload["sampling"]["source_points"] == 20
    assert payload["sampling"]["returned_points"] <= 8
    assert payload["time"]["values"][0] == 0.0
    assert payload["time"]["values"][-1] == 19.0
    assert payload["signals"][0]["values"][0] == 0.0
    assert payload["signals"][0]["values"][-1] == 19.0


def test_library_adapter_timeseries_window_rejects_missing_signal(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    adapter = LibraryAdapter(libraries_root)

    with pytest.raises(SignalNotFoundError):
        adapter.get_timeseries_window(
            "default-library",
            {
                "session": session_ref,
                "signals": [{"column": "not_a_real_signal"}],
            },
        )


def test_library_adapter_timeseries_window_rejects_empty_window(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    adapter = LibraryAdapter(libraries_root)

    with pytest.raises(TimeseriesUnavailableError):
        adapter.get_timeseries_window(
            "default-library",
            {
                "session": session_ref,
                "signals": [{"column": "front_wheel_disp_dom_wheel [mm]"}],
                "window": {"start_s": 99.0, "end_s": 100.0},
            },
        )


def test_export_library_fixture_writes_static_payloads(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    fixture_dir = tmp_path / "fixture"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)

    manifest = export_library_fixture(libraries_root, "default-library", fixture_dir)

    assert manifest["schema"] == "bodaqs.library_api_fixture"
    assert manifest["library_id"] == "default-library"
    assert (fixture_dir / "capabilities.json").exists()
    assert (fixture_dir / "libraries.json").exists()
    assert (fixture_dir / "libraries" / "default-library" / "library.json").exists()
    assert (fixture_dir / "libraries" / "default-library" / "catalog.json").exists()

    study_set_path = (
        fixture_dir
        / "study_sets"
        / "fixture-study-set.json"
    )
    study_set = _read_json(study_set_path)
    assert study_set["study_set_id"] == "fixture-study-set"
    assert study_set["sessions"][0]["session_key"] == session_ref["session_key"]

    study_set_index = _read_json(
        fixture_dir / "study_sets" / "index.json"
    )
    assert study_set_index[0]["path"].endswith("fixture-study-set.json")

    window_index = _read_json(
        fixture_dir / "libraries" / "default-library" / "timeseries_windows" / "index.json"
    )
    window = _read_json(fixture_dir / window_index[0]["path"])
    assert window["schema"] == "bodaqs.timeseries_window"
    assert window["session"] == session_ref
    assert [signal["column"] for signal in window["signals"]] == [
        "front_wheel_disp_dom_wheel [mm]",
        "rear_wheel_disp_dom_wheel [mm]",
    ]
    assert [event["event_type"] for event in window["events"]] == [
        "bottom_out",
        "jump",
        "jump",
    ]


def test_export_library_fixture_uses_existing_study_set(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    fixture_dir = tmp_path / "fixture"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    adapter = LibraryAdapter(libraries_root)
    adapter.create_study_set(
        "default-library",
        {
            "study_set_id": "existing-study-set",
            "display_name": "Existing Study Set",
            "sessions": [session_ref],
        },
    )

    export_library_fixture(libraries_root, "default-library", fixture_dir)

    study_set_path = (
        fixture_dir
        / "study_sets"
        / "existing-study-set.json"
    )
    assert _read_json(study_set_path)["display_name"] == "Existing Study Set"


def test_export_library_fixture_rejects_nonempty_output_dir(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    fixture_dir = tmp_path / "fixture"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    _write_catalog_fixture_session(library_root)
    _write_json(fixture_dir / "existing.json", {"already": "here"})

    with pytest.raises(InvalidRequestError):
        export_library_fixture(libraries_root, "default-library", fixture_dir)


def test_study_set_selection_snapshot_bridge_for_plain_sessions(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    adapter = LibraryAdapter(libraries_root)
    adapter.create_study_set(
        "default-library",
        {
            "study_set_id": "plain-study-set",
            "display_name": "Plain Study Set",
            "sessions": [session_ref],
        },
    )

    bridge = adapter.study_set_to_selection_snapshot(
        "default-library",
        "plain-study-set",
    )

    assert bridge["schema"] == "bodaqs.study_set_selection_snapshot"
    assert bridge["study_set_id"] == "plain-study-set"
    assert bridge["key_to_ref"] == {
        session_ref["session_key"]: (session_ref["run_id"], session_ref["session_id"])
    }
    assert isinstance(bridge["selection_snapshot"], SelectionSnapshot)
    assert isinstance(bridge["entity_snapshot"], EntitySelectionSnapshot)
    assert bridge["selection_snapshot"].session_keys() == [session_ref["session_key"]]
    assert bridge["events_index_df"].to_dict("records") == [
        {
            "session_key": session_ref["session_key"],
            "run_id": session_ref["run_id"],
            "session_id": session_ref["session_id"],
        }
    ]

    selector_handle = bridge["selector_handle"]
    assert selector_handle["store"].root == library_root
    assert selector_handle["get_key_to_ref"]() == bridge["key_to_ref"]
    assert selector_handle["get_events_index_df"]().equals(bridge["events_index_df"])
    entity_snapshot = selector_handle["get_entity_snapshot"]()
    assert entity_snapshot.expanded_session_keys == [session_ref["session_key"]]
    assert entity_snapshot.selected_entities[0].kind == "session"


def test_study_set_selection_snapshot_bridge_maps_groupings_to_entities(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    first_ref = _write_catalog_fixture_session(library_root)
    second_ref = _make_session(library_root, "run_2", "session_2")
    adapter = LibraryAdapter(libraries_root)
    adapter.create_study_set(
        "default-library",
        {
            "study_set_id": "grouped-study-set",
            "display_name": "Grouped Study Set",
            "sessions": [first_ref, second_ref],
            "groupings": [
                {
                    "grouping_id": "baseline",
                    "display_name": "Baseline",
                    "sessions": [first_ref],
                }
            ],
        },
    )

    bridge = adapter.study_set_to_selection_snapshot(
        "default-library",
        "grouped-study-set",
    )

    entity_snapshot = bridge["entity_snapshot"]
    assert [entity.kind for entity in entity_snapshot.selected_entities] == [
        "aggregation",
        "session",
    ]
    assert entity_snapshot.selected_entities[0].entity_key == (
        "study_set:grouped-study-set:grouping:baseline"
    )
    assert entity_snapshot.selected_entities[0].member_session_keys == (
        first_ref["session_key"],
    )
    assert entity_snapshot.selected_entities[1].entity_key == second_ref["session_key"]
    assert entity_snapshot.expanded_session_keys == [
        first_ref["session_key"],
        second_ref["session_key"],
    ]
    assert entity_snapshot.key_to_ref == {
        first_ref["session_key"]: (first_ref["run_id"], first_ref["session_id"]),
        second_ref["session_key"]: (second_ref["run_id"], second_ref["session_id"]),
    }

    bridge_without_groups = adapter.study_set_to_selection_snapshot(
        "default-library",
        "grouped-study-set",
        include_groupings=False,
    )
    assert [entity.kind for entity in bridge_without_groups["entity_snapshot"].selected_entities] == [
        "session",
        "session",
    ]


def test_library_api_service_exposes_core_routes(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    client = TestClient(create_app(libraries_root))

    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    capabilities = client.get("/api/v1/capabilities")
    assert capabilities.status_code == 200
    assert capabilities.json()["features"]["write_study_sets"] is True

    libraries = client.get("/api/v1/libraries")
    assert libraries.status_code == 200
    assert libraries.json()[0]["library_id"] == "default-library"

    library = client.get("/api/v1/libraries/default-library")
    assert library.status_code == 200
    assert library.json()["display_name"] == "Default Library"

    catalog = client.get("/api/v1/libraries/default-library/catalog")
    assert catalog.status_code == 200
    assert catalog.json()["rows"][0]["session_key"] == session_ref["session_key"]

    refresh = client.post("/api/v1/libraries/default-library/refresh")
    assert refresh.status_code == 200
    assert refresh.json()["refreshed"] is True

    other_libraries_root = tmp_path / "other-libraries"
    other_library_root = other_libraries_root / "field-library"
    _make_library_definition(
        other_library_root,
        library_id="field-library",
        display_name="Field Library",
    )
    other_session_ref = _write_catalog_fixture_session(other_library_root, library_id="field-library")

    switch_root = client.post(
        "/api/v1/config/libraries-root",
        json={"libraries_root": str(other_libraries_root)},
    )
    assert switch_root.status_code == 200
    assert switch_root.json()["updated"] is True
    assert switch_root.json()["library_count"] == 1
    assert switch_root.json()["libraries_root"] == str(other_libraries_root)

    switched_health = client.get("/api/v1/health")
    assert switched_health.status_code == 200
    assert switched_health.json()["libraries_root"] == str(other_libraries_root)

    switched_libraries = client.get("/api/v1/libraries")
    assert switched_libraries.status_code == 200
    assert switched_libraries.json()[0]["library_id"] == "field-library"

    switched_catalog = client.get("/api/v1/libraries/field-library/catalog")
    assert switched_catalog.status_code == 200
    assert switched_catalog.json()["rows"][0]["session_key"] == other_session_ref["session_key"]


def test_library_api_service_study_set_crud_and_revision_conflict(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    client = TestClient(create_app(libraries_root))

    create_response = client.post(
        "/api/v1/study-sets",
        json={
            "display_name": "Service Study Set",
            "sessions": [session_ref],
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["study_set_id"] == "service-study-set"
    assert created["revision"] == 1

    list_response = client.get("/api/v1/study-sets")
    assert list_response.status_code == 200
    assert list_response.json()[0]["study_set_id"] == "service-study-set"

    load_response = client.get("/api/v1/study-sets/service-study-set")
    assert load_response.status_code == 200
    assert load_response.json()["display_name"] == "Service Study Set"

    updated_payload = dict(created)
    updated_payload["display_name"] = "Service Study Set Edited"
    update_response = client.put(
        "/api/v1/study-sets/service-study-set",
        json={"expected_revision": 1, "study_set": updated_payload},
    )
    assert update_response.status_code == 200
    assert update_response.json()["revision"] == 2

    conflict_response = client.put(
        "/api/v1/study-sets/service-study-set",
        json={"expected_revision": 1, "study_set": updated_payload},
    )
    assert conflict_response.status_code == 409
    assert conflict_response.json()["error"]["code"] == "revision_conflict"

    delete_response = client.delete("/api/v1/study-sets/service-study-set")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"deleted": True, "study_set_id": "service-study-set"}


def test_library_api_service_timeseries_window_and_error_envelope(
    tmp_path: Path,
) -> None:
    libraries_root = tmp_path / "libraries"
    library_root = libraries_root / "default-library"
    _make_library_definition(
        library_root,
        library_id="default-library",
        display_name="Default Library",
    )
    session_ref = _write_catalog_fixture_session(library_root)
    client = TestClient(create_app(libraries_root))

    window_response = client.post(
        "/api/v1/libraries/default-library/timeseries/window",
        json={
            "session": session_ref,
            "signals": [{"column": "front_wheel_disp_dom_wheel [mm]"}],
            "include_events": True,
        },
    )
    assert window_response.status_code == 200
    window = window_response.json()
    assert window["schema"] == "bodaqs.timeseries_window"
    assert window["signals"][0]["values"] == [0.0, 10.0, 20.0]
    assert [event["event_type"] for event in window["events"]] == [
        "bottom_out",
        "jump",
        "jump",
    ]

    missing_response = client.get("/api/v1/libraries/missing-library")
    assert missing_response.status_code == 404
    assert missing_response.json()["error"]["code"] == "library_not_found"
