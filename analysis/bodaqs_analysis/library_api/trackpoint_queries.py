"""Root-scoped asynchronous trackpoint match query records."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .errors import InvalidRequestError, TrackpointMatchQueryNotFoundError
from .ids import derive_object_id, is_valid_object_id


TRACKPOINT_MATCH_QUERY_SCHEMA = "bodaqs.trackpoint_match_query"
TRACKPOINT_MATCH_QUERY_VERSION = 1
TRACKPOINT_MATCH_QUERY_RESULTS_SCHEMA = "bodaqs.trackpoint_match_query_results"
TRACKPOINT_MATCH_QUERY_RESULTS_VERSION = 1
TRACKPOINT_MATCH_QUERIES_DIR = Path("trackpoint_match_queries")
TRACKPOINT_MATCH_RESULTS_DIR = Path("trackpoint_match_results")

_MATCH_MODES = {"any", "all", "min_count"}
_ACTIVE_STATUSES = {"queued", "running", "completed"}


def create_trackpoint_match_query_record(
    libraries_root: str | Path,
    request: Mapping[str, Any],
    *,
    track: Mapping[str, Any],
    policy: Mapping[str, Any],
    candidate_session_refs: list[Mapping[str, Any]],
    candidate_gps_sources: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create or resume a persisted broad trackpoint match query."""

    normalized = _normalized_request(
        request,
        track=track,
        policy=policy,
        candidate_session_refs=candidate_session_refs,
        candidate_gps_sources=candidate_gps_sources or [],
    )
    query_id = normalized["query_id"]
    path = _trackpoint_match_query_path(libraries_root, query_id)
    if path.exists():
        existing = load_trackpoint_match_query(libraries_root, query_id)
        if existing.get("status") in _ACTIVE_STATUSES:
            return existing

    now = _utcnow_iso()
    query = {
        "schema": TRACKPOINT_MATCH_QUERY_SCHEMA,
        "version": TRACKPOINT_MATCH_QUERY_VERSION,
        "query_id": query_id,
        "status": "queued",
        "scope": normalized["scope"],
        "track_ref": normalized["track_ref"],
        "policy_ref": normalized["policy_ref"],
        "trackpoint_ids": normalized["trackpoint_ids"],
        "match_mode": normalized["match_mode"],
        "min_count": normalized["min_count"],
        "tolerance_m": normalized["tolerance_m"],
        "persist": normalized["persist"],
        "gps_source_selector": normalized["gps_source_selector"],
        "candidate_session_count": len(candidate_session_refs),
        "candidate_gps_sources": [dict(ref) for ref in candidate_gps_sources or []],
        "processed_session_count": 0,
        "matched_session_count": 0,
        "failed_session_count": 0,
        "cache": {
            "reused_match_count": 0,
            "stale_match_count": 0,
            "missing_match_count": len(candidate_session_refs),
        },
        "candidate_sessions": [dict(ref) for ref in candidate_session_refs],
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
        "cancelled_at": None,
        "error": None,
    }
    _write_json(path, query)
    _write_results(libraries_root, query_id, [])
    return query


def load_trackpoint_match_query(libraries_root: str | Path, query_id: str) -> dict[str, Any]:
    path = _trackpoint_match_query_path(libraries_root, query_id)
    if not path.exists():
        raise TrackpointMatchQueryNotFoundError(
            "Trackpoint match query was not found.",
            details={"query_id": str(query_id)},
        )
    return _read_json_object(path)


def update_trackpoint_match_query(
    libraries_root: str | Path,
    query_id: str,
    updates: Mapping[str, Any],
) -> dict[str, Any]:
    query = load_trackpoint_match_query(libraries_root, query_id)
    query.update(dict(updates))
    query["updated_at"] = _utcnow_iso()
    _write_json(_trackpoint_match_query_path(libraries_root, query_id), query)
    return query


def cancel_trackpoint_match_query(libraries_root: str | Path, query_id: str) -> dict[str, Any]:
    now = _utcnow_iso()
    return update_trackpoint_match_query(
        libraries_root,
        query_id,
        {
            "status": "cancelled",
            "cancelled_at": now,
            "completed_at": None,
        },
    )


def fail_trackpoint_match_query(libraries_root: str | Path, query_id: str, message: str) -> dict[str, Any]:
    return update_trackpoint_match_query(
        libraries_root,
        query_id,
        {
            "status": "failed",
            "error": str(message),
            "completed_at": _utcnow_iso(),
        },
    )


