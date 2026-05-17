from __future__ import annotations

import copy
import json
import os
import re
import sys
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from .bike_profile import validate_bike_profile
from .preprocess_profile import normalize_preprocess_config_keys, validate_preprocess_profile
from .schema import parse_event_schema


IMPORT_AGENT_APP_SCHEMA = "bodaqs.import_agent_app"
IMPORT_AGENT_APP_VERSION = 1
IMPORT_AGENT_LIBRARY_SCHEMA = "bodaqs.import_agent_library"
IMPORT_AGENT_LIBRARY_VERSION = 1

DEFAULT_IMPORT_SOURCE_FILENAME = "import_source.json"
DEFAULT_SETTINGS_DIRNAME = "settings"
DEFAULT_BIKE_DIRNAME = "bike"
DEFAULT_LIBRARY_RUNS_DIRNAME = "runs"
DEFAULT_LIBRARY_STATE_DIRNAME = "library"
DEFAULT_IMPORT_AGENT_APP_CONFIG_FILENAME = "import_agent_app.json"
DEFAULT_IMPORT_AGENT_VENDOR_DIRNAME = "BODAQS"
DEFAULT_IMPORT_AGENT_APP_DIRNAME = "import-agent"
IMPORT_AGENT_APP_CONFIG_MODE_AUTO = "auto"
IMPORT_AGENT_APP_CONFIG_MODE_PORTABLE = "portable"
IMPORT_AGENT_APP_CONFIG_MODE_INSTALLED = "installed"

_ASSET_PACKAGE = "bodaqs_analysis.import_agent_assets"


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


