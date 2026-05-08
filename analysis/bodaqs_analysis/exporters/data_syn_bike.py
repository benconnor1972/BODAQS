"""Export processed BODAQS sessions to the data.syn.bike CSV shape.

The core API is transport-agnostic: it consumes an in-memory session mapping and
returns one or more pandas DataFrames plus machine-readable metadata. File IO is
kept in the separate ``write_data_syn_bike_exports`` convenience helper.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd


DATA_SYN_BIKE_FORMAT = "data_syn_bike"

DEFAULT_DATA_SYN_BIKE_COLUMNS: dict[str, str] = {
    "time": "Sample Time",
    "front_raw": "Front Raw",
    "rear_raw": "Rear Raw",
    "lon": "Long",
    "lat": "Lat",
    "speed": "Speed",
}

LAT_COLS = (
    "gps_fit_position_latitude_dom_world [deg]",
    "gps_position_latitude_dom_world [deg]",
    "latitude_deg",
    "lat",
)
LON_COLS = (
    "gps_fit_position_longitude_dom_world [deg]",
    "gps_position_longitude_dom_world [deg]",
    "longitude_deg",
    "lon",
    "long",
)
SPEED_COLS = (
    "gps_fit_enhanced_speed_dom_world [m/s]",
    "gps_fit_speed_dom_world [m/s]",
    "gps_speed_dom_world [m/s]",
    "speed_mps",
    "speed",
)

DEFAULT_FILENAME_TEMPLATE = "{session_id}__{export_id}__data_syn_bike.csv"


def default_data_syn_bike_export_config(**overrides: Any) -> dict[str, Any]:
    """Return a validated default data.syn.bike export configuration."""
    config: dict[str, Any] = {
        "columns": dict(DEFAULT_DATA_SYN_BIKE_COLUMNS),
        "adc_max_count": 4095,
        "invert_raw_by_end": {"front": False, "rear": False},
        "invert_raw_columns": [],
        "time_format": "sample_count",
        "sample_count_origin": "session",
        "speed_multiplier": 3.6 / 1.852,
        "drop_inactive": True,
        "split_by_activity": False,
        "filename_template": DEFAULT_FILENAME_TEMPLATE,
    }
    config.update(overrides)
    return _validate_export_config(config)


def export_data_syn_bike_resolved(
    session: Mapping[str, Any],
    *,
    export_config: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Build one or more data.syn.bike export tables from a processed session."""
    if not isinstance(session, Mapping):
        raise ValueError("session must be a mapping")
    df = session.get("df")
    if not isinstance(df, pd.DataFrame):
        raise ValueError("session['df'] must be a pandas DataFrame")
    if "time_s" not in df.columns:
        raise ValueError("Session dataframe does not contain required time_s column")

    config = default_data_syn_bike_export_config(**dict(export_config or {}))
    session_id = str(session.get("session_id") or ((session.get("meta") or {}).get("session_id")) or "session")
    run_id = str(session.get("run_id") or ((session.get("meta") or {}).get("run_id")) or "")

    front_col, front_info, front_reason = _pick_raw_column(session, "front")
    rear_col, rear_info, rear_reason = _pick_raw_column(session, "rear")
    front_inverted, front_inversion_reason = _raw_inversion(front_col, front_info, "front", session, config)
    rear_inverted, rear_inversion_reason = _raw_inversion(rear_col, rear_info, "rear", session, config)

    lat_col = _first_existing(df, LAT_COLS)
    lon_col = _first_existing(df, LON_COLS)
    speed_col = _first_existing(df, SPEED_COLS)

    active_mask = _active_rows_mask(df)
    inactive_rows_total = int((~active_mask).sum())
    regions = _activity_regions(df, active_mask, split_by_activity=bool(config["split_by_activity"]))

    exports: list[dict[str, Any]] = []
    for region_index, region in enumerate(regions):
        if bool(config["split_by_activity"]):
            export_id = f"activity_{region_index + 1:03d}"
        else:
            export_id = "session"

        region_df = df.iloc[int(region["start_row"]) : int(region["end_row_exclusive"])]
        region_mask = active_mask.iloc[int(region["start_row"]) : int(region["end_row_exclusive"])]
        export_df, export_meta = _build_export_frame_for_region(
            session,
            region_df=region_df,
            region_active_mask=region_mask,
            source_start_row=int(region["start_row"]),
            config=config,
            front_col=front_col,
            front_info=front_info,
            front_reason=front_reason,
            front_inverted=front_inverted,
            front_inversion_reason=front_inversion_reason,
            rear_col=rear_col,
            rear_info=rear_info,
            rear_reason=rear_reason,
            rear_inverted=rear_inverted,
            rear_inversion_reason=rear_inversion_reason,
            lat_col=lat_col,
            lon_col=lon_col,
            speed_col=speed_col,
        )
        if export_df.empty:
            continue

        exports.append(
            {
                "export_id": export_id,
                "dataframe": export_df,
                "region": region,
                "metadata": {
                    **export_meta,
                    "export_id": export_id,
                    "region_index": region_index,
                },
            }
        )

    summary = {
        "session_id": session_id,
        "run_id": run_id,
        "n_exports": len(exports),
        "input_rows": int(len(df)),
        "exported_rows": int(sum(len(item["dataframe"]) for item in exports)),
        "inactive_rows_dropped": inactive_rows_total if bool(config["drop_inactive"]) else 0,
        "split_by_activity": bool(config["split_by_activity"]),
        "time_format": config["time_format"],
        "sample_count_origin": config["sample_count_origin"],
        "front_raw_col": front_col,
        "front_raw_reason": front_reason,
        "front_raw_inverted": front_inverted,
        "front_raw_inversion_reason": front_inversion_reason,
        "rear_raw_col": rear_col,
        "rear_raw_reason": rear_reason,
        "rear_raw_inverted": rear_inverted,
        "rear_raw_inversion_reason": rear_inversion_reason,
        "lat_col": lat_col,
        "lon_col": lon_col,
        "speed_col": speed_col,
    }
    return {
        "format": DATA_SYN_BIKE_FORMAT,
        "session_id": session_id,
        "run_id": run_id,
        "config": _public_config(config),
        "exports": exports,
        "summary": summary,
    }


