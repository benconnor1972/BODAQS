import sys
from pathlib import Path

import pandas as pd
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ANALYSIS_ROOT = _REPO_ROOT / "analysis"
if str(_ANALYSIS_ROOT) not in sys.path:
    sys.path.insert(0, str(_ANALYSIS_ROOT))

from bodaqs_analysis.artifacts import ArtifactStore, safe_artifact_folder_name
from bodaqs_analysis.widgets.event_schema_resolution import (
    EventSchemaResolutionError,
    resolve_event_schema_for_selection,
    resolve_event_schema_for_sessions,
)


def _schema_text(*, version: str, event_id: str = "test_event") -> str:
    return f"""specification: 0.1.2
version: "{version}"
events:
  - id: {event_id}
    label: Test Event {version}
"""


def _write_schema(path: Path, *, version: str, event_id: str = "test_event") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_schema_text(version=version, event_id=event_id), encoding="utf-8")


def _write_event_partition(
    store: ArtifactStore,
    *,
    run_id: str,
    session_id: str,
    schema_dir: str = "test_event",
    write_schema: bool = True,
    schema_version: str = "frozen",
) -> None:
    path = store.path_events_df(run_id, session_id, schema_dir)
    store.write_df(
        path,
        pd.DataFrame(
            [
                {
                    "session_id": session_id,
                    "event_id": "event-1",
                    "schema_id": schema_dir,
                    "trigger_time_s": 1.0,
                }
            ]
        ),
    )
    if write_schema:
        _write_schema(
            store.path_events_schema(run_id, session_id, schema_dir),
            version=schema_version,
            event_id=schema_dir,
        )


def test_resolve_event_schema_for_selection_prefers_frozen_schema(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "library")
    _write_event_partition(
        store,
        run_id="run_1",
        session_id="session_1",
        schema_version="frozen",
    )
    fallback = tmp_path / "fallback.yaml"
    _write_schema(fallback, version="fallback")

    key_to_ref = {"run_1::session_1": ("run_1", "session_1")}
    sel = {
        "store": store,
        "get_key_to_ref": lambda: dict(key_to_ref),
        "get_events_index_df": lambda: pd.DataFrame(
            [{"session_key": "run_1::session_1", "run_id": "run_1", "session_id": "session_1"}]
        ),
    }

    resolution = resolve_event_schema_for_selection(sel, fallback_schema_path=fallback)

    assert resolution.source == "frozen_artifacts"
    assert resolution.schema["version"] == "frozen"
    assert resolution.warnings == ()
    assert resolution.source_paths == (
        str(store.path_events_schema("run_1", "session_1", "test_event")),
    )


def test_resolve_event_schema_falls_back_when_no_frozen_schema(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "library")
    _write_event_partition(
        store,
        run_id="run_1",
        session_id="session_1",
        write_schema=False,
    )
    fallback = tmp_path / "fallback.yaml"
    _write_schema(fallback, version="fallback")

    resolution = resolve_event_schema_for_sessions(
        store=store,
        key_to_ref={"run_1::session_1": ("run_1", "session_1")},
        fallback_schema_path=fallback,
    )

    assert resolution.source == "fallback"
    assert resolution.schema["version"] == "fallback"
    assert resolution.source_paths == (str(fallback),)
    assert any("No frozen event schema artifacts" in warning for warning in resolution.warnings)


def test_resolve_event_schema_rejects_conflicting_frozen_schemas(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "library")
    _write_event_partition(
        store,
        run_id="run_1",
        session_id="session_1",
        schema_version="one",
    )
    _write_event_partition(
        store,
        run_id="run_2",
        session_id="session_2",
        schema_version="two",
    )

    with pytest.raises(EventSchemaResolutionError, match="multiple frozen event schema versions"):
        resolve_event_schema_for_sessions(
            store=store,
            key_to_ref={
                "run_1::session_1": ("run_1", "session_1"),
                "run_2::session_2": ("run_2", "session_2"),
            },
        )


def test_safe_artifact_folder_name_matches_schema_partition_convention() -> None:
    assert safe_artifact_folder_name("rebounds_all>25") == "rebounds_all_25"
    assert safe_artifact_folder_name(None) == "null"
