from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Dict, Optional


PREPROCESS_PROFILE_SCHEMA = "bodaqs.preprocess_profile"
PREPROCESS_PROFILE_VERSION = 1
DEFAULT_PREPROCESS_PROFILE_DIR = Path("config/preprocess_profiles")
DEFAULT_PREPROCESS_PROFILE_CONFIG: Dict[str, Any] = {
    "schema_path": "event schema/event_schema.yaml",
    "strict": False,
    "fit_import": {
        "enabled": False,
        "fit_dir": "Garmin/FIT",
        "field_allowlist": [
            "position_lat",
            "position_long",
            "altitude",
            "enhanced_altitude",
            "speed",
            "enhanced_speed",
            "distance",
            "grade",
            "heading",
        ],
        "ambiguity_policy": "require_binding",
        "partial_overlap": "allow",
        "persist_raw_stream": True,
        "resample_to_primary": True,
        "resample_method": "linear",
        "raw_stream_name": "gps_fit",
        "bindings_path": "analysis/config/fit_bindings_v1.json",
    },
    "generic_log_metadata_paths": [],
    "bike_profile_path": "config/bike_profiles/example_enduro_bike_v1.json",
    "bike_profile_id": None,
    "zeroing_enabled": False,
    "zero_window_s": 0.4,
    "zero_min_samples": 10,
    "clip_0_1": False,
    "butterworth_smoothing": [],
    "butterworth_generate_residuals": False,
    "active_signal_disp_col": None,
    "active_signal_vel_col": None,
    "active_disp_thresh": 20.0,
    "active_vel_thresh": 50.0,
    "active_window": "500ms",
    "active_padding": "1s",
    "active_min_seg": "3s",
}

_REQUIRED_CONFIG_KEYS = {
    "schema_path",
    "strict",
    "zeroing_enabled",
    "zero_window_s",
    "zero_min_samples",
    "clip_0_1",
    "butterworth_smoothing",
    "butterworth_generate_residuals",
    "active_signal_disp_col",
    "active_disp_thresh",
    "active_vel_thresh",
    "active_window",
    "active_padding",
    "active_min_seg",
}


def default_preprocess_config(**overrides: Any) -> Dict[str, Any]:
    """Return a validated default preprocess config payload with optional overrides."""
    config = copy.deepcopy(DEFAULT_PREPROCESS_PROFILE_CONFIG)
    config.update(overrides)
    validate_preprocess_config(config)
    return config


