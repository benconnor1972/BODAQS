from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping
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
    },
    "zeroing_enabled": False,
    "zero_window_s": 0.4,
    "zero_min_samples": 10,
    "clip_0_1": False,
    "motion_derivation": {
        "enabled": False,
        "sources": [
            {
                "id": "rear_wheel",
                "selector": {
                    "end": "rear",
                    "quantity": "disp",
                    "domain": "wheel",
                    "unit": "mm",
                },
            }
        ],
        "primary": {
            "displacement_lowpass_hz": 80.0,
            "displacement_lowpass_order": 4,
            "velocity_sg_window_ms": 20.0,
            "acceleration_sg_window_ms": 40.0,
            "sg_polyorder": 3,
            "velocity_lowpass_hz": 60.0,
            "velocity_lowpass_order": 4,
            "acceleration_lowpass_hz": 30.0,
            "acceleration_lowpass_order": 4,
        },
        "secondary": [],
    },
    "butterworth_smoothing": [],
    "butterworth_generate_residuals": False,
    "active_signal_disp_selector": {
        "end": "rear",
        "quantity": "disp",
        "domain": "suspension",
        "unit": "mm",
    },
    "active_signal_vel_selector": {
        "end": "rear",
        "quantity": "vel",
        "domain": "suspension",
        "unit": "mm/s",
    },
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
    "active_signal_disp_selector",
    "active_disp_thresh",
    "active_vel_thresh",
    "active_window",
    "active_padding",
    "active_min_seg",
}

_FORBIDDEN_CONFIG_KEYS = {
    "generic_log_metadata_paths",
    "bike_profile_path",
    "bike_profile_id",
    "normalize_ranges",
    "prompt_for_descriptions",
    "active_signal_disp_col",
    "active_signal_vel_col",
}

