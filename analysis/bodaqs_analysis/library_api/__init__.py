"""Python adapter foundation for the BODAQS Library API."""

from .adapter import LibraryAdapter
from .catalog import (
    SESSION_CATALOG_ROW_SCHEMA,
    SESSION_CATALOG_ROW_VERSION,
    SESSION_CATALOG_SCHEMA,
    SESSION_CATALOG_VERSION,
    build_session_catalog,
    discover_libraries,
)
from .errors import (
    CapabilityUnavailableError,
    InvalidRequestError,
    InvalidStudySetError,
    LibraryApiError,
    LibraryNotFoundError,
    RevisionConflictError,
    SessionNotFoundError,
    SignalNotFoundError,
    StudySetNotFoundError,
    TimeseriesUnavailableError,
)
from .fixtures import FIXTURE_SCHEMA, FIXTURE_VERSION, export_library_fixture
from .ids import (
    derive_object_id,
    is_valid_object_id,
    make_session_ref_id,
    make_session_key,
    make_unique_object_id,
    parse_session_key,
)
from .selection import (
    SELECTION_BRIDGE_SCHEMA,
    SELECTION_BRIDGE_VERSION,
    study_set_to_selection_snapshot,
)
from .study_sets import (
    STUDY_SET_SCHEMA,
    STUDY_SET_VERSION,
    create_study_set,
    delete_study_set,
    list_study_sets,
    load_study_set,
    update_study_set,
    validate_study_set,
)
from .timeseries import (
    TIMESERIES_WINDOW_SCHEMA,
    TIMESERIES_WINDOW_VERSION,
    get_timeseries_window,
)

__all__ = [
    "CapabilityUnavailableError",
    "FIXTURE_SCHEMA",
    "FIXTURE_VERSION",
    "InvalidRequestError",
    "InvalidStudySetError",
    "LibraryAdapter",
    "LibraryApiError",
    "LibraryNotFoundError",
    "RevisionConflictError",
    "SESSION_CATALOG_ROW_SCHEMA",
    "SESSION_CATALOG_ROW_VERSION",
    "SESSION_CATALOG_SCHEMA",
    "SESSION_CATALOG_VERSION",
    "SELECTION_BRIDGE_SCHEMA",
    "SELECTION_BRIDGE_VERSION",
    "SessionNotFoundError",
    "SignalNotFoundError",
    "STUDY_SET_SCHEMA",
    "STUDY_SET_VERSION",
    "StudySetNotFoundError",
    "TIMESERIES_WINDOW_SCHEMA",
    "TIMESERIES_WINDOW_VERSION",
    "TimeseriesUnavailableError",
    "create_study_set",
    "delete_study_set",
    "derive_object_id",
    "discover_libraries",
    "build_session_catalog",
    "export_library_fixture",
    "get_timeseries_window",
    "is_valid_object_id",
    "list_study_sets",
    "load_study_set",
    "make_session_key",
    "make_session_ref_id",
    "make_unique_object_id",
    "parse_session_key",
    "study_set_to_selection_snapshot",
    "update_study_set",
    "validate_study_set",
]
