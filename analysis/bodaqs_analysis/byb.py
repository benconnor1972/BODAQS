"""Source-local BYB calibration, geometry resolution and canonical session adapter."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import timezone
import hashlib
import json
import math
from pathlib import Path
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import pandas as pd

from .bike_profile import apply_signal_transforms, validate_bike_profile
from .io_byb import BYB_READER_VERSION, BYB_TIMING_VERSION, read_byb

BYB_ADAPTER_VERSION = "byb.calibration.v1"
TRAVEL_KEYS = ("front_suspension_mm", "front_wheel_mm", "rear_suspension_mm", "rear_wheel_mm")


class BYBConfigurationError(ValueError):
    """Actionable setup problem. Keep the recording available for retry."""


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BYBConfigurationError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _json(data: bytes) -> dict:
    def bad_constant(value):
        raise BYBConfigurationError(f"Non-finite JSON number: {value}")
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_strict_object, parse_constant=bad_constant)
    except (ValueError, UnicodeError) as exc:
        raise BYBConfigurationError(f"Invalid BYB JSON: {exc}") from exc


def _object(value, allowed, required, label):
    if not isinstance(value, dict):
        raise BYBConfigurationError(f"{label} must be an object")
    missing, extra = set(required) - value.keys(), value.keys() - set(allowed)
    if missing or extra:
        raise BYBConfigurationError(f"{label}: missing {sorted(missing)}, unknown {sorted(extra)}")


def _number(value, label, minimum=0, inclusive=False, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BYBConfigurationError(f"{label} must be a finite number")
    if (value < minimum if inclusive else value <= minimum) or (maximum is not None and value > maximum):
        raise BYBConfigurationError(f"{label} is outside its permitted range")


def validate_byb_config(config: dict) -> dict:
    _object(config, ("schema", "version", "$schema", "display_name", "description", "timezone", "suspension", "geometry", "front_projection", "travel_overrides"), ("schema", "version", "suspension"), "byb.json")
    if config["schema"] != "bodaqs.compatibility.byb" or type(config["version"]) is not int or config["version"] != 1:
        raise BYBConfigurationError("byb.json requires schema=bodaqs.compatibility.byb, version=1")
    for field in ("$schema", "display_name", "description", "timezone"):
        if field in config and (not isinstance(config[field], str) or (field != "description" and not config[field].strip())):
            raise BYBConfigurationError(f"byb.json.{field} must be a non-empty string")
    _object(config["suspension"], ("front", "rear"), ("front", "rear"), "suspension")
    for end, channel in config["suspension"].items():
        if not isinstance(channel, dict) or type(channel.get("enabled")) is not bool:
            raise BYBConfigurationError(f"suspension.{end}.enabled must be boolean")
        if not channel["enabled"]:
            _object(channel, ("enabled",), ("enabled",), f"suspension.{end}")
            continue
        _object(channel, ("enabled", "sensor_length_mm", "compression_direction", "zero"), ("enabled", "sensor_length_mm", "compression_direction"), f"suspension.{end}")
        _number(channel["sensor_length_mm"], f"suspension.{end}.sensor_length_mm")
        if channel["compression_direction"] not in ("increasing_counts", "decreasing_counts"):
            raise BYBConfigurationError(f"suspension.{end}.compression_direction is invalid")
        zero = channel.get("zero", {"mode": "recording"})
        if not isinstance(zero, dict) or zero.get("mode") not in ("recording", "fixed"):
            raise BYBConfigurationError(f"suspension.{end}.zero requires mode=recording or fixed")
        keys = ("mode", "count") if zero["mode"] == "fixed" else ("mode",)
        _object(zero, keys, keys, f"suspension.{end}.zero")
        if zero["mode"] == "fixed":
            _number(zero["count"], f"suspension.{end}.zero.count", inclusive=True, maximum=4095)
    if "geometry" in config:
        geometry = config["geometry"]
        _object(geometry, ("kind", "path"), ("kind", "path"), "geometry")
        if geometry["kind"] not in ("byb_leverage", "bodaqs_bike_profile"):
            raise BYBConfigurationError("geometry.kind requires byb_leverage or bodaqs_bike_profile")
        if not isinstance(geometry["path"], str) or not geometry["path"].strip():
            raise BYBConfigurationError("geometry.path must name one file")
    elif config["suspension"]["rear"]["enabled"]:
        raise BYBConfigurationError("Enabled rear suspension requires geometry")
    if "front_projection" in config:
        _object(config["front_projection"], ("head_angle_deg",), ("head_angle_deg",), "front_projection")
        _number(config["front_projection"]["head_angle_deg"], "front_projection.head_angle_deg", maximum=90)
    elif config["suspension"]["front"]["enabled"] and config.get("geometry", {}).get("kind") != "bodaqs_bike_profile":
        raise BYBConfigurationError("Enabled front suspension requires front_projection or a bike-profile mapping")
    if "travel_overrides" in config:
        overrides = config["travel_overrides"]
        _object(overrides, TRAVEL_KEYS, (), "travel_overrides")
        if not overrides:
            raise BYBConfigurationError("travel_overrides must not be empty")
        for key, value in overrides.items():
            _number(value, f"travel_overrides.{key}")
    return copy.deepcopy(config)


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _empty_profile():
    return {"schema": "bodaqs.bike_profile", "version": 1, "bike_profile_id": "byb_resolved", "display_name": "BYB resolved geometry", "signal_transforms": [], "normalization_ranges": []}


def _curve(data: bytes) -> dict:
    points, metadata = [], {}
    try:
        for line in data.decode("utf-8-sig").splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                if not points and ":" in line:
                    key, value = line[1:].split(":", 1)
                    if key.strip().lower() in ("shockstrokemm", "wheeltravelmm"):
                        number = float(value.strip())
                        _number(number, f"curve metadata {key}")
                        if key.strip().lower() in metadata:
                            raise BYBConfigurationError(f"Duplicate curve metadata: {key}")
                        metadata[key.strip().lower()] = number
                continue
            fields = line.split(",")
            if len(fields) < 2:
                raise BYBConfigurationError(f"Invalid curve row: {line}")
            x, y = map(float, fields[:2])
            _number(x, "curve shock displacement", inclusive=True)
            _number(y, "curve wheel displacement", inclusive=True)
            if points and x <= points[-1]["input"]:
                raise BYBConfigurationError("Curve shock coordinates must be strictly increasing; do not sort/deduplicate implicitly")
            points.append({"input": x, "output": y})
    except (ValueError, UnicodeError) as exc:
        raise BYBConfigurationError(f"Invalid .bybLeverage: {exc}") from exc
    if len(points) < 2:
        raise BYBConfigurationError(".bybLeverage needs at least two valid points")
    profile = _empty_profile()
    profile["signal_transforms"] = [{"id": "byb_rear_linkage", "input": {"end": "rear", "quantity": "disp", "domain": "suspension", "unit": "mm"}, "output": {"end": "rear", "quantity": "disp", "domain": "wheel", "unit": "mm"}, "method": "lut", "interpolation": "linear", "extrapolation": "linear", "lut": points}]
    for domain, key, field in (("suspension", "shockstrokemm", "input"), ("wheel", "wheeltravelmm", "output")):
        full_range = metadata.get(key, max(p[field] for p in points))
        _number(full_range, f"curve {domain} travel")
        profile["normalization_ranges"].append({"id": f"rear_{domain}", "signal": {"end": "rear", "quantity": "disp", "domain": domain, "unit": "mm"}, "full_range": full_range})
    return profile


@dataclass
class BYBSetup:
    config: dict
    profile: dict
    timezone: str
    assets: list[tuple[str, bytes, str]]

    @property
    def identity(self):
        effective = copy.deepcopy(self.config)
        for key in ("display_name", "description", "$schema", "timezone"):
            effective.pop(key, None)
        effective.pop("geometry", None)  # Geometry content, not its live path, is hashed below.
        for channel in effective["suspension"].values():
            if channel["enabled"]:
                channel.setdefault("zero", {"mode": "recording"})
        return _hash(json.dumps({"config": effective, "profile": self.profile, "timezone": self.timezone, "reader": BYB_READER_VERSION, "adapter": BYB_ADAPTER_VERSION, "timing": BYB_TIMING_VERSION}, sort_keys=True).encode())

    def manifest(self):
        return {"schema": "bodaqs.byb_snapshot", "version": 1, "config": self.config, "profile": self.profile, "timezone": self.timezone, "setup_identity": self.identity, "assets": [{"path": name, "sha256": _hash(data), "original_path": original} for name, data, original in self.assets]}


def load_byb_setup(config_path: str | Path, *, fallback_timezone: str | None = None, config_bytes: bytes | None = None) -> BYBSetup:
    path = Path(config_path)
    try:
        data = path.read_bytes() if config_bytes is None else config_bytes
        config = validate_byb_config(_json(data))
        assets = [("byb.json", data, str(path))]
        profile = _empty_profile()
        if "geometry" in config:
            ref = config["geometry"]
            name = ref["path"]
            if re.search(r"[*?%$]", name) or name.startswith("~") or "://" in name:
                raise BYBConfigurationError("geometry.path must be a literal local file path")
            target = Path(name)
            if not target.is_absolute():
                target = path.parent / target
            content = target.read_bytes()
            assets.append(("geometry" + target.suffix, content, str(target.resolve())))
            profile = _curve(content) if ref["kind"] == "byb_leverage" else _json(content)
            validate_bike_profile(profile)
        tz = config.get("timezone") or fallback_timezone
        if not tz:
            raise BYBConfigurationError("Set byb.json.timezone or source logger_timezone to an IANA timezone")
        ZoneInfo(tz)
        return BYBSetup(config, profile, tz, assets)
    except (OSError, ValueError, ZoneInfoNotFoundError) as exc:
        raise BYBConfigurationError(f"{path}: {exc}") from exc


def load_byb_snapshot(path: str | Path) -> BYBSetup:
    """Restore a frozen setup without any original live paths being available."""
    path = Path(path)
    manifest = _json(path.read_bytes())
    if manifest.get("schema") != "bodaqs.byb_snapshot" or manifest.get("version") != 1:
        raise BYBConfigurationError("Unsupported BYB snapshot")
    assets = []
    for asset in manifest["assets"]:
        relative = Path(asset["path"])
        target = (path.parent / relative).resolve()
        if not target.is_relative_to(path.parent.resolve()):
            raise BYBConfigurationError("Snapshot asset must remain within the snapshot directory")
        data = target.read_bytes()
        if _hash(data) != asset["sha256"]:
            raise BYBConfigurationError(f"Snapshot asset hash mismatch: {relative}")
        assets.append((asset["path"], data, asset["original_path"]))
    setup = BYBSetup(validate_byb_config(manifest["config"]), manifest["profile"], manifest["timezone"], assets)
    validate_bike_profile(setup.profile)
    if setup.identity != manifest["setup_identity"]:
        raise BYBConfigurationError("Snapshot effective setup hash mismatch")
    return setup


def write_byb_snapshot(setup: BYBSetup, directory: str | Path, *, resolved: dict | None = None, preprocess_config: dict | None = None) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, data, _ in setup.assets:
        (directory / name).write_bytes(data)
    manifest = setup.manifest()
    if resolved is not None:
        manifest["resolved"] = resolved
    if preprocess_config is not None:
        cfg = copy.deepcopy(preprocess_config)
        if cfg.get("schema_path"):
            cfg["schema_path"] = "event_schema.yaml"
        manifest["preprocess_config"] = cfg
    path = directory / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")
    return path


def preprocess_byb_snapshot(recording_path: str | Path, snapshot_path: str | Path, **kwargs) -> dict:
    """Reprocess retained recording/setup/analysis assets without their live source."""
    from .pipeline import preprocess_session
    from .preprocess_profile import resolve_preprocess_config_paths
    snapshot_path = Path(snapshot_path)
    load_byb_snapshot(snapshot_path)  # Verify all retained asset hashes first.
    manifest = _json(snapshot_path.read_bytes())
    expected_raw = manifest.get("resolved", {}).get("recording_sha256")
    if expected_raw and _hash(Path(recording_path).read_bytes()) != expected_raw:
        raise BYBConfigurationError("Replay recording does not match the retained recording hash")
    cfg = resolve_preprocess_config_paths(manifest["preprocess_config"], base_dir=snapshot_path.parent)
    if (cfg.get("fit_import") or {}).get("enabled"):
        # The ordinary importer retains selected FIT files here, beside this snapshot.
        auxiliary = snapshot_path.parents[2] / "source_aux"
        cfg["fit_import"] = {**cfg["fit_import"], "fit_dir": str(auxiliary), "ambiguity_policy": "largest_overlap", "failure_policy": "warn"}
    return preprocess_session(recording_path, byb_snapshot_path=snapshot_path, preprocess_config=cfg, **kwargs)


def _zero(frame, values, cfg, dt):
    window = float(cfg.get("zero_window_s", 1.0))
    minimum = max(int(cfg.get("zero_min_samples", 10)), math.ceil(window / dt))
    best = None
    for _, indices in frame.groupby("segment_id", sort=False).groups.items():
        t = frame.loc[indices, "time_s"].to_numpy()
        y = values[indices]
        # Time-based rolling median implements the shared BODAQS estimator in O(n log window).
        series = pd.Series(y, index=pd.to_timedelta(t, unit="s"))
        medians = series.rolling(pd.Timedelta(seconds=window), min_periods=minimum, closed="both").median()
        if medians.notna().any():
            k = int(np.nanargmin(medians.to_numpy()))
            candidate = {"offset": float(medians.iloc[k]), "time_end_s": float(t[k]), "method": "min_window_median", "window_s": window, "min_samples": minimum}
            if best is None or candidate["offset"] < best["offset"]:
                best = candidate
    if best is None:
        finite = np.flatnonzero(np.isfinite(values))
        if not len(finite):
            raise BYBConfigurationError("Enabled suspension channel has no valid samples; correct or disable it")
        best = {"offset": float(values[finite[0]]), "method": "fallback_first_value", "warning": "No eligible zero-estimation window"}
    return best


def _resolve_travel(setup, trailer):
    facts = {key: [] for key in TRAVEL_KEYS}
    for item in setup.profile.get("normalization_ranges", []):
        selector = item["signal"]
        if selector.get("quantity") == "disp" and selector.get("unit") == "mm":
            key = f"{selector.get('end')}_{selector.get('domain')}_mm"
            if key in facts:
                facts[key].append({"source": "geometry", "value": float(item["full_range"])})
    for key, value in trailer.items():
        facts[key].append({"source": "trailer", "value": value})
    result = {}
    for key, declarations in facts.items():
        if not setup.config["suspension"][key.split("_")[0]]["enabled"]:
            continue
        override = setup.config.get("travel_overrides", {}).get(key)
        if override is not None:
            result[key] = {"value": override, "source": "override", "declarations": declarations}
            continue
        for i, a in enumerate(declarations):
            for b in declarations[i + 1:]:
                if abs(a["value"] - b["value"]) > max(0.5, 0.001 * max(a["value"], b["value"])):
                    raise BYBConfigurationError(f"Travel conflict {key}: {declarations}; correct geometry/trailer or set travel_overrides.{key}")
        if declarations:
            result[key] = {**declarations[0], "declarations": declarations}
    if setup.config["suspension"]["front"]["enabled"] and "front_wheel_mm" not in result and "front_projection" in setup.config and "front_suspension_mm" in result:
        result["front_wheel_mm"] = {"value": result["front_suspension_mm"]["value"] * math.sin(math.radians(setup.config["front_projection"]["head_angle_deg"])), "source": "front_projection", "declarations": []}
    for end, channel in setup.config["suspension"].items():
        for domain in ("suspension", "wheel") if channel["enabled"] else ():
            key = f"{end}_{domain}_mm"
            if key not in result:
                raise BYBConfigurationError(f"Missing travel {key}; supply a geometry range or travel_overrides.{key}")
    return result


def load_byb_session(path: str | Path, *, setup: BYBSetup | None = None, config_path: str | Path | None = None, snapshot_path: str | Path | None = None, timezone: str | None = None, preprocess_config: dict | None = None) -> tuple[dict, dict, BYBSetup]:
    """Return a canonical Session, effective bike profile and frozen setup."""
    from .pipeline import build_session_from_dataframe
    path = Path(path)
    if setup is None:
        if snapshot_path is not None:
            setup = load_byb_snapshot(snapshot_path)
        else:
            setup = load_byb_setup(config_path or path.parent / "byb.json", fallback_timezone=timezone)
    recording = read_byb(path)
    zone = ZoneInfo(setup.timezone)
    start = recording.started_local
    candidates = {start.replace(tzinfo=zone, fold=fold).utcoffset() for fold in (0, 1)}
    aware = start.replace(tzinfo=zone)
    if len(candidates) != 1 or aware.astimezone(timezone_utc).astimezone(zone).replace(tzinfo=None) != start:
        raise BYBConfigurationError("BYB header time is ambiguous/nonexistent in the selected timezone; supply an unambiguous timezone")
    frame = recording.analysis.copy()
    signals, calibrated, zeros = {}, [], {}
    for end, channel in setup.config["suspension"].items():
        raw_col = f"{end}_counts"
        if not channel["enabled"]:
            frame.drop(columns=raw_col, inplace=True)
            continue
        direction = 1 if channel["compression_direction"] == "increasing_counts" else -1
        values = frame[raw_col].to_numpy(dtype=float)
        zero_policy = channel.get("zero", {"mode": "recording"})
        if zero_policy["mode"] == "fixed":
            zero = {"count": zero_policy["count"], "method": "fixed"}
        else:
            info = _zero(frame, direction * values, preprocess_config or {}, recording.qc["timing"]["nominal_dt_s"])
            zero = {**info, "count": direction * info["offset"]}
        zeros[end] = zero
        col = f"{end}_shock_dom_suspension [mm]"
        frame[col] = direction * (values - zero["count"]) * channel["sensor_length_mm"] / 4095
        frame.drop(columns=raw_col, inplace=True)
        calibrated.append(col)
        signals[col] = {"sensor": f"{end}_shock", "end": end, "quantity": "disp", "domain": "suspension", "unit": "mm", "origin": "analysis", "motion_source_id": f"byb_{end}_linear", "processing_role": "primary_analysis", "calibration": {"type": "linear", "sensor_length_mm": channel["sensor_length_mm"], "zero_count": zero["count"], "compression_direction": channel["compression_direction"]}, "zero_reference_resolved": True}
    digest = _hash(path.read_bytes())
    session = build_session_from_dataframe(frame, session_id=f"byb_{start:%y%m%d_%H%M%S}_{digest[:12]}", source_path=path, timezone=setup.timezone)
    session["meta"].update({"channel_info": copy.deepcopy(signals), "signals": copy.deepcopy(signals), "sample_rate_hz": 1 / recording.qc["timing"]["nominal_dt_s"], "t0_datetime": aware.isoformat(), "source_contract": {"name": "byb.v1", "version": "1"}, "zero_reference_resolved_columns": calibrated})
    session["source"].update({"input_format": "byb", "created_local": aware.isoformat(), "created_utc": aware.astimezone(timezone_utc).isoformat()})
    session["df_raw"] = recording.raw
    session["stream_dfs"] = {"byb_raw": recording.raw, "logger_gps": recording.gps}
    session["meta"]["secondary_streams"] = {
        "byb_raw": {"kind": "intermittent", "time_col": "time_s", "source_kind": "raw_recording", "notes": "Unmodified BYB records; ancillary units are raw counts"},
        "logger_gps": {"kind": "intermittent", "time_col": "time_s", "source_kind": "logger_sensor", "columns": {"latitude_deg": {"quantity": "latitude", "unit": "deg"}, "longitude_deg": {"quantity": "longitude", "unit": "deg"}, "altitude_m": {"quantity": "altitude", "unit": "m"}, "speed_mps": {"quantity": "speed", "unit": "m/s"}}},
    }
    gps_signals = {}
    for col, quantity, unit in (("latitude_deg", "position_latitude", "deg"), ("longitude_deg", "position_longitude", "deg"), ("altitude_m", "altitude", "m"), ("speed_mps", "speed", "m/s")):
        gps_signals[col] = {"quantity": quantity, "unit": unit, "domain": "world", "sensor": "gps", "source": "logger_gps", "origin": "logger"}
    session["meta"]["secondary_streams"]["logger_gps"].update({"signals": gps_signals, "channel_info": gps_signals, "resolution_mode": "registry_only", "position_columns": {"latitude": "latitude_deg", "longitude": "longitude_deg"}})
    session["meta"]["secondary_streams"]["byb_raw"]["signals"] = {
        col: {"quantity": "raw", "unit": "counts", "sensor": "byb_raw", "semantic_selection_excluded": True}
        for col in recording.raw.columns if col.endswith("_counts")
    }
    profile = copy.deepcopy(setup.profile)
    profile["normalization_ranges"] = []
    profile["signal_transforms"] = [item for item in profile.get("signal_transforms", []) if setup.config["suspension"].get(item.get("output", {}).get("end"), {}).get("enabled", True)]
    # Preflight on real semantic inputs, retaining the original frame for the shared pipeline.
    probe = {"df": frame.copy(), "meta": {"signals": copy.deepcopy(signals), "channel_info": copy.deepcopy(signals)}}
    try:
        apply_signal_transforms(probe, profile)
        for end, channel in setup.config["suspension"].items():
            if not channel["enabled"]:
                continue
            matches = [info for info in probe["meta"]["signals"].values() if info.get("end") == end and info.get("domain") == "wheel" and info.get("quantity") == "disp" and info.get("unit") == "mm" and info.get("processing_role", "primary_analysis") == "primary_analysis"]
            fallback = setup.config.get("front_projection") if end == "front" else None
            if matches and fallback:
                raise BYBConfigurationError("Ambiguous front mapping: remove front_projection or the enabled profile front transform")
            if not matches and fallback:
                profile["signal_transforms"].append({"id": "byb_front_projection", "input": {"end": "front", "quantity": "disp", "domain": "suspension", "unit": "mm"}, "output": {"end": "front", "quantity": "disp", "domain": "wheel", "unit": "mm"}, "method": "polynomial", "polynomial": {"coefficients": [0, math.sin(math.radians(fallback["head_angle_deg"]))], "coefficient_order": "ascending"}})
            elif len(matches) != 1:
                raise BYBConfigurationError(f"{end}: geometry must provide one linear suspension-mm to wheel-mm route; check input selectors, angular quantities and motion_source_id")
    except ValueError as exc:
        raise BYBConfigurationError(f"Geometry preflight failed: {exc}") from exc
    travels = _resolve_travel(setup, recording.travel)
    for key, resolution in travels.items():
        end, domain, _ = key.split("_")
        profile["normalization_ranges"].append({"id": key, "signal": {"end": end, "quantity": "disp", "domain": domain, "unit": "mm"}, "full_range": resolution["value"]})
    excursions = {}
    for end in zeros:
        values = frame[f"{end}_shock_dom_suspension [mm]"].to_numpy()
        excursions[end] = {"below_zero_samples": int(np.count_nonzero(values < 0)), "above_travel_samples": int(np.count_nonzero(values > travels[f"{end}_suspension_mm"]["value"]))}
    from .signal_selectors import resolve_signal_selector
    lut_domains = {}
    for transform in profile.get("signal_transforms", []):
        if transform.get("method") != "lut" or transform.get("enabled") is False:
            continue
        column = resolve_signal_selector(probe, transform["input"], purpose="BYB LUT QC")
        if column:
            values = probe["df"][column].to_numpy()
            low, high = transform["lut"][0]["input"], transform["lut"][-1]["input"]
            lut_domains[transform["id"]] = {"input_min_mm": low, "input_max_mm": high, "outside_domain_samples": int(np.count_nonzero((values < low) | (values > high)))}
    session["meta"]["byb"] = {"setup_identity": setup.identity, "recording_sha256": digest, "adapter_version": BYB_ADAPTER_VERSION, "zero_references": zeros, "travel": travels, "recording": recording.qc, "effective_bike_profile": profile, "suspension_excursions": excursions, "lut_domains": lut_domains}
    session["qc"]["byb"] = session["meta"]["byb"]
    session["qc"]["warnings"].extend(recording.qc["warnings"])
    return session, profile, setup


timezone_utc = timezone.utc
