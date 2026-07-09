from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple
import pandas as pd
import numpy as np
import logging
import os
import re

from .io_logger import load_logger_csv_with_log_metadata, parse_run_stats_footer
from .io_bdq import bdq_to_dataframe, bdq_to_log_metadata, is_bdq_path, read_bdq
from .io_fit import (
    FIT_DEFAULT_FIELDS,
    find_overlapping_fit_candidates,
    find_overlapping_fit_files,
    load_fit_stream,
    parse_fit_stream,
    select_fit_candidate,
)
from .normalize import scale_signal_columns, zero_signal_columns
from .va import estimate_va, name_vel
from .schema import load_event_schema, parse_event_schema
from .detect import detect_events_from_schema
from .metrics import extract_metrics_df, compute_metrics_from_segments
from .model import validate_metrics_df
from .model import validate_session
from .timebase import register_stream_metadata, register_stream_timebase, estimate_uniform_timebase
from .resample import resample_to_time_grid
from .signal_standardize import (
    canonicalize_signal_names,
    rebuild_and_validate_signal_registry,
)
from .signal_registry import build_signals_registry
from .signal_selectors import resolve_signal_selector
from .gps_semantics import (
    build_logger_gps_route_stream,
    preferred_gps_source_name,
    refresh_gps_source_metadata,
    resolve_gps_columns,
)
from .segment import extract_segments, SegmentRequest
from .preprocess_filters import (
    apply_butterworth_smoothing,
    normalize_butterworth_smoothing_configs,
)
from .motion_derivation import derive_motion_channels
from .bike_profile import apply_signal_transforms, load_bike_profile, parse_bike_profile, resolve_normalization_ranges
from .preprocess_profile import load_preprocess_config, preprocess_config_from_profile, validate_preprocess_config
from .sensor_aliases import canonical_end, canonical_sensor_id
from .signalname import SignalNameError, SignalNameParts, format_signal_name, parse_signal_name

_UNIT_RE = re.compile(r"\[(.*?)\]")
_FILENAME_STEM_LONG_DATETIME_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{2}-\d{2}-\d{2})(?:$|[^0-9].*)"
)
_FILENAME_STEM_COMPACT_DATETIME_RE = re.compile(
    r"^(?P<year>\d{2})(?P<month>\d{2})(?P<day>\d{2})_"
    r"(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})(?:$|[^0-9].*)"
)
ACTIVE_MASK_COL = "active_mask_qc"  # stored in session["df"] (not in registry)

logger = logging.getLogger(__name__)

_LOG_METADATA_BINDING_KEY = "_bodaqs_log_metadata_binding"
_SIDECAR_BINDING_KEY = "_bodaqs_sidecar_binding"


def _optional_nonempty_str(value: Any) -> Optional[str]:
    text = "" if value is None else str(value).strip()
    return text or None


_FIT_IMPORT_DEFAULTS: Dict[str, Any] = {
    "enabled": False,
    "fit_dir": None,
    "field_allowlist": list(FIT_DEFAULT_FIELDS),
    "ambiguity_policy": "require_binding",
    "partial_overlap": "allow",
    "persist_raw_stream": True,
    "resample_to_primary": True,
    "resample_method": "linear",
    "resample_max_gap_s": None,
    "gps_resample_max_gap_s": 5.0,
    "raw_stream_name": "gps_fit",
    "resampled_prefix": "gps_fit",
    "bindings_path": None,
}

_FIT_GPS_POSITION_COLUMNS = {
    "gps_fit_position_latitude_dom_world [deg]",
    "gps_fit_position_longitude_dom_world [deg]",
}
_FIT_GPS_POSITION_ROLES = {"position_latitude", "position_longitude"}


