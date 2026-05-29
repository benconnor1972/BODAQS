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


class StudySetNotFoundError(LibraryApiError):
    code = "study_set_not_found"
    status_code = 404
    default_message = "Study set was not found."


class InvalidRequestError(LibraryApiError):
    code = "invalid_request"
    status_code = 400
    default_message = "Request is invalid."


class InvalidStudySetError(LibraryApiError):
    code = "invalid_study_set"
    status_code = 400
    default_message = "Study set is invalid."


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


class TimeseriesUnavailableError(LibraryApiError):
    code = "timeseries_unavailable"
    status_code = 404
    default_message = "Time-series data is unavailable."
