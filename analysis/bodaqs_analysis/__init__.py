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
    "prepare_session_input": (".session_archive", "prepare_session_input"),
    "read_session_archive_contract": (".session_archive", "read_session_archive_contract"),
    "session_input_identity": (".session_archive", "session_input_identity"),
    "find_overlapping_fit_candidates": (".io_fit", "find_overlapping_fit_candidates"),
    "inspect_fit_stream": (".io_fit", "inspect_fit_stream"),
    "parse_fit_bindings": (".io_fit", "parse_fit_bindings"),
    "parse_fit_stream": (".io_fit", "parse_fit_stream"),
    "data_syn_bike_manual_settings": (".exporters.data_syn_bike", "data_syn_bike_manual_settings"),
    "default_data_syn_bike_export_config": (".exporters.data_syn_bike", "default_data_syn_bike_export_config"),
    "export_data_syn_bike_resolved": (".exporters.data_syn_bike", "export_data_syn_bike_resolved"),
    "render_data_syn_bike_manual_settings_text": (
        ".exporters.data_syn_bike",
        "render_data_syn_bike_manual_settings_text",
    ),
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
    "ImportAgentAppConfig": (".import_agent_provisioning", "ImportAgentAppConfig"),
    "ImportAgentLibraryConfig": (".import_agent_provisioning", "ImportAgentLibraryConfig"),
    "ImportSourceConfig": (".import_agent", "ImportSourceConfig"),
    "ImportAgentManagedSourceConfig": (".import_agent_provisioning", "ImportAgentManagedSourceConfig"),
    "LoggerWifiSourceConfig": (".import_agent_sources", "LoggerWifiSourceConfig"),
    "BikeSetupPreset": (".session_note_presets", "BikeSetupPreset"),
    "ProvisionedImportAgentLibrary": (".import_agent_provisioning", "ProvisionedImportAgentLibrary"),
    "ProvisionedImportAgentSource": (".import_agent_provisioning", "ProvisionedImportAgentSource"),
    "ProvisionedImportAgentAppSetup": (".import_agent_provisioning", "ProvisionedImportAgentAppSetup"),
    "ImportAgentSupervisor": (".import_agent", "ImportAgentSupervisor"),
    "ImportSourceRunner": (".import_agent", "ImportSourceRunner"),
    "LoggerWifiApiClient": (".import_agent_logger_wifi", "LoggerWifiApiClient"),
    "LoggerWifiApiError": (".import_agent_logger_wifi", "LoggerWifiApiError"),
    "LoggerWifiDiscoveryError": (".import_agent_logger_wifi_discovery", "LoggerWifiDiscoveryError"),
    "LoggerWifiDiscoveryResult": (".import_agent_logger_wifi_discovery", "LoggerWifiDiscoveryResult"),
    "LoggerWifiDiscoveryUnavailable": (
        ".import_agent_logger_wifi_discovery",
        "LoggerWifiDiscoveryUnavailable",
    ),
    "build_windows_startup_command": (".import_agent_startup", "build_windows_startup_command"),
    "build_import_agent_tray_image": (".import_agent_tray", "build_import_agent_tray_image"),
    "default_import_agent_app_config_dir": (".import_agent_provisioning", "default_import_agent_app_config_dir"),
    "default_import_agent_app_config_path": (".import_agent_provisioning", "default_import_agent_app_config_path"),
    "import_agent_app_config_to_jsonable": (".import_agent_provisioning", "import_agent_app_config_to_jsonable"),
    "load_import_agent_app_config": (".import_agent_provisioning", "load_import_agent_app_config"),
    "load_import_source_config": (".import_agent", "load_import_source_config"),
    "load_import_sources": (".import_agent", "load_import_sources"),
    "managed_import_agent_source_roots": (".import_agent_provisioning", "managed_import_agent_source_roots"),
    "make_import_agent_app_config": (".import_agent_provisioning", "make_import_agent_app_config"),
    "normalize_import_source_type": (".import_agent_sources", "normalize_import_source_type"),
    "parse_import_agent_app_config": (".import_agent_provisioning", "parse_import_agent_app_config"),
    "parse_logger_wifi_source_config": (".import_agent_sources", "parse_logger_wifi_source_config"),
    "load_bike_setup_preset": (".session_note_presets", "load_bike_setup_preset"),
    "parse_bike_setup_preset": (".session_note_presets", "parse_bike_setup_preset"),
    "discover_logger_wifi_sources": (
        ".import_agent_logger_wifi_discovery",
        "discover_logger_wifi_sources",
    ),
    "discover_single_logger_wifi_source": (
        ".import_agent_logger_wifi_discovery",
        "discover_single_logger_wifi_source",
    ),
    "provision_import_agent_app_setup": (".import_agent_provisioning", "provision_import_agent_app_setup"),
    "provision_import_agent_library_for_app": (".import_agent_provisioning", "provision_import_agent_library_for_app"),
    "provision_import_agent_library": (".import_agent_provisioning", "provision_import_agent_library"),
    "provision_import_agent_source_for_app": (".import_agent_provisioning", "provision_import_agent_source_for_app"),
    "provision_import_agent_source": (".import_agent_provisioning", "provision_import_agent_source"),
    "remove_import_agent_source": (".import_agent_provisioning", "remove_import_agent_source"),
    "runtime_import_agent_app_config_path": (".import_agent_provisioning", "runtime_import_agent_app_config_path"),
    "apply_bike_profile_form_values": (".import_agent_profile_builders", "apply_bike_profile_form_values"),
    "bike_profile_form_values": (".import_agent_profile_builders", "bike_profile_form_values"),
    "build_bike_profile_from_form": (".import_agent_profile_builders", "build_bike_profile_from_form"),
    "build_session_note_template_from_field_ids": (
        ".import_agent_profile_builders",
        "build_session_note_template_from_field_ids",
    ),
    "copy_source_bike_profile": (".import_agent_profile_builders", "copy_source_bike_profile"),
    "copy_source_note_assets": (".import_agent_profile_builders", "copy_source_note_assets"),
    "derive_profile_id": (".import_agent_profile_builders", "derive_profile_id"),
    "front_head_angle_from_profile": (".import_agent_profile_builders", "front_head_angle_from_profile"),
    "front_vertical_transform_from_profile": (
        ".import_agent_profile_builders",
        "front_vertical_transform_from_profile",
    ),
    "load_session_note_field_catalog": (".import_agent_profile_builders", "load_session_note_field_catalog"),
    "normalize_lut_points": (".import_agent_profile_builders", "normalize_lut_points"),
    "parse_lut_text": (".import_agent_profile_builders", "parse_lut_text"),
    "rear_wheel_lut_from_profile": (".import_agent_profile_builders", "rear_wheel_lut_from_profile"),
    "set_front_vertical_wheel_transform": (
        ".import_agent_profile_builders",
        "set_front_vertical_wheel_transform",
    ),
    "set_rear_wheel_lut_transform": (".import_agent_profile_builders", "set_rear_wheel_lut_transform"),
    "SOURCE_TYPE_FILESYSTEM_ARCHIVE": (".import_agent_sources", "SOURCE_TYPE_FILESYSTEM_ARCHIVE"),
    "SOURCE_TYPE_LOGGER_WIFI": (".import_agent_sources", "SOURCE_TYPE_LOGGER_WIFI"),
    "run_sources_once": (".import_agent", "run_sources_once"),
    "save_import_agent_app_config": (".import_agent_provisioning", "save_import_agent_app_config"),
    "read_windows_startup_registration": (".import_agent_startup", "read_windows_startup_registration"),
    "load_import_agent_tray_image": (".import_agent_tray", "load_import_agent_tray_image"),
    "sync_windows_startup_registration": (".import_agent_startup", "sync_windows_startup_registration"),
    "tray_supported": (".import_agent_tray", "tray_supported"),
    "update_import_agent_app_auto_start": (".import_agent_provisioning", "update_import_agent_app_auto_start"),
    "update_import_agent_source_session_note_attach_enabled": (
        ".import_agent_provisioning",
        "update_import_agent_source_session_note_attach_enabled",
    ),
    "update_import_agent_source_enabled": (".import_agent_provisioning", "update_import_agent_source_enabled"),
    "update_import_agent_source_library": (".import_agent_provisioning", "update_import_agent_source_library"),
    "validate_bike_setup_preset": (".session_note_presets", "validate_bike_setup_preset"),
    "validate_import_agent_app_config": (".import_agent_provisioning", "validate_import_agent_app_config"),
    "validate_import_sources": (".import_agent", "validate_import_sources"),
    "watch_sources": (".import_agent", "watch_sources"),
    "windows_startup_supported": (".import_agent_startup", "windows_startup_supported"),
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