def complete_trackpoint_match_query(
    libraries_root: str | Path,
    query_id: str,
    *,
    processed_count: int,
    matched_count: int,
    failed_count: int,
) -> dict[str, Any]:
    return update_trackpoint_match_query(
        libraries_root,
        query_id,
        {
            "status": "completed",
            "processed_session_count": int(processed_count),
            "matched_session_count": int(matched_count),
            "failed_session_count": int(failed_count),
            "completed_at": _utcnow_iso(),
        },
    )


def write_trackpoint_match_query_results(
    libraries_root: str | Path,
    query_id: str,
    results: list[Mapping[str, Any]],
) -> None:
    load_trackpoint_match_query(libraries_root, query_id)
    _write_results(libraries_root, query_id, results)


def load_trackpoint_match_query_results(
    libraries_root: str | Path,
    query_id: str,
    *,
    cursor: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    load_trackpoint_match_query(libraries_root, query_id)
    path = _trackpoint_match_results_path(libraries_root, query_id)
    rows: list[dict[str, Any]] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                if isinstance(value, Mapping):
                    rows.append(dict(value))

    start = 0
    if cursor:
        try:
            start = max(0, int(cursor))
        except ValueError as exc:
            raise InvalidRequestError("Trackpoint match query cursor must be an integer offset.") from exc
    safe_limit = max(1, min(500, int(limit or 100)))
    page = rows[start : start + safe_limit]
    next_offset = start + len(page)
    next_cursor = str(next_offset) if next_offset < len(rows) else None
    return {
        "schema": TRACKPOINT_MATCH_QUERY_RESULTS_SCHEMA,
        "version": TRACKPOINT_MATCH_QUERY_RESULTS_VERSION,
        "query_id": str(query_id),
        "result_count": len(rows),
        "returned_count": len(page),
        "next_cursor": next_cursor,
        "results": page,
    }


def _normalized_request(
    request: Mapping[str, Any],
    *,
    track: Mapping[str, Any],
    policy: Mapping[str, Any],
    candidate_session_refs: list[Mapping[str, Any]],
    candidate_gps_sources: list[Mapping[str, Any]],
) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise InvalidRequestError("Trackpoint match query request must be a JSON object.")

    track_id = _required_text(track.get("track_id"), field_name="track_id")
    track_revision = int(track.get("revision") or 0)
    policy_id = _required_text(policy.get("policy_id"), field_name="policy_id")
    trackpoint_ids = _trackpoint_ids(request, track)
    match_mode = _optional_text(request.get("match_mode")) or "all"
    if match_mode not in _MATCH_MODES:
        raise InvalidRequestError("Trackpoint match query match_mode is not supported.", details={"match_mode": match_mode})
    min_count = _min_count(request, match_mode, len(trackpoint_ids))
    tolerance_m = _number(request.get("tolerance_m"), fallback=5.0)
    if tolerance_m < 0:
        raise InvalidRequestError("Trackpoint match query tolerance_m must be non-negative.")
    persist = bool(request.get("persist", True))
    scope = dict(request.get("scope")) if isinstance(request.get("scope"), Mapping) else {}

    query_id = _optional_text(request.get("query_id")) or derive_object_id(
        " ".join(
            [
                track_id,
                str(track_revision),
                policy_id,
                *trackpoint_ids,
                match_mode,
                str(min_count),
                f"{tolerance_m:g}",
                _scope_identity(scope, candidate_session_refs),
                _gps_sources_identity(candidate_gps_sources),
            ]
        ),
        fallback="trackpoint-query",
    )
    if not is_valid_object_id(query_id):
        raise InvalidRequestError("Trackpoint match query id is not filename-safe.", details={"query_id": query_id})

    return {
        "query_id": query_id,
        "scope": scope,
        "track_ref": {
            "track_id": track_id,
            "revision": track_revision,
        },
        "policy_ref": {
            "policy_id": policy_id,
            "version": policy.get("version"),
        },
        "trackpoint_ids": trackpoint_ids,
        "match_mode": match_mode,
        "min_count": min_count,
        "tolerance_m": tolerance_m,
        "persist": persist,
        "gps_source_selector": _gps_source_selector(request, policy),
    }


def _trackpoint_ids(request: Mapping[str, Any], track: Mapping[str, Any]) -> list[str]:
    raw = request.get("trackpoint_ids")
    if raw is None and request.get("trackpoint_id") is not None:
        raw = [request.get("trackpoint_id")]
    if not isinstance(raw, list):
        raise InvalidRequestError("Trackpoint match query must include trackpoint_ids.")
    ids = [str(item).strip() for item in raw if str(item).strip()]
    if not ids:
        raise InvalidRequestError("Trackpoint match query must include at least one trackpoint id.")
    available = {
        str(trackpoint.get("trackpoint_id") or "")
        for trackpoint in track.get("trackpoints") or []
        if isinstance(trackpoint, Mapping)
    }
    missing = [trackpoint_id for trackpoint_id in ids if trackpoint_id not in available]
    if missing:
        raise InvalidRequestError(
            "Trackpoint match query references unknown trackpoints.",
            details={"trackpoint_ids": missing},
        )
    return ids


def _min_count(request: Mapping[str, Any], match_mode: str, trackpoint_count: int) -> int | None:
    if match_mode != "min_count":
        return None
    raw = request.get("min_count")
    if isinstance(raw, bool):
        raise InvalidRequestError("Trackpoint match query min_count must be an integer.")
    try:
        value = int(raw)
    except Exception as exc:
        raise InvalidRequestError("Trackpoint match query min_count must be an integer.") from exc
    if value < 1 or value > trackpoint_count:
        raise InvalidRequestError(
            "Trackpoint match query min_count must be between 1 and the number of trackpoints.",
            details={"min_count": value, "trackpoint_count": trackpoint_count},
        )
    return value


def _scope_identity(scope: Mapping[str, Any], candidate_session_refs: list[Mapping[str, Any]]) -> str:
    library_ids = scope.get("library_ids")
    if isinstance(library_ids, list) and library_ids:
        return "libraries:" + ",".join(str(item) for item in library_ids)
    return "sessions:" + ",".join(str(ref.get("session_ref_id") or ref.get("session_key")) for ref in candidate_session_refs)


def _gps_source_selector(request: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    raw = request.get("gps_source_selector") if isinstance(request.get("gps_source_selector"), Mapping) else {}
    matching_policy = policy.get("matching_policy") if isinstance(policy.get("matching_policy"), Mapping) else {}
    selector = dict(raw)
    selector.setdefault("mode", "preferred")
    source_preference = matching_policy.get("position_source_preference")
    if isinstance(source_preference, list):
        selector.setdefault("position_source_preference", [str(item) for item in source_preference])
    return selector


def _gps_sources_identity(candidate_gps_sources: list[Mapping[str, Any]]) -> str:
    identity = [
        {
            "session_ref_id": str(item.get("session_ref_id") or ""),
            "source_id": item.get("source_id"),
            "kind": item.get("kind"),
            "selection_method": item.get("selection_method"),
            "policy": item.get("policy"),
        }
        for item in candidate_gps_sources
    ]
    return json.dumps(identity, sort_keys=True, separators=(",", ":"))


def _write_results(libraries_root: str | Path, query_id: str, results: list[Mapping[str, Any]]) -> None:
    path = _trackpoint_match_results_path(libraries_root, query_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = "".join(json.dumps(dict(result), sort_keys=True) + "\n" for result in results)
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _trackpoint_match_query_path(libraries_root: str | Path, query_id: str) -> Path:
    return _object_path(
        Path(libraries_root).expanduser() / TRACKPOINT_MATCH_QUERIES_DIR,
        query_id,
        field_name="query_id",
    )


def _trackpoint_match_results_path(libraries_root: str | Path, query_id: str) -> Path:
    return _object_path(
        Path(libraries_root).expanduser() / TRACKPOINT_MATCH_RESULTS_DIR,
        query_id,
        field_name="query_id",
        suffix=".jsonl",
    )


def _object_path(directory: Path, object_id: str, *, field_name: str, suffix: str = ".json") -> Path:
    object_id = _required_text(object_id, field_name=field_name)
    if not is_valid_object_id(object_id):
        raise InvalidRequestError(f"{field_name} is not filename-safe.", details={field_name: object_id})
    return directory / f"{object_id}{suffix}"


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise TrackpointMatchQueryNotFoundError(
            "Trackpoint match query could not be read.",
            details={"path": str(path), "error": f"{type(exc).__name__}: {exc}"},
        ) from exc
    if not isinstance(value, Mapping):
        raise InvalidRequestError("Trackpoint match query JSON must be an object.", details={"path": str(path)})
    return dict(value)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.02 * (attempt + 1))


def _required_text(value: Any, *, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise InvalidRequestError(f"Trackpoint match query missing non-empty {field_name!r}.")
    return text


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _number(value: Any, *, fallback: float) -> float:
    if value is None:
        return fallback
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidRequestError("Trackpoint match query numeric field must be a finite number.")
    number = float(value)
    if not number == number or number in {float("inf"), float("-inf")}:
        raise InvalidRequestError("Trackpoint match query numeric field must be a finite number.")
    return number


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
