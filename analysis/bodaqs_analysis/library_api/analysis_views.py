"""Analysis view registry and adequacy checks for the Library API."""

from __future__ import annotations

from typing import Any, Mapping

from .errors import AnalysisViewNotFoundError


ANALYSIS_VIEW_REGISTRY_SCHEMA = "bodaqs.analysis_view_registry"
ANALYSIS_VIEW_REGISTRY_VERSION = 1
ANALYSIS_ADEQUACY_SCHEMA = "bodaqs.analysis_adequacy"
ANALYSIS_ADEQUACY_VERSION = 1
ANALYSIS_ADEQUACY_POLICY_VERSION = 1

SIMPLE_SUSPENSION_VIEW_ID = "simple-suspension"
_SUSPENSION_ENDS = ("front", "rear")
_REQUIRED_EVENT_TYPES = ("compressions_all", "rebounds_all")
_REQUIRED_METRIC_COLUMNS = (
    "m_stroke_disp_max",
    "m_stroke_disp_range",
    "m_interval_vel_max",
    "m_interval_vel_min",
)


def list_analysis_views() -> list[dict[str, Any]]:
    """Return supported analysis view descriptors."""

    return [_simple_suspension_view_descriptor()]


def get_analysis_view(view_id: str) -> dict[str, Any]:
    normalized = str(view_id or "").strip()
    for view in list_analysis_views():
        if view["view_id"] == normalized:
            return view
    raise AnalysisViewNotFoundError(
        "Analysis view was not found.",
        details={"view_id": normalized, "available_view_ids": [view["view_id"] for view in list_analysis_views()]},
    )


def analysis_view_adequacy_policy_version(view_id: str) -> int:
    """Return the cache-affecting adequacy policy version for a view."""

    view = get_analysis_view(view_id)
    if view["view_id"] == SIMPLE_SUSPENSION_VIEW_ID:
        return ANALYSIS_ADEQUACY_POLICY_VERSION
    return ANALYSIS_ADEQUACY_POLICY_VERSION