def _metadata_binding(log_metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    binding = log_metadata.get(_LOG_METADATA_BINDING_KEY)
    if isinstance(binding, dict):
        return binding
    binding = log_metadata.get(_SIDECAR_BINDING_KEY)
    return binding if isinstance(binding, dict) else None


def _firmware_stats_from_log_metadata(log_metadata: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(log_metadata, Mapping):
        return None
    qc = log_metadata.get("qc")
    if not isinstance(qc, Mapping):
        return None
    run_stats = qc.get("run_stats")
    if not isinstance(run_stats, Mapping) or not run_stats:
        return None
    return dict(run_stats)


def _firmware_dropped_sample_count(stats: Any) -> int:
    if not isinstance(stats, Mapping):
        return 0
    value = stats.get("samples_dropped", stats.get("samplesDropped", 0))
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _source_identity_token(*values: Any) -> str:
    for value in values:
        token = canonical_sensor_id(value)
        if token:
            return token
    return ""


def _signal_source_identity(info: Mapping[str, Any]) -> str:
    return _source_identity_token(
        info.get("motion_source_id"),
        info.get("sensor"),
        info.get("log_metadata_column_id"),
        info.get("sidecar_column_id"),
    )


def _source_qualified_signal_name(base_name: str, token: str) -> str:
    token = canonical_sensor_id(token)
    if not token:
        return base_name
    try:
        parts = parse_signal_name(base_name)
        base = parts.base
        if base != token and not base.endswith(f"_{token}"):
            base = f"{base}_{token}"
        return format_signal_name(
            SignalNameParts(
                base=base,
                kind=parts.kind,
                domain=parts.domain,
                unit=parts.unit,
                ops=parts.ops,
            )
        )
    except SignalNameError:
        stem = canonical_sensor_id(base_name) or "signal"
        return f"{stem}_{token}"


def _unique_signal_column_name(base_name: str, *, source_id: str, fallback: str, existing_names: set[str]) -> str:
    if base_name not in existing_names:
        return base_name

    tokens = [source_id, fallback]
    seen: set[str] = set()
    for token in tokens:
        token = canonical_sensor_id(token)
        if not token or token in seen:
            continue
        seen.add(token)
        candidate = _source_qualified_signal_name(base_name, token)
        if candidate not in existing_names:
            return candidate

    index = 2
    while True:
        candidate = _source_qualified_signal_name(base_name, f"{fallback}_{index}")
        if candidate not in existing_names:
            return candidate
        index += 1


def _declared_time_columns(sidecar: Dict[str, Any]) -> set[str]:
    out: set[str] = set()
    binding = _metadata_binding(sidecar)
    bound_columns = binding.get("columns", {}) if isinstance(binding, dict) else {}

    columns = sidecar.get("columns")
    if isinstance(columns, dict):
        for col_name, info in columns.items():
            if isinstance(info, dict) and info.get("class") == "time":
                out.add(str(col_name))
                bound = bound_columns.get(str(col_name))
                if isinstance(bound, dict) and isinstance(bound.get("dataframe_column"), str):
                    out.add(bound["dataframe_column"])

    streams = sidecar.get("streams")
    if isinstance(streams, dict):
        for stream_info in streams.values():
            if not isinstance(stream_info, dict):
                continue
            time_col = stream_info.get("time_column", stream_info.get("time_col"))
            if isinstance(time_col, str) and time_col.strip():
                out.add(time_col)
                bound = bound_columns.get(time_col)
                if isinstance(bound, dict) and isinstance(bound.get("dataframe_column"), str):
                    out.add(bound["dataframe_column"])

    out.add("time_s")
    return out


def _build_channel_info_from_sidecar(sidecar: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    columns = sidecar.get("columns")
    streams = sidecar.get("streams")
    sensors = sidecar.get("sensors")
    binding = _metadata_binding(sidecar)
    bound_columns = binding.get("columns", {}) if isinstance(binding, dict) else {}
    if not isinstance(columns, dict):
        return out
    if not isinstance(sensors, Mapping):
        sensors = {}

    def _sensor_metadata_for_ref(ref: Any) -> tuple[Optional[str], Optional[Mapping[str, Any]]]:
        if not isinstance(ref, str) or not ref.strip():
            return None, None
        ref_text = ref.strip()
        direct = sensors.get(ref_text)
        if isinstance(direct, Mapping):
            return ref_text, direct

        canonical_ref = canonical_sensor_id(ref_text)
        for sensor_key, sensor_info in sensors.items():
            if not isinstance(sensor_info, Mapping):
                continue
            candidates = [str(sensor_key)]
            sensor_name = sensor_info.get("name")
            if isinstance(sensor_name, str) and sensor_name.strip():
                candidates.append(sensor_name)
            if any(canonical_sensor_id(candidate) == canonical_ref for candidate in candidates):
                return str(sensor_key), sensor_info
        return None, None

    for col_name, info in columns.items():
        if not isinstance(info, dict):
            continue
        column_class = str(info.get("class") or "").strip().lower()
        column_kind = str(info.get("kind") or "").strip().lower()
        if column_class == "diagnostic":
            bound = bound_columns.get(str(col_name))
            dataframe_col = bound.get("dataframe_column") if isinstance(bound, dict) else str(col_name)
            if not isinstance(dataframe_col, str) or not dataframe_col.strip():
                dataframe_col = str(col_name)

            ch: Dict[str, Any] = {
                "class": "diagnostic",
                "origin": "logger",
                "semantic_selection_excluded": True,
                "semantic_selection_exclusion_reason": "diagnostic_column",
                "log_metadata_column_id": str(col_name),
                "sidecar_column_id": str(col_name),
            }

            metric = info.get("metric")
            if isinstance(metric, str) and metric.strip():
                ch["metric"] = metric.strip()

            unit = info.get("unit")
            if isinstance(unit, str) and unit.strip():
                ch["unit"] = "1" if unit.strip().lower() in {"norm", "normalized", "normalised", "unitless"} else unit

            sensor = info.get("sensor")
            if isinstance(sensor, str) and sensor.strip():
                ch["sensor"] = canonical_sensor_id(sensor)

            for key in ("source", "processing_role"):
                if key in info:
                    ch[key] = info[key]

            if isinstance(bound, dict):
                ch["csv_column"] = bound.get("physical_column_label")
                ch["csv_ref"] = bound.get("csv_ref")

            out[dataframe_col] = ch
            continue

        if column_class != "signal" and column_kind != "qc":
            continue

        bound = bound_columns.get(str(col_name))
        dataframe_col = bound.get("dataframe_column") if isinstance(bound, dict) else str(col_name)
        if not isinstance(dataframe_col, str) or not dataframe_col.strip():
            dataframe_col = str(col_name)

        ch: Dict[str, Any] = {}
        unit = info.get("unit")
        if isinstance(unit, str) and unit.strip():
            ch["unit"] = "1" if unit.strip().lower() in {"norm", "normalized", "normalised", "unitless"} else unit

        sensor = info.get("sensor")
        if isinstance(sensor, str) and sensor.strip():
            ch["sensor"] = canonical_sensor_id(sensor)

        end = info.get("end")
        canonical = canonical_end(end) if isinstance(end, str) and end.strip() else ""
        if canonical:
            ch["end"] = canonical

        quantity = info.get("quantity")
        if isinstance(quantity, str) and quantity.strip():
            ch["role"] = quantity
            ch["quantity"] = quantity

        domain = info.get("domain")
        if isinstance(domain, str) and domain.strip():
            ch["domain"] = domain

        for key in (
            "kind",
            "source",
            "processing_role",
            "motion_source_id",
            "motion_profile_id",
            "semantic_selection_excluded",
            "semantic_selection_exclusion_reason",
        ):
            if key in info:
                ch[key] = info[key]

        source_columns = info.get("source_columns")
        if isinstance(source_columns, list):
            ch["source_columns"] = [str(x) for x in source_columns if isinstance(x, str)]

        calibration_ref = info.get("calibration_ref")
        if isinstance(calibration_ref, str) and calibration_ref.strip():
            ch["calibration_ref"] = calibration_ref
        direct_calibration = info.get("calibration")
        if isinstance(direct_calibration, Mapping):
            ch["calibration"] = dict(direct_calibration)

        for ref in (calibration_ref, sensor):
            matched_ref, sensor_info = _sensor_metadata_for_ref(ref)
            if sensor_info is None:
                continue
            if "calibration_ref" not in ch and isinstance(matched_ref, str) and matched_ref.strip():
                ch["calibration_ref"] = matched_ref
            calibration = sensor_info.get("calibration")
            if "calibration" not in ch and isinstance(calibration, Mapping):
                ch["calibration"] = dict(calibration)
            break

        transform_chain = info.get("transform_chain")
        if isinstance(transform_chain, list):
            ch["transform_chain"] = [str(x) for x in transform_chain if isinstance(x, str)]

        ch["origin"] = "logger"

        stream_name = info.get("stream")
        if isinstance(stream_name, str) and isinstance(streams, dict):
            stream_info = streams.get(stream_name)
            if isinstance(stream_info, dict):
                sample_rate_hz = stream_info.get("sample_rate_hz")
                if sample_rate_hz is not None:
                    try:
                        ch["nominal_rate_hz"] = float(sample_rate_hz)
                    except Exception:
                        pass

        ch["log_metadata_column_id"] = str(col_name)
        ch["sidecar_column_id"] = str(col_name)
        if "motion_source_id" not in ch:
            motion_source_id = _source_identity_token(ch.get("sensor"), col_name)
            if motion_source_id:
                ch["motion_source_id"] = motion_source_id
        if isinstance(bound, dict):
            ch["csv_column"] = bound.get("physical_column_label")
            ch["csv_ref"] = bound.get("csv_ref")
            token = bound.get("dataframe_column_disambiguation_token")
            if isinstance(token, str) and token.strip():
                ch["dataframe_column_disambiguation_token"] = token
            canonical = bound.get("canonical_dataframe_column")
            if isinstance(canonical, str) and canonical.strip():
                ch["canonical_dataframe_column"] = canonical

        out[dataframe_col] = ch

    return out


def _apply_log_metadata(
    session: Dict[str, Any],
    *,
    log_metadata: Dict[str, Any],
    log_metadata_path: Optional[str] = None,
) -> None:
    source = session.setdefault("source", {})
    meta = session.setdefault("meta", {})
    qc = session.setdefault("qc", {})
    parse = qc.setdefault("parse", {})

    if isinstance(log_metadata_path, str) and log_metadata_path.strip():
        source["log_metadata_path"] = log_metadata_path
        # Transitional alias for existing consumers.
        source["sidecar_path"] = log_metadata_path
    binding = _metadata_binding(log_metadata)
    if isinstance(binding, dict):
        log_metadata_kind = binding.get("log_metadata_kind", binding.get("sidecar_kind"))
        if isinstance(log_metadata_kind, str) and log_metadata_kind.strip():
            source["log_metadata_kind"] = log_metadata_kind
            source["sidecar_kind"] = log_metadata_kind
            parse["log_metadata_kind"] = log_metadata_kind
            parse["sidecar_kind"] = log_metadata_kind
        parse["log_metadata_column_bindings"] = binding.get("columns", {})
        parse["sidecar_column_bindings"] = binding.get("columns", {})
        missing_optional = binding.get("missing_optional_columns")
        if isinstance(missing_optional, list):
            parse["log_metadata_missing_optional_columns"] = list(missing_optional)
            parse["sidecar_missing_optional_columns"] = list(missing_optional)
        skipped_unknown = binding.get("skipped_unknown_columns")
        if isinstance(skipped_unknown, list):
            parse["log_metadata_skipped_unknown_columns"] = list(skipped_unknown)
            parse["sidecar_skipped_unknown_columns"] = list(skipped_unknown)
        for warning in binding.get("warnings", []):
            if isinstance(warning, str) and warning.strip():
                _append_qc_warning(session, warning)

    contract = log_metadata.get("contract")
    if isinstance(contract, dict):
        name = contract.get("name")
        version = contract.get("version")
        if isinstance(name, str) and isinstance(version, str):
            meta["source_contract"] = {"name": name, "version": version}

    declared_streams = log_metadata.get("streams")
    if isinstance(declared_streams, dict):
        meta["declared_streams"] = declared_streams

        primary_stream = declared_streams.get("primary")
        if not isinstance(primary_stream, dict):
            for stream_info in declared_streams.values():
                if isinstance(stream_info, dict):
                    primary_stream = stream_info
                    break

        if isinstance(primary_stream, dict):
            time_col = primary_stream.get("time_column", primary_stream.get("time_col"))
            if isinstance(time_col, str) and time_col.strip():
                parse["time_column_used"] = time_col
                if isinstance(binding, dict):
                    bound = binding.get("columns", {}).get(time_col)
                    if isinstance(bound, dict) and isinstance(bound.get("dataframe_column"), str):
                        parse["time_dataframe_column_used"] = bound["dataframe_column"]
            if primary_stream.get("type") == "uniform":
                sample_rate_hz = primary_stream.get("sample_rate_hz")
                if sample_rate_hz is not None:
                    try:
                        meta["sample_rate_hz"] = float(sample_rate_hz)
                    except Exception:
                        pass

    declared_sensors = log_metadata.get("sensors")
    if isinstance(declared_sensors, dict):
        meta["declared_sensors"] = declared_sensors

    session_meta = log_metadata.get("session")
    if isinstance(session_meta, dict):
        started_at_utc = session_meta.get("started_at_utc")
        if isinstance(started_at_utc, str) and started_at_utc.strip():
            source["created_utc"] = started_at_utc
            meta["t0_datetime"] = started_at_utc

        started_at_local = session_meta.get("started_at_local")
        if isinstance(started_at_local, str) and started_at_local.strip():
            source["created_local"] = started_at_local
            if not isinstance(meta.get("t0_datetime"), str) or not meta["t0_datetime"].strip():
                meta["t0_datetime"] = started_at_local

        timezone = _optional_nonempty_str(session_meta.get("timezone"))
        if timezone is not None:
            previous_timezone = _optional_nonempty_str(source.get("timezone"))
            if previous_timezone is not None and previous_timezone != timezone:
                parse["runtime_timezone_fallback"] = previous_timezone
                parse["runtime_timezone_overridden_by_log_metadata"] = True
            source["timezone"] = timezone
            source["timezone_source"] = "log_metadata"

        notes = session_meta.get("notes")
        if notes is not None:
            meta["notes"] = notes

        source_session_id = session_meta.get("session_id")
        if isinstance(source_session_id, str) and source_session_id.strip():
            meta["source_session_id"] = source_session_id

    provenance = log_metadata.get("provenance")
    if isinstance(provenance, dict):
        device = meta.get("device")
        if not isinstance(device, dict):
            device = {}
        for src_key, dst_key in (
            ("logger_family", "logger_family"),
            ("firmware_version", "firmware_version"),
            ("generator", "generator"),
            ("metadata_generated_at", "metadata_generated_at"),
        ):
            value = provenance.get(src_key)
            if value is not None:
                device[dst_key] = value
        meta["device"] = device or None

    channel_info = meta.setdefault("channel_info", {})
    if not isinstance(channel_info, dict):
        channel_info = {}
        meta["channel_info"] = channel_info
    channel_info.update(_build_channel_info_from_sidecar(log_metadata))

    parse["log_metadata_used"] = True
    parse["sidecar_used"] = True


def _apply_sidecar_metadata(
    session: Dict[str, Any],
    *,
    sidecar: Dict[str, Any],
    sidecar_path: Optional[str] = None,
) -> None:
    """
    Backward-compatible alias for _apply_log_metadata().
    """
    _apply_log_metadata(session, log_metadata=sidecar, log_metadata_path=sidecar_path)


def _infer_time_anchor_from_filename_stem(
    csv_path: str | Path,
    *,
    timezone: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    stem = Path(csv_path).stem
    match = _FILENAME_STEM_LONG_DATETIME_RE.match(stem)
    if match is not None:
        base_ts = pd.Timestamp(
            f"{match.group('date')}T{match.group('time').replace('-', ':')}"
        )
    else:
        match = _FILENAME_STEM_COMPACT_DATETIME_RE.match(stem)
        if match is None:
            return None, None
        base_ts = pd.Timestamp(
            "20"
            f"{match.group('year')}-{match.group('month')}-{match.group('day')}"
            f"T{match.group('hour')}:{match.group('minute')}:{match.group('second')}"
        )

    if pd.isna(base_ts):
        return None, None
    tz_source: Optional[str] = None

    if isinstance(timezone, str) and timezone.strip():
        try:
            return base_ts.tz_localize(timezone.strip()).isoformat(), "explicit_timezone"
        except Exception:
            tz_source = "local_machine_timezone"

    local_tzinfo = datetime.now().astimezone().tzinfo
    if local_tzinfo is not None:
        return base_ts.tz_localize(local_tzinfo).isoformat(), (tz_source or "local_machine_timezone")

    return base_ts.isoformat(), "naive_no_timezone"


def _apply_filename_stem_time_anchor(
    session: Dict[str, Any],
    *,
    csv_path: str | Path,
) -> None:
    source = session.setdefault("source", {})
    meta = session.setdefault("meta", {})
    qc = session.setdefault("qc", {})
    parse = qc.setdefault("parse", {})

    existing_anchor = None
    if isinstance(meta, dict):
        existing_anchor = meta.get("t0_datetime")
    if existing_anchor is None and isinstance(source, dict):
        existing_anchor = source.get("created_local")
    if isinstance(existing_anchor, str) and existing_anchor.strip():
        return

    timezone = source.get("timezone") if isinstance(source, dict) else None
    anchor, tz_source = _infer_time_anchor_from_filename_stem(csv_path, timezone=timezone)
    if not isinstance(anchor, str) or not anchor.strip():
        return

    source["created_local"] = anchor
    meta["t0_datetime"] = anchor
    parse["time_anchor_source"] = "filename_stem"
    parse["time_anchor_timezone_source"] = tz_source

    if tz_source == "local_machine_timezone":
        _append_qc_warning(session, "filename_stem_time_anchor_used_local_machine_timezone")
    elif tz_source == "naive_no_timezone":
        _append_qc_warning(session, "filename_stem_time_anchor_used_without_timezone")


def load_session(
    csv_path: str,
    *,
    timezone: Optional[str] = None,
    sidecar_path: Optional[str] = None,
    generic_sidecar_paths: Optional[Sequence[str | Path]] = None,
    log_metadata_path: Optional[str | Path] = None,
    generic_log_metadata_paths: Optional[Sequence[str | Path]] = None,
) -> Dict[str, Any]:
    """Load a CSV into a v0 Session dict (df_raw + initial qc/meta)."""
    p = Path(csv_path)
    df_raw, sidecar, resolved_sidecar_path = load_logger_csv_with_log_metadata(
        str(p),
        log_metadata_path=log_metadata_path,
        generic_log_metadata_paths=generic_log_metadata_paths,
        sidecar_path=sidecar_path,
        generic_sidecar_paths=generic_sidecar_paths,
    )

    stats = _firmware_stats_from_log_metadata(sidecar) or parse_run_stats_footer(str(p))
    return build_session_from_dataframe(
        df_raw,
        session_id=p.stem,
        source_path=p,
        timezone=timezone,
        log_metadata=sidecar,
        log_metadata_path=resolved_sidecar_path,
        firmware_stats=stats,
    )


def build_session_from_dataframe(
    df_raw: pd.DataFrame,
    *,
    session_id: Optional[str] = None,
    source_name: Optional[str] = None,
    source_path: Optional[str | Path] = None,
    timezone: Optional[str] = None,
    log_metadata: Optional[Mapping[str, Any]] = None,
    log_metadata_path: Optional[str | Path] = None,
    firmware_stats: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a v0 Session dict from an already-loaded dataframe and optional metadata."""
    if not isinstance(df_raw, pd.DataFrame):
        raise TypeError("df_raw must be a pandas DataFrame")

    source_ref = source_path if source_path is not None else source_name
    resolved_source_name: Optional[str] = None
    if source_name is not None:
        resolved_source_name = Path(str(source_name)).name
    elif source_path is not None:
        resolved_source_name = Path(source_path).name

    resolved_session_id = session_id
    if not isinstance(resolved_session_id, str) or not resolved_session_id.strip():
        if resolved_source_name:
            resolved_session_id = Path(resolved_source_name).stem
        else:
            resolved_session_id = "session"

    log_metadata_obj = dict(log_metadata) if isinstance(log_metadata, Mapping) else None
    excluded_time_columns = {"sample_id", "time_s", "clock", "Clock", "Time"}
    if isinstance(log_metadata_obj, dict):
        excluded_time_columns |= _declared_time_columns(log_metadata_obj)

    stats: Optional[Dict[str, Any]] = None
    if isinstance(firmware_stats, Mapping):
        stats = dict(firmware_stats)
    else:
        stats = _firmware_stats_from_log_metadata(log_metadata_obj)

    session: Dict[str, Any] = {
        "session_id": resolved_session_id,
        "source": {},
        "meta": {
            "channels": [c for c in df_raw.columns if c not in excluded_time_columns],
            "channel_info": {},  # can be enriched later
            "sample_rate_hz": None,
            "sample_rate_by_channel_hz": None,
            "device": None,
            "notes": None,
        },
        "qc": {
            "warnings": [],
            "transforms": {
                "zeroed": {"applied": False, "method": None, "by_channel": None},
                "scaled": {"applied": False, "by_channel": None},
                "filtered": {"applied": False, "method": None, "params": None},
                "resampled": {"applied": False, "target_rate_hz": None, "method": None},
            },
            "firmware_stats": stats or None,
            "parse": {
                "rows_read": int(len(df_raw)),
                "rows_ignored": None,
                "clock_column_used": None,
            },
            "time_monotonic": True,
            "time_repaired": False,
            "n_time_gaps": 0,
            "gap_total_s": 0.0,
        },
        "df_raw": df_raw,
        "df": df_raw.copy(),
    }
    if resolved_source_name is not None:
        session["source"]["filename"] = resolved_source_name
    if source_path is not None:
        session["source"]["path"] = str(source_path)
    runtime_timezone = _optional_nonempty_str(timezone)
    if runtime_timezone is not None:
        session["source"]["timezone"] = runtime_timezone
        session["source"]["timezone_source"] = "runtime_fallback"
    if isinstance(log_metadata_obj, dict):
        _apply_log_metadata(
            session,
            log_metadata=log_metadata_obj,
            log_metadata_path=str(log_metadata_path) if log_metadata_path is not None else None,
        )
    _warn_on_firmware_dropped_samples(session)
    if source_ref is not None:
        _apply_filename_stem_time_anchor(session, csv_path=source_ref)
    return session


def load_bdq_session(
    bdq_path: str | Path,
    *,
    timezone: Optional[str] = None,
) -> Dict[str, Any]:
    """Load a self-contained BDQ compact binary log into a v0 Session dict."""
    p = Path(bdq_path)
    info = read_bdq(p)
    df_raw = bdq_to_dataframe(p)
    log_metadata = bdq_to_log_metadata(info)
    session_meta = log_metadata.get("session") if isinstance(log_metadata.get("session"), Mapping) else {}
    session_id = _optional_nonempty_str(session_meta.get("session_id")) if isinstance(session_meta, Mapping) else None

    session = build_session_from_dataframe(
        df_raw,
        session_id=session_id or p.stem,
        source_path=p,
        timezone=timezone,
        log_metadata=log_metadata,
        firmware_stats=log_metadata.get("qc", {}).get("run_stats") if isinstance(log_metadata.get("qc"), Mapping) else None,
    )

    source = session.setdefault("source", {})
    source["input_format"] = "bdq"
    source["bdq_path"] = str(p)

    parse = session.setdefault("qc", {}).setdefault("parse", {})
    parse["bdq_used"] = True
    parse["bdq_sample_count"] = info.sample_count
    parse["bdq_valid_chunk_count"] = info.valid_chunk_count
    if info.detected_errors:
        parse["bdq_detected_errors"] = list(info.detected_errors)
        for error in info.detected_errors:
            _append_qc_warning(session, f"bdq_parser_warning:{error}")
    return session


def load_and_canonicalize(
    csv_path: str,
    *,
    timezone: Optional[str] = None,
    sidecar_path: Optional[str] = None,
    generic_sidecar_paths: Optional[Sequence[str | Path]] = None,
    log_metadata_path: Optional[str | Path] = None,
    generic_log_metadata_paths: Optional[Sequence[str | Path]] = None,
) -> Dict[str, Any]:
    """
    Step 1 helper for notebooks/UI:
      - load session
      - canonicalize signal names (best effort, inferred from column units)
      - build signals registry (so we can list displacement signals)
    Does NOT require normalize_ranges.
    """
    session = load_session(
        csv_path,
        timezone=timezone,
        log_metadata_path=log_metadata_path,
        generic_log_metadata_paths=generic_log_metadata_paths,
        sidecar_path=sidecar_path,
        generic_sidecar_paths=generic_sidecar_paths,
    )

    # Infer units from column headers like "... [mm]"
    df = session["df"]
    units_by_col: Dict[str, str] = {}
    for c in df.columns:
        m = _UNIT_RE.search(str(c))
        if m:
            u = (m.group(1) or "").strip()
            if u:
                units_by_col[str(c)] = u

    # Conservative domain mapping (can expand later)
    domain_by_base = {"front_shock": "suspension", "rear_shock": "suspension"}

    session = canonicalize_signal_names(
        session,
        units_by_base=units_by_col,   # note: mapping is by *column name* in your current pipeline :contentReference[oaicite:3]{index=3}
        domain_by_base=domain_by_base,
    )

    # Populate session["meta"]["signals"] with quantity="disp"/"vel"/... etc.
    session = build_signals_registry(session, strict=False)
    return session


def _append_qc_warning(session: Dict[str, Any], warning: str) -> None:
    qc = session.setdefault("qc", {})
    warnings = qc.setdefault("warnings", [])
    if warning not in warnings:
        warnings.append(warning)


def _warn_on_firmware_dropped_samples(session: Dict[str, Any]) -> None:
    stats = session.get("qc", {}).get("firmware_stats")
    dropped = _firmware_dropped_sample_count(stats)
    if dropped <= 0:
        return
    csv_path = session.get("source", {}).get("path")
    logger.warning(
        "Logger firmware reported dropped samples: samples_dropped=%s csv=%s",
        dropped,
        csv_path,
    )
    _append_qc_warning(session, f"firmware_samples_dropped:{dropped}")


def _merge_channel_info(
    session: Dict[str, Any],
    channel_info: Mapping[str, Mapping[str, Any]],
) -> None:
    meta = session.setdefault("meta", {})
    current = meta.setdefault("channel_info", {})
    if not isinstance(current, dict):
        current = {}
        meta["channel_info"] = current
    for col, info in channel_info.items():
        if not isinstance(col, str):
            continue
        existing = current.get(col)
        if isinstance(existing, dict):
            merged = dict(existing)
            merged.update(dict(info))
            current[col] = merged
        else:
            current[col] = dict(info)


def _canonical_unit_label(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    unit = value.strip()
    if unit.lower() in {"norm", "normalized", "normalised", "unitless"}:
        return "1"
    return unit


def _materialized_quantity_for_output_unit(unit: str) -> Optional[str]:
    clean = _canonical_unit_label(unit)
    if clean in {"mm", "deg"}:
        return "disp"
    return None


def _materialized_signal_name(
    *,
    sensor: Any,
    end: Any,
    domain: Any,
    quantity: str,
    unit: str,
    fallback: str,
) -> str:
    sensor_token = canonical_sensor_id(sensor)
    end_token = canonical_end(end)
    domain_token = canonical_sensor_id(domain)
    fallback_token = canonical_sensor_id(fallback) or "signal"

    if end_token and domain_token:
        base_token = f"{end_token}_{domain_token}"
    elif end_token:
        base_token = end_token
    elif sensor_token:
        base_token = sensor_token
    else:
        base_token = fallback_token

    quantity_token = canonical_sensor_id(quantity)
    if quantity_token and quantity_token != "raw":
        base = f"{base_token}_{quantity_token}"
        kind = ""
    else:
        base = base_token
        kind = "raw" if quantity_token == "raw" else ""

    return format_signal_name(
        SignalNameParts(
            base=base,
            kind=kind,
            domain=domain_token or None,
            unit=_canonical_unit_label(unit) or None,
            ops=(),
        )
    )


def _is_legacy_va_displacement_column(column: Any) -> bool:
    match = _UNIT_RE.search(str(column))
    return bool(match and (match.group(1) or "").strip() == "mm")


def _signal_matches_semantics(signal_info: Mapping[str, Any], selector: Mapping[str, Any]) -> bool:
    if signal_info.get("semantic_selection_excluded"):
        return False

    for key in ("end", "quantity", "domain", "unit", "processing_role", "motion_source_id", "motion_profile_id"):
        expected = selector.get(key)
        if expected is None or (isinstance(expected, str) and not expected.strip()):
            continue

        actual = signal_info.get(key)
        if key == "end":
            if canonical_end(actual) != canonical_end(expected):
                return False
        elif key == "unit":
            if _canonical_unit_label(actual) != _canonical_unit_label(expected):
                return False
        elif key in {"motion_source_id", "motion_profile_id"}:
            if canonical_sensor_id(actual) != canonical_sensor_id(expected):
                return False
        else:
            if canonical_sensor_id(actual) != canonical_sensor_id(expected):
                return False

    return True


def _as_finite_float(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except Exception:
        return None
    return out if np.isfinite(out) else None


def _logger_linear_materialization_report() -> Dict[str, Any]:
    return {
        "applied": False,
        "generated": [],
        "skipped": [],
        "warnings": [],
    }


def _materialize_logger_linear_calibrations(session: Dict[str, Any]) -> Dict[str, Any]:
    report = _logger_linear_materialization_report()

    df = session.get("df")
    meta = session.get("meta")
    if not isinstance(df, pd.DataFrame) or not isinstance(meta, dict):
        return report

    signals = meta.get("signals")
    if not isinstance(signals, Mapping):
        return report

    channel_info_updates: Dict[str, Dict[str, Any]] = {}
    generated_signal_infos: list[dict[str, Any]] = []
    for column, info in signals.items():
        if not isinstance(column, str) or not isinstance(info, Mapping):
            continue
        if column not in df.columns:
            continue
        if str(info.get("origin") or "").strip().lower() != "logger":
            continue
        if str(info.get("quantity") or "").strip().lower() != "raw":
            continue
        if _canonical_unit_label(info.get("unit")) != "counts":
            continue

        calibration = info.get("calibration")
        if not isinstance(calibration, Mapping):
            report["skipped"].append({"source_column": column, "reason": "missing_calibration"})
            continue

        calibration_type = str(calibration.get("type") or "linear").strip().lower()
        if calibration_type not in {"linear", "zero_offset"}:
            report["skipped"].append(
                {"source_column": column, "reason": "unsupported_calibration_type", "type": calibration_type}
            )
            continue

        input_unit = _canonical_unit_label(calibration.get("input_unit")) or "counts"
        if input_unit != "counts":
            report["skipped"].append(
                {"source_column": column, "reason": "unsupported_input_unit", "input_unit": input_unit}
            )
            continue

        output_unit = _canonical_unit_label(calibration.get("output_unit"))
        quantity = _materialized_quantity_for_output_unit(output_unit)
        if quantity is None:
            report["skipped"].append(
                {"source_column": column, "reason": "unsupported_output_unit", "output_unit": output_unit}
            )
            continue

        sensor_zero_count = _as_finite_float(calibration.get("sensor_zero_count"))
        sensor_full_count = _as_finite_float(calibration.get("sensor_full_count"))
        sensor_full_travel = _as_finite_float(calibration.get("sensor_full_travel"))
        if sensor_zero_count is None or sensor_full_count is None or sensor_full_travel is None:
            report["skipped"].append({"source_column": column, "reason": "incomplete_calibration"})
            continue
        if sensor_full_travel <= 0:
            report["skipped"].append({"source_column": column, "reason": "non_positive_full_travel"})
            continue

        span_counts = sensor_full_count - sensor_zero_count
        span_abs = abs(span_counts)
        if span_abs == 0:
            report["skipped"].append({"source_column": column, "reason": "zero_span_counts"})
            continue

        installed_zero_count = _as_finite_float(calibration.get("installed_zero_count"))
        zero_reference = installed_zero_count if installed_zero_count is not None else sensor_zero_count
        zero_reference_source = "installed_zero_count" if installed_zero_count is not None else "sensor_zero_count"
        invert = calibration.get("invert")
        invert_flag = bool(invert) if isinstance(invert, bool) else bool(sensor_full_count < sensor_zero_count)

        source_id = _signal_source_identity(info)
        selector = {
            "end": info.get("end"),
            "quantity": quantity,
            "domain": info.get("domain"),
            "unit": output_unit,
        }
        same_source_selector = dict(selector)
        if source_id:
            same_source_selector["motion_source_id"] = source_id

        existing_matches = [
            str(existing_col)
            for existing_col, existing_info in signals.items()
            if isinstance(existing_info, Mapping)
            and str(existing_col) != column
            and _signal_matches_semantics(existing_info, same_source_selector if source_id else selector)
        ]
        generated_matches = [
            str(rec.get("output_column"))
            for rec in generated_signal_infos
            if isinstance(rec, Mapping)
            and _signal_matches_semantics(rec, same_source_selector if source_id else selector)
        ]
        if existing_matches or generated_matches:
            report["skipped"].append(
                {
                    "source_column": column,
                    "reason": "output_semantics_exists",
                    "matching_output_columns": existing_matches + generated_matches,
                }
            )
            continue

        core_existing_matches = [
            str(existing_col)
            for existing_col, existing_info in signals.items()
            if isinstance(existing_info, Mapping)
            and str(existing_col) != column
            and _signal_matches_semantics(existing_info, selector)
        ]
        core_generated_matches = [
            str(rec.get("output_column"))
            for rec in generated_signal_infos
            if isinstance(rec, Mapping) and _signal_matches_semantics(rec, selector)
        ]
        processing_role = str(info.get("processing_role") or "").strip()
        if not processing_role:
            processing_role = "secondary_analysis" if (core_existing_matches or core_generated_matches) else "primary_analysis"

        canonical_output_column = _materialized_signal_name(
            sensor=info.get("sensor"),
            end=info.get("end"),
            domain=info.get("domain"),
            quantity=quantity,
            unit=output_unit,
            fallback=column,
        )
        output_column = _unique_signal_column_name(
            canonical_output_column,
            source_id=source_id,
            fallback=column,
            existing_names=set(map(str, df.columns)) | set(channel_info_updates.keys()),
        )
        if output_column in df.columns:
            report["skipped"].append(
                {
                    "source_column": column,
                    "reason": "output_column_exists",
                    "output_column": output_column,
                }
            )
            continue

        counts_per_output_unit = span_abs / sensor_full_travel
        values = pd.to_numeric(df[column], errors="coerce").astype(float)
        materialized = (values - zero_reference) / counts_per_output_unit
        if invert_flag:
            materialized = -materialized
        df.loc[:, output_column] = materialized
        derivation_method = (
            "logger_zero_offset_calibration"
            if calibration_type == "zero_offset"
            else "logger_linear_calibration"
        )

        channel_info_updates[output_column] = {
            "unit": output_unit,
            "sensor": info.get("sensor"),
            "end": info.get("end"),
            "role": quantity,
            "quantity": quantity,
            "domain": info.get("domain"),
            "source": [column],
            "source_columns": [column],
            "calibration_ref": info.get("calibration_ref"),
            "calibration": dict(calibration),
            "origin": "analysis",
            "processing_role": processing_role,
            "derivation": {
                "method": derivation_method,
                "source_col": column,
                "calibration_type": calibration_type,
                "counts_per_output_unit": float(counts_per_output_unit),
                "output_unit": output_unit,
                "zero_reference": float(zero_reference),
                "zero_reference_source": zero_reference_source,
                "invert": invert_flag,
            },
        }
        if source_id:
            channel_info_updates[output_column]["motion_source_id"] = source_id
        if "motion_profile_id" in info:
            channel_info_updates[output_column]["motion_profile_id"] = info.get("motion_profile_id")
        if output_column != canonical_output_column:
            channel_info_updates[output_column]["canonical_dataframe_column"] = canonical_output_column
            channel_info_updates[output_column]["dataframe_column_disambiguation_token"] = source_id or column
        if "nominal_rate_hz" in info:
            channel_info_updates[output_column]["nominal_rate_hz"] = info.get("nominal_rate_hz")

        report["generated"].append(
            {
                "source_column": column,
                "output_column": output_column,
                "sensor": info.get("sensor"),
                "end": info.get("end"),
                "domain": info.get("domain"),
                "quantity": quantity,
                "unit": output_unit,
                "calibration_type": calibration_type,
                "counts_per_output_unit": float(counts_per_output_unit),
                "zero_reference": float(zero_reference),
                "zero_reference_source": zero_reference_source,
                "invert": invert_flag,
            }
        )
        generated_signal_infos.append(
            {
                "output_column": output_column,
                "end": info.get("end"),
                "domain": info.get("domain"),
                "quantity": quantity,
                "unit": output_unit,
                "motion_source_id": source_id,
                "processing_role": processing_role,
            }
        )

    if channel_info_updates:
        session["df"] = df
        _merge_channel_info(session, channel_info_updates)
        report["applied"] = True

    return report


def _motion_normalization_ranges(
    motion_meta: Mapping[str, Any],
    normalize_ranges: Mapping[str, float],
) -> Dict[str, float]:
    """Return normalization ranges for generated motion displacement channels."""
    out: Dict[str, float] = {}
    generated = motion_meta.get("generated", [])
    if not isinstance(generated, Sequence) or isinstance(generated, (str, bytes)):
        return out

    for rec in generated:
        if not isinstance(rec, Mapping):
            continue
        if rec.get("quantity") != "disp":
            continue
        output_col = rec.get("output_col")
        source_col = rec.get("source_col")
        if not isinstance(output_col, str) or not isinstance(source_col, str):
            continue
        if source_col in normalize_ranges:
            out[output_col] = float(normalize_ranges[source_col])
    return out


def _motion_zeroed_columns(
    motion_meta: Mapping[str, Any],
    zeroed_columns: set[str],
) -> set[str]:
    """Propagate in-place zeroing provenance to generated motion displacement outputs."""
    out: set[str] = set()
    generated = motion_meta.get("generated", [])
    if not isinstance(generated, Sequence) or isinstance(generated, (str, bytes)):
        return out

    for rec in generated:
        if not isinstance(rec, Mapping):
            continue
        if rec.get("quantity") != "disp":
            continue
        output_col = rec.get("output_col")
        source_col = rec.get("source_col")
        if isinstance(output_col, str) and isinstance(source_col, str) and source_col in zeroed_columns:
            out.add(output_col)
    return out


def _motion_legacy_va_suppressed_columns(motion_meta: Mapping[str, Any]) -> set[str]:
    """Return displacement columns whose velocity/acceleration are owned by motion_derivation."""
    out: set[str] = set()
    generated = motion_meta.get("generated", [])
    if not isinstance(generated, Sequence) or isinstance(generated, (str, bytes)):
        return out

    for rec in generated:
        if not isinstance(rec, Mapping):
            continue
        if rec.get("quantity") != "disp":
            continue
        if rec.get("role") != "primary_analysis":
            continue
        for key in ("source_col", "output_col"):
            value = rec.get(key)
            if isinstance(value, str) and value.strip():
                out.add(value)
    return out


def _channel_info_for_scaled_outputs(
    session: Mapping[str, Any],
    scale_meta: Mapping[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """Preserve analysis-role provenance on normalized outputs."""
    signals = ((session.get("meta") or {}).get("signals") or {})
    if not isinstance(signals, Mapping):
        signals = {}

    out: Dict[str, Dict[str, Any]] = {}
    per_column = scale_meta.get("per_column", [])
    if not isinstance(per_column, Sequence) or isinstance(per_column, (str, bytes)):
        return out

    passthrough_keys = (
        "sensor",
        "end",
        "domain",
        "processing_role",
        "motion_source_id",
        "motion_profile_id",
    )
    for rec in per_column:
        if not isinstance(rec, Mapping) or rec.get("status") != "ok":
            continue
        norm_col = rec.get("norm_col")
        source_col = rec.get("source_column", rec.get("column"))
        if not isinstance(norm_col, str) or not isinstance(source_col, str):
            continue

        source_info = signals.get(source_col)
        if not isinstance(source_info, Mapping):
            continue

        info: Dict[str, Any] = {
            "unit": "1",
            "quantity": "disp_norm",
            "source": [source_col],
            "source_columns": [source_col],
            "derivation": {
                "method": "normalization",
                "source_col": source_col,
                "full_range": rec.get("full_range"),
                "clip_0_1": bool(rec.get("clip_0_1", False)),
            },
        }
        for key in passthrough_keys:
            value = source_info.get(key)
            if value is not None:
                info[key] = value

        source_ops = source_info.get("op_chain")
        if isinstance(source_ops, (list, tuple)):
            ops = [str(x).strip() for x in source_ops if str(x).strip()]
        elif source_ops is not None and str(source_ops).strip():
            ops = [str(source_ops).strip()]
        else:
            ops = []
        if not any(str(op).strip().lower() == "norm" for op in ops):
            ops.append("norm")
        info["op_chain"] = ops

        source_derivation = source_info.get("derivation")
        if isinstance(source_derivation, Mapping):
            info["derivation"]["source_derivation"] = dict(source_derivation)

        out[norm_col] = info
    return out


def _normalized_fit_import_config(fit_import: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    cfg = dict(_FIT_IMPORT_DEFAULTS)
    if isinstance(fit_import, Mapping):
        cfg.update(dict(fit_import))
    return cfg


def _positive_float_or_none(value: Any, *, field_name: str) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        out = float(value)
    except Exception as exc:
        raise ValueError(f"{field_name} must be a positive finite number or None") from exc
    if not np.isfinite(out) or out <= 0:
        raise ValueError(f"{field_name} must be a positive finite number or None")
    return out


def _session_absolute_bounds(session: Dict[str, Any]) -> Optional[tuple[pd.Timestamp, pd.Timestamp]]:
    meta = session.get("meta", {})
    source = session.get("source", {})

    anchor = None
    if isinstance(meta, dict):
        anchor = meta.get("t0_datetime")
    if anchor is None and isinstance(source, dict):
        anchor = source.get("created_local")
    if not isinstance(anchor, str) or not anchor.strip():
        return None

    df = session.get("df")
    if not isinstance(df, pd.DataFrame):
        return None
    if "time_s" not in df.columns:
        return None

    t = pd.to_numeric(df["time_s"], errors="coerce").dropna()
    if t.empty:
        return None

    start = pd.Timestamp(anchor)
    end = start + pd.to_timedelta(float(t.max()), unit="s")
    return start, end


def _is_fit_gps_position_column(column: str, fit_meta: Mapping[str, Any]) -> bool:
    channel_info = fit_meta.get("channel_info", {})
    if isinstance(channel_info, Mapping):
        info = channel_info.get(column)
        if isinstance(info, Mapping) and info.get("role") in _FIT_GPS_POSITION_ROLES:
            return True
    return column in _FIT_GPS_POSITION_COLUMNS


def _fit_gps_position_pair_summary(
    fit_df: pd.DataFrame,
    resampled_df: pd.DataFrame,
    *,
    target_time_s: np.ndarray,
    gps_columns: Sequence[str],
    max_gap_s: Optional[float],
    resampling_meta: Sequence[Mapping[str, Any]],
) -> Optional[Dict[str, Any]]:
    lat_col = next((c for c in gps_columns if "latitude" in c), None)
    lon_col = next((c for c in gps_columns if "longitude" in c), None)
    if lat_col is None or lon_col is None:
        return None

    raw_pairs = 0
    finite_target = target_time_s[np.isfinite(target_time_s)]
    if finite_target.size and lat_col in fit_df.columns and lon_col in fit_df.columns:
        t_src = pd.to_numeric(fit_df["time_s"], errors="coerce").to_numpy(dtype=float)
        lat = pd.to_numeric(fit_df[lat_col], errors="coerce").to_numpy(dtype=float)
        lon = pd.to_numeric(fit_df[lon_col], errors="coerce").to_numpy(dtype=float)
        in_window = (
            np.isfinite(t_src)
            & (t_src >= float(np.nanmin(finite_target)))
            & (t_src <= float(np.nanmax(finite_target)))
        )
        raw_pairs = int(np.count_nonzero(in_window & np.isfinite(lat) & np.isfinite(lon)))

    resampled_pairs = 0
    if lat_col in resampled_df.columns and lon_col in resampled_df.columns:
        lat_out = pd.to_numeric(resampled_df[lat_col], errors="coerce").to_numpy(dtype=float)
        lon_out = pd.to_numeric(resampled_df[lon_col], errors="coerce").to_numpy(dtype=float)
        resampled_pairs = int(np.count_nonzero(np.isfinite(lat_out) & np.isfinite(lon_out)))

    gap_rejected = 0
    for meta in resampling_meta:
        stats_by_col = meta.get("column_stats", {})
        if not isinstance(stats_by_col, Mapping):
            continue
        for col in (lat_col, lon_col):
            stats = stats_by_col.get(col)
            if isinstance(stats, Mapping):
                gap_rejected += int(stats.get("n_gap_rejected", 0) or 0)

    return {
        "position_columns": [lat_col, lon_col],
        "max_gap_s": max_gap_s,
        "raw_position_points_in_session_window": raw_pairs,
        "resampled_position_points": resampled_pairs,
        "gap_rejected_samples": gap_rejected,
    }


def _resample_fit_columns_onto_primary(
    session: Dict[str, Any],
    *,
    fit_df: pd.DataFrame,
    fit_meta: Mapping[str, Any],
    method: str,
    max_gap_s: Optional[float],
    gps_max_gap_s: Optional[float],
) -> None:
    df = session.get("df")
    if not isinstance(df, pd.DataFrame):
        raise ValueError("session['df'] must be a DataFrame before FIT resampling")
    if "time_s" not in df.columns:
        raise ValueError("session['df'] missing required time_s column for FIT resampling")

    columns = [
        c
        for c in fit_meta.get("resample_columns", [])
        if isinstance(c, str) and c in fit_df.columns
    ]
    if not columns:
        return

    target_time_s = pd.to_numeric(df["time_s"], errors="coerce").to_numpy(dtype=float)
    gps_columns = [c for c in columns if _is_fit_gps_position_column(c, fit_meta)]
    other_columns = [c for c in columns if c not in gps_columns]
    column_groups = [
        ("fit", other_columns, max_gap_s),
        ("fit_gps_position", gps_columns, gps_max_gap_s),
    ]
    resampling_meta: list[Mapping[str, Any]] = []
    if len(fit_df.index) >= 2:
        resampled_df = pd.DataFrame({"time_s": target_time_s})
        for group_name, group_columns, group_max_gap_s in column_groups:
            if not group_columns:
                continue
            group_df, group_meta = resample_to_time_grid(
                fit_df,
                src_time_col="time_s",
                target_time_s=target_time_s,
                columns=group_columns,
                method=method,
                allow_extrapolation=False,
                max_gap_s=group_max_gap_s,
            )
            for col in group_columns:
                resampled_df[col] = group_df[col].to_numpy()
            group_meta["column_group"] = group_name
            resampling_meta.append(group_meta)
    else:
        resampled_df = pd.DataFrame({"time_s": target_time_s})
        for col in columns:
            resampled_df[col] = np.nan
        rs_meta = {
            "method": method,
            "src_time_col": "time_s",
            "target_time_col": "time_s",
            "allow_extrapolation": False,
            "src_time_min": None,
            "src_time_max": None,
            "n_target": int(len(target_time_s)),
            "columns": list(columns),
            "max_gap_s": None,
            "column_group": "fit",
            "column_stats": {col: {"n_source": int(len(fit_df.index)), "n_output": 0} for col in columns},
        }
        resampling_meta.append(rs_meta)
        _append_qc_warning(session, "fit_import_resample_skipped_too_few_samples")

    for col in columns:
        df[col] = resampled_df[col].to_numpy()

    qc = session.setdefault("qc", {})
    resampling = qc.setdefault("resampling", [])
    stream_name = str(fit_meta.get("stream_name", "gps_fit"))
    for rs_meta in resampling_meta:
        resampling.append({"stream": stream_name, **rs_meta})

    gps_summary = _fit_gps_position_pair_summary(
        fit_df,
        resampled_df,
        target_time_s=target_time_s,
        gps_columns=gps_columns,
        max_gap_s=gps_max_gap_s,
        resampling_meta=resampling_meta,
    )
    if gps_summary is not None:
        fit_qc = qc.setdefault("fit_import", {})
        fit_qc["gps_resampling"] = gps_summary
        if (
            gps_summary["raw_position_points_in_session_window"] == 0
            and gps_summary["resampled_position_points"] == 0
        ):
            _append_qc_warning(session, "fit_import_no_gps_position_points_in_session_window")
        if gps_summary["gap_rejected_samples"] > 0:
            _append_qc_warning(session, "fit_import_gps_resample_gap_limited")

    transforms = qc.setdefault("transforms", {})
    transforms["resampled"] = {
        "applied": True,
        "target_rate_hz": session.get("meta", {}).get("sample_rate_hz"),
        "method": method,
        "fit_resample_max_gap_s": max_gap_s,
        "fit_gps_resample_max_gap_s": gps_max_gap_s,
    }

    _merge_channel_info(session, fit_meta.get("channel_info", {}))


def attach_fit_stream(
    session: Dict[str, Any],
    *,
    fit_df: pd.DataFrame,
    fit_meta: Mapping[str, Any],
    stream_name: str = "gps_fit",
) -> Dict[str, Any]:
    stream_dfs = session.setdefault("stream_dfs", {})
    if not isinstance(stream_dfs, dict):
        stream_dfs = {}
        session["stream_dfs"] = stream_dfs
    stream_dfs[stream_name] = fit_df

    register_stream_metadata(
        session,
        stream_name=stream_name,
        kind="intermittent",
        time_col="time_s",
        notes="Garmin FIT navigation stream",
    )

    meta = session.setdefault("meta", {})
    fit_streams = meta.setdefault("secondary_streams", {})
    if not isinstance(fit_streams, dict):
        fit_streams = {}
        meta["secondary_streams"] = fit_streams
    fit_streams[stream_name] = dict(fit_meta)

    source = session.setdefault("source", {})
    aux_sources = source.setdefault("aux_sources", [])
    if not isinstance(aux_sources, list):
        aux_sources = []
        source["aux_sources"] = aux_sources
    aux_sources[:] = [x for x in aux_sources if not (isinstance(x, dict) and x.get("stream_name") == stream_name)]
    aux_sources.append(
        {
            "kind": "fit",
            "stream_name": stream_name,
            "path": fit_meta.get("path"),
            "filename": fit_meta.get("filename"),
            "sha256": fit_meta.get("fit_sha256"),
        }
    )
    return session


def _fit_failure_policy_warns(cfg: Mapping[str, Any]) -> bool:
    policy = str(cfg.get("failure_policy") or cfg.get("on_error") or "raise").strip().lower()
    return policy in {"warn", "warning", "qc_warning", "skip", "continue"}


def enrich_session_with_fit(
    session: Dict[str, Any],
    *,
    fit_import: Optional[Mapping[str, Any]],
    fit_stream: Optional[Mapping[str, Any]] = None,
    fit_candidates: Optional[Sequence[Mapping[str, Any]]] = None,
    fit_bindings: Optional[Sequence[Mapping[str, Any]] | Mapping[str, Any] | str | bytes | Path] = None,
) -> Dict[str, Any]:
    cfg = _normalized_fit_import_config(fit_import)
    if not bool(cfg.get("enabled")):
        return session
    if _fit_failure_policy_warns(cfg):
        try:
            return _enrich_session_with_fit_impl(
                session,
                fit_import=cfg,
                fit_stream=fit_stream,
                fit_candidates=fit_candidates,
                fit_bindings=fit_bindings,
            )
        except Exception as exc:
            logger.warning("FIT enrichment failed; continuing without FIT data: %s", exc)
            _append_qc_warning(session, "fit_import_failed")
            fit_qc = session.setdefault("qc", {}).setdefault("fit_import", {})
            fit_qc.update(
                {
                    "enabled": True,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            return session

    return _enrich_session_with_fit_impl(
        session,
        fit_import=cfg,
        fit_stream=fit_stream,
        fit_candidates=fit_candidates,
        fit_bindings=fit_bindings,
    )


def _enrich_session_with_fit_impl(
    session: Dict[str, Any],
    *,
    fit_import: Mapping[str, Any],
    fit_stream: Optional[Mapping[str, Any]] = None,
    fit_candidates: Optional[Sequence[Mapping[str, Any]]] = None,
    fit_bindings: Optional[Sequence[Mapping[str, Any]] | Mapping[str, Any] | str | bytes | Path] = None,
) -> Dict[str, Any]:
    cfg = _normalized_fit_import_config(fit_import)

    stream_name = str(cfg.get("raw_stream_name") or "gps_fit")
    selected: Optional[Mapping[str, Any]] = None

    if fit_stream is not None:
        fit_df = fit_stream.get("df") if isinstance(fit_stream, Mapping) else None
        fit_meta = fit_stream.get("meta") if isinstance(fit_stream, Mapping) else None
        if not isinstance(fit_df, pd.DataFrame):
            raise TypeError("fit_stream['df'] must be a pandas DataFrame")
        if not isinstance(fit_meta, Mapping):
            raise TypeError("fit_stream['meta'] must be a mapping")
        fit_meta = dict(fit_meta)
    else:
        bounds = _session_absolute_bounds(session)
        if bounds is None:
            _append_qc_warning(session, "fit_import_skipped_missing_absolute_time_anchor")
            return session

        session_start, session_end = bounds
        if fit_candidates is not None:
            candidates = find_overlapping_fit_candidates(
                fit_candidates,
                session_start_datetime=session_start.isoformat(),
                session_end_datetime=session_end.isoformat(),
                partial_overlap=str(cfg.get("partial_overlap", "allow")),
            )
        else:
            fit_dir = cfg.get("fit_dir")
            if not isinstance(fit_dir, str) or not fit_dir.strip():
                raise ValueError(
                    "fit_import.enabled=True requires fit_import.fit_dir unless fit_stream or fit_candidates is provided"
                )
            candidates = find_overlapping_fit_files(
                fit_dir=fit_dir,
                session_start_datetime=session_start.isoformat(),
                session_end_datetime=session_end.isoformat(),
                field_allowlist=cfg.get("field_allowlist"),
                partial_overlap=str(cfg.get("partial_overlap", "allow")),
            )
        if not candidates:
            _append_qc_warning(session, "fit_import_no_overlapping_files")
            return session

        source = session.get("source", {})
        selected = select_fit_candidate(
            session_id=session.get("session_id"),
            csv_path=source.get("path") if isinstance(source, dict) else None,
            csv_sha256=source.get("sha256") if isinstance(source, dict) else None,
            candidates=candidates,
            ambiguity_policy=str(cfg.get("ambiguity_policy", "require_binding")),
            bindings=fit_bindings,
            bindings_path=cfg.get("bindings_path"),
        )
        if selected is None:
            _append_qc_warning(session, "fit_import_no_selected_file")
            return session

        selected_stream = selected.get("fit_stream")
        if isinstance(selected_stream, Mapping):
            fit_df = selected_stream.get("df")
            fit_meta = selected_stream.get("meta")
            if not isinstance(fit_df, pd.DataFrame):
                raise TypeError("selected fit candidate fit_stream['df'] must be a pandas DataFrame")
            if not isinstance(fit_meta, Mapping):
                raise TypeError("selected fit candidate fit_stream['meta'] must be a mapping")
            fit_meta = dict(fit_meta)
        elif "fit_input" in selected:
            fit_df, fit_meta = parse_fit_stream(
                selected["fit_input"],
                session_start_datetime=session_start.isoformat(),
                field_allowlist=cfg.get("field_allowlist"),
                source_name=selected.get("filename"),
            )
            fit_meta = dict(fit_meta)
        else:
            fit_path = selected.get("path")
            if not isinstance(fit_path, str) or not fit_path.strip():
                raise ValueError(
                    "Selected FIT candidate does not contain a usable path, fit_input, or fit_stream"
                )
            fit_df, fit_meta = load_fit_stream(
                fit_path,
                session_start_datetime=session_start.isoformat(),
                field_allowlist=cfg.get("field_allowlist"),
            )
            fit_meta = dict(fit_meta)
        fit_meta["match"] = {
            "overlap_s": float(selected.get("overlap_s", 0.0)),
            "overlap_start_datetime": selected.get("overlap_start_datetime"),
            "overlap_end_datetime": selected.get("overlap_end_datetime"),
            "ambiguity_policy": cfg.get("ambiguity_policy"),
        }

    fit_meta["stream_name"] = stream_name
    fit_meta.setdefault("source_kind", "fit_enrichment")
    fit_meta.setdefault("source", "fit_enrichment")

    if bool(cfg.get("persist_raw_stream", True)):
        attach_fit_stream(session, fit_df=fit_df, fit_meta=fit_meta, stream_name=stream_name)

    if bool(cfg.get("resample_to_primary", True)):
        _resample_fit_columns_onto_primary(
            session,
            fit_df=fit_df,
            fit_meta=fit_meta,
            method=str(cfg.get("resample_method", "linear")),
            max_gap_s=_positive_float_or_none(
                cfg.get("resample_max_gap_s"),
                field_name="fit_import.resample_max_gap_s",
            ),
            gps_max_gap_s=_positive_float_or_none(
                cfg.get("gps_resample_max_gap_s"),
                field_name="fit_import.gps_resample_max_gap_s",
            ),
        )

    qc = session.setdefault("qc", {})
    fit_qc = qc.setdefault("fit_import", {})
    fit_qc.update(
        {
            "enabled": True,
            "selected_file": fit_meta.get("filename"),
            "stream_name": stream_name,
            "overlap_s": float(selected.get("overlap_s", 0.0)) if selected is not None else None,
            "partial_overlap": str(cfg.get("partial_overlap", "allow")),
        }
    )
    return session
    
def _soften_active_mask_from_time_s(
    df: pd.DataFrame,
    base_active: Sequence[bool],
    *,
    window: str,
    padding: str,
    min_segment: str,
) -> pd.Series:
    """Apply the standard activity rolling/padding/min-segment policy."""
    if "time_s" not in df.columns:
        raise ValueError("Expected 'time_s' in df for activity mask")

    t = pd.to_numeric(df["time_s"], errors="coerce").to_numpy(dtype=float, copy=False)
    base = np.asarray(base_active, dtype=bool)
    if base.shape[0] != len(df.index):
        raise ValueError("activity base mask must align to df rows")

    finite_time = np.isfinite(t)
    if not np.any(finite_time):
        return pd.Series(False, index=df.index, name=ACTIVE_MASK_COL)

    td = pd.to_timedelta(t[finite_time], unit="s")
    active = pd.Series(base[finite_time], index=td).sort_index(kind="stable")

    # rolling soften
    active = active.rolling(window, min_periods=1).max().astype(bool)

    pad = pd.to_timedelta(padding)
    minseg = pd.to_timedelta(min_segment)

    # contiguous blocks (time-indexed series)
    merged: list[list[pd.Timedelta]] = []
    if active.any():
        block_id = (active != active.shift(fill_value=False)).cumsum()
        segments = []
        for _, g in active.groupby(block_id):
            if not bool(g.iloc[0]):
                continue
            s = g.index[0] - pad
            e = g.index[-1] + pad
            segments.append([s, e])

        segments.sort(key=lambda x: x[0])
        for s, e in segments:
            if not merged or s > merged[-1][1]:
                merged.append([s, e])
            else:
                merged[-1][1] = max(merged[-1][1], e)

        merged = [[s, e] for s, e in merged if (e - s) >= minseg]

    original_td = pd.to_timedelta(t, unit="s")
    keep_values = np.zeros(len(df.index), dtype=bool)
    for s, e in merged:
        keep_values |= finite_time & (original_td >= s) & (original_td <= e)

    return pd.Series(keep_values, index=df.index, name=ACTIVE_MASK_COL)


def _build_active_mask_from_time_s(
    df: pd.DataFrame,
    *,
    disp_col: Optional[str],
    vel_col: Optional[str],
    disp_thresh: float,
    vel_thresh: float,
    window: str,
    padding: str,
    min_segment: str,
) -> pd.Series:
    """
    Return boolean mask aligned to df.index. Uses time_s to build a TimedeltaIndex internally.
    Non-destructive: does not modify df.
    """
    if "time_s" not in df.columns:
        raise ValueError("Expected 'time_s' in df for activity mask")

    if disp_col not in df.columns or vel_col not in df.columns:
        # soft-fail: return all True so downstream behaves identically to "no masking"
        return pd.Series(True, index=df.index, name=ACTIVE_MASK_COL)

    disp = pd.to_numeric(df[disp_col], errors="coerce").to_numpy(dtype=float)
    vel = pd.to_numeric(df[vel_col], errors="coerce").to_numpy(dtype=float)
    active = np.isfinite(disp) & np.isfinite(vel) & (np.abs(disp) > disp_thresh) & (np.abs(vel) > vel_thresh)
    return _soften_active_mask_from_time_s(
        df,
        active,
        window=window,
        padding=padding,
        min_segment=min_segment,
    )


def _activity_detection_enabled(activity_detection: Optional[Mapping[str, Any]]) -> bool:
    return isinstance(activity_detection, Mapping) and bool(activity_detection.get("enabled", False))


def _activity_detection_candidates(activity_detection: Optional[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    if not isinstance(activity_detection, Mapping):
        return []
    raw = activity_detection.get("candidates")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    return [candidate for candidate in raw if isinstance(candidate, Mapping)]


def _activity_candidate_id(candidate: Mapping[str, Any], index: int) -> str:
    text = str(candidate.get("id") or "").strip()
    return text or f"candidate_{index + 1}"


def _activity_candidate_type(candidate: Mapping[str, Any]) -> str:
    return str(candidate.get("type") or candidate.get("kind") or "motion_pair").strip().lower()


def _resolve_activity_motion_columns(
    session: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    purpose_prefix: str,
) -> tuple[Optional[str], Optional[str], Optional[Mapping[str, Any]], Optional[Mapping[str, Any]]]:
    disp_selector = candidate.get("disp_selector")
    if disp_selector is None:
        disp_selector = candidate.get("selector")
    vel_selector = candidate.get("vel_selector")

    disp_col = _optional_nonempty_str(candidate.get("disp_col"))
    vel_col = _optional_nonempty_str(candidate.get("vel_col"))

    if disp_col is None and isinstance(disp_selector, Mapping):
        disp_col = resolve_signal_selector(
            session,
            disp_selector,
            purpose=f"{purpose_prefix} displacement",
        )
    if vel_col is None and isinstance(vel_selector, Mapping):
        vel_col = resolve_signal_selector(
            session,
            vel_selector,
            purpose=f"{purpose_prefix} velocity",
        )
    if disp_col and not vel_col:
        try:
            vel_col = name_vel(disp_col)
        except ValueError:
            vel_col = None

    return (
        disp_col,
        vel_col,
        disp_selector if isinstance(disp_selector, Mapping) else None,
        vel_selector if isinstance(vel_selector, Mapping) else None,
    )


def _activity_motion_displacement_cols_for_va(
    session: Mapping[str, Any],
    activity_detection: Optional[Mapping[str, Any]],
) -> list[str]:
    cols: list[str] = []
    if not _activity_detection_enabled(activity_detection):
        return cols
    for index, candidate in enumerate(_activity_detection_candidates(activity_detection)):
        candidate_type = _activity_candidate_type(candidate)
        if candidate_type not in {"motion_pair", "wheel_motion", "legacy_motion"}:
            continue
        if candidate_type == "legacy_motion":
            continue
        candidate_id = _activity_candidate_id(candidate, index)
        disp_col, _vel_col, _disp_selector, _vel_selector = _resolve_activity_motion_columns(
            session,
            candidate,
            purpose_prefix=f"activity candidate {candidate_id}",
        )
        if disp_col and disp_col not in cols:
            cols.append(disp_col)
    return cols


def _nearest_sample_distance_s(source_t: np.ndarray, target_t: np.ndarray) -> np.ndarray:
    if source_t.size == 0:
        return np.full_like(target_t, np.inf, dtype=float)
    right = np.searchsorted(source_t, target_t, side="left")
    left = np.clip(right - 1, 0, source_t.size - 1)
    right = np.clip(right, 0, source_t.size - 1)
    return np.minimum(np.abs(target_t - source_t[left]), np.abs(source_t[right] - target_t))


def _positive_activity_float(value: Any, *, default: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float(default)
    return out if np.isfinite(out) and out > 0 else float(default)


def _gps_activity_source(
    session: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> tuple[Optional[str], Optional[pd.DataFrame], Mapping[str, Any]]:
    requested_source = _optional_nonempty_str(candidate.get("source_id")) or _optional_nonempty_str(
        candidate.get("stream_name")
    )
    source_id = requested_source or preferred_gps_source_name(session)

    stream_dfs = session.get("stream_dfs")
    meta = session.get("meta") if isinstance(session.get("meta"), Mapping) else {}
    secondary_streams = meta.get("secondary_streams") if isinstance(meta.get("secondary_streams"), Mapping) else {}

    if source_id and source_id != "primary" and isinstance(stream_dfs, Mapping):
        stream_df = stream_dfs.get(source_id)
        if isinstance(stream_df, pd.DataFrame):
            stream_meta = secondary_streams.get(source_id) if isinstance(secondary_streams, Mapping) else {}
            return source_id, stream_df, stream_meta if isinstance(stream_meta, Mapping) else {}

    primary_df = session.get("df")
    if isinstance(primary_df, pd.DataFrame):
        if source_id in {None, "primary"}:
            return "primary", primary_df, meta
        columns = resolve_gps_columns(meta, known_columns=set(map(str, primary_df.columns)))
        if columns is not None:
            return "primary", primary_df, meta

    if isinstance(stream_dfs, Mapping):
        for fallback_id in ("gps_logger", "gps_fit"):
            stream_df = stream_dfs.get(fallback_id)
            if isinstance(stream_df, pd.DataFrame):
                stream_meta = secondary_streams.get(fallback_id) if isinstance(secondary_streams, Mapping) else {}
                return fallback_id, stream_df, stream_meta if isinstance(stream_meta, Mapping) else {}

    return None, None, {}


def _build_gps_speed_activity_candidate(
    session: Mapping[str, Any],
    df: pd.DataFrame,
    candidate: Mapping[str, Any],
    *,
    candidate_id: str,
    window: str,
    padding: str,
    min_segment: str,
) -> tuple[Optional[pd.Series], dict[str, Any]]:
    source_id, source_df, source_meta = _gps_activity_source(session, candidate)
    speed_threshold = _positive_activity_float(
        candidate.get("speed_threshold_mps", candidate.get("threshold_mps")),
        default=0.5,
    )
    max_gap_s = _positive_activity_float(candidate.get("max_gap_s"), default=5.0)
    meta: dict[str, Any] = {
        "id": candidate_id,
        "type": "gps_speed",
        "source_id": source_id,
        "speed_threshold_mps": float(speed_threshold),
        "max_gap_s": float(max_gap_s),
    }
    if source_df is None or "time_s" not in source_df.columns:
        meta.update({"status": "missing", "reason": "gps_source_missing"})
        return None, meta

    speed_col = _optional_nonempty_str(candidate.get("speed_col"))
    if speed_col is None:
        columns = resolve_gps_columns(source_meta, known_columns=set(map(str, source_df.columns)))
        speed_col = columns.speed if columns is not None else None
    if speed_col is None or speed_col not in source_df.columns:
        meta.update({"status": "missing", "reason": "speed_column_missing", "speed_col": speed_col})
        return None, meta

    source_t_raw = pd.to_numeric(source_df["time_s"], errors="coerce").to_numpy(dtype=float)
    source_speed_raw = pd.to_numeric(source_df[speed_col], errors="coerce").to_numpy(dtype=float)
    source_valid = np.isfinite(source_t_raw) & np.isfinite(source_speed_raw)
    if not np.any(source_valid):
        meta.update({"status": "empty", "reason": "no_finite_speed_rows", "speed_col": speed_col})
        return None, meta

    source_t = source_t_raw[source_valid]
    source_speed = source_speed_raw[source_valid]
    order = np.argsort(source_t, kind="stable")
    source_t = source_t[order]
    source_speed = source_speed[order]
    unique_t, unique_idx = np.unique(source_t, return_index=True)
    source_t = unique_t
    source_speed = source_speed[unique_idx]

    target_t = pd.to_numeric(df["time_s"], errors="coerce").to_numpy(dtype=float)
    target_valid = np.isfinite(target_t)
    speed_on_primary = np.full(len(df.index), np.nan, dtype=float)
    in_range = target_valid & (target_t >= source_t[0]) & (target_t <= source_t[-1])
    if np.any(in_range):
        speed_on_primary[in_range] = np.interp(target_t[in_range], source_t, source_speed)
        nearest = _nearest_sample_distance_s(source_t, target_t[in_range])
        too_far = nearest > max_gap_s
        if np.any(too_far):
            in_range_positions = np.flatnonzero(in_range)
            speed_on_primary[in_range_positions[too_far]] = np.nan

    finite_speed = np.isfinite(speed_on_primary)
    active = finite_speed & (np.abs(speed_on_primary) > speed_threshold)
    mask = _soften_active_mask_from_time_s(
        df,
        active,
        window=window,
        padding=padding,
        min_segment=min_segment,
    )
    meta.update(
        {
            "status": "evaluated",
            "speed_col": speed_col,
            "valid_rows": int(np.count_nonzero(finite_speed)),
            "active_rows": int(mask.sum()),
        }
    )
    return mask, meta


def _build_motion_activity_candidate(
    session: Mapping[str, Any],
    df: pd.DataFrame,
    candidate: Mapping[str, Any],
    *,
    candidate_id: str,
    disp_thresh: float,
    vel_thresh: float,
    window: str,
    padding: str,
    min_segment: str,
) -> tuple[Optional[pd.Series], dict[str, Any]]:
    disp_col, vel_col, disp_selector, vel_selector = _resolve_activity_motion_columns(
        session,
        candidate,
        purpose_prefix=f"activity candidate {candidate_id}",
    )
    candidate_disp_thresh = float(candidate.get("disp_thresh", disp_thresh))
    candidate_vel_thresh = float(candidate.get("vel_thresh", vel_thresh))
    meta: dict[str, Any] = {
        "id": candidate_id,
        "type": _activity_candidate_type(candidate),
        "disp_col": disp_col,
        "vel_col": vel_col,
        "disp_selector": dict(disp_selector) if isinstance(disp_selector, Mapping) else None,
        "vel_selector": dict(vel_selector) if isinstance(vel_selector, Mapping) else None,
        "disp_thresh": float(candidate_disp_thresh),
        "vel_thresh": float(candidate_vel_thresh),
    }
    if disp_col not in df.columns or vel_col not in df.columns:
        meta.update({"status": "missing", "reason": "motion_columns_missing"})
        return None, meta

    disp = pd.to_numeric(df[disp_col], errors="coerce").to_numpy(dtype=float)
    vel = pd.to_numeric(df[vel_col], errors="coerce").to_numpy(dtype=float)
    finite = np.isfinite(disp) & np.isfinite(vel)
    active = finite & (np.abs(disp) > candidate_disp_thresh) & (np.abs(vel) > candidate_vel_thresh)
    mask = _soften_active_mask_from_time_s(
        df,
        active,
        window=window,
        padding=padding,
        min_segment=min_segment,
    )
    meta.update(
        {
            "status": "evaluated",
            "valid_rows": int(np.count_nonzero(finite)),
            "active_rows": int(mask.sum()),
        }
    )
    return mask, meta


def _build_activity_mask_from_policy(
    session: Mapping[str, Any],
    df: pd.DataFrame,
    activity_detection: Mapping[str, Any],
    *,
    legacy_disp_col: Optional[str],
    legacy_vel_col: Optional[str],
    legacy_disp_selector: Optional[Mapping[str, Any]],
    legacy_vel_selector: Optional[Mapping[str, Any]],
    disp_thresh: float,
    vel_thresh: float,
    window: str,
    padding: str,
    min_segment: str,
) -> tuple[pd.Series, dict[str, Any]]:
    candidate_meta: list[dict[str, Any]] = []
    candidate_masks: list[pd.Series] = []
    candidates = _activity_detection_candidates(activity_detection)
    for index, candidate in enumerate(candidates):
        candidate_id = _activity_candidate_id(candidate, index)
        candidate_type = _activity_candidate_type(candidate)
        if candidate_type == "gps_speed":
            mask, meta = _build_gps_speed_activity_candidate(
                session,
                df,
                candidate,
                candidate_id=candidate_id,
                window=window,
                padding=padding,
                min_segment=min_segment,
            )
        elif candidate_type in {"motion_pair", "wheel_motion"}:
            mask, meta = _build_motion_activity_candidate(
                session,
                df,
                candidate,
                candidate_id=candidate_id,
                disp_thresh=disp_thresh,
                vel_thresh=vel_thresh,
                window=window,
                padding=padding,
                min_segment=min_segment,
            )
        elif candidate_type == "legacy_motion":
            legacy_candidate = dict(candidate)
            if legacy_disp_selector is not None:
                legacy_candidate.setdefault("disp_selector", legacy_disp_selector)
            if legacy_vel_selector is not None:
                legacy_candidate.setdefault("vel_selector", legacy_vel_selector)
            if legacy_disp_col is not None:
                legacy_candidate.setdefault("disp_col", legacy_disp_col)
            if legacy_vel_col is not None:
                legacy_candidate.setdefault("vel_col", legacy_vel_col)
            mask, meta = _build_motion_activity_candidate(
                session,
                df,
                legacy_candidate,
                candidate_id=candidate_id,
                disp_thresh=disp_thresh,
                vel_thresh=vel_thresh,
                window=window,
                padding=padding,
                min_segment=min_segment,
            )
        else:
            mask = None
            meta = {"id": candidate_id, "type": candidate_type, "status": "skipped", "reason": "unsupported_type"}

        candidate_meta.append(meta)
        if mask is not None and meta.get("status") == "evaluated":
            candidate_masks.append(mask.astype(bool))

    if candidate_masks:
        combined = candidate_masks[0].copy()
        for mask in candidate_masks[1:]:
            combined |= mask.astype(bool)
        combined.name = ACTIVE_MASK_COL
        source = "activity_detection"
    elif bool(activity_detection.get("fallback_to_legacy", True)):
        combined = _build_active_mask_from_time_s(
            df,
            disp_col=legacy_disp_col,
            vel_col=legacy_vel_col,
            disp_thresh=disp_thresh,
            vel_thresh=vel_thresh,
            window=window,
            padding=padding,
            min_segment=min_segment,
        )
        source = "legacy_fallback"
    else:
        combined = pd.Series(True, index=df.index, name=ACTIVE_MASK_COL)
        source = "no_evaluable_candidates_soft_pass"

    qc = {
        "policy": "activity_detection_v1",
        "source": source,
        "enabled": True,
        "combination": str(activity_detection.get("combination") or "any"),
        "fallback_to_legacy": bool(activity_detection.get("fallback_to_legacy", True)),
        "candidates": candidate_meta,
        "evaluated_candidate_ids": [
            str(item.get("id"))
            for item in candidate_meta
            if item.get("status") == "evaluated"
        ],
        "active_rows": int(combined.sum()),
        "inactive_rows": int(len(combined.index) - int(combined.sum())),
    }
    return combined, qc


def _validated_preprocess_config_copy(config: Mapping[str, Any]) -> Dict[str, Any]:
    validate_preprocess_config(config)
    return dict(config)


def _coerce_preprocess_config(
    *,
    preprocess_profile_path: Optional[str | Path],
    preprocess_profile: Optional[Mapping[str, Any]],
    preprocess_config: Optional[Mapping[str, Any]],
) -> Optional[Dict[str, Any]]:
    provided = [
        preprocess_profile_path is not None,
        preprocess_profile is not None,
        preprocess_config is not None,
    ]
    if sum(provided) > 1:
        raise ValueError(
            "Use only one of preprocess_profile_path, preprocess_profile, or preprocess_config"
        )
    if preprocess_profile_path is not None:
        return load_preprocess_config(preprocess_profile_path)
    if preprocess_profile is not None:
        return preprocess_config_from_profile(preprocess_profile)
    if preprocess_config is not None:
        return _validated_preprocess_config_copy(preprocess_config)
    return None


def _preprocess_loaded_session(session: Dict[str, Any],
                               *,
                               preprocess_config: Optional[Mapping[str, Any]] = None,
                               gps_source_policy: Optional[Mapping[str, Any]] = None,
                               normalize_ranges: Optional[Dict[str, float]] = None,
                               bike_profile: Optional[Mapping[str, Any]] = None,
                               bike_profile_path: Optional[str | Path] = None,
                               sample_rate_hz: Optional[float] = None,
                               zeroing_enabled: bool = True,
                               zero_window_s: float = 1.0,
                               zero_min_samples: int = 10,
                               clip_0_1: bool = False,
                               active_signal_disp_col: Optional[str] = None,
                               active_signal_vel_col: Optional[str] = None,
                               active_signal_disp_selector: Optional[Mapping[str, Any]] = None,
                               active_signal_vel_selector: Optional[Mapping[str, Any]] = None,
                               active_disp_thresh: float = 20,
                               active_vel_thresh: float = 50,
                               active_window: str = "500ms",
                               active_padding: str = "1s",
                               active_min_seg: str = "3s",
                               prefer_postprocessing_transformations: bool = False,
                               ignore_on_logger_transformations: Optional[bool] = None,
                               butterworth_smoothing: Optional[Sequence[Dict[str, Any]]] = None,
                               butterworth_generate_residuals: bool = False,
                               motion_derivation: Optional[Mapping[str, Any]] = None,
                               activity_detection: Optional[Mapping[str, Any]] = None,
                               va_cols: Optional[Sequence[str]] = None,
                               va_window_points: int = 11,
                               va_poly_order: int = 3,
                               strict: bool = True) -> Dict[str, Any]:
    
    """Apply preprocessing to an already-loaded session."""
    if preprocess_config is not None:
        cfg = _validated_preprocess_config_copy(preprocess_config)
        sample_rate_hz = sample_rate_hz if sample_rate_hz is not None else cfg.get("sample_rate_hz")
        zeroing_enabled = bool(cfg.get("zeroing_enabled", zeroing_enabled))
        zero_window_s = float(cfg.get("zero_window_s", zero_window_s))
        zero_min_samples = int(cfg.get("zero_min_samples", zero_min_samples))
        clip_0_1 = bool(cfg.get("clip_0_1", clip_0_1))
        active_signal_disp_selector = cfg.get("active_signal_disp_selector", active_signal_disp_selector)
        active_signal_vel_selector = cfg.get("active_signal_vel_selector", active_signal_vel_selector)
        active_disp_thresh = float(cfg.get("active_disp_thresh", active_disp_thresh))
        active_vel_thresh = float(cfg.get("active_vel_thresh", active_vel_thresh))
        active_window = str(cfg.get("active_window", active_window))
        active_padding = str(cfg.get("active_padding", active_padding))
        active_min_seg = str(cfg.get("active_min_seg", active_min_seg))
        if "prefer_postprocessing_transformations" in cfg:
            prefer_postprocessing_transformations = bool(cfg.get("prefer_postprocessing_transformations"))
        elif "ignore_on_logger_transformations" in cfg:
            prefer_postprocessing_transformations = bool(cfg.get("ignore_on_logger_transformations"))
        motion_derivation = cfg.get("motion_derivation", motion_derivation)
        activity_detection = cfg.get("activity_detection", activity_detection)
        gps_source_policy = cfg.get("gps_source_policy", gps_source_policy)
        butterworth_smoothing = cfg.get("butterworth_smoothing", butterworth_smoothing)
        butterworth_generate_residuals = bool(
            cfg.get("butterworth_generate_residuals", butterworth_generate_residuals)
        )
        strict = bool(cfg.get("strict", strict))

    if ignore_on_logger_transformations is not None:
        prefer_postprocessing_transformations = bool(ignore_on_logger_transformations)

    df = session["df"].copy()

    # QC: ensure structure exists early
    qc = session.setdefault("qc", {})
    transforms = qc.setdefault("transforms", {})
    logger.info(
        "Post-processing transformation policy: prefer_postprocessing_transformations=%s",
        bool(prefer_postprocessing_transformations),
    )

    # ---------------- Signals: canonicalize names early (no dependency on normalize_ranges) ----------------
    units_by_col: Dict[str, str] = {}
    for c in df.columns:
        m = _UNIT_RE.search(str(c))
        if m:
            u = (m.group(1) or "").strip()
            if u:
                units_by_col[str(c)] = u

    domain_by_base = {"front_shock": "suspension", "rear_shock": "suspension"}

    session["df"] = df
    session = canonicalize_signal_names(
        session,
        units_by_base=units_by_col,
        domain_by_base=domain_by_base,
    )
    session = build_signals_registry(session, strict=False)
    session = build_logger_gps_route_stream(session, gps_source_policy=gps_source_policy)
    session = refresh_gps_source_metadata(session, gps_source_policy=gps_source_policy)
    logger_calibration_meta = _materialize_logger_linear_calibrations(session)
    transforms["logger_calibration"] = logger_calibration_meta
    if logger_calibration_meta.get("applied"):
        session = build_signals_registry(session, strict=False)
    df = session["df"]

    if bike_profile is None and bike_profile_path is not None:
        bike_profile = load_bike_profile(bike_profile_path)

    if normalize_ranges is None and bike_profile is None:
        raise ValueError("preprocessing requires either normalize_ranges or bike_profile_path")

    # ---------------- Zero physical signal columns before bike-profile transforms ----------------
    if normalize_ranges is None:
        zero_ranges = resolve_normalization_ranges(
            session,
            bike_profile,
            bike_profile_path=bike_profile_path,
            require_at_least_one=False,
            record=False,
            warn_unmatched=False,
        )
    else:
        zero_ranges = dict(normalize_ranges)

    df2, zero_meta = zero_signal_columns(
        df,
        zero_ranges,
        zeroing_enabled=zeroing_enabled,
        zero_window_s=zero_window_s,
        min_samples_abs_min=zero_min_samples,
        return_meta=True,
    )
    zero_per_column = zero_meta.get("per_column", [])
    zeroed_columns_for_norm = {
        str(r.get("column"))
        for r in zero_per_column
        if r.get("status") == "ok" and (r.get("zeroing") or {}).get("enabled", False)
    }
    session["df"] = df2

    if bike_profile is not None:
        session = apply_signal_transforms(
            session,
            bike_profile,
            bike_profile_path=bike_profile_path,
            output_conflict_policy="prefer_analysis" if prefer_postprocessing_transformations else "prefer_existing",
        )
        generated_transform_records = [
            r
            for r in (
                (session.get("qc") or {})
                .get("transforms", {})
                .get("bike_profile_signal_transforms", {})
                .get("generated", [])
            )
            if isinstance(r, Mapping)
        ]
        generated_zeroed_transform_columns = {
            str(r.get("output_column"))
            for r in generated_transform_records
            if r.get("output_column") is not None
            and str(r.get("input_column")) in zeroed_columns_for_norm
        }
        if zeroing_enabled:
            zeroed_columns_for_norm.update(generated_zeroed_transform_columns)
        session = build_signals_registry(session, strict=False)
        df2 = session["df"]

    if normalize_ranges is None:
        normalize_ranges = resolve_normalization_ranges(
            session,
            bike_profile,
            bike_profile_path=bike_profile_path,
        )
    else:
        normalize_ranges = dict(normalize_ranges)
    normalize_ranges_for_scale = dict(normalize_ranges)

    meta = session.setdefault("meta", {})
    sample_rate_hint_hz = sample_rate_hz
    if sample_rate_hint_hz is None:
        sample_rate_hint_hz = meta.get("sample_rate_hz")

    # ---------------- Resolve canonical preprocessing sample-rate ----------------
    # Use the same source for all preprocessing transforms (explicit sample_rate_hz
    # if provided, else inferred from canonical time_s).
    tb = estimate_uniform_timebase(
        df2,
        time_col="time_s",
        sample_rate_hz=sample_rate_hint_hz,
    )
    preprocess_sample_rate_hz = float(tb.sample_rate_hz)

    # ---------------- Motion analysis channels ----------------
    motion_meta: Dict[str, Any] = {
        "enabled": bool((motion_derivation or {}).get("enabled", False))
        if isinstance(motion_derivation, Mapping)
        else False,
        "generated": [],
        "skipped": [],
        "warnings": [],
        "sample_rate_hz": preprocess_sample_rate_hz,
        "generated_channel_info": {},
    }
    if motion_meta["enabled"]:
        df2, motion_meta = derive_motion_channels(
            session,
            motion_derivation,
            sample_rate_hz=preprocess_sample_rate_hz,
            strict=bool(strict),
            overwrite_existing_primary=bool(prefer_postprocessing_transformations),
        )
        session["df"] = df2
        _merge_channel_info(
            session,
            motion_meta.get("generated_channel_info", {})
            if isinstance(motion_meta.get("generated_channel_info"), Mapping)
            else {},
        )
        for warning in motion_meta.get("warnings", []):
            _append_qc_warning(session, str(warning))

        zeroed_columns_for_norm.update(_motion_zeroed_columns(motion_meta, zeroed_columns_for_norm))
        normalize_ranges_for_scale.update(_motion_normalization_ranges(motion_meta, normalize_ranges))
        session = build_signals_registry(session, strict=False)
        df2 = session["df"]

    if active_signal_disp_col is None and active_signal_disp_selector is not None:
        active_signal_disp_col = resolve_signal_selector(
            session,
            active_signal_disp_selector,
            purpose="activity displacement",
        )

    # ---------------- Scale after transformations ----------------
    df2, scale_meta = scale_signal_columns(
        df2,
        normalize_ranges_for_scale,
        clip_0_1=clip_0_1,
        zeroed_columns=sorted(zeroed_columns_for_norm),
        return_meta=True,
    )
    per_column = scale_meta.get("per_column", [])
    session["df"] = df2
    scaled_channel_info = _channel_info_for_scaled_outputs(session, scale_meta)
    if scaled_channel_info:
        _merge_channel_info(session, scaled_channel_info)

    # Update QC transforms from report
    # (report entries may be missing/empty depending on input columns)
    by_channel = {}
    methods = set()
    
    for r in zero_per_column:
        if r.get("status") != "ok":
            continue
        z = r.get("zeroing") or {}
        if not z.get("enabled", False):
            continue
    
        col = r["column"]
        m = z.get("method")
        if m:
            methods.add(m)
    
        if "offset" in z and z["offset"] is not None:
            by_channel[col] = {"offset": float(z["offset"]), "method": m}
        elif "segment_offsets" in z and z["segment_offsets"]:
            by_channel[col] = {"segment_offsets": z["segment_offsets"], "method": m}
    
    transforms["zeroed"] = {
        "applied": bool(zeroing_enabled),
        "method": (next(iter(methods)) if len(methods) == 1 else ("mixed" if methods else None)),
        "window_s": float(zero_window_s),
        "by_channel": by_channel or None,
    }

    transforms["scaled"] = {
        "applied": True,
        "by_channel": {
            r["column"]: {"full_range": float(r.get("full_range"))}
            for r in per_column
            if r.get("status") == "ok" and r.get("full_range") is not None
        } or None,
    }

    transforms["motion_derivation"] = {
        "applied": bool(motion_meta.get("generated")),
        "enabled": bool(motion_meta.get("enabled", False)),
        "method": "butterworth_savgol_butterworth" if motion_meta.get("enabled") else None,
        "sample_rate_hz": float(preprocess_sample_rate_hz),
        "generated_columns": [
            str(g.get("output_col"))
            for g in motion_meta.get("generated", [])
            if isinstance(g, Mapping) and g.get("output_col") is not None
        ],
        "n_generated": int(len(motion_meta.get("generated", []))),
        "n_skipped": int(len(motion_meta.get("skipped", []))),
        "warnings": [str(w) for w in motion_meta.get("warnings", [])],
    }
    transforms["logger_transform_policy"] = {
        "prefer_postprocessing_transformations": bool(prefer_postprocessing_transformations),
    }

    # ---------------- Optional offline Butterworth smoothing ----------------
    bw_configs = normalize_butterworth_smoothing_configs(butterworth_smoothing)
    bw_meta: Dict[str, Any] = {
        "configs": [],
        "eligible_columns": [],
        "generated": [],
        "generated_residuals": [],
        "skipped": [],
        "warnings": [],
        "sample_rate_hz": preprocess_sample_rate_hz,
        "generate_residuals": bool(butterworth_generate_residuals),
    }
    if bw_configs:
        df2, bw_meta = apply_butterworth_smoothing(
            df2,
            sample_rate_hz=preprocess_sample_rate_hz,
            configs=bw_configs,
            generate_residuals=bool(butterworth_generate_residuals),
        )
        session["df"] = df2
        qc_warnings = qc.setdefault("warnings", [])
        qc_warnings.extend([str(w) for w in bw_meta.get("warnings", [])])

    if bw_configs:
        transforms["filtered"] = {
            "applied": bool(bw_meta.get("generated")),
            "method": "butterworth_zero_phase_sosfiltfilt",
            "params": {
                "sample_rate_hz": float(preprocess_sample_rate_hz),
                "configs": bw_meta.get("configs", []),
                "eligible_columns": bw_meta.get("eligible_columns", []),
                "generated_columns": [g["output_col"] for g in bw_meta.get("generated", [])],
                "generated_residual_columns": [
                    g["output_col"] for g in bw_meta.get("generated_residuals", [])
                ],
                "n_generated": int(len(bw_meta.get("generated", []))),
                "n_generated_residuals": int(len(bw_meta.get("generated_residuals", []))),
                "n_skipped": int(len(bw_meta.get("skipped", []))),
                "generate_residuals": bool(bw_meta.get("generate_residuals", False)),
            },
        }
    else:
        transforms.setdefault(
            "filtered",
            {"applied": False, "method": None, "params": None},
        )

    # ---------------- Velocity/acceleration ----------------
    if va_cols is None:
        va_cols = [
            col
            for col in normalize_ranges.keys()
            if _is_legacy_va_displacement_column(col)
        ]

    motion_va_suppressed_cols = _motion_legacy_va_suppressed_columns(motion_meta)
    if motion_va_suppressed_cols:
        va_cols = [col for col in va_cols if str(col) not in motion_va_suppressed_cols]

    # Ensure VA is computed for the activity-mask displacement signal if provided
    if (
        active_signal_disp_col
        and active_signal_disp_col not in motion_va_suppressed_cols
        and active_signal_disp_col not in set(va_cols)
    ):
        va_cols = list(va_cols) + [active_signal_disp_col]
    for activity_disp_col in _activity_motion_displacement_cols_for_va(session, activity_detection):
        if activity_disp_col not in motion_va_suppressed_cols and activity_disp_col not in set(va_cols):
            va_cols = list(va_cols) + [activity_disp_col]

    df3, va_meta = estimate_va(
        df2,
        cols=list(va_cols),
        sample_rate_hz=preprocess_sample_rate_hz,
        window_points=va_window_points,
        poly_order=va_poly_order,
        return_meta=True,            # <-- opt-in diagnostics
    )
    session["df"] = df3
    session = build_signals_registry(session, strict=False)

    # ---------------- Activity mask (QC; non-destructive) ----------------
    # Derive companion columns from ACTIVE_SIGNAL_BASE
    # Assumes your VA naming convention appends "_vel" to the signal column name.
    # Adjust vel_col derivation if your VA uses a different convention.

    if active_signal_vel_col is None and active_signal_vel_selector is not None:
        active_signal_vel_col = resolve_signal_selector(
            session,
            active_signal_vel_selector,
            purpose="activity velocity",
        )

    # If user specified only displacement for activity mask, derive the velocity name
    if active_signal_disp_col and not active_signal_vel_col:
        active_signal_vel_col = name_vel(active_signal_disp_col)

    activity_policy_qc: Dict[str, Any]
    if _activity_detection_enabled(activity_detection):
        active_mask, activity_policy_qc = _build_activity_mask_from_policy(
            session,
            session["df"],
            activity_detection,
            legacy_disp_col=active_signal_disp_col,
            legacy_vel_col=active_signal_vel_col,
            legacy_disp_selector=active_signal_disp_selector,
            legacy_vel_selector=active_signal_vel_selector,
            disp_thresh=active_disp_thresh,
            vel_thresh=active_vel_thresh,
            window=active_window,
            padding=active_padding,
            min_segment=active_min_seg,
        )
    else:
        active_mask = _build_active_mask_from_time_s(
            session["df"],
            disp_col=active_signal_disp_col,
            vel_col=active_signal_vel_col,
            disp_thresh=active_disp_thresh,
            vel_thresh=active_vel_thresh,
            window=active_window,
            padding=active_padding,
            min_segment=active_min_seg,
        )
        activity_policy_qc = {
            "policy": "legacy_single_pair_v0",
            "enabled": False,
            "source": "legacy",
            "active_rows": int(active_mask.sum()),
            "inactive_rows": int(len(active_mask.index) - int(active_mask.sum())),
        }

    # Store as QC column (won't be in registry signals)
    session["df"][ACTIVE_MASK_COL] = active_mask

    # Record provenance in qc/meta
    qc = session.setdefault("qc", {})
    qc.setdefault("activity_mask", {})
    qc["activity_mask"] = {
        "applied": True,
        "mask_col": ACTIVE_MASK_COL,
        "disp_col": active_signal_disp_col,
        "vel_col": active_signal_vel_col,
        "disp_selector": dict(active_signal_disp_selector) if isinstance(active_signal_disp_selector, Mapping) else None,
        "vel_selector": dict(active_signal_vel_selector) if isinstance(active_signal_vel_selector, Mapping) else None,
        "disp_thresh": float(active_disp_thresh),
        "vel_thresh": float(active_vel_thresh),
        "window": str(active_window),
        "padding": str(active_padding),
        "min_segment": str(active_min_seg),
        "logic": "disp&vel",
        "version": "v0",
    }
    qc["activity_mask"].update(activity_policy_qc)

    transforms["va"] = {
        "applied": True,
        "by_channel": list(va_meta.get("cols", [])) if va_meta else list(va_cols),
        "dt": float(va_meta["dt"]) if va_meta and va_meta.get("dt") is not None else None,
        "window_points": int(va_window_points),
        "poly_order": int(va_poly_order),
    }

    # ---------------- Meta ----------------
    if sample_rate_hint_hz is not None:
        meta["sample_rate_hz"] = float(sample_rate_hint_hz)

    # ---------------- Timebase / streams meta (v0) ----------------
    # For now, your analysis df is a single "primary" stream.
    # Later, you'll add additional streams (imu, etc.) and register each.
    register_stream_timebase(
        session,
        stream_name="primary",
        df_stream=session["df"],   # df3 (post normalize + VA) is now in session["df"]
        time_col="time_s",
        sample_rate_hz=meta.get("sample_rate_hz"),  # may be None; estimator will infer from time_s
        jitter_tol_frac=0.05,
    )
    validate_session(session)

    # ---------------- Signals: rebuild registry + validate (final df) ----------------
    session = rebuild_and_validate_signal_registry(
        session,
        strict_registry_parse=True,
    )
    session = refresh_gps_source_metadata(session, gps_source_policy=gps_source_policy)
    return session

     
def preprocess_resolved(
    session: Mapping[str, Any],
    *,
    schema: Optional[Mapping[str, Any] | str | bytes | Path] = None,
    preprocess_profile: Optional[Mapping[str, Any]] = None,
    preprocess_config: Optional[Mapping[str, Any]] = None,
    fit_import: Optional[Mapping[str, Any]] = None,
    fit_stream: Optional[Mapping[str, Any]] = None,
    fit_candidates: Optional[Sequence[Mapping[str, Any]]] = None,
    fit_bindings: Optional[Sequence[Mapping[str, Any]] | Mapping[str, Any] | str | bytes | Path] = None,
    gps_source_policy: Optional[Mapping[str, Any]] = None,
    zeroing_enabled: bool = True,
    zero_window_s: float = 1,
    zero_min_samples: int = 10,
    clip_0_1: bool = False,
    active_signal_disp_col: Optional[str] = None,
    active_signal_vel_col: Optional[str] = None,
    active_disp_thresh: float = 20,
    active_vel_thresh: float = 50,
    active_window: str = "500ms",
    active_padding: str = "1s",
    active_min_seg: str = "3s",
    normalize_ranges: Optional[Dict[str, float]] = None,
    bike_profile: Optional[Mapping[str, Any] | str | bytes | Path] = None,
    bike_profile_path: Optional[str | Path] = None,
    active_signal_disp_selector: Optional[Mapping[str, Any]] = None,
    active_signal_vel_selector: Optional[Mapping[str, Any]] = None,
    sample_rate_hz: Optional[float] = None,
    prefer_postprocessing_transformations: bool = False,
    ignore_on_logger_transformations: Optional[bool] = None,
    butterworth_smoothing: Optional[Sequence[Dict[str, Any]]] = None,
    butterworth_generate_residuals: bool = False,
    motion_derivation: Optional[Mapping[str, Any]] = None,
    activity_detection: Optional[Mapping[str, Any]] = None,
    include_events: bool = True,
    include_metrics: bool = True,
    strict: bool = True,
) -> Dict[str, Any]:
    """
    Run preprocessing from already-resolved session/schema/profile content rather
    than discovering local files.
    """
    if not isinstance(session, Mapping):
        raise ValueError("preprocess_resolved expects an existing session mapping")

    cfg = _coerce_preprocess_config(
        preprocess_profile_path=None,
        preprocess_profile=preprocess_profile,
        preprocess_config=preprocess_config,
    )
    if cfg is not None:
        fit_import = fit_import if fit_import is not None else cfg.get("fit_import")
        gps_source_policy = gps_source_policy if gps_source_policy is not None else cfg.get("gps_source_policy")
        sample_rate_hz = sample_rate_hz if sample_rate_hz is not None else cfg.get("sample_rate_hz")
        zeroing_enabled = bool(cfg.get("zeroing_enabled", zeroing_enabled))
        zero_window_s = float(cfg.get("zero_window_s", zero_window_s))
        zero_min_samples = int(cfg.get("zero_min_samples", zero_min_samples))
        clip_0_1 = bool(cfg.get("clip_0_1", clip_0_1))
        active_signal_disp_selector = cfg.get("active_signal_disp_selector", active_signal_disp_selector)
        active_signal_vel_selector = cfg.get("active_signal_vel_selector", active_signal_vel_selector)
        active_disp_thresh = float(cfg.get("active_disp_thresh", active_disp_thresh))
        active_vel_thresh = float(cfg.get("active_vel_thresh", active_vel_thresh))
        active_window = str(cfg.get("active_window", active_window))
        active_padding = str(cfg.get("active_padding", active_padding))
        active_min_seg = str(cfg.get("active_min_seg", active_min_seg))
        if "prefer_postprocessing_transformations" in cfg:
            prefer_postprocessing_transformations = bool(cfg.get("prefer_postprocessing_transformations"))
        elif "ignore_on_logger_transformations" in cfg:
            prefer_postprocessing_transformations = bool(cfg.get("ignore_on_logger_transformations"))
        motion_derivation = cfg.get("motion_derivation", motion_derivation)
        activity_detection = cfg.get("activity_detection", activity_detection)
        butterworth_smoothing = cfg.get("butterworth_smoothing", butterworth_smoothing)
        butterworth_generate_residuals = bool(
            cfg.get("butterworth_generate_residuals", butterworth_generate_residuals)
        )
        strict = bool(cfg.get("strict", strict))

    resolved_schema: Optional[Dict[str, Any]] = None
    if schema is not None and not (isinstance(schema, str) and not schema.strip()):
        resolved_schema = parse_event_schema(schema)
    elif include_events and isinstance(cfg, Mapping) and cfg.get("schema_path"):
        raise ValueError(
            "preprocess_resolved does not resolve schema_path from preprocess_config; "
            "pass a loaded schema object/text/bytes explicitly"
        )

    resolved_bike_profile: Optional[Dict[str, Any]] = None
    if bike_profile is not None:
        resolved_bike_profile = parse_bike_profile(bike_profile)

    session_obj = dict(session)
    source = session_obj.get("source") if isinstance(session_obj.get("source"), dict) else {}
    csv_path = source.get("path") if isinstance(source, dict) else None
    logger.info("Using resolved session for preprocessing")

    session_obj = enrich_session_with_fit(
        session_obj,
        fit_import=fit_import,
        fit_stream=fit_stream,
        fit_candidates=fit_candidates,
        fit_bindings=fit_bindings,
    )
    if bool((fit_import or {}).get("enabled")):
        logger.info("FIT enrichment step complete")

    session_obj = _preprocess_loaded_session(
        session_obj,
        preprocess_config=cfg,
        gps_source_policy=gps_source_policy,
        normalize_ranges=normalize_ranges,
        sample_rate_hz=sample_rate_hz,
        zeroing_enabled=zeroing_enabled,
        zero_window_s=zero_window_s,
        zero_min_samples=zero_min_samples,
        clip_0_1=clip_0_1,
        active_signal_disp_col=active_signal_disp_col,
        active_signal_vel_col=active_signal_vel_col,
        active_signal_disp_selector=active_signal_disp_selector,
        active_signal_vel_selector=active_signal_vel_selector,
        active_disp_thresh=active_disp_thresh,
        active_vel_thresh=active_vel_thresh,
        active_window=active_window,
        active_padding=active_padding,
        active_min_seg=active_min_seg,
        prefer_postprocessing_transformations=prefer_postprocessing_transformations,
        ignore_on_logger_transformations=ignore_on_logger_transformations,
        bike_profile=resolved_bike_profile,
        bike_profile_path=bike_profile_path,
        motion_derivation=motion_derivation,
        activity_detection=activity_detection,
        butterworth_smoothing=butterworth_smoothing,
        butterworth_generate_residuals=butterworth_generate_residuals,
        strict=strict,
    )
    logger.info("Session pre-process complete")

    t = session_obj["df"]["time_s"].to_numpy()
    logger.debug("time_s start/end: %s .. %s", t[0], t[-1])
    logger.debug(
        "dt median/min/max: %s / %s / %s",
        float(np.median(np.diff(t))),
        float(np.min(np.diff(t))),
        float(np.max(np.diff(t))),
    )

    sig = session_obj.get("meta", {}).get("signals", {})
    logger.debug("signals entries: %d", len(sig))
    for col, info in list(sig.items())[:10]:
        logger.debug("%s -> %s", col, info)

    kinds = {}
    units = {}
    for info in sig.values():
        if isinstance(info, dict):
            kinds[info.get("kind")] = kinds.get(info.get("kind"), 0) + 1
            units[info.get("unit")] = units.get(info.get("unit"), 0) + 1
    logger.debug("kind counts: %s", kinds)
    logger.debug("unit counts: %s", units)

    assert "df" in session_obj
    assert "time_s" in session_obj["df"].columns
    assert "signals" in session_obj.get("meta", {})

    meta = session_obj.setdefault("meta", {})
    if not isinstance(meta, dict):
        raise ValueError("session['meta'] must be a dict")

    if csv_path is not None:
        sid = os.path.splitext(os.path.basename(str(csv_path)))[0]
    else:
        sid = str(session_obj.get("session_id") or meta.get("session_id") or "session")
    session_obj["session_id"] = sid
    meta["session_id"] = sid

    if resolved_schema is not None:
        logger.info("Schema load complete")

    events_df = pd.DataFrame()
    if resolved_schema is not None and include_events:
        events_df = detect_events_from_schema(
            session_obj["df"],
            resolved_schema,
            meta=session_obj["meta"],
        )

        logger.info("Event detection complete")
        logger.info("events rows: %d", len(events_df))

        if isinstance(events_df, pd.DataFrame):
            if "event_name" in events_df.columns:
                logger.debug(
                    "event_name unique: %s",
                    sorted(events_df["event_name"].dropna().unique().tolist()),
                )
            else:
                logger.debug("events_df has no 'event_name' column; columns=%s", list(events_df.columns))

            if "schema_id" in events_df.columns:
                logger.debug(
                    "schema_id unique: %s",
                    sorted(events_df["schema_id"].dropna().astype(str).unique().tolist()),
                )
            else:
                logger.debug("events_df has no 'schema_id' column; columns=%s", list(events_df.columns))

    detected_sids = sorted(events_df["schema_id"].dropna().astype(str).unique().tolist()) if (
        isinstance(events_df, pd.DataFrame) and ("schema_id" in events_df.columns)
    ) else []

    defined_sids = sorted(
        [
            str(e.get("id"))
            for e in ((resolved_schema or {}).get("events") or [])
            if isinstance(e, dict) and e.get("id")
        ]
    )
    missing = [sid for sid in defined_sids if sid not in set(detected_sids)]
    if missing:
        logger.info("Schema events with zero detections this run: %s", missing)

    if resolved_schema is not None and include_metrics:
        logger.info("Running segment extraction for detected schema events: %s", detected_sids)

    bundles_by_schema_id: dict[str, dict] = {}
    metrics_parts: list[pd.DataFrame] = []

    for sid in (detected_sids if resolved_schema is not None and include_metrics else []):
        events_sel = events_df[events_df["schema_id"].astype(str) == str(sid)]
        if events_sel.empty:
            logger.info("No events for schema_id=%s; skipping.", sid)
            continue

        bundle = extract_segments(
            df=session_obj["df"],
            events=events_df,
            meta=session_obj["meta"],
            schema=resolved_schema,
            request=SegmentRequest(schema_id=sid),
        )
        bundles_by_schema_id[sid] = bundle
        logger.info("Segment extraction complete (schema_id=%s)", sid)

        seg = bundle["segments"]
        valid_n = int(seg["valid"].sum()) if "valid" in seg.columns else 0
        total_n = len(seg)
        logger.info("segments valid (schema_id=%s): %d/%d", sid, valid_n, total_n)

        t2 = bundle["data"].get("t_rel_s")
        logger.debug("t_rel_s type=%s shape=%s", type(t2), getattr(t2, "shape", None))
        if isinstance(t2, np.ndarray):
            logger.debug("t_rel_s[0][:10]=%s", t2[0][:10])
            logger.debug("t_rel_s[0][-10:]=%s", t2[0][-10:])
            d = np.diff(t2[0].astype(float))
            logger.debug("diff stats: min=%s med=%s max=%s", np.nanmin(d), np.nanmedian(d), np.nanmax(d))
            logger.debug("nonpositive diffs=%d", int(np.sum(d <= 0)))

        metrics_i = compute_metrics_from_segments(bundle, schema=resolved_schema, strict=strict)
        logger.info("Metrics calculation complete (schema_id=%s)", sid)

        if "schema_id" not in metrics_i.columns:
            metrics_i = metrics_i.copy()
            metrics_i["schema_id"] = sid

        metrics_parts.append(metrics_i)

    metrics_df = pd.concat(metrics_parts, ignore_index=True) if metrics_parts else pd.DataFrame()

    if resolved_schema is not None and include_metrics:
        validate_metrics_df(metrics_df, events_df=events_df)
        logger.info("Metrics validation complete")

    return {
        "session": session_obj,
        "schema": resolved_schema,
        "events": events_df,
        "segments": bundles_by_schema_id,
        "metrics": metrics_df,
    }


def preprocess_session(
    session_or_path: str | Path | Mapping[str, Any],
    schema_path: Optional[str | Path] = None,
    *,
    preprocess_profile_path: Optional[str | Path] = None,
    preprocess_profile: Optional[Mapping[str, Any]] = None,
    preprocess_config: Optional[Mapping[str, Any]] = None,
    sidecar_path: Optional[str] = None,
    generic_sidecar_paths: Optional[Sequence[str | Path]] = None,
    log_metadata_path: Optional[str | Path] = None,
    generic_log_metadata_paths: Optional[Sequence[str | Path]] = None,
    fit_import: Optional[Mapping[str, Any]] = None,
    fit_stream: Optional[Mapping[str, Any]] = None,
    fit_candidates: Optional[Sequence[Mapping[str, Any]]] = None,
    fit_bindings: Optional[Sequence[Mapping[str, Any]] | Mapping[str, Any] | str | bytes | Path] = None,
    gps_source_policy: Optional[Mapping[str, Any]] = None,
    zeroing_enabled: bool = True,
    zero_window_s: float = 1,
    zero_min_samples: int = 10,
    clip_0_1: bool = False,
    active_signal_disp_col: Optional[str] = None,
    active_signal_vel_col: Optional[str] = None,
    active_disp_thresh: float = 20,
    active_vel_thresh: float = 50,
    active_window: str = "500ms",
    active_padding: str = "1s",
    active_min_seg: str = "3s",
    normalize_ranges: Optional[Dict[str, float]] = None,
    bike_profile_path: Optional[str | Path] = None,
    bike_profile: Optional[Mapping[str, Any]] = None,
    active_signal_disp_selector: Optional[Mapping[str, Any]] = None,
    active_signal_vel_selector: Optional[Mapping[str, Any]] = None,
    sample_rate_hz: Optional[float] = None,
    prefer_postprocessing_transformations: bool = False,
    ignore_on_logger_transformations: Optional[bool] = None,
    butterworth_smoothing: Optional[Sequence[Dict[str, Any]]] = None,
    butterworth_generate_residuals: bool = False,
    motion_derivation: Optional[Mapping[str, Any]] = None,
    activity_detection: Optional[Mapping[str, Any]] = None,
    timezone: Optional[str] = None,
    include_events: bool = True,
    include_metrics: bool = True,
    strict: bool = True,
) -> Dict[str, Any]:
    """Run the standard BODAQS preprocessing pipeline for one session or CSV."""
    cfg = _coerce_preprocess_config(
        preprocess_profile_path=preprocess_profile_path,
        preprocess_profile=preprocess_profile,
        preprocess_config=preprocess_config,
    )
    if cfg is not None:
        schema_path = schema_path if schema_path is not None else cfg.get("schema_path")
        fit_import = fit_import if fit_import is not None else cfg.get("fit_import")
        gps_source_policy = gps_source_policy if gps_source_policy is not None else cfg.get("gps_source_policy")

    if isinstance(schema_path, str) and not schema_path.strip():
        schema_path = None

    if isinstance(session_or_path, Mapping):
        session = dict(session_or_path)
        logger.info("Using existing session for preprocessing")
    else:
        input_path = session_or_path
        if is_bdq_path(input_path):
            session = load_bdq_session(input_path, timezone=timezone)
            logger.info("BDQ session load complete: %s", input_path)
        else:
            csv_path = input_path
            session = load_session(
                str(csv_path),
                timezone=timezone,
                log_metadata_path=log_metadata_path,
                generic_log_metadata_paths=generic_log_metadata_paths,
                sidecar_path=sidecar_path,
                generic_sidecar_paths=generic_sidecar_paths,
            )
            logger.info("Session load complete: %s", csv_path)

    resolved_schema = parse_event_schema(schema_path) if schema_path is not None else None
    resolved_bike_profile = (
        parse_bike_profile(bike_profile)
        if bike_profile is not None
        else (load_bike_profile(bike_profile_path) if bike_profile_path is not None else None)
    )

    return preprocess_resolved(
        session,
        schema=resolved_schema,
        preprocess_profile=preprocess_profile,
        preprocess_config=cfg,
        fit_import=fit_import,
        fit_stream=fit_stream,
        fit_candidates=fit_candidates,
        fit_bindings=fit_bindings,
        gps_source_policy=gps_source_policy,
        zeroing_enabled=zeroing_enabled,
        zero_window_s=zero_window_s,
        zero_min_samples=zero_min_samples,
        clip_0_1=clip_0_1,
        active_signal_disp_col=active_signal_disp_col,
        active_signal_vel_col=active_signal_vel_col,
        active_disp_thresh=active_disp_thresh,
        active_vel_thresh=active_vel_thresh,
        active_window=active_window,
        active_padding=active_padding,
        active_min_seg=active_min_seg,
        normalize_ranges=normalize_ranges,
        bike_profile=resolved_bike_profile,
        bike_profile_path=bike_profile_path,
        active_signal_disp_selector=active_signal_disp_selector,
        active_signal_vel_selector=active_signal_vel_selector,
        sample_rate_hz=sample_rate_hz,
        prefer_postprocessing_transformations=prefer_postprocessing_transformations,
        ignore_on_logger_transformations=ignore_on_logger_transformations,
        butterworth_smoothing=butterworth_smoothing,
        butterworth_generate_residuals=butterworth_generate_residuals,
        motion_derivation=motion_derivation,
        activity_detection=activity_detection,
        include_events=include_events,
        include_metrics=include_metrics,
        strict=strict,
    )