def _safe_slug(value: str, *, fallback: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._").lower()
    return slug or fallback


def _write_json(path: Path, obj: Mapping[str, Any], *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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


@dataclass(frozen=True)
class ImportAgentLibraryConfig:
    library_id: str
    display_name: str
    artifacts_dir: Path


@dataclass(frozen=True)
class ImportAgentManagedSourceConfig:
    source_id: str
    display_name: str
    source_root: Path
    library_id: str
    enabled: bool = True


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
    metadata_path: Path


@dataclass(frozen=True)
class ProvisionedImportAgentSource:
    source_id: str
    display_name: str
    source_root: Path
    import_source_config_path: Path
    settings_dir: Path
    bike_dir: Path
    preprocess_profile_path: Path
    event_schema_path: Path
    bike_profile_path: Path
    library_id: str
    artifacts_dir: Path


@dataclass(frozen=True)
class ProvisionedImportAgentAppSetup:
    app_config_path: Path
    app_config: ImportAgentAppConfig
    library: ProvisionedImportAgentLibrary
    source: ProvisionedImportAgentSource


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
            }
            for library in config.libraries
        ],
        "sources": [
            {
                "source_id": source.source_id,
                "display_name": source.display_name,
                "source_root": str(source.source_root),
                "library_id": source.library_id,
                "enabled": source.enabled,
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
        libraries.append(
            ImportAgentLibraryConfig(
                library_id=str(item.get("library_id") or "").strip(),
                display_name=str(item.get("display_name") or "").strip(),
                artifacts_dir=_coerce_required_path(
                    str(item.get("artifacts_dir") or ""),
                    field_name="libraries[].artifacts_dir",
                ),
            )
        )

    sources: list[ImportAgentManagedSourceConfig] = []
    for item in obj.get("sources", []):
        if not isinstance(item, Mapping):
            raise ValueError("Import agent app config sources entries must be objects")
        sources.append(
            ImportAgentManagedSourceConfig(
                source_id=str(item.get("source_id") or "").strip(),
                display_name=str(item.get("display_name") or "").strip(),
                source_root=_coerce_required_path(
                    str(item.get("source_root") or ""),
                    field_name="sources[].source_root",
                ),
                library_id=str(item.get("library_id") or "").strip(),
                enabled=bool(item.get("enabled", True)),
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
    if base_config.libraries_root != library.artifacts_dir.parent:
        raise ValueError(
            "Existing import agent app config libraries_root does not match the requested library root: "
            f"{base_config.libraries_root} != {library.artifacts_dir.parent}"
        )

    library_entries: dict[str, ImportAgentLibraryConfig] = {
        item.library_id: item for item in base_config.libraries
    }
    library_entries[library.library_id] = ImportAgentLibraryConfig(
        library_id=library.library_id,
        display_name=library.display_name,
        artifacts_dir=library.artifacts_dir,
    )

    source_entries: dict[str, ImportAgentManagedSourceConfig] = {
        item.source_id: item for item in base_config.sources
    }
    source_entries[source.source_id] = ImportAgentManagedSourceConfig(
        source_id=source.source_id,
        display_name=source.display_name,
        source_root=source.source_root,
        library_id=library.library_id,
        enabled=True,
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
                    enabled=bool(enabled),
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
    overwrite: bool = False,
) -> ProvisionedImportAgentLibrary:
    if not _optional_text(display_name):
        raise ValueError("display_name must be a non-empty string")

    resolved_root = Path(libraries_root).expanduser().resolve()
    safe_id = _safe_slug(library_id or display_name, fallback="library")
    safe_dirname = _safe_slug(directory_name or display_name, fallback=safe_id)
    artifacts_dir = resolved_root / safe_dirname
    runs_dir = artifacts_dir / DEFAULT_LIBRARY_RUNS_DIRNAME
    state_dir = artifacts_dir / DEFAULT_LIBRARY_STATE_DIRNAME
    metadata_path = artifacts_dir / "library_definition.json"

    if artifacts_dir.exists() and not overwrite and any(artifacts_dir.iterdir()):
        raise FileExistsError(f"Import agent library directory already exists and is not empty: {artifacts_dir}")

    runs_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        metadata_path,
        {
            "schema": IMPORT_AGENT_LIBRARY_SCHEMA,
            "version": IMPORT_AGENT_LIBRARY_VERSION,
            "library_id": safe_id,
            "display_name": str(display_name).strip(),
            "artifacts_dir": str(artifacts_dir),
        },
        overwrite=overwrite,
    )

    return ProvisionedImportAgentLibrary(
        library_id=safe_id,
        display_name=str(display_name).strip(),
        artifacts_dir=artifacts_dir,
        runs_dir=runs_dir,
        state_dir=state_dir,
        metadata_path=metadata_path,
    )


def provision_import_agent_source(
    source_root: str | Path,
    *,
    artifacts_dir: str | Path,
    source_id: Optional[str] = None,
    display_name: Optional[str] = None,
    library_id: str,
    import_source_filename: str = DEFAULT_IMPORT_SOURCE_FILENAME,
    settings_dir_name: str = DEFAULT_SETTINGS_DIRNAME,
    bike_dir_name: str = DEFAULT_BIKE_DIRNAME,
    logger_timezone: Optional[str] = None,
    run_tz_label: str = "LOCAL",
    poll_interval_s: float = 5.0,
    settle_time_s: float = 15.0,
    include_events: bool = True,
    include_metrics: bool = True,
    force_reprocess: bool = False,
    overwrite: bool = False,
) -> ProvisionedImportAgentSource:
    source_root_path = Path(source_root).expanduser().resolve()
    display = _optional_text(display_name) or source_root_path.name or "Default Source"
    safe_source_id = _safe_slug(source_id or display, fallback="source")
    artifacts_dir_path = Path(artifacts_dir).expanduser().resolve()
    preprocess_asset = _discover_preprocess_profile_asset()
    schema_asset = _discover_single_schema_asset()
    bike_asset = _discover_bike_profile_asset()

    settings_dir = source_root_path / settings_dir_name
    bike_dir = source_root_path / bike_dir_name
    inbox_dir = source_root_path / "inbox"
    done_dir = source_root_path / "done"
    failed_dir = source_root_path / "failed"
    staging_dir = source_root_path / "staging"
    import_source_config_path = source_root_path / import_source_filename
    preprocess_profile_path = settings_dir / "preprocess_profile.json"
    event_schema_path = settings_dir / "event_schema.yaml"
    bike_profile_path = bike_dir / "bike_profile.json"

    for path in (settings_dir, bike_dir, inbox_dir, done_dir, failed_dir, staging_dir):
        path.mkdir(parents=True, exist_ok=True)

    preprocess_profile = copy.deepcopy(dict(preprocess_asset.payload))
    preprocess_profile["config"] = normalize_preprocess_config_keys(preprocess_profile["config"])
    preprocess_profile["config"]["schema_path"] = event_schema_path.name

    _write_text(event_schema_path, str(schema_asset.payload), overwrite=overwrite)
    _write_json(preprocess_profile_path, preprocess_profile, overwrite=overwrite)
    _write_json(bike_profile_path, dict(bike_asset.payload), overwrite=overwrite)
    _write_json(
        import_source_config_path,
        {
            "schema": "bodaqs.import_source",
            "version": 1,
            "source_id": safe_source_id,
            "description": f"Provisioned BODAQS import source for {display}.",
            "artifacts_dir": str(artifacts_dir_path),
            "preprocess_profile_path": settings_dir_name,
            "bike_profile_path": bike_dir_name,
            "inbox_dir": "inbox",
            "done_dir": "done",
            "failed_dir": "failed",
            "staging_dir": "staging",
            "archive_patterns": ["*.zip"],
            "logger_timezone": logger_timezone,
            "run_tz_label": str(run_tz_label).strip() or "LOCAL",
            "poll_interval_s": float(poll_interval_s),
            "settle_time_s": float(settle_time_s),
            "include_events": bool(include_events),
            "include_metrics": bool(include_metrics),
            "force_reprocess": bool(force_reprocess),
        },
        overwrite=overwrite,
    )

    return ProvisionedImportAgentSource(
        source_id=safe_source_id,
        display_name=display,
        source_root=source_root_path,
        import_source_config_path=import_source_config_path,
        settings_dir=settings_dir,
        bike_dir=bike_dir,
        preprocess_profile_path=preprocess_profile_path,
        event_schema_path=event_schema_path,
        bike_profile_path=bike_profile_path,
        library_id=library_id,
        artifacts_dir=artifacts_dir_path,
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
    source_id: Optional[str] = None,
    source_directory_name: Optional[str] = None,
    logger_timezone: Optional[str] = None,
    run_tz_label: str = "LOCAL",
    poll_interval_s: float = 5.0,
    settle_time_s: float = 15.0,
    include_events: bool = True,
    include_metrics: bool = True,
    force_reprocess: bool = False,
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
        overwrite=overwrite,
    )

    source_dirname = _safe_slug(source_directory_name or source_display_name, fallback="source")
    source = provision_import_agent_source(
        resolved_sources_root / source_dirname,
        artifacts_dir=library.artifacts_dir,
        source_id=source_id,
        display_name=source_display_name,
        library_id=library.library_id,
        logger_timezone=logger_timezone,
        run_tz_label=run_tz_label,
        poll_interval_s=poll_interval_s,
        settle_time_s=settle_time_s,
        include_events=include_events,
        include_metrics=include_metrics,
        force_reprocess=force_reprocess,
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
                )
            ],
            sources=[
                ImportAgentManagedSourceConfig(
                    source_id=source.source_id,
                    display_name=source.display_name,
                    source_root=source.source_root,
                    library_id=library.library_id,
                    enabled=True,
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
    overwrite: bool = False,
) -> tuple[ImportAgentAppConfig, ProvisionedImportAgentLibrary]:
    config_path = _coerce_required_path(app_config_path, field_name="app_config_path")
    config = load_import_agent_app_config(config_path)

    library = provision_import_agent_library(
        config.libraries_root,
        display_name=display_name,
        library_id=library_id,
        directory_name=directory_name,
        overwrite=overwrite,
    )

    libraries = {item.library_id: item for item in config.libraries}
    libraries[library.library_id] = ImportAgentLibraryConfig(
        library_id=library.library_id,
        display_name=library.display_name,
        artifacts_dir=library.artifacts_dir,
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
    logger_timezone: Optional[str] = None,
    run_tz_label: str = "LOCAL",
    poll_interval_s: float = 5.0,
    settle_time_s: float = 15.0,
    include_events: bool = True,
    include_metrics: bool = True,
    force_reprocess: bool = False,
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
        logger_timezone=logger_timezone,
        run_tz_label=run_tz_label,
        poll_interval_s=poll_interval_s,
        settle_time_s=settle_time_s,
        include_events=include_events,
        include_metrics=include_metrics,
        force_reprocess=force_reprocess,
        overwrite=overwrite,
    )

    sources = {item.source_id: item for item in config.sources}
    sources[source.source_id] = ImportAgentManagedSourceConfig(
        source_id=source.source_id,
        display_name=source.display_name,
        source_root=source.source_root,
        library_id=library.library_id,
        enabled=True,
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