def write_data_syn_bike_exports(
    export_result: Mapping[str, Any],
    output_dir: str | Path,
    *,
    filename_template: Optional[str] = None,
) -> dict[str, Any]:
    """Write a data.syn.bike export result to headerless CSV files."""
    if not isinstance(export_result, Mapping):
        raise ValueError("export_result must be a mapping returned by export_data_syn_bike_resolved")
    exports = export_result.get("exports")
    if not isinstance(exports, Sequence) or isinstance(exports, (str, bytes, bytearray)):
        raise ValueError("export_result['exports'] must be a list")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    config = export_result.get("config") if isinstance(export_result.get("config"), Mapping) else {}
    template = filename_template or str(config.get("filename_template") or DEFAULT_FILENAME_TEMPLATE)
    session_id = str(export_result.get("session_id") or "session")
    run_id = str(export_result.get("run_id") or "")

    written: list[dict[str, Any]] = []
    for item in exports:
        if not isinstance(item, Mapping):
            continue
        export_df = item.get("dataframe")
        if not isinstance(export_df, pd.DataFrame):
            continue
        export_id = str(item.get("export_id") or "export")
        filename = _render_filename(template, session_id=session_id, run_id=run_id, export_id=export_id)
        out_path = out_dir / filename
        export_df.to_csv(out_path, index=False, header=False, na_rep="")
        written.append(
            {
                "path": out_path,
                "export_id": export_id,
                "rows": int(len(export_df)),
                "metadata": dict(item.get("metadata") or {}),
            }
        )

    return {
        "format": DATA_SYN_BIKE_FORMAT,
        "session_id": session_id,
        "output_dir": out_dir,
        "written": written,
        "n_files": len(written),
    }