def evaluate_analysis_view_adequacy(
    view_id: str,
    *,
    scope: Mapping[str, Any],
    session_rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluate whether a scope can support an analysis view."""

    view = get_analysis_view(view_id)
    if view["view_id"] == SIMPLE_SUSPENSION_VIEW_ID:
        return _simple_suspension_adequacy(view, scope=scope, session_rows=session_rows)
    raise AnalysisViewNotFoundError(
        "Analysis view was not found.",
        details={"view_id": str(view_id or "").strip()},
    )


def _simple_suspension_view_descriptor() -> dict[str, Any]:
    return {
        "schema": "bodaqs.analysis_view",
        "version": 1,
        "view_id": SIMPLE_SUSPENSION_VIEW_ID,
        "display_name": "Simple Suspension Analysis",
        "category": "Suspension",
        "description": "Compare wheel displacement, velocity, stroke length, and suspension event metrics.",
        "route": "/analysis/simple-suspension",
        "scope_kinds": ["study_set", "session_refs"],
        "adequacy_policy": "partial",
        "requirements": {
            "required": [
                {
                    "id": "wheel_motion_data",
                    "label": "Wheel displacement and velocity data",
                    "applies_to": "session_end",
                    "minimum": "at_least_one_end",
                    "description": "At least one suspension end must expose wheel displacement and velocity evidence.",
                }
            ],
            "recommended": [
                {
                    "id": "both_ends",
                    "label": "Front and rear ends",
                    "applies_to": "session",
                    "description": "Both ends are available for front-vs-rear comparison.",
                },
                {
                    "id": "event_metrics",
                    "label": "Compression/rebound event metrics",
                    "applies_to": "session",
                    "description": "Compression and rebound events include velocity and stroke-length metrics.",
                },
            ],
            "optional": [
                {
                    "id": "gps",
                    "label": "GPS data",
                    "applies_to": "session",
                    "description": "GPS data is available for track-sector filtering.",
                }
            ],
        },
    }


def _simple_suspension_adequacy(
    view: Mapping[str, Any],
    *,
    scope: Mapping[str, Any],
    session_rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    session_results = [_simple_suspension_session_result(row) for row in session_rows]
    usable_sessions = [result for result in session_results if bool(result["usable"])]
    blocked_sessions = [result for result in session_results if not bool(result["usable"])]
    if not session_results or not usable_sessions:
        scope_status = "blocked"
    elif blocked_sessions:
        scope_status = "partial"
    elif any(result["status"] != "ready" for result in session_results):
        scope_status = "warning"
    else:
        scope_status = "ready"

    usable_units = [
        {
            "session_ref_id": result["session_ref_id"],
            "library_id": result["library_id"],
            "session_key": result["session_key"],
            "run_id": result["run_id"],
            "session_id": result["session_id"],
            "unit_kind": "session_end",
            "end": end,
        }
        for result in session_results
        for end, end_result in result["ends"].items()
        if end_result.get("usable")
    ]
    excluded_units = [
        {
            "session_ref_id": result["session_ref_id"],
            "library_id": result["library_id"],
            "session_key": result["session_key"],
            "run_id": result["run_id"],
            "session_id": result["session_id"],
            "unit_kind": "session_end",
            "end": end,
            "missing_required": list(end_result.get("missing_required") or []),
            "reason": "; ".join(str(item) for item in end_result.get("missing_required") or [])
            or "Suspension end is not analyzable.",
        }
        for result in session_results
        for end, end_result in result["ends"].items()
        if not end_result.get("usable")
    ]

    return {
        "schema": ANALYSIS_ADEQUACY_SCHEMA,
        "version": ANALYSIS_ADEQUACY_VERSION,
        "view_id": view["view_id"],
        "display_name": view["display_name"],
        "policy": view["adequacy_policy"],
        "status": scope_status,
        "summary": _scope_summary(scope_status, usable_sessions=len(usable_sessions), total_sessions=len(session_results)),
        "scope": dict(scope),
        "requirements": view["requirements"],
        "total_session_count": len(session_results),
        "usable_session_count": len(usable_sessions),
        "blocked_session_count": len(blocked_sessions),
        "usable_units": usable_units,
        "excluded_units": excluded_units,
        "messages": _scope_messages(session_results, scope_status=scope_status),
        "session_results": session_results,
    }


def _simple_suspension_session_result(row: Mapping[str, Any]) -> dict[str, Any]:
    signals = [signal for signal in row.get("available_signals") or [] if isinstance(signal, Mapping)]
    has_event_metrics = _has_required_event_metrics(row)
    end_results = {end: _end_result(end, signals, has_event_velocity_metrics=has_event_metrics) for end in _SUSPENSION_ENDS}
    usable_end_count = sum(1 for result in end_results.values() if result["usable"])
    missing_recommended = []
    missing_optional = []
    if usable_end_count < len(_SUSPENSION_ENDS):
        missing_recommended.append("both_ends")
    if not has_event_metrics:
        missing_recommended.append("event_metrics")
    gps_summary = row.get("gps_summary") if isinstance(row.get("gps_summary"), Mapping) else {}
    if not bool(gps_summary.get("present")):
        missing_optional.append("gps")

    if usable_end_count == 0:
        status = "blocked"
    elif missing_recommended or missing_optional:
        status = "warning"
    else:
        status = "ready"

    return {
        "session_ref_id": row.get("session_ref_id"),
        "library_id": row.get("library_id"),
        "session_key": row.get("session_key"),
        "run_id": row.get("run_id"),
        "session_id": row.get("session_id"),
        "label": _session_label(row),
        "status": status,
        "usable": usable_end_count > 0,
        "usable_end_count": usable_end_count,
        "ends": end_results,
        "missing_recommended": missing_recommended,
        "missing_optional": missing_optional,
        "messages": _session_messages(missing_recommended, missing_optional, usable_end_count=usable_end_count),
    }


def _end_result(
    end: str,
    signals: list[Mapping[str, Any]],
    *,
    has_event_velocity_metrics: bool,
) -> dict[str, Any]:
    displacement_signal = _wheel_displacement_signal(end, signals)
    velocity_signal = _wheel_velocity_signal(end, signals)
    missing_required = []
    if displacement_signal is None:
        missing_required.append("wheel_displacement_signal")
    if velocity_signal is None and not has_event_velocity_metrics:
        missing_required.append("wheel_velocity_data")
    if missing_required:
        return {
            "status": "blocked",
            "usable": False,
            "missing_required": missing_required,
            "signals": [],
        }
    signals_out = [
        {
            "role": "wheel_displacement",
            "signal_id": displacement_signal.get("signal_id"),
            "column": displacement_signal.get("column"),
            "display_name": displacement_signal.get("display_name"),
        }
    ]
    if velocity_signal is not None:
        signals_out.append(
            {
                "role": "wheel_velocity",
                "signal_id": velocity_signal.get("signal_id"),
                "column": velocity_signal.get("column"),
                "display_name": velocity_signal.get("display_name"),
            }
        )
    return {
        "status": "ready",
        "usable": True,
        "missing_required": [],
        "signals": signals_out,
        "velocity_evidence": "signal" if velocity_signal is not None else "event_metrics",
    }


def _wheel_displacement_signal(end: str, signals: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    for signal in signals:
        if _signal_text(signal, "end") != end:
            continue
        quantity = _signal_text(signal, "quantity")
        unit = _signal_text(signal, "unit")
        domain = _signal_text(signal, "domain")
        if quantity == "disp_norm" and unit == "1":
            return signal
        if quantity == "disp" and domain == "wheel":
            return signal
    return None


def _wheel_velocity_signal(end: str, signals: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    for signal in signals:
        if _signal_text(signal, "end") != end:
            continue
        quantity = _signal_text(signal, "quantity")
        unit = _signal_text(signal, "unit")
        domain = _signal_text(signal, "domain")
        if quantity == "vel" and unit in {"mm/s", "mmps"} and domain in {"wheel", "suspension", ""}:
            return signal
    return None


def _has_required_event_metrics(row: Mapping[str, Any]) -> bool:
    event_summary = row.get("event_summary") if isinstance(row.get("event_summary"), Mapping) else {}
    by_type = event_summary.get("by_type") if isinstance(event_summary.get("by_type"), Mapping) else {}
    if any(int(by_type.get(event_type) or 0) <= 0 for event_type in _REQUIRED_EVENT_TYPES):
        return False

    metric_summary = row.get("metric_summary") if isinstance(row.get("metric_summary"), Mapping) else {}
    schema_ids = {str(item) for item in metric_summary.get("schema_ids") or []}
    metric_columns = {str(item) for item in metric_summary.get("metric_columns") or []}
    return set(_REQUIRED_EVENT_TYPES).issubset(schema_ids) and set(_REQUIRED_METRIC_COLUMNS).issubset(metric_columns)


def _scope_summary(status: str, *, usable_sessions: int, total_sessions: int) -> str:
    if status == "ready":
        return f"{usable_sessions} of {total_sessions} sessions can be analyzed cleanly."
    if status == "warning":
        return f"{usable_sessions} of {total_sessions} sessions can be analyzed with missing recommended or optional data."
    if status == "partial":
        return f"{usable_sessions} of {total_sessions} sessions can be analyzed; some sessions will be excluded."
    return "No sessions in this scope have the required suspension motion data."


def _scope_messages(session_results: list[Mapping[str, Any]], *, scope_status: str) -> list[dict[str, str]]:
    if scope_status == "ready":
        return []
    messages: list[dict[str, str]] = []
    blocked_count = sum(1 for result in session_results if not result.get("usable"))
    if blocked_count:
        messages.append(
            {
                "severity": "warning" if scope_status == "partial" else "error",
                "code": "blocked_sessions",
                "message": f"{blocked_count} session(s) lack required suspension motion data.",
            }
        )
    missing_metrics_count = sum(1 for result in session_results if "event_metrics" in result.get("missing_recommended", []))
    if missing_metrics_count:
        messages.append(
            {
                "severity": "warning",
                "code": "missing_event_metrics",
                "message": f"{missing_metrics_count} session(s) lack complete compression/rebound metric support.",
            }
        )
    missing_gps_count = sum(1 for result in session_results if "gps" in result.get("missing_optional", []))
    if missing_gps_count:
        messages.append(
            {
                "severity": "info",
                "code": "missing_gps",
                "message": f"{missing_gps_count} session(s) lack GPS data; sector filtering may be unavailable.",
            }
        )
    return messages


def _session_messages(
    missing_recommended: list[str],
    missing_optional: list[str],
    *,
    usable_end_count: int,
) -> list[dict[str, str]]:
    if usable_end_count == 0:
        return [
            {
                "severity": "error",
                "code": "missing_required_motion_data",
                "message": "No front or rear end has both wheel displacement and velocity evidence.",
            }
        ]
    messages: list[dict[str, str]] = []
    if "both_ends" in missing_recommended:
        messages.append(
            {
                "severity": "warning",
                "code": "missing_end",
                "message": "Only one suspension end has required displacement data.",
            }
        )
    if "event_metrics" in missing_recommended:
        messages.append(
            {
                "severity": "warning",
                "code": "missing_event_metrics",
                "message": "Compression/rebound event metrics are incomplete.",
            }
        )
    if "gps" in missing_optional:
        messages.append(
            {
                "severity": "info",
                "code": "missing_gps",
                "message": "GPS data is unavailable for sector filtering.",
            }
        )
    return messages


def _session_label(row: Mapping[str, Any]) -> str:
    display = row.get("display")
    if isinstance(display, Mapping):
        label = str(display.get("label") or "").strip()
        if label:
            return label
    return str(row.get("session_key") or row.get("session_id") or "")


def _signal_text(signal: Mapping[str, Any], key: str) -> str:
    return str(signal.get(key) or "").strip().lower()
