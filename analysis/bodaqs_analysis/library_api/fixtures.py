"""Static fixture export for BODAQS Library API frontend development."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .adapter import LibraryAdapter
from .errors import InvalidRequestError
from .ids import derive_object_id


FIXTURE_SCHEMA = "bodaqs.library_api_fixture"
FIXTURE_VERSION = 1


def export_library_fixture(
    libraries_root: str | Path,
    library_id: str,
    fixture_dir: str | Path,
    *,
    study_set_id: str | None = None,
    timeseries_request: Mapping[str, Any] | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Export a small static Library API fixture for frontend development."""

    out_root = Path(fixture_dir).expanduser()
    _prepare_output_dir(out_root, overwrite=overwrite)

    adapter = LibraryAdapter(libraries_root)
    library = adapter.get_library(library_id)
    catalog = adapter.get_catalog(library_id, refresh=True)
    study_set = _select_or_synthesize_study_set(
        adapter,
        library_id,
        catalog,
        study_set_id=study_set_id,
    )
    request = dict(timeseries_request) if timeseries_request is not None else _default_timeseries_request(
        catalog,
        study_set,
    )
    window = adapter.get_timeseries_window(library_id, request)

    library_dir = out_root / "libraries" / str(library_id)
    study_set_rel = Path("study_sets") / f"{study_set['study_set_id']}.json"
    window_id = _timeseries_window_id(window)
    window_rel = Path("libraries") / str(library_id) / "timeseries_windows" / f"{window_id}.json"

    _write_json(out_root / "capabilities.json", adapter.capabilities())
    _write_json(out_root / "libraries.json", adapter.list_libraries(refresh=True))
    _write_json(library_dir / "library.json", library)
    _write_json(library_dir / "catalog.json", catalog)
    _write_json(out_root / study_set_rel, study_set)
    _write_json(
        out_root / "study_sets" / "index.json",
        [
            {
                "study_set_id": study_set["study_set_id"],
                "display_name": study_set.get("display_name"),
                "path": str(study_set_rel).replace("\\", "/"),
            }
        ],
    )
    _write_json(out_root / window_rel, window)
    _write_json(
        library_dir / "timeseries_windows" / "index.json",
        [
            {
                "window_id": window_id,
                "session_key": window["session"]["session_key"],
                "path": str(window_rel).replace("\\", "/"),
            }
        ],
    )

    manifest = {
        "schema": FIXTURE_SCHEMA,
        "version": FIXTURE_VERSION,
        "generated_at": _utcnow_iso(),
        "library_id": str(library_id),
        "files": {
            "capabilities": "capabilities.json",
            "libraries": "libraries.json",
            "library": f"libraries/{library_id}/library.json",
            "catalog": f"libraries/{library_id}/catalog.json",
            "study_sets": [str(study_set_rel).replace("\\", "/")],
            "timeseries_windows": [str(window_rel).replace("\\", "/")],
        },
    }
    _write_json(out_root / "manifest.json", manifest)
    return manifest


def _select_or_synthesize_study_set(
    adapter: LibraryAdapter,
    library_id: str,
    catalog: Mapping[str, Any],
    *,
    study_set_id: str | None,
) -> dict[str, Any]:
    if study_set_id is not None:
        return adapter.load_study_set(study_set_id)

    summaries = adapter.list_study_sets()
    if summaries:
        return adapter.load_study_set(str(summaries[0]["study_set_id"]))

    rows = catalog.get("rows")
    if not isinstance(rows, list) or not rows:
        raise InvalidRequestError("Cannot synthesize fixture Study Set without catalog rows.")
    row = rows[0]
    if not isinstance(row, Mapping):
        raise InvalidRequestError("Cannot synthesize fixture Study Set from invalid catalog row.")

    now = _utcnow_iso()
    return {
        "schema": "bodaqs.study_set",
        "version": 1,
        "study_set_id": "fixture-study-set",
        "display_name": "Fixture Study Set",
        "revision": 1,
        "sessions": [
            {
                "session_key": row["session_key"],
                "session_ref_id": row["session_ref_id"],
                "library_id": row["library_id"],
                "run_id": row["run_id"],
                "session_id": row["session_id"],
                "label": (row.get("display") or {}).get("label") if isinstance(row.get("display"), Mapping) else None,
            }
        ],
        "groupings": [],
        "tracks": [],
        "bookmarks": [],
        "provenance": {
            "created_at": now,
            "created_by": "fixture_export",
            "created_from": {"kind": "catalog_first_session", "details": {}},
            "updated_at": now,
        },
        "display_state": {"bodaqs_web_v1": {}},
    }


