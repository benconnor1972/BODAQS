from __future__ import annotations

import copy
import json
import os
import re
import shutil
import stat
import sys
from dataclasses import dataclass, replace
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from bodaqs_analysis.bike_profile import validate_bike_profile
from bodaqs_analysis.import_agent_sources import (
    LoggerWifiSourceConfig,
    SOURCE_TYPE_FILESYSTEM_ARCHIVE,
    SOURCE_TYPE_LOGGER_WIFI,
    logger_wifi_source_config_to_jsonable,
    normalize_import_source_type,
    parse_logger_wifi_source_config,
)
from bodaqs_analysis.preprocess_profile import normalize_preprocess_config_keys, validate_preprocess_profile
from bodaqs_analysis.schema import parse_event_schema
from bodaqs_analysis.session_note_presets import validate_bike_setup_preset
from bodaqs_analysis.session_notes import validate_session_note_template


IMPORT_AGENT_APP_SCHEMA = "bodaqs.import_agent_app"
IMPORT_AGENT_APP_VERSION = 1
IMPORT_AGENT_LIBRARY_SCHEMA = "bodaqs.import_agent_library"
IMPORT_AGENT_LIBRARY_VERSION = 1

DEFAULT_IMPORT_SOURCE_FILENAME = "import_source.json"
DEFAULT_SETTINGS_DIRNAME = "settings"
DEFAULT_BIKE_DIRNAME = "bike"
DEFAULT_LIBRARY_COLLECTION_DIRNAME = "libraries"
DEFAULT_LIBRARY_BIKE_PROFILES_DIRNAME = "bike_profiles"
DEFAULT_LIBRARY_PREPROCESS_PROFILES_DIRNAME = "preprocess_profiles"
DEFAULT_LIBRARY_EVENT_SCHEMAS_DIRNAME = "event_schemas"
DEFAULT_NOTES_DIRNAME = "notes"
DEFAULT_LIBRARY_RUNS_DIRNAME = "runs"
DEFAULT_LIBRARY_STATE_DIRNAME = "library"
DEFAULT_IMPORT_AGENT_APP_CONFIG_FILENAME = "import_agent_app.json"
DEFAULT_IMPORT_AGENT_VENDOR_DIRNAME = "BODAQS"
DEFAULT_IMPORT_AGENT_APP_DIRNAME = "import-agent"
IMPORT_AGENT_APP_CONFIG_MODE_AUTO = "auto"
IMPORT_AGENT_APP_CONFIG_MODE_PORTABLE = "portable"
IMPORT_AGENT_APP_CONFIG_MODE_INSTALLED = "installed"

_ASSET_PACKAGE = "bodaqs_import_manager.import_agent_assets"


def default_library_data_syn_bike_export_config(*, enabled: bool = False) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "adc_bit_count": 12,
        "raw_scale_mode": "processed_wheel_travel",
        "clip_raw_to_adc_range": True,
        "drop_inactive": True,
        "split_by_activity": False,
        "sample_count_origin": "session",
        "filename_template": "{run_id}__{session_id}__{export_id}__data_syn_bike.csv",
    }


def _library_metadata_payload(
    *,
    library_id: str,
    display_name: str,
    artifacts_dir: Path,
    data_syn_bike_export_enabled: bool,
) -> dict[str, Any]:
    return {
        "schema": IMPORT_AGENT_LIBRARY_SCHEMA,
        "version": IMPORT_AGENT_LIBRARY_VERSION,
        "library_id": library_id,
        "display_name": display_name,
        "artifacts_dir": str(artifacts_dir),
        "exports": {
            "data_syn_bike": default_library_data_syn_bike_export_config(
                enabled=data_syn_bike_export_enabled
            )
        },
    }


def _library_metadata_data_syn_bike_export_enabled(artifacts_dir: Path) -> bool:
    metadata = _read_json(artifacts_dir / "library_definition.json", {})
    exports = metadata.get("exports") if isinstance(metadata, Mapping) else None
    data_syn_bike = exports.get("data_syn_bike") if isinstance(exports, Mapping) else None
    if not isinstance(data_syn_bike, Mapping):
        return False
    return bool(data_syn_bike.get("enabled", False))


def _source_session_note_attach_enabled(source_root: Path) -> bool:
    payload = _read_json(source_root / DEFAULT_IMPORT_SOURCE_FILENAME, {})
    if not isinstance(payload, Mapping):
        return False
    session_note = payload.get("session_note")
    if not isinstance(session_note, Mapping):
        return False
    return bool(session_note.get("attach_on_import", False))


def _source_force_reprocess_enabled(source_root: Path) -> bool:
    payload = _read_json(source_root / DEFAULT_IMPORT_SOURCE_FILENAME, {})
    if not isinstance(payload, Mapping):
        return False
    return bool(payload.get("force_reprocess", False))


def _coerce_index_value(value: Any, *, field_name: str, default: int) -> int:
    if value is None:
        return int(default)
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be an integer") from None
    if number < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return number


def _session_naming_payload(
    *,
    enabled: bool,
    base: Optional[str],
    index_start: int = 1,
    index_padding: int = 2,
) -> dict[str, Any]:
    base_text = _optional_text(base)
    if enabled and base_text is None:
        raise ValueError("Session base name is required when session auto-naming is enabled")
    return {
        "enabled": bool(enabled),
        "mode": "base_index" if enabled else "default",
        "base": base_text or "",
        "index_start": _coerce_index_value(index_start, field_name="session index start", default=1),
        "index_padding": _coerce_index_value(index_padding, field_name="session index padding", default=2),
    }


def _write_source_session_note_attach_enabled(source_root: Path, *, enabled: bool) -> None:
    config_path = source_root / DEFAULT_IMPORT_SOURCE_FILENAME
    payload = _read_json(config_path, {})
    if not isinstance(payload, Mapping):
        raise ValueError(f"Import source config is not a JSON object: {config_path}")
    updated = dict(payload)
    session_note = updated.get("session_note")
    if not isinstance(session_note, Mapping):
        session_note = {}
    session_note = dict(session_note)
    session_note.setdefault("template_path", DEFAULT_NOTES_DIRNAME)
    session_note.setdefault("setup_preset_path", DEFAULT_NOTES_DIRNAME)
    session_note["attach_on_import"] = bool(enabled)
    updated["session_note"] = session_note
    _write_json(config_path, updated, overwrite=True)


def _write_source_force_reprocess_enabled(source_root: Path, *, enabled: bool) -> None:
    config_path = source_root / DEFAULT_IMPORT_SOURCE_FILENAME
    payload = _read_json(config_path, {})
    if not isinstance(payload, Mapping):
        raise ValueError(f"Import source config is not a JSON object: {config_path}")
    updated = dict(payload)
    updated["force_reprocess"] = bool(enabled)
    _write_json(config_path, updated, overwrite=True)


def _write_source_session_naming(
    source_root: Path,
    *,
    enabled: bool,
    base: Optional[str],
    index_start: int = 1,
    index_padding: int = 2,
) -> None:
    config_path = source_root / DEFAULT_IMPORT_SOURCE_FILENAME
    payload = _read_json(config_path, {})
    if not isinstance(payload, Mapping):
        raise ValueError(f"Import source config is not a JSON object: {config_path}")
    updated = dict(payload)
    naming = updated.get("naming")
    if not isinstance(naming, Mapping):
        naming = {}
    naming = dict(naming)
    naming["session_description"] = _session_naming_payload(
        enabled=enabled,
        base=base,
        index_start=index_start,
        index_padding=index_padding,
    )
    updated["naming"] = naming
    _write_json(config_path, updated, overwrite=True)


def _write_source_target_library(source_root: Path, *, library_id: str, artifacts_dir: Path) -> None:
    config_path = source_root / DEFAULT_IMPORT_SOURCE_FILENAME
    payload = _read_json(config_path, {})
    if not isinstance(payload, Mapping):
        raise ValueError(f"Import source config is not a JSON object: {config_path}")
    updated = dict(payload)
    updated["library_id"] = str(library_id).strip()
    updated["artifacts_dir"] = _portable_path_text(artifacts_dir, base_dir=source_root)
    _write_json(config_path, updated, overwrite=True)


def _write_source_bike_profile_path(source_root: Path, *, bike_profile_path: Path) -> None:
    config_path = source_root / DEFAULT_IMPORT_SOURCE_FILENAME
    payload = _read_json(config_path, {})
    if not isinstance(payload, Mapping):
        raise ValueError(f"Import source config is not a JSON object: {config_path}")
    updated = dict(payload)
    updated["bike_profile_path"] = _portable_path_text(bike_profile_path, base_dir=source_root)
    _write_json(config_path, updated, overwrite=True)


def _write_source_preprocess_profile_path(source_root: Path, *, preprocess_profile_path: Path) -> None:
    config_path = source_root / DEFAULT_IMPORT_SOURCE_FILENAME
    payload = _read_json(config_path, {})
    if not isinstance(payload, Mapping):
        raise ValueError(f"Import source config is not a JSON object: {config_path}")
    updated = dict(payload)
    updated["preprocess_profile_path"] = _portable_path_text(preprocess_profile_path, base_dir=source_root)
    _write_json(config_path, updated, overwrite=True)


def _write_source_logger_wifi(source_root: Path, *, logger_wifi: LoggerWifiSourceConfig) -> None:
    config_path = source_root / DEFAULT_IMPORT_SOURCE_FILENAME
    payload = _read_json(config_path, {})
    if not isinstance(payload, Mapping):
        raise ValueError(f"Import source config is not a JSON object: {config_path}")
    updated = dict(payload)
    if normalize_import_source_type(updated.get("source_type")) != SOURCE_TYPE_LOGGER_WIFI:
        raise ValueError(f"Import source is not a Wi-Fi logger source: {config_path}")
    updated["logger_wifi"] = logger_wifi_source_config_to_jsonable(logger_wifi)
    _write_json(config_path, updated, overwrite=True)


def _optional_text(value: Any) -> Optional[str]:
    text = "" if value is None else str(value).strip()
    return text or None


def _coerce_required_path(value: str | Path, *, field_name: str) -> Path:
    if isinstance(value, Path):
        return value.expanduser().resolve()
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"{field_name} must be a non-empty path")
    return Path(text).expanduser().resolve()


def _portable_path_text(path: Path, *, base_dir: Path) -> str:
    try:
        relative = os.path.relpath(path, start=base_dir)
    except ValueError:
        return str(path)
    return Path(relative).as_posix()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _delete_directory_tree(path: Path, *, expected_parent: Path, label: str) -> None:
    target = path.expanduser().resolve()
    parent = expected_parent.expanduser().resolve()
    if not target.exists():
        return
    if not target.is_dir():
        raise ValueError(f"Cannot delete {label}: path is not a directory: {target}")
    if target == parent or not _is_relative_to(target, parent):
        raise ValueError(f"Refusing to delete {label} outside the managed root: {target}")
    _remove_directory_tree(target)


