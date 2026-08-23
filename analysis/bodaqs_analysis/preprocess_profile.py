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
    "gps_source_policy": {
        "preferred_source": "logger_then_fit",
        "preserve_all_sources": True,
        "build_logger_stream": True,
        "logger_stream_name": "gps_logger",
    },
    "imu_attitude": {
        "enabled": False,
        "required": False,
        "fixed_interval_tilt_smoother": {
            "enabled": True,
            "gps_translational_compensation": "when_qualified",
        },
        "inertial_dynamics": {
            "enabled": True,
            "include_world_frame": True,
            "include_angular_kinematics": True,
            "include_magnitudes": True,
        },
    },
    "zeroing_enabled": False,
    "zero_window_s": 0.4,
    "zero_min_samples": 10,
    "clip_0_1": False,
    "prefer_postprocessing_transformations": False,
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
    "activity_detection": {
        "enabled": True,
        "combination": "any",
        "fallback_to_legacy": True,
        "candidates": [
            {
                "id": "gps_speed",
                "type": "gps_speed",
                "speed_threshold_mps": 0.5,
                "max_gap_s": 5.0,
            },
            {
                "id": "rear_wheel_motion",
                "type": "wheel_motion",
                "disp_selector": {
                    "end": "rear",
                    "quantity": "disp",
                    "domain": "wheel",
                    "unit": "mm",
                },
                "vel_selector": {
                    "end": "rear",
                    "quantity": "vel",
                    "domain": "wheel",
                    "unit": "mm/s",
                },
            },
            {
                "id": "front_wheel_motion",
                "type": "wheel_motion",
                "disp_selector": {
                    "end": "front",
                    "quantity": "disp",
                    "domain": "wheel",
                    "unit": "mm",
                },
                "vel_selector": {
                    "end": "front",
                    "quantity": "vel",
                    "domain": "wheel",
                    "unit": "mm/s",
                },
            },
        ],
    },
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
    config = normalize_preprocess_config_keys(config)
    validate_preprocess_config(config)
    return config


