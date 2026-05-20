from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import socket
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

import pandas as pd

from .artifacts import (
    ArtifactStore,
    copy_session_aux_sources,
    copy_raw_csv_to_source,
    ensure_run_is_new,
    ensure_session_is_new,
    make_run_id,
    save_session_artifacts,
    write_events_partitioned_by_schema_id,
    write_metrics_partitioned_by_schema_id,
    write_run_manifest,
    write_session_manifest,
)
from .bike_profile import load_bike_profile
from .exporters.data_syn_bike import (
    data_syn_bike_manual_settings,
    default_data_syn_bike_export_config,
    export_data_syn_bike_resolved,
    render_data_syn_bike_manual_settings_text,
    write_data_syn_bike_exports,
)
from .import_agent_logger_wifi import LoggerWifiApiClient
from .import_agent_logger_wifi_discovery import (
    LoggerWifiDiscoveryError,
    LoggerWifiDiscoveryUnavailable,
    discover_single_logger_wifi_source,
)
from .pipeline import preprocess_session
from .preprocess_profile import load_preprocess_config, resolve_preprocess_config_paths
from .session_note_presets import BikeSetupPreset, load_bike_setup_preset
from .session_notes import (
    SessionNoteStore,
    SessionNoteTemplate,
    SessionNoteTemplateStore,
    library_session_note_template_root,
)
from .session_archive import (
    SessionArchiveContract,
    extract_session_archive,
    raw_session_identity as make_raw_session_identity,
    read_session_archive_contract,
)
from .import_agent_sources import (
    LOGGER_WIFI_CLEANUP_NONE,
    LoggerWifiSourceConfig,
    SOURCE_TYPE_FILESYSTEM_ARCHIVE,
    SOURCE_TYPE_LOGGER_WIFI,
    normalize_import_source_type,
    parse_logger_wifi_source_config,
)


IMPORT_SOURCE_SCHEMA = "bodaqs.import_source"
IMPORT_SOURCE_VERSION = 1
IMPORT_AGENT_STATE_SCHEMA = "bodaqs.import_agent_state"
IMPORT_AGENT_STATE_VERSION = 1
DEFAULT_ARCHIVE_PATTERNS = ("*.zip",)
DEFAULT_DATA_SYN_BIKE_EXPORT_FILENAME_TEMPLATE = "{run_id}__{session_id}__{export_id}__data_syn_bike.csv"
DEFAULT_DATA_SYN_BIKE_SETTINGS_FILENAME_TEMPLATE = "{run_id}__{session_id}__data_syn_bike_settings.txt"
DATA_SYN_BIKE_LIBRARY_MANIFEST_FILENAME = "data_syn_bike_export_manifest.json"
DEFAULT_SESSION_NOTE_DIRNAME = "notes"

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _optional_text(value: Any) -> Optional[str]:
    text = "" if value is None else str(value).strip()
    return text or None


def _safe_float(value: Any, *, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be numeric") from None
    if number < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return number


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_jsonable(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _write_json_atomic(path: Path, obj: Mapping[str, Any]) -> None:
    _ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _library_data_syn_bike_export_config(artifacts_dir: Path) -> Optional[Dict[str, Any]]:
    metadata = _read_json(artifacts_dir / "library_definition.json", {})
    if not isinstance(metadata, Mapping):
        return None
    exports = metadata.get("exports")
    data_syn_bike = exports.get("data_syn_bike") if isinstance(exports, Mapping) else None
    if data_syn_bike is None:
        data_syn_bike = metadata.get("data_syn_bike_export")
    if not isinstance(data_syn_bike, Mapping) or not bool(data_syn_bike.get("enabled", False)):
        return None

    cfg = {
        "adc_bit_count": 12,
        "raw_scale_mode": "calibrated_full_scale",
        "clip_raw_to_adc_range": True,
        "drop_inactive": True,
        "split_by_activity": False,
        "sample_count_origin": "session",
        "filename_template": DEFAULT_DATA_SYN_BIKE_EXPORT_FILENAME_TEMPLATE,
    }
    cfg.update({k: v for k, v in data_syn_bike.items() if k != "enabled"})
    return cfg


def _bike_profile_syn_raw_full_scale_by_end(bike_profile: Mapping[str, Any]) -> dict[str, float]:
    ranges = bike_profile.get("normalization_ranges")
    if not isinstance(ranges, Sequence) or isinstance(ranges, (str, bytes, bytearray)):
        return {}

    front_wheel: Optional[float] = None
    rear_shock: Optional[float] = None
    for item in ranges:
        if not isinstance(item, Mapping):
            continue
        selector = item.get("signal")
        if not isinstance(selector, Mapping):
            continue
        try:
            full_range = float(item.get("full_range"))
        except (TypeError, ValueError):
            continue
        if full_range <= 0:
            continue
        end = str(selector.get("end") or "").strip().lower()
        quantity = str(selector.get("quantity") or "").strip().lower()
        domain = str(selector.get("domain") or "").strip().lower()
        unit = str(selector.get("unit") or "").strip().lower()
        if quantity != "disp" or unit != "mm":
            continue
        if end == "front" and domain == "wheel":
            front_wheel = full_range
        elif end == "rear" and domain == "suspension":
            rear_shock = full_range

    out: dict[str, float] = {}
    if front_wheel is not None:
        out["front"] = float(front_wheel)
    if rear_shock is not None:
        out["rear"] = float(rear_shock)
    return out


def _render_data_syn_bike_settings_filename(run_id: str, session_id: str) -> str:
    return DEFAULT_DATA_SYN_BIKE_SETTINGS_FILENAME_TEMPLATE.format(
        run_id=_safe_filename_component(run_id),
        session_id=_safe_filename_component(session_id),
    )


def _safe_filename_component(value: str) -> str:
    text = str(value or "").strip() or "session"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve()).lower()
    except Exception:
        return str(path).replace("\\", "/").lower()


def _resolve_source_path(path_or_dir: str | Path) -> Path:
    p = Path(path_or_dir).expanduser()
    if p.is_dir():
        return (p / "import_source.json").resolve()
    return p.resolve()


def _resolve_relative_path(value: str | Path, *, base_dir: Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base_dir / path).resolve()


def _summarize_candidates(paths: Sequence[Path], *, limit: int = 5) -> str:
    shown = [path.name for path in paths[:limit]]
    summary = ", ".join(shown)
    if len(paths) > limit:
        summary += f", +{len(paths) - limit} more"
    return summary


def _resolve_single_valid_json_file(
    path_or_dir: Path,
    *,
    label: str,
    loader: Any,
) -> Path:
    if not path_or_dir.exists():
        raise FileNotFoundError(f"{label} path not found: {path_or_dir}")

    if path_or_dir.is_file():
        loader(path_or_dir)
        return path_or_dir.resolve()

    if not path_or_dir.is_dir():
        raise ValueError(f"{label} path must be a file or directory: {path_or_dir}")

    valid_paths: list[Path] = []
    invalid_records: list[tuple[Path, Exception]] = []

    for candidate in sorted(path_or_dir.iterdir()):
        if not candidate.is_file() or candidate.suffix.lower() != ".json":
            continue
        try:
            loader(candidate)
        except Exception as exc:
            invalid_records.append((candidate, exc))
            continue
        valid_paths.append(candidate.resolve())

    if len(valid_paths) == 1:
        return valid_paths[0]

    if len(valid_paths) > 1:
        raise ValueError(
            f"{label} directory must contain exactly one valid JSON file: {path_or_dir} "
            f"(found {len(valid_paths)} valid files: {_summarize_candidates(valid_paths)})"
        )

    if invalid_records:
        invalid_details = "; ".join(
            f"{path.name} ({type(exc).__name__}: {exc})"
            for path, exc in invalid_records[:3]
        )
        if len(invalid_records) > 3:
            invalid_details += f"; +{len(invalid_records) - 3} more"
        raise ValueError(
            f"{label} directory must contain exactly one valid JSON file: {path_or_dir} "
            f"(found 0 valid files; invalid candidates: {invalid_details})"
        )

    raise FileNotFoundError(
        f"{label} directory must contain exactly one valid JSON file, but none were found: {path_or_dir}"
    )


def _move_to_dir_unique(src: Path, dst_dir: Path) -> Path:
    _ensure_dir(dst_dir)
    candidate = dst_dir / src.name
    if not candidate.exists():
        src.replace(candidate)
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    for idx in range(1, 10000):
        alt = dst_dir / f"{stem}_{idx:02d}{suffix}"
        if alt.exists():
            continue
        src.replace(alt)
        return alt
    raise FileExistsError(f"Could not find a unique destination for {src} in {dst_dir}")


class ImportAgentLock:
    """
    Best-effort single-writer lock per artifact library.
    """

    def __init__(self, path: Path, *, stale_after_s: float = 12 * 60 * 60) -> None:
        self.path = path
        self.stale_after_s = float(stale_after_s)
        self._held = False

    def acquire(self) -> None:
        _ensure_dir(self.path.parent)
        payload = {
            "schema": "bodaqs.import_agent.lock",
            "created_at": _utcnow_iso(),
            "host": socket.gethostname(),
            "pid": os.getpid(),
        }

        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2, sort_keys=True)
                self._held = True
                return
            except FileExistsError:
                if not self._clear_if_stale():
                    existing = _read_json(self.path, {})
                    raise FileExistsError(
                        "Import agent output library is locked by another process: "
                        f"{self.path} ({existing})"
                    ) from None

    def _clear_if_stale(self) -> bool:
        if self.stale_after_s <= 0 or not self.path.exists():
            return False
        try:
            age_s = time.time() - self.path.stat().st_mtime
        except OSError:
            return False
        if age_s < self.stale_after_s:
            return False
        try:
            self.path.unlink()
            logger.warning("Removed stale import-agent lock: %s", self.path)
            return True
        except OSError:
            return False

    def release(self) -> None:
        if not self._held:
            return
        try:
            if self.path.exists():
                self.path.unlink()
        finally:
            self._held = False

    def __enter__(self) -> "ImportAgentLock":
        self.acquire()
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.release()