def _default_timeseries_request(
    catalog: Mapping[str, Any],
    study_set: Mapping[str, Any],
) -> dict[str, Any]:
    session_ref = _first_study_set_session(study_set)
    row = _catalog_row_for_session(catalog, session_ref["session_key"])
    signals = _default_signal_requests(row)
    if not signals:
        raise InvalidRequestError(
            "Cannot synthesize fixture time-series request without available signals.",
            details={"session_key": session_ref["session_key"]},
        )
    return {
        "session": {
            "session_key": session_ref["session_key"],
            "session_ref_id": session_ref["session_ref_id"],
            "library_id": session_ref["library_id"],
            "run_id": session_ref["run_id"],
            "session_id": session_ref["session_id"],
        },
        "signals": signals,
        "resolution": {"target_points": 2000},
        "include_events": True,
    }


def _first_study_set_session(study_set: Mapping[str, Any]) -> dict[str, str]:
    sessions = study_set.get("sessions")
    if not isinstance(sessions, list) or not sessions or not isinstance(sessions[0], Mapping):
        raise InvalidRequestError("Fixture Study Set must contain at least one session.")
    session = sessions[0]
    return {
        "session_key": _required_text(session.get("session_key"), field_name="session.session_key"),
        "session_ref_id": _required_text(session.get("session_ref_id"), field_name="session.session_ref_id"),
        "library_id": _required_text(session.get("library_id"), field_name="session.library_id"),
        "run_id": _required_text(session.get("run_id"), field_name="session.run_id"),
        "session_id": _required_text(session.get("session_id"), field_name="session.session_id"),
    }


def _catalog_row_for_session(catalog: Mapping[str, Any], session_key: str) -> Mapping[str, Any]:
    rows = catalog.get("rows")
    if not isinstance(rows, list):
        raise InvalidRequestError("Catalog rows are unavailable.")
    for row in rows:
        if isinstance(row, Mapping) and row.get("session_key") == session_key:
            return row
    raise InvalidRequestError(
        "Study Set session is not present in catalog.",
        details={"session_key": session_key},
    )


def _default_signal_requests(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    available = row.get("available_signals")
    if not isinstance(available, list):
        return []

    out: list[dict[str, Any]] = []
    for end in ("front", "rear"):
        match = _find_signal(
            available,
            end=end,
            domain="wheel",
            quantity="disp",
            unit="mm",
            processing_role="primary_analysis",
        )
        if match is not None:
            out.append({"selector": _selector_from_signal(match)})

    if out:
        return out

    for signal in available:
        if not isinstance(signal, Mapping):
            continue
        if str(signal.get("quantity") or "").strip().lower() == "time":
            continue
        column = signal.get("column")
        if isinstance(column, str) and column.strip():
            out.append({"column": column.strip()})
        if len(out) >= 2:
            break
    return out


def _find_signal(
    available: list[Any],
    *,
    end: str,
    domain: str,
    quantity: str,
    unit: str,
    processing_role: str,
) -> Mapping[str, Any] | None:
    for signal in available:
        if not isinstance(signal, Mapping):
            continue
        if (
            _norm(signal.get("end")) == end
            and _norm(signal.get("domain")) == domain
            and _norm(signal.get("quantity")) == quantity
            and _norm(signal.get("unit")) == unit
            and _norm(signal.get("processing_role")) == processing_role
        ):
            return signal
    return None


def _selector_from_signal(signal: Mapping[str, Any]) -> dict[str, Any]:
    selector: dict[str, Any] = {}
    for key in ("end", "domain", "quantity", "unit", "processing_role"):
        value = signal.get(key)
        if value is not None:
            selector[key] = value
    return selector


def _timeseries_window_id(window: Mapping[str, Any]) -> str:
    session = window.get("session")
    session_key = session.get("session_key") if isinstance(session, Mapping) else None
    signals = window.get("signals")
    signal_ids: list[str] = []
    if isinstance(signals, list):
        for signal in signals[:3]:
            if isinstance(signal, Mapping) and isinstance(signal.get("signal_id"), str):
                signal_ids.append(signal["signal_id"])
    label = " ".join([str(session_key or "session"), *signal_ids])
    return derive_object_id(label, fallback="timeseries-window")


def _prepare_output_dir(path: Path, *, overwrite: bool) -> None:
    if path.exists() and any(path.iterdir()) and not overwrite:
        raise InvalidRequestError(
            "Fixture directory already exists and is not empty.",
            details={"fixture_dir": str(path)},
        )
    path.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _required_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"Missing non-empty {field_name}.")
    return value.strip()


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
