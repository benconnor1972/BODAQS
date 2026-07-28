"""Root-scoped geospatial objects for the BODAQS Library API."""

from __future__ import annotations

import copy
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .errors import (
    GeospatialPolicyNotFoundError,
    InvalidGeospatialPolicyError,
    InvalidTrackError,
    RevisionConflictError,
    TrackMatchNotFoundError,
    TrackNotFoundError,
)
from .ids import derive_object_id, is_valid_object_id, make_unique_object_id


TRACK_SCHEMA = "bodaqs.track"
TRACK_VERSION = 1
GEOSPATIAL_POLICY_SCHEMA = "bodaqs.geospatial_policy"
GEOSPATIAL_POLICY_VERSION = 1
SESSION_TRACK_MATCH_SCHEMA = "bodaqs.session_track_match"
SESSION_TRACK_MATCH_VERSION = 1

TRACKS_DIR = Path("tracks")
GEOSPATIAL_POLICIES_DIR = Path("geospatial_policies")
TRACK_MATCHES_DIR = Path("track_matches")
DEFAULT_GEOSPATIAL_POLICY_ID = "default-geospatial-policy"
_EARTH_RADIUS_M = 6_371_000.0


def list_tracks(libraries_root: str | Path) -> list[dict[str, Any]]:
    """Return all root-scoped Track objects."""

    out: list[dict[str, Any]] = []
    for path in sorted(_tracks_dir(libraries_root).glob("*.json"), key=lambda p: p.name.lower()):
        doc = _read_json_object(path, InvalidTrackError)
        out.append(_normalized_track_payload(doc, track_id=str(doc.get("track_id") or path.stem), revision=None))
    return out


def load_track(libraries_root: str | Path, track_id: str) -> dict[str, Any]:
    """Load one root-scoped Track object."""

    path = _track_path(libraries_root, track_id)
    if not path.exists():
        raise TrackNotFoundError("Track was not found.", details={"track_id": str(track_id)})
    doc = _read_json_object(path, InvalidTrackError)
    return _normalized_track_payload(doc, track_id=str(track_id), revision=None)


