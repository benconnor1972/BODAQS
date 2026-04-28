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
from .io_fit import (
    FIT_DEFAULT_FIELDS,
    find_overlapping_fit_files,
    load_fit_stream,
    select_fit_candidate,
)
from .normalize import scale_signal_columns, zero_signal_columns
from .va import estimate_va, name_vel
from .schema import load_event_schema
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
from .segment import extract_segments, SegmentRequest
from .preprocess_filters import (
    apply_butterworth_smoothing,
    normalize_butterworth_smoothing_configs,
)
from .motion_derivation import derive_motion_channels
from .bike_profile import apply_signal_transforms, load_bike_profile, resolve_normalization_ranges
from .preprocess_profile import load_preprocess_config, preprocess_config_from_profile, validate_preprocess_config
from .sensor_aliases import canonical_end, canonical_sensor_id

_UNIT_RE = re.compile(r"\[(.*?)\]")
_FILENAME_STEM_DATETIME_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{2}-\d{2}-\d{2})(?:$|[^0-9].*)"
)
ACTIVE_MASK_COL = "active_mask_qc"  # stored in session["df"] (not in registry)

logger = logging.getLogger(__name__)

_LOG_METADATA_BINDING_KEY = "_bodaqs_log_metadata_binding"
_SIDECAR_BINDING_KEY = "_bodaqs_sidecar_binding"

_FIT_IMPORT_DEFAULTS: Dict[str, Any] = {
    "enabled": False,
    "fit_dir": None,
    "field_allowlist": list(FIT_DEFAULT_FIELDS),
    "ambiguity_policy": "require_binding",
    "partial_overlap": "allow",
    "persist_raw_stream": True,
    "resample_to_primary": True,
    "resample_method": "linear",
    "raw_stream_name": "gps_fit",
    "resampled_prefix": "gps_fit",
    "bindings_path": None,
}


