import json
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bodaqs_analysis.artifacts import ArtifactStore
from bodaqs_analysis.library_api import InvalidRequestError, LibraryAdapter, RevisionConflictError, SessionNotFoundError
from bodaqs_analysis.library_api.session_annotations import load_session_user_annotations, save_session_user_annotations
from bodaqs_analysis.library_api_service import create_app
from bodaqs_analysis.library_api.errors import InvalidSessionFilterError
from bodaqs_analysis.library_api.session_filters import create_session_filter


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "libraries"
    store = ArtifactStore(root / "test")
    store.write_json(store.root / "library_definition.json", {
        "schema": "bodaqs.import_agent_library", "version": 1,
        "library_id": "test", "display_name": "Test", "artifacts_dir": str(store.root),
    })
    store.write_json(store.path_run_manifest("run"), {"run_id": "run"})
    store.write_json(store.path_session_manifest("run", "session"), {"session_id": "session"})
    ref = {"library_id": "test", "run_id": "run", "session_id": "session"}
    return root, store, ref


def payload(revision=0, **changes):
    return {"expected_revision": revision, "annotations": {
        "tags": [" Wet ", "WET", "Test Run"],
        "gps_issue": {"flagged": True, "explanation": "Wrong location"},
        "qa_issue": {"flagged": False}, **changes,
    }}


def test_default_does_not_create_files(library):
    _, store, ref = library
    result = load_session_user_annotations(store.root, ref)
    assert not result["present"]
    assert result["annotations"]["revision"] == 0
    assert result["annotations"]["tags"] == []
    assert result["annotations"]["gps_issue"] == {"flagged": False, "explanation": ""}
    assert not store.path_session_user_annotations("run", "session").exists()


def test_round_trip_clear_and_revision(library):
    _, store, ref = library
    first = save_session_user_annotations(store.root, ref, payload())
    assert first["annotations"]["tags"] == ["test run", "wet"]
    assert load_session_user_annotations(store.root, ref) == first
    with pytest.raises(RevisionConflictError):
        save_session_user_annotations(store.root, ref, payload())
    second = save_session_user_annotations(store.root, ref, payload(1, tags=[], gps_issue={"flagged": False}))
    assert second["annotations"]["revision"] == 2
    assert second["annotations"]["created_at_utc"] == first["annotations"]["created_at_utc"]
    assert second["annotations"]["gps_issue"] == {"flagged": False, "explanation": ""}
    assert not list(store.path_session_annotations_dir("run", "session").glob("*.tmp"))


@pytest.mark.parametrize("changes", [
    {"tags": "wet"}, {"tags": [1]}, {"tags": [""]}, {"tags": ["x" * 81]},
    {"tags": ["x"] * 101}, {"tags": ["a\nb"]},
    {"gps_issue": {"flagged": "false"}}, {"qa_issue": {"explanation": "oops"}},
    {"gps_issue": {"flagged": True, "explanation": 5}},
    {"gps_issue": {"flagged": True, "explanation": "x" * 4001}},
    {"gps_issue": {"flagged": True, "other": True}}, {"other": True},
])
def test_invalid_content_is_not_written(library, changes):
    _, store, ref = library
    with pytest.raises(InvalidRequestError):
        save_session_user_annotations(store.root, ref, payload(**changes))
    assert not store.path_session_user_annotations("run", "session").exists()


@pytest.mark.parametrize("revision", [None, True, "0", -1, 0.0])
def test_expected_revision_is_strict(library, revision):
    _, store, ref = library
    with pytest.raises(InvalidRequestError):
        save_session_user_annotations(store.root, ref, payload(revision))


def test_missing_session_and_unsafe_reference(library):
    _, store, ref = library
    with pytest.raises(SessionNotFoundError):
        load_session_user_annotations(store.root, {**ref, "session_id": "missing"})
    with pytest.raises(InvalidRequestError):
        load_session_user_annotations(store.root, {**ref, "run_id": "../outside"})
    with pytest.raises(InvalidRequestError):
        load_session_user_annotations(store.root, {**ref, "session_key": "wrong"})


def test_simultaneous_writers_cannot_both_save_same_revision(library):
    _, store, ref = library
    def save():
        try:
            save_session_user_annotations(store.root, ref, payload())
            return "saved"
        except RevisionConflictError:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(lambda _: save(), range(2))) == ["conflict", "saved"]