def _build_export_frame_for_region(
    session: Mapping[str, Any],
    *,
    region_df: pd.DataFrame,
    region_active_mask: pd.Series,
    source_start_row: int,
    config: Mapping[str, Any],
    front_col: Optional[str],
    front_info: Mapping[str, Any],
    front_reason: str,
    front_inverted: bool,
    front_inversion_reason: str,
    rear_col: Optional[str],
    rear_info: Mapping[str, Any],
    rear_reason: str,
    rear_inverted: bool,
    rear_inversion_reason: str,
    lat_col: Optional[str],
    lon_col: Optional[str],
    speed_col: Optional[str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    columns = config["columns"]

    front = _numeric_or_blank(region_df, front_col)
    rear = _numeric_or_blank(region_df, rear_col)
    adc_max = int(config["adc_max_count"])

    if front_col is not None and front_inverted:
        front_num = pd.to_numeric(front, errors="coerce")
        front = (adc_max - front_num).where(np.isfinite(front_num), "")
    if rear_col is not None and rear_inverted:
        rear_num = pd.to_numeric(rear, errors="coerce")
        rear = (adc_max - rear_num).where(np.isfinite(rear_num), "")

    front = _raw_counts_for_export(front) if front_col is not None else front
    rear = _raw_counts_for_export(rear) if rear_col is not None else rear

    out = pd.DataFrame(
        {
            columns["time"]: _sample_time_for_export(region_df, source_start_row=source_start_row, config=config),
            columns["front_raw"]: front,
            columns["rear_raw"]: rear,
            columns["lon"]: _numeric_or_blank(region_df, lon_col),
            columns["lat"]: _numeric_or_blank(region_df, lat_col),
            columns["speed"]: _numeric_or_blank(
                region_df,
                speed_col,
                multiplier=float(config["speed_multiplier"]),
            ),
        },
        index=region_df.index,
    )

    inactive_rows_dropped = 0
    if bool(config["drop_inactive"]):
        inactive_rows_dropped = int((~region_active_mask).sum())
        if inactive_rows_dropped:
            out = out.loc[region_active_mask].copy()

    meta = {
        "front_raw_col": front_col,
        "front_raw_reason": front_reason,
        "front_raw_inverted": bool(front_inverted),
        "front_raw_inversion_reason": front_inversion_reason,
        "rear_raw_col": rear_col,
        "rear_raw_reason": rear_reason,
        "rear_raw_inverted": bool(rear_inverted),
        "rear_raw_inversion_reason": rear_inversion_reason,
        "lat_col": lat_col,
        "lon_col": lon_col,
        "speed_col": speed_col,
        "time_format": config["time_format"],
        "sample_count_origin": config["sample_count_origin"],
        "rows": int(len(out)),
        "input_rows": int(len(region_df)),
        "inactive_rows_dropped": int(inactive_rows_dropped),
    }
    return out, meta


def _activity_regions(
    df: pd.DataFrame,
    active_mask: pd.Series,
    *,
    split_by_activity: bool,
) -> list[dict[str, Any]]:
    if not split_by_activity:
        return [_region_record(df, 0, len(df))]

    active = active_mask.fillna(False).to_numpy(dtype=bool)
    regions: list[dict[str, Any]] = []
    start: Optional[int] = None
    for i, value in enumerate(active):
        if value and start is None:
            start = i
        elif not value and start is not None:
            regions.append(_region_record(df, start, i))
            start = None
    if start is not None:
        regions.append(_region_record(df, start, len(df)))
    return regions


def _region_record(df: pd.DataFrame, start_row: int, end_row_exclusive: int) -> dict[str, Any]:
    if end_row_exclusive <= start_row:
        start_time_s = None
        end_time_s = None
    else:
        time_s = pd.to_numeric(df["time_s"], errors="coerce")
        start_time_s = _finite_or_none(time_s.iloc[start_row])
        end_time_s = _finite_or_none(time_s.iloc[end_row_exclusive - 1])
    return {
        "start_row": int(start_row),
        "end_row_exclusive": int(end_row_exclusive),
        "start_time_s": start_time_s,
        "end_time_s": end_time_s,
    }


def _active_rows_mask(df: pd.DataFrame) -> pd.Series:
    if "inactive_mask_qc" in df.columns:
        inactive = pd.to_numeric(df["inactive_mask_qc"], errors="coerce").fillna(0).astype(bool)
        return pd.Series(~inactive.to_numpy(dtype=bool), index=df.index)
    if "inactive_mask" in df.columns:
        inactive = pd.to_numeric(df["inactive_mask"], errors="coerce").fillna(0).astype(bool)
        return pd.Series(~inactive.to_numpy(dtype=bool), index=df.index)
    if "active_mask_qc" in df.columns:
        return pd.Series(df["active_mask_qc"].astype(bool).to_numpy(dtype=bool), index=df.index)
    return pd.Series(True, index=df.index)


def _sample_time_for_export(
    df: pd.DataFrame,
    *,
    source_start_row: int,
    config: Mapping[str, Any],
) -> pd.Series:
    time_format = str(config["time_format"])
    if time_format == "sample_count":
        origin = str(config["sample_count_origin"])
        if origin == "export":
            values = np.arange(len(df), dtype=np.uint64)
        elif origin == "session":
            values = np.arange(source_start_row, source_start_row + len(df), dtype=np.uint64)
        else:
            raise ValueError(f"Unsupported sample_count_origin: {origin!r}")
        return pd.Series(values, index=df.index)
    if time_format == "elapsed_s":
        return pd.to_numeric(df["time_s"], errors="coerce")
    raise ValueError(f"Unsupported time_format: {time_format!r}")


def _pick_raw_column(session: Mapping[str, Any], end: str) -> tuple[Optional[str], dict[str, Any], str]:
    df = session["df"]
    end = _norm(end)
    candidates: list[tuple[int, str, dict[str, Any], str]] = []

    for col, info in _signals(session).items():
        if col not in df.columns:
            continue
        if _norm(info.get("end")) != end:
            continue
        if not _is_raw_signal(col, info):
            continue
        candidates.append((_raw_domain_score(info, col), col, info, "signal registry"))

    if not candidates:
        end_tokens = ("front", "fork") if end == "front" else ("rear", "shock")
        for col in df.columns:
            name = _norm(col)
            if not any(tok in name for tok in end_tokens):
                continue
            if "raw" not in name and "counts" not in name:
                continue
            info = {"end": end, "quantity": "raw", "unit": "counts", "domain": None}
            candidates.append((_raw_domain_score(info, col), str(col), info, "column-name fallback"))

    if not candidates:
        return None, {}, "not found"

    candidates.sort(key=lambda item: (item[0], item[1]))
    _, col, info, reason = candidates[0]
    return col, info, reason


def _signals(session: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    signals = ((session.get("meta") or {}).get("signals") or {})
    return {str(k): dict(v) for k, v in signals.items() if isinstance(v, Mapping)}


def _is_raw_signal(col: str, info: Mapping[str, Any]) -> bool:
    quantity = _norm(info.get("quantity"))
    kind = _norm(info.get("kind"))
    unit = _norm(info.get("unit"))
    name = _norm(col)
    return quantity == "raw" or kind == "raw" or unit == "counts" or "_raw" in name or "[counts]" in name


def _raw_domain_score(info: Mapping[str, Any], col: str) -> int:
    domain = _norm(info.get("domain"))
    name = _norm(col)
    if domain == "wheel" or "wheel" in name:
        return 0
    if domain == "suspension" or "shock" in name or "fork" in name:
        return 1
    return 2


def _raw_inversion(
    col: Optional[str],
    info: Mapping[str, Any],
    end: str,
    session: Mapping[str, Any],
    config: Mapping[str, Any],
) -> tuple[bool, str]:
    invert_raw_columns = {str(x) for x in config.get("invert_raw_columns", [])}
    invert_raw_by_end = config.get("invert_raw_by_end")
    if col is not None and str(col) in invert_raw_columns:
        return True, "manual column override"
    if isinstance(invert_raw_by_end, Mapping) and bool(invert_raw_by_end.get(end, False)):
        return True, "manual end override"
    reason = _metadata_inversion_reason(session, col, info)
    if reason:
        return True, reason
    return False, "not inverted"


def _metadata_inversion_reason(
    session: Mapping[str, Any],
    col: Optional[str],
    info: Mapping[str, Any],
) -> Optional[str]:
    for source, mapping in _calibration_candidates(session, col, info):
        for key in ("invert", "inverted", "raw_inverted", "calibration_invert"):
            if isinstance(mapping.get(key), bool) and bool(mapping[key]):
                return f"{source}.{key}=true"
        range_reason = _range_inversion_reason(mapping, source=source)
        if range_reason:
            return range_reason
    return None


def _calibration_candidates(session: Mapping[str, Any], col: Optional[str], info: Mapping[str, Any]):
    if isinstance(info, Mapping):
        yield "signal metadata", info
        calibration = info.get("calibration")
        if isinstance(calibration, Mapping):
            yield "signal calibration", calibration

    meta = session.get("meta") if isinstance(session, Mapping) else None
    if not isinstance(meta, Mapping):
        return

    channel_info = meta.get("channel_info")
    if col is not None and isinstance(channel_info, Mapping):
        channel = channel_info.get(str(col))
        if isinstance(channel, Mapping):
            yield "channel metadata", channel
            calibration = channel.get("calibration")
            if isinstance(calibration, Mapping):
                yield "channel calibration", calibration

    refs = []
    for key in ("calibration_ref", "sensor", "sensor_id"):
        value = info.get(key) if isinstance(info, Mapping) else None
        if isinstance(value, str) and value.strip():
            refs.append(value.strip())
    if col is not None and isinstance(channel_info, Mapping):
        channel = channel_info.get(str(col))
        if isinstance(channel, Mapping):
            for key in ("calibration_ref", "sensor", "sensor_id"):
                value = channel.get(key)
                if isinstance(value, str) and value.strip():
                    refs.append(value.strip())

    seen_refs = []
    for ref in refs:
        if ref not in seen_refs:
            seen_refs.append(ref)

    for container_key in ("sensors", "declared_sensors", "calibrations"):
        container = meta.get(container_key)
        if not isinstance(container, Mapping):
            continue
        for ref in seen_refs:
            obj = container.get(ref)
            if isinstance(obj, Mapping):
                yield f"{container_key}.{ref}", obj
                calibration = obj.get("calibration")
                if isinstance(calibration, Mapping):
                    yield f"{container_key}.{ref}.calibration", calibration


def _range_inversion_reason(mapping: Mapping[str, Any], *, source: str) -> Optional[str]:
    start = _first_numeric(
        mapping,
        (
            "range_start_count",
            "start_count",
            "raw_start_count",
            "installed_zero_count",
            "zero_count",
        ),
    )
    end = _first_numeric(
        mapping,
        (
            "range_end_count",
            "end_count",
            "raw_end_count",
            "sensor_full_count",
            "full_count",
        ),
    )
    if start is not None and end is not None and start > end:
        return f"{source} range start {start:g} > end {end:g}"
    return None


def _first_numeric(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> Optional[float]:
    for key in keys:
        if key in mapping:
            value = _as_finite_float(mapping.get(key))
            if value is not None:
                return value
    return None


def _as_finite_float(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _first_existing(df: pd.DataFrame, candidates: tuple[str, ...]) -> Optional[str]:
    for col in candidates:
        if col in df.columns:
            return col
    return None


def _numeric_or_blank(df: pd.DataFrame, col: Optional[str], *, multiplier: float = 1.0) -> pd.Series:
    if col is None or col not in df.columns:
        return _blank_series(df.index)
    s = pd.to_numeric(df[col], errors="coerce") * float(multiplier)
    return s.where(np.isfinite(s), "")


def _blank_series(index: pd.Index) -> pd.Series:
    return pd.Series([""] * len(index), index=index, dtype="object")


def _raw_counts_for_export(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce").round()
    return numeric.astype("Int64")


def _finite_or_none(value: Any) -> Optional[float]:
    out = _as_finite_float(value)
    return float(out) if out is not None else None


def _validate_export_config(config: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(config)
    columns = out.get("columns")
    if not isinstance(columns, Mapping):
        raise ValueError("data.syn.bike export config 'columns' must be a mapping")
    missing = set(DEFAULT_DATA_SYN_BIKE_COLUMNS) - set(columns)
    if missing:
        raise ValueError(f"data.syn.bike export config 'columns' missing keys: {sorted(missing)}")
    out["columns"] = {str(k): str(v) for k, v in columns.items()}

    time_format = str(out.get("time_format", "sample_count"))
    if time_format not in {"sample_count", "elapsed_s"}:
        raise ValueError("data.syn.bike export config 'time_format' must be 'sample_count' or 'elapsed_s'")
    out["time_format"] = time_format

    sample_count_origin = str(out.get("sample_count_origin", "session"))
    if sample_count_origin not in {"session", "export"}:
        raise ValueError("data.syn.bike export config 'sample_count_origin' must be 'session' or 'export'")
    out["sample_count_origin"] = sample_count_origin

    try:
        out["adc_max_count"] = int(out.get("adc_max_count", 4095))
    except Exception:
        raise ValueError("data.syn.bike export config 'adc_max_count' must be an integer") from None
    if out["adc_max_count"] <= 0:
        raise ValueError("data.syn.bike export config 'adc_max_count' must be > 0")

    try:
        out["speed_multiplier"] = float(out.get("speed_multiplier", 1.0))
    except Exception:
        raise ValueError("data.syn.bike export config 'speed_multiplier' must be numeric") from None

    invert_raw_by_end = out.get("invert_raw_by_end", {})
    if not isinstance(invert_raw_by_end, Mapping):
        raise ValueError("data.syn.bike export config 'invert_raw_by_end' must be a mapping")
    out["invert_raw_by_end"] = {str(k): bool(v) for k, v in invert_raw_by_end.items()}

    invert_raw_columns = out.get("invert_raw_columns", [])
    if not isinstance(invert_raw_columns, Sequence) or isinstance(invert_raw_columns, (str, bytes, bytearray)):
        raise ValueError("data.syn.bike export config 'invert_raw_columns' must be a list")
    out["invert_raw_columns"] = [str(x) for x in invert_raw_columns]

    out["drop_inactive"] = bool(out.get("drop_inactive", True))
    out["split_by_activity"] = bool(out.get("split_by_activity", False))
    out["filename_template"] = str(out.get("filename_template") or DEFAULT_FILENAME_TEMPLATE)
    return out


def _public_config(config: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "columns": dict(config["columns"]),
        "adc_max_count": int(config["adc_max_count"]),
        "invert_raw_by_end": dict(config["invert_raw_by_end"]),
        "invert_raw_columns": list(config["invert_raw_columns"]),
        "time_format": str(config["time_format"]),
        "sample_count_origin": str(config["sample_count_origin"]),
        "speed_multiplier": float(config["speed_multiplier"]),
        "drop_inactive": bool(config["drop_inactive"]),
        "split_by_activity": bool(config["split_by_activity"]),
        "filename_template": str(config["filename_template"]),
    }


def _render_filename(template: str, *, session_id: str, run_id: str, export_id: str) -> str:
    return template.format(
        session_id=_safe_filename_part(session_id),
        run_id=_safe_filename_part(run_id),
        export_id=_safe_filename_part(export_id),
    )


def _safe_filename_part(value: str) -> str:
    text = str(value or "").strip() or "session"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()