def make_preprocess_profile(
    profile_id: str,
    *,
    config: Optional[Mapping[str, Any]] = None,
    description: Optional[str] = None,
    version: int = PREPROCESS_PROFILE_VERSION,
    extra_fields: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a validated preprocess profile document."""
    if not _nonempty_str(profile_id):
        raise ValueError("profile_id must be a non-empty string")
    if int(version) != PREPROCESS_PROFILE_VERSION:
        raise ValueError(
            f"Unsupported preprocess profile version: {version!r} "
            f"(expected {PREPROCESS_PROFILE_VERSION})"
        )

    cfg = copy.deepcopy(dict(config)) if config is not None else default_preprocess_config()
    validate_preprocess_config(cfg)

    profile: Dict[str, Any] = {
        "schema": PREPROCESS_PROFILE_SCHEMA,
        "version": int(version),
        "profile_id": str(profile_id).strip(),
    }
    if _nonempty_str(description):
        profile["description"] = str(description).strip()
    if extra_fields:
        profile.update(copy.deepcopy(dict(extra_fields)))
    profile["config"] = cfg

    validate_preprocess_profile(profile)
    return profile


def preprocess_profile_filename(profile_id: str, *, version: int = PREPROCESS_PROFILE_VERSION) -> str:
    """Return the conventional filename for a preprocess profile id."""
    if not _nonempty_str(profile_id):
        raise ValueError("profile_id must be a non-empty string")
    safe_id = _safe_profile_id(str(profile_id))
    return f"{safe_id}_v{int(version)}.json"


def preprocess_profile_path(
    profile_id: str,
    *,
    directory: str | Path = DEFAULT_PREPROCESS_PROFILE_DIR,
    version: int = PREPROCESS_PROFILE_VERSION,
) -> Path:
    """Return the conventional profile path for a profile id and directory."""
    return Path(directory) / preprocess_profile_filename(profile_id, version=version)


def save_preprocess_profile(
    profile: Mapping[str, Any],
    path: str | Path,
    *,
    overwrite: bool = True,
    create_dirs: bool = True,
) -> Path:
    """Validate and save a preprocess profile JSON document."""
    validate_preprocess_profile(profile, path=path)
    out_path = Path(path)
    if out_path.exists() and not overwrite:
        raise FileExistsError(f"Preprocess profile already exists: {out_path}")
    if create_dirs:
        out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(dict(profile), indent=2) + "\n", encoding="utf-8")
    return out_path


def discover_preprocess_profiles(
    directory: str | Path = DEFAULT_PREPROCESS_PROFILE_DIR,
    *,
    pattern: str = "*.json",
    include_invalid: bool = False,
) -> list[Dict[str, Any]]:
    """
    Discover preprocess profile JSON files in a directory.

    Returns lightweight records suitable for UI menus. Invalid files are skipped
    by default; set ``include_invalid=True`` to include error records.
    """
    root = Path(directory)
    if not root.exists():
        return []

    records: list[Dict[str, Any]] = []
    for path in sorted(root.glob(pattern)):
        if not path.is_file():
            continue
        try:
            profile = load_preprocess_profile(path)
            records.append(
                {
                    "path": str(path),
                    "profile_id": str(profile.get("profile_id")),
                    "version": int(profile.get("version", PREPROCESS_PROFILE_VERSION)),
                    "description": profile.get("description"),
                    "valid": True,
                }
            )
        except Exception as exc:
            if include_invalid:
                records.append(
                    {
                        "path": str(path),
                        "profile_id": None,
                        "version": None,
                        "description": None,
                        "valid": False,
                        "error": str(exc),
                    }
                )

    return sorted(records, key=lambda r: (str(r.get("profile_id") or ""), str(r.get("path") or "")))


def load_preprocess_profile(path: str | Path) -> Dict[str, Any]:
    """Load and validate a BODAQS preprocess profile document."""
    profile_path = Path(path)
    if not profile_path.exists():
        raise FileNotFoundError(f"Preprocess profile not found: {profile_path}")

    with profile_path.open("r", encoding="utf-8") as f:
        profile = json.load(f)

    validate_preprocess_profile(profile, path=profile_path)
    return profile


def load_preprocess_config(path: str | Path) -> Dict[str, Any]:
    """Load a preprocess profile and return a copy of its config payload."""
    return preprocess_config_from_profile(load_preprocess_profile(path))


def preprocess_config_from_profile(profile: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a validated copy of ``profile['config']``."""
    validate_preprocess_profile(profile)
    return copy.deepcopy(dict(profile["config"]))


def validate_preprocess_profile(profile: Mapping[str, Any], *, path: Optional[str | Path] = None) -> None:
    """Validate the preprocess profile fields consumed by the public pipeline API."""
    label = f" ({path})" if path is not None else ""
    if not isinstance(profile, Mapping):
        raise ValueError(f"Preprocess profile must be a JSON object{label}")
    if profile.get("schema") != PREPROCESS_PROFILE_SCHEMA:
        raise ValueError(
            f"Unexpected preprocess profile schema{label}: {profile.get('schema')!r} "
            f"(expected {PREPROCESS_PROFILE_SCHEMA!r})"
        )
    if int(profile.get("version", -1)) != PREPROCESS_PROFILE_VERSION:
        raise ValueError(
            f"Unexpected preprocess profile version{label}: {profile.get('version')!r} "
            f"(expected {PREPROCESS_PROFILE_VERSION})"
        )
    if not _nonempty_str(profile.get("profile_id")):
        raise ValueError(f"Preprocess profile missing non-empty 'profile_id'{label}")

    config = profile.get("config")
    if not isinstance(config, Mapping):
        raise ValueError(f"Preprocess profile missing 'config' object{label}")
    validate_preprocess_config(config, label=label)


def validate_preprocess_config(config: Mapping[str, Any], *, label: str = "") -> None:
    """Validate a preprocess config payload without requiring the root profile wrapper."""
    if not isinstance(config, Mapping):
        raise ValueError(f"Preprocess config must be an object{label}")

    missing = sorted(_REQUIRED_CONFIG_KEYS - set(config.keys()))
    if missing:
        raise ValueError(f"Preprocess config missing required keys{label}: {', '.join(missing)}")

    if not _nonempty_str(config.get("schema_path")):
        raise ValueError(f"Preprocess config 'schema_path' must be a non-empty string{label}")
    if not isinstance(config.get("strict"), bool):
        raise ValueError(f"Preprocess config 'strict' must be boolean{label}")
    if not isinstance(config.get("zeroing_enabled"), bool):
        raise ValueError(f"Preprocess config 'zeroing_enabled' must be boolean{label}")
    if not isinstance(config.get("clip_0_1"), bool):
        raise ValueError(f"Preprocess config 'clip_0_1' must be boolean{label}")
    if not isinstance(config.get("butterworth_smoothing"), list):
        raise ValueError(f"Preprocess config 'butterworth_smoothing' must be a list{label}")
    if not isinstance(config.get("butterworth_generate_residuals"), bool):
        raise ValueError(f"Preprocess config 'butterworth_generate_residuals' must be boolean{label}")

    for key in ("zero_window_s", "active_disp_thresh", "active_vel_thresh"):
        _require_number(config, key, label=label)
    _require_int(config, "zero_min_samples", label=label)

    for key in ("active_window", "active_padding", "active_min_seg"):
        if not _nonempty_str(config.get(key)):
            raise ValueError(f"Preprocess config {key!r} must be a non-empty string{label}")

    if config.get("active_signal_disp_col") is not None and not _nonempty_str(config.get("active_signal_disp_col")):
        raise ValueError(f"Preprocess config 'active_signal_disp_col' must be string or null{label}")
    if config.get("active_signal_vel_col") is not None and not _nonempty_str(config.get("active_signal_vel_col")):
        raise ValueError(f"Preprocess config 'active_signal_vel_col' must be string or null{label}")

    bike_profile_path = config.get("bike_profile_path")
    normalize_ranges = config.get("normalize_ranges")
    if bike_profile_path is None and normalize_ranges is None:
        raise ValueError(
            "Preprocess config requires either 'bike_profile_path' or legacy 'normalize_ranges'"
            f"{label}"
        )
    if bike_profile_path is not None and not _nonempty_str(bike_profile_path):
        raise ValueError(f"Preprocess config 'bike_profile_path' must be string or null{label}")
    if normalize_ranges is not None:
        _validate_legacy_normalize_ranges(normalize_ranges, label=label)

    generic_log_metadata_paths = config.get("generic_log_metadata_paths")
    if generic_log_metadata_paths is not None:
        if not isinstance(generic_log_metadata_paths, Sequence) or isinstance(
            generic_log_metadata_paths, (str, bytes, bytearray)
        ):
            raise ValueError(f"Preprocess config 'generic_log_metadata_paths' must be an array{label}")
        for i, item in enumerate(generic_log_metadata_paths):
            if not _nonempty_str(item):
                raise ValueError(f"Preprocess config generic_log_metadata_paths[{i}] must be a string{label}")

    fit_import = config.get("fit_import")
    if fit_import is not None and not isinstance(fit_import, Mapping):
        raise ValueError(f"Preprocess config 'fit_import' must be object or null{label}")


def resolve_preprocess_config_paths(
    config: Mapping[str, Any],
    *,
    base_dir: str | Path,
) -> Dict[str, Any]:
    """
    Return a copy of a preprocess config with path-like fields resolved.

    This is deliberately a helper rather than hidden magic: notebooks/CLIs can
    choose whether profile-relative, notebook-relative, or absolute paths are
    appropriate for their workflow.
    """
    validate_preprocess_config(config)
    base = Path(base_dir)
    resolved = copy.deepcopy(dict(config))

    for key in ("schema_path", "bike_profile_path"):
        if resolved.get(key) is not None:
            resolved[key] = str(_resolve_path(resolved[key], base_dir=base))

    paths = resolved.get("generic_log_metadata_paths")
    if isinstance(paths, Sequence) and not isinstance(paths, (str, bytes, bytearray)):
        resolved["generic_log_metadata_paths"] = [str(_resolve_path(p, base_dir=base)) for p in paths]

    fit_import = resolved.get("fit_import")
    if isinstance(fit_import, dict):
        for key in ("fit_dir", "bindings_path"):
            if fit_import.get(key):
                fit_import[key] = str(_resolve_path(fit_import[key], base_dir=base))

    return resolved


def _resolve_path(value: Any, *, base_dir: Path) -> Path:
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (base_dir / path).resolve()


def _validate_legacy_normalize_ranges(value: Any, *, label: str) -> None:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"Preprocess config legacy 'normalize_ranges' must be a non-empty object{label}")
    for key, item in value.items():
        if not _nonempty_str(key):
            raise ValueError(f"Preprocess config legacy 'normalize_ranges' keys must be non-empty strings{label}")
        try:
            number = float(item)
        except (TypeError, ValueError):
            raise ValueError(f"Preprocess config legacy 'normalize_ranges' values must be numeric{label}") from None
        if number <= 0:
            raise ValueError(f"Preprocess config legacy 'normalize_ranges' values must be > 0{label}")


def _require_number(config: Mapping[str, Any], key: str, *, label: str) -> None:
    try:
        float(config.get(key))
    except (TypeError, ValueError):
        raise ValueError(f"Preprocess config {key!r} must be numeric{label}") from None


def _require_int(config: Mapping[str, Any], key: str, *, label: str) -> None:
    try:
        int(config.get(key))
    except (TypeError, ValueError):
        raise ValueError(f"Preprocess config {key!r} must be an integer{label}") from None


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _safe_profile_id(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        raise ValueError("profile_id must contain at least one alphanumeric character")
    return text
