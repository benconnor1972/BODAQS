"""FastAPI application for the local BODAQS Library API service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from bodaqs_analysis.library_api import LibraryAdapter
from bodaqs_analysis.library_api.errors import LibraryApiError


SERVICE_API_VERSION = "0"
SERVICE_NAME = "BODAQS Library API"
DEFAULT_ALLOW_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


@dataclass(frozen=True)
class LibraryApiServiceConfig:
    """Configuration for the local Library API service."""

    libraries_root: Path
    allow_origins: tuple[str, ...] = DEFAULT_ALLOW_ORIGINS


def create_app(
    libraries_root: str | Path,
    *,
    allow_origins: Sequence[str] | None = None,
) -> FastAPI:
    """Create a local-only FastAPI app backed by ``LibraryAdapter``."""

    config = LibraryApiServiceConfig(
        libraries_root=Path(libraries_root).expanduser(),
        allow_origins=tuple(allow_origins or DEFAULT_ALLOW_ORIGINS),
    )
    app = FastAPI(
        title=SERVICE_NAME,
        version=SERVICE_API_VERSION,
        description="Local HTTP wrapper around processed BODAQS libraries.",
    )
    app.state.config = config
    app.state.adapter = LibraryAdapter(config.libraries_root)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.allow_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.exception_handler(LibraryApiError)
    async def library_api_error_handler(_request: Request, exc: LibraryApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_error_payload())

    @app.get("/api/v1/health")
    def health() -> dict[str, Any]:
        current_config = _current_config(app)
        return {
            "status": "ok",
            "service": SERVICE_NAME,
            "api_version": SERVICE_API_VERSION,
            "libraries_root": str(current_config.libraries_root),
        }

    @app.get("/api/v1/capabilities")
    def capabilities() -> dict[str, Any]:
        return _current_adapter(app).capabilities()

    @app.post("/api/v1/config/libraries-root")
    async def set_libraries_root(request: Request) -> dict[str, Any]:
        payload = await request.json()
        libraries_root = _libraries_root_payload(payload)
        next_adapter = LibraryAdapter(libraries_root)
        libraries = next_adapter.list_libraries(refresh=True)
        app.state.config = LibraryApiServiceConfig(
            libraries_root=Path(libraries_root).expanduser(),
            allow_origins=_current_config(app).allow_origins,
        )
        app.state.adapter = next_adapter
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

    @app.get("/api/v1/tracks")
    def list_root_tracks() -> list[dict[str, Any]]:
        return _current_adapter(app).list_tracks()

    @app.post("/api/v1/tracks")
    async def create_root_track(request: Request) -> dict[str, Any]:
        payload = await request.json()
        return _current_adapter(app).create_track(_track_payload(payload))

    @app.get("/api/v1/tracks/{track_id}")
    def load_root_track(track_id: str) -> dict[str, Any]:
        return _current_adapter(app).load_track(track_id)

    @app.put("/api/v1/tracks/{track_id}")
    async def update_root_track(track_id: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        return _current_adapter(app).update_track(
            track_id,
            expected_revision=_expected_revision_optional(payload),
            payload=_track_payload(payload),
        )

    @app.delete("/api/v1/tracks/{track_id}")
    def delete_root_track(track_id: str) -> dict[str, Any]:
        return _current_adapter(app).delete_track(track_id)

    @app.get("/api/v1/geospatial-policies")
    def list_root_geospatial_policies() -> list[dict[str, Any]]:
        return _current_adapter(app).list_geospatial_policies()

    @app.post("/api/v1/geospatial-policies")
    async def create_root_geospatial_policy(request: Request) -> dict[str, Any]:
        payload = await request.json()
        return _current_adapter(app).create_geospatial_policy(_geospatial_policy_payload(payload))

    @app.get("/api/v1/geospatial-policies/{policy_id}")
    def load_root_geospatial_policy(policy_id: str) -> dict[str, Any]:
        return _current_adapter(app).load_geospatial_policy(policy_id)

    @app.put("/api/v1/geospatial-policies/{policy_id}")
    async def update_root_geospatial_policy(policy_id: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        return _current_adapter(app).update_geospatial_policy(policy_id, payload=_geospatial_policy_payload(payload))

    @app.delete("/api/v1/geospatial-policies/{policy_id}")
    def delete_root_geospatial_policy(policy_id: str) -> dict[str, Any]:
        return _current_adapter(app).delete_geospatial_policy(policy_id)

    @app.get("/api/v1/study-sets")
    def list_root_study_sets() -> list[dict[str, Any]]:
        return _current_adapter(app).list_study_sets()

    @app.post("/api/v1/study-sets")
    async def create_root_study_set(request: Request) -> dict[str, Any]:
        payload = await request.json()
        return _current_adapter(app).create_study_set(_study_set_payload(payload))

    @app.get("/api/v1/study-sets/{study_set_id}")
    def load_root_study_set(study_set_id: str) -> dict[str, Any]:
        return _current_adapter(app).load_study_set(study_set_id)

    @app.put("/api/v1/study-sets/{study_set_id}")
    async def update_root_study_set(study_set_id: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        expected_revision = _expected_revision(payload)
        return _current_adapter(app).update_study_set(
            study_set_id,
            expected_revision=expected_revision,
            payload=_study_set_payload(payload),
        )

    @app.delete("/api/v1/study-sets/{study_set_id}")
    def delete_root_study_set(study_set_id: str) -> dict[str, Any]:
        return _current_adapter(app).delete_study_set(study_set_id)

    @app.post("/api/v1/libraries/{library_id}/timeseries/window")
    async def get_timeseries_window(library_id: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        return _current_adapter(app).get_timeseries_window(library_id, payload)

    @app.post("/api/v1/track-matches/query")
    async def query_track_matches(request: Request) -> dict[str, Any]:
        payload = await request.json()
        return _current_adapter(app).query_track_matches(_json_object_payload(payload))

    @app.post("/api/v1/track-matches/compute")
    async def compute_track_match(request: Request) -> dict[str, Any]:
        payload = await request.json()
        return _current_adapter(app).compute_track_match(_json_object_payload(payload))

    @app.get("/api/v1/track-matches/{track_match_id}")
    def load_track_match(track_match_id: str) -> dict[str, Any]:
        return _current_adapter(app).load_track_match(track_match_id)

    return app


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
