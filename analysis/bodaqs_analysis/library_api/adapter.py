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
        return get_timeseries_window(self._library_root(library_id), request, library_id=library_id)

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