def _delete_library_artifacts_dir(path: Path, *, libraries_root: Path) -> None:
    target = path.expanduser().resolve()
    root = libraries_root.expanduser().resolve()
    if not target.exists():
        return
    if not target.is_dir():
        raise ValueError(f"Cannot delete library data folder: path is not a directory: {target}")
    if target == root or not _is_relative_to(target, root):
        raise ValueError(f"Refusing to delete library data folder outside the libraries root: {target}")

    managed_libraries_parent = import_agent_libraries_dir(root).resolve()
    shared_names = {
        DEFAULT_LIBRARY_COLLECTION_DIRNAME,
        DEFAULT_LIBRARY_BIKE_PROFILES_DIRNAME,
        DEFAULT_LIBRARY_PREPROCESS_PROFILES_DIRNAME,
        DEFAULT_LIBRARY_EVENT_SCHEMAS_DIRNAME,
    }
    is_new_layout_library = target.parent == managed_libraries_parent
    is_legacy_library = target.parent == root and target.name not in shared_names
    if not is_new_layout_library and not is_legacy_library:
        raise ValueError(f"Refusing to delete path that is not a managed library data folder: {target}")
    _remove_directory_tree(target)


def _make_tree_writable(path: Path) -> None:
    """Restore owner write/search permission before removing a managed tree."""

    for root, directories, filenames in os.walk(path, topdown=True):
        root_path = Path(root)
        try:
            os.chmod(root_path, stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)
        except OSError:
            pass
        for name in [*directories, *filenames]:
            try:
                os.chmod(root_path / name, stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)
            except OSError:
                pass


def _remove_readonly_and_retry(func: Any, path: str, exc_info: tuple[type[BaseException], BaseException, Any]) -> None:
    exc = exc_info[1]
    if not isinstance(exc, PermissionError):
        raise exc
    os.chmod(path, stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)
    func(path)


def _remove_directory_tree(path: Path) -> None:
    _make_tree_writable(path)
    shutil.rmtree(path, onerror=_remove_readonly_and_retry)


