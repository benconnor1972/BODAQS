"""High-level Python facade for processed BODAQS libraries."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping

from .catalog import (
    build_session_catalog,
    discover_libraries,
    get_session_gps_points as catalog_get_session_gps_points,
)
from .errors import InvalidRequestError, LibraryApiError, LibraryNotFoundError, SessionNotFoundError
from .geospatial import (
    DEFAULT_GEOSPATIAL_POLICY_ID,
    build_session_track_match,
    create_geospatial_policy,
    create_track,
    delete_geospatial_policy,
    delete_track,
    list_geospatial_policies,
    list_tracks,
    load_geospatial_policy,
    load_track,
    load_track_match,
    update_geospatial_policy,
    update_track,
    write_track_match,
)
from .ids import make_session_key, make_session_ref_id, parse_session_key
from .models import default_capabilities
from .selection import study_set_to_selection_snapshot
from .session_filters import (
    create_session_filter,
    delete_session_filter,
    list_session_filters,
    load_session_filter,
    update_session_filter,
)
from .session_notes import load_session_note, save_session_note
from .study_sets import (
    create_study_set,
    delete_study_set,
    list_study_sets,
    load_study_set,
    update_study_set,
)
from .timeseries import get_timeseries_window
from .trackpoint_queries import (
    cancel_trackpoint_match_query,
    complete_trackpoint_match_query,
    create_trackpoint_match_query_record,
    fail_trackpoint_match_query,
    load_trackpoint_match_query,
    load_trackpoint_match_query_results,
    update_trackpoint_match_query,
    write_trackpoint_match_query_results,
)


class LibraryAdapter:
    """Adapter facade that maps processed libraries to Library API payloads."""

    def __init__(self, libraries_root: str | Path) -> None:
        self.libraries_root = Path(libraries_root).expanduser()
        self._libraries_cache: list[dict[str, Any]] | None = None
        self._catalog_cache: dict[str, dict[str, Any]] = {}

    def capabilities(self) -> dict[str, Any]:
        return default_capabilities()

    def list_libraries(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        if refresh or self._libraries_cache is None:
            self._libraries_cache = discover_libraries(self.libraries_root)
        return [dict(library) for library in self._libraries_cache]

    def get_library(self, library_id: str) -> dict[str, Any]:
        wanted = str(library_id).strip()
        for library in self.list_libraries():
            if str(library.get("library_id")) == wanted:
                return dict(library)
        raise LibraryNotFoundError(
            "Library was not found.",
            details={"library_id": wanted},
        )

    def refresh_library(self, library_id: str) -> dict[str, Any]:
        self.list_libraries(refresh=True)
        self._catalog_cache.pop(str(library_id).strip(), None)
        return self.get_library(library_id)

    def get_catalog(self, library_id: str, *, refresh: bool = False) -> dict[str, Any]:
        wanted = str(library_id).strip()
        if refresh or wanted not in self._catalog_cache:
            self._catalog_cache[wanted] = build_session_catalog(
                self._library_root(wanted),
                library_id=wanted,
            )
        return copy.deepcopy(self._catalog_cache[wanted])

    def get_timeseries_window(self, library_id: str, request: dict[str, Any]) -> dict[str, Any]:
        return get_timeseries_window(self._library_root(library_id), request, library_id=library_id)

    def get_session_gps_summary(self, library_id: str, request: dict[str, Any]) -> dict[str, Any]:
        row = self._catalog_row_for_session(library_id, request)
        summary = row.get("gps_summary")
        if isinstance(summary, Mapping):
            return copy.deepcopy(dict(summary))
        return {
            "schema": "bodaqs.session_gps_summary",
            "version": 1,
            "present": False,
            "preferred_source": None,
            "sources": [],
            "session_duration_s": 0.0,
            "time_coverage_ratio": 0.0,
            "position_point_count": 0,
            "quality": "absent",
            "warnings": [],
        }

    def get_session_gps_points(self, library_id: str, request: dict[str, Any]) -> dict[str, Any]:
        session_ref = self._normalized_session_ref_request(library_id, request)
        self._catalog_row_for_session(library_id, session_ref)
        raw_max_points = request.get("max_points") if isinstance(request, Mapping) else None
        max_points = raw_max_points if isinstance(raw_max_points, int) and not isinstance(raw_max_points, bool) else None
        raw_window = request.get("window") if isinstance(request, Mapping) else None
        window = raw_window if isinstance(raw_window, Mapping) else None
        source_id = str(request.get("source_id") or request.get("gps_source_id") or "").strip() or None
        return catalog_get_session_gps_points(
            self._library_root(library_id),
            session_ref,
            library_id=library_id,
            max_points=max_points,
            window=window,
            source_id=source_id,
        )

    def load_session_note(self, library_id: str, request: dict[str, Any]) -> dict[str, Any]:
        session_ref = self._normalized_session_ref_request(library_id, request)
        self._catalog_row_for_session(library_id, session_ref)
        return load_session_note(self._library_root(library_id), session_ref)

    def save_session_note(self, library_id: str, request: dict[str, Any]) -> dict[str, Any]:
        session_ref = self._normalized_session_ref_request(library_id, request)
        self._catalog_row_for_session(library_id, session_ref)
        saved = save_session_note(self._library_root(library_id), session_ref, request)
        self._catalog_cache.pop(str(library_id).strip(), None)
        return saved

    def list_tracks(self) -> list[dict[str, Any]]:
        return list_tracks(self.libraries_root)

    def load_track(self, track_id: str) -> dict[str, Any]:
        return load_track(self.libraries_root, track_id)

    def create_track(self, payload: dict[str, Any]) -> dict[str, Any]:
        return create_track(self.libraries_root, payload)

    def update_track(
        self,
        track_id: str,
        *,
        payload: dict[str, Any],
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        return update_track(
            self.libraries_root,
            track_id,
            payload=payload,
            expected_revision=expected_revision,
        )

    def delete_track(self, track_id: str) -> dict[str, Any]:
        return delete_track(self.libraries_root, track_id)

    def list_geospatial_policies(self) -> list[dict[str, Any]]:
        return list_geospatial_policies(self.libraries_root)

    def load_geospatial_policy(self, policy_id: str) -> dict[str, Any]:
        return load_geospatial_policy(self.libraries_root, policy_id)

    def create_geospatial_policy(self, payload: dict[str, Any]) -> dict[str, Any]:
        return create_geospatial_policy(self.libraries_root, payload)

    def update_geospatial_policy(self, policy_id: str, *, payload: dict[str, Any]) -> dict[str, Any]:
        return update_geospatial_policy(self.libraries_root, policy_id, payload=payload)

    def delete_geospatial_policy(self, policy_id: str) -> dict[str, Any]:
        return delete_geospatial_policy(self.libraries_root, policy_id)

    def query_track_matches(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise InvalidRequestError("Track match query body must be a JSON object.")
        study_set = self._study_set_for_match_request(request)
        session_refs = self._session_refs_for_match_request(request, study_set=study_set)
        track_ids = self._track_ids_for_match_request(request, study_set=study_set)
        policy = self._policy_for_match_request(request)
        persist = bool(request.get("persist", False))

        matches = [
            self._build_track_match(track_id, session_ref, policy=policy, persist=persist)
            for track_id in track_ids
            for session_ref in session_refs
        ]
        return {
            "schema": "bodaqs.track_match_query",
            "version": 1,
            "match_count": len(matches),
            "matches": matches,
        }

    def compute_track_match(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise InvalidRequestError("Track match compute body must be a JSON object.")
        track_ids = self._track_ids_for_match_request(request, study_set=None)
        session_refs = self._session_refs_for_match_request(request, study_set=None)
        if len(track_ids) != 1 or len(session_refs) != 1:
            raise InvalidRequestError(
                "Track match compute requires exactly one track and one session reference.",
                details={"track_count": len(track_ids), "session_count": len(session_refs)},
            )
        policy = self._policy_for_match_request(request)
        persist = bool(request.get("persist", False))
        return self._build_track_match(track_ids[0], session_refs[0], policy=policy, persist=persist)

    def load_track_match(self, track_match_id: str) -> dict[str, Any]:
        return load_track_match(self.libraries_root, track_match_id)

    def create_trackpoint_match_query(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise InvalidRequestError("Trackpoint match query body must be a JSON object.")
        track = self.load_track(self._track_id_for_trackpoint_query(request))
        policy = self._policy_for_match_request(request)
        candidate_refs = self._session_refs_for_trackpoint_query(request)
        candidate_gps_sources = [self._gps_source_ref_for_session(ref) for ref in candidate_refs]
        return create_trackpoint_match_query_record(
            self.libraries_root,
            request,
            track=track,
            policy=policy,
            candidate_session_refs=candidate_refs,
            candidate_gps_sources=candidate_gps_sources,
        )

    def load_trackpoint_match_query(self, query_id: str) -> dict[str, Any]:
        return load_trackpoint_match_query(self.libraries_root, query_id)

    def load_trackpoint_match_query_results(
        self,
        query_id: str,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return load_trackpoint_match_query_results(
            self.libraries_root,
            query_id,
            cursor=cursor,
            limit=limit,
        )

    def cancel_trackpoint_match_query(self, query_id: str) -> dict[str, Any]:
        return cancel_trackpoint_match_query(self.libraries_root, query_id)

    def fail_trackpoint_match_query(self, query_id: str, message: str) -> dict[str, Any]:
        return fail_trackpoint_match_query(self.libraries_root, query_id, message)

    def run_trackpoint_match_query(self, query_id: str) -> dict[str, Any]:
        query = load_trackpoint_match_query(self.libraries_root, query_id)
        if query.get("status") in {"cancelled", "completed"}:
            return query

        update_trackpoint_match_query(
            self.libraries_root,
            query_id,
            {
                "status": "running",
                "processed_session_count": 0,
                "matched_session_count": 0,
                "failed_session_count": 0,
                "error": None,
            },
        )
        results: list[dict[str, Any]] = []
        processed_count = 0
        failed_count = 0
        try:
            track_id = str(query["track_ref"]["track_id"])
            policy_id = str(query.get("policy_ref", {}).get("policy_id") or DEFAULT_GEOSPATIAL_POLICY_ID)
            policy = self.load_geospatial_policy(policy_id)
            for raw_ref in query.get("candidate_sessions") or []:
                if not isinstance(raw_ref, Mapping):
                    failed_count += 1
                    continue
                latest = load_trackpoint_match_query(self.libraries_root, query_id)
                if latest.get("status") == "cancelled":
                    write_trackpoint_match_query_results(self.libraries_root, query_id, results)
                    return latest
                try:
                    match = self._build_track_match(
                        track_id,
                        raw_ref,
                        policy=policy,
                        persist=bool(query.get("persist", True)),
                    )
                    result = self._trackpoint_match_result(query, match)
                    if result is not None:
                        results.append(result)
                except LibraryApiError:
                    failed_count += 1
                processed_count += 1
                update_trackpoint_match_query(
                    self.libraries_root,
                    query_id,
                    {
                        "processed_session_count": processed_count,
                        "matched_session_count": len(results),
                        "failed_session_count": failed_count,
                    },
                )

            write_trackpoint_match_query_results(self.libraries_root, query_id, results)
            return complete_trackpoint_match_query(
                self.libraries_root,
                query_id,
                processed_count=processed_count,
                matched_count=len(results),
                failed_count=failed_count,
            )
        except Exception as exc:
            return fail_trackpoint_match_query(self.libraries_root, query_id, f"{type(exc).__name__}: {exc}")

    def list_session_filters(self) -> list[dict[str, Any]]:
        return list_session_filters(self.libraries_root)

    def load_session_filter(self, filter_id: str) -> dict[str, Any]:
        return load_session_filter(self.libraries_root, filter_id)

    def create_session_filter(self, payload: dict[str, Any]) -> dict[str, Any]:
        return create_session_filter(self.libraries_root, payload)

    def update_session_filter(
        self,
        filter_id: str,
        *,
        expected_revision: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return update_session_filter(
            self.libraries_root,
            filter_id,
            expected_revision=expected_revision,
            payload=payload,
        )

    def delete_session_filter(self, filter_id: str) -> dict[str, Any]:
        return delete_session_filter(self.libraries_root, filter_id)

    def list_study_sets(self, library_id: str | None = None) -> list[dict[str, Any]]:
        if library_id is not None:
            self.get_library(library_id)
        return list_study_sets(self.libraries_root)

    def load_study_set(self, *args: str) -> dict[str, Any]:
        study_set_id = self._study_set_id_arg(*args)
        return load_study_set(self.libraries_root, study_set_id)

    def create_study_set(self, *args: Any) -> dict[str, Any]:
        payload = self._study_set_payload_arg(*args)
        return create_study_set(self.libraries_root, payload)

    def update_study_set(
        self,
        *args: Any,
        expected_revision: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        study_set_id = self._study_set_id_arg(*args)
        return update_study_set(
            self.libraries_root,
            study_set_id,
            expected_revision=expected_revision,
            payload=payload,
        )

    def delete_study_set(self, *args: str) -> dict[str, Any]:
        study_set_id = self._study_set_id_arg(*args)
        return delete_study_set(self.libraries_root, study_set_id)

    def study_set_to_selection_snapshot(
        self,
        library_id: str,
        study_set_id: str,
        *,
        include_groupings: bool = True,
    ) -> dict[str, Any]:
        study_set = self.load_study_set(study_set_id)
        for session in study_set.get("sessions") or []:
            if isinstance(session, dict) and session.get("library_id") != library_id:
                from .errors import InvalidStudySetError

                raise InvalidStudySetError(
                    "Selection snapshot bridge only supports one-library Study Sets.",
                    details={"library_id": library_id, "session_ref": session},
                )
        return study_set_to_selection_snapshot(
            self._library_root(library_id),
            study_set,
            include_groupings=include_groupings,
        )

    def _study_set_id_arg(self, *args: str) -> str:
        if len(args) == 1:
            return str(args[0])
        if len(args) == 2:
            self.get_library(str(args[0]))
            return str(args[1])
        raise TypeError("Expected study_set_id or library_id, study_set_id")

    def _study_set_payload_arg(self, *args: Any) -> dict[str, Any]:
        if len(args) == 1:
            payload = args[0]
        elif len(args) == 2:
            self.get_library(str(args[0]))
            payload = args[1]
        else:
            raise TypeError("Expected payload or library_id, payload")
        if not isinstance(payload, dict):
            from .errors import InvalidStudySetError

            raise InvalidStudySetError("Study Set payload must be a JSON object.")
        return payload

    def _library_root(self, library_id: str) -> Path:
        return Path(str(self.get_library(library_id)["root"]))

    def _catalog_row_for_session(self, library_id: str, request: Mapping[str, Any]) -> dict[str, Any]:
        session_ref = self._normalized_session_ref_request(library_id, request)
        catalog = self.get_catalog(library_id)
        for row in catalog.get("rows") or []:
            if not isinstance(row, Mapping):
                continue
            if row.get("session_ref_id") == session_ref.get("session_ref_id"):
                return dict(row)
            if row.get("session_key") == session_ref.get("session_key"):
                return dict(row)
            if row.get("run_id") == session_ref.get("run_id") and row.get("session_id") == session_ref.get("session_id"):
                return dict(row)
        raise SessionNotFoundError(
            "Session was not found.",
            details={
                "library_id": str(library_id),
                "session_ref_id": session_ref.get("session_ref_id"),
                "session_key": session_ref.get("session_key"),
                "run_id": session_ref.get("run_id"),
                "session_id": session_ref.get("session_id"),
            },
        )

    def _normalized_session_ref_request(
        self,
        library_id: str | None,
        request: Mapping[str, Any],
    ) -> dict[str, Any]:
        raw = request.get("session_ref") if isinstance(request.get("session_ref"), Mapping) else request
        if not isinstance(raw, Mapping):
            raise InvalidRequestError("Session reference must be a JSON object.")
        ref_library_id = str(raw.get("library_id") or library_id or "").strip()
        if not ref_library_id:
            raise InvalidRequestError("Session reference missing library_id.")

        run_id = str(raw.get("run_id") or "").strip()
        session_id = str(raw.get("session_id") or "").strip()
        session_key = str(raw.get("session_key") or "").strip()
        if session_key and (not run_id or not session_id):
            try:
                parsed_run_id, parsed_session_id = parse_session_key(session_key)
            except ValueError as exc:
                raise InvalidRequestError("Session reference session_key is invalid.") from exc
            run_id = run_id or parsed_run_id
            session_id = session_id or parsed_session_id
        if not run_id or not session_id:
            raise InvalidRequestError("Session reference must include run_id/session_id or session_key.")
        expected_session_key = make_session_key(run_id, session_id)
        if session_key and session_key != expected_session_key:
            raise InvalidRequestError(
                "Session reference session_key does not match run_id/session_id.",
                details={"session_key": session_key, "expected_session_key": expected_session_key},
            )
        session_key = expected_session_key
        expected_ref_id = make_session_ref_id(ref_library_id, session_key)
        session_ref_id = str(raw.get("session_ref_id") or "").strip() or expected_ref_id
        if session_ref_id != expected_ref_id:
            raise InvalidRequestError(
                "Session reference session_ref_id does not match library_id/session_key.",
                details={"session_ref_id": session_ref_id, "expected_session_ref_id": expected_ref_id},
            )
        return {
            "library_id": ref_library_id,
            "session_ref_id": session_ref_id,
            "session_key": session_key,
            "run_id": run_id,
            "session_id": session_id,
        }

    def _study_set_for_match_request(self, request: Mapping[str, Any]) -> dict[str, Any] | None:
        study_set_id = str(request.get("study_set_id") or "").strip()
        return self.load_study_set(study_set_id) if study_set_id else None

    def _session_refs_for_match_request(
        self,
        request: Mapping[str, Any],
        *,
        study_set: Mapping[str, Any] | None,
    ) -> list[dict[str, Any]]:
        raw_sessions = request.get("sessions")
        if raw_sessions is None and isinstance(request.get("session_ref"), Mapping):
            raw_sessions = [request.get("session_ref")]
        if raw_sessions is None and any(key in request for key in ("library_id", "session_key", "run_id", "session_id")):
            raw_sessions = [request]
        if raw_sessions is None and isinstance(study_set, Mapping):
            raw_sessions = study_set.get("sessions")
        if not isinstance(raw_sessions, list) or not raw_sessions:
            raise InvalidRequestError("Track match request must include at least one session reference.")
        refs: list[dict[str, Any]] = []
        for index, raw_session in enumerate(raw_sessions):
            if not isinstance(raw_session, Mapping):
                raise InvalidRequestError(
                    "Track match session references must be objects.",
                    details={"index": index},
                )
            refs.append(self._normalized_session_ref_request(raw_session.get("library_id"), raw_session))
        return refs

    def _track_ids_for_match_request(
        self,
        request: Mapping[str, Any],
        *,
        study_set: Mapping[str, Any] | None,
    ) -> list[str]:
        raw_track_ids = request.get("track_ids")
        if raw_track_ids is None and request.get("track_id") is not None:
            raw_track_ids = [request.get("track_id")]
        if raw_track_ids is None and isinstance(study_set, Mapping):
            raw_track_ids = [
                track.get("track_id")
                for track in study_set.get("tracks") or []
                if isinstance(track, Mapping)
            ]
        if not isinstance(raw_track_ids, list) or not raw_track_ids:
            raise InvalidRequestError("Track match request must include at least one track_id.")
        track_ids = [str(track_id).strip() for track_id in raw_track_ids if str(track_id).strip()]
        if not track_ids:
            raise InvalidRequestError("Track match request must include at least one non-empty track_id.")
        return track_ids

    def _track_id_for_trackpoint_query(self, request: Mapping[str, Any]) -> str:
        track_id = str(request.get("track_id") or "").strip()
        if not track_id:
            raise InvalidRequestError("Trackpoint match query must include track_id.")
        return track_id

    def _session_refs_for_trackpoint_query(self, request: Mapping[str, Any]) -> list[dict[str, Any]]:
        scope = request.get("scope") if isinstance(request.get("scope"), Mapping) else {}
        if isinstance(scope.get("session_filter_ids"), list) and scope.get("session_filter_ids"):
            raise InvalidRequestError(
                "Trackpoint match query session_filter_ids are not supported in this first implementation slice."
            )

        raw_refs = scope.get("session_refs") if isinstance(scope, Mapping) else None
        if raw_refs is None:
            raw_refs = request.get("session_refs")
        if raw_refs is None and isinstance(request.get("sessions"), list):
            raw_refs = request.get("sessions")
        if isinstance(raw_refs, list):
            refs: list[dict[str, Any]] = []
            for index, raw_ref in enumerate(raw_refs):
                if not isinstance(raw_ref, Mapping):
                    raise InvalidRequestError(
                        "Trackpoint match query session references must be objects.",
                        details={"index": index},
                    )
                refs.append(self._normalized_session_ref_request(raw_ref.get("library_id"), raw_ref))
            return refs

        raw_library_ids = scope.get("library_ids") if isinstance(scope, Mapping) else None
        if raw_library_ids is None:
            raw_library_ids = request.get("library_ids")
        if raw_library_ids is None:
            library_ids = [str(library.get("library_id")) for library in self.list_libraries()]
        elif isinstance(raw_library_ids, list):
            library_ids = [str(item).strip() for item in raw_library_ids if str(item).strip()]
        else:
            raise InvalidRequestError("Trackpoint match query library_ids must be a list when supplied.")
        if not library_ids:
            raise InvalidRequestError("Trackpoint match query must include at least one candidate library.")

        refs = []
        for library_id in library_ids:
            catalog = self.get_catalog(library_id)
            for row in catalog.get("rows") or []:
                if not isinstance(row, Mapping):
                    continue
                refs.append(
                    self._normalized_session_ref_request(
                        library_id,
                        {
                            "library_id": library_id,
                            "session_ref_id": row.get("session_ref_id"),
                            "session_key": row.get("session_key"),
                            "run_id": row.get("run_id"),
                            "session_id": row.get("session_id"),
                        },
                    )
                )
        return refs

    def _policy_for_match_request(self, request: Mapping[str, Any]) -> dict[str, Any]:
        policy_ref = request.get("policy_ref") if isinstance(request.get("policy_ref"), Mapping) else {}
        policy_id = str(request.get("policy_id") or policy_ref.get("policy_id") or DEFAULT_GEOSPATIAL_POLICY_ID)
        return self.load_geospatial_policy(policy_id)

    def _build_track_match(
        self,
        track_id: str,
        session_ref: Mapping[str, Any],
        *,
        policy: Mapping[str, Any],
        persist: bool,
    ) -> dict[str, Any]:
        track = self.load_track(track_id)
        row = self._catalog_row_for_session(str(session_ref["library_id"]), session_ref)
        gps_summary = row.get("gps_summary") if isinstance(row.get("gps_summary"), Mapping) else {}
        gps_points = catalog_get_session_gps_points(
            self._library_root(str(session_ref["library_id"])),
            session_ref,
            library_id=str(session_ref["library_id"]),
            max_points=25_000,
        )
        match = build_session_track_match(
            track=track,
            policy=policy,
            session_ref=session_ref,
            gps_summary=gps_summary,
            gps_points=gps_points,
        )
        if persist:
            write_track_match(self.libraries_root, match)
        return match

    def _gps_source_ref_for_session(self, session_ref: Mapping[str, Any]) -> dict[str, Any]:
        try:
            row = self._catalog_row_for_session(str(session_ref["library_id"]), session_ref)
        except Exception:
            return {"session_ref_id": session_ref.get("session_ref_id"), "source_id": None, "kind": None}
        gps_summary = row.get("gps_summary") if isinstance(row.get("gps_summary"), Mapping) else {}
        return {
            "session_ref_id": session_ref.get("session_ref_id"),
            "source_id": gps_summary.get("preferred_source_id") or gps_summary.get("preferred_source"),
            "kind": gps_summary.get("preferred_source_kind"),
            "selection_method": gps_summary.get("source_selection_method"),
            "policy": gps_summary.get("gps_source_policy"),
        }

    def _trackpoint_match_result(
        self,
        query: Mapping[str, Any],
        match: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        wanted_ids = [str(item) for item in query.get("trackpoint_ids") or []]
        tolerance_m = float(query.get("tolerance_m") or 0.0)
        crossed: list[dict[str, Any]] = []
        for result in match.get("trackpoint_results") or []:
            if not isinstance(result, Mapping):
                continue
            trackpoint_id = str(result.get("trackpoint_id") or "")
            min_distance = result.get("min_distance_m")
            if (
                trackpoint_id in wanted_ids
                and bool(result.get("crossed"))
                and isinstance(min_distance, (int, float))
                and not isinstance(min_distance, bool)
                and float(min_distance) <= tolerance_m
            ):
                crossed.append(dict(result))

        matched_ids = [str(result.get("trackpoint_id")) for result in crossed]
        missing_ids = [trackpoint_id for trackpoint_id in wanted_ids if trackpoint_id not in set(matched_ids)]
        match_mode = str(query.get("match_mode") or "all")
        min_count = int(query.get("min_count") or 0)
        if match_mode == "all":
            accepted = len(missing_ids) == 0
        elif match_mode == "any":
            accepted = len(matched_ids) > 0
        elif match_mode == "min_count":
            accepted = len(matched_ids) >= min_count
        else:
            accepted = False
        if not accepted:
            return None

        qualities = {str(result.get("quality") or "") for result in crossed}
        if len(matched_ids) == len(wanted_ids) and qualities <= {"good"}:
            quality = "good"
        elif "ambiguous" in qualities:
            quality = "ambiguous"
        else:
            quality = "partial"
        return {
            "session_ref": dict(match.get("session_ref") or {}),
            "track_match_id": match.get("track_match_id"),
            "matched_trackpoint_ids": matched_ids,
            "missing_trackpoint_ids": missing_ids,
            "quality": quality,
        }