class ImportAgentState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = {
            "schema": IMPORT_AGENT_STATE_SCHEMA,
            "version": IMPORT_AGENT_STATE_VERSION,
            "updated_at": _utcnow_iso(),
            "records": {},
        }
        self.load()

    def load(self) -> None:
        obj = _read_json(self.path, self.data)
        if not isinstance(obj, dict):
            return
        if obj.get("schema") != IMPORT_AGENT_STATE_SCHEMA:
            return
        if int(obj.get("version", -1)) != IMPORT_AGENT_STATE_VERSION:
            return
        records = obj.get("records")
        self.data = {
            "schema": IMPORT_AGENT_STATE_SCHEMA,
            "version": IMPORT_AGENT_STATE_VERSION,
            "updated_at": str(obj.get("updated_at") or _utcnow_iso()),
            "records": records if isinstance(records, dict) else {},
        }

    def save(self) -> None:
        self.data["updated_at"] = _utcnow_iso()
        _write_json_atomic(self.path, self.data)

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        records = self.data.get("records")
        if not isinstance(records, dict):
            return None
        record = records.get(key)
        return dict(record) if isinstance(record, dict) else None

    def records(self) -> dict[str, Dict[str, Any]]:
        records = self.data.get("records")
        if not isinstance(records, dict):
            return {}
        return {
            str(key): dict(value)
            for key, value in records.items()
            if isinstance(value, dict)
        }

    def upsert(self, key: str, record: Mapping[str, Any]) -> None:
        records = self.data.setdefault("records", {})
        if not isinstance(records, dict):
            raise ValueError("Import agent state records store is corrupted")
        records[key] = dict(record)
        self.save()


@dataclass(frozen=True)
class ImportSourceSessionNoteConfig:
    attach_on_import: bool = False
    template_path: Optional[Path] = None
    setup_preset_path: Optional[Path] = None


@dataclass(frozen=True)
class ImportSourceConfig:
    config_path: Path
    source_root: Path
    source_id: str
    source_type: str
    artifacts_dir: Path
    preprocess_profile_path: Path
    bike_profile_path: Path
    fit_dir: Path
    inbox_dir: Path
    done_dir: Path
    failed_dir: Path
    staging_dir: Path
    archive_patterns: tuple[str, ...] = DEFAULT_ARCHIVE_PATTERNS
    logger_timezone: Optional[str] = None
    run_tz_label: str = "AWST"
    poll_interval_s: float = 5.0
    settle_time_s: float = 15.0
    include_events: bool = True
    include_metrics: bool = True
    description: Optional[str] = None
    force_reprocess: bool = False
    max_archives_per_scan: Optional[int] = None
    library_id: Optional[str] = None
    logger_wifi: Optional[LoggerWifiSourceConfig] = None
    session_note: ImportSourceSessionNoteConfig = field(default_factory=ImportSourceSessionNoteConfig)

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("Import source config must include a non-empty source_id")
        if self.source_type != normalize_import_source_type(self.source_type):
            raise ValueError(f"Import source config has unsupported source_type: {self.source_type!r}")
        if self.source_type == SOURCE_TYPE_LOGGER_WIFI and self.logger_wifi is None:
            raise ValueError("logger_wifi import sources must include a logger_wifi config block")
        if not self.archive_patterns:
            raise ValueError("Import source config must include at least one archive pattern")
        if self.max_archives_per_scan is not None and int(self.max_archives_per_scan) <= 0:
            raise ValueError("max_archives_per_scan must be > 0 when provided")
        if self.session_note.attach_on_import and (
            self.session_note.template_path is None or self.session_note.setup_preset_path is None
        ):
            raise ValueError("session_note attach_on_import requires template_path and setup_preset_path")


@dataclass(frozen=True)
class ImportArchiveCandidate:
    source: ImportSourceConfig
    inbox_archive_path: Path
    claimed_archive_path: Path
    archive_name: str
    archive_sha256: str
    archive_size_bytes: int
    archive_mtime_ns: int
    contract: SessionArchiveContract
    raw_session_identity: str
    processing_key: str


@dataclass(frozen=True)
class LoggerWifiArchiveAcquisition:
    remote_state_key: str
    remote_session_id: str
    logger_id: str
    base_url: str
    local_archive_path: Path
    remote_already_acknowledged: bool = False


@dataclass
class ImportSourceSupervisorState:
    runner: "ImportSourceRunner"
    paused: bool = False
    next_due_s: float = 0.0
    last_scan_started_at: Optional[str] = None
    last_scan_completed_at: Optional[str] = None
    last_report: Optional[Dict[str, Any]] = None


def load_import_source_config(path_or_dir: str | Path) -> ImportSourceConfig:
    config_path = _resolve_source_path(path_or_dir)
    if not config_path.exists():
        raise FileNotFoundError(f"Import source config not found: {config_path}")

    obj = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("Import source config must be a JSON object")
    if obj.get("schema") != IMPORT_SOURCE_SCHEMA:
        raise ValueError(
            f"Unexpected import source schema: {obj.get('schema')!r} "
            f"(expected {IMPORT_SOURCE_SCHEMA!r})"
        )
    if int(obj.get("version", -1)) != IMPORT_SOURCE_VERSION:
        raise ValueError(
            f"Unexpected import source version: {obj.get('version')!r} "
            f"(expected {IMPORT_SOURCE_VERSION})"
        )

    base_dir = config_path.parent.resolve()
    source_id = _optional_text(obj.get("source_id"))
    if source_id is None:
        raise ValueError("Import source config missing non-empty 'source_id'")
    source_type = normalize_import_source_type(obj.get("source_type"))

    logger_wifi: Optional[LoggerWifiSourceConfig] = None
    if source_type == SOURCE_TYPE_LOGGER_WIFI:
        logger_wifi = parse_logger_wifi_source_config(obj.get("logger_wifi"))

    archive_patterns_raw = obj.get("archive_patterns")
    if archive_patterns_raw is None:
        archive_patterns = DEFAULT_ARCHIVE_PATTERNS
    elif isinstance(archive_patterns_raw, list) and archive_patterns_raw:
        archive_patterns = tuple(
            str(x).strip()
            for x in archive_patterns_raw
            if _optional_text(x) is not None
        )
        if not archive_patterns:
            raise ValueError("Import source archive_patterns list is empty")
    else:
        raise ValueError("Import source archive_patterns must be a non-empty list when provided")

    max_archives_per_scan_raw = obj.get("max_archives_per_scan")
    max_archives_per_scan: Optional[int] = None
    if max_archives_per_scan_raw is not None:
        try:
            max_archives_per_scan = int(max_archives_per_scan_raw)
        except (TypeError, ValueError):
            raise ValueError("max_archives_per_scan must be an integer when provided") from None

    session_note_raw = obj.get("session_note")
    if session_note_raw is None:
        session_note = ImportSourceSessionNoteConfig()
    elif not isinstance(session_note_raw, Mapping):
        raise ValueError("Import source session_note must be an object when provided")
    else:
        attach_on_import = bool(session_note_raw.get("attach_on_import", False))
        session_note = ImportSourceSessionNoteConfig(
            attach_on_import=attach_on_import,
            template_path=_resolve_relative_path(
                _optional_text(session_note_raw.get("template_path")) or DEFAULT_SESSION_NOTE_DIRNAME,
                base_dir=base_dir,
            ),
            setup_preset_path=_resolve_relative_path(
                _optional_text(session_note_raw.get("setup_preset_path")) or DEFAULT_SESSION_NOTE_DIRNAME,
                base_dir=base_dir,
            ),
        )

    return ImportSourceConfig(
        config_path=config_path,
        source_root=base_dir,
        source_id=source_id,
        source_type=source_type,
        artifacts_dir=_resolve_relative_path(
            _optional_text(obj.get("artifacts_dir")) or "artifacts",
            base_dir=base_dir,
        ),
        preprocess_profile_path=_resolve_relative_path(
            _optional_text(obj.get("preprocess_profile_path")) or "preprocess_profile.json",
            base_dir=base_dir,
        ),
        bike_profile_path=_resolve_relative_path(
            _optional_text(obj.get("bike_profile_path")) or "bike_profile.json",
            base_dir=base_dir,
        ),
        fit_dir=_resolve_relative_path(
            _optional_text(obj.get("fit_dir")) or "fit",
            base_dir=base_dir,
        ),
        inbox_dir=_resolve_relative_path(
            _optional_text(obj.get("inbox_dir")) or "inbox",
            base_dir=base_dir,
        ),
        done_dir=_resolve_relative_path(
            _optional_text(obj.get("done_dir")) or "done",
            base_dir=base_dir,
        ),
        failed_dir=_resolve_relative_path(
            _optional_text(obj.get("failed_dir")) or "failed",
            base_dir=base_dir,
        ),
        staging_dir=_resolve_relative_path(
            _optional_text(obj.get("staging_dir")) or "staging",
            base_dir=base_dir,
        ),
        archive_patterns=archive_patterns,
        logger_timezone=_optional_text(obj.get("logger_timezone")),
        run_tz_label=_optional_text(obj.get("run_tz_label")) or "AWST",
        poll_interval_s=_safe_float(obj.get("poll_interval_s", 5.0), field_name="poll_interval_s"),
        settle_time_s=_safe_float(obj.get("settle_time_s", 15.0), field_name="settle_time_s"),
        include_events=True,
        include_metrics=True,
        description=_optional_text(obj.get("description")),
        force_reprocess=bool(obj.get("force_reprocess", False)),
        max_archives_per_scan=max_archives_per_scan,
        library_id=_optional_text(obj.get("library_id")),
        logger_wifi=logger_wifi,
        session_note=session_note,
    )