@pytest.mark.parametrize("operation", ["read", "write"])
def test_location_resolution_waits_for_atomic_replacement(library, monkeypatch, operation):
    import bodaqs_analysis.library_api.session_annotations as annotations
    _, store, ref = library
    replacing = Event()
    release = Event()
    started = Event()
    original_replace = annotations.os.replace
    original_location = annotations._location

    def replace(source, destination):
        replacing.set()
        assert release.wait(5)
        try:
            return original_replace(source, destination)
        finally:
            replacing.clear()

    def location(*args):
        if replacing.is_set():
            raise InvalidRequestError("Simulated Windows path resolution during replacement")
        return original_location(*args)

    monkeypatch.setattr(annotations.os, "replace", replace)
    monkeypatch.setattr(annotations, "_location", location)

    def concurrent_request():
        started.set()
        if operation == "read":
            return load_session_user_annotations(store.root, ref)
        with pytest.raises(RevisionConflictError):
            save_session_user_annotations(store.root, ref, payload())

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(save_session_user_annotations, store.root, ref, payload())
        assert replacing.wait(5)
        second = executor.submit(concurrent_request)
        try:
            assert started.wait(5)
            with pytest.raises(TimeoutError):
                second.result(timeout=0.1)
        finally:
            release.set()
        assert first.result()["annotations"]["revision"] == 1
        result = second.result()
        if operation == "read":
            assert result["annotations"]["revision"] == 1


def test_catalog_refresh_and_other_documents_unchanged(library):
    root, store, ref = library
    store.write_json(store.path_session_notes("run", "session"), {"note": "Keep"})
    store.write_json(store.path_session_meta("run", "session"), {"qc": {"warnings": ["existing"]}})
    paths = [store.path_session_notes("run", "session"), store.path_session_meta("run", "session")]
    original = [p.read_bytes() for p in paths]
    adapter = LibraryAdapter(root)
    before = adapter.get_catalog("test")["rows"][0]
    assert not before["user_annotations"]["present"]
    adapter.save_session_user_annotations("test", {**ref, **payload()})
    after = adapter.get_catalog("test")["rows"][0]
    assert after["user_annotations"]["gps_issue"]["flagged"]
    assert after["user_annotations"]["tags"] == ["test run", "wet"]
    assert after["gps_summary"] == before["gps_summary"]
    assert after["qc_summary"] == before["qc_summary"]
    assert original == [p.read_bytes() for p in paths]
    assert LibraryAdapter(root).get_catalog("test")["rows"][0]["user_annotations"] == after["user_annotations"]


@pytest.mark.parametrize("broken", ["{", json.dumps({"schema": "unknown", "version": 2})])
def test_corrupt_file_is_reported_and_not_overwritten(library, broken):
    root, store, ref = library
    path = store.path_session_user_annotations("run", "session")
    path.parent.mkdir(parents=True)
    path.write_text(broken, encoding="utf-8")
    summary = LibraryAdapter(root).get_catalog("test")["rows"][0]["user_annotations"]
    assert summary["warnings"] == ["user_annotations_invalid"]
    assert summary["gps_issue"] is None
    with pytest.raises(InvalidRequestError):
        save_session_user_annotations(store.root, ref, payload())
    assert path.read_text(encoding="utf-8") == broken


def test_http_round_trip_conflict_and_read_only(library):
    root, _, _ = library
    url = "/api/v1/libraries/test/runs/run/sessions/session/user-annotations"
    client = TestClient(create_app(root))
    assert client.get(url).json()["annotations"]["revision"] == 0
    assert client.put(url, json=payload()).status_code == 200
    assert client.put(url, json=payload()).status_code == 409
    assert client.put(url, json=payload("1")).status_code == 400
    assert client.get(url.replace("session/user", "missing/user")).status_code == 404
    readonly = TestClient(create_app(root, read_only=True))
    assert readonly.get(url).json()["annotations"]["revision"] == 1
    assert readonly.put(url, json=payload(1)).status_code == 403
    capabilities = readonly.get("/api/v1/capabilities").json()["features"]
    assert capabilities["read_session_user_annotations"]
    assert not capabilities["write_session_user_annotations"]


def test_persisted_annotation_filter_validation(library):
    root, _, _ = library
    saved = create_session_filter(root, {"display_name": "Tagged GPS problems", "predicate": {
        "op": "and", "children": [
            {"field": "tags", "op": "all", "value": [" WET ", "wet", "Test, one"]},
            {"field": "user.gps_issue", "op": "eq", "value": "true"},
        ],
    }})
    assert saved["predicate"]["children"] == [
        {"field": "tags", "op": "all", "value": ["test, one", "wet"]},
        {"field": "user.gps_issue", "op": "eq", "value": True},
    ]


@pytest.mark.parametrize("predicate", [
    {"field": "rider", "op": "all", "value": ["a"]},
    {"field": "tags", "op": "all", "value": []},
    {"field": "tags", "op": "in", "value": [1]},
    {"field": "tags", "op": "contains", "value": "we"},
    {"field": "user.qa_issue", "op": "eq", "value": "unknown"},
])
def test_rejects_invalid_annotation_filters(library, predicate):
    root, _, _ = library
    with pytest.raises(InvalidSessionFilterError):
        create_session_filter(root, {"display_name": "Bad", "predicate": predicate})
