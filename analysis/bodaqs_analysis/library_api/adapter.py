"""High-level Python facade for processed BODAQS libraries."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .catalog import build_session_catalog, discover_libraries
from .errors import LibraryNotFoundError
from .models import default_capabilities
from .selection import study_set_to_selection_snapshot
from .study_sets import (
    create_study_set,
    delete_study_set,
    list_study_sets,
    load_study_set,
    update_study_set,
)
from .timeseries import get_timeseries_window


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
        return get_timeseries_window(self._library_root(library_id), request)

    def list_study_sets(self, library_id: str) -> list[dict[str, Any]]:
        return list_study_sets(self._library_root(library_id))

    def load_study_set(self, library_id: str, study_set_id: str) -> dict[str, Any]:
        return load_study_set(self._library_root(library_id), study_set_id)

    def create_study_set(self, library_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return create_study_set(self._library_root(library_id), payload)

    def update_study_set(
        self,
        library_id: str,
        study_set_id: str,
        *,
        expected_revision: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return update_study_set(
            self._library_root(library_id),
            study_set_id,
            expected_revision=expected_revision,
            payload=payload,
        )

    def delete_study_set(self, library_id: str, study_set_id: str) -> dict[str, Any]:
        return delete_study_set(self._library_root(library_id), study_set_id)

    def study_set_to_selection_snapshot(
        self,
        library_id: str,
        study_set_id: str,
        *,
        include_groupings: bool = True,
    ) -> dict[str, Any]:
        return study_set_to_selection_snapshot(
            self._library_root(library_id),
            study_set_id,
            include_groupings=include_groupings,
        )

    def _library_root(self, library_id: str) -> Path:
        return Path(str(self.get_library(library_id)["root"]))