_FORBIDDEN_FIT_IMPORT_KEYS = {
    "fit_dir",
    "bindings_path",
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
    forbidden = sorted(_FORBIDDEN_CONFIG_KEYS & set(config.keys()))
    if forbidden:
        raise ValueError(
            "Preprocess config contains runtime binding field(s) that do not belong in a "
            f"preprocess profile{label}: {', '.join(forbidden)}"
        )

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
    _validate_motion_derivation(config.get("motion_derivation"), label=label)

    for key in ("zero_window_s", "active_disp_thresh", "active_vel_thresh"):
        _require_number(config, key, label=label)
    _require_int(config, "zero_min_samples", label=label)

    for key in ("active_window", "active_padding", "active_min_seg"):
        if not _nonempty_str(config.get(key)):
            raise ValueError(f"Preprocess config {key!r} must be a non-empty string{label}")

    _validate_signal_selector(
        config.get("active_signal_disp_selector"),
        key="active_signal_disp_selector",
        label=label,
        required=False,
    )
    _validate_signal_selector(
        config.get("active_signal_vel_selector"),
        key="active_signal_vel_selector",
        label=label,
        required=False,
    )
    if config.get("active_signal_disp_selector") is None and config.get("active_signal_vel_selector") is not None:
        raise ValueError(
            "Preprocess config 'active_signal_vel_selector' must be null when "
            f"'active_signal_disp_selector' is null{label}"
        )

    fit_import = config.get("fit_import")
    if fit_import is not None and not isinstance(fit_import, Mapping):
        raise ValueError(f"Preprocess config 'fit_import' must be object or null{label}")
    if isinstance(fit_import, Mapping):
        forbidden_fit = sorted(_FORBIDDEN_FIT_IMPORT_KEYS & set(fit_import.keys()))
        if forbidden_fit:
            raise ValueError(
                "Preprocess config fit_import contains runtime path field(s) that do not belong "
                f"in a preprocess profile{label}: {', '.join(forbidden_fit)}"
            )


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

    if resolved.get("schema_path") is not None:
        resolved["schema_path"] = str(_resolve_path(resolved["schema_path"], base_dir=base))

    return resolved


def _resolve_path(value: Any, *, base_dir: Path) -> Path:
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (base_dir / path).resolve()


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


def _require_positive_number(config: Mapping[str, Any], key: str, *, label: str) -> None:
    _require_number(config, key, label=label)
    try:
        value = float(config.get(key))
    except (TypeError, ValueError):
        raise ValueError(f"Preprocess config {key!r} must be numeric{label}") from None
    if value <= 0:
        raise ValueError(f"Preprocess config {key!r} must be > 0{label}")


def _require_positive_int(config: Mapping[str, Any], key: str, *, label: str) -> None:
    _require_int(config, key, label=label)
    try:
        value = int(config.get(key))
    except (TypeError, ValueError):
        raise ValueError(f"Preprocess config {key!r} must be an integer{label}") from None
    if value <= 0:
        raise ValueError(f"Preprocess config {key!r} must be a positive integer{label}")


def _validate_motion_derivation(value: Any, *, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise ValueError(f"Preprocess config 'motion_derivation' must be object or null{label}")

    enabled = value.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError(f"Preprocess config 'motion_derivation.enabled' must be boolean{label}")

    sources = value.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError(f"Preprocess config 'motion_derivation.sources' must be a list{label}")
    if enabled and not sources:
        raise ValueError(f"Preprocess config 'motion_derivation.sources' must not be empty when enabled{label}")
    seen_source_ids: set[str] = set()
    for idx, source in enumerate(sources):
        if not isinstance(source, Mapping):
            raise ValueError(f"Preprocess config 'motion_derivation.sources[{idx}]' must be an object{label}")
        source_id = source.get("id")
        if not _nonempty_str(source_id):
            raise ValueError(f"Preprocess config 'motion_derivation.sources[{idx}].id' must be a non-empty string{label}")
        if str(source_id) in seen_source_ids:
            raise ValueError(f"Duplicate motion derivation source id{label}: {source_id!r}")
        seen_source_ids.add(str(source_id))
        _validate_signal_selector(
            source.get("selector"),
            key=f"motion_derivation.sources[{idx}].selector",
            label=label,
            required=True,
        )

    primary = value.get("primary")
    if enabled and not isinstance(primary, Mapping):
        raise ValueError(f"Preprocess config 'motion_derivation.primary' must be an object when enabled{label}")
    if isinstance(primary, Mapping):
        _validate_motion_profile(primary, key="motion_derivation.primary", label=label, require_id=False)

    secondary = value.get("secondary", [])
    if not isinstance(secondary, list):
        raise ValueError(f"Preprocess config 'motion_derivation.secondary' must be a list{label}")
    seen_secondary_ids: set[str] = set()
    for idx, profile in enumerate(secondary):
        if not isinstance(profile, Mapping):
            raise ValueError(f"Preprocess config 'motion_derivation.secondary[{idx}]' must be an object{label}")
        profile_id = profile.get("id")
        if not _nonempty_str(profile_id):
            raise ValueError(
                f"Preprocess config 'motion_derivation.secondary[{idx}].id' must be a non-empty string{label}"
            )
        if str(profile_id) in seen_secondary_ids:
            raise ValueError(f"Duplicate motion derivation secondary profile id{label}: {profile_id!r}")
        seen_secondary_ids.add(str(profile_id))
        _validate_motion_profile(
            profile,
            key=f"motion_derivation.secondary[{idx}]",
            label=label,
            require_id=True,
        )


def _validate_motion_profile(profile: Mapping[str, Any], *, key: str, label: str, require_id: bool) -> None:
    if require_id and not _nonempty_str(profile.get("id")):
        raise ValueError(f"Preprocess config {key!r}.id must be a non-empty string{label}")

    required_positive_numbers = (
        "displacement_lowpass_hz",
        "velocity_sg_window_ms",
        "acceleration_sg_window_ms",
        "velocity_lowpass_hz",
        "acceleration_lowpass_hz",
    )
    required_positive_ints = (
        "displacement_lowpass_order",
        "sg_polyorder",
        "velocity_lowpass_order",
        "acceleration_lowpass_order",
    )

    for field in required_positive_numbers:
        _require_positive_number(profile, field, label=f"{label} ({key})")
    for field in required_positive_ints:
        _require_positive_int(profile, field, label=f"{label} ({key})")


def _validate_signal_selector(value: Any, *, key: str, label: str, required: bool) -> None:
    if value is None:
        if required:
            raise ValueError(f"Preprocess config {key!r} must be an object{label}")
        return
    if not isinstance(value, Mapping):
        raise ValueError(f"Preprocess config {key!r} must be object or null{label}")
    if not value:
        raise ValueError(f"Preprocess config {key!r} must not be empty when enabled{label}")
    for field, field_value in value.items():
        if field not in {
            "end",
            "quantity",
            "domain",
            "unit",
            "processing_role",
            "motion_source_id",
            "motion_profile_id",
        }:
            raise ValueError(f"Preprocess config {key!r} has unsupported selector field {field!r}{label}")
        if not _nonempty_str(field_value):
            raise ValueError(f"Preprocess config {key!r}.{field!s} must be a non-empty string{label}")


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _safe_profile_id(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        raise ValueError("profile_id must contain at least one alphanumeric character")
    return text