def _safe_slug(value: str, *, fallback: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._").lower()
    return slug or fallback


def library_bike_profiles_dir(library_root: str | Path) -> Path:
    return library_workspace_root(library_root) / DEFAULT_LIBRARY_BIKE_PROFILES_DIRNAME


def library_preprocess_profiles_dir(library_root: str | Path) -> Path:
    return library_workspace_root(library_root) / DEFAULT_LIBRARY_PREPROCESS_PROFILES_DIRNAME


def library_event_schemas_dir(library_root: str | Path) -> Path:
    library_path = Path(library_root).expanduser().resolve()
    return library_workspace_root(library_path) / DEFAULT_LIBRARY_EVENT_SCHEMAS_DIRNAME


def import_agent_libraries_dir(libraries_root: str | Path) -> Path:
    return Path(libraries_root).expanduser().resolve() / DEFAULT_LIBRARY_COLLECTION_DIRNAME


def library_workspace_root(library_root: str | Path) -> Path:
    library_path = Path(library_root).expanduser().resolve()
    if library_path.parent.name == DEFAULT_LIBRARY_COLLECTION_DIRNAME:
        return library_path.parent.parent
    return library_path.parent


def _bike_profile_filename(profile: Mapping[str, Any], *, fallback: str = "bike_profile") -> str:
    profile_id = _optional_text(profile.get("bike_profile_id"))
    display_name = _optional_text(profile.get("display_name"))
    return f"{_safe_slug(profile_id or display_name or fallback, fallback=fallback)}.json"


def _display_name_from_slug(value: str, *, fallback: str) -> str:
    text = re.sub(r"[-_]+", " ", str(value or "").strip()).strip()
    return text.title() if text else fallback


def _write_json(path: Path, obj: Mapping[str, Any], *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _write_text(path: Path, text: str, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@dataclass(frozen=True)
class _DiscoveredImportAgentAsset:
    name: str
    payload: Any


def _iter_asset_entries() -> list[Any]:
    return [entry for entry in files(_ASSET_PACKAGE).iterdir() if entry.is_file()]


def _discover_single_json_asset(
    *,
    label: str,
    validator: Any,
) -> _DiscoveredImportAgentAsset:
    matches: list[_DiscoveredImportAgentAsset] = []
    rejected: list[str] = []

    for entry in _iter_asset_entries():
        if entry.name == "__init__.py" or entry.suffix.lower() != ".json":
            continue
        try:
            payload = json.loads(entry.read_text(encoding="utf-8"))
            validator(payload, path=entry.name)
        except Exception as exc:
            rejected.append(f"{entry.name}: {exc}")
            continue
        matches.append(_DiscoveredImportAgentAsset(name=entry.name, payload=payload))

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(sorted(item.name for item in matches))
        raise ValueError(f"Import-agent asset package must contain exactly one valid {label} JSON file; found: {names}")

    if rejected:
        raise ValueError(
            f"Import-agent asset package did not contain a valid {label} JSON file. "
            f"Rejected candidates: {'; '.join(rejected)}"
        )
    raise ValueError(f"Import-agent asset package did not contain any JSON candidate for {label}")


def _discover_single_schema_asset() -> _DiscoveredImportAgentAsset:
    matches: list[_DiscoveredImportAgentAsset] = []
    rejected: list[str] = []

    for entry in _iter_asset_entries():
        if entry.suffix.lower() not in {".yaml", ".yml"}:
            continue
        try:
            payload = entry.read_text(encoding="utf-8")
            parse_event_schema(payload)
        except Exception as exc:
            rejected.append(f"{entry.name}: {exc}")
            continue
        matches.append(_DiscoveredImportAgentAsset(name=entry.name, payload=payload))

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(sorted(item.name for item in matches))
        raise ValueError(f"Import-agent asset package must contain exactly one valid event-schema YAML file; found: {names}")

    if rejected:
        raise ValueError(
            "Import-agent asset package did not contain a valid event-schema YAML file. "
            f"Rejected candidates: {'; '.join(rejected)}"
        )
    raise ValueError("Import-agent asset package did not contain any YAML candidate for the event schema")


def _discover_preprocess_profile_asset() -> _DiscoveredImportAgentAsset:
    return _discover_single_json_asset(label="preprocess profile", validator=validate_preprocess_profile)


def _discover_bike_profile_asset() -> _DiscoveredImportAgentAsset:
    return _discover_single_json_asset(label="bike profile", validator=validate_bike_profile)


def _load_bike_profile_file(path: str | Path) -> tuple[Path, dict[str, Any]]:
    profile_path = Path(path).expanduser().resolve()
    if not profile_path.is_file():
        raise FileNotFoundError(f"Bike profile file does not exist: {profile_path}")
    payload = _read_json_object(profile_path)
    validate_bike_profile(payload, path=profile_path)
    return profile_path, payload


def _load_preprocess_profile_file(path: str | Path) -> tuple[Path, dict[str, Any]]:
    profile_path = Path(path).expanduser().resolve()
    if not profile_path.is_file():
        raise FileNotFoundError(f"Preprocess profile file does not exist: {profile_path}")
    payload = _read_json_object(profile_path)
    validate_preprocess_profile(payload, path=profile_path)
    payload["config"] = normalize_preprocess_config_keys(payload["config"])
    return profile_path, payload


def _load_event_schema_file(path: str | Path) -> tuple[Path, str]:
    schema_path = Path(path).expanduser().resolve()
    if not schema_path.is_file():
        raise FileNotFoundError(f"Event schema file does not exist: {schema_path}")
    payload = schema_path.read_text(encoding="utf-8")
    parse_event_schema(payload)
    return schema_path, payload


def _ensure_library_default_bike_profile(
    artifacts_dir: str | Path,
    *,
    overwrite: bool,
) -> tuple[Path, dict[str, Any]]:
    asset = _discover_bike_profile_asset()
    payload = dict(asset.payload)
    profile_path = library_bike_profiles_dir(artifacts_dir) / _bike_profile_filename(payload)
    if profile_path.exists() and not overwrite:
        return _load_bike_profile_file(profile_path)
    _write_json(profile_path, payload, overwrite=overwrite)
    return profile_path, payload


def _ensure_library_default_event_schema(
    artifacts_dir: str | Path,
    *,
    overwrite: bool,
) -> tuple[Path, str]:
    asset = _discover_single_schema_asset()
    schema_path = library_event_schemas_dir(artifacts_dir) / "event_schema.yaml"
    if schema_path.exists() and not overwrite:
        return _load_event_schema_file(schema_path)
    payload = str(asset.payload)
    _write_text(schema_path, payload, overwrite=overwrite)
    return schema_path, payload


def _ensure_library_default_preprocess_profile(
    artifacts_dir: str | Path,
    *,
    event_schema_path: Path,
    overwrite: bool,
) -> tuple[Path, dict[str, Any]]:
    asset = _discover_preprocess_profile_asset()
    profile_dir = library_preprocess_profiles_dir(artifacts_dir)
    profile_path = profile_dir / "preprocess_profile.json"
    if profile_path.exists() and not overwrite:
        return _load_preprocess_profile_file(profile_path)

    payload = copy.deepcopy(dict(asset.payload))
    payload["config"] = normalize_preprocess_config_keys(payload["config"])
    payload["config"]["schema_path"] = _portable_path_text(event_schema_path, base_dir=profile_dir)
    _write_json(profile_path, payload, overwrite=overwrite)
    return profile_path, payload


def _discover_session_note_template_asset() -> _DiscoveredImportAgentAsset:
    return _discover_single_json_asset(
        label="session note template",
        validator=validate_session_note_template,
    )


def _discover_bike_setup_preset_asset() -> _DiscoveredImportAgentAsset:
    return _discover_single_json_asset(
        label="bike setup preset",
        validator=validate_bike_setup_preset,
    )


@dataclass(frozen=True)
class ImportAgentLibraryConfig:
    library_id: str
    display_name: str
    artifacts_dir: Path
    data_syn_bike_export_enabled: bool = False


@dataclass(frozen=True)
class ImportAgentManagedSourceConfig:
    source_id: str
    display_name: str
    source_root: Path
    library_id: str
    source_type: str = SOURCE_TYPE_FILESYSTEM_ARCHIVE
    enabled: bool = True
    attach_session_note_on_import: bool = False
    force_reprocess: bool = False


@dataclass(frozen=True)
class ImportAgentAppConfig:
    sources_root: Path
    libraries_root: Path
    libraries: tuple[ImportAgentLibraryConfig, ...] = ()
    sources: tuple[ImportAgentManagedSourceConfig, ...] = ()
    auto_start: bool = False


@dataclass(frozen=True)
class ProvisionedImportAgentLibrary:
    library_id: str
    display_name: str
    artifacts_dir: Path
    runs_dir: Path
    state_dir: Path
    bike_profiles_dir: Path
    preprocess_profiles_dir: Path
    event_schemas_dir: Path
    metadata_path: Path
    data_syn_bike_export_enabled: bool = False


@dataclass(frozen=True)
class ProvisionedImportAgentSource:
    source_id: str
    display_name: str
    source_type: str
    source_root: Path
    import_source_config_path: Path
    settings_dir: Path
    bike_dir: Path
    notes_dir: Path
    preprocess_profile_path: Path
    event_schema_path: Path
    bike_profile_path: Path
    session_note_template_path: Path
    bike_setup_preset_path: Path
    library_id: str
    artifacts_dir: Path
    attach_session_note_on_import: bool = False
    force_reprocess: bool = False


@dataclass(frozen=True)
class ProvisionedImportAgentAppSetup:
    app_config_path: Path
    app_config: ImportAgentAppConfig
    library: ProvisionedImportAgentLibrary
    source: ProvisionedImportAgentSource


@dataclass(frozen=True)
class AdoptedImportAgentWorkspace:
    app_config_path: Path
    app_config: ImportAgentAppConfig


@dataclass(frozen=True)
class ImportAgentWorkspaceSyncReport:
    added_libraries: tuple[str, ...] = ()
    updated_libraries: tuple[str, ...] = ()
    missing_libraries: tuple[str, ...] = ()
    added_sources: tuple[str, ...] = ()
    updated_sources: tuple[str, ...] = ()
    missing_sources: tuple[str, ...] = ()

    @property
    def has_changes(self) -> bool:
        return bool(
            self.added_libraries
            or self.updated_libraries
            or self.missing_libraries
            or self.added_sources
            or self.updated_sources
            or self.missing_sources
        )

    @property
    def has_syncable_changes(self) -> bool:
        return bool(
            self.added_libraries
            or self.updated_libraries
            or self.added_sources
            or self.updated_sources
        )


@dataclass(frozen=True)
class SyncedImportAgentWorkspace:
    app_config_path: Path
    app_config: ImportAgentAppConfig
    report: ImportAgentWorkspaceSyncReport


def default_import_agent_app_config_dir(
    *,
    platform: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    home: Optional[str | Path] = None,
) -> Path:
    resolved_platform = platform or sys.platform
    env_map = dict(os.environ if env is None else env)
    home_path = Path.home() if home is None else Path(home).expanduser()

    if resolved_platform.startswith("win"):
        local_app_data = env_map.get("LOCALAPPDATA")
        base_dir = Path(local_app_data).expanduser() if local_app_data else home_path / "AppData" / "Local"
        return (base_dir / DEFAULT_IMPORT_AGENT_VENDOR_DIRNAME / DEFAULT_IMPORT_AGENT_APP_DIRNAME).resolve()

    if resolved_platform == "darwin":
        return (
            home_path
            / "Library"
            / "Application Support"
            / DEFAULT_IMPORT_AGENT_VENDOR_DIRNAME
            / DEFAULT_IMPORT_AGENT_APP_DIRNAME
        ).resolve()

    xdg_config_home = env_map.get("XDG_CONFIG_HOME")
    base_dir = Path(xdg_config_home).expanduser() if xdg_config_home else home_path / ".config"
    return (base_dir / DEFAULT_IMPORT_AGENT_VENDOR_DIRNAME.lower() / DEFAULT_IMPORT_AGENT_APP_DIRNAME).resolve()


def default_import_agent_app_config_path(
    *,
    platform: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    home: Optional[str | Path] = None,
) -> Path:
    return default_import_agent_app_config_dir(platform=platform, env=env, home=home) / DEFAULT_IMPORT_AGENT_APP_CONFIG_FILENAME


def _is_directory_writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe_path = directory / ".bodaqs_import_agent_write_probe.tmp"
        probe_path.write_text("probe", encoding="utf-8")
        probe_path.unlink()
    except OSError:
        return False
    return True


def runtime_import_agent_app_config_path(
    *,
    preferred_dir: Optional[str | Path] = None,
    mode: str = IMPORT_AGENT_APP_CONFIG_MODE_AUTO,
    platform: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    home: Optional[str | Path] = None,
) -> Path:
    if mode not in {
        IMPORT_AGENT_APP_CONFIG_MODE_AUTO,
        IMPORT_AGENT_APP_CONFIG_MODE_PORTABLE,
        IMPORT_AGENT_APP_CONFIG_MODE_INSTALLED,
    }:
        raise ValueError(f"Unsupported import-agent app-config mode: {mode!r}")
    if mode == IMPORT_AGENT_APP_CONFIG_MODE_INSTALLED:
        return default_import_agent_app_config_path(platform=platform, env=env, home=home)
    if preferred_dir is not None:
        candidate_dir = Path(preferred_dir).expanduser().resolve()
        if _is_directory_writable(candidate_dir):
            return candidate_dir / DEFAULT_IMPORT_AGENT_APP_CONFIG_FILENAME
    return default_import_agent_app_config_path(platform=platform, env=env, home=home)


def make_import_agent_app_config(
    *,
    sources_root: str | Path,
    libraries_root: str | Path,
    libraries: Optional[Sequence[ImportAgentLibraryConfig]] = None,
    sources: Optional[Sequence[ImportAgentManagedSourceConfig]] = None,
    auto_start: bool = False,
) -> ImportAgentAppConfig:
    config = ImportAgentAppConfig(
        sources_root=_coerce_required_path(sources_root, field_name="sources_root"),
        libraries_root=_coerce_required_path(libraries_root, field_name="libraries_root"),
        libraries=tuple(libraries or ()),
        sources=tuple(sources or ()),
        auto_start=bool(auto_start),
    )
    validate_import_agent_app_config(config)
    return config


def validate_import_agent_app_config(config: ImportAgentAppConfig | Mapping[str, Any]) -> None:
    if isinstance(config, ImportAgentAppConfig):
        sources_root = config.sources_root
        libraries_root = config.libraries_root
        libraries = list(config.libraries)
        sources = list(config.sources)
        auto_start = config.auto_start
    elif isinstance(config, Mapping):
        parsed = parse_import_agent_app_config(config)
        sources_root = parsed.sources_root
        libraries_root = parsed.libraries_root
        libraries = list(parsed.libraries)
        sources = list(parsed.sources)
        auto_start = parsed.auto_start
    else:
        raise ValueError("Import agent app config must be a mapping or ImportAgentAppConfig")

    if not isinstance(sources_root, Path):
        raise ValueError("Import agent app config sources_root must be a Path")
    if not isinstance(libraries_root, Path):
        raise ValueError("Import agent app config libraries_root must be a Path")
    if not isinstance(auto_start, bool):
        raise ValueError("Import agent app config auto_start must be boolean")

    seen_library_ids: set[str] = set()
    for library in libraries:
        if not _optional_text(library.library_id):
            raise ValueError("Import agent library config must include a non-empty library_id")
        if not _optional_text(library.display_name):
            raise ValueError(f"Import agent library {library.library_id!r} must include a non-empty display_name")
        if library.library_id in seen_library_ids:
            raise ValueError(f"Duplicate import agent library id: {library.library_id!r}")
        if not isinstance(library.data_syn_bike_export_enabled, bool):
            raise ValueError(
                f"Import agent library {library.library_id!r} data_syn_bike_export_enabled must be boolean"
            )
        seen_library_ids.add(library.library_id)

    seen_source_ids: set[str] = set()
    for source in sources:
        if not _optional_text(source.source_id):
            raise ValueError("Import agent managed source config must include a non-empty source_id")
        if not _optional_text(source.display_name):
            raise ValueError(f"Import agent source {source.source_id!r} must include a non-empty display_name")
        if source.source_id in seen_source_ids:
            raise ValueError(f"Duplicate import agent source id: {source.source_id!r}")
        seen_source_ids.add(source.source_id)
        if source.library_id not in seen_library_ids:
            raise ValueError(
                f"Import agent source {source.source_id!r} references unknown library_id {source.library_id!r}"
            )
        normalize_import_source_type(source.source_type)
        if not isinstance(source.attach_session_note_on_import, bool):
            raise ValueError(
                f"Import agent source {source.source_id!r} attach_session_note_on_import must be boolean"
            )
        if not isinstance(source.force_reprocess, bool):
            raise ValueError(
                f"Import agent source {source.source_id!r} force_reprocess must be boolean"
            )


def import_agent_app_config_to_jsonable(config: ImportAgentAppConfig) -> dict[str, Any]:
    validate_import_agent_app_config(config)
    return {
        "schema": IMPORT_AGENT_APP_SCHEMA,
        "version": IMPORT_AGENT_APP_VERSION,
        "sources_root": str(config.sources_root),
        "libraries_root": str(config.libraries_root),
        "auto_start": config.auto_start,
        "libraries": [
            {
                "library_id": library.library_id,
                "display_name": library.display_name,
                "artifacts_dir": str(library.artifacts_dir),
                "data_syn_bike_export_enabled": bool(library.data_syn_bike_export_enabled),
            }
            for library in config.libraries
        ],
        "sources": [
            {
                "source_id": source.source_id,
                "display_name": source.display_name,
                "source_root": str(source.source_root),
                "library_id": source.library_id,
                "source_type": source.source_type,
                "enabled": source.enabled,
                "attach_session_note_on_import": source.attach_session_note_on_import,
                "force_reprocess": source.force_reprocess,
            }
            for source in config.sources
        ],
    }


def save_import_agent_app_config(
    config: ImportAgentAppConfig,
    path: str | Path,
    *,
    overwrite: bool = True,
) -> Path:
    out_path = Path(path).expanduser().resolve()
    _write_json(out_path, import_agent_app_config_to_jsonable(config), overwrite=overwrite)
    return out_path


def parse_import_agent_app_config(value: Mapping[str, Any] | str | bytes | Path) -> ImportAgentAppConfig:
    if isinstance(value, Mapping):
        obj = dict(value)
    else:
        if isinstance(value, Path):
            text = value.read_text(encoding="utf-8")
        elif isinstance(value, bytes):
            text = value.decode("utf-8")
        elif isinstance(value, str):
            candidate = Path(value)
            text = candidate.read_text(encoding="utf-8") if candidate.exists() else value
        else:
            raise TypeError("Import agent app config must be a mapping, JSON text/bytes, or a path")
        obj = json.loads(text)

    if not isinstance(obj, Mapping):
        raise ValueError("Import agent app config must be a JSON object")
    if obj.get("schema") != IMPORT_AGENT_APP_SCHEMA:
        raise ValueError(
            f"Unexpected import agent app config schema: {obj.get('schema')!r} "
            f"(expected {IMPORT_AGENT_APP_SCHEMA!r})"
        )
    if int(obj.get("version", -1)) != IMPORT_AGENT_APP_VERSION:
        raise ValueError(
            f"Unexpected import agent app config version: {obj.get('version')!r} "
            f"(expected {IMPORT_AGENT_APP_VERSION})"
        )

    libraries: list[ImportAgentLibraryConfig] = []
    for item in obj.get("libraries", []):
        if not isinstance(item, Mapping):
            raise ValueError("Import agent app config libraries entries must be objects")
        artifacts_dir = _coerce_required_path(
            str(item.get("artifacts_dir") or ""),
            field_name="libraries[].artifacts_dir",
        )
        data_syn_bike_export_enabled = item.get("data_syn_bike_export_enabled")
        if data_syn_bike_export_enabled is None:
            data_syn_bike_export_enabled = _library_metadata_data_syn_bike_export_enabled(artifacts_dir)
        libraries.append(
            ImportAgentLibraryConfig(
                library_id=str(item.get("library_id") or "").strip(),
                display_name=str(item.get("display_name") or "").strip(),
                artifacts_dir=artifacts_dir,
                data_syn_bike_export_enabled=bool(data_syn_bike_export_enabled),
            )
        )

    sources: list[ImportAgentManagedSourceConfig] = []
    for item in obj.get("sources", []):
        if not isinstance(item, Mapping):
            raise ValueError("Import agent app config sources entries must be objects")
        source_root = _coerce_required_path(
            str(item.get("source_root") or ""),
            field_name="sources[].source_root",
        )
        sources.append(
            ImportAgentManagedSourceConfig(
                source_id=str(item.get("source_id") or "").strip(),
                display_name=str(item.get("display_name") or "").strip(),
                source_root=source_root,
                library_id=str(item.get("library_id") or "").strip(),
                source_type=normalize_import_source_type(item.get("source_type")),
                enabled=bool(item.get("enabled", True)),
                attach_session_note_on_import=bool(
                    item.get(
                        "attach_session_note_on_import",
                        _source_session_note_attach_enabled(source_root),
                    )
                ),
                force_reprocess=bool(
                    item.get(
                        "force_reprocess",
                        _source_force_reprocess_enabled(source_root),
                    )
                ),
            )
        )

    return make_import_agent_app_config(
        sources_root=_coerce_required_path(str(obj.get("sources_root") or ""), field_name="sources_root"),
        libraries_root=_coerce_required_path(str(obj.get("libraries_root") or ""), field_name="libraries_root"),
        libraries=libraries,
        sources=sources,
        auto_start=bool(obj.get("auto_start", False)),
    )


def load_import_agent_app_config(path: str | Path) -> ImportAgentAppConfig:
    return parse_import_agent_app_config(Path(path).expanduser().resolve())


def _merge_managed_app_entries(
    base_config: ImportAgentAppConfig,
    *,
    library: ProvisionedImportAgentLibrary,
    source: ProvisionedImportAgentSource,
    auto_start: Optional[bool] = None,
) -> ImportAgentAppConfig:
    if base_config.sources_root != source.source_root.parent:
        raise ValueError(
            "Existing import agent app config sources_root does not match the requested source root parent: "
            f"{base_config.sources_root} != {source.source_root.parent}"
        )
    library_workspace = library_workspace_root(library.artifacts_dir)
    if base_config.libraries_root != library_workspace:
        raise ValueError(
            "Existing import agent app config libraries_root does not match the requested library root: "
            f"{base_config.libraries_root} != {library_workspace}"
        )

    library_entries: dict[str, ImportAgentLibraryConfig] = {
        item.library_id: item for item in base_config.libraries
    }
    library_entries[library.library_id] = ImportAgentLibraryConfig(
        library_id=library.library_id,
        display_name=library.display_name,
        artifacts_dir=library.artifacts_dir,
        data_syn_bike_export_enabled=library.data_syn_bike_export_enabled,
    )

    source_entries: dict[str, ImportAgentManagedSourceConfig] = {
        item.source_id: item for item in base_config.sources
    }
    source_entries[source.source_id] = ImportAgentManagedSourceConfig(
        source_id=source.source_id,
        display_name=source.display_name,
        source_root=source.source_root,
        library_id=library.library_id,
        source_type=source.source_type,
        enabled=True,
        attach_session_note_on_import=source.attach_session_note_on_import,
        force_reprocess=source.force_reprocess,
    )

    return make_import_agent_app_config(
        sources_root=base_config.sources_root,
        libraries_root=base_config.libraries_root,
        libraries=sorted(library_entries.values(), key=lambda item: item.library_id),
        sources=sorted(source_entries.values(), key=lambda item: item.source_id),
        auto_start=base_config.auto_start if auto_start is None else bool(auto_start),
    )


def managed_import_agent_source_roots(
    config: ImportAgentAppConfig,
    *,
    enabled_only: bool = False,
) -> list[Path]:
    validate_import_agent_app_config(config)
    return [
        source.source_root
        for source in config.sources
        if (not enabled_only) or source.enabled
    ]


def load_managed_import_source_configs(
    config: ImportAgentAppConfig,
    *,
    enabled_only: bool = False,
) -> list[Any]:
    """Load managed sources with library paths resolved from local app config."""
    from bodaqs_analysis.import_agent import load_import_source_config

    validate_import_agent_app_config(config)
    libraries_by_id = {library.library_id: library for library in config.libraries}
    resolved_sources: list[Any] = []
    for managed_source in config.sources:
        if enabled_only and not managed_source.enabled:
            continue
        library = libraries_by_id.get(managed_source.library_id)
        if library is None:
            raise ValueError(
                f"Import agent source {managed_source.source_id!r} references unknown "
                f"library_id {managed_source.library_id!r}"
            )
        source_config = load_import_source_config(managed_source.source_root)
        if source_config.source_id != managed_source.source_id:
            raise ValueError(
                f"Managed source id {managed_source.source_id!r} does not match "
                f"{source_config.config_path}: {source_config.source_id!r}"
            )
        return_source_type = normalize_import_source_type(source_config.source_type)
        if return_source_type != normalize_import_source_type(managed_source.source_type):
            raise ValueError(
                f"Managed source {managed_source.source_id!r} type {managed_source.source_type!r} "
                f"does not match {source_config.config_path}: {source_config.source_type!r}"
            )
        resolved_sources.append(
            replace(
                source_config,
                artifacts_dir=library.artifacts_dir,
                library_id=managed_source.library_id,
            )
        )
    return resolved_sources


def validate_managed_import_sources(
    config: ImportAgentAppConfig,
    *,
    enabled_only: bool = False,
) -> list[dict[str, Any]]:
    from bodaqs_analysis.import_agent import ImportSourceRunner

    results: list[dict[str, Any]] = []
    for source in load_managed_import_source_configs(config, enabled_only=enabled_only):
        runner = ImportSourceRunner(source)
        errors, warnings = runner.validate()
        results.append(
            {
                "source_id": source.source_id,
                "source_type": source.source_type,
                "config_path": str(source.config_path),
                "errors": errors,
                "warnings": warnings,
            }
        )
    return results


def discover_import_agent_libraries(libraries_root: str | Path) -> list[ImportAgentLibraryConfig]:
    root = _coerce_required_path(libraries_root, field_name="libraries_root")
    if not root.exists():
        raise FileNotFoundError(f"Libraries root does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Libraries root is not a directory: {root}")

    libraries: list[ImportAgentLibraryConfig] = []
    seen_ids: set[str] = set()
    for metadata_path in _iter_import_agent_library_definition_paths(root):
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError(f"Library definition must be a JSON object: {metadata_path}")
        if payload.get("schema") != IMPORT_AGENT_LIBRARY_SCHEMA:
            raise ValueError(
                f"Unexpected library definition schema in {metadata_path}: {payload.get('schema')!r}"
            )
        if int(payload.get("version", -1)) != IMPORT_AGENT_LIBRARY_VERSION:
            raise ValueError(
                f"Unexpected library definition version in {metadata_path}: {payload.get('version')!r}"
            )
        library_id = _optional_text(payload.get("library_id"))
        if library_id is None:
            raise ValueError(f"Library definition missing non-empty library_id: {metadata_path}")
        if library_id in seen_ids:
            raise ValueError(f"Duplicate library_id {library_id!r} under {root}")
        seen_ids.add(library_id)
        artifacts_dir = metadata_path.parent.resolve()
        libraries.append(
            ImportAgentLibraryConfig(
                library_id=library_id,
                display_name=_optional_text(payload.get("display_name"))
                or _display_name_from_slug(artifacts_dir.name, fallback=library_id),
                artifacts_dir=artifacts_dir,
                data_syn_bike_export_enabled=_library_metadata_data_syn_bike_export_enabled(artifacts_dir),
            )
        )
    return libraries


def _iter_import_agent_library_definition_paths(root: Path) -> list[Path]:
    candidates: list[Path] = []
    seen_paths: set[Path] = set()
    for search_root in (import_agent_libraries_dir(root), root):
        if not search_root.exists() or not search_root.is_dir():
            continue
        for metadata_path in sorted(search_root.glob("*/library_definition.json")):
            resolved = metadata_path.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            candidates.append(metadata_path)
    return candidates


def discover_import_agent_sources(
    sources_root: str | Path,
    *,
    known_library_ids: Optional[set[str]] = None,
) -> list[ImportAgentManagedSourceConfig]:
    from bodaqs_analysis.import_agent import load_import_source_config

    root = _coerce_required_path(sources_root, field_name="sources_root")
    if not root.exists():
        raise FileNotFoundError(f"Sources root does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Sources root is not a directory: {root}")

    candidate_paths: list[Path] = []
    root_config = root / DEFAULT_IMPORT_SOURCE_FILENAME
    if root_config.exists():
        candidate_paths.append(root_config)
    candidate_paths.extend(sorted(root.glob(f"*/{DEFAULT_IMPORT_SOURCE_FILENAME}")))

    sources: list[ImportAgentManagedSourceConfig] = []
    seen_ids: set[str] = set()
    for config_path in candidate_paths:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError(f"Import source config must be a JSON object: {config_path}")
        source_config = load_import_source_config(config_path)
        if source_config.source_id in seen_ids:
            raise ValueError(f"Duplicate source_id {source_config.source_id!r} under {root}")
        seen_ids.add(source_config.source_id)
        library_id = _optional_text(source_config.library_id)
        if library_id is None:
            raise ValueError(f"Import source is missing target library_id: {config_path}")
        if known_library_ids is not None and library_id not in known_library_ids:
            raise ValueError(
                f"Import source {source_config.source_id!r} references library_id {library_id!r}, "
                f"but that library was not found under the selected libraries root."
            )
        source_root = config_path.parent.resolve()
        sources.append(
            ImportAgentManagedSourceConfig(
                source_id=source_config.source_id,
                display_name=_optional_text(payload.get("display_name"))
                or _display_name_from_slug(source_root.name, fallback=source_config.source_id),
                source_root=source_root,
                library_id=library_id,
                source_type=source_config.source_type,
                enabled=True,
                attach_session_note_on_import=source_config.session_note.attach_on_import,
                force_reprocess=source_config.force_reprocess,
            )
        )
    return sources


def adopt_import_agent_existing_workspace(
    *,
    sources_root: str | Path,
    libraries_root: str | Path,
    app_config_path: Optional[str | Path] = None,
    auto_start: bool = False,
) -> AdoptedImportAgentWorkspace:
    resolved_sources_root = _coerce_required_path(sources_root, field_name="sources_root")
    resolved_libraries_root = _coerce_required_path(libraries_root, field_name="libraries_root")
    resolved_app_config_path = (
        default_import_agent_app_config_path()
        if app_config_path is None
        else _coerce_required_path(app_config_path, field_name="app_config_path")
    )

    libraries = discover_import_agent_libraries(resolved_libraries_root)
    if not libraries:
        raise ValueError(f"No BODAQS import-manager libraries found under: {resolved_libraries_root}")
    sources = discover_import_agent_sources(
        resolved_sources_root,
        known_library_ids={library.library_id for library in libraries},
    )
    if not sources:
        raise ValueError(f"No BODAQS import-manager sources found under: {resolved_sources_root}")

    app_config = make_import_agent_app_config(
        sources_root=resolved_sources_root,
        libraries_root=resolved_libraries_root,
        libraries=sorted(libraries, key=lambda item: item.library_id),
        sources=sorted(sources, key=lambda item: item.source_id),
        auto_start=auto_start,
    )
    save_import_agent_app_config(app_config, resolved_app_config_path, overwrite=True)
    return AdoptedImportAgentWorkspace(app_config_path=resolved_app_config_path, app_config=app_config)


def _library_config_matches(lhs: ImportAgentLibraryConfig, rhs: ImportAgentLibraryConfig) -> bool:
    return (
        lhs.display_name == rhs.display_name
        and lhs.artifacts_dir == rhs.artifacts_dir
        and lhs.data_syn_bike_export_enabled == rhs.data_syn_bike_export_enabled
    )


def _source_config_matches_for_workspace_sync(
    lhs: ImportAgentManagedSourceConfig,
    rhs: ImportAgentManagedSourceConfig,
) -> bool:
    return (
        lhs.display_name == rhs.display_name
        and lhs.source_root == rhs.source_root
        and lhs.library_id == rhs.library_id
        and lhs.source_type == rhs.source_type
        and lhs.attach_session_note_on_import == rhs.attach_session_note_on_import
        and lhs.force_reprocess == rhs.force_reprocess
    )


def check_import_agent_workspace_sync(
    config: ImportAgentAppConfig | str | Path,
) -> ImportAgentWorkspaceSyncReport:
    current = load_import_agent_app_config(config) if isinstance(config, (str, Path)) else config
    validate_import_agent_app_config(current)

    discovered_libraries = discover_import_agent_libraries(current.libraries_root)
    discovered_sources = discover_import_agent_sources(
        current.sources_root,
        known_library_ids={library.library_id for library in discovered_libraries},
    )

    current_libraries = {library.library_id: library for library in current.libraries}
    current_sources = {source.source_id: source for source in current.sources}
    discovered_library_map = {library.library_id: library for library in discovered_libraries}
    discovered_source_map = {source.source_id: source for source in discovered_sources}

    added_libraries: list[str] = []
    updated_libraries: list[str] = []
    missing_libraries: list[str] = []
    for library_id, discovered in discovered_library_map.items():
        existing = current_libraries.get(library_id)
        if existing is None:
            added_libraries.append(library_id)
        elif not _library_config_matches(existing, discovered):
            updated_libraries.append(library_id)
    for library_id in current_libraries:
        if library_id not in discovered_library_map:
            missing_libraries.append(library_id)

    added_sources: list[str] = []
    updated_sources: list[str] = []
    missing_sources: list[str] = []
    for source_id, discovered in discovered_source_map.items():
        existing = current_sources.get(source_id)
        if existing is None:
            added_sources.append(source_id)
        elif not _source_config_matches_for_workspace_sync(existing, discovered):
            updated_sources.append(source_id)
    for source_id in current_sources:
        if source_id not in discovered_source_map:
            missing_sources.append(source_id)

    return ImportAgentWorkspaceSyncReport(
        added_libraries=tuple(sorted(added_libraries)),
        updated_libraries=tuple(sorted(updated_libraries)),
        missing_libraries=tuple(sorted(missing_libraries)),
        added_sources=tuple(sorted(added_sources)),
        updated_sources=tuple(sorted(updated_sources)),
        missing_sources=tuple(sorted(missing_sources)),
    )


def sync_import_agent_workspace_from_roots(
    app_config_path: str | Path,
) -> SyncedImportAgentWorkspace:
    config_path = _coerce_required_path(app_config_path, field_name="app_config_path")
    current = load_import_agent_app_config(config_path)
    report = check_import_agent_workspace_sync(current)

    if not report.has_syncable_changes:
        return SyncedImportAgentWorkspace(
            app_config_path=config_path,
            app_config=current,
            report=report,
        )

    discovered_libraries = discover_import_agent_libraries(current.libraries_root)
    discovered_sources = discover_import_agent_sources(
        current.sources_root,
        known_library_ids={library.library_id for library in discovered_libraries},
    )
    discovered_library_map = {library.library_id: library for library in discovered_libraries}
    discovered_source_map = {source.source_id: source for source in discovered_sources}

    library_entries: dict[str, ImportAgentLibraryConfig] = {
        library.library_id: library for library in current.libraries
    }
    for library_id in (*report.added_libraries, *report.updated_libraries):
        library_entries[library_id] = discovered_library_map[library_id]

    source_entries: dict[str, ImportAgentManagedSourceConfig] = {
        source.source_id: source for source in current.sources
    }
    for source_id in (*report.added_sources, *report.updated_sources):
        discovered = discovered_source_map[source_id]
        existing = source_entries.get(source_id)
        source_entries[source_id] = (
            discovered
            if existing is None
            else replace(discovered, enabled=existing.enabled)
        )

    updated = make_import_agent_app_config(
        sources_root=current.sources_root,
        libraries_root=current.libraries_root,
        libraries=sorted(library_entries.values(), key=lambda item: item.library_id),
        sources=sorted(source_entries.values(), key=lambda item: item.source_id),
        auto_start=current.auto_start,
    )
    save_import_agent_app_config(updated, config_path, overwrite=True)
    return SyncedImportAgentWorkspace(
        app_config_path=config_path,
        app_config=updated,
        report=report,
    )


def update_import_agent_source_enabled(
    app_config_path: str | Path,
    *,
    source_id: str,
    enabled: bool,
) -> ImportAgentAppConfig:
    config_path = _coerce_required_path(app_config_path, field_name="app_config_path")
    config = load_import_agent_app_config(config_path)

    updated_sources: list[ImportAgentManagedSourceConfig] = []
    found = False
    for source in config.sources:
        if source.source_id == source_id:
            updated_sources.append(
                ImportAgentManagedSourceConfig(
                    source_id=source.source_id,
                    display_name=source.display_name,
                    source_root=source.source_root,
                    library_id=source.library_id,
                    source_type=source.source_type,
                    enabled=bool(enabled),
                    attach_session_note_on_import=source.attach_session_note_on_import,
                    force_reprocess=source.force_reprocess,
                )
            )
            found = True
        else:
            updated_sources.append(source)

    if not found:
        raise ValueError(f"Unknown managed import-agent source_id: {source_id!r}")

    updated = make_import_agent_app_config(
        sources_root=config.sources_root,
        libraries_root=config.libraries_root,
        libraries=config.libraries,
        sources=updated_sources,
        auto_start=config.auto_start,
    )
    save_import_agent_app_config(updated, config_path, overwrite=True)
    return updated


def update_import_agent_source_session_note_attach_enabled(
    app_config_path: str | Path,
    *,
    source_id: str,
    enabled: bool,
) -> ImportAgentAppConfig:
    config_path = _coerce_required_path(app_config_path, field_name="app_config_path")
    config = load_import_agent_app_config(config_path)

    updated_sources: list[ImportAgentManagedSourceConfig] = []
    found: Optional[ImportAgentManagedSourceConfig] = None
    for source in config.sources:
        if source.source_id == source_id:
            found = source
            updated_sources.append(
                ImportAgentManagedSourceConfig(
                    source_id=source.source_id,
                    display_name=source.display_name,
                    source_root=source.source_root,
                    library_id=source.library_id,
                    source_type=source.source_type,
                    enabled=source.enabled,
                    attach_session_note_on_import=bool(enabled),
                    force_reprocess=source.force_reprocess,
                )
            )
        else:
            updated_sources.append(source)

    if found is None:
        raise ValueError(f"Unknown managed import-agent source_id: {source_id!r}")

    _write_source_session_note_attach_enabled(found.source_root, enabled=bool(enabled))
    updated = make_import_agent_app_config(
        sources_root=config.sources_root,
        libraries_root=config.libraries_root,
        libraries=config.libraries,
        sources=updated_sources,
        auto_start=config.auto_start,
    )
    save_import_agent_app_config(updated, config_path, overwrite=True)
    return updated


def update_import_agent_source_force_reprocess_enabled(
    app_config_path: str | Path,
    *,
    source_id: str,
    enabled: bool,
) -> ImportAgentAppConfig:
    config_path = _coerce_required_path(app_config_path, field_name="app_config_path")
    config = load_import_agent_app_config(config_path)

    updated_sources: list[ImportAgentManagedSourceConfig] = []
    found: Optional[ImportAgentManagedSourceConfig] = None
    for source in config.sources:
        if source.source_id == source_id:
            found = source
            updated_sources.append(
                ImportAgentManagedSourceConfig(
                    source_id=source.source_id,
                    display_name=source.display_name,
                    source_root=source.source_root,
                    library_id=source.library_id,
                    source_type=source.source_type,
                    enabled=source.enabled,
                    attach_session_note_on_import=source.attach_session_note_on_import,
                    force_reprocess=bool(enabled),
                )
            )
        else:
            updated_sources.append(source)

    if found is None:
        raise ValueError(f"Unknown managed import-agent source_id: {source_id!r}")

    _write_source_force_reprocess_enabled(found.source_root, enabled=bool(enabled))
    updated = make_import_agent_app_config(
        sources_root=config.sources_root,
        libraries_root=config.libraries_root,
        libraries=config.libraries,
        sources=updated_sources,
        auto_start=config.auto_start,
    )
    save_import_agent_app_config(updated, config_path, overwrite=True)
    return updated


def update_import_agent_source_library(
    app_config_path: str | Path,
    *,
    source_id: str,
    library_id: str,
) -> ImportAgentAppConfig:
    config_path = _coerce_required_path(app_config_path, field_name="app_config_path")
    config = load_import_agent_app_config(config_path)
    target_library = next((library for library in config.libraries if library.library_id == library_id), None)
    if target_library is None:
        raise ValueError(f"Unknown managed import-agent library_id: {library_id!r}")

    updated_sources: list[ImportAgentManagedSourceConfig] = []
    found: Optional[ImportAgentManagedSourceConfig] = None
    for source in config.sources:
        if source.source_id == source_id:
            found = source
            updated_sources.append(
                ImportAgentManagedSourceConfig(
                    source_id=source.source_id,
                    display_name=source.display_name,
                    source_root=source.source_root,
                    library_id=target_library.library_id,
                    source_type=source.source_type,
                    enabled=source.enabled,
                    attach_session_note_on_import=source.attach_session_note_on_import,
                    force_reprocess=source.force_reprocess,
                )
            )
        else:
            updated_sources.append(source)

    if found is None:
        raise ValueError(f"Unknown managed import-agent source_id: {source_id!r}")

    _write_source_target_library(
        found.source_root,
        library_id=target_library.library_id,
        artifacts_dir=target_library.artifacts_dir,
    )
    updated = make_import_agent_app_config(
        sources_root=config.sources_root,
        libraries_root=config.libraries_root,
        libraries=config.libraries,
        sources=updated_sources,
        auto_start=config.auto_start,
    )
    save_import_agent_app_config(updated, config_path, overwrite=True)
    return updated


def update_import_agent_source_bike_profile(
    app_config_path: str | Path,
    *,
    source_id: str,
    bike_profile_path: str | Path,
) -> ImportAgentAppConfig:
    config_path = _coerce_required_path(app_config_path, field_name="app_config_path")
    config = load_import_agent_app_config(config_path)
    found = next((source for source in config.sources if source.source_id == source_id), None)
    if found is None:
        raise ValueError(f"Unknown managed import-agent source_id: {source_id!r}")

    resolved_profile_path, _profile = _load_bike_profile_file(bike_profile_path)
    _write_source_bike_profile_path(found.source_root, bike_profile_path=resolved_profile_path)

    # The app-level source record stores library assignment and status flags only.
    # Reloading keeps callers in sync while preserving the source record shape.
    updated = load_import_agent_app_config(config_path)
    save_import_agent_app_config(updated, config_path, overwrite=True)
    return updated


def update_import_agent_source_preprocess_profile(
    app_config_path: str | Path,
    *,
    source_id: str,
    preprocess_profile_path: str | Path,
) -> ImportAgentAppConfig:
    config_path = _coerce_required_path(app_config_path, field_name="app_config_path")
    config = load_import_agent_app_config(config_path)
    found = next((source for source in config.sources if source.source_id == source_id), None)
    if found is None:
        raise ValueError(f"Unknown managed import-agent source_id: {source_id!r}")

    resolved_profile_path, _profile = _load_preprocess_profile_file(preprocess_profile_path)
    _write_source_preprocess_profile_path(
        found.source_root,
        preprocess_profile_path=resolved_profile_path,
    )

    # The app-level source record stores library assignment and status flags only.
    # Reloading keeps callers in sync while preserving the source record shape.
    updated = load_import_agent_app_config(config_path)
    save_import_agent_app_config(updated, config_path, overwrite=True)
    return updated


def update_import_agent_library_data_syn_bike_export_enabled(
    app_config_path: str | Path,
    *,
    library_id: str,
    enabled: bool,
) -> ImportAgentAppConfig:
    config_path = _coerce_required_path(app_config_path, field_name="app_config_path")
    config = load_import_agent_app_config(config_path)

    updated_libraries: list[ImportAgentLibraryConfig] = []
    found: Optional[ImportAgentLibraryConfig] = None
    for library in config.libraries:
        if library.library_id == library_id:
            found = library
            updated_libraries.append(
                ImportAgentLibraryConfig(
                    library_id=library.library_id,
                    display_name=library.display_name,
                    artifacts_dir=library.artifacts_dir,
                    data_syn_bike_export_enabled=bool(enabled),
                )
            )
        else:
            updated_libraries.append(library)

    if found is None:
        raise ValueError(f"Unknown managed import-agent library_id: {library_id!r}")

    metadata_path = found.artifacts_dir / "library_definition.json"
    existing_metadata = _read_json(metadata_path, {}) if metadata_path.exists() else {}
    existing_exports = existing_metadata.get("exports") if isinstance(existing_metadata, Mapping) else None
    existing_syn_export = (
        existing_exports.get("data_syn_bike")
        if isinstance(existing_exports, Mapping) and isinstance(existing_exports.get("data_syn_bike"), Mapping)
        else {}
    )
    payload = _library_metadata_payload(
        library_id=found.library_id,
        display_name=found.display_name,
        artifacts_dir=found.artifacts_dir,
        data_syn_bike_export_enabled=bool(enabled),
    )
    merged_syn_export = dict(payload["exports"]["data_syn_bike"])
    merged_syn_export.update({k: v for k, v in dict(existing_syn_export).items() if k != "enabled"})
    merged_syn_export["enabled"] = bool(enabled)
    payload["exports"]["data_syn_bike"] = merged_syn_export
    _write_json(
        metadata_path,
        payload,
        overwrite=True,
    )

    updated = make_import_agent_app_config(
        sources_root=config.sources_root,
        libraries_root=config.libraries_root,
        libraries=updated_libraries,
        sources=config.sources,
        auto_start=config.auto_start,
    )
    save_import_agent_app_config(updated, config_path, overwrite=True)
    return updated


def update_import_agent_source_session_naming(
    app_config_path: str | Path,
    *,
    source_id: str,
    enabled: bool,
    base: Optional[str] = None,
    index_start: int = 1,
    index_padding: int = 2,
) -> ImportAgentAppConfig:
    config_path = _coerce_required_path(app_config_path, field_name="app_config_path")
    config = load_import_agent_app_config(config_path)
    found = next((source for source in config.sources if source.source_id == source_id), None)
    if found is None:
        raise ValueError(f"Unknown managed import-agent source_id: {source_id!r}")

    _write_source_session_naming(
        found.source_root,
        enabled=bool(enabled),
        base=base,
        index_start=index_start,
        index_padding=index_padding,
    )
    save_import_agent_app_config(config, config_path, overwrite=True)
    return config


def update_import_agent_library_display_name(
    app_config_path: str | Path,
    *,
    library_id: str,
    display_name: str,
) -> ImportAgentAppConfig:
    new_display_name = _optional_text(display_name)
    if new_display_name is None:
        raise ValueError("display_name must be a non-empty string")
    config_path = _coerce_required_path(app_config_path, field_name="app_config_path")
    config = load_import_agent_app_config(config_path)

    updated_libraries: list[ImportAgentLibraryConfig] = []
    found: Optional[ImportAgentLibraryConfig] = None
    for library in config.libraries:
        if library.library_id == library_id:
            found = library
            updated_libraries.append(
                ImportAgentLibraryConfig(
                    library_id=library.library_id,
                    display_name=new_display_name,
                    artifacts_dir=library.artifacts_dir,
                    data_syn_bike_export_enabled=library.data_syn_bike_export_enabled,
                )
            )
        else:
            updated_libraries.append(library)

    if found is None:
        raise ValueError(f"Unknown managed import-agent library_id: {library_id!r}")

    metadata_path = found.artifacts_dir / "library_definition.json"
    if metadata_path.exists():
        metadata = _read_json(metadata_path, {})
        if isinstance(metadata, Mapping):
            updated_metadata = dict(metadata)
            updated_metadata["display_name"] = new_display_name
            _write_json(metadata_path, updated_metadata, overwrite=True)

    updated = make_import_agent_app_config(
        sources_root=config.sources_root,
        libraries_root=config.libraries_root,
        libraries=updated_libraries,
        sources=config.sources,
        auto_start=config.auto_start,
    )
    save_import_agent_app_config(updated, config_path, overwrite=True)
    return updated


def update_import_agent_source_display_name(
    app_config_path: str | Path,
    *,
    source_id: str,
    display_name: str,
) -> ImportAgentAppConfig:
    new_display_name = _optional_text(display_name)
    if new_display_name is None:
        raise ValueError("display_name must be a non-empty string")
    config_path = _coerce_required_path(app_config_path, field_name="app_config_path")
    config = load_import_agent_app_config(config_path)

    updated_sources: list[ImportAgentManagedSourceConfig] = []
    found: Optional[ImportAgentManagedSourceConfig] = None
    for source in config.sources:
        if source.source_id == source_id:
            found = source
            updated_sources.append(
                ImportAgentManagedSourceConfig(
                    source_id=source.source_id,
                    display_name=new_display_name,
                    source_root=source.source_root,
                    library_id=source.library_id,
                    source_type=source.source_type,
                    enabled=source.enabled,
                    attach_session_note_on_import=source.attach_session_note_on_import,
                    force_reprocess=source.force_reprocess,
                )
            )
        else:
            updated_sources.append(source)

    if found is None:
        raise ValueError(f"Unknown managed import-agent source_id: {source_id!r}")

    config_path_on_disk = found.source_root / DEFAULT_IMPORT_SOURCE_FILENAME
    if config_path_on_disk.exists():
        payload = _read_json(config_path_on_disk, {})
        if isinstance(payload, Mapping):
            updated_payload = dict(payload)
            updated_payload["display_name"] = new_display_name
            _write_json(config_path_on_disk, updated_payload, overwrite=True)

    updated = make_import_agent_app_config(
        sources_root=config.sources_root,
        libraries_root=config.libraries_root,
        libraries=config.libraries,
        sources=updated_sources,
        auto_start=config.auto_start,
    )
    save_import_agent_app_config(updated, config_path, overwrite=True)
    return updated


def update_import_agent_source_logger_wifi(
    app_config_path: str | Path,
    *,
    source_id: str,
    logger_wifi: LoggerWifiSourceConfig | Mapping[str, Any],
) -> ImportAgentAppConfig:
    config_path = _coerce_required_path(app_config_path, field_name="app_config_path")
    config = load_import_agent_app_config(config_path)
    found = next((source for source in config.sources if source.source_id == source_id), None)
    if found is None:
        raise ValueError(f"Unknown managed import-agent source_id: {source_id!r}")
    if found.source_type != SOURCE_TYPE_LOGGER_WIFI:
        raise ValueError(f"Managed source {source_id!r} is not a Wi-Fi logger source")

    logger_wifi_config = (
        logger_wifi
        if isinstance(logger_wifi, LoggerWifiSourceConfig)
        else parse_logger_wifi_source_config(logger_wifi)
    )
    _write_source_logger_wifi(found.source_root, logger_wifi=logger_wifi_config)

    # The app-level source record does not duplicate Wi-Fi connection details.
    # Reloading keeps the controller in sync while preserving source IDs/paths.
    updated = load_import_agent_app_config(config_path)
    save_import_agent_app_config(updated, config_path, overwrite=True)
    return updated


def remove_import_agent_source(
    app_config_path: str | Path,
    *,
    source_id: str,
    delete_files: bool = False,
) -> ImportAgentAppConfig:
    config_path = _coerce_required_path(app_config_path, field_name="app_config_path")
    config = load_import_agent_app_config(config_path)

    found = next((source for source in config.sources if source.source_id == source_id), None)
    if found is None:
        raise ValueError(f"Unknown managed import-agent source_id: {source_id!r}")
    updated_sources = [source for source in config.sources if source.source_id != source_id]
    if delete_files:
        _delete_directory_tree(
            found.source_root,
            expected_parent=config.sources_root,
            label=f"source folder for {source_id!r}",
        )

    updated = make_import_agent_app_config(
        sources_root=config.sources_root,
        libraries_root=config.libraries_root,
        libraries=config.libraries,
        sources=updated_sources,
        auto_start=config.auto_start,
    )
    save_import_agent_app_config(updated, config_path, overwrite=True)
    return updated


def remove_import_agent_library(
    app_config_path: str | Path,
    *,
    library_id: str,
    delete_files: bool = False,
) -> ImportAgentAppConfig:
    config_path = _coerce_required_path(app_config_path, field_name="app_config_path")
    config = load_import_agent_app_config(config_path)

    found = next((library for library in config.libraries if library.library_id == library_id), None)
    if found is None:
        raise ValueError(f"Unknown managed import-agent library_id: {library_id!r}")
    linked_sources = [source.source_id for source in config.sources if source.library_id == library_id]
    if linked_sources:
        source_list = ", ".join(sorted(linked_sources))
        raise ValueError(
            f"Cannot remove library {library_id!r} while source(s) still target it: {source_list}"
        )

    updated_libraries = [library for library in config.libraries if library.library_id != library_id]
    if delete_files:
        _delete_library_artifacts_dir(found.artifacts_dir, libraries_root=config.libraries_root)
    updated = make_import_agent_app_config(
        sources_root=config.sources_root,
        libraries_root=config.libraries_root,
        libraries=updated_libraries,
        sources=config.sources,
        auto_start=config.auto_start,
    )
    save_import_agent_app_config(updated, config_path, overwrite=True)
    return updated


def update_import_agent_app_auto_start(
    app_config_path: str | Path,
    *,
    enabled: bool,
) -> ImportAgentAppConfig:
    config_path = _coerce_required_path(app_config_path, field_name="app_config_path")
    config = load_import_agent_app_config(config_path)

    updated = make_import_agent_app_config(
        sources_root=config.sources_root,
        libraries_root=config.libraries_root,
        libraries=config.libraries,
        sources=config.sources,
        auto_start=bool(enabled),
    )
    save_import_agent_app_config(updated, config_path, overwrite=True)
    return updated


def provision_import_agent_library(
    libraries_root: str | Path,
    *,
    display_name: str,
    library_id: Optional[str] = None,
    directory_name: Optional[str] = None,
    data_syn_bike_export_enabled: bool = False,
    overwrite: bool = False,
) -> ProvisionedImportAgentLibrary:
    if not _optional_text(display_name):
        raise ValueError("display_name must be a non-empty string")

    resolved_root = Path(libraries_root).expanduser().resolve()
    safe_id = _safe_slug(library_id or display_name, fallback="library")
    safe_dirname = _safe_slug(directory_name or display_name, fallback=safe_id)
    artifacts_dir = import_agent_libraries_dir(resolved_root) / safe_dirname
    runs_dir = artifacts_dir / DEFAULT_LIBRARY_RUNS_DIRNAME
    state_dir = artifacts_dir / DEFAULT_LIBRARY_STATE_DIRNAME
    bike_profiles_dir = library_bike_profiles_dir(artifacts_dir)
    preprocess_profiles_dir = library_preprocess_profiles_dir(artifacts_dir)
    event_schemas_dir = library_event_schemas_dir(artifacts_dir)
    metadata_path = artifacts_dir / "library_definition.json"

    if artifacts_dir.exists() and not overwrite and any(artifacts_dir.iterdir()):
        raise FileExistsError(f"Import agent library directory already exists and is not empty: {artifacts_dir}")

    runs_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    bike_profiles_dir.mkdir(parents=True, exist_ok=True)
    preprocess_profiles_dir.mkdir(parents=True, exist_ok=True)
    event_schemas_dir.mkdir(parents=True, exist_ok=True)
    _ensure_library_default_bike_profile(artifacts_dir, overwrite=False)
    event_schema_path, _event_schema_payload = _ensure_library_default_event_schema(
        artifacts_dir,
        overwrite=False,
    )
    _ensure_library_default_preprocess_profile(
        artifacts_dir,
        event_schema_path=event_schema_path,
        overwrite=False,
    )
    _write_json(
        metadata_path,
        _library_metadata_payload(
            library_id=safe_id,
            display_name=str(display_name).strip(),
            artifacts_dir=artifacts_dir,
            data_syn_bike_export_enabled=bool(data_syn_bike_export_enabled),
        ),
        overwrite=overwrite,
    )

    return ProvisionedImportAgentLibrary(
        library_id=safe_id,
        display_name=str(display_name).strip(),
        artifacts_dir=artifacts_dir,
        runs_dir=runs_dir,
        state_dir=state_dir,
        bike_profiles_dir=bike_profiles_dir,
        preprocess_profiles_dir=preprocess_profiles_dir,
        event_schemas_dir=event_schemas_dir,
        metadata_path=metadata_path,
        data_syn_bike_export_enabled=bool(data_syn_bike_export_enabled),
    )


def provision_import_agent_source(
    source_root: str | Path,
    *,
    artifacts_dir: str | Path,
    source_id: Optional[str] = None,
    display_name: Optional[str] = None,
    library_id: str,
    source_type: str = SOURCE_TYPE_FILESYSTEM_ARCHIVE,
    logger_wifi: Optional[LoggerWifiSourceConfig | Mapping[str, Any]] = None,
    import_source_filename: str = DEFAULT_IMPORT_SOURCE_FILENAME,
    settings_dir_name: str = DEFAULT_SETTINGS_DIRNAME,
    bike_dir_name: str = DEFAULT_BIKE_DIRNAME,
    notes_dir_name: str = DEFAULT_NOTES_DIRNAME,
    logger_timezone: Optional[str] = None,
    run_tz_label: str = "LOCAL",
    poll_interval_s: float = 5.0,
    settle_time_s: float = 15.0,
    include_events: bool = True,
    include_metrics: bool = True,
    attach_session_note_on_import: bool = False,
    force_reprocess: bool = False,
    session_auto_name_enabled: bool = False,
    session_name_base: Optional[str] = None,
    session_name_index_start: int = 1,
    session_name_index_padding: int = 2,
    overwrite: bool = False,
) -> ProvisionedImportAgentSource:
    source_root_path = Path(source_root).expanduser().resolve()
    display = _optional_text(display_name) or source_root_path.name or "Default Source"
    safe_source_id = _safe_slug(source_id or display, fallback="source")
    normalized_source_type = normalize_import_source_type(source_type)
    artifacts_dir_path = Path(artifacts_dir).expanduser().resolve()
    logger_wifi_config: Optional[LoggerWifiSourceConfig] = None
    if normalized_source_type == SOURCE_TYPE_FILESYSTEM_ARCHIVE:
        if logger_wifi is not None:
            raise ValueError("logger_wifi config can only be used with source_type='logger_wifi'")
    else:
        if logger_wifi is None:
            raise ValueError("source_type='logger_wifi' requires a logger_wifi config")
        logger_wifi_config = (
            logger_wifi
            if isinstance(logger_wifi, LoggerWifiSourceConfig)
            else parse_logger_wifi_source_config(logger_wifi)
        )
    event_schema_path, _event_schema_payload = _ensure_library_default_event_schema(
        artifacts_dir_path,
        overwrite=False,
    )
    preprocess_profile_path, _preprocess_profile_payload = _ensure_library_default_preprocess_profile(
        artifacts_dir_path,
        event_schema_path=event_schema_path,
        overwrite=False,
    )
    bike_profile_path, bike_profile_payload = _ensure_library_default_bike_profile(
        artifacts_dir_path,
        overwrite=False,
    )
    note_template_asset = _discover_session_note_template_asset()
    setup_preset_asset = _discover_bike_setup_preset_asset()

    settings_dir = source_root_path / settings_dir_name
    bike_dir = source_root_path / bike_dir_name
    notes_dir = source_root_path / notes_dir_name
    fit_dir = source_root_path / "fit"
    inbox_dir = source_root_path / "inbox"
    done_dir = source_root_path / "done"
    failed_dir = source_root_path / "failed"
    staging_dir = source_root_path / "staging"
    import_source_config_path = source_root_path / import_source_filename
    session_note_template_path = notes_dir / "session_note_template.json"
    bike_setup_preset_path = notes_dir / "bike_setup_preset.json"

    for path in (notes_dir, fit_dir, inbox_dir, done_dir, failed_dir, staging_dir):
        path.mkdir(parents=True, exist_ok=True)

    _write_json(session_note_template_path, dict(note_template_asset.payload), overwrite=overwrite)
    setup_preset_payload = copy.deepcopy(dict(setup_preset_asset.payload))
    setup_preset_payload["bike_profile_id"] = bike_profile_payload.get("bike_profile_id")
    setup_values = setup_preset_payload.setdefault("values", {})
    if isinstance(setup_values, dict):
        if not _optional_text(setup_values.get("bike")):
            setup_values["bike"] = bike_profile_payload.get("display_name") or ""
    _write_json(bike_setup_preset_path, setup_preset_payload, overwrite=overwrite)
    import_source_payload: dict[str, Any] = {
        "schema": "bodaqs.import_source",
        "version": 1,
        "source_id": safe_source_id,
        "display_name": display,
        "source_type": normalized_source_type,
        "description": f"Provisioned BODAQS import source for {display}.",
        "library_id": str(library_id).strip(),
        "artifacts_dir": _portable_path_text(artifacts_dir_path, base_dir=source_root_path),
        "preprocess_profile_path": _portable_path_text(preprocess_profile_path, base_dir=source_root_path),
        "bike_profile_path": _portable_path_text(bike_profile_path, base_dir=source_root_path),
        "session_note": {
            "attach_on_import": bool(attach_session_note_on_import),
            "template_path": notes_dir_name,
            "setup_preset_path": notes_dir_name,
        },
        "fit_dir": "fit",
        "inbox_dir": "inbox",
        "done_dir": "done",
        "failed_dir": "failed",
        "staging_dir": "staging",
        "archive_patterns": ["*.zip", "*.bdq"],
        "run_tz_label": str(run_tz_label).strip() or "LOCAL",
        "poll_interval_s": float(poll_interval_s),
        "settle_time_s": float(settle_time_s),
        "force_reprocess": bool(force_reprocess),
    }
    if session_auto_name_enabled:
        import_source_payload["naming"] = {
            "session_description": _session_naming_payload(
                enabled=True,
                base=session_name_base,
                index_start=session_name_index_start,
                index_padding=session_name_index_padding,
            )
        }
    if logger_wifi_config is not None:
        import_source_payload["logger_wifi"] = logger_wifi_source_config_to_jsonable(logger_wifi_config)

    _write_json(import_source_config_path, import_source_payload, overwrite=overwrite)

    return ProvisionedImportAgentSource(
        source_id=safe_source_id,
        display_name=display,
        source_type=normalized_source_type,
        source_root=source_root_path,
        import_source_config_path=import_source_config_path,
        settings_dir=settings_dir,
        bike_dir=bike_dir,
        notes_dir=notes_dir,
        preprocess_profile_path=preprocess_profile_path,
        event_schema_path=event_schema_path,
        bike_profile_path=bike_profile_path,
        session_note_template_path=session_note_template_path,
        bike_setup_preset_path=bike_setup_preset_path,
        library_id=library_id,
        artifacts_dir=artifacts_dir_path,
        attach_session_note_on_import=bool(attach_session_note_on_import),
        force_reprocess=bool(force_reprocess),
    )


def provision_import_agent_app_setup(
    *,
    sources_root: str | Path,
    libraries_root: str | Path,
    library_display_name: str,
    source_display_name: str,
    app_config_path: Optional[str | Path] = None,
    library_id: Optional[str] = None,
    library_directory_name: Optional[str] = None,
    data_syn_bike_export_enabled: bool = False,
    source_id: Optional[str] = None,
    source_directory_name: Optional[str] = None,
    source_type: str = SOURCE_TYPE_FILESYSTEM_ARCHIVE,
    logger_wifi: Optional[LoggerWifiSourceConfig | Mapping[str, Any]] = None,
    logger_timezone: Optional[str] = None,
    run_tz_label: str = "LOCAL",
    poll_interval_s: float = 5.0,
    settle_time_s: float = 15.0,
    include_events: bool = True,
    include_metrics: bool = True,
    attach_session_note_on_import: bool = False,
    force_reprocess: bool = False,
    session_auto_name_enabled: bool = False,
    session_name_base: Optional[str] = None,
    session_name_index_start: int = 1,
    session_name_index_padding: int = 2,
    auto_start: bool = False,
    overwrite: bool = False,
) -> ProvisionedImportAgentAppSetup:
    resolved_sources_root = _coerce_required_path(sources_root, field_name="sources_root")
    resolved_libraries_root = _coerce_required_path(libraries_root, field_name="libraries_root")
    resolved_app_config_path = (
        default_import_agent_app_config_path()
        if app_config_path is None
        else _coerce_required_path(app_config_path, field_name="app_config_path")
    )

    resolved_sources_root.mkdir(parents=True, exist_ok=True)
    resolved_libraries_root.mkdir(parents=True, exist_ok=True)

    library = provision_import_agent_library(
        resolved_libraries_root,
        display_name=library_display_name,
        library_id=library_id,
        directory_name=library_directory_name,
        data_syn_bike_export_enabled=data_syn_bike_export_enabled,
        overwrite=overwrite,
    )

    source_dirname = _safe_slug(source_directory_name or source_display_name, fallback="source")
    source = provision_import_agent_source(
        resolved_sources_root / source_dirname,
        artifacts_dir=library.artifacts_dir,
        source_id=source_id,
        display_name=source_display_name,
        library_id=library.library_id,
        source_type=source_type,
        logger_wifi=logger_wifi,
        logger_timezone=logger_timezone,
        run_tz_label=run_tz_label,
        poll_interval_s=poll_interval_s,
        settle_time_s=settle_time_s,
        include_events=include_events,
        include_metrics=include_metrics,
        attach_session_note_on_import=attach_session_note_on_import,
        force_reprocess=force_reprocess,
        session_auto_name_enabled=session_auto_name_enabled,
        session_name_base=session_name_base,
        session_name_index_start=session_name_index_start,
        session_name_index_padding=session_name_index_padding,
        overwrite=overwrite,
    )

    if resolved_app_config_path.exists():
        existing_config = load_import_agent_app_config(resolved_app_config_path)
        app_config = _merge_managed_app_entries(
            existing_config,
            library=library,
            source=source,
            auto_start=auto_start,
        )
    else:
        app_config = make_import_agent_app_config(
            sources_root=resolved_sources_root,
            libraries_root=resolved_libraries_root,
            libraries=[
                ImportAgentLibraryConfig(
                    library_id=library.library_id,
                    display_name=library.display_name,
                    artifacts_dir=library.artifacts_dir,
                    data_syn_bike_export_enabled=library.data_syn_bike_export_enabled,
                )
            ],
            sources=[
                ImportAgentManagedSourceConfig(
                    source_id=source.source_id,
                    display_name=source.display_name,
                    source_root=source.source_root,
                    library_id=library.library_id,
                    source_type=source.source_type,
                    enabled=True,
                    attach_session_note_on_import=source.attach_session_note_on_import,
                    force_reprocess=source.force_reprocess,
                )
            ],
            auto_start=auto_start,
        )

    save_import_agent_app_config(app_config, resolved_app_config_path, overwrite=True)
    return ProvisionedImportAgentAppSetup(
        app_config_path=resolved_app_config_path,
        app_config=app_config,
        library=library,
        source=source,
    )


def provision_import_agent_library_for_app(
    app_config_path: str | Path,
    *,
    display_name: str,
    library_id: Optional[str] = None,
    directory_name: Optional[str] = None,
    data_syn_bike_export_enabled: bool = False,
    overwrite: bool = False,
) -> tuple[ImportAgentAppConfig, ProvisionedImportAgentLibrary]:
    config_path = _coerce_required_path(app_config_path, field_name="app_config_path")
    config = load_import_agent_app_config(config_path)

    library = provision_import_agent_library(
        config.libraries_root,
        display_name=display_name,
        library_id=library_id,
        directory_name=directory_name,
        data_syn_bike_export_enabled=data_syn_bike_export_enabled,
        overwrite=overwrite,
    )

    libraries = {item.library_id: item for item in config.libraries}
    libraries[library.library_id] = ImportAgentLibraryConfig(
        library_id=library.library_id,
        display_name=library.display_name,
        artifacts_dir=library.artifacts_dir,
        data_syn_bike_export_enabled=library.data_syn_bike_export_enabled,
    )
    updated = make_import_agent_app_config(
        sources_root=config.sources_root,
        libraries_root=config.libraries_root,
        libraries=sorted(libraries.values(), key=lambda item: item.library_id),
        sources=config.sources,
        auto_start=config.auto_start,
    )
    save_import_agent_app_config(updated, config_path, overwrite=True)
    return updated, library


def provision_import_agent_source_for_app(
    app_config_path: str | Path,
    *,
    library_id: str,
    display_name: str,
    source_id: Optional[str] = None,
    source_directory_name: Optional[str] = None,
    source_type: str = SOURCE_TYPE_FILESYSTEM_ARCHIVE,
    logger_wifi: Optional[LoggerWifiSourceConfig | Mapping[str, Any]] = None,
    logger_timezone: Optional[str] = None,
    run_tz_label: str = "LOCAL",
    poll_interval_s: float = 5.0,
    settle_time_s: float = 15.0,
    include_events: bool = True,
    include_metrics: bool = True,
    attach_session_note_on_import: bool = False,
    force_reprocess: bool = False,
    session_auto_name_enabled: bool = False,
    session_name_base: Optional[str] = None,
    session_name_index_start: int = 1,
    session_name_index_padding: int = 2,
    overwrite: bool = False,
) -> tuple[ImportAgentAppConfig, ProvisionedImportAgentSource]:
    config_path = _coerce_required_path(app_config_path, field_name="app_config_path")
    config = load_import_agent_app_config(config_path)
    library = next((item for item in config.libraries if item.library_id == library_id), None)
    if library is None:
        raise ValueError(f"Unknown managed import-agent library_id: {library_id!r}")

    source_dirname = _safe_slug(source_directory_name or display_name, fallback="source")
    source = provision_import_agent_source(
        config.sources_root / source_dirname,
        artifacts_dir=library.artifacts_dir,
        source_id=source_id,
        display_name=display_name,
        library_id=library.library_id,
        source_type=source_type,
        logger_wifi=logger_wifi,
        logger_timezone=logger_timezone,
        run_tz_label=run_tz_label,
        poll_interval_s=poll_interval_s,
        settle_time_s=settle_time_s,
        include_events=include_events,
        include_metrics=include_metrics,
        attach_session_note_on_import=attach_session_note_on_import,
        force_reprocess=force_reprocess,
        session_auto_name_enabled=session_auto_name_enabled,
        session_name_base=session_name_base,
        session_name_index_start=session_name_index_start,
        session_name_index_padding=session_name_index_padding,
        overwrite=overwrite,
    )

    sources = {item.source_id: item for item in config.sources}
    sources[source.source_id] = ImportAgentManagedSourceConfig(
        source_id=source.source_id,
        display_name=source.display_name,
        source_root=source.source_root,
        library_id=library.library_id,
        source_type=source.source_type,
        enabled=True,
        attach_session_note_on_import=source.attach_session_note_on_import,
        force_reprocess=source.force_reprocess,
    )
    updated = make_import_agent_app_config(
        sources_root=config.sources_root,
        libraries_root=config.libraries_root,
        libraries=config.libraries,
        sources=sorted(sources.values(), key=lambda item: item.source_id),
        auto_start=config.auto_start,
    )
    save_import_agent_app_config(updated, config_path, overwrite=True)
    return updated, source
