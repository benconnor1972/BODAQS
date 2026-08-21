"""FastAPI application for the local BODAQS Library API service."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from bodaqs_analysis.library_api import LibraryAdapter
from bodaqs_analysis.library_api.errors import LibraryApiError, ReadOnlyModeError

try:
    from bodaqs_library_service_build_version import SERVICE_VERSION as _PACKAGED_SERVICE_VERSION
except Exception:
    _PACKAGED_SERVICE_VERSION = ""


SERVICE_API_VERSION = "0"
SERVICE_COMPONENT_VERSION = str(_PACKAGED_SERVICE_VERSION or "0.1.0-dev")
SERVICE_NAME = "BODAQS Library API"
WEB_APP_INDEX_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}
WEB_APP_ASSET_CACHE_HEADERS = {
    "Cache-Control": "public, max-age=31536000, immutable",
}
DEFAULT_ALLOW_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
)
LOOPBACK_ALLOW_ORIGIN_REGEX = r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?"


@dataclass(frozen=True)
class LibraryApiServiceConfig:
    """Configuration for the local Library API service."""

    libraries_root: Path
    allow_origins: tuple[str, ...] = DEFAULT_ALLOW_ORIGINS
    web_root: Path | None = None
    read_only: bool = False
    demo_welcome_enabled: bool = False


def create_app(
    libraries_root: str | Path,
    *,
    allow_origins: Sequence[str] | None = None,
    web_root: str | Path | None = None,
    read_only: bool = False,
    demo_welcome_enabled: bool = False,
) -> FastAPI:
    """Create a local-only FastAPI app backed by ``LibraryAdapter``."""

    resolved_web_root = Path(web_root).expanduser().resolve() if web_root is not None else None
    config = LibraryApiServiceConfig(
        libraries_root=Path(libraries_root).expanduser(),
        allow_origins=tuple(allow_origins or DEFAULT_ALLOW_ORIGINS),
        web_root=resolved_web_root,
        read_only=bool(read_only),
        demo_welcome_enabled=bool(demo_welcome_enabled),
    )
    app = FastAPI(
        title=SERVICE_NAME,
        version=SERVICE_API_VERSION,
        description="Local HTTP wrapper around processed BODAQS libraries.",
    )
    app.state.config = config
    app.state.adapter = LibraryAdapter(config.libraries_root, write_catalog_revision=not config.read_only)
    app.state.trackpoint_query_threads = {}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.allow_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        allow_origin_regex=LOOPBACK_ALLOW_ORIGIN_REGEX,
    )

    @app.exception_handler(LibraryApiError)
    async def library_api_error_handler(_request: Request, exc: LibraryApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_error_payload())

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "The Library API service hit an unexpected error.",
                    "details": {
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc),
                    },
                }
            },
        )

    @app.get("/api/v1/health")
    def health() -> dict[str, Any]:
        current_config = _current_config(app)
        return {
            "status": "ok",
            "service": SERVICE_NAME,
            "api_version": SERVICE_API_VERSION,
            "service_version": SERVICE_COMPONENT_VERSION,
            "libraries_root": str(current_config.libraries_root),
            "read_only": current_config.read_only,
            "web_app": _web_app_status(current_config),
        }

    @app.get("/api/v1/capabilities")
    def capabilities() -> dict[str, Any]:
        return _capabilities_response(app)

    @app.get("/api/v1/cache/diagnostics")
    def cache_diagnostics() -> dict[str, Any]:
        return _current_adapter(app).cache_diagnostics()

    @app.post("/api/v1/local/video-file-dialog")
    def select_local_video_file() -> dict[str, Any]:
        _assert_writable(app)
        return _select_local_video_file(_current_config(app).libraries_root)

    @app.get("/api/v1/workbench/bootstrap")
    def workbench_bootstrap() -> dict[str, Any]:
        return _current_adapter(app).get_workbench_bootstrap()

    @app.get("/api/v1/signal-sets")
    def get_signal_sets() -> dict[str, Any]:
        return _current_adapter(app).get_signal_sets()

    @app.post("/api/v1/config/libraries-root")
    async def set_libraries_root(request: Request) -> dict[str, Any]:
        _assert_writable(app)
        payload = await request.json()
        libraries_root = _libraries_root_payload(payload)
        next_adapter = LibraryAdapter(libraries_root, write_catalog_revision=not _current_config(app).read_only)
        libraries = next_adapter.list_libraries(refresh=True)
        app.state.config = LibraryApiServiceConfig(
            libraries_root=Path(libraries_root).expanduser(),
            allow_origins=_current_config(app).allow_origins,
            web_root=_current_config(app).web_root,
            read_only=_current_config(app).read_only,
        )
        app.state.adapter = next_adapter
        app.state.trackpoint_query_threads = {}
        return {
            "updated": True,
            "libraries_root": str(_current_config(app).libraries_root),
            "library_count": len(libraries),
            "libraries": libraries,
        }

    @app.get("/api/v1/libraries")
    def list_libraries() -> list[dict[str, Any]]:
        return _current_adapter(app).list_libraries()

    @app.get("/api/v1/libraries/{library_id}")
    def get_library(library_id: str) -> dict[str, Any]:
        return _current_adapter(app).get_library(library_id)

    @app.post("/api/v1/libraries/{library_id}/refresh")
    def refresh_library(library_id: str) -> dict[str, Any]:
        library = _current_adapter(app).refresh_library(library_id)
        return {"refreshed": True, "library": library}

    @app.post("/api/v1/libraries/{library_id}/catalog/invalidate")
    def invalidate_library_catalog(library_id: str) -> dict[str, Any]:
        return _current_adapter(app).invalidate_library_catalog(library_id)

    @app.get("/api/v1/libraries/{library_id}/catalog")
    def get_catalog(library_id: str) -> dict[str, Any]:
        return _current_adapter(app).get_catalog(library_id)

    @app.post("/api/v1/libraries/{library_id}/sessions/gps-summary")
    async def get_session_gps_summary(library_id: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        return _current_adapter(app).get_session_gps_summary(library_id, _json_object_payload(payload))

    @app.post("/api/v1/libraries/{library_id}/sessions/gps/points")
    async def get_session_gps_points(library_id: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        return _current_adapter(app).get_session_gps_points(library_id, _json_object_payload(payload))

    @app.post("/api/v1/libraries/{library_id}/sessions/note")
    async def load_session_note(library_id: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        return _current_adapter(app).load_session_note(library_id, _json_object_payload(payload))

    @app.put("/api/v1/libraries/{library_id}/sessions/note")
    async def save_session_note(library_id: str, request: Request) -> dict[str, Any]:
        _assert_writable(app)
        payload = await request.json()
        return _current_adapter(app).save_session_note(library_id, _json_object_payload(payload))

    @app.put("/api/v1/libraries/{library_id}/sessions/notes")
    async def save_session_notes(library_id: str, request: Request) -> dict[str, Any]:
        _assert_writable(app)
        payload = await request.json()
        return _current_adapter(app).save_session_notes(library_id, _json_object_payload(payload))

    @app.get("/api/v1/libraries/{library_id}/runs/{run_id}/sessions/{session_id}/videos")
    def load_session_video_attachments(library_id: str, run_id: str, session_id: str) -> dict[str, Any]:
        return _current_adapter(app).load_session_video_attachments(
            library_id,
            _session_route_ref(library_id, run_id, session_id),
        )

    @app.put("/api/v1/libraries/{library_id}/runs/{run_id}/sessions/{session_id}/videos")
    async def save_session_video_attachments(library_id: str, run_id: str, session_id: str, request: Request) -> dict[str, Any]:
        _assert_writable(app)
        payload = await request.json()
        payload = _json_object_payload(payload)
        payload.update(_session_route_ref(library_id, run_id, session_id))
        return _current_adapter(app).save_session_video_attachments(library_id, payload)

    @app.get("/api/v1/libraries/{library_id}/runs/{run_id}/sessions/{session_id}/videos/{attachment_id}/stream")
    def stream_session_video_attachment(
        library_id: str,
        run_id: str,
        session_id: str,
        attachment_id: str,
    ) -> FileResponse:
        resolved = _current_adapter(app).resolve_session_video_attachment(
            library_id,
            _session_route_ref(library_id, run_id, session_id),
            attachment_id,
        )
        attachment = resolved["attachment"]
        return FileResponse(
            resolved["path"],
            media_type=resolved["media_type"],
            filename=str(attachment.get("display_name") or attachment.get("attachment_id") or "session-video"),
        )

    @app.put("/api/v1/libraries/{library_id}/sessions/descriptions")
    async def update_session_descriptions(library_id: str, request: Request) -> dict[str, Any]:
        _assert_writable(app)
        payload = await request.json()
        return _current_adapter(app).update_session_descriptions(library_id, _json_object_payload(payload))

    @app.delete("/api/v1/libraries/{library_id}/runs/{run_id}/sessions/{session_id}")
    def delete_library_session(
        library_id: str,
        run_id: str,
        session_id: str,
        cleanup_memberships: bool = False,
    ) -> dict[str, Any]:
        _assert_writable(app)
        return _current_adapter(app).delete_session(
            library_id,
            run_id,
            session_id,
            cleanup_memberships=cleanup_memberships,
        )

    @app.get("/api/v1/tracks")
    def list_root_tracks() -> list[dict[str, Any]]:
        return _current_adapter(app).list_tracks()

    @app.post("/api/v1/tracks")
    async def create_root_track(request: Request) -> dict[str, Any]:
        _assert_writable(app)
        payload = await request.json()
        return _current_adapter(app).create_track(_track_payload(payload))

    @app.get("/api/v1/tracks/{track_id}")
    def load_root_track(track_id: str) -> dict[str, Any]:
        return _current_adapter(app).load_track(track_id)

    @app.put("/api/v1/tracks/{track_id}")
    async def update_root_track(track_id: str, request: Request) -> dict[str, Any]:
        _assert_writable(app)
        payload = await request.json()
        return _current_adapter(app).update_track(
            track_id,
            expected_revision=_expected_revision_optional(payload),
            payload=_track_payload(payload),
        )

    @app.delete("/api/v1/tracks/{track_id}")
    def delete_root_track(track_id: str) -> dict[str, Any]:
        _assert_writable(app)
        return _current_adapter(app).delete_track(track_id)

    @app.get("/api/v1/geospatial-policies")
    def list_root_geospatial_policies() -> list[dict[str, Any]]:
        return _current_adapter(app).list_geospatial_policies()

    @app.post("/api/v1/geospatial-policies")
    async def create_root_geospatial_policy(request: Request) -> dict[str, Any]:
        _assert_writable(app)
        payload = await request.json()
        return _current_adapter(app).create_geospatial_policy(_geospatial_policy_payload(payload))

    @app.get("/api/v1/geospatial-policies/{policy_id}")
    def load_root_geospatial_policy(policy_id: str) -> dict[str, Any]:
        return _current_adapter(app).load_geospatial_policy(policy_id)

    @app.put("/api/v1/geospatial-policies/{policy_id}")
    async def update_root_geospatial_policy(policy_id: str, request: Request) -> dict[str, Any]:
        _assert_writable(app)
        payload = await request.json()
        return _current_adapter(app).update_geospatial_policy(policy_id, payload=_geospatial_policy_payload(payload))

    @app.delete("/api/v1/geospatial-policies/{policy_id}")
    def delete_root_geospatial_policy(policy_id: str) -> dict[str, Any]:
        _assert_writable(app)
        return _current_adapter(app).delete_geospatial_policy(policy_id)

    @app.get("/api/v1/study-sets")
    def list_root_study_sets() -> list[dict[str, Any]]:
        return _current_adapter(app).list_study_sets()

    @app.post("/api/v1/study-sets")
    async def create_root_study_set(request: Request) -> dict[str, Any]:
        _assert_writable(app)
        payload = await request.json()
        return _current_adapter(app).create_study_set(_study_set_payload(payload))

    @app.get("/api/v1/study-sets/{study_set_id}")
    def load_root_study_set(study_set_id: str) -> dict[str, Any]:
        return _current_adapter(app).load_study_set(study_set_id)

    @app.put("/api/v1/study-sets/{study_set_id}")
    async def update_root_study_set(study_set_id: str, request: Request) -> dict[str, Any]:
        _assert_writable(app)
        payload = await request.json()
        expected_revision = _expected_revision(payload)
        return _current_adapter(app).update_study_set(
            study_set_id,
            expected_revision=expected_revision,
            payload=_study_set_payload(payload),
        )

    @app.delete("/api/v1/study-sets/{study_set_id}")
    def delete_root_study_set(study_set_id: str) -> dict[str, Any]:
        _assert_writable(app)
        return _current_adapter(app).delete_study_set(study_set_id)

    @app.get("/api/v1/session-filters")
    def list_root_session_filters() -> list[dict[str, Any]]:
        return _current_adapter(app).list_session_filters()

    @app.post("/api/v1/session-filters")
    async def create_root_session_filter(request: Request) -> dict[str, Any]:
        _assert_writable(app)
        payload = await request.json()
        return _current_adapter(app).create_session_filter(_session_filter_payload(payload))

    @app.get("/api/v1/session-filters/{filter_id}")
    def load_root_session_filter(filter_id: str) -> dict[str, Any]:
        return _current_adapter(app).load_session_filter(filter_id)

    @app.put("/api/v1/session-filters/{filter_id}")
    async def update_root_session_filter(filter_id: str, request: Request) -> dict[str, Any]:
        _assert_writable(app)
        payload = await request.json()
        return _current_adapter(app).update_session_filter(
            filter_id,
            expected_revision=_expected_revision(payload),
            payload=_session_filter_payload(payload),
        )

    @app.delete("/api/v1/session-filters/{filter_id}")
    def delete_root_session_filter(filter_id: str) -> dict[str, Any]:
        _assert_writable(app)
        return _current_adapter(app).delete_session_filter(filter_id)

    @app.get("/api/v1/bookmarks")
    def list_root_bookmarks(
        library_id: str | None = None,
        session_key: str | None = None,
        session_ref_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return _current_adapter(app).list_bookmarks(
            library_id=library_id,
            session_key=session_key,
            session_ref_id=session_ref_id,
        )

    @app.post("/api/v1/bookmarks")
    async def create_root_bookmark(request: Request) -> dict[str, Any]:
        _assert_writable(app)
        payload = await request.json()
        return _current_adapter(app).create_bookmark(_bookmark_payload(payload))

    @app.get("/api/v1/bookmarks/{bookmark_id}")
    def load_root_bookmark(bookmark_id: str) -> dict[str, Any]:
        return _current_adapter(app).load_bookmark(bookmark_id)

    @app.put("/api/v1/bookmarks/{bookmark_id}")
    async def update_root_bookmark(bookmark_id: str, request: Request) -> dict[str, Any]:
        _assert_writable(app)
        payload = await request.json()
        return _current_adapter(app).update_bookmark(
            bookmark_id,
            expected_revision=_expected_revision(payload),
            payload=_bookmark_payload(payload),
        )

    @app.delete("/api/v1/bookmarks/{bookmark_id}")
    def delete_root_bookmark(bookmark_id: str) -> dict[str, Any]:
        _assert_writable(app)
        return _current_adapter(app).delete_bookmark(bookmark_id)

    @app.get("/api/v1/analysis-views")
    def list_analysis_views() -> list[dict[str, Any]]:
        return _current_adapter(app).list_analysis_views()

    @app.post("/api/v1/analysis-views/{view_id}/adequacy")
    async def get_analysis_view_adequacy(view_id: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        return _current_adapter(app).get_analysis_view_adequacy(view_id, _json_object_payload(payload))

    @app.post("/api/v1/analysis-views/{view_id}/adequacy/cache-key/explain")
    async def explain_analysis_view_adequacy_cache_key(view_id: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        return _current_adapter(app).explain_analysis_view_adequacy_cache_key(view_id, _json_object_payload(payload))

    @app.post("/api/v1/libraries/{library_id}/timeseries/window")
    async def get_timeseries_window(library_id: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        return _current_adapter(app).get_timeseries_window(library_id, payload)

    @app.post("/api/v1/libraries/{library_id}/timeseries/multistream-window")
    async def get_multistream_timeseries_window(library_id: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        return _current_adapter(app).get_multistream_timeseries_window(library_id, payload)

    @app.post("/api/v1/libraries/{library_id}/signals/query")
    async def query_signals(library_id: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        return _current_adapter(app).query_signals(library_id, _json_object_payload(payload))

    @app.post("/api/v1/libraries/{library_id}/events/query")
    async def query_events(library_id: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        return _current_adapter(app).query_events(library_id, _json_object_payload(payload))

    @app.post("/api/v1/libraries/{library_id}/metrics/query")
    async def query_metrics(library_id: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        return _current_adapter(app).query_metrics(library_id, _json_object_payload(payload))

    @app.post("/api/v1/track-matches/query")
    async def query_track_matches(request: Request) -> dict[str, Any]:
        payload = await request.json()
        payload = _json_object_payload(payload)
        if bool(payload.get("persist", False)):
            _assert_writable(app)
        return _current_adapter(app).query_track_matches(payload)

    @app.post("/api/v1/track-matches/compute")
    async def compute_track_match(request: Request) -> dict[str, Any]:
        _assert_writable(app)
        payload = await request.json()
        return _current_adapter(app).compute_track_match(_json_object_payload(payload))

    @app.get("/api/v1/track-matches/{track_match_id}")
    def load_track_match(track_match_id: str) -> dict[str, Any]:
        return _current_adapter(app).load_track_match(track_match_id)

    @app.post("/api/v1/trackpoint-match-queries")
    async def create_trackpoint_match_query(request: Request) -> dict[str, Any]:
        _assert_writable(app)
        payload = await request.json()
        query = _current_adapter(app).create_trackpoint_match_query(_json_object_payload(payload))
        if query.get("status") in {"queued", "running"}:
            _start_trackpoint_query_worker(app, query["query_id"])
        return query

    @app.get("/api/v1/trackpoint-match-queries/{query_id}")
    def load_trackpoint_match_query(query_id: str) -> dict[str, Any]:
        return _current_adapter(app).load_trackpoint_match_query(query_id)

    @app.get("/api/v1/trackpoint-match-queries/{query_id}/results")
    def load_trackpoint_match_query_results(
        query_id: str,
        cursor: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return _current_adapter(app).load_trackpoint_match_query_results(
            query_id,
            cursor=cursor,
            limit=limit,
        )

    @app.delete("/api/v1/trackpoint-match-queries/{query_id}")
    def cancel_trackpoint_match_query(query_id: str) -> dict[str, Any]:
        _assert_writable(app)
        return _current_adapter(app).cancel_trackpoint_match_query(query_id)

    if config.web_root is not None:

        @app.get("/{request_path:path}", include_in_schema=False)
        def serve_web_app(request_path: str) -> FileResponse:
            return _web_app_response(_current_config(app), request_path)

    return app


def _web_app_status(config: LibraryApiServiceConfig) -> dict[str, Any]:
    web_root = config.web_root
    if web_root is None:
        return {
            "enabled": False,
            "demo_welcome_enabled": config.demo_welcome_enabled,
        }
    index_path = web_root / "index.html"
    return {
        "enabled": True,
        "web_root": str(web_root),
        "index_present": index_path.is_file(),
        "demo_welcome_enabled": config.demo_welcome_enabled,
    }


def _web_app_response(config: LibraryApiServiceConfig, request_path: str) -> FileResponse:
    web_root = config.web_root
    if web_root is None:
        raise HTTPException(status_code=404)
    normalized_path = request_path.strip("/")
    if normalized_path == "api" or normalized_path.startswith("api/"):
        raise HTTPException(status_code=404)

    root = web_root.resolve()
    index_path = root / "index.html"
    if not index_path.is_file():
        raise HTTPException(status_code=404, detail="Web app index.html was not found.")

    if not normalized_path:
        return _web_app_index_response(index_path)

    requested = (root / normalized_path).resolve()
    if not _path_is_within(requested, root):
        raise HTTPException(status_code=404)
    if requested.is_file():
        if normalized_path.startswith("assets/"):
            return FileResponse(requested, headers=WEB_APP_ASSET_CACHE_HEADERS)
        if requested.name == "index.html":
            return _web_app_index_response(index_path)
        return FileResponse(requested)
    if Path(normalized_path).suffix:
        raise HTTPException(status_code=404)
    return _web_app_index_response(index_path)


def _web_app_index_response(index_path: Path) -> FileResponse:
    return FileResponse(index_path, headers=WEB_APP_INDEX_CACHE_HEADERS)


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _json_object_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        from bodaqs_analysis.library_api.errors import InvalidRequestError

        raise InvalidRequestError("Request body must be a JSON object.")
    return payload


def _study_set_payload(payload: Any) -> dict[str, Any]:
    payload = _json_object_payload(payload)
    value = payload.get("study_set", payload)
    if not isinstance(value, dict):
        from bodaqs_analysis.library_api.errors import InvalidRequestError

        raise InvalidRequestError("Study Set request body must include a JSON object.")
    return value


def _track_payload(payload: Any) -> dict[str, Any]:
    payload = _json_object_payload(payload)
    value = payload.get("track", payload)
    if not isinstance(value, dict):
        from bodaqs_analysis.library_api.errors import InvalidRequestError

        raise InvalidRequestError("Track request body must include a JSON object.")
    return value


def _geospatial_policy_payload(payload: Any) -> dict[str, Any]:
    payload = _json_object_payload(payload)
    value = payload.get("geospatial_policy", payload.get("policy", payload))
    if not isinstance(value, dict):
        from bodaqs_analysis.library_api.errors import InvalidRequestError

        raise InvalidRequestError("Geospatial policy request body must include a JSON object.")
    return value


def _session_filter_payload(payload: Any) -> dict[str, Any]:
    payload = _json_object_payload(payload)
    value = payload.get("session_filter", payload.get("filter", payload))
    if not isinstance(value, dict):
        from bodaqs_analysis.library_api.errors import InvalidRequestError

        raise InvalidRequestError("Session filter request body must include a JSON object.")
    return value


def _bookmark_payload(payload: Any) -> dict[str, Any]:
    payload = _json_object_payload(payload)
    value = payload.get("bookmark", payload)
    if not isinstance(value, dict):
        from bodaqs_analysis.library_api.errors import InvalidRequestError

        raise InvalidRequestError("Bookmark request body must include a JSON object.")
    return value


def _session_route_ref(library_id: str, run_id: str, session_id: str) -> dict[str, str]:
    from bodaqs_analysis.library_api.ids import make_session_key, make_session_ref_id

    session_key = make_session_key(run_id, session_id)
    return {
        "library_id": str(library_id),
        "run_id": str(run_id),
        "session_id": str(session_id),
        "session_key": session_key,
        "session_ref_id": make_session_ref_id(library_id, session_key),
    }


def _libraries_root_payload(payload: Any) -> Path:
    payload = _json_object_payload(payload)
    value = payload.get("libraries_root")
    if not isinstance(value, str) or not value.strip():
        from bodaqs_analysis.library_api.errors import InvalidRequestError

        raise InvalidRequestError("libraries_root must be a non-empty string.")
    return Path(value).expanduser()


def _current_config(app: FastAPI) -> LibraryApiServiceConfig:
    return app.state.config


def _current_adapter(app: FastAPI) -> LibraryAdapter:
    return app.state.adapter


def _assert_writable(app: FastAPI) -> None:
    if _current_config(app).read_only:
        raise ReadOnlyModeError(
            "The Library API service is running in read-only mode.",
            details={"read_only": True},
        )


def _capabilities_response(app: FastAPI) -> dict[str, Any]:
    capabilities = _current_adapter(app).capabilities()
    if not _current_config(app).read_only:
        capabilities["read_only"] = False
        return capabilities

    capabilities = dict(capabilities)
    capabilities["read_only"] = True
    features = dict(capabilities.get("features", {}))
    for feature in (
        "write_study_sets",
        "delete_study_sets",
        "delete_sessions",
        "write_session_notes",
        "write_session_video_attachments",
        "select_local_video_files",
        "write_session_descriptions",
        "write_tracks",
        "write_geospatial_policies",
        "compute_track_matches",
        "query_trackpoint_matches",
        "cancel_trackpoint_match_queries",
        "write_filters",
        "write_bookmarks",
    ):
        features[feature] = False
    capabilities["features"] = features
    return capabilities


def _select_local_video_file(libraries_root: Path) -> dict[str, Any]:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise HTTPException(
            status_code=501,
            detail={
                "message": "Native file picker is not available in this environment.",
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
            },
        ) from exc

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askopenfilename(
            title="Select session video",
            filetypes=(
                ("Video files", "*.mp4 *.mov *.m4v *.avi *.mkv *.webm"),
                ("MP4 video", "*.mp4"),
                ("All files", "*.*"),
            ),
        )
    finally:
        root.destroy()

    if not selected:
        return {"selected": False}

    path = Path(selected).expanduser().resolve()
    workspace_relative = ""
    try:
        workspace_relative = path.relative_to(libraries_root.expanduser().resolve()).as_posix()
    except ValueError:
        workspace_relative = ""
    media_created_at_unix_s = _mp4_creation_time_unix_s(path)
    return {
        "selected": True,
        "path": str(path),
        "workspace_relative_path": workspace_relative,
        "display_name": path.stem,
        "file_name": path.name,
        "media_created_at_unix_s": media_created_at_unix_s,
        "media_created_at_utc": _unix_seconds_to_utc_iso(media_created_at_unix_s),
    }


def _mp4_creation_time_unix_s(path: Path) -> float | None:
    """Return the MP4/MOV movie-header creation time as Unix seconds if present."""

    try:
        with path.open("rb") as handle:
            return _find_mp4_creation_time_unix_s(handle, 0, path.stat().st_size)
    except OSError:
        return None


def _find_mp4_creation_time_unix_s(handle: Any, start: int, end: int, *, depth: int = 0) -> float | None:
    if depth > 4:
        return None
    pos = start
    while pos + 8 <= end:
        handle.seek(pos)
        header = handle.read(8)
        if len(header) < 8:
            return None
        box_size = int.from_bytes(header[0:4], "big")
        box_type = header[4:8]
        header_size = 8
        if box_size == 1:
            largesize = handle.read(8)
            if len(largesize) < 8:
                return None
            box_size = int.from_bytes(largesize, "big")
            header_size = 16
        elif box_size == 0:
            box_size = end - pos
        if box_size < header_size:
            return None
        box_end = min(end, pos + box_size)
        payload_start = pos + header_size
        if box_type == b"mvhd":
            return _read_mvhd_creation_time_unix_s(handle, payload_start, box_end)
        if box_type in {b"moov", b"trak", b"mdia", b"minf", b"stbl"}:
            found = _find_mp4_creation_time_unix_s(handle, payload_start, box_end, depth=depth + 1)
            if found is not None:
                return found
        pos = box_end
    return None


def _read_mvhd_creation_time_unix_s(handle: Any, start: int, end: int) -> float | None:
    handle.seek(start)
    version_flags = handle.read(4)
    if len(version_flags) < 4:
        return None
    version = version_flags[0]
    if version == 1:
        if start + 12 > end:
            return None
        value = handle.read(8)
        if len(value) < 8:
            return None
        mp4_seconds = int.from_bytes(value, "big")
    elif version == 0:
        if start + 8 > end:
            return None
        value = handle.read(4)
        if len(value) < 4:
            return None
        mp4_seconds = int.from_bytes(value, "big")
    else:
        return None
    unix_seconds = mp4_seconds - 2082844800
    if unix_seconds <= 0:
        return None
    return float(unix_seconds)


def _unix_seconds_to_utc_iso(value: float | None) -> str:
    if value is None:
        return ""
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(value, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except (OSError, OverflowError, ValueError):
        return ""


def _start_trackpoint_query_worker(app: FastAPI, query_id: str) -> None:
    threads = app.state.trackpoint_query_threads
    current = threads.get(query_id)
    if isinstance(current, threading.Thread) and current.is_alive():
        return
    libraries_root = _current_config(app).libraries_root
    worker = threading.Thread(
        target=_run_trackpoint_query_worker,
        args=(libraries_root, str(query_id)),
        daemon=True,
    )
    threads[query_id] = worker
    worker.start()


def _run_trackpoint_query_worker(libraries_root: Path, query_id: str) -> None:
    adapter = LibraryAdapter(libraries_root)
    adapter.run_trackpoint_match_query(query_id)


def _expected_revision(payload: Any) -> int:
    payload = _json_object_payload(payload)
    value = payload.get("expected_revision")
    if isinstance(value, bool):
        from bodaqs_analysis.library_api.errors import InvalidRequestError

        raise InvalidRequestError("expected_revision must be an integer.")
    try:
        return int(value)
    except Exception as exc:
        from bodaqs_analysis.library_api.errors import InvalidRequestError

        raise InvalidRequestError("expected_revision must be an integer.") from exc


def _expected_revision_optional(payload: Any) -> int | None:
    payload = _json_object_payload(payload)
    if "expected_revision" not in payload:
        return None
    return _expected_revision(payload)
