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
    adapter = LibraryAdapter(config.libraries_root)

    app = FastAPI(
        title=SERVICE_NAME,
        version=SERVICE_API_VERSION,
        description="Local HTTP wrapper around processed BODAQS libraries.",
    )
    app.state.config = config
    app.state.adapter = adapter

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
        return {
            "status": "ok",
            "service": SERVICE_NAME,
            "api_version": SERVICE_API_VERSION,
            "libraries_root": str(config.libraries_root),
        }

    @app.get("/api/v1/capabilities")
    def capabilities() -> dict[str, Any]:
        return adapter.capabilities()

    @app.get("/api/v1/libraries")
    def list_libraries() -> list[dict[str, Any]]:
        return adapter.list_libraries()

    @app.get("/api/v1/libraries/{library_id}")
    def get_library(library_id: str) -> dict[str, Any]:
        return adapter.get_library(library_id)

    @app.post("/api/v1/libraries/{library_id}/refresh")
    def refresh_library(library_id: str) -> dict[str, Any]:
        library = adapter.refresh_library(library_id)
        return {"refreshed": True, "library": library}

    @app.get("/api/v1/libraries/{library_id}/catalog")
    def get_catalog(library_id: str) -> dict[str, Any]:
        return adapter.get_catalog(library_id)

    @app.get("/api/v1/study-sets")
    def list_root_study_sets() -> list[dict[str, Any]]:
        return adapter.list_study_sets()

    @app.post("/api/v1/study-sets")
    async def create_root_study_set(request: Request) -> dict[str, Any]:
        payload = await request.json()
        return adapter.create_study_set(_study_set_payload(payload))

    @app.get("/api/v1/study-sets/{study_set_id}")
    def load_root_study_set(study_set_id: str) -> dict[str, Any]:
        return adapter.load_study_set(study_set_id)

    @app.put("/api/v1/study-sets/{study_set_id}")
    async def update_root_study_set(study_set_id: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        expected_revision = _expected_revision(payload)
        return adapter.update_study_set(
            study_set_id,
            expected_revision=expected_revision,
            payload=_study_set_payload(payload),
        )

    @app.delete("/api/v1/study-sets/{study_set_id}")
    def delete_root_study_set(study_set_id: str) -> dict[str, Any]:
        return adapter.delete_study_set(study_set_id)

    @app.post("/api/v1/libraries/{library_id}/timeseries/window")
    async def get_timeseries_window(library_id: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        return adapter.get_timeseries_window(library_id, payload)

    return app


def _study_set_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        from bodaqs_analysis.library_api.errors import InvalidRequestError

        raise InvalidRequestError("Request body must be a JSON object.")
    value = payload.get("study_set", payload)
    if not isinstance(value, dict):
        from bodaqs_analysis.library_api.errors import InvalidRequestError

        raise InvalidRequestError("Study Set request body must include a JSON object.")
    return value


def _expected_revision(payload: Any) -> int:
    if not isinstance(payload, dict):
        from bodaqs_analysis.library_api.errors import InvalidRequestError

        raise InvalidRequestError("Request body must be a JSON object.")
    value = payload.get("expected_revision")
    if isinstance(value, bool):
        from bodaqs_analysis.library_api.errors import InvalidRequestError

        raise InvalidRequestError("expected_revision must be an integer.")
    try:
        return int(value)
    except Exception as exc:
        from bodaqs_analysis.library_api.errors import InvalidRequestError

        raise InvalidRequestError("expected_revision must be an integer.") from exc