def normalize_preprocess_config_keys(config: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a config copy using current field names."""
    out = copy.deepcopy(dict(config))
    if "prefer_postprocessing_transformations" not in out and "ignore_on_logger_transformations" in out:
        out["prefer_postprocessing_transformations"] = bool(out["ignore_on_logger_transformations"])
    out.pop("ignore_on_logger_transformations", None)
    return out


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

    cfg = normalize_preprocess_config_keys(config) if config is not None else default_preprocess_config()
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
    out_profile = copy.deepcopy(dict(profile))
    out_profile["config"] = normalize_preprocess_config_keys(out_profile["config"])
    out_path = Path(path)
    if out_path.exists() and not overwrite:
        raise FileExistsError(f"Preprocess profile already exists: {out_path}")
    if create_dirs:
        out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_profile, indent=2) + "\n", encoding="utf-8")
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
    profile["config"] = normalize_preprocess_config_keys(profile["config"])
    return profile


def load_preprocess_config(path: str | Path) -> Dict[str, Any]:
    """Load a preprocess profile and return a copy of its config payload."""
    return preprocess_config_from_profile(load_preprocess_profile(path))


def preprocess_config_from_profile(profile: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a validated copy of ``profile['config']``."""
    validate_preprocess_profile(profile)
    return normalize_preprocess_config_keys(profile["config"])


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
    if "prefer_postprocessing_transformations" in config and not isinstance(
        config.get("prefer_postprocessing_transformations"), bool
    ):
        raise ValueError(f"Preprocess config 'prefer_postprocessing_transformations' must be boolean{label}")
    if "ignore_on_logger_transformations" in config and not isinstance(
        config.get("ignore_on_logger_transformations"), bool
    ):
        raise ValueError(f"Preprocess config 'ignore_on_logger_transformations' must be boolean{label}")
    if not isinstance(config.get("butterworth_smoothing"), list):
        raise ValueError(f"Preprocess config 'butterworth_smoothing' must be a list{label}")
    if not isinstance(config.get("butterworth_generate_residuals"), bool):
        raise ValueError(f"Preprocess config 'butterworth_generate_residuals' must be boolean{label}")
    _validate_motion_derivation(config.get("motion_derivation"), label=label)
    _validate_activity_detection(config.get("activity_detection"), label=label)

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

    _validate_imu_attitude(config.get("imu_attitude"), label=label)


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


def _validate_imu_attitude(value: Any, *, label: str) -> None:
    """Validate the optional, profile-controlled offline attitude stage."""
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise ValueError(f"Preprocess config 'imu_attitude' must be object or null{label}")

    unknown = sorted(set(value) - {"enabled", "required", "fixed_interval_tilt_smoother", "inertial_dynamics"})
    if unknown:
        raise ValueError(
            "Preprocess config 'imu_attitude' has unsupported field(s)"
            f"{label}: {', '.join(unknown)}"
        )
    for field in ("enabled", "required"):
        if field in value and not isinstance(value.get(field), bool):
            raise ValueError(f"Preprocess config 'imu_attitude.{field}' must be boolean{label}")
    tilt_smoother = value.get("fixed_interval_tilt_smoother")
    if tilt_smoother is not None:
        if not isinstance(tilt_smoother, Mapping):
            raise ValueError(f"Preprocess config 'imu_attitude.fixed_interval_tilt_smoother' must be object or null{label}")
        allowed_tilt = {"enabled", "gps_translational_compensation"}
        unknown_tilt = sorted(set(tilt_smoother) - allowed_tilt)
        if unknown_tilt:
            raise ValueError(
                "Preprocess config 'imu_attitude.fixed_interval_tilt_smoother' has unsupported field(s)"
                f"{label}: {', '.join(unknown_tilt)}"
            )
        if "enabled" in tilt_smoother and not isinstance(tilt_smoother.get("enabled"), bool):
            raise ValueError(f"Preprocess config 'imu_attitude.fixed_interval_tilt_smoother.enabled' must be boolean{label}")
        gps_compensation = tilt_smoother.get("gps_translational_compensation", "when_qualified")
        if gps_compensation not in {"when_qualified", "disabled"}:
            raise ValueError(
                "Preprocess config 'imu_attitude.fixed_interval_tilt_smoother.gps_translational_compensation' "
                f"must be 'when_qualified' or 'disabled'{label}"
            )
    dynamics = value.get("inertial_dynamics")
    if dynamics is None:
        return
    if not isinstance(dynamics, Mapping):
        raise ValueError(f"Preprocess config 'imu_attitude.inertial_dynamics' must be object or null{label}")
    allowed_dynamics = {"enabled", "include_world_frame", "include_angular_kinematics", "include_magnitudes"}
    unknown_dynamics = sorted(set(dynamics) - allowed_dynamics)
    if unknown_dynamics:
        raise ValueError(
            "Preprocess config 'imu_attitude.inertial_dynamics' has unsupported field(s)"
            f"{label}: {', '.join(unknown_dynamics)}"
        )
    for field in sorted(allowed_dynamics):
        if field in dynamics and not isinstance(dynamics.get(field), bool):
            raise ValueError(f"Preprocess config 'imu_attitude.inertial_dynamics.{field}' must be boolean{label}")


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


def _validate_activity_detection(value: Any, *, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise ValueError(f"Preprocess config 'activity_detection' must be object or null{label}")

    enabled = value.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError(f"Preprocess config 'activity_detection.enabled' must be boolean{label}")
    if "fallback_to_legacy" in value and not isinstance(value.get("fallback_to_legacy"), bool):
        raise ValueError(f"Preprocess config 'activity_detection.fallback_to_legacy' must be boolean{label}")

    combination = str(value.get("combination") or "any").strip().lower()
    if combination not in {"any"}:
        raise ValueError(
            "Preprocess config 'activity_detection.combination' must be 'any'"
            f"{label}"
        )

    candidates = value.get("candidates", [])
    if not isinstance(candidates, list):
        raise ValueError(f"Preprocess config 'activity_detection.candidates' must be a list{label}")

    seen_ids: set[str] = set()
    for idx, candidate in enumerate(candidates):
        candidate_key = f"activity_detection.candidates[{idx}]"
        if not isinstance(candidate, Mapping):
            raise ValueError(f"Preprocess config '{candidate_key}' must be an object{label}")
        candidate_id = candidate.get("id")
        if not _nonempty_str(candidate_id):
            raise ValueError(f"Preprocess config '{candidate_key}.id' must be a non-empty string{label}")
        if str(candidate_id) in seen_ids:
            raise ValueError(f"Duplicate activity detection candidate id{label}: {candidate_id!r}")
        seen_ids.add(str(candidate_id))

        candidate_type = str(candidate.get("type") or candidate.get("kind") or "motion_pair").strip().lower()
        if candidate_type not in {"gps_speed", "motion_pair", "wheel_motion", "legacy_motion"}:
            raise ValueError(
                f"Preprocess config '{candidate_key}.type' has unsupported value {candidate_type!r}{label}"
            )

        if candidate_type == "gps_speed":
            for numeric_key in ("speed_threshold_mps", "threshold_mps", "max_gap_s"):
                if numeric_key in candidate:
                    _require_positive_number(candidate, numeric_key, label=f"{label} ({candidate_key})")
            for text_key in ("source_id", "stream_name", "speed_col"):
                if text_key in candidate and not _nonempty_str(candidate.get(text_key)):
                    raise ValueError(
                        f"Preprocess config '{candidate_key}.{text_key}' must be a non-empty string{label}"
                    )
            continue

        if candidate_type == "legacy_motion":
            required_disp_selector = False
        else:
            required_disp_selector = "disp_col" not in candidate and "selector" not in candidate

        disp_selector = candidate.get("disp_selector", candidate.get("selector"))
        _validate_signal_selector(
            disp_selector,
            key=f"{candidate_key}.disp_selector",
            label=label,
            required=required_disp_selector,
        )
        _validate_signal_selector(
            candidate.get("vel_selector"),
            key=f"{candidate_key}.vel_selector",
            label=label,
            required=False,
        )
        for text_key in ("disp_col", "vel_col"):
            if text_key in candidate and not _nonempty_str(candidate.get(text_key)):
                raise ValueError(
                    f"Preprocess config '{candidate_key}.{text_key}' must be a non-empty string{label}"
                )
        for numeric_key in ("disp_thresh", "vel_thresh"):
            if numeric_key in candidate:
                _require_number(candidate, numeric_key, label=f"{label} ({candidate_key})")


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