def _metadata_binding(log_metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    binding = log_metadata.get(_LOG_METADATA_BINDING_KEY)
    if isinstance(binding, dict):
        return binding
    binding = log_metadata.get(_SIDECAR_BINDING_KEY)
    return binding if isinstance(binding, dict) else None


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
    binding = _metadata_binding(sidecar)
    bound_columns = binding.get("columns", {}) if isinstance(binding, dict) else {}
    if not isinstance(columns, dict):
        return out

    for col_name, info in columns.items():
        if not isinstance(info, dict):
            continue
        if info.get("class") != "signal":
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

        source_columns = info.get("source_columns")
        if isinstance(source_columns, list):
            ch["source_columns"] = [str(x) for x in source_columns if isinstance(x, str)]

        calibration_ref = info.get("calibration_ref")
        if isinstance(calibration_ref, str) and calibration_ref.strip():
            ch["calibration_ref"] = calibration_ref

        transform_chain = info.get("transform_chain")
        if isinstance(transform_chain, list):
            ch["transform_chain"] = [str(x) for x in transform_chain if isinstance(x, str)]

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
        if isinstance(bound, dict):
            ch["csv_column"] = bound.get("physical_column_label")
            ch["csv_ref"] = bound.get("csv_ref")

        out[dataframe_col] = ch

    return out


def _apply_log_metadata(
    session: Dict[str, Any],
    *,
    log_metadata: Dict[str, Any],
    log_metadata_path: str,
) -> None:
    source = session.setdefault("source", {})
    meta = session.setdefault("meta", {})
    qc = session.setdefault("qc", {})
    parse = qc.setdefault("parse", {})

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

    session_meta = log_metadata.get("session")
    if isinstance(session_meta, dict):
        started_at_local = session_meta.get("started_at_local")
        if isinstance(started_at_local, str) and started_at_local.strip():
            source["created_local"] = started_at_local
            meta["t0_datetime"] = started_at_local

        timezone = session_meta.get("timezone")
        if isinstance(timezone, str) and timezone.strip() and not source.get("timezone"):
            source["timezone"] = timezone

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
    sidecar_path: str,
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
    match = _FILENAME_STEM_DATETIME_RE.match(Path(csv_path).stem)
    if match is None:
        return None, None

    base_ts = pd.Timestamp(
        f"{match.group('date')}T{match.group('time').replace('-', ':')}"
    )
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

    stats = parse_run_stats_footer(str(p))
    excluded_time_columns = {"sample_id", "time_s", "clock", "Clock", "Time"}
    if isinstance(sidecar, dict):
        excluded_time_columns |= _declared_time_columns(sidecar)

    session: Dict[str, Any] = {
        "session_id": p.stem,
        "source": {
            "path": str(p),
            "filename": p.name,
            "timezone": timezone,
        },
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
    if isinstance(sidecar, dict) and isinstance(resolved_sidecar_path, str):
        _apply_log_metadata(session, log_metadata=sidecar, log_metadata_path=resolved_sidecar_path)
    _apply_filename_stem_time_anchor(session, csv_path=p)
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


def _resample_fit_columns_onto_primary(
    session: Dict[str, Any],
    *,
    fit_df: pd.DataFrame,
    fit_meta: Mapping[str, Any],
    method: str,
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
    if len(fit_df.index) >= 2:
        resampled_df, rs_meta = resample_to_time_grid(
            fit_df,
            src_time_col="time_s",
            target_time_s=target_time_s,
            columns=columns,
            method=method,
            allow_extrapolation=False,
        )
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
        }
        _append_qc_warning(session, "fit_import_resample_skipped_too_few_samples")

    for col in columns:
        df[col] = resampled_df[col].to_numpy()

    qc = session.setdefault("qc", {})
    resampling = qc.setdefault("resampling", [])
    resampling.append({"stream": str(fit_meta.get("stream_name", "gps_fit")), **rs_meta})

    transforms = qc.setdefault("transforms", {})
    transforms["resampled"] = {
        "applied": True,
        "target_rate_hz": session.get("meta", {}).get("sample_rate_hz"),
        "method": method,
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


def enrich_session_with_fit(
    session: Dict[str, Any],
    *,
    fit_import: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    cfg = _normalized_fit_import_config(fit_import)
    if not bool(cfg.get("enabled")):
        return session

    fit_dir = cfg.get("fit_dir")
    if not isinstance(fit_dir, str) or not fit_dir.strip():
        raise ValueError("fit_import.enabled=True requires fit_import.fit_dir")

    bounds = _session_absolute_bounds(session)
    if bounds is None:
        _append_qc_warning(session, "fit_import_skipped_missing_absolute_time_anchor")
        return session

    session_start, session_end = bounds
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
        bindings_path=cfg.get("bindings_path"),
    )
    if selected is None:
        _append_qc_warning(session, "fit_import_no_selected_file")
        return session

    stream_name = str(cfg.get("raw_stream_name") or "gps_fit")
    fit_df, fit_meta = load_fit_stream(
        selected["path"],
        session_start_datetime=session_start.isoformat(),
        field_allowlist=cfg.get("field_allowlist"),
    )
    fit_meta = dict(fit_meta)
    fit_meta["stream_name"] = stream_name
    fit_meta["match"] = {
        "overlap_s": float(selected.get("overlap_s", 0.0)),
        "overlap_start_datetime": selected.get("overlap_start_datetime"),
        "overlap_end_datetime": selected.get("overlap_end_datetime"),
        "ambiguity_policy": cfg.get("ambiguity_policy"),
    }

    if bool(cfg.get("persist_raw_stream", True)):
        attach_fit_stream(session, fit_df=fit_df, fit_meta=fit_meta, stream_name=stream_name)

    if bool(cfg.get("resample_to_primary", True)):
        _resample_fit_columns_onto_primary(
            session,
            fit_df=fit_df,
            fit_meta=fit_meta,
            method=str(cfg.get("resample_method", "linear")),
        )

    qc = session.setdefault("qc", {})
    fit_qc = qc.setdefault("fit_import", {})
    fit_qc.update(
        {
            "enabled": True,
            "selected_file": fit_meta.get("filename"),
            "stream_name": stream_name,
            "overlap_s": float(selected.get("overlap_s", 0.0)),
            "partial_overlap": str(cfg.get("partial_overlap", "allow")),
        }
    )
    return session
    
def _build_active_mask_from_time_s(
    df: pd.DataFrame,
    *,
    disp_col: str,
    vel_col: str,
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

    # build a time index locally (do NOT mutate df index)
    t = pd.to_numeric(df["time_s"], errors="coerce").to_numpy(dtype=float, copy=False)
    td = pd.to_timedelta(t, unit="s")

    disp_active = pd.Series(pd.to_numeric(df[disp_col], errors="coerce").to_numpy(), index=td).abs() > disp_thresh
    vel_active  = pd.Series(pd.to_numeric(df[vel_col],  errors="coerce").to_numpy(), index=td).abs() > vel_thresh

    active = disp_active & vel_active   # keep your current AND policy (change to | if desired)

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

    # apply merged blocks to td index
    keep_td = pd.Series(False, index=td)
    for s, e in merged:
        keep_td |= (keep_td.index >= s) & (keep_td.index <= e)

    # return aligned to df rows (original df index)
    keep = pd.Series(keep_td.to_numpy(dtype=bool), index=df.index, name=ACTIVE_MASK_COL)
    return keep


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
                               butterworth_smoothing: Optional[Sequence[Dict[str, Any]]] = None,
                               butterworth_generate_residuals: bool = False,
                               motion_derivation: Optional[Mapping[str, Any]] = None,
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
        motion_derivation = cfg.get("motion_derivation", motion_derivation)
        butterworth_smoothing = cfg.get("butterworth_smoothing", butterworth_smoothing)
        butterworth_generate_residuals = bool(
            cfg.get("butterworth_generate_residuals", butterworth_generate_residuals)
        )
        strict = bool(cfg.get("strict", strict))

    df = session["df"].copy()

    # QC: ensure structure exists early
    qc = session.setdefault("qc", {})
    transforms = qc.setdefault("transforms", {})

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
        va_cols = list(normalize_ranges.keys())

    # Ensure VA is computed for the activity-mask displacement signal if provided
    if active_signal_disp_col and (active_signal_disp_col not in set(va_cols)):
        va_cols = list(va_cols) + [active_signal_disp_col]

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
    return session

     
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
    butterworth_smoothing: Optional[Sequence[Dict[str, Any]]] = None,
    butterworth_generate_residuals: bool = False,
    motion_derivation: Optional[Mapping[str, Any]] = None,
    timezone: Optional[str] = None,
    include_events: bool = True,
    include_metrics: bool = True,
    strict: bool = True,
) -> Dict[str, Any]:
    """Run the standard BODAQS preprocessing pipeline for one session or CSV.

    ``session_or_path`` may be an existing session dict or a logger CSV path.
    The return value is always a results dictionary with stable top-level keys:
    ``session``, ``schema``, ``events``, ``segments``, and ``metrics``.

    If an event schema is supplied directly or through ``preprocess_config``,
    event detection runs by default. Metrics run when events are enabled unless
    ``include_metrics`` is false.

    ``strict``:
        When True, metrics computation enforces strict trigger/spec requirements (may raise).
        When False, missing trigger times (etc.) should propagate as NaN where supported.
    """
    cfg = _coerce_preprocess_config(
        preprocess_profile_path=preprocess_profile_path,
        preprocess_profile=preprocess_profile,
        preprocess_config=preprocess_config,
    )
    if cfg is not None:
        schema_path = schema_path if schema_path is not None else cfg.get("schema_path")
        fit_import = fit_import if fit_import is not None else cfg.get("fit_import")
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
        motion_derivation = cfg.get("motion_derivation", motion_derivation)
        butterworth_smoothing = cfg.get("butterworth_smoothing", butterworth_smoothing)
        butterworth_generate_residuals = bool(
            cfg.get("butterworth_generate_residuals", butterworth_generate_residuals)
        )
        strict = bool(cfg.get("strict", strict))

    if isinstance(schema_path, str) and not schema_path.strip():
        schema_path = None

    csv_path: Optional[str | Path] = None
    if isinstance(session_or_path, Mapping):
        session = dict(session_or_path)
        source = session.get("source") if isinstance(session.get("source"), dict) else {}
        source_path = source.get("path") if isinstance(source, dict) else None
        if isinstance(source_path, (str, Path)):
            csv_path = source_path
        logger.info("Using existing session for preprocessing")
    else:
        csv_path = session_or_path
        session = load_session(
            str(csv_path),
            timezone=timezone,
            log_metadata_path=log_metadata_path,
            generic_log_metadata_paths=generic_log_metadata_paths,
            sidecar_path=sidecar_path,
            generic_sidecar_paths=generic_sidecar_paths,
        )
        logger.info("Session load complete: %s", csv_path)

    session = enrich_session_with_fit(session, fit_import=fit_import)
    if bool((fit_import or {}).get("enabled")):
        logger.info("FIT enrichment step complete")

    session = _preprocess_loaded_session(
        session,
        preprocess_config=cfg,
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
        bike_profile=bike_profile,
        bike_profile_path=bike_profile_path,
        motion_derivation=motion_derivation,
        butterworth_smoothing=butterworth_smoothing,
        butterworth_generate_residuals=butterworth_generate_residuals,
        strict=strict,
    )
    logger.info("Session pre-process complete")

    # debug
    t = session["df"]["time_s"].to_numpy()
    logger.debug("time_s start/end: %s .. %s", t[0], t[-1])
    logger.debug(
        "dt median/min/max: %s / %s / %s",
        float(np.median(np.diff(t))),
        float(np.min(np.diff(t))),
        float(np.max(np.diff(t))),
    )

    # debug: inspect signal registry shape
    sig = session.get("meta", {}).get("signals", {})
    logger.debug("signals entries: %d", len(sig))

    # show a few entries
    for col, info in list(sig.items())[:10]:
        logger.debug("%s -> %s", col, info)

    # show kind/unit distribution
    kinds = {}
    units = {}
    for info in sig.values():
        if isinstance(info, dict):
            kinds[info.get("kind")] = kinds.get(info.get("kind"), 0) + 1
            units[info.get("unit")] = units.get(info.get("unit"), 0) + 1
    logger.debug("kind counts: %s", kinds)
    logger.debug("unit counts: %s", units)

    # debug
    assert "df" in session
    assert "time_s" in session["df"].columns
    assert "signals" in session.get("meta", {})

    meta = session.setdefault("meta", {})
    if not isinstance(meta, dict):
        raise ValueError("session['meta'] must be a dict")

    # Standardized session_id: CSV filename stem where a source path is available.
    if csv_path is not None:
        sid = os.path.splitext(os.path.basename(str(csv_path)))[0]
    else:
        sid = str(session.get("session_id") or meta.get("session_id") or "session")
    session["session_id"] = sid
    meta["session_id"] = sid

    schema = load_event_schema(schema_path) if schema_path is not None and include_events else None
    if schema is not None:
        logger.info("Schema load complete")

    events_df = pd.DataFrame()
    if schema is not None and include_events:
        events_df = detect_events_from_schema(
            session["df"],
            schema,
            meta=session["meta"],
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


    # Segment extraction (one schema event per call in v0)
    detected_sids = sorted(events_df["schema_id"].dropna().astype(str).unique().tolist()) if (
        isinstance(events_df, pd.DataFrame) and ("schema_id" in events_df.columns)
    ) else []

    defined_sids = sorted(
        [
            str(e.get("id"))
            for e in ((schema or {}).get("events") or [])
            if isinstance(e, dict) and e.get("id")
        ]
    )
    missing = [sid for sid in defined_sids if sid not in set(detected_sids)]
    if missing:
        logger.info("Schema events with zero detections this run: %s", missing)

    if schema is not None and include_metrics:
        logger.info("Running segment extraction for detected schema events: %s", detected_sids)

    bundles_by_schema_id: dict[str, dict] = {}
    metrics_parts: list[pd.DataFrame] = []

    for sid in (detected_sids if schema is not None and include_metrics else []):
        # (Optional but nice) pre-filter for clarity + earlier logging
        events_sel = events_df[events_df["schema_id"].astype(str) == str(sid)]
        if events_sel.empty:
            logger.info("No events for schema_id=%s; skipping.", sid)
            continue

        bundle = extract_segments(
            df=session["df"],
            events=events_df,  # extract_segments will select internally; keep as-is
            meta=session["meta"],
            schema=schema,
            request=SegmentRequest(schema_id=sid),
        )
        bundles_by_schema_id[sid] = bundle
        logger.info("Segment extraction complete (schema_id=%s)", sid)

        seg = bundle["segments"]
        valid_n = int(seg["valid"].sum()) if "valid" in seg.columns else 0
        total_n = len(seg)
        logger.info("segments valid (schema_id=%s): %d/%d", sid, valid_n, total_n)

        # debug
        t2 = bundle["data"].get("t_rel_s")
        logger.debug("t_rel_s type=%s shape=%s", type(t2), getattr(t2, "shape", None))
        if isinstance(t2, np.ndarray):
            logger.debug("t_rel_s[0][:10]=%s", t2[0][:10])
            logger.debug("t_rel_s[0][-10:]=%s", t2[0][-10:])
            d = np.diff(t2[0].astype(float))
            logger.debug("diff stats: min=%s med=%s max=%s", np.nanmin(d), np.nanmedian(d), np.nanmax(d))
            logger.debug("nonpositive diffs=%d", int(np.sum(d <= 0)))
        # debug

        # Metrics from SegmentBundle (per schema event)
        metrics_i = compute_metrics_from_segments(bundle, schema=schema, strict=strict)
        logger.info("Metrics calculation complete (schema_id=%s)", sid)

        # Ensure schema_id is present for grouping/faceting downstream
        if "schema_id" not in metrics_i.columns:
            metrics_i = metrics_i.copy()
            metrics_i["schema_id"] = sid

        metrics_parts.append(metrics_i)

    metrics_df = pd.concat(metrics_parts, ignore_index=True) if metrics_parts else pd.DataFrame()

    if schema is not None and include_metrics:
        validate_metrics_df(metrics_df, events_df=events_df)
        logger.info("Metrics validation complete")

    return {
        "session": session,
        "schema": schema,
        "events": events_df,
        "segments": bundles_by_schema_id,
        "metrics": metrics_df,
    }