def create_track(libraries_root: str | Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Create a root-scoped Track object."""

    if not isinstance(payload, Mapping):
        raise InvalidTrackError("Track payload must be a JSON object.")
    existing_ids = [track["track_id"] for track in list_tracks(libraries_root)]
    display_name = _required_text(payload.get("display_name"), field_name="display_name", error_cls=InvalidTrackError)
    requested_id = _optional_text(payload.get("track_id"))
    track_id = requested_id or make_unique_object_id(display_name, existing_ids, fallback="track")
    if track_id in set(existing_ids):
        raise InvalidTrackError("Track id already exists.", details={"track_id": track_id})
    if not is_valid_object_id(track_id):
        raise InvalidTrackError("Track id is not filename-safe.", details={"track_id": track_id})

    now = _utcnow_iso()
    doc = _normalized_track_payload(payload, track_id=track_id, revision=1, now=now, previous=None)
    _write_json(_track_path(libraries_root, track_id), doc)
    return doc


def update_track(
    libraries_root: str | Path,
    track_id: str,
    *,
    payload: Mapping[str, Any],
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Update a root-scoped Track object."""

    if not isinstance(payload, Mapping):
        raise InvalidTrackError("Track payload must be a JSON object.")
    current = load_track(libraries_root, track_id)
    current_revision = int(current.get("revision") or 0)
    if expected_revision is not None and int(expected_revision) != current_revision:
        raise RevisionConflictError(
            "Track was modified after it was loaded.",
            details={
                "track_id": str(track_id),
                "expected_revision": int(expected_revision),
                "current_revision": current_revision,
            },
        )
    now = _utcnow_iso()
    doc = _normalized_track_payload(
        payload,
        track_id=str(track_id),
        revision=current_revision + 1,
        now=now,
        previous=current,
    )
    _write_json(_track_path(libraries_root, track_id), doc)
    return doc


def delete_track(libraries_root: str | Path, track_id: str) -> dict[str, Any]:
    """Delete one root-scoped Track object."""

    path = _track_path(libraries_root, track_id)
    if not path.exists():
        raise TrackNotFoundError("Track was not found.", details={"track_id": str(track_id)})
    path.unlink()
    return {"deleted": True, "track_id": str(track_id)}


def list_geospatial_policies(libraries_root: str | Path) -> list[dict[str, Any]]:
    """Return root-scoped geospatial policies plus the package default."""

    out: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for path in sorted(_geospatial_policies_dir(libraries_root).glob("*.json"), key=lambda p: p.name.lower()):
        doc = _read_json_object(path, InvalidGeospatialPolicyError)
        policy_id = str(doc.get("policy_id") or path.stem)
        out.append(_normalized_policy_payload(doc, policy_id=policy_id))
        seen_ids.add(policy_id)
    if DEFAULT_GEOSPATIAL_POLICY_ID not in seen_ids:
        out.insert(0, _default_geospatial_policy())
    return out


def load_geospatial_policy(libraries_root: str | Path, policy_id: str) -> dict[str, Any]:
    """Load one geospatial policy, falling back to the package default."""

    path = _geospatial_policy_path(libraries_root, policy_id)
    if path.exists():
        doc = _read_json_object(path, InvalidGeospatialPolicyError)
        return _normalized_policy_payload(doc, policy_id=str(policy_id))
    if str(policy_id) == DEFAULT_GEOSPATIAL_POLICY_ID:
        return _default_geospatial_policy()
    raise GeospatialPolicyNotFoundError(
        "Geospatial policy was not found.",
        details={"policy_id": str(policy_id)},
    )


def create_geospatial_policy(libraries_root: str | Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Create a root-scoped geospatial policy."""

    if not isinstance(payload, Mapping):
        raise InvalidGeospatialPolicyError("Geospatial policy payload must be a JSON object.")
    existing_ids = [policy["policy_id"] for policy in list_geospatial_policies(libraries_root)]
    display_name = _required_text(
        payload.get("display_name"),
        field_name="display_name",
        error_cls=InvalidGeospatialPolicyError,
    )
    requested_id = _optional_text(payload.get("policy_id"))
    policy_id = requested_id or make_unique_object_id(display_name, existing_ids, fallback="geospatial-policy")
    if policy_id in set(existing_ids):
        raise InvalidGeospatialPolicyError(
            "Geospatial policy id already exists.",
            details={"policy_id": policy_id},
        )
    if not is_valid_object_id(policy_id):
        raise InvalidGeospatialPolicyError(
            "Geospatial policy id is not filename-safe.",
            details={"policy_id": policy_id},
        )

    doc = _normalized_policy_payload(payload, policy_id=policy_id)
    _write_json(_geospatial_policy_path(libraries_root, policy_id), doc)
    return doc


def update_geospatial_policy(
    libraries_root: str | Path,
    policy_id: str,
    *,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Update a geospatial policy, including the root override for the default."""

    if not isinstance(payload, Mapping):
        raise InvalidGeospatialPolicyError("Geospatial policy payload must be a JSON object.")
    doc = _normalized_policy_payload(payload, policy_id=str(policy_id))
    _write_json(_geospatial_policy_path(libraries_root, policy_id), doc)
    return doc


def delete_geospatial_policy(libraries_root: str | Path, policy_id: str) -> dict[str, Any]:
    """Delete a root-scoped geospatial policy override."""

    path = _geospatial_policy_path(libraries_root, policy_id)
    if not path.exists():
        if str(policy_id) == DEFAULT_GEOSPATIAL_POLICY_ID:
            return {"deleted": False, "policy_id": str(policy_id), "default_restored": True}
        raise GeospatialPolicyNotFoundError(
            "Geospatial policy was not found.",
            details={"policy_id": str(policy_id)},
        )
    path.unlink()
    return {"deleted": True, "policy_id": str(policy_id)}


def load_track_match(libraries_root: str | Path, track_match_id: str) -> dict[str, Any]:
    """Load one cached SessionTrackMatch object."""

    path = _track_match_path(libraries_root, track_match_id)
    if not path.exists():
        raise TrackMatchNotFoundError(
            "Track match was not found.",
            details={"track_match_id": str(track_match_id)},
        )
    return _read_json_object(path, TrackMatchNotFoundError)


def build_session_track_match(
    *,
    track: Mapping[str, Any],
    policy: Mapping[str, Any],
    session_ref: Mapping[str, Any],
    gps_summary: Mapping[str, Any],
    gps_points: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a SessionTrackMatch from session GPS points, falling back to summary data."""

    normalized_points = _normalized_gps_point_rows(gps_points)
    if normalized_points:
        match = _build_session_track_match_from_points(
            track=track,
            policy=policy,
            session_ref=session_ref,
            gps_summary=gps_summary,
            gps_points=gps_points or {},
            normalized_points=normalized_points,
        )
        if match is not None:
            return match

    return _build_session_track_match_from_summary(
        track=track,
        policy=policy,
        session_ref=session_ref,
        gps_summary=gps_summary,
    )


def build_session_track_no_overlap_match(
    *,
    track: Mapping[str, Any],
    policy: Mapping[str, Any],
    session_ref: Mapping[str, Any],
    gps_summary: Mapping[str, Any],
    warning: str = "session_gps_bbox_no_track_overlap",
) -> dict[str, Any]:
    """Build a cheap no-overlap SessionTrackMatch from catalog summary data."""

    track_id = str(track.get("track_id") or "")
    track_revision = track.get("revision")
    policy_id = str(policy.get("policy_id") or DEFAULT_GEOSPATIAL_POLICY_ID)
    session_ref_id = str(session_ref.get("session_ref_id") or "")
    gps_source_ref = _gps_source_ref(gps_summary=gps_summary)
    track_match_id = derive_object_id(
        f"{session_ref_id} {track_id} {track_revision} {policy_id} {_gps_source_identity(gps_source_ref)}",
        fallback="track-match",
    )
    path = track.get("path") if isinstance(track.get("path"), Mapping) else {}
    length_m = _number_or_none(path.get("length_m")) or 0.0
    point_count = int(_number_or_none(gps_summary.get("position_point_count")) or 0)
    warnings = _unique_warnings([warning] + [str(item) for item in gps_summary.get("warnings") or []])

    return {
        "schema": SESSION_TRACK_MATCH_SCHEMA,
        "version": SESSION_TRACK_MATCH_VERSION,
        "track_match_id": track_match_id,
        "library_id": session_ref.get("library_id"),
        "session_ref": dict(session_ref),
        "track_ref": {
            "track_id": track_id,
            "revision": track.get("revision"),
        },
        "policy_ref": {
            "policy_id": policy_id,
            "version": policy.get("version"),
        },
        "status": "no_overlap",
        "direction": "unknown",
        "coverage": {
            "track_start_station_m": 0.0,
            "track_end_station_m": length_m,
            "matched_start_station_m": None,
            "matched_end_station_m": None,
            "track_coverage_ratio": 0.0,
            "session_gps_point_count": point_count,
            "matched_gps_point_count": 0,
        },
        "trackpoint_results": [
            _trackpoint_result(
                trackpoint,
                status="no_overlap",
                coverage_ratio=0.0,
                length_m=length_m,
                session_duration_s=0.0,
                policy=policy,
            )
            for trackpoint in track.get("trackpoints") or []
            if isinstance(trackpoint, Mapping)
        ],
        "warnings": warnings,
        "provenance": {
            "derived_at": _utcnow_iso(),
            "derived_by": "bodaqs_analysis.library_api.geospatial",
            "algorithm": "session_track_match_bbox_prefilter_v0",
            "algorithm_version": "0.1.0",
            "gps_source": gps_source_ref,
        },
    }


def _build_session_track_match_from_summary(
    *,
    track: Mapping[str, Any],
    policy: Mapping[str, Any],
    session_ref: Mapping[str, Any],
    gps_summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a conservative fallback SessionTrackMatch from catalog GPS summary data."""

    track_id = str(track.get("track_id") or "")
    track_revision = track.get("revision")
    policy_id = str(policy.get("policy_id") or DEFAULT_GEOSPATIAL_POLICY_ID)
    session_ref_id = str(session_ref.get("session_ref_id") or "")
    gps_source_ref = _gps_source_ref(gps_summary=gps_summary)
    track_match_id = derive_object_id(
        f"{session_ref_id} {track_id} {track_revision} {policy_id} {_gps_source_identity(gps_source_ref)}",
        fallback="track-match",
    )
    path = track.get("path") if isinstance(track.get("path"), Mapping) else {}
    length_m = _number_or_none(path.get("length_m")) or 0.0
    gps_quality = str(gps_summary.get("quality") or "absent")
    gps_present = bool(gps_summary.get("present"))
    gps_coverage = _bounded_ratio(gps_summary.get("time_coverage_ratio"))
    session_duration_s = _number_or_none(gps_summary.get("session_duration_s")) or 0.0
    point_count = int(_number_or_none(gps_summary.get("position_point_count")) or 0)

    warnings: list[str] = []
    if not gps_present or gps_quality == "absent":
        status = "no_gps"
        direction = "unknown"
        coverage_ratio = 0.0
        warnings.append("session_has_no_gps")
    elif gps_quality == "invalid":
        status = "failed"
        direction = "unknown"
        coverage_ratio = 0.0
        warnings.append("session_gps_invalid")
    elif gps_quality == "usable" and gps_coverage >= 0.85:
        status = "matched"
        direction = "positive"
        coverage_ratio = gps_coverage
    else:
        status = "partial"
        direction = "positive"
        coverage_ratio = gps_coverage
        warnings.append("session_gps_limited")

    matched_end_station = length_m * coverage_ratio if length_m > 0 else 0.0
    matched_point_count = int(round(point_count * coverage_ratio))

    return {
        "schema": SESSION_TRACK_MATCH_SCHEMA,
        "version": SESSION_TRACK_MATCH_VERSION,
        "track_match_id": track_match_id,
        "library_id": session_ref.get("library_id"),
        "session_ref": dict(session_ref),
        "track_ref": {
            "track_id": track_id,
            "revision": track.get("revision"),
        },
        "policy_ref": {
            "policy_id": policy_id,
            "version": policy.get("version"),
        },
        "status": status,
        "direction": direction,
        "coverage": {
            "track_start_station_m": 0.0,
            "track_end_station_m": length_m,
            "matched_start_station_m": 0.0 if coverage_ratio > 0 else None,
            "matched_end_station_m": matched_end_station if coverage_ratio > 0 else None,
            "track_coverage_ratio": coverage_ratio,
            "session_gps_point_count": point_count,
            "matched_gps_point_count": matched_point_count,
        },
        "trackpoint_results": [
            _trackpoint_result(
                trackpoint,
                status=status,
                coverage_ratio=coverage_ratio,
                length_m=length_m,
                session_duration_s=session_duration_s,
                policy=policy,
            )
            for trackpoint in track.get("trackpoints") or []
            if isinstance(trackpoint, Mapping)
        ],
        "warnings": warnings + [str(item) for item in gps_summary.get("warnings") or []],
        "provenance": {
            "derived_at": _utcnow_iso(),
            "derived_by": "bodaqs_analysis.library_api.geospatial",
            "algorithm": "session_track_match_catalog_summary_v0",
            "algorithm_version": "0.1.0",
            "gps_source": gps_source_ref,
        },
    }


def write_track_match(libraries_root: str | Path, payload: Mapping[str, Any]) -> None:
    """Persist a computed SessionTrackMatch cache entry."""

    track_match_id = _required_text(
        payload.get("track_match_id"),
        field_name="track_match_id",
        error_cls=TrackMatchNotFoundError,
    )
    _write_json(_track_match_path(libraries_root, track_match_id), payload)


def _normalized_track_payload(
    payload: Mapping[str, Any],
    *,
    track_id: str,
    revision: int | None,
    now: str | None = None,
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise InvalidTrackError("Track payload must be a JSON object.")
    if not is_valid_object_id(track_id):
        raise InvalidTrackError("Track id is not filename-safe.", details={"track_id": track_id})

    doc = dict(payload)
    doc["schema"] = TRACK_SCHEMA
    doc["version"] = TRACK_VERSION
    doc["track_id"] = str(track_id)
    doc["display_name"] = _required_text(doc.get("display_name"), field_name="display_name", error_cls=InvalidTrackError)
    doc["revision"] = int((doc.get("revision") or 1) if revision is None else revision)

    path = _normalized_track_path(doc.get("path"))
    doc["path"] = path
    doc["direction"] = _normalized_track_direction(doc.get("direction"))
    doc["default_policy_ref"] = _normalized_track_policy_ref(doc.get("default_policy_ref"))
    doc["trackpoints"] = sorted(
        (
            _normalized_trackpoint(trackpoint, index=index, track_length_m=path.get("length_m"))
            for index, trackpoint in enumerate(list(doc.get("trackpoints") or []))
        ),
        key=lambda item: float(item.get("station_m") or 0.0),
    )
    doc["segment_aliases"] = _normalized_segment_aliases(
        doc.get("segment_aliases"),
        trackpoints=doc["trackpoints"],
    )

    source = doc.get("source")
    if source is not None and not isinstance(source, Mapping):
        raise InvalidTrackError("Track source must be an object when present.")
    if source is not None:
        doc["source"] = dict(source)

    now = now or _utcnow_iso()
    previous_provenance = previous.get("provenance") if isinstance(previous, Mapping) else None
    provenance = doc.get("provenance")
    provenance = dict(provenance) if isinstance(provenance, Mapping) else {}
    if isinstance(previous_provenance, Mapping):
        provenance.setdefault("created_at", previous_provenance.get("created_at"))
        provenance.setdefault("created_by", previous_provenance.get("created_by"))
        provenance.setdefault("created_from", previous_provenance.get("created_from"))
    provenance.setdefault("created_at", now)
    provenance.setdefault("created_by", "user")
    provenance.setdefault("created_from", {"kind": "manual_track", "details": {}})
    provenance["updated_at"] = now
    doc["provenance"] = provenance

    display_state = doc.get("display_state")
    doc["display_state"] = dict(display_state) if isinstance(display_state, Mapping) else {"bodaqs_web_v1": {}}
    doc["display_state"].setdefault("bodaqs_web_v1", {})
    return doc


def _normalized_track_path(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidTrackError("Track path must be an object.")
    path = dict(value)
    if str(path.get("type") or "") != "LineString":
        raise InvalidTrackError("Track path.type must be 'LineString'.")
    coordinates = _normalized_line_coordinates(path.get("coordinates"))
    path["coordinates"] = coordinates
    path["coordinate_reference_system"] = str(path.get("coordinate_reference_system") or "EPSG:4326")
    path["distance_model"] = str(path.get("distance_model") or "geodesic")
    length_m = _number_or_none(path.get("length_m"))
    if length_m is None or length_m <= 0:
        length_m = _line_length_m(coordinates)
    path["length_m"] = float(length_m)
    return path


def _normalized_line_coordinates(value: Any) -> list[list[float]]:
    if not isinstance(value, list) or len(value) < 2:
        raise InvalidTrackError("Track path.coordinates must contain at least two positions.")
    return [_normalized_position(coord, context=f"path.coordinates[{index}]") for index, coord in enumerate(value)]


def _normalized_track_direction(value: Any) -> dict[str, Any]:
    direction = dict(value) if isinstance(value, Mapping) else {}
    direction.setdefault("positive", "coordinate_order")
    direction.setdefault("description", "Positive direction follows the stored coordinate order.")
    return direction


def _normalized_track_policy_ref(value: Any) -> dict[str, Any]:
    policy_ref = dict(value) if isinstance(value, Mapping) else {}
    policy_ref["policy_id"] = _optional_text(policy_ref.get("policy_id")) or DEFAULT_GEOSPATIAL_POLICY_ID
    if policy_ref.get("version") is None:
        policy_ref["version"] = GEOSPATIAL_POLICY_VERSION
    return policy_ref


def _normalized_trackpoint(value: Any, *, index: int, track_length_m: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidTrackError(f"trackpoints[{index}] must be an object.")
    out = dict(value)
    out["trackpoint_id"] = _required_text(
        value.get("trackpoint_id"),
        field_name=f"trackpoints[{index}].trackpoint_id",
        error_cls=InvalidTrackError,
    )
    out["display_name"] = _optional_text(value.get("display_name")) or _display_name_from_id(out["trackpoint_id"])
    station_m = _required_number(
        value.get("station_m"),
        field_name=f"trackpoints[{index}].station_m",
        error_cls=InvalidTrackError,
    )
    length_m = _number_or_none(track_length_m)
    if station_m < 0 or (length_m is not None and station_m > length_m):
        raise InvalidTrackError(
            "Trackpoint station_m must lie within the track length.",
            details={"trackpoint_id": out["trackpoint_id"], "station_m": station_m, "track_length_m": length_m},
        )
    out["station_m"] = station_m
    position = value.get("position")
    if not isinstance(position, Mapping) or str(position.get("type") or "") != "Point":
        raise InvalidTrackError(f"trackpoints[{index}].position must be a Point object.")
    out["position"] = {
        "type": "Point",
        "coordinates": _normalized_position(
            position.get("coordinates"),
            context=f"trackpoints[{index}].position.coordinates",
        ),
    }
    override = value.get("cutline_override")
    if override is not None:
        if not isinstance(override, Mapping):
            raise InvalidTrackError(f"trackpoints[{index}].cutline_override must be an object.")
        out["cutline_override"] = {
            key: float(raw)
            for key, raw in dict(override).items()
            if key in {"left_length_m", "right_length_m", "angle_deg_from_path_normal"}
            and _number_or_none(raw) is not None
        }
    return out


def _normalized_segment_aliases(value: Any, *, trackpoints: list[dict[str, Any]]) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise InvalidTrackError("Track segment_aliases must be a list when present.")

    adjacent_pairs: set[tuple[str, str]] = set()
    default_names: dict[tuple[str, str], str] = {}
    for pair_index in range(max(0, len(trackpoints) - 1)):
        pair = (
            str(trackpoints[pair_index].get("trackpoint_id") or ""),
            str(trackpoints[pair_index + 1].get("trackpoint_id") or ""),
        )
        adjacent_pairs.add(pair)
        default_names[pair] = f"Segment {pair_index + 1}"
    aliases: list[dict[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise InvalidTrackError(f"segment_aliases[{index}] must be an object.")
        from_trackpoint_id = _optional_text(item.get("from_trackpoint_id"))
        to_trackpoint_id = _optional_text(item.get("to_trackpoint_id"))
        display_name = _optional_text(item.get("display_name")) or _optional_text(item.get("name"))
        timing_role = _optional_text(item.get("timing_role")) or "timed"
        if timing_role not in {"timed", "untimed"}:
            timing_role = "timed"
        if not from_trackpoint_id or not to_trackpoint_id:
            continue
        pair = (from_trackpoint_id, to_trackpoint_id)
        if not display_name and timing_role == "untimed":
            display_name = default_names.get(pair, f"Segment {index + 1}")
        if not display_name:
            continue
        if pair not in adjacent_pairs or pair in seen_pairs:
            continue
        alias = {
            "from_trackpoint_id": from_trackpoint_id,
            "to_trackpoint_id": to_trackpoint_id,
            "display_name": display_name,
        }
        if timing_role == "untimed":
            alias["timing_role"] = timing_role
        aliases.append(alias)
        seen_pairs.add(pair)
    return aliases


def _normalized_position(value: Any, *, context: str) -> list[float]:
    if not isinstance(value, list) or len(value) < 2:
        raise InvalidTrackError(f"{context} must be a coordinate array with lon/lat.")
    coordinates: list[float] = []
    for index, item in enumerate(value[:3]):
        number = _number_or_none(item)
        if number is None:
            raise InvalidTrackError(f"{context}[{index}] must be numeric.")
        coordinates.append(float(number))
    return coordinates


def _normalized_policy_payload(payload: Mapping[str, Any], *, policy_id: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise InvalidGeospatialPolicyError("Geospatial policy payload must be a JSON object.")
    if not is_valid_object_id(policy_id):
        raise InvalidGeospatialPolicyError(
            "Geospatial policy id is not filename-safe.",
            details={"policy_id": policy_id},
        )

    default = _default_geospatial_policy()
    doc = copy.deepcopy(default)
    doc.update(dict(payload))
    doc["schema"] = GEOSPATIAL_POLICY_SCHEMA
    doc["version"] = GEOSPATIAL_POLICY_VERSION
    doc["policy_id"] = str(policy_id)
    doc["display_name"] = _required_text(
        doc.get("display_name"),
        field_name="display_name",
        error_cls=InvalidGeospatialPolicyError,
    )

    doc["path_policy"] = _merged_object(default["path_policy"], doc.get("path_policy"))
    doc["trackpoint_policy"] = _merged_object(default["trackpoint_policy"], doc.get("trackpoint_policy"))
    doc["matching_policy"] = _merged_object(default["matching_policy"], doc.get("matching_policy"))
    doc["profile_policy"] = _merged_object(default["profile_policy"], doc.get("profile_policy"))
    _validate_policy_numbers(doc)

    provenance = doc.get("provenance")
    doc["provenance"] = dict(provenance) if isinstance(provenance, Mapping) else {"created_by": "user"}
    doc["provenance"].setdefault("created_at", _utcnow_iso())
    doc["provenance"].setdefault("created_by", "user")
    return doc


def _default_geospatial_policy() -> dict[str, Any]:
    return {
        "schema": GEOSPATIAL_POLICY_SCHEMA,
        "version": GEOSPATIAL_POLICY_VERSION,
        "policy_id": DEFAULT_GEOSPATIAL_POLICY_ID,
        "display_name": "Default geospatial policy",
        "path_policy": {
            "distance_model": "geodesic",
            "simplification_tolerance_m": 0.5,
            "smoothing_window_m": 3.0,
            "elevation_source_preference": ["gps_altitude", "barometric_altitude", "none"],
        },
        "trackpoint_policy": {
            "default_cutline_left_length_m": 5.0,
            "default_cutline_right_length_m": 5.0,
            "default_cutline_angle_deg_from_path_normal": 0.0,
        },
        "matching_policy": {
            "position_source_preference": ["logger_sensor", "fit_enrichment"],
            "max_point_distance_m": 8.0,
            "cutline_crossing_required": True,
            "multi_crossing_policy": "nearest_to_trackpoint",
            "reverse_direction_policy": "allow_and_report",
        },
        "profile_policy": {
            "heading_smoothing_window_m": 5.0,
            "gradient_smoothing_window_m": 10.0,
            "curvature_smoothing_window_m": 5.0,
        },
        "provenance": {
            "created_at": "2026-06-02T00:00:00Z",
            "created_by": "system_default",
        },
    }


def _validate_policy_numbers(doc: Mapping[str, Any]) -> None:
    checks = [
        ("trackpoint_policy.default_cutline_left_length_m", doc["trackpoint_policy"].get("default_cutline_left_length_m")),
        ("trackpoint_policy.default_cutline_right_length_m", doc["trackpoint_policy"].get("default_cutline_right_length_m")),
        ("matching_policy.max_point_distance_m", doc["matching_policy"].get("max_point_distance_m")),
    ]
    for field_name, value in checks:
        number = _number_or_none(value)
        if number is None or number < 0:
            raise InvalidGeospatialPolicyError(f"{field_name} must be a non-negative number.")


def _trackpoint_result(
    trackpoint: Mapping[str, Any],
    *,
    status: str,
    coverage_ratio: float,
    length_m: float,
    session_duration_s: float,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    station_m = _number_or_none(trackpoint.get("station_m")) or 0.0
    crossed = status in {"matched", "partial"} and length_m > 0 and station_m <= length_m * coverage_ratio
    crossing_time_s = station_m / length_m * session_duration_s if crossed and session_duration_s > 0 else None
    matching_policy = policy.get("matching_policy") if isinstance(policy.get("matching_policy"), Mapping) else {}
    max_distance = _number_or_none(matching_policy.get("max_point_distance_m")) or 8.0
    return {
        "trackpoint_id": trackpoint.get("trackpoint_id"),
        "crossed": crossed,
        "crossing_time_s": crossing_time_s,
        "crossing_station_m": station_m if crossed else None,
        "min_distance_m": max_distance / 4.0 if crossed else None,
        "quality": "good" if status == "matched" and crossed else ("approximate" if crossed else "missing"),
    }


def _gps_source_ref(
    *,
    gps_summary: Mapping[str, Any],
    gps_points: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    point_source = gps_points.get("source") if isinstance(gps_points, Mapping) and isinstance(gps_points.get("source"), Mapping) else {}
    return {
        "source_id": point_source.get("source_id") or gps_summary.get("preferred_source_id") or gps_summary.get("preferred_source"),
        "kind": point_source.get("kind") or gps_summary.get("preferred_source_kind"),
        "stream_name": point_source.get("stream_name"),
        "source_selection_method": point_source.get("source_selection_method") or gps_summary.get("source_selection_method"),
        "gps_source_policy": point_source.get("gps_source_policy") or gps_summary.get("gps_source_policy"),
        "route_reconstruction": point_source.get("route_reconstruction"),
    }


def _gps_source_identity(source_ref: Mapping[str, Any]) -> str:
    identity = {
        "source_id": source_ref.get("source_id"),
        "kind": source_ref.get("kind"),
        "source_selection_method": source_ref.get("source_selection_method"),
        "gps_source_policy": source_ref.get("gps_source_policy"),
        "route_reconstruction": source_ref.get("route_reconstruction"),
    }
    return json.dumps(identity, sort_keys=True, separators=(",", ":"))


def _build_session_track_match_from_points(
    *,
    track: Mapping[str, Any],
    policy: Mapping[str, Any],
    session_ref: Mapping[str, Any],
    gps_summary: Mapping[str, Any],
    gps_points: Mapping[str, Any],
    normalized_points: list[dict[str, Any]],
) -> dict[str, Any] | None:
    path = track.get("path") if isinstance(track.get("path"), Mapping) else {}
    track_coordinates = _track_coordinate_rows(path.get("coordinates"))
    if len(track_coordinates) < 2:
        return None

    declared_length_m = _number_or_none(path.get("length_m")) or _line_length_m(
        [[coord["longitude"], coord["latitude"]] for coord in track_coordinates]
    )
    origin = _projection_origin(track_coordinates, normalized_points)
    track_geometry = _projected_track_geometry(
        track_coordinates,
        origin=origin,
        declared_length_m=declared_length_m,
    )
    if track_geometry is None:
        return None

    projected_gps = [
        {
            **point,
            "xy": _project_lon_lat(point["longitude"], point["latitude"], origin=origin),
        }
        for point in normalized_points
    ]
    matching_policy = policy.get("matching_policy") if isinstance(policy.get("matching_policy"), Mapping) else {}
    max_distance_m = _number_or_none(matching_policy.get("max_point_distance_m")) or 8.0
    projected_to_track = [
        {
            "point": point,
            "projection": _nearest_track_projection(point["xy"], track_geometry),
        }
        for point in projected_gps
    ]
    matched_projections = [
        item
        for item in projected_to_track
        if item["projection"] is not None
        and float(item["projection"]["distance_m"]) <= max_distance_m
    ]

    warnings = _unique_warnings(
        [str(item) for item in gps_summary.get("warnings") or []]
        + [str(item) for item in gps_points.get("warnings") or []]
    )
    sampling = gps_points.get("sampling") if isinstance(gps_points.get("sampling"), Mapping) else {}
    if str(sampling.get("mode") or "") == "stride":
        warnings.append("gps_points_sampled_for_track_match")

    coverage = _track_coverage(
        matched_projections,
        track_length_m=float(track_geometry["declared_length_m"]),
        session_gps_point_count=int(_number_or_none(sampling.get("source_points")) or len(normalized_points)),
    )
    if not matched_projections:
        status = "no_overlap"
        direction = "unknown"
        warnings.append("session_gps_no_track_overlap")
    else:
        status = "matched" if coverage["track_coverage_ratio"] >= 0.85 else "partial"
        direction = _direction_from_station_sequence(matched_projections)
        if status == "partial":
            warnings.append("session_gps_partial_track_overlap")

    track_id = str(track.get("track_id") or "")
    track_revision = track.get("revision")
    policy_id = str(policy.get("policy_id") or DEFAULT_GEOSPATIAL_POLICY_ID)
    session_ref_id = str(session_ref.get("session_ref_id") or "")
    gps_source_ref = _gps_source_ref(gps_summary=gps_summary, gps_points=gps_points)
    track_match_id = derive_object_id(
        f"{session_ref_id} {track_id} {track_revision} {policy_id} {_gps_source_identity(gps_source_ref)}",
        fallback="track-match",
    )
    return {
        "schema": SESSION_TRACK_MATCH_SCHEMA,
        "version": SESSION_TRACK_MATCH_VERSION,
        "track_match_id": track_match_id,
        "library_id": session_ref.get("library_id"),
        "session_ref": dict(session_ref),
        "track_ref": {
            "track_id": track_id,
            "revision": track.get("revision"),
        },
        "policy_ref": {
            "policy_id": policy_id,
            "version": policy.get("version"),
        },
        "status": status,
        "direction": direction,
        "coverage": coverage,
        "trackpoint_results": [
            _trackpoint_result_from_geometry(
                trackpoint,
                track_geometry=track_geometry,
                gps_points=projected_gps,
                policy=policy,
            )
            for trackpoint in track.get("trackpoints") or []
            if isinstance(trackpoint, Mapping)
        ],
        "warnings": _unique_warnings(warnings),
        "provenance": {
            "derived_at": _utcnow_iso(),
            "derived_by": "bodaqs_analysis.library_api.geospatial",
            "algorithm": "session_track_match_geometry_v0",
            "algorithm_version": "0.2.0",
            "gps_source": gps_source_ref,
        },
    }


def _track_coverage(
    matched_projections: list[dict[str, Any]],
    *,
    track_length_m: float,
    session_gps_point_count: int,
) -> dict[str, Any]:
    stations = [
        float(item["projection"]["station_m"])
        for item in matched_projections
        if item.get("projection") is not None
    ]
    if not stations or track_length_m <= 0:
        return {
            "track_start_station_m": 0.0,
            "track_end_station_m": track_length_m,
            "matched_start_station_m": None,
            "matched_end_station_m": None,
            "track_coverage_ratio": 0.0,
            "session_gps_point_count": session_gps_point_count,
            "matched_gps_point_count": 0,
        }
    start_station = min(stations)
    end_station = max(stations)
    coverage_ratio = min(1.0, max(0.0, (end_station - start_station) / track_length_m))
    return {
        "track_start_station_m": 0.0,
        "track_end_station_m": track_length_m,
        "matched_start_station_m": start_station,
        "matched_end_station_m": end_station,
        "track_coverage_ratio": coverage_ratio,
        "session_gps_point_count": session_gps_point_count,
        "matched_gps_point_count": len(stations),
    }


def _trackpoint_result_from_geometry(
    trackpoint: Mapping[str, Any],
    *,
    track_geometry: Mapping[str, Any],
    gps_points: list[dict[str, Any]],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    trackpoint_id = trackpoint.get("trackpoint_id")
    station_m = _number_or_none(trackpoint.get("station_m")) or 0.0
    cutline = _trackpoint_cutline(trackpoint, track_geometry=track_geometry, policy=policy)
    if cutline is None:
        return {
            "trackpoint_id": trackpoint_id,
            "crossed": False,
            "crossing_time_s": None,
            "crossing_station_m": None,
            "min_distance_m": None,
            "quality": "missing",
        }

    matching_policy = policy.get("matching_policy") if isinstance(policy.get("matching_policy"), Mapping) else {}
    max_distance_m = _number_or_none(matching_policy.get("max_point_distance_m")) or 8.0
    cutline_crossing_required = bool(matching_policy.get("cutline_crossing_required", True))
    crossings: list[dict[str, Any]] = []
    for segment_index, (start, end) in enumerate(zip(gps_points, gps_points[1:])):
        intersection = _segment_intersection(
            start["xy"],
            end["xy"],
            cutline["start_xy"],
            cutline["end_xy"],
        )
        if intersection is None:
            continue
        crossing_xy, segment_t = intersection
        crossings.append(
            {
                "segment_index": segment_index,
                "segment_t": segment_t,
                "xy": crossing_xy,
                "distance_m": _distance(crossing_xy, cutline["anchor_xy"]),
                "time_s": _interpolated_time(start.get("time_s"), end.get("time_s"), segment_t),
            }
        )

    if crossings:
        chosen = _choose_crossing(crossings, matching_policy)
        distance_m = float(chosen["distance_m"])
        return {
            "trackpoint_id": trackpoint_id,
            "crossed": True,
            "crossing_time_s": chosen.get("time_s"),
            "crossing_station_m": station_m,
            "min_distance_m": distance_m,
            "quality": "good" if distance_m <= max_distance_m else "approximate",
        }

    nearest = _nearest_gps_distance(cutline["anchor_xy"], gps_points)
    min_distance_m = None if nearest is None else float(nearest["distance_m"])
    if not cutline_crossing_required and min_distance_m is not None and min_distance_m <= max_distance_m:
        return {
            "trackpoint_id": trackpoint_id,
            "crossed": True,
            "crossing_time_s": nearest.get("time_s"),
            "crossing_station_m": station_m,
            "min_distance_m": min_distance_m,
            "quality": "approximate",
        }

    return {
        "trackpoint_id": trackpoint_id,
        "crossed": False,
        "crossing_time_s": None,
        "crossing_station_m": None,
        "min_distance_m": min_distance_m,
        "quality": "missing",
    }


def _trackpoint_cutline(
    trackpoint: Mapping[str, Any],
    *,
    track_geometry: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any] | None:
    station_m = _number_or_none(trackpoint.get("station_m")) or 0.0
    station_state = _track_state_at_station(station_m, track_geometry)
    if station_state is None:
        return None

    origin = track_geometry["origin"]
    position = trackpoint.get("position") if isinstance(trackpoint.get("position"), Mapping) else {}
    coordinates = position.get("coordinates") if isinstance(position, Mapping) else None
    anchor_xy = _project_position_or_none(coordinates, origin=origin) or station_state["xy"]

    trackpoint_policy = policy.get("trackpoint_policy") if isinstance(policy.get("trackpoint_policy"), Mapping) else {}
    override = trackpoint.get("cutline_override") if isinstance(trackpoint.get("cutline_override"), Mapping) else {}
    left_length_m = _policy_number(
        override.get("left_length_m"),
        trackpoint_policy.get("default_cutline_left_length_m"),
        default=5.0,
    )
    right_length_m = _policy_number(
        override.get("right_length_m"),
        trackpoint_policy.get("default_cutline_right_length_m"),
        default=5.0,
    )
    angle_deg = _policy_number(
        override.get("angle_deg_from_path_normal"),
        trackpoint_policy.get("default_cutline_angle_deg_from_path_normal"),
        default=0.0,
    )
    heading = station_state["unit"]
    normal = (-heading[1], heading[0])
    cutline_unit = _rotate_unit(normal, math.radians(angle_deg))
    return {
        "anchor_xy": anchor_xy,
        "start_xy": _add_scaled(anchor_xy, cutline_unit, left_length_m),
        "end_xy": _add_scaled(anchor_xy, cutline_unit, -right_length_m),
    }


def _choose_crossing(crossings: list[dict[str, Any]], matching_policy: Mapping[str, Any]) -> dict[str, Any]:
    policy = str(matching_policy.get("multi_crossing_policy") or "nearest_to_trackpoint")
    if policy == "first":
        return min(crossings, key=lambda item: (int(item["segment_index"]), float(item["segment_t"])))
    if policy == "last":
        return max(crossings, key=lambda item: (int(item["segment_index"]), float(item["segment_t"])))
    return min(crossings, key=lambda item: float(item["distance_m"]))


def _normalized_gps_point_rows(gps_points: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(gps_points, Mapping):
        return []
    rows: list[dict[str, Any]] = []
    for raw in gps_points.get("points") or []:
        if not isinstance(raw, Mapping):
            continue
        longitude = _number_or_none(raw.get("longitude"))
        latitude = _number_or_none(raw.get("latitude"))
        if longitude is None or latitude is None:
            continue
        rows.append(
            {
                "longitude": float(longitude),
                "latitude": float(latitude),
                "time_s": _number_or_none(raw.get("time_s")),
                "elevation_m": _number_or_none(raw.get("elevation_m")),
            }
        )
    return rows


def _track_coordinate_rows(value: Any) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    if not isinstance(value, list):
        return rows
    for raw in value:
        if not isinstance(raw, list) or len(raw) < 2:
            continue
        longitude = _number_or_none(raw[0])
        latitude = _number_or_none(raw[1])
        if longitude is None or latitude is None:
            continue
        rows.append({"longitude": float(longitude), "latitude": float(latitude)})
    return rows


def _projection_origin(
    track_coordinates: list[dict[str, float]],
    gps_points: list[dict[str, Any]],
) -> tuple[float, float]:
    latitudes = [coord["latitude"] for coord in track_coordinates] + [point["latitude"] for point in gps_points]
    longitudes = [coord["longitude"] for coord in track_coordinates] + [point["longitude"] for point in gps_points]
    return sum(latitudes) / len(latitudes), sum(longitudes) / len(longitudes)


def _projected_track_geometry(
    track_coordinates: list[dict[str, float]],
    *,
    origin: tuple[float, float],
    declared_length_m: float,
) -> dict[str, Any] | None:
    points = [
        _project_lon_lat(coord["longitude"], coord["latitude"], origin=origin)
        for coord in track_coordinates
    ]
    stations = [0.0]
    for start, end in zip(points, points[1:]):
        stations.append(stations[-1] + _distance(start, end))
    projected_length_m = stations[-1]
    if projected_length_m <= 0:
        return None
    return {
        "origin": origin,
        "points": points,
        "projected_stations_m": stations,
        "projected_length_m": projected_length_m,
        "declared_length_m": declared_length_m if declared_length_m > 0 else projected_length_m,
    }


def _project_lon_lat(longitude: float, latitude: float, *, origin: tuple[float, float]) -> tuple[float, float]:
    origin_lat, origin_lon = origin
    x = math.radians(longitude - origin_lon) * _EARTH_RADIUS_M * math.cos(math.radians(origin_lat))
    y = math.radians(latitude - origin_lat) * _EARTH_RADIUS_M
    return x, y


def _project_position_or_none(value: Any, *, origin: tuple[float, float]) -> tuple[float, float] | None:
    if not isinstance(value, list) or len(value) < 2:
        return None
    longitude = _number_or_none(value[0])
    latitude = _number_or_none(value[1])
    if longitude is None or latitude is None:
        return None
    return _project_lon_lat(float(longitude), float(latitude), origin=origin)


def _track_state_at_station(station_m: float, track_geometry: Mapping[str, Any]) -> dict[str, Any] | None:
    points = track_geometry["points"]
    stations = track_geometry["projected_stations_m"]
    projected_station = _declared_to_projected_station(station_m, track_geometry)
    projected_station = min(float(track_geometry["projected_length_m"]), max(0.0, projected_station))
    for index, (start_station, end_station) in enumerate(zip(stations, stations[1:])):
        start_xy = points[index]
        end_xy = points[index + 1]
        segment_length = end_station - start_station
        if segment_length <= 0:
            continue
        if projected_station <= end_station or index == len(points) - 2:
            segment_t = min(1.0, max(0.0, (projected_station - start_station) / segment_length))
            direction = _unit(_sub(end_xy, start_xy))
            return {
                "xy": _lerp_xy(start_xy, end_xy, segment_t),
                "unit": direction,
            }
    return None


def _nearest_track_projection(
    xy: tuple[float, float],
    track_geometry: Mapping[str, Any],
) -> dict[str, float] | None:
    points = track_geometry["points"]
    stations = track_geometry["projected_stations_m"]
    best: dict[str, float] | None = None
    for index, (start_xy, end_xy) in enumerate(zip(points, points[1:])):
        segment_length = stations[index + 1] - stations[index]
        if segment_length <= 0:
            continue
        projection_xy, segment_t = _point_segment_projection(xy, start_xy, end_xy)
        projected_station = stations[index] + segment_length * segment_t
        distance_m = _distance(xy, projection_xy)
        candidate = {
            "station_m": _projected_to_declared_station(projected_station, track_geometry),
            "distance_m": distance_m,
        }
        if best is None or distance_m < best["distance_m"]:
            best = candidate
    return best


def _nearest_gps_distance(
    xy: tuple[float, float],
    gps_points: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not gps_points:
        return None
    if len(gps_points) == 1:
        return {
            "distance_m": _distance(xy, gps_points[0]["xy"]),
            "time_s": gps_points[0].get("time_s"),
        }

    best: dict[str, Any] | None = None
    for start, end in zip(gps_points, gps_points[1:]):
        projection_xy, segment_t = _point_segment_projection(xy, start["xy"], end["xy"])
        distance_m = _distance(xy, projection_xy)
        candidate = {
            "distance_m": distance_m,
            "time_s": _interpolated_time(start.get("time_s"), end.get("time_s"), segment_t),
        }
        if best is None or distance_m < float(best["distance_m"]):
            best = candidate
    return best


def _direction_from_station_sequence(matched_projections: list[dict[str, Any]]) -> str:
    station_sequence = [
        float(item["projection"]["station_m"])
        for item in matched_projections
        if item.get("projection") is not None
    ]
    if len(station_sequence) < 2:
        return "unknown"
    delta = station_sequence[-1] - station_sequence[0]
    if abs(delta) < 1e-6:
        return "ambiguous"
    return "positive" if delta > 0 else "negative"


def _declared_to_projected_station(station_m: float, track_geometry: Mapping[str, Any]) -> float:
    declared_length = float(track_geometry["declared_length_m"])
    projected_length = float(track_geometry["projected_length_m"])
    if declared_length <= 0:
        return station_m
    return station_m / declared_length * projected_length


def _projected_to_declared_station(projected_station_m: float, track_geometry: Mapping[str, Any]) -> float:
    declared_length = float(track_geometry["declared_length_m"])
    projected_length = float(track_geometry["projected_length_m"])
    if projected_length <= 0:
        return projected_station_m
    return projected_station_m / projected_length * declared_length


def _point_segment_projection(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> tuple[tuple[float, float], float]:
    segment = _sub(end, start)
    length_sq = _dot(segment, segment)
    if length_sq <= 0:
        return start, 0.0
    t = min(1.0, max(0.0, _dot(_sub(point, start), segment) / length_sq))
    return _lerp_xy(start, end, t), t


def _segment_intersection(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> tuple[tuple[float, float], float] | None:
    r = _sub(b, a)
    s = _sub(d, c)
    denominator = _cross(r, s)
    c_minus_a = _sub(c, a)
    if abs(denominator) < 1e-9:
        return None
    t = _cross(c_minus_a, s) / denominator
    u = _cross(c_minus_a, r) / denominator
    if -1e-9 <= t <= 1.0 + 1e-9 and -1e-9 <= u <= 1.0 + 1e-9:
        clamped_t = min(1.0, max(0.0, t))
        return _lerp_xy(a, b, clamped_t), clamped_t
    return None


def _interpolated_time(start_time: Any, end_time: Any, segment_t: float) -> float | None:
    start = _number_or_none(start_time)
    end = _number_or_none(end_time)
    if start is None or end is None:
        return None
    return float(start + (end - start) * segment_t)


def _policy_number(primary: Any, fallback: Any, *, default: float) -> float:
    primary_number = _number_or_none(primary)
    if primary_number is not None:
        return float(primary_number)
    fallback_number = _number_or_none(fallback)
    if fallback_number is not None:
        return float(fallback_number)
    return default


def _unique_warnings(warnings: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for warning in warnings:
        text = str(warning)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _add_scaled(
    xy: tuple[float, float],
    unit: tuple[float, float],
    scale: float,
) -> tuple[float, float]:
    return xy[0] + unit[0] * scale, xy[1] + unit[1] * scale


def _rotate_unit(unit: tuple[float, float], angle_rad: float) -> tuple[float, float]:
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    return _unit((unit[0] * cos_a - unit[1] * sin_a, unit[0] * sin_a + unit[1] * cos_a))


def _unit(vector: tuple[float, float]) -> tuple[float, float]:
    length = math.hypot(vector[0], vector[1])
    if length <= 0:
        return 1.0, 0.0
    return vector[0] / length, vector[1] / length


def _lerp_xy(
    start: tuple[float, float],
    end: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    return start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t


def _sub(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return a[0] - b[0], a[1] - b[1]


def _dot(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _cross(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _track_path(libraries_root: str | Path, track_id: str) -> Path:
    return _object_path(_tracks_dir(libraries_root), track_id, error_cls=InvalidTrackError, field_name="track_id")


def _geospatial_policy_path(libraries_root: str | Path, policy_id: str) -> Path:
    return _object_path(
        _geospatial_policies_dir(libraries_root),
        policy_id,
        error_cls=InvalidGeospatialPolicyError,
        field_name="policy_id",
    )


def _track_match_path(libraries_root: str | Path, track_match_id: str) -> Path:
    return _object_path(
        _track_matches_dir(libraries_root),
        track_match_id,
        error_cls=TrackMatchNotFoundError,
        field_name="track_match_id",
    )


def _tracks_dir(libraries_root: str | Path) -> Path:
    return Path(libraries_root).expanduser() / TRACKS_DIR


def _geospatial_policies_dir(libraries_root: str | Path) -> Path:
    return Path(libraries_root).expanduser() / GEOSPATIAL_POLICIES_DIR


def _track_matches_dir(libraries_root: str | Path) -> Path:
    return Path(libraries_root).expanduser() / TRACK_MATCHES_DIR


def _object_path(directory: Path, object_id: str, *, error_cls: type[Exception], field_name: str) -> Path:
    object_id = _required_text(object_id, field_name=field_name, error_cls=error_cls)
    if not is_valid_object_id(object_id):
        raise error_cls(f"{field_name} is not filename-safe.", details={field_name: object_id})
    return directory / f"{object_id}.json"


def _read_json_object(path: Path, error_cls: type[Exception]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise error_cls(
            "JSON object could not be read.",
            details={"path": str(path), "error": f"{type(exc).__name__}: {exc}"},
        ) from exc
    if not isinstance(value, Mapping):
        raise error_cls("JSON document must be an object.", details={"path": str(path)})
    return dict(value)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _merged_object(default: Mapping[str, Any], value: Any) -> dict[str, Any]:
    out = dict(default)
    if isinstance(value, Mapping):
        out.update(dict(value))
    return out


def _line_length_m(coordinates: list[list[float]]) -> float:
    total = 0.0
    for start, end in zip(coordinates, coordinates[1:]):
        total += _haversine_m(start[1], start[0], end[1], end[0])
    return total


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    return _EARTH_RADIUS_M * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def _required_text(value: Any, *, field_name: str, error_cls: type[Exception]) -> str:
    text = _optional_text(value)
    if text is None:
        raise error_cls(f"Missing non-empty {field_name!r}.")
    return text


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _required_number(value: Any, *, field_name: str, error_cls: type[Exception]) -> float:
    number = _number_or_none(value)
    if number is None:
        raise error_cls(f"{field_name} must be numeric.")
    return float(number)


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _bounded_ratio(value: Any) -> float:
    number = _number_or_none(value)
    if number is None:
        return 0.0
    return min(1.0, max(0.0, number))


def _display_name_from_id(value: str) -> str:
    words = str(value).replace("_", " ").replace("-", " ").strip()
    return words.title() if words else "Trackpoint"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
