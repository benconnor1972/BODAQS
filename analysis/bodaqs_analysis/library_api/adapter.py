"""High-level Python facade for processed BODAQS libraries."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping, Sequence

from bodaqs_analysis.artifacts import ArtifactStore, list_event_types, list_metric_event_types

from .analysis_views import (
    analysis_view_adequacy_policy_version,
    evaluate_analysis_view_adequacy,
    list_analysis_views,
)
from .bookmarks import create_bookmark, delete_bookmark, list_bookmarks, load_bookmark, update_bookmark
from .cache import InMemoryLruCache, PersistentJsonCache, stable_cache_digest
from .catalog import (
    build_session_catalog,
    discover_libraries,
    get_session_gps_points as catalog_get_session_gps_points,
)
from .errors import InvalidRequestError, InvalidStudySetError, LibraryApiError, LibraryNotFoundError, SessionNotFoundError
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
from .ids import derive_object_id, is_valid_object_id, make_session_key, make_session_ref_id, parse_session_key
from .models import default_capabilities
from .queries import (
    EVENT_QUERY_SCHEMA,
    METRIC_QUERY_SCHEMA,
    QUERY_VERSION,
    SIGNAL_QUERY_SCHEMA,
    query_events,
    query_metrics,
    query_signals,
)
from .selection import study_set_to_selection_snapshot
from .session_filters import (
    create_session_filter,
    delete_session_filter,
    list_session_filters,
    load_session_filter,
    update_session_filter,
)
from .session_descriptions import update_session_descriptions as write_session_descriptions
from .session_notes import load_session_note, save_session_note
from .sessions import delete_session as delete_session_artifact
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

    _ANALYSIS_ADEQUACY_CACHE_NAMESPACE = "analysis_adequacy"
    _ANALYSIS_INPUT_CACHE_NAMESPACE = "analysis_input"
    _ANALYSIS_ADEQUACY_CACHE_TTL_S = 900.0
    _ANALYSIS_INPUT_CACHE_TTL_S = 900.0
    _ANALYSIS_ADEQUACY_PERSISTENT_CACHE_TTL_S = 86400.0
    _ANALYSIS_ADEQUACY_PERSISTENT_CACHE_MAX_ENTRIES = 512
    _SERVICE_CACHE_DIR_NAME = ".bodaqs_library_api_cache"

    def __init__(self, libraries_root: str | Path) -> None:
        self.libraries_root = Path(libraries_root).expanduser()
        self._libraries_cache: list[dict[str, Any]] | None = None
        self._catalog_cache: dict[str, dict[str, Any]] = {}
        self._cache = InMemoryLruCache(max_entries=1024, default_ttl_s=900.0)
        self._persistent_cache = PersistentJsonCache(self.libraries_root / self._SERVICE_CACHE_DIR_NAME)
        self._load_persisted_analysis_adequacy_cache_entries()

    def capabilities(self) -> dict[str, Any]:
        return default_capabilities()

    def cache_diagnostics(self) -> dict[str, Any]:
        return {
            "schema": "bodaqs.library_api.cache_diagnostics",
            "version": 1,
            "cache": self._cache.stats(),
            "persistent_cache": self._persistent_cache.stats(),
        }

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
        self._invalidate_analysis_adequacy_cache()
        self._invalidate_analysis_input_cache()
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

    def query_signals(self, library_id: str, request: dict[str, Any]) -> dict[str, Any]:
        session_refs = self._query_session_refs(library_id, request)
        if session_refs is None:
            return query_signals(self._library_root(library_id), request, library_id=library_id)
        sessions: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        for session_ref in session_refs:
            response = self._cached_analysis_input_query(
                "signals",
                library_id,
                request,
                session_ref,
                lambda single_request: query_signals(
                    self._library_root(library_id),
                    single_request,
                    library_id=library_id,
                ),
            )
            sessions.extend(response.get("sessions") or [])
            warnings.extend(response.get("warnings") or [])
        return {
            "schema": SIGNAL_QUERY_SCHEMA,
            "version": QUERY_VERSION,
            "encoding": "json_arrays",
            "sessions": sessions,
            "warnings": warnings,
        }

    def query_events(self, library_id: str, request: dict[str, Any]) -> dict[str, Any]:
        return self._cached_analysis_table_query(
            "events",
            EVENT_QUERY_SCHEMA,
            "event",
            library_id,
            request,
            lambda single_request: query_events(self._library_root(library_id), single_request, library_id=library_id),
        )

    def query_metrics(self, library_id: str, request: dict[str, Any]) -> dict[str, Any]:
        return self._cached_analysis_table_query(
            "metrics",
            METRIC_QUERY_SCHEMA,
            "metric",
            library_id,
            request,
            lambda single_request: query_metrics(self._library_root(library_id), single_request, library_id=library_id),
        )

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
        self._invalidate_analysis_adequacy_cache()
        return saved

    def update_session_descriptions(self, library_id: str, request: dict[str, Any]) -> dict[str, Any]:
        session_ref = self._normalized_session_ref_request(library_id, request)
        self._catalog_row_for_session(library_id, session_ref)
        updated = write_session_descriptions(self._library_root(library_id), session_ref, request)
        self._catalog_cache.pop(str(library_id).strip(), None)
        self._invalidate_analysis_adequacy_cache()
        return updated

    def delete_session(
        self,
        library_id: str,
        run_id: str,
        session_id: str,
        *,
        cleanup_memberships: bool = False,
    ) -> dict[str, Any]:
        self._catalog_row_for_session(
            library_id,
            {
                "library_id": library_id,
                "run_id": run_id,
                "session_id": session_id,
            },
        )
        deleted = delete_session_artifact(
            self.libraries_root,
            self._library_root(library_id),
            library_id=library_id,
            run_id=run_id,
            session_id=session_id,
            cleanup_memberships=cleanup_memberships,
        )
        self._catalog_cache.pop(str(library_id).strip(), None)
        self._invalidate_analysis_adequacy_cache()
        self._invalidate_analysis_input_cache()
        return deleted

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

    def list_bookmarks(
        self,
        *,
        library_id: str | None = None,
        session_key: str | None = None,
        session_ref_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return list_bookmarks(
            self.libraries_root,
            library_id=library_id,
            session_key=session_key,
            session_ref_id=session_ref_id,
        )

    def load_bookmark(self, bookmark_id: str) -> dict[str, Any]:
        return load_bookmark(self.libraries_root, bookmark_id)

    def create_bookmark(self, payload: dict[str, Any]) -> dict[str, Any]:
        return create_bookmark(self.libraries_root, payload)

    def update_bookmark(
        self,
        bookmark_id: str,
        *,
        expected_revision: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return update_bookmark(
            self.libraries_root,
            bookmark_id,
            expected_revision=expected_revision,
            payload=payload,
        )

    def delete_bookmark(self, bookmark_id: str) -> dict[str, Any]:
        return delete_bookmark(self.libraries_root, bookmark_id)

    def list_analysis_views(self) -> list[dict[str, Any]]:
        return list_analysis_views()

    def get_analysis_view_adequacy(self, view_id: str, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise InvalidRequestError("Analysis adequacy request body must be a JSON object.")
        study_set = self._study_set_for_analysis_request(request)
        session_refs = self._session_refs_for_match_request(request, study_set=study_set)
        session_rows = [self._catalog_row_for_session(str(session["library_id"]), session) for session in session_refs]
        scope = self._analysis_scope_payload(request, study_set=study_set, session_refs=session_refs)
        include_cache_status = bool(request.get("include_cache_status"))
        dependencies = self._analysis_adequacy_cache_dependency_payload(
            view_id,
            request=request,
            study_set=study_set,
            session_refs=session_refs,
            session_rows=session_rows,
        )
        cache_key = stable_cache_digest(dependencies)
        cached = self._cache.get(self._ANALYSIS_ADEQUACY_CACHE_NAMESPACE, cache_key)
        if isinstance(cached, dict):
            return self._analysis_adequacy_response_with_cache_status(
                cached,
                source="memory",
                cache_key=cache_key,
                include=include_cache_status,
            )

        persisted = self._persistent_cache.get(self._ANALYSIS_ADEQUACY_CACHE_NAMESPACE, cache_key)
        if persisted is not None and isinstance(persisted.value, dict):
            self._cache.set(
                self._ANALYSIS_ADEQUACY_CACHE_NAMESPACE,
                cache_key,
                persisted.value,
                ttl_s=self._memory_ttl_for_persisted_record(persisted.remaining_ttl_s()),
            )
            return self._analysis_adequacy_response_with_cache_status(
                persisted.value,
                source="persistent",
                cache_key=cache_key,
                include=include_cache_status,
            )

        adequacy = evaluate_analysis_view_adequacy(
            view_id,
            scope=scope,
            session_rows=session_rows,
        )
        self._cache.set(
            self._ANALYSIS_ADEQUACY_CACHE_NAMESPACE,
            cache_key,
            adequacy,
            ttl_s=self._ANALYSIS_ADEQUACY_CACHE_TTL_S,
        )
        self._persistent_cache.set(
            self._ANALYSIS_ADEQUACY_CACHE_NAMESPACE,
            cache_key,
            adequacy,
            ttl_s=self._ANALYSIS_ADEQUACY_PERSISTENT_CACHE_TTL_S,
            metadata=self._analysis_adequacy_persistent_cache_metadata(dependencies),
        )
        self._prune_persisted_analysis_adequacy_cache()
        return self._analysis_adequacy_response_with_cache_status(
            adequacy,
            source="computed",
            cache_key=cache_key,
            include=include_cache_status,
        )

    def explain_analysis_view_adequacy_cache_key(self, view_id: str, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise InvalidRequestError("Analysis adequacy request body must be a JSON object.")
        study_set = self._study_set_for_analysis_request(request)
        session_refs = self._session_refs_for_match_request(request, study_set=study_set)
        session_rows = [self._catalog_row_for_session(str(session["library_id"]), session) for session in session_refs]
        dependencies = self._analysis_adequacy_cache_dependency_payload(
            view_id,
            request=request,
            study_set=study_set,
            session_refs=session_refs,
            session_rows=session_rows,
        )
        cache_key = stable_cache_digest(dependencies)
        memory_cached = self._cache.has(self._ANALYSIS_ADEQUACY_CACHE_NAMESPACE, cache_key)
        persistent_cached = self._persistent_cache.has(self._ANALYSIS_ADEQUACY_CACHE_NAMESPACE, cache_key)
        return {
            "schema": "bodaqs.library_api.analysis_adequacy_cache_key_explain",
            "version": 1,
            "namespace": self._ANALYSIS_ADEQUACY_CACHE_NAMESPACE,
            "cache_key": cache_key,
            "cache_key_prefix": cache_key[:12],
            "cached": memory_cached or persistent_cached,
            "memory_cached": memory_cached,
            "persistent_cached": persistent_cached,
            "dependencies": dependencies,
        }

    def warm_analysis_adequacy_for_study_set(
        self,
        study_set: Mapping[str, Any],
        *,
        view_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(study_set, Mapping):
            raise InvalidStudySetError("Study Set payload must be a JSON object.")

        study_set_id = str(study_set.get("study_set_id") or "").strip()
        candidate_view_ids = (
            [str(view_id).strip() for view_id in view_ids if str(view_id).strip()]
            if view_ids is not None
            else [str(view.get("view_id")) for view in self.list_analysis_views() if view.get("view_id")]
        )
        warmed: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for view_id in candidate_view_ids:
            try:
                adequacy = self.get_analysis_view_adequacy(
                    view_id,
                    {
                        "study_set_id": study_set_id,
                        "study_set": dict(study_set),
                    },
                )
                warmed.append(
                    {
                        "view_id": view_id,
                        "status": adequacy.get("status"),
                        "usable_session_count": adequacy.get("usable_session_count"),
                        "blocked_session_count": adequacy.get("blocked_session_count"),
                    }
                )
            except LibraryApiError as exc:
                errors.append(
                    {
                        "view_id": view_id,
                        "code": exc.code,
                        "message": exc.message,
                    }
                )
            except Exception as exc:
                errors.append(
                    {
                        "view_id": view_id,
                        "code": "internal_error",
                        "message": str(exc),
                    }
                )

        return {
            "schema": "bodaqs.library_api.analysis_adequacy_warmup",
            "version": 1,
            "study_set_id": study_set_id,
            "view_count": len(candidate_view_ids),
            "warmed_count": len(warmed),
            "error_count": len(errors),
            "warmed": warmed,
            "errors": errors,
        }

    def list_study_sets(self, library_id: str | None = None) -> list[dict[str, Any]]:
        if library_id is not None:
            self.get_library(library_id)
        return list_study_sets(self.libraries_root)

    def load_study_set(self, *args: str) -> dict[str, Any]:
        study_set_id = self._study_set_id_arg(*args)
        return load_study_set(self.libraries_root, study_set_id)

    def resolve_study_set_id(self, study_set_ref: str, *, library_id: str | None = None) -> str:
        text = str(study_set_ref or "").strip()
        if not text:
            raise InvalidStudySetError("Study Set id is required.", details={"study_set_id": text})

        rows = self.list_study_sets(library_id=library_id)
        available_ids = [
            str(row.get("study_set_id"))
            for row in rows
            if isinstance(row, Mapping) and row.get("study_set_id")
        ]
        by_id = {study_set_id: study_set_id for study_set_id in available_ids}
        if text in by_id:
            return text

        def _unique(matches: list[str], *, kind: str) -> str | None:
            uniq = sorted(set(matches))
            if len(uniq) == 1:
                return uniq[0]
            if len(uniq) > 1:
                raise InvalidStudySetError(
                    "Study Set reference is ambiguous.",
                    details={
                        "study_set_ref": text,
                        "match_kind": kind,
                        "matches": uniq,
                    },
                )
            return None

        exact_display = _unique(
            [
                str(row.get("study_set_id"))
                for row in rows
                if isinstance(row, Mapping)
                and row.get("study_set_id")
                and str(row.get("display_name") or "").strip() == text
            ],
            kind="display_name",
        )
        if exact_display:
            return exact_display

        folded = text.casefold()
        folded_match = _unique(
            [
                str(row.get("study_set_id"))
                for row in rows
                if isinstance(row, Mapping)
                and row.get("study_set_id")
                and (
                    str(row.get("study_set_id")).casefold() == folded
                    or str(row.get("display_name") or "").strip().casefold() == folded
                )
            ],
            kind="case_insensitive",
        )
        if folded_match:
            return folded_match

        candidate_id = derive_object_id(text, fallback="study-set")
        if candidate_id in by_id:
            return candidate_id

        if is_valid_object_id(text):
            return text

        raise InvalidStudySetError(
            "Study Set id is not filename-safe and did not match a saved Study Set display name.",
            details={
                "study_set_ref": text,
                "candidate_id": candidate_id,
                "available_study_set_ids": sorted(available_ids),
            },
        )

    def create_study_set(self, *args: Any) -> dict[str, Any]:
        payload = self._study_set_payload_arg(*args)
        created = create_study_set(self.libraries_root, payload)
        self._invalidate_analysis_adequacy_cache()
        self.warm_analysis_adequacy_for_study_set(created)
        return created

    def update_study_set(
        self,
        *args: Any,
        expected_revision: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        study_set_id = self._study_set_id_arg(*args)
        updated = update_study_set(
            self.libraries_root,
            study_set_id,
            expected_revision=expected_revision,
            payload=payload,
        )
        self._invalidate_analysis_adequacy_cache()
        self.warm_analysis_adequacy_for_study_set(updated)
        return updated

    def delete_study_set(self, *args: str) -> dict[str, Any]:
        study_set_id = self._study_set_id_arg(*args)
        deleted = delete_study_set(self.libraries_root, study_set_id)
        self._invalidate_analysis_adequacy_cache()
        return deleted

    def study_set_to_selection_snapshot(
        self,
        library_id: str,
        study_set_id: str,
        *,
        include_groupings: bool = True,
    ) -> dict[str, Any]:
        study_set_id = self.resolve_study_set_id(study_set_id, library_id=library_id)
        study_set = self.load_study_set(study_set_id)
        for session in study_set.get("sessions") or []:
            if isinstance(session, dict) and session.get("library_id") != library_id:
                raise InvalidStudySetError(
                    "Selection snapshot bridge only supports one-library Study Sets.",
                    details={"library_id": library_id, "session_ref": session},
                )
        return study_set_to_selection_snapshot(
            self._library_root(library_id),
            study_set,
            include_groupings=include_groupings,
        )

    def _cached_analysis_table_query(
        self,
        kind: str,
        schema: str,
        row_kind: str,
        library_id: str,
        request: Mapping[str, Any],
        query_fn: Any,
    ) -> dict[str, Any]:
        session_refs = self._query_session_refs(library_id, request)
        if session_refs is None:
            return query_fn(request)
        rows: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        for session_ref in session_refs:
            response = self._cached_analysis_input_query(kind, library_id, request, session_ref, query_fn)
            rows.extend(response.get("rows") or [])
            warnings.extend(response.get("warnings") or [])
        return {
            "schema": schema,
            "version": QUERY_VERSION,
            "row_kind": row_kind,
            "row_count": len(rows),
            "rows": rows,
            "warnings": warnings,
        }

    def _cached_analysis_input_query(
        self,
        kind: str,
        library_id: str,
        request: Mapping[str, Any],
        session_ref: Mapping[str, Any],
        query_fn: Any,
    ) -> dict[str, Any]:
        single_request = self._single_session_query_request(request, session_ref)
        cache_key = self._analysis_input_cache_key(kind, library_id, single_request, session_ref)
        cached = self._cache.get(self._ANALYSIS_INPUT_CACHE_NAMESPACE, cache_key)
        if isinstance(cached, dict):
            return cached
        response = query_fn(single_request)
        self._cache.set(
            self._ANALYSIS_INPUT_CACHE_NAMESPACE,
            cache_key,
            response,
            ttl_s=self._ANALYSIS_INPUT_CACHE_TTL_S,
        )
        return response

    def _query_session_refs(self, library_id: str, request: Mapping[str, Any]) -> list[dict[str, Any]] | None:
        if not isinstance(request, Mapping):
            return None
        raw_sessions = request.get("sessions")
        if not isinstance(raw_sessions, list) or not raw_sessions:
            return None
        refs: list[dict[str, Any]] = []
        for raw_session in raw_sessions:
            if not isinstance(raw_session, Mapping):
                return None
            refs.append(self._normalized_session_ref_request(library_id, raw_session))
        return refs

    @staticmethod
    def _single_session_query_request(request: Mapping[str, Any], session_ref: Mapping[str, Any]) -> dict[str, Any]:
        single_request = dict(request)
        single_request["sessions"] = [dict(session_ref)]
        return single_request

    def _analysis_input_cache_key(
        self,
        kind: str,
        library_id: str,
        request: Mapping[str, Any],
        session_ref: Mapping[str, Any],
    ) -> str:
        return stable_cache_digest(
            {
                "cache_schema": "bodaqs.analysis_input_cache_key",
                "cache_version": 1,
                "kind": str(kind),
                "library_id": str(library_id),
                "session": self._session_ref_cache_dependency(session_ref),
                "request": self._analysis_input_request_dependency(kind, request),
                "artifacts": self._analysis_input_artifact_dependency(kind, library_id, session_ref, request),
            }
        )

    @staticmethod
    def _analysis_input_request_dependency(kind: str, request: Mapping[str, Any]) -> dict[str, Any]:
        if kind == "signals":
            return {"signals": copy.deepcopy(list(request.get("signals") or []))}
        return {"sets": LibraryAdapter._requested_query_sets(request)}

    def _analysis_input_artifact_dependency(
        self,
        kind: str,
        library_id: str,
        session_ref: Mapping[str, Any],
        request: Mapping[str, Any],
    ) -> dict[str, Any]:
        library_root = self._library_root(library_id)
        store = ArtifactStore(library_root)
        run_id = str(session_ref.get("run_id") or "")
        session_id = str(session_ref.get("session_id") or "")
        if kind == "signals":
            return {
                "files": [
                    self._file_fingerprint(store.path_session_meta(run_id, session_id), root=library_root),
                    self._file_fingerprint(store.path_session_df(run_id, session_id), root=library_root),
                ]
            }

        requested_sets = self._requested_query_sets(request)
        if kind == "events":
            set_ids = requested_sets if requested_sets is not None else list_event_types(store, run_id, session_id)
            return {
                "sets": [
                    {
                        "set_id": set_id,
                        "file": self._file_fingerprint(store.path_events_df(run_id, session_id, set_id), root=library_root),
                    }
                    for set_id in sorted(set_ids)
                ]
            }
        if kind == "metrics":
            set_ids = requested_sets if requested_sets is not None else list_metric_event_types(store, run_id, session_id)
            return {
                "sets": [
                    {
                        "set_id": set_id,
                        "file": self._file_fingerprint(store.path_metrics_df(run_id, session_id, set_id), root=library_root),
                    }
                    for set_id in sorted(set_ids)
                ]
            }
        return {}

    @staticmethod
    def _requested_query_sets(request: Mapping[str, Any]) -> list[str] | None:
        value = request.get("event_types")
        if value is None:
            value = request.get("schema_ids")
        if value is None:
            value = request.get("sets")
        if value is None:
            return None
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
            return sorted({str(item).strip() for item in value if str(item).strip()})
        return []

    @staticmethod
    def _file_fingerprint(path: Path, *, root: Path) -> dict[str, Any]:
        try:
            relative_path = str(path.relative_to(root))
        except ValueError:
            relative_path = str(path)
        try:
            stat = path.stat()
        except OSError:
            return {
                "path": relative_path,
                "exists": False,
            }
        return {
            "path": relative_path,
            "exists": True,
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
        }

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

    def _study_set_for_analysis_request(self, request: Mapping[str, Any]) -> dict[str, Any] | None:
        study_set = request.get("study_set")
        if isinstance(study_set, Mapping):
            return dict(study_set)
        return self._study_set_for_match_request(request)

    def _analysis_scope_payload(
        self,
        request: Mapping[str, Any],
        *,
        study_set: Mapping[str, Any] | None,
        session_refs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if isinstance(study_set, Mapping):
            return {
                "kind": "study_set",
                "study_set_id": str(study_set.get("study_set_id") or request.get("study_set_id") or ""),
                "display_name": str(study_set.get("display_name") or ""),
                "session_count": len(session_refs),
            }
        return {
            "kind": "session_refs",
            "session_count": len(session_refs),
        }

    def _analysis_adequacy_cache_key(
        self,
        view_id: str,
        *,
        request: Mapping[str, Any],
        study_set: Mapping[str, Any] | None,
        session_refs: list[dict[str, Any]],
        session_rows: list[Mapping[str, Any]],
    ) -> str:
        return stable_cache_digest(
            self._analysis_adequacy_cache_dependency_payload(
                view_id,
                request=request,
                study_set=study_set,
                session_refs=session_refs,
                session_rows=session_rows,
            )
        )

    def _load_persisted_analysis_adequacy_cache_entries(self) -> int:
        self._prune_persisted_analysis_adequacy_cache()
        loaded = 0
        for record in self._persistent_cache.iter_records(self._ANALYSIS_ADEQUACY_CACHE_NAMESPACE):
            if not isinstance(record.value, dict):
                continue
            self._cache.set(
                self._ANALYSIS_ADEQUACY_CACHE_NAMESPACE,
                record.key,
                record.value,
                ttl_s=self._memory_ttl_for_persisted_record(record.remaining_ttl_s()),
            )
            loaded += 1
        return loaded

    def _prune_persisted_analysis_adequacy_cache(self) -> dict[str, int]:
        return self._persistent_cache.prune_namespace(
            self._ANALYSIS_ADEQUACY_CACHE_NAMESPACE,
            max_entries=self._ANALYSIS_ADEQUACY_PERSISTENT_CACHE_MAX_ENTRIES,
        )

    def _analysis_adequacy_response_with_cache_status(
        self,
        adequacy: Mapping[str, Any],
        *,
        source: str,
        cache_key: str,
        include: bool,
    ) -> dict[str, Any]:
        response = copy.deepcopy(dict(adequacy))
        if include:
            response["cache_status"] = {
                "source": source,
                "namespace": self._ANALYSIS_ADEQUACY_CACHE_NAMESPACE,
                "cache_key_prefix": cache_key[:12],
            }
        return response

    def _analysis_adequacy_persistent_cache_metadata(self, dependencies: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "cache_schema": dependencies.get("cache_schema"),
            "cache_version": dependencies.get("cache_version"),
            "view_id": dependencies.get("view_id"),
            "policy_version": dependencies.get("policy_version"),
            "persistent_ttl_s": self._ANALYSIS_ADEQUACY_PERSISTENT_CACHE_TTL_S,
            "persistent_max_entries": self._ANALYSIS_ADEQUACY_PERSISTENT_CACHE_MAX_ENTRIES,
        }

    def _memory_ttl_for_persisted_record(self, remaining_ttl_s: float | None) -> float | None:
        if remaining_ttl_s is None:
            return self._ANALYSIS_ADEQUACY_CACHE_TTL_S
        return min(self._ANALYSIS_ADEQUACY_CACHE_TTL_S, max(0.0, remaining_ttl_s))

    def _analysis_adequacy_cache_dependency_payload(
        self,
        view_id: str,
        *,
        request: Mapping[str, Any],
        study_set: Mapping[str, Any] | None,
        session_refs: list[dict[str, Any]],
        session_rows: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        return {
            "cache_schema": "bodaqs.analysis_adequacy_cache_key",
            "cache_version": 1,
            "view_id": str(view_id or "").strip(),
            "policy_version": analysis_view_adequacy_policy_version(view_id),
            "scope": self._analysis_scope_cache_dependency(
                request,
                study_set=study_set,
                session_refs=session_refs,
            ),
            "sessions": [self._analysis_session_cache_dependency(row) for row in session_rows],
        }

    def _analysis_scope_cache_dependency(
        self,
        request: Mapping[str, Any],
        *,
        study_set: Mapping[str, Any] | None,
        session_refs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if isinstance(study_set, Mapping):
            return {
                "kind": "study_set",
                "request_study_set_id": str(request.get("study_set_id") or ""),
                "study_set_id": str(study_set.get("study_set_id") or ""),
                "revision": study_set.get("revision"),
                "display_name": str(study_set.get("display_name") or ""),
                "sessions": [self._session_ref_cache_dependency(ref) for ref in session_refs],
                "groupings": self._study_set_grouping_cache_dependency(study_set),
                "track_ids": self._study_set_track_cache_dependency(study_set),
            }
        return {
            "kind": "session_refs",
            "sessions": [self._session_ref_cache_dependency(ref) for ref in session_refs],
        }

    @staticmethod
    def _session_ref_cache_dependency(session_ref: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "library_id": str(session_ref.get("library_id") or ""),
            "session_ref_id": str(session_ref.get("session_ref_id") or ""),
            "session_key": str(session_ref.get("session_key") or ""),
            "run_id": str(session_ref.get("run_id") or ""),
            "session_id": str(session_ref.get("session_id") or ""),
        }

    @staticmethod
    def _study_set_grouping_cache_dependency(study_set: Mapping[str, Any]) -> list[dict[str, Any]]:
        groupings = study_set.get("groupings")
        if not isinstance(groupings, list):
            return []
        out: list[dict[str, Any]] = []
        for grouping in groupings:
            if not isinstance(grouping, Mapping):
                continue
            raw_refs = grouping.get("session_refs")
            refs = [str(item) for item in raw_refs] if isinstance(raw_refs, list) else []
            out.append(
                {
                    "grouping_id": str(grouping.get("grouping_id") or ""),
                    "display_name": str(grouping.get("display_name") or ""),
                    "session_refs": refs,
                }
            )
        return out

    @staticmethod
    def _study_set_track_cache_dependency(study_set: Mapping[str, Any]) -> list[str]:
        raw_tracks = study_set.get("tracks")
        if isinstance(raw_tracks, list):
            track_ids: list[str] = []
            for track in raw_tracks:
                track_id = track.get("track_id") if isinstance(track, Mapping) else track
                if str(track_id).strip():
                    track_ids.append(str(track_id))
            return track_ids
        raw_track_ids = study_set.get("track_ids")
        if isinstance(raw_track_ids, list):
            return [str(track_id) for track_id in raw_track_ids if str(track_id).strip()]
        return []

    @staticmethod
    def _analysis_session_cache_dependency(row: Mapping[str, Any]) -> dict[str, Any]:
        gps_summary = row.get("gps_summary") if isinstance(row.get("gps_summary"), Mapping) else {}
        return {
            "schema": row.get("schema"),
            "version": row.get("version"),
            "library_id": row.get("library_id"),
            "session_ref_id": row.get("session_ref_id"),
            "session_key": row.get("session_key"),
            "run_id": row.get("run_id"),
            "session_id": row.get("session_id"),
            "display": row.get("display") if isinstance(row.get("display"), Mapping) else {},
            "available_signals": sorted(
                [
                    LibraryAdapter._signal_cache_dependency(signal)
                    for signal in row.get("available_signals") or []
                    if isinstance(signal, Mapping)
                ],
                key=lambda signal: (
                    str(signal.get("end") or ""),
                    str(signal.get("domain") or ""),
                    str(signal.get("quantity") or ""),
                    str(signal.get("unit") or ""),
                    str(signal.get("motion_source_id") or ""),
                    str(signal.get("column") or ""),
                ),
            ),
            "event_summary": row.get("event_summary") if isinstance(row.get("event_summary"), Mapping) else {},
            "metric_summary": row.get("metric_summary") if isinstance(row.get("metric_summary"), Mapping) else {},
            "gps_summary": {
                "present": bool(gps_summary.get("present")),
                "preferred_source": gps_summary.get("preferred_source") or gps_summary.get("preferred_source_id"),
                "quality": gps_summary.get("quality"),
                "position_point_count": gps_summary.get("position_point_count"),
                "time_coverage_ratio": gps_summary.get("time_coverage_ratio"),
            },
        }

    @staticmethod
    def _signal_cache_dependency(signal: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "signal_id": signal.get("signal_id"),
            "column": signal.get("column"),
            "display_name": signal.get("display_name"),
            "end": signal.get("end"),
            "domain": signal.get("domain"),
            "quantity": signal.get("quantity"),
            "unit": signal.get("unit"),
            "processing_role": signal.get("processing_role"),
            "kind": signal.get("kind"),
            "motion_source_id": signal.get("motion_source_id"),
            "origin": signal.get("origin"),
        }

    def _invalidate_analysis_adequacy_cache(self) -> None:
        self._cache.invalidate_namespace(self._ANALYSIS_ADEQUACY_CACHE_NAMESPACE)
        self._persistent_cache.invalidate_namespace(self._ANALYSIS_ADEQUACY_CACHE_NAMESPACE)

    def _invalidate_analysis_input_cache(self) -> None:
        self._cache.invalidate_namespace(self._ANALYSIS_INPUT_CACHE_NAMESPACE)

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
