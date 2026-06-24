"""Error types for the BODAQS Library API adapter.

The local HTTP service can map these directly to the contract error envelope.
"""

from __future__ import annotations

from typing import Any, Mapping


class LibraryApiError(Exception):
    """Base class for adapter errors that should become API error responses."""

    code = "internal_error"
    status_code = 500
    default_message = "An internal error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.message = str(message or self.default_message)
        self.details = dict(details or {})
        super().__init__(self.message)

    def to_error_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


class LibraryNotFoundError(LibraryApiError):
    code = "library_not_found"
    status_code = 404
    default_message = "Library was not found."


class SessionNotFoundError(LibraryApiError):
    code = "session_not_found"
    status_code = 404
    default_message = "Session was not found."


class SessionDeleteConflictError(LibraryApiError):
    code = "session_delete_conflict"
    status_code = 409
    default_message = "Session is still referenced by saved library objects."


class StudySetNotFoundError(LibraryApiError):
    code = "study_set_not_found"
    status_code = 404
    default_message = "Study set was not found."


class SessionFilterNotFoundError(LibraryApiError):
    code = "session_filter_not_found"
    status_code = 404
    default_message = "Session filter was not found."


class TrackNotFoundError(LibraryApiError):
    code = "track_not_found"
    status_code = 404
    default_message = "Track was not found."


class GeospatialPolicyNotFoundError(LibraryApiError):
    code = "geospatial_policy_not_found"
    status_code = 404
    default_message = "Geospatial policy was not found."


class TrackMatchNotFoundError(LibraryApiError):
    code = "track_match_not_found"
    status_code = 404
    default_message = "Track match was not found."


class TrackpointMatchQueryNotFoundError(LibraryApiError):
    code = "trackpoint_match_query_not_found"
    status_code = 404
    default_message = "Trackpoint match query was not found."


class InvalidRequestError(LibraryApiError):
    code = "invalid_request"
    status_code = 400
    default_message = "Request is invalid."


class InvalidStudySetError(LibraryApiError):
    code = "invalid_study_set"
    status_code = 400
    default_message = "Study set is invalid."


class InvalidSessionFilterError(LibraryApiError):
    code = "invalid_session_filter"
    status_code = 400
    default_message = "Session filter is invalid."


class InvalidTrackError(LibraryApiError):
    code = "invalid_track"
    status_code = 400
    default_message = "Track is invalid."


class InvalidGeospatialPolicyError(LibraryApiError):
    code = "invalid_geospatial_policy"
    status_code = 400
    default_message = "Geospatial policy is invalid."


class RevisionConflictError(LibraryApiError):
    code = "revision_conflict"
    status_code = 409
    default_message = "Study set was modified after it was loaded."


class CapabilityUnavailableError(LibraryApiError):
    code = "capability_unavailable"
    status_code = 501
    default_message = "Capability is unavailable."


class SignalNotFoundError(LibraryApiError):
    code = "signal_not_found"
    status_code = 404
    default_message = "Signal was not found."


class GpsUnavailableError(LibraryApiError):
    code = "gps_unavailable"
    status_code = 404
    default_message = "GPS data is unavailable."


class TrackMatchUnavailableError(LibraryApiError):
    code = "track_match_unavailable"
    status_code = 404
    default_message = "Track match data is unavailable."


class TrackpointMatchQueryUnavailableError(LibraryApiError):
    code = "trackpoint_match_query_unavailable"
    status_code = 404
    default_message = "Trackpoint match query data is unavailable."


class TimeseriesUnavailableError(LibraryApiError):
    code = "timeseries_unavailable"
    status_code = 404
    default_message = "Time-series data is unavailable."
