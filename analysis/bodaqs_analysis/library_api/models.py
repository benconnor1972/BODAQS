"""Payload builders for the BODAQS Library API adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


LIBRARY_API_CAPABILITIES_SCHEMA = "bodaqs.library_api_capabilities"
LIBRARY_API_CAPABILITIES_VERSION = 1


def default_capabilities() -> dict[str, Any]:
    return {
        "schema": LIBRARY_API_CAPABILITIES_SCHEMA,
        "version": LIBRARY_API_CAPABILITIES_VERSION,
        "service": {
            "name": "BODAQS Library API",
            "api_version": "0",
            "implementation": "python-library-adapter",
        },
        "required": {
            "read_processed_library": True,
            "read_parquet": True,
            "list_sessions": True,
            "serve_timeseries_windows": True,
            "query_signals": True,
            "query_events": True,
            "query_metrics": True,
            "read_session_notes": True,
        },
        "features": {
            "write_study_sets": True,
            "delete_study_sets": True,
            "read_session_notes": True,
            "write_session_notes": True,
            "write_session_descriptions": True,
            "query_signals": True,
            "query_events": True,
            "query_metrics": True,
            "read_session_gps_summaries": True,
            "read_tracks": True,
            "write_tracks": True,
            "read_geospatial_policies": True,
            "write_geospatial_policies": True,
            "read_track_matches": True,
            "compute_track_matches": True,
            "query_trackpoint_matches": True,
            "cancel_trackpoint_match_queries": True,
            "read_filters": True,
            "write_filters": True,
            "export_static_bundle": False,
            "run_processing_jobs": False,
        },
    }


def library_payload(
    *,
    library_id: str,
    display_name: str,
    root: Path,
    definition: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "library_id": str(library_id),
        "display_name": str(display_name),
        "root": str(root),
        "capabilities": {
            "read_processed_library": True,
            "read_parquet": True,
            "write_study_sets": True,
            "delete_study_sets": True,
            "read_session_notes": True,
            "write_session_notes": True,
            "write_session_descriptions": True,
            "query_signals": True,
            "query_events": True,
            "query_metrics": True,
            "read_session_gps_summaries": True,
            "read_tracks": True,
            "write_tracks": True,
            "read_geospatial_policies": True,
            "write_geospatial_policies": True,
            "read_track_matches": True,
            "compute_track_matches": True,
            "query_trackpoint_matches": True,
            "cancel_trackpoint_match_queries": True,
            "read_filters": True,
            "write_filters": True,
        },
    }
    if definition:
        schema = definition.get("schema")
        version = definition.get("version")
        if schema is not None:
            payload["definition_schema"] = str(schema)
        if version is not None:
            payload["definition_version"] = version
    return payload