class ImportSourceRunner:
    def __init__(
        self,
        source: ImportSourceConfig,
        *,
        store: Optional[ArtifactStore] = None,
        state_path: Optional[Path] = None,
    ) -> None:
        self.source = source
        self.store = store or ArtifactStore(source.artifacts_dir)
        self.state = ImportAgentState(
            state_path or (self.store.path_library_dir() / "import_agent_state_v1.json")
        )
        self.lock = ImportAgentLock(self.store.path_library_dir() / "import_agent.lock")
        self.preprocess_profile_sha256: Optional[str] = None
        self.bike_profile_sha256: Optional[str] = None
        self.preprocess_config: Optional[Dict[str, Any]] = None
        self.resolved_preprocess_profile_path: Optional[Path] = None
        self.resolved_bike_profile_path: Optional[Path] = None

    def _resolve_preprocess_profile_path(self) -> Path:
        if self.resolved_preprocess_profile_path is None:
            self.resolved_preprocess_profile_path = _resolve_single_valid_json_file(
                self.source.preprocess_profile_path,
                label="Preprocess profile",
                loader=load_preprocess_config,
            )
        return self.resolved_preprocess_profile_path

    def _resolve_bike_profile_path(self) -> Path:
        if self.resolved_bike_profile_path is None:
            self.resolved_bike_profile_path = _resolve_single_valid_json_file(
                self.source.bike_profile_path,
                label="Bike profile",
                loader=load_bike_profile,
            )
        return self.resolved_bike_profile_path

    def _ensure_runtime_config_loaded(self) -> None:
        if self.preprocess_config is None:
            preprocess_profile_path = self._resolve_preprocess_profile_path()
            bike_profile_path = self._resolve_bike_profile_path()
            self.preprocess_profile_sha256 = _sha256_file(preprocess_profile_path)
            self.bike_profile_sha256 = _sha256_file(bike_profile_path)
            self.preprocess_config = resolve_preprocess_config_paths(
                load_preprocess_config(preprocess_profile_path),
                base_dir=preprocess_profile_path.parent,
            )

    def validate(self) -> tuple[list[str], list[str]]:
        errors: list[str] = []
        warnings: list[str] = []

        try:
            self.resolved_preprocess_profile_path = _resolve_single_valid_json_file(
                self.source.preprocess_profile_path,
                label="Preprocess profile",
                loader=load_preprocess_config,
            )
        except Exception as exc:
            errors.append(str(exc))

        try:
            self.resolved_bike_profile_path = _resolve_single_valid_json_file(
                self.source.bike_profile_path,
                label="Bike profile",
                loader=load_bike_profile,
            )
        except Exception as exc:
            errors.append(str(exc))

        if self.source.session_note.attach_on_import:
            template_store = SessionNoteTemplateStore(self.source.session_note.template_path)
            try:
                _resolve_single_valid_json_file(
                    self.source.session_note.template_path,
                    label="Session note template",
                    loader=template_store.load_template_file,
                )
            except Exception as exc:
                errors.append(str(exc))
            try:
                _resolve_single_valid_json_file(
                    self.source.session_note.setup_preset_path,
                    label="Bike setup preset",
                    loader=load_bike_setup_preset,
                )
            except Exception as exc:
                errors.append(str(exc))

        for path in (
            self.source.inbox_dir,
            self.source.done_dir,
            self.source.failed_dir,
            self.source.staging_dir,
            self.source.fit_dir,
        ):
            if not path.exists():
                warnings.append(f"Directory will be created when needed: {path}")

        if self.source.source_type == SOURCE_TYPE_LOGGER_WIFI:
            if self.source.logger_wifi is not None and self.source.logger_wifi.base_url is None:
                warnings.append(
                    "Wi-Fi logger source has no remembered base_url; mDNS discovery will be used before acquisition."
                )

        return errors, warnings

    def ensure_runtime_dirs(self) -> None:
        for path in (
            self.source.inbox_dir,
            self.source.done_dir,
            self.source.failed_dir,
            self.source.staging_dir,
            self.source.fit_dir,
        ):
            _ensure_dir(path)

    def _import_agent_fit_import_config(self) -> Optional[Dict[str, Any]]:
        if not isinstance(self.preprocess_config, Mapping):
            return None
        raw = self.preprocess_config.get("fit_import")
        if not isinstance(raw, Mapping):
            return None
        if not bool(raw.get("enabled", False)):
            return dict(raw)

        cfg = dict(raw)
        cfg["fit_dir"] = str(self.source.fit_dir)
        cfg["ambiguity_policy"] = "largest_overlap"
        cfg["failure_policy"] = "warn"
        return cfg

    def _write_data_syn_bike_outputs_if_enabled(
        self,
        *,
        session: Mapping[str, Any],
        run_id: str,
        session_id: str,
        bike_profile_path: Path,
    ) -> Optional[Dict[str, Any]]:
        library_export_config = _library_data_syn_bike_export_config(self.store.root)
        if library_export_config is None:
            return None

        record: Dict[str, Any] = {
            "format": "data_syn_bike",
            "status": "not_started",
            "run_id": run_id,
            "session_id": session_id,
            "updated_at": _utcnow_iso(),
        }
        try:
            bike_profile = load_bike_profile(bike_profile_path)
            raw_full_scale_by_end = _bike_profile_syn_raw_full_scale_by_end(bike_profile)
            export_config = dict(library_export_config)
            if raw_full_scale_by_end:
                existing = export_config.get("raw_full_scale_by_end")
                merged_full_scales = dict(existing) if isinstance(existing, Mapping) else {}
                merged_full_scales.update(raw_full_scale_by_end)
                export_config["raw_full_scale_by_end"] = merged_full_scales

            session_for_export = dict(session)
            session_for_export["run_id"] = run_id
            session_for_export["session_id"] = session_id
            export_config = default_data_syn_bike_export_config(**export_config)
            export_result = export_data_syn_bike_resolved(session_for_export, export_config=export_config)

            output_dir = self.store.root / "syn"
            write_result = write_data_syn_bike_exports(export_result, output_dir)
            settings = data_syn_bike_manual_settings(
                bike_profile=bike_profile,
                export_config=export_config,
                session=session_for_export,
            )
            settings_name = _render_data_syn_bike_settings_filename(run_id, session_id)
            settings_path = output_dir / settings_name
            _ensure_dir(settings_path.parent)
            settings_path.write_text(
                render_data_syn_bike_manual_settings_text(settings, export_result=export_result),
                encoding="utf-8",
            )

            record.update(
                {
                    "status": "succeeded",
                    "output_dir": str(output_dir),
                    "n_files": int(write_result.get("n_files", 0)),
                    "files": [
                        {
                            "path": str(item.get("path")),
                            "export_id": item.get("export_id"),
                            "rows": item.get("rows"),
                        }
                        for item in write_result.get("written", [])
                        if isinstance(item, Mapping)
                    ],
                    "settings_path": str(settings_path),
                    "settings": settings,
                    "summary": export_result.get("summary", {}),
                }
            )
        except Exception as exc:
            record.update(
                {
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            logger.exception("data.syn.bike export failed for run=%s session=%s", run_id, session_id)

        self._upsert_data_syn_bike_manifest(record)
        return record

    def _upsert_data_syn_bike_manifest(self, record: Mapping[str, Any]) -> None:
        syn_dir = self.store.root / "syn"
        manifest_path = syn_dir / DATA_SYN_BIKE_LIBRARY_MANIFEST_FILENAME
        manifest = _read_json(
            manifest_path,
            {
                "schema": "bodaqs.data_syn_bike_export_manifest",
                "version": 1,
                "records": {},
            },
        )
        if not isinstance(manifest, dict):
            manifest = {"schema": "bodaqs.data_syn_bike_export_manifest", "version": 1, "records": {}}
        records = manifest.setdefault("records", {})
        if not isinstance(records, dict):
            records = {}
            manifest["records"] = records
        key = f"{record.get('run_id')}/{record.get('session_id')}"
        records[key] = dict(record)
        manifest["updated_at"] = _utcnow_iso()
        _write_json_atomic(manifest_path, manifest)

    def _resolve_session_note_template_path(self) -> Path:
        if not self.source.session_note.attach_on_import:
            raise ValueError("Session-note auto-attach is not enabled for this source")
        if self.source.session_note.template_path is None:
            raise ValueError("Session-note template path is not configured")
        return _resolve_single_valid_json_file(
            self.source.session_note.template_path,
            label="Session note template",
            loader=SessionNoteTemplateStore().load_template_file,
        )

    def _resolve_bike_setup_preset_path(self) -> Path:
        if not self.source.session_note.attach_on_import:
            raise ValueError("Session-note auto-attach is not enabled for this source")
        if self.source.session_note.setup_preset_path is None:
            raise ValueError("Bike setup preset path is not configured")
        return _resolve_single_valid_json_file(
            self.source.session_note.setup_preset_path,
            label="Bike setup preset",
            loader=load_bike_setup_preset,
        )

    def _copy_template_to_library(self, template: SessionNoteTemplate, template_path: Path) -> Path:
        target = library_session_note_template_root(self.store.root) / template.template_id / f"{template.template_version}.json"
        _ensure_dir(target.parent)
        source_sha256 = _sha256_file(template_path)
        if target.exists():
            target_sha256 = _sha256_file(target)
            if target_sha256 != source_sha256:
                raise ValueError(
                    "Library already contains a different session note template for "
                    f"{template.template_id}@{template.template_version}: {target}"
                )
            return target
        shutil.copy2(template_path, target)
        return target

    def _write_draft_session_note_if_enabled(
        self,
        *,
        run_id: str,
        session_id: str,
        bike_profile_path: Path,
    ) -> Optional[Dict[str, Any]]:
        if not self.source.session_note.attach_on_import:
            return None

        template_path = self._resolve_session_note_template_path()
        preset_path = self._resolve_bike_setup_preset_path()
        source_template_store = SessionNoteTemplateStore(template_path.parent)
        template = source_template_store.load_template_file(template_path)
        preset: BikeSetupPreset = load_bike_setup_preset(preset_path)
        if preset.template_id != template.template_id:
            raise ValueError(
                f"Bike setup preset template_id {preset.template_id!r} does not match "
                f"session note template {template.template_id!r}"
            )
        if preset.template_version is not None and preset.template_version != template.template_version:
            raise ValueError(
                f"Bike setup preset template_version {preset.template_version!r} does not match "
                f"session note template {template.template_version!r}"
            )

        library_template_path = self._copy_template_to_library(template, template_path)
        bike_profile = load_bike_profile(bike_profile_path)
        bike_profile_id = _optional_text(bike_profile.get("bike_profile_id"))
        source_context: Dict[str, Any] = {
            "origin": "import_agent",
            "import_source_id": self.source.source_id,
            "import_source_type": self.source.source_type,
            "import_source_config_path": str(self.source.config_path),
            "bike_profile_id": bike_profile_id,
            "bike_profile_path": str(bike_profile_path),
            "bike_profile_sha256": _sha256_file(bike_profile_path),
            "setup_preset_id": preset.preset_id,
            "setup_preset_path": str(preset_path),
            "setup_preset_sha256": _sha256_file(preset_path),
            "template_id": template.template_id,
            "template_version": template.template_version,
            "template_path": str(template_path),
            "template_sha256": _sha256_file(template_path),
            "library_template_path": str(library_template_path),
        }
        if preset.bike_profile_id is not None:
            source_context["preset_bike_profile_id"] = preset.bike_profile_id
            source_context["preset_bike_profile_id_matches"] = preset.bike_profile_id == bike_profile_id

        note_store = SessionNoteStore(
            store=self.store,
            template_store=SessionNoteTemplateStore(library_session_note_template_root(self.store.root)),
        )
        note = note_store.create_note_from_template(
            run_id=run_id,
            session_id=session_id,
            template_id=template.template_id,
            template_version=template.template_version,
            title=preset.title,
            draft=True,
            source_context=source_context,
        )
        note = note_store.update_note(
            note,
            values=preset.values,
            custom_values=preset.custom_values,
            free_text_notes=preset.free_text_notes,
        )
        saved = note_store.save_note(note)
        return {
            "status": "succeeded",
            "path": str(note_store.note_path(run_id=run_id, session_id=session_id)),
            "draft": bool(saved.draft),
            "template_id": saved.template_id,
            "template_version": saved.template_version,
            "setup_preset_id": preset.preset_id,
            "setup_preset_path": str(preset_path),
            "template_path": str(template_path),
            "library_template_path": str(library_template_path),
        }

    def _logger_wifi_remote_state_key(self, remote_session_id: str) -> str:
        if self.source.logger_wifi is None:
            raise ValueError("Cannot build Wi-Fi remote state key without logger_wifi config")
        return "logger_wifi:" + _sha256_jsonable(
            {
                "source_id": self.source.source_id,
                "logger_id": self.source.logger_wifi.logger_id,
                "remote_session_id": remote_session_id,
            }
        )

    def _logger_wifi_archive_filename(self, session: Mapping[str, Any]) -> str:
        remote_session_id = _optional_text(session.get("session_id"))
        if remote_session_id is None:
            raise ValueError("Wi-Fi logger session entry is missing session_id")

        name_hint = _optional_text(session.get("session_stem")) or remote_session_id
        safe_hint = re.sub(r"[^A-Za-z0-9._-]+", "_", name_hint).strip("._-")
        if not safe_hint:
            safe_hint = "logger_session"
        digest = hashlib.sha256(remote_session_id.encode("utf-8")).hexdigest()[:12]
        return f"{safe_hint[:80]}_{digest}.zip"

    def _logger_wifi_client(self) -> Optional[LoggerWifiApiClient]:
        config = self.source.logger_wifi
        if self.source.source_type != SOURCE_TYPE_LOGGER_WIFI or config is None:
            return None
        if config.base_url is None:
            return None
        return self._logger_wifi_client_for_base_url(config.base_url)

    def _logger_wifi_client_for_base_url(self, base_url: str) -> LoggerWifiApiClient:
        config = self.source.logger_wifi
        if config is None:
            raise ValueError("Cannot build Wi-Fi logger client without logger_wifi config")
        return LoggerWifiApiClient(
            base_url,
            request_timeout_s=config.request_timeout_s,
            download_timeout_s=config.download_timeout_s,
        )

    def _discover_logger_wifi_client(self, remote_summary: Dict[str, Any]) -> Optional[LoggerWifiApiClient]:
        config = self.source.logger_wifi
        if self.source.source_type != SOURCE_TYPE_LOGGER_WIFI or config is None:
            return None

        timeout_s = max(1.0, min(float(config.request_timeout_s), 5.0))
        try:
            result = discover_single_logger_wifi_source(
                logger_id=config.logger_id,
                timeout_s=timeout_s,
            )
        except LoggerWifiDiscoveryUnavailable as exc:
            remote_summary["discovery"] = {
                "state": "unavailable",
                "message": str(exc),
            }
            return None
        except LoggerWifiDiscoveryError as exc:
            remote_summary["discovery"] = {
                "state": "error",
                "error": str(exc),
            }
            return None
        except Exception as exc:
            remote_summary["discovery"] = {
                "state": "error",
                "error": f"{type(exc).__name__}: {exc}",
            }
            return None

        if result is None:
            remote_summary["discovery"] = {
                "state": "not_found",
                "logger_id": config.logger_id,
            }
            return None

        remote_summary["discovery"] = {
            "state": "found",
            "logger_id": result.logger_id,
            "base_url": result.base_url,
            "hostname": result.hostname,
            "upload_mode": result.upload_mode,
            "api_version": result.api_version,
            "addresses": list(result.addresses),
        }
        return self._logger_wifi_client_for_base_url(result.base_url)

    def _logger_wifi_client_from_acquisition(
        self,
        acquisition: LoggerWifiArchiveAcquisition,
    ) -> Optional[LoggerWifiApiClient]:
        base_url = _optional_text(acquisition.base_url)
        if base_url is not None:
            return self._logger_wifi_client_for_base_url(base_url)
        return self._logger_wifi_client()

    def _pending_logger_wifi_acquisitions_from_state(self) -> dict[str, LoggerWifiArchiveAcquisition]:
        if self.source.source_type != SOURCE_TYPE_LOGGER_WIFI or self.source.logger_wifi is None:
            return {}

        out: dict[str, LoggerWifiArchiveAcquisition] = {}
        for state_key, record in self.state.records().items():
            if not state_key.startswith("logger_wifi:"):
                continue
            if str(record.get("source_id") or "") != self.source.source_id:
                continue
            if str(record.get("status") or "") != "downloaded":
                continue
            remote_session_id = _optional_text(record.get("remote_session_id"))
            local_archive_path_raw = _optional_text(record.get("local_archive_path"))
            if remote_session_id is None or local_archive_path_raw is None:
                continue
            local_archive_path = Path(local_archive_path_raw)
            if not local_archive_path.exists():
                continue
            acquisition = LoggerWifiArchiveAcquisition(
                remote_state_key=state_key,
                remote_session_id=remote_session_id,
                logger_id=_optional_text(record.get("logger_id")) or self.source.logger_wifi.logger_id,
                base_url=_optional_text(record.get("base_url")) or self.source.logger_wifi.base_url or "",
                local_archive_path=local_archive_path.resolve(),
                remote_already_acknowledged=bool(
                    record.get("remote_already_acknowledged", record.get("acknowledged", False))
                ),
            )
            out[_path_key(local_archive_path)] = acquisition
        return out

    def _record_logger_wifi_downloaded(
        self,
        *,
        acquisition: LoggerWifiArchiveAcquisition,
        archive_sha256: str,
    ) -> None:
        self.state.upsert(
            acquisition.remote_state_key,
            {
                "status": "downloaded",
                "source_id": self.source.source_id,
                "source_type": SOURCE_TYPE_LOGGER_WIFI,
                "remote_session_id": acquisition.remote_session_id,
                "logger_id": acquisition.logger_id,
                "base_url": acquisition.base_url,
                "local_archive_path": str(acquisition.local_archive_path),
                "archive_sha256": archive_sha256,
                "remote_already_acknowledged": acquisition.remote_already_acknowledged,
                "updated_at": _utcnow_iso(),
            },
        )

    def _record_logger_wifi_failure(
        self,
        *,
        acquisition: LoggerWifiArchiveAcquisition,
        error: str,
        processing_key: Optional[str] = None,
        archive_sha256: Optional[str] = None,
    ) -> None:
        record: dict[str, Any] = {
            "status": "failed",
            "source_id": self.source.source_id,
            "source_type": SOURCE_TYPE_LOGGER_WIFI,
            "remote_session_id": acquisition.remote_session_id,
            "logger_id": acquisition.logger_id,
            "base_url": acquisition.base_url,
            "local_archive_path": str(acquisition.local_archive_path),
            "updated_at": _utcnow_iso(),
            "error": error,
        }
        if processing_key is not None:
            record["processing_key"] = processing_key
        if archive_sha256 is not None:
            record["archive_sha256"] = archive_sha256
        self.state.upsert(acquisition.remote_state_key, record)

    def _acquire_logger_wifi_archives(
        self,
        summary: Dict[str, Any],
    ) -> dict[str, LoggerWifiArchiveAcquisition]:
        if self.source.source_type != SOURCE_TYPE_LOGGER_WIFI or self.source.logger_wifi is None:
            return {}

        config = self.source.logger_wifi
        remote_summary: Dict[str, Any] = {
            "logger_id": config.logger_id,
            "base_url": config.base_url,
            "status": None,
            "sessions_seen": 0,
            "downloaded": [],
            "skipped": [],
            "failed": [],
        }
        summary["remote"] = remote_summary

        acquisitions = self._pending_logger_wifi_acquisitions_from_state()
        client = self._logger_wifi_client()
        configured_error: Optional[Exception] = None
        device: Optional[dict[str, Any]] = None

        if client is not None:
            try:
                device = client.get_device()
                device_logger_id = _optional_text(device.get("logger_id"))
                if device_logger_id != config.logger_id:
                    raise ValueError(
                        f"Logger identity mismatch: expected {config.logger_id!r}, got {device_logger_id!r}"
                    )
            except Exception as exc:
                configured_error = exc
                remote_summary["configured_address_error"] = f"{type(exc).__name__}: {exc}"
                device = None

        if device is None:
            discovered_client = self._discover_logger_wifi_client(remote_summary)
            if discovered_client is not None:
                client = discovered_client

        try:
            if client is None:
                discovery_state = (
                    remote_summary.get("discovery", {})
                    if isinstance(remote_summary.get("discovery"), Mapping)
                    else {}
                )
                remote_summary["status"] = {
                    "state": str(discovery_state.get("state") or "not_found"),
                    "message": "Wi-Fi logger was not reachable by remembered address or mDNS discovery.",
                }
                return acquisitions

            if device is None:
                device = client.get_device()

            device_logger_id = _optional_text(device.get("logger_id"))
            if device_logger_id != config.logger_id:
                raise ValueError(
                    f"Logger identity mismatch: expected {config.logger_id!r}, got {device_logger_id!r}"
                )

            status = client.get_status()
            status_logger_id = _optional_text(status.get("logger_id"))
            if status_logger_id is not None and status_logger_id != config.logger_id:
                raise ValueError(
                    f"Logger status identity mismatch: expected {config.logger_id!r}, got {status_logger_id!r}"
                )

            upload_mode = bool(status.get("upload_mode", False))
            if not upload_mode:
                remote_summary["status"] = {
                    "state": "waiting_upload_mode",
                    "upload_mode": False,
                    "message": "Logger is reachable but not in upload mode.",
                }
                logger.info(
                    "Wi-Fi logger source waiting for upload mode: source=%s logger_id=%s",
                    self.source.source_id,
                    config.logger_id,
                )
                return acquisitions

            sessions = client.list_sessions()
            remote_summary["sessions_seen"] = len(sessions)
            remote_summary["status"] = {
                "state": "ready",
                "upload_mode": upload_mode,
                "importable_session_count": len(sessions),
            }

            for session in sessions:
                remote_session_id = _optional_text(session.get("session_id"))
                if remote_session_id is None:
                    continue
                remote_state_key = self._logger_wifi_remote_state_key(remote_session_id)
                existing = self.state.get(remote_state_key)
                if (
                    existing is not None
                    and str(existing.get("status") or "") == "succeeded"
                    and not self.source.force_reprocess
                ):
                    remote_summary["skipped"].append(
                        {
                            "session_id": remote_session_id,
                            "reason": "already_imported",
                            "run_id": existing.get("run_id"),
                            "session": existing.get("session_id"),
                        }
                    )
                    continue
                if session.get("archive_ready") is False:
                    remote_summary["skipped"].append(
                        {"session_id": remote_session_id, "reason": "archive_not_ready"}
                    )
                    continue

                target_path = (self.source.inbox_dir / self._logger_wifi_archive_filename(session)).resolve()
                acquisition = LoggerWifiArchiveAcquisition(
                    remote_state_key=remote_state_key,
                    remote_session_id=remote_session_id,
                    logger_id=config.logger_id,
                    base_url=client.base_url,
                    local_archive_path=target_path,
                    remote_already_acknowledged=bool(session.get("acknowledged", False)),
                )

                if target_path.exists():
                    acquisitions[_path_key(target_path)] = acquisition
                    remote_summary["skipped"].append(
                        {
                            "session_id": remote_session_id,
                            "reason": "already_local_pending",
                            "archive_path": str(target_path),
                        }
                    )
                    continue

                downloaded_path = client.download_archive_to_part(remote_session_id, target_path)
                try:
                    self._archive_contract(downloaded_path)
                except Exception as exc:
                    failed_path = _move_to_dir_unique(downloaded_path, self.source.failed_dir)
                    error = f"{type(exc).__name__}: {exc}"
                    self._record_logger_wifi_failure(acquisition=acquisition, error=error)
                    remote_summary["failed"].append(
                        {
                            "session_id": remote_session_id,
                            "failed_archive_path": str(failed_path),
                            "error": error,
                        }
                    )
                    continue

                acquisition = LoggerWifiArchiveAcquisition(
                    remote_state_key=remote_state_key,
                    remote_session_id=remote_session_id,
                    logger_id=config.logger_id,
                    base_url=client.base_url,
                    local_archive_path=downloaded_path.resolve(),
                    remote_already_acknowledged=bool(session.get("acknowledged", False)),
                )
                archive_sha256 = _sha256_file(downloaded_path)
                self._record_logger_wifi_downloaded(
                    acquisition=acquisition,
                    archive_sha256=archive_sha256,
                )
                acquisitions[_path_key(downloaded_path)] = acquisition
                remote_summary["downloaded"].append(
                    {
                        "session_id": remote_session_id,
                        "archive_path": str(downloaded_path),
                        "archive_sha256": archive_sha256,
                    }
                )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            remote_summary["status"] = {
                "state": "error",
                "error": error,
            }
            remote_summary["failed"].append({"error": error})
            if configured_error is not None:
                remote_summary["configured_address_error"] = f"{type(configured_error).__name__}: {configured_error}"
            logger.warning(
                "Wi-Fi logger acquisition failed for source=%s logger_id=%s: %s",
                self.source.source_id,
                config.logger_id,
                error,
            )

        return acquisitions

    def _postprocess_logger_wifi_import(
        self,
        *,
        acquisition: Optional[LoggerWifiArchiveAcquisition],
        record: Mapping[str, Any],
        candidate: ImportArchiveCandidate,
        summary: Dict[str, Any],
    ) -> None:
        if acquisition is None:
            return
        if self.source.logger_wifi is None:
            return

        config = self.source.logger_wifi
        acknowledged = False
        cleanup_done = False
        ack_response: Optional[dict[str, Any]] = None
        cleanup_response: Optional[dict[str, Any]] = None
        post_error: Optional[str] = None

        client = self._logger_wifi_client_from_acquisition(acquisition)
        if acquisition.remote_already_acknowledged:
            acknowledged = True
        elif client is None:
            post_error = "Wi-Fi logger source has no base_url configured; cannot acknowledge remote session."
        else:
            try:
                ack_response = client.ack_session(
                    session_id=acquisition.remote_session_id,
                    library_id=self.source.library_id,
                    run_id=_optional_text(record.get("run_id")),
                    imported_at=_optional_text(record.get("updated_at")),
                )
                acknowledged = True
            except Exception as exc:
                post_error = f"ack failed: {type(exc).__name__}: {exc}"
                logger.warning(
                    "Wi-Fi logger acknowledgement failed for source=%s session=%s: %s",
                    self.source.source_id,
                    acquisition.remote_session_id,
                    post_error,
                )

        if acknowledged and config.cleanup_mode != LOGGER_WIFI_CLEANUP_NONE:
            if client is None:
                post_error = "Wi-Fi logger source has no base_url configured; cannot clean up remote session."
            else:
                try:
                    cleanup_response = client.cleanup_session(
                        session_id=acquisition.remote_session_id,
                        mode=config.cleanup_mode,
                    )
                    cleanup_done = True
                except Exception as exc:
                    post_error = f"cleanup failed: {type(exc).__name__}: {exc}"
                    logger.warning(
                        "Wi-Fi logger cleanup failed for source=%s session=%s: %s",
                        self.source.source_id,
                        acquisition.remote_session_id,
                        post_error,
                    )

        updated_record = dict(record)
        updated_record.update(
            {
                "remote_source": SOURCE_TYPE_LOGGER_WIFI,
                "remote_session_id": acquisition.remote_session_id,
                "remote_logger_id": acquisition.logger_id,
                "remote_base_url": acquisition.base_url,
                "remote_acknowledged": acknowledged,
                "remote_already_acknowledged": acquisition.remote_already_acknowledged,
                "remote_cleanup_mode": config.cleanup_mode,
                "remote_cleanup_done": cleanup_done,
            }
        )
        if post_error is not None:
            updated_record["remote_postprocess_error"] = post_error
        self.state.upsert(candidate.processing_key, updated_record)

        remote_record: dict[str, Any] = {
            "status": "succeeded",
            "source_id": self.source.source_id,
            "source_type": SOURCE_TYPE_LOGGER_WIFI,
            "remote_session_id": acquisition.remote_session_id,
            "logger_id": acquisition.logger_id,
            "base_url": acquisition.base_url,
            "local_archive_path": str(acquisition.local_archive_path),
            "archive_sha256": candidate.archive_sha256,
            "processing_key": candidate.processing_key,
            "raw_session_identity": candidate.raw_session_identity,
            "run_id": record.get("run_id"),
            "session_id": record.get("session_id"),
            "acknowledged": acknowledged,
            "remote_already_acknowledged": acquisition.remote_already_acknowledged,
            "cleanup_mode": config.cleanup_mode,
            "cleanup_done": cleanup_done,
            "updated_at": _utcnow_iso(),
        }
        if ack_response is not None:
            remote_record["ack_response"] = ack_response
        if cleanup_response is not None:
            remote_record["cleanup_response"] = cleanup_response
        if post_error is not None:
            remote_record["postprocess_error"] = post_error
        self.state.upsert(acquisition.remote_state_key, remote_record)

        if post_error is not None:
            summary.setdefault("remote", {}).setdefault("failed", []).append(
                {
                    "session_id": acquisition.remote_session_id,
                    "stage": "postprocess",
                    "error": post_error,
                }
            )

    def _discover_archives(self) -> list[Path]:
        self.ensure_runtime_dirs()
        out: list[Path] = []
        seen: set[str] = set()
        for pattern in self.source.archive_patterns:
            for path in sorted(self.source.inbox_dir.glob(pattern)):
                if not path.is_file():
                    continue
                key = _path_key(path)
                if key in seen:
                    continue
                seen.add(key)
                out.append(path.resolve())
        out.sort(key=lambda p: (p.stat().st_mtime_ns if p.exists() else 0, str(p)))
        if self.source.max_archives_per_scan is not None:
            return out[: int(self.source.max_archives_per_scan)]
        return out

    def _is_settled(self, path: Path, *, now_s: float) -> bool:
        if self.source.source_type == SOURCE_TYPE_LOGGER_WIFI:
            return True
        age_s = now_s - (path.stat().st_mtime_ns / 1_000_000_000.0)
        return age_s >= float(self.source.settle_time_s)

    def _archive_contract(self, archive_path: Path) -> SessionArchiveContract:
        return read_session_archive_contract(archive_path)

    def _build_candidate(
        self,
        *,
        inbox_archive_path: Path,
        claimed_archive_path: Path,
    ) -> ImportArchiveCandidate:
        self._ensure_runtime_config_loaded()
        stat = claimed_archive_path.stat()
        contract = self._archive_contract(claimed_archive_path)
        raw_session_identity = make_raw_session_identity(
            csv_sha256=contract.csv_sha256,
            log_metadata_sha256=contract.log_metadata_sha256,
        )
        processing_key = _sha256_jsonable(
            {
                "raw_session_identity": raw_session_identity,
                "preprocess_profile_sha256": self.preprocess_profile_sha256,
                "bike_profile_sha256": self.bike_profile_sha256,
                "include_events": self.source.include_events,
                "include_metrics": self.source.include_metrics,
                "logger_timezone": self.source.logger_timezone,
            }
        )
        return ImportArchiveCandidate(
            source=self.source,
            inbox_archive_path=inbox_archive_path,
            claimed_archive_path=claimed_archive_path,
            archive_name=claimed_archive_path.name,
            archive_sha256=_sha256_file(claimed_archive_path),
            archive_size_bytes=int(stat.st_size),
            archive_mtime_ns=int(stat.st_mtime_ns),
            contract=contract,
            raw_session_identity=raw_session_identity,
            processing_key=processing_key,
        )

    def _extract_candidate(self, candidate: ImportArchiveCandidate, target_dir: Path) -> tuple[Path, Path]:
        extracted = extract_session_archive(
            candidate.claimed_archive_path,
            target_dir,
            contract=candidate.contract,
        )
        if extracted.log_metadata_path is None:
            raise ValueError(f"Session archive did not yield log metadata: {candidate.archive_name}")
        return extracted.csv_path, extracted.log_metadata_path

    def scan_once(self) -> Dict[str, Any]:
        summary: Dict[str, Any] = {
            "source_id": self.source.source_id,
            "source_type": self.source.source_type,
            "artifacts_dir": str(self.source.artifacts_dir),
            "seen": 0,
            "deferred_unsettled": [],
            "skipped_succeeded": [],
            "skipped_failed": [],
            "imported": [],
            "failed": [],
        }
        now_s = time.time()

        with self.lock:
            remote_acquisitions = self._acquire_logger_wifi_archives(summary)

            for inbox_path in self._discover_archives():
                remote_acquisition = remote_acquisitions.get(_path_key(inbox_path))
                summary["seen"] += 1
                if not self._is_settled(inbox_path, now_s=now_s):
                    summary["deferred_unsettled"].append(str(inbox_path))
                    continue

                try:
                    claimed_path = _move_to_dir_unique(inbox_path, self.source.staging_dir)
                except FileNotFoundError:
                    logger.warning("Archive disappeared before it could be claimed: %s", inbox_path)
                    continue

                try:
                    candidate = self._build_candidate(
                        inbox_archive_path=inbox_path,
                        claimed_archive_path=claimed_path,
                    )
                except Exception as exc:
                    failed_path = _move_to_dir_unique(claimed_path, self.source.failed_dir)
                    failure = {
                        "status": "failed",
                        "source_id": self.source.source_id,
                        "archive_path": str(inbox_path),
                        "failed_archive_path": str(failed_path),
                        "updated_at": _utcnow_iso(),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    logger.exception("Archive validation failed for %s", inbox_path)
                    if remote_acquisition is not None:
                        self._record_logger_wifi_failure(
                            acquisition=remote_acquisition,
                            error=failure["error"],
                        )
                    summary["failed"].append(failure)
                    continue

                existing = self.state.get(candidate.processing_key)
                if existing is not None and not self.source.force_reprocess:
                    if str(existing.get("status") or "") == "succeeded":
                        done_path = _move_to_dir_unique(claimed_path, self.source.done_dir)
                        summary["skipped_succeeded"].append(
                            {
                                "archive_path": str(inbox_path),
                                "done_archive_path": str(done_path),
                                "run_id": existing.get("run_id"),
                                "session_id": existing.get("session_id"),
                                "processing_key": candidate.processing_key,
                            }
                        )
                        self._postprocess_logger_wifi_import(
                            acquisition=remote_acquisition,
                            record=existing,
                            candidate=candidate,
                            summary=summary,
                        )
                        continue
                    if str(existing.get("status") or "") == "failed":
                        failed_path = _move_to_dir_unique(claimed_path, self.source.failed_dir)
                        summary["skipped_failed"].append(
                            {
                                "archive_path": str(inbox_path),
                                "failed_archive_path": str(failed_path),
                                "processing_key": candidate.processing_key,
                                "error": existing.get("error"),
                            }
                        )
                        continue

                try:
                    record = self.import_candidate(candidate)
                    self._postprocess_logger_wifi_import(
                        acquisition=remote_acquisition,
                        record=record,
                        candidate=candidate,
                        summary=summary,
                    )
                    record = self.state.get(candidate.processing_key) or record
                    summary["imported"].append(record)
                except Exception as exc:
                    failed_path = _move_to_dir_unique(candidate.claimed_archive_path, self.source.failed_dir)
                    error_record = {
                        "status": "failed",
                        "source_id": self.source.source_id,
                        "archive_path": str(candidate.inbox_archive_path),
                        "archive_sha256": candidate.archive_sha256,
                        "failed_archive_path": str(failed_path),
                        "raw_session_identity": candidate.raw_session_identity,
                        "processing_key": candidate.processing_key,
                        "updated_at": _utcnow_iso(),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    self.state.upsert(candidate.processing_key, error_record)
                    if remote_acquisition is not None:
                        self._record_logger_wifi_failure(
                            acquisition=remote_acquisition,
                            error=error_record["error"],
                            processing_key=candidate.processing_key,
                            archive_sha256=candidate.archive_sha256,
                        )
                    logger.exception("Import failed for %s", candidate.inbox_archive_path)
                    summary["failed"].append(error_record)

        return summary

    def import_candidate(self, candidate: ImportArchiveCandidate) -> Dict[str, Any]:
        self._ensure_runtime_config_loaded()
        run_id: Optional[str] = None
        preprocess_profile_path = self._resolve_preprocess_profile_path()
        bike_profile_path = self._resolve_bike_profile_path()

        try:
            with tempfile.TemporaryDirectory(
                prefix=f"{self.source.source_id}_",
                dir=str(self.source.staging_dir),
            ) as tmpdir:
                csv_path, log_metadata_path = self._extract_candidate(candidate, Path(tmpdir))

                results = preprocess_session(
                    str(csv_path),
                    preprocess_config=self.preprocess_config,
                    fit_import=self._import_agent_fit_import_config(),
                    bike_profile_path=str(bike_profile_path),
                    log_metadata_path=str(log_metadata_path),
                    timezone=self.source.logger_timezone,
                    include_events=True,
                    include_metrics=True,
                )

                session = results["session"]
                session_id = str(session["session_id"])
                run_id = self._make_unique_run_id()
                ensure_run_is_new(self.store, run_id=run_id, force=False)
                ensure_session_is_new(self.store, run_id=run_id, session_id=session_id, force=False)

                copied_csv_sha256 = copy_raw_csv_to_source(
                    store=self.store,
                    run_id=run_id,
                    session_id=session_id,
                    csv_path=csv_path,
                )

                save_session_artifacts(
                    self.store,
                    run_id=run_id,
                    session_id=session_id,
                    session_df=session["df"],
                    session_meta=session["meta"],
                    secondary_stream_dfs=session.get("stream_dfs"),
                    secondary_stream_meta=session.get("meta", {}).get("secondary_streams"),
                )

                events_df = results.get("events", pd.DataFrame())
                metrics_df = results.get("metrics", pd.DataFrame())

                source_manifest = {
                    "path": "source/input.csv",
                    "sha256": copied_csv_sha256,
                    "import_mode": "import_agent_archive_v1",
                    "import_source_id": self.source.source_id,
                    "import_source_type": self.source.source_type,
                    "import_source_config_path": str(self.source.config_path),
                    "original_archive_filename": candidate.archive_name,
                    "original_archive_sha256": candidate.archive_sha256,
                    "original_archive_path": str(candidate.inbox_archive_path),
                    "archive_csv_member": candidate.contract.csv_member_name,
                    "archive_csv_sha256": candidate.contract.csv_sha256,
                    "archive_log_metadata_member": candidate.contract.log_metadata_member_name,
                    "archive_log_metadata_sha256": candidate.contract.log_metadata_sha256,
                    "raw_session_identity": candidate.raw_session_identity,
                    "source_identity": candidate.raw_session_identity,
                    "source_identity_kind": "raw_session_identity",
                    "input_kind": "archive",
                    "processing_key": candidate.processing_key,
                }
                if self.source.logger_timezone is not None:
                    source_manifest["logger_timezone_fallback"] = self.source.logger_timezone
                if self.source.source_type == SOURCE_TYPE_LOGGER_WIFI and self.source.logger_wifi is not None:
                    source_manifest["remote_source"] = {
                        "kind": SOURCE_TYPE_LOGGER_WIFI,
                        "logger_id": self.source.logger_wifi.logger_id,
                        "base_url": self.source.logger_wifi.base_url,
                    }

                session_source = session.get("source", {}) if isinstance(session.get("source"), Mapping) else {}
                aux_manifest: list[Dict[str, Any]] = []
                try:
                    aux_manifest = copy_session_aux_sources(
                        store=self.store,
                        run_id=run_id,
                        session_id=session_id,
                        aux_sources=session_source.get("aux_sources"),
                    )
                except Exception as exc:
                    logger.warning("Auxiliary source copy failed for %s: %s", session_id, exc)
                    source_manifest["aux_source_copy_error"] = f"{type(exc).__name__}: {exc}"
                if aux_manifest:
                    source_manifest["aux_sources"] = aux_manifest

                write_session_manifest(
                    self.store,
                    run_id=run_id,
                    session_id=session_id,
                    contracts={"session": "v0.x", "events": "v0.x", "metrics": "v0.x"},
                    source=source_manifest,
                    summary=self._session_summary(session),
                )

                schema_path = _optional_text(self.preprocess_config.get("schema_path"))
                if schema_path and isinstance(events_df, pd.DataFrame) and not events_df.empty:
                    write_events_partitioned_by_schema_id(
                        store=self.store,
                        run_id=run_id,
                        session_id=session_id,
                        events_df=events_df,
                        schema_path=Path(schema_path),
                    )
                if isinstance(metrics_df, pd.DataFrame) and not metrics_df.empty:
                    write_metrics_partitioned_by_schema_id(
                        store=self.store,
                        run_id=run_id,
                        session_id=session_id,
                        metrics_df=metrics_df,
                    )

                data_syn_bike_export_record = self._write_data_syn_bike_outputs_if_enabled(
                    session=session,
                    run_id=run_id,
                    session_id=session_id,
                    bike_profile_path=bike_profile_path,
                )
                session_note_record = self._write_draft_session_note_if_enabled(
                    run_id=run_id,
                    session_id=session_id,
                    bike_profile_path=bike_profile_path,
                )

                archive_import_config = {
                    "schema": IMPORT_SOURCE_SCHEMA,
                    "version": IMPORT_SOURCE_VERSION,
                    "archive_sha256": candidate.archive_sha256,
                    "raw_session_identity": candidate.raw_session_identity,
                    "processing_key": candidate.processing_key,
                    "preprocess_profile_path": str(preprocess_profile_path),
                    "preprocess_profile_selection_path": str(self.source.preprocess_profile_path),
                    "preprocess_profile_sha256": self.preprocess_profile_sha256,
                    "bike_profile_path": str(bike_profile_path),
                    "bike_profile_selection_path": str(self.source.bike_profile_path),
                    "bike_profile_sha256": self.bike_profile_sha256,
                }
                if data_syn_bike_export_record is not None:
                    archive_import_config["data_syn_bike_export"] = data_syn_bike_export_record
                if session_note_record is not None:
                    archive_import_config["session_note"] = session_note_record

                write_run_manifest(
                    self.store,
                    run_id=run_id,
                    session_ids=[session_id],
                    timezone_label=self.source.run_tz_label,
                    description=self.source.description,
                    pipeline_config={
                        "import_source": {
                            "source_id": self.source.source_id,
                            "source_type": self.source.source_type,
                            "config_path": str(self.source.config_path),
                        },
                        "archive_import": archive_import_config,
                    },
                )

            done_path = _move_to_dir_unique(candidate.claimed_archive_path, self.source.done_dir)
            record = {
                "status": "succeeded",
                "source_id": self.source.source_id,
                "archive_path": str(candidate.inbox_archive_path),
                "archive_sha256": candidate.archive_sha256,
                "done_archive_path": str(done_path),
                "archive_csv_member": candidate.contract.csv_member_name,
                "archive_log_metadata_member": candidate.contract.log_metadata_member_name,
                "raw_session_identity": candidate.raw_session_identity,
                "processing_key": candidate.processing_key,
                "run_id": run_id,
                "session_id": session_id,
                "session_key": f"{run_id}/{session_id}",
                "session_manifest_path": str(self.store.path_session_manifest(run_id, session_id)),
                "updated_at": _utcnow_iso(),
            }
            if session_note_record is not None:
                record["session_note"] = session_note_record
            self.state.upsert(candidate.processing_key, record)
            logger.info(
                "Imported %s -> run=%s session=%s",
                candidate.inbox_archive_path,
                run_id,
                session_id,
            )
            return record

        except Exception:
            if run_id is not None:
                self._cleanup_failed_run(run_id)
            raise

    def _cleanup_failed_run(self, run_id: str) -> None:
        run_dir = self.store.run_dir(run_id)
        if not run_dir.exists():
            return
        try:
            shutil.rmtree(run_dir)
        except Exception:
            logger.warning("Failed to clean up partial run directory after import error: %s", run_dir)

    def _make_unique_run_id(self) -> str:
        base = make_run_id(tz_label=self.source.run_tz_label)
        run_id = base
        suffix = 1
        while self.store.run_dir(run_id).exists():
            run_id = f"{base}_{suffix:02d}"
            suffix += 1
        return run_id

    def _session_summary(self, session: Mapping[str, Any]) -> Dict[str, Any]:
        df = session.get("df")
        if not isinstance(df, pd.DataFrame) or df.empty or "time_s" not in df.columns:
            return {}
        return {
            "n_rows": int(len(df)),
            "t_start_s": float(df["time_s"].iloc[0]),
            "t_end_s": float(df["time_s"].iloc[-1]),
        }


class ImportAgentSupervisor:
    """
    Supervises one or more import-source runners inside a single process.

    This is the app-facing orchestration layer that future tray/desktop shells
    can use instead of spawning one watcher process per source.
    """

    def __init__(self, sources: Sequence[ImportSourceConfig]) -> None:
        self._source_ids: list[str] = []
        self._states: dict[str, ImportSourceSupervisorState] = {}
        seen_ids: set[str] = set()

        for source in sources:
            if source.source_id in seen_ids:
                raise ValueError(f"Duplicate import source id: {source.source_id!r}")
            seen_ids.add(source.source_id)
            state = ImportSourceSupervisorState(runner=ImportSourceRunner(source))
            self._source_ids.append(source.source_id)
            self._states[source.source_id] = state

    @classmethod
    def from_paths(cls, paths_or_dirs: Sequence[str | Path]) -> "ImportAgentSupervisor":
        return cls(load_import_sources(paths_or_dirs))

    def source_ids(self) -> list[str]:
        return list(self._source_ids)

    def get_state(self, source_id: str) -> ImportSourceSupervisorState:
        try:
            return self._states[source_id]
        except KeyError:
            raise KeyError(f"Unknown import source id: {source_id!r}") from None

    def pause_source(self, source_id: str) -> None:
        self.get_state(source_id).paused = True

    def resume_source(self, source_id: str, *, scan_immediately: bool = True) -> None:
        state = self.get_state(source_id)
        state.paused = False
        if scan_immediately:
            state.next_due_s = 0.0

    def scan_source_once(
        self,
        source_id: str,
        *,
        now_s: Optional[float] = None,
        include_paused: bool = False,
    ) -> Optional[Dict[str, Any]]:
        state = self.get_state(source_id)
        if state.paused and not include_paused:
            return None

        state.last_scan_started_at = _utcnow_iso()
        report = state.runner.scan_once()
        state.last_scan_completed_at = _utcnow_iso()
        state.last_report = report
        next_due_base = time.time() if now_s is None else float(now_s)
        state.next_due_s = next_due_base + float(state.runner.source.poll_interval_s)
        return report

    def scan_all_once(self, *, include_paused: bool = False, now_s: Optional[float] = None) -> Dict[str, Any]:
        reports: list[Dict[str, Any]] = []
        skipped_paused: list[str] = []

        for source_id in self._source_ids:
            report = self.scan_source_once(
                source_id,
                now_s=now_s,
                include_paused=include_paused,
            )
            if report is None:
                skipped_paused.append(source_id)
                continue
            reports.append(report)

        return {
            "sources": reports,
            "totals": _aggregate_reports(reports),
            "skipped_paused_sources": skipped_paused,
        }

    def scan_due(self, *, now_s: Optional[float] = None) -> list[Dict[str, Any]]:
        due_reports: list[Dict[str, Any]] = []
        current_s = time.time() if now_s is None else float(now_s)

        for source_id in self._source_ids:
            state = self.get_state(source_id)
            if state.paused or current_s < float(state.next_due_s):
                continue
            report = self.scan_source_once(source_id, now_s=current_s)
            if report is not None:
                due_reports.append(report)

        return due_reports

    def watch(
        self,
        *,
        max_loops: Optional[int] = None,
        time_fn: Any = time.time,
        sleep_fn: Any = time.sleep,
    ) -> None:
        loops = 0

        while True:
            now_s = float(time_fn())
            reports = self.scan_due(now_s=now_s)
            for report in reports:
                totals = _aggregate_reports([report])
                logger.info(
                    "Import scan complete: source=%s seen=%d imported=%d deferred=%d dup_ok=%d dup_failed=%d failed=%d",
                    report["source_id"],
                    totals["seen"],
                    totals["imported"],
                    totals["deferred_unsettled"],
                    totals["skipped_succeeded"],
                    totals["skipped_failed"],
                    totals["failed"],
                )

            loops += 1
            if max_loops is not None and loops >= int(max_loops):
                return

            if not self._source_ids:
                return

            active_due_times = [
                max(float(self.get_state(source_id).next_due_s) - now_s, 0.0)
                for source_id in self._source_ids
                if not self.get_state(source_id).paused
            ]
            if not active_due_times:
                sleep_fn(0.25)
                continue

            if not reports:
                sleep_fn(min(max(0.1, min(active_due_times)), 5.0))

    def snapshot(self, *, now_s: Optional[float] = None) -> Dict[str, Any]:
        current_s = time.time() if now_s is None else float(now_s)
        sources: list[Dict[str, Any]] = []

        for source_id in self._source_ids:
            state = self.get_state(source_id)
            report = state.last_report
            sources.append(
                {
                    "source_id": source_id,
                    "source_type": state.runner.source.source_type,
                    "config_path": str(state.runner.source.config_path),
                    "source_root": str(state.runner.source.source_root),
                    "artifacts_dir": str(state.runner.source.artifacts_dir),
                    "poll_interval_s": float(state.runner.source.poll_interval_s),
                    "paused": state.paused,
                    "next_due_s": float(state.next_due_s),
                    "due_now": (not state.paused) and current_s >= float(state.next_due_s),
                    "last_scan_started_at": state.last_scan_started_at,
                    "last_scan_completed_at": state.last_scan_completed_at,
                    "last_totals": _aggregate_reports([report]) if report is not None else None,
                }
            )

        return {
            "source_count": len(self._source_ids),
            "active_source_count": sum(0 if self.get_state(source_id).paused else 1 for source_id in self._source_ids),
            "sources": sources,
        }


def load_import_sources(paths_or_dirs: Sequence[str | Path]) -> list[ImportSourceConfig]:
    seen: set[str] = set()
    sources: list[ImportSourceConfig] = []
    for item in paths_or_dirs:
        source = load_import_source_config(item)
        key = _path_key(source.config_path)
        if key in seen:
            continue
        seen.add(key)
        sources.append(source)
    return sources


def validate_import_sources(paths_or_dirs: Sequence[str | Path]) -> list[Dict[str, Any]]:
    results: list[Dict[str, Any]] = []
    for source in load_import_sources(paths_or_dirs):
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


def run_sources_once(paths_or_dirs: Sequence[str | Path]) -> Dict[str, Any]:
    supervisor = ImportAgentSupervisor.from_paths(paths_or_dirs)
    return supervisor.scan_all_once()


def watch_sources(
    paths_or_dirs: Sequence[str | Path],
    *,
    max_loops: Optional[int] = None,
) -> None:
    supervisor = ImportAgentSupervisor.from_paths(paths_or_dirs)
    supervisor.watch(max_loops=max_loops)


def _aggregate_reports(reports: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    totals = {
        "seen": 0,
        "deferred_unsettled": 0,
        "skipped_succeeded": 0,
        "skipped_failed": 0,
        "imported": 0,
        "failed": 0,
    }
    for report in reports:
        totals["seen"] += int(report.get("seen", 0))
        for key in (
            "deferred_unsettled",
            "skipped_succeeded",
            "skipped_failed",
            "imported",
            "failed",
        ):
            totals[key] += len(report.get(key, []))
    return totals


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the BODAQS archive import agent over one or more import_source.json sources."
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Python logging level (default: INFO).",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate one or more import sources.")
    validate_parser.add_argument("sources", nargs="+", help="Source directories or import_source.json paths.")

    once_parser = subparsers.add_parser("once", help="Scan sources once and import any ready archives.")
    once_parser.add_argument("sources", nargs="+", help="Source directories or import_source.json paths.")

    watch_parser = subparsers.add_parser("watch", help="Poll sources continuously for new ready archives.")
    watch_parser.add_argument("sources", nargs="+", help="Source directories or import_source.json paths.")
    watch_parser.add_argument(
        "--max-loops",
        type=int,
        default=None,
        help="Optional test/debug limit on scheduler loops.",
    )
    return parser


def _print_validate_results(results: Sequence[Mapping[str, Any]]) -> None:
    for result in results:
        print(f"Source: {result['source_id']}")
        print(f"Config: {result['config_path']}")
        errors = result.get("errors", [])
        warnings = result.get("warnings", [])
        if errors:
            print("Errors:")
            for item in errors:
                print(f"  - {item}")
        else:
            print("Errors: none")
        if warnings:
            print("Warnings:")
            for item in warnings:
                print(f"  - {item}")
        else:
            print("Warnings: none")


def _print_run_report(report: Mapping[str, Any]) -> None:
    totals = report.get("totals", {})
    print(f"Seen: {int(totals.get('seen', 0))}")
    print(f"Imported: {int(totals.get('imported', 0))}")
    print(f"Deferred (unsettled): {int(totals.get('deferred_unsettled', 0))}")
    print(f"Skipped duplicate success: {int(totals.get('skipped_succeeded', 0))}")
    print(f"Skipped duplicate failure: {int(totals.get('skipped_failed', 0))}")
    print(f"Failed this scan: {int(totals.get('failed', 0))}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.command == "validate":
        results = validate_import_sources(args.sources)
        _print_validate_results(results)
        return 1 if any(result.get("errors") for result in results) else 0

    if args.command == "once":
        report = run_sources_once(args.sources)
        _print_run_report(report)
        return 1 if int(report.get("totals", {}).get("failed", 0)) > 0 else 0

    if args.command == "watch":
        try:
            watch_sources(args.sources, max_loops=args.max_loops)
        except KeyboardInterrupt:
            logger.info("Import watch interrupted by user")
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
