from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS: dict[str, tuple[str, str]] = {
    "build_session_from_dataframe": (".pipeline", "build_session_from_dataframe"),
    "preprocess_resolved": (".pipeline", "preprocess_resolved"),
    "preprocess_session": (".pipeline", "preprocess_session"),
    "normalize_and_scale": (".normalize", "normalize_and_scale"),
    "estimate_va": (".va", "estimate_va"),
    "load_event_schema": (".schema", "load_event_schema"),
    "parse_event_schema": (".schema", "parse_event_schema"),
    "detect_events_from_schema": (".detect", "detect_events_from_schema"),
    "extract_metrics_df": (".metrics", "extract_metrics_df"),
    "apply_signal_transforms": (".bike_profile", "apply_signal_transforms"),
    "load_bike_profile": (".bike_profile", "load_bike_profile"),
    "parse_bike_profile": (".bike_profile", "parse_bike_profile"),
    "resolve_normalization_ranges": (".bike_profile", "resolve_normalization_ranges"),
    "canonicalize_logger_dataframe": (".io_logger", "canonicalize_logger_dataframe"),
    "parse_logger_log_metadata": (".io_logger", "parse_logger_log_metadata"),
    "prepare_logger_dataframe": (".io_logger", "prepare_logger_dataframe"),
    "find_overlapping_fit_candidates": (".io_fit", "find_overlapping_fit_candidates"),
    "inspect_fit_stream": (".io_fit", "inspect_fit_stream"),
    "parse_fit_bindings": (".io_fit", "parse_fit_bindings"),
    "parse_fit_stream": (".io_fit", "parse_fit_stream"),
    "default_data_syn_bike_export_config": (".exporters.data_syn_bike", "default_data_syn_bike_export_config"),
    "export_data_syn_bike_resolved": (".exporters.data_syn_bike", "export_data_syn_bike_resolved"),
    "write_data_syn_bike_exports": (".exporters.data_syn_bike", "write_data_syn_bike_exports"),
    "default_preprocess_config": (".preprocess_profile", "default_preprocess_config"),
    "discover_preprocess_profiles": (".preprocess_profile", "discover_preprocess_profiles"),
    "load_preprocess_config": (".preprocess_profile", "load_preprocess_config"),
    "load_preprocess_profile": (".preprocess_profile", "load_preprocess_profile"),
    "make_preprocess_profile": (".preprocess_profile", "make_preprocess_profile"),
    "preprocess_config_from_profile": (".preprocess_profile", "preprocess_config_from_profile"),
    "preprocess_profile_filename": (".preprocess_profile", "preprocess_profile_filename"),
    "preprocess_profile_path": (".preprocess_profile", "preprocess_profile_path"),
    "resolve_preprocess_config_paths": (".preprocess_profile", "resolve_preprocess_config_paths"),
    "save_preprocess_profile": (".preprocess_profile", "save_preprocess_profile"),
    "validate_preprocess_config": (".preprocess_profile", "validate_preprocess_config"),
    "validate_preprocess_profile": (".preprocess_profile", "validate_preprocess_profile"),
    "ImportSourceConfig": (".import_agent", "ImportSourceConfig"),
    "ImportAgentSupervisor": (".import_agent", "ImportAgentSupervisor"),
    "ImportSourceRunner": (".import_agent", "ImportSourceRunner"),
    "load_import_source_config": (".import_agent", "load_import_source_config"),
    "load_import_sources": (".import_agent", "load_import_sources"),
    "run_sources_once": (".import_agent", "run_sources_once"),
    "validate_import_sources": (".import_agent", "validate_import_sources"),
    "watch_sources": (".import_agent", "watch_sources"),
}

__all__ = sorted(_EXPORTS.keys())


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals().keys()) | set(__all__))
