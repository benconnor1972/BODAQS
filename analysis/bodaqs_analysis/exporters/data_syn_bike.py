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
        "adc_bit_count": 12,
        "adc_max_count": 4095,
        "invert_raw_by_end": {"front": False, "rear": False},
        "invert_raw_columns": [],
        "raw_scale_mode": "as_is",
        "raw_full_scale_by_end": {},
        "clip_raw_to_adc_range": True,
        "time_format": "sample_count",
        "sample_count_origin": "session",
        "speed_multiplier": 3.6 / 1.852,
        "drop_inactive": True,
        "split_by_activity": False,
        "filename_template": DEFAULT_FILENAME_TEMPLATE,
    }
    if "adc_bit_count" in overrides and "adc_max_count" not in overrides:
        try:
            bit_count = int(overrides["adc_bit_count"])
            if bit_count > 0:
                config["adc_max_count"] = (1 << bit_count) - 1
        except Exception:
            pass
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

    if str(config["raw_scale_mode"]) == "processed_wheel_travel":
        front_col, front_info, front_reason = _pick_processed_wheel_column(session, "front")
        rear_col, rear_info, rear_reason = _pick_processed_wheel_column(session, "rear")
        front_inverted, front_inversion_reason = False, "not applicable for processed_wheel_travel"
        rear_inverted, rear_inversion_reason = False, "not applicable for processed_wheel_travel"
    else:
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
        "raw_scale_mode": config["raw_scale_mode"],
        "adc_bit_count": config["adc_bit_count"],
        "adc_max_count": config["adc_max_count"],
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


def data_syn_bike_manual_settings(
    *,
    bike_profile: Optional[Mapping[str, Any]] = None,
    export_config: Optional[Mapping[str, Any]] = None,
    session: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Return the manual data.syn.bike settings implied by an export."""
    config = default_data_syn_bike_export_config(**dict(export_config or {}))
    ranges = bike_profile_travel_ranges(bike_profile)

    front_travel = ranges.get("front_wheel")
    rear_shock_travel = ranges.get("rear_shock")
    rear_wheel_travel = ranges.get("rear_wheel")
    raw_scale_mode = str(config["raw_scale_mode"])
    if raw_scale_mode == "processed_wheel_travel":
        # Rear raw is synthetic rear wheel travel, so tell data.syn.bike to
        # treat the rear input as a 1:1 shock-to-wheel channel for this import.
        rear_input_travel = rear_wheel_travel
        leverage = 1.0 if rear_wheel_travel is not None else None
    else:
        rear_input_travel = rear_shock_travel
        leverage = None
        if rear_shock_travel is not None and rear_shock_travel > 0 and rear_wheel_travel is not None:
            leverage = rear_wheel_travel / rear_shock_travel

    warnings: list[str] = []
    for label, value in (
        ("front wheel travel", front_travel),
        ("rear shock travel", rear_input_travel),
        ("rear wheel travel", rear_wheel_travel),
    ):
        if value is None:
            warnings.append(f"missing_{label.replace(' ', '_')}")

    meta = session.get("meta") if isinstance(session, Mapping) else None
    source = session.get("source") if isinstance(session, Mapping) else None
    return {
        "format": DATA_SYN_BIKE_FORMAT,
        "session_id": str(session.get("session_id")) if isinstance(session, Mapping) and session.get("session_id") else None,
        "run_id": str(session.get("run_id")) if isinstance(session, Mapping) and session.get("run_id") else None,
        "bike_profile_id": (
            str(bike_profile.get("bike_profile_id"))
            if isinstance(bike_profile, Mapping) and bike_profile.get("bike_profile_id") is not None
            else (str(meta.get("bike_profile_id")) if isinstance(meta, Mapping) and meta.get("bike_profile_id") else None)
        ),
        "bike_profile_path": (
            str(source.get("bike_profile_path")) if isinstance(source, Mapping) and source.get("bike_profile_path") else None
        ),
        "adc_bit_count": int(config["adc_bit_count"]),
        "adc_max_count": int(config["adc_max_count"]),
        "front_normalization_range_mm": front_travel,
        "rear_shock_normalization_range_mm": rear_input_travel,
        "rear_wheel_normalization_range_mm": rear_wheel_travel,
        "max_shock_mm": rear_input_travel,
        "front_wheel_travel_mm": front_travel,
        "rear_wheel_travel_mm": rear_wheel_travel,
        "average_leverage_rate": leverage,
        "raw_scale_mode": raw_scale_mode,
        "raw_full_scale_by_end": dict(config["raw_full_scale_by_end"]),
        "warnings": warnings,
    }


def render_data_syn_bike_manual_settings_text(
    settings: Mapping[str, Any],
    *,
    export_result: Optional[Mapping[str, Any]] = None,
) -> str:
    """Render a small user-facing helper file for manual data.syn.bike setup."""
    summary = export_result.get("summary") if isinstance(export_result, Mapping) else None
    lines = [
        "BODAQS data.syn.bike manual import settings",
        "",
        "Enter these values manually in data.syn.bike for the accompanying CSV export.",
        "",
    ]
    if settings.get("session_id") or settings.get("run_id"):
        lines.append(f"Session: {settings.get('run_id') or ''} / {settings.get('session_id') or ''}".strip())
    if settings.get("bike_profile_id"):
        lines.append(f"Bike profile: {settings.get('bike_profile_id')}")
    lines.extend(
        [
            "",
            f"ADC bit count: {_fmt_setting(settings.get('adc_bit_count'))}",
            f"ADC max count: {_fmt_setting(settings.get('adc_max_count'))}",
            f"Front normalisation range: {_fmt_mm(settings.get('front_normalization_range_mm'))}",
            f"Rear shock normalisation range: {_fmt_mm(settings.get('rear_shock_normalization_range_mm'))}",
            f"Rear wheel normalisation range: {_fmt_mm(settings.get('rear_wheel_normalization_range_mm'))}",
            f"Max shock: {_fmt_mm(settings.get('max_shock_mm'))}",
            f"Front wheel travel: {_fmt_mm(settings.get('front_wheel_travel_mm'))}",
            f"Rear wheel travel: {_fmt_mm(settings.get('rear_wheel_travel_mm'))}",
            f"Average leverage rate: {_fmt_setting(settings.get('average_leverage_rate'))}",
            "",
            "Notes:",
            "- CSV files are headerless data.syn.bike exports.",
            "- Raw columns may be synthetic ADC counts, not untouched logger ADC counts.",
            "- In processed_wheel_travel mode, rear raw represents rear wheel travel; use average leverage rate 1.",
            f"- Raw scale mode: {settings.get('raw_scale_mode') or 'unknown'}",
        ]
    )
    if isinstance(summary, Mapping):
        lines.extend(
            [
                f"- Exported rows: {summary.get('exported_rows')}",
                f"- Export files: {summary.get('n_exports')}",
                f"- Inactive rows dropped: {summary.get('inactive_rows_dropped')}",
            ]
        )
    warnings = settings.get("warnings")
    if isinstance(warnings, Sequence) and not isinstance(warnings, (str, bytes, bytearray)) and warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in warnings:
            lines.append(f"- {warning}")
    lines.append("")
    return "\n".join(lines)


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

    front, front_scale_meta = _raw_counts_for_end(
        session,
        region_df,
        col=front_col,
        info=front_info,
        end="front",
        config=config,
        inverted=front_inverted,
        inversion_reason=front_inversion_reason,
    )
    rear, rear_scale_meta = _raw_counts_for_end(
        session,
        region_df,
        col=rear_col,
        info=rear_info,
        end="rear",
        config=config,
        inverted=rear_inverted,
        inversion_reason=rear_inversion_reason,
    )

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
        "front_raw_scale": front_scale_meta,
        "rear_raw_col": rear_col,
        "rear_raw_reason": rear_reason,
        "rear_raw_inverted": bool(rear_inverted),
        "rear_raw_inversion_reason": rear_inversion_reason,
        "rear_raw_scale": rear_scale_meta,
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


def _pick_processed_wheel_column(session: Mapping[str, Any], end: str) -> tuple[Optional[str], dict[str, Any], str]:
    df = session["df"]
    end = _norm(end)
    candidates: list[tuple[int, str, dict[str, Any], str]] = []

    for col, info in _signals(session).items():
        if col not in df.columns:
            continue
        if not _is_wheel_displacement_signal(info):
            continue
        if _norm(info.get("end")) != end:
            continue
        candidates.append((_wheel_displacement_score(info, col), col, info, "signal registry"))

    if not candidates:
        token = f"{end}_wheel"
        for col in df.columns:
            name = _norm(col)
            if token not in name or "disp" not in name or "[mm]" not in name:
                continue
            if "raw" in name or "[counts]" in name or "_norm" in name or "[1]" in name:
                continue
            info = {"end": end, "quantity": "disp", "domain": "wheel", "unit": "mm"}
            candidates.append((_wheel_displacement_score(info, col), str(col), info, "column-name fallback"))

    if not candidates:
        return None, {}, "not found"

    candidates.sort(key=lambda item: (item[0], item[1]))
    _, col, info, reason = candidates[0]
    return col, info, reason


def _signals(session: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    signals = ((session.get("meta") or {}).get("signals") or {})
    return {str(k): dict(v) for k, v in signals.items() if isinstance(v, Mapping)}


def _is_wheel_displacement_signal(info: Mapping[str, Any]) -> bool:
    return (
        _norm(info.get("domain")) == "wheel"
        and _norm(info.get("quantity")) == "disp"
        and _norm(info.get("unit")) == "mm"
    )


def _wheel_displacement_score(info: Mapping[str, Any], col: str) -> int:
    score = 0
    if _norm(info.get("processing_role")) == "primary_analysis":
        score -= 20
    if _norm(info.get("origin")) == "analysis":
        score -= 10
    name = _norm(col)
    if "disp_dom_wheel" in name:
        score -= 5
    if "vel" in name or "acc" in name or "raw" in name:
        score += 100
    if "_norm" in name or "[1]" in name:
        score += 100
    return score


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


def _raw_counts_for_end(
    session: Mapping[str, Any],
    df: pd.DataFrame,
    *,
    col: Optional[str],
    info: Mapping[str, Any],
    end: str,
    config: Mapping[str, Any],
    inverted: bool,
    inversion_reason: str,
) -> tuple[pd.Series, dict[str, Any]]:
    if col is None or col not in df.columns:
        return _blank_series(df.index), {
            "mode": str(config["raw_scale_mode"]),
            "status": "missing_raw_column",
        }

    if str(config["raw_scale_mode"]) == "processed_wheel_travel":
        return _processed_wheel_travel_raw_counts(
            df,
            col=col,
            end=end,
            config=config,
        )

    if str(config["raw_scale_mode"]) == "calibrated_full_scale":
        scaled, meta = _calibrated_full_scale_raw_counts(
            session,
            df,
            col=col,
            info=info,
            end=end,
            config=config,
        )
        if scaled is not None:
            return scaled, meta

    values = pd.to_numeric(df[col], errors="coerce")
    adc_max = int(config["adc_max_count"])
    if inverted:
        values = (adc_max - values).where(np.isfinite(values), np.nan)
    return _raw_counts_for_export(values), {
        "mode": "as_is",
        "status": "ok",
        "inverted": bool(inverted),
        "inversion_reason": inversion_reason,
        "adc_max_count": adc_max,
    }


def _processed_wheel_travel_raw_counts(
    df: pd.DataFrame,
    *,
    col: str,
    end: str,
    config: Mapping[str, Any],
) -> tuple[pd.Series, dict[str, Any]]:
    adc_max = int(config["adc_max_count"])
    target_full_range, target_source = _raw_full_scale_for_end(
        end,
        config=config,
        calibration_full_travel=None,
    )
    if target_full_range is None or target_full_range <= 0:
        return _blank_series(df.index), {
            "mode": "processed_wheel_travel",
            "status": "missing_target_full_scale",
            "source_col": col,
            "adc_max_count": adc_max,
        }

    values = pd.to_numeric(df[col], errors="coerce").astype(float)
    scaled = values / float(target_full_range) * adc_max
    finite = np.isfinite(scaled)
    clipped_low = int(((scaled < 0) & finite).sum())
    clipped_high = int(((scaled > adc_max) & finite).sum())
    if bool(config["clip_raw_to_adc_range"]):
        scaled = scaled.clip(lower=0, upper=adc_max)

    return _raw_counts_for_export(scaled), {
        "mode": "processed_wheel_travel",
        "status": "ok",
        "source_col": col,
        "target_full_range": float(target_full_range),
        "target_full_range_source": target_source,
        "adc_max_count": adc_max,
        "adc_bit_count": int(config["adc_bit_count"]),
        "clip_raw_to_adc_range": bool(config["clip_raw_to_adc_range"]),
        "clipped_low_rows": clipped_low if bool(config["clip_raw_to_adc_range"]) else 0,
        "clipped_high_rows": clipped_high if bool(config["clip_raw_to_adc_range"]) else 0,
    }


def _calibrated_full_scale_raw_counts(
    session: Mapping[str, Any],
    df: pd.DataFrame,
    *,
    col: str,
    info: Mapping[str, Any],
    end: str,
    config: Mapping[str, Any],
) -> tuple[Optional[pd.Series], dict[str, Any]]:
    calibration_source, calibration = _first_complete_linear_calibration(session, col, info)
    adc_max = int(config["adc_max_count"])
    if calibration is None:
        return None, {
            "mode": "calibrated_full_scale",
            "status": "fallback_as_is",
            "reason": "missing_complete_linear_calibration",
            "adc_max_count": adc_max,
        }

    sensor_zero_count = _as_finite_float(calibration.get("sensor_zero_count"))
    sensor_full_count = _as_finite_float(calibration.get("sensor_full_count"))
    sensor_full_travel = _as_finite_float(calibration.get("sensor_full_travel"))
    if sensor_zero_count is None or sensor_full_count is None or sensor_full_travel is None:
        return None, {
            "mode": "calibrated_full_scale",
            "status": "fallback_as_is",
            "reason": "incomplete_calibration",
            "calibration_source": calibration_source,
            "adc_max_count": adc_max,
        }

    span_abs = abs(sensor_full_count - sensor_zero_count)
    if span_abs == 0 or sensor_full_travel <= 0:
        return None, {
            "mode": "calibrated_full_scale",
            "status": "fallback_as_is",
            "reason": "invalid_calibration_span_or_travel",
            "calibration_source": calibration_source,
            "adc_max_count": adc_max,
        }

    target_full_range, target_source = _raw_full_scale_for_end(
        end,
        config=config,
        calibration_full_travel=sensor_full_travel,
    )
    if target_full_range is None or target_full_range <= 0:
        return None, {
            "mode": "calibrated_full_scale",
            "status": "fallback_as_is",
            "reason": "missing_target_full_scale",
            "calibration_source": calibration_source,
            "adc_max_count": adc_max,
        }

    installed_zero_count = _as_finite_float(calibration.get("installed_zero_count"))
    zero_reference = installed_zero_count if installed_zero_count is not None else sensor_zero_count
    zero_reference_source = "installed_zero_count" if installed_zero_count is not None else "sensor_zero_count"
    raw = pd.to_numeric(df[col], errors="coerce").astype(float)
    invert_flag, invert_reason = _calibrated_raw_inversion(
        raw,
        calibration=calibration,
        zero_reference=zero_reference,
        sensor_zero_count=sensor_zero_count,
        sensor_full_count=sensor_full_count,
    )
    counts_per_output_unit = span_abs / sensor_full_travel
    physical_travel = (raw - zero_reference) / counts_per_output_unit
    if invert_flag:
        physical_travel = -physical_travel

    scaled = physical_travel / target_full_range * adc_max
    finite = np.isfinite(scaled)
    clipped_low = int(((scaled < 0) & finite).sum())
    clipped_high = int(((scaled > adc_max) & finite).sum())
    if bool(config["clip_raw_to_adc_range"]):
        scaled = scaled.clip(lower=0, upper=adc_max)

    return _raw_counts_for_export(scaled), {
        "mode": "calibrated_full_scale",
        "status": "ok",
        "calibration_source": calibration_source,
        "target_full_range": float(target_full_range),
        "target_full_range_source": target_source,
        "sensor_full_travel": float(sensor_full_travel),
        "zero_reference": float(zero_reference),
        "zero_reference_source": zero_reference_source,
        "counts_per_output_unit": float(counts_per_output_unit),
        "inverted": bool(invert_flag),
        "inversion_reason": invert_reason,
        "adc_max_count": adc_max,
        "adc_bit_count": int(config["adc_bit_count"]),
        "clip_raw_to_adc_range": bool(config["clip_raw_to_adc_range"]),
        "clipped_low_rows": clipped_low if bool(config["clip_raw_to_adc_range"]) else 0,
        "clipped_high_rows": clipped_high if bool(config["clip_raw_to_adc_range"]) else 0,
    }


def _calibrated_raw_inversion(
    raw: pd.Series,
    *,
    calibration: Mapping[str, Any],
    zero_reference: float,
    sensor_zero_count: float,
    sensor_full_count: float,
) -> tuple[bool, str]:
    configured = calibration.get("invert")
    configured_flag = bool(configured) if isinstance(configured, bool) else bool(sensor_full_count < sensor_zero_count)
    configured_reason = "calibration.invert" if isinstance(configured, bool) else "sensor_full_count_less_than_zero_count"

    delta = raw - float(zero_reference)
    finite = delta[np.isfinite(delta)]
    if not finite.empty:
        normal_nonnegative = float((finite >= 0).mean())
        inverted_nonnegative = float(((-finite) >= 0).mean())
        if inverted_nonnegative >= normal_nonnegative + 0.5:
            return True, "raw_values_decrease_from_zero_reference"
        if normal_nonnegative >= inverted_nonnegative + 0.5:
            return False, "raw_values_increase_from_zero_reference"

    return configured_flag, configured_reason


def _first_complete_linear_calibration(
    session: Mapping[str, Any],
    col: Optional[str],
    info: Mapping[str, Any],
) -> tuple[Optional[str], Optional[Mapping[str, Any]]]:
    for source, mapping in _calibration_candidates(session, col, info):
        calibration_type = str(mapping.get("type") or "linear").strip().lower()
        if calibration_type != "linear":
            continue
        if (
            _as_finite_float(mapping.get("sensor_zero_count")) is not None
            and _as_finite_float(mapping.get("sensor_full_count")) is not None
            and _as_finite_float(mapping.get("sensor_full_travel")) is not None
        ):
            return source, mapping
    return None, None


def _raw_full_scale_for_end(
    end: str,
    *,
    config: Mapping[str, Any],
    calibration_full_travel: Optional[float],
) -> tuple[Optional[float], str]:
    configured = config.get("raw_full_scale_by_end")
    if isinstance(configured, Mapping):
        value = _as_finite_float(configured.get(end))
        if value is not None and value > 0:
            return float(value), f"raw_full_scale_by_end.{end}"
    if calibration_full_travel is not None and calibration_full_travel > 0:
        return float(calibration_full_travel), "calibration.sensor_full_travel"
    return None, "missing"


def bike_profile_travel_ranges(bike_profile: Optional[Mapping[str, Any]]) -> dict[str, Optional[float]]:
    """Return bike-profile travel ranges used by data.syn.bike helpers."""
    out: dict[str, Optional[float]] = {
        "front_wheel": None,
        "front_suspension": None,
        "rear_shock": None,
        "rear_wheel": None,
    }
    if not isinstance(bike_profile, Mapping):
        return out

    ranges = bike_profile.get("normalization_ranges")
    if not isinstance(ranges, Sequence) or isinstance(ranges, (str, bytes, bytearray)):
        return out

    for item in ranges:
        if not isinstance(item, Mapping):
            continue
        selector = item.get("signal")
        if not isinstance(selector, Mapping):
            continue
        value = _as_finite_float(item.get("full_range"))
        if value is None or value <= 0:
            continue
        end = _norm(selector.get("end"))
        quantity = _norm(selector.get("quantity"))
        domain = _norm(selector.get("domain"))
        unit = _norm(selector.get("unit"))
        if quantity != "disp" or unit != "mm":
            continue
        if end == "front" and domain == "wheel":
            out["front_wheel"] = float(value)
        elif end == "front" and domain == "suspension":
            out["front_suspension"] = float(value)
        elif end == "rear" and domain == "suspension":
            out["rear_shock"] = float(value)
        elif end == "rear" and domain == "wheel":
            out["rear_wheel"] = float(value)
    if out["front_wheel"] is None and out["front_suspension"] is not None:
        out["front_wheel"] = _derive_front_wheel_travel_from_transform(
            bike_profile,
            front_suspension_travel=float(out["front_suspension"]),
        )
    return out


def _derive_front_wheel_travel_from_transform(
    bike_profile: Mapping[str, Any],
    *,
    front_suspension_travel: float,
) -> Optional[float]:
    transforms = bike_profile.get("signal_transforms")
    if not isinstance(transforms, Sequence) or isinstance(transforms, (str, bytes, bytearray)):
        return None

    for transform in transforms:
        if not isinstance(transform, Mapping) or transform.get("enabled") is False:
            continue
        input_selector = transform.get("input")
        output_selector = transform.get("output")
        if not isinstance(input_selector, Mapping) or not isinstance(output_selector, Mapping):
            continue
        if not (
            _selector_matches(input_selector, end="front", domain="suspension", quantity="disp", unit="mm")
            and _selector_matches(output_selector, end="front", domain="wheel", quantity="disp", unit="mm")
        ):
            continue
        method = _norm(transform.get("method"))
        if method == "polynomial":
            derived = _polynomial_travel_at(transform, front_suspension_travel)
        elif method == "lut":
            derived = _lut_travel_at(transform, front_suspension_travel)
        else:
            derived = None
        if derived is not None and derived > 0:
            return float(derived)
    return None


def _selector_matches(
    selector: Mapping[str, Any],
    *,
    end: str,
    domain: str,
    quantity: str,
    unit: str,
) -> bool:
    return (
        _norm(selector.get("end")) == end
        and _norm(selector.get("domain")) == domain
        and _norm(selector.get("quantity")) == quantity
        and _norm(selector.get("unit")) == unit
    )


def _polynomial_travel_at(transform: Mapping[str, Any], travel: float) -> Optional[float]:
    polynomial = transform.get("polynomial")
    if not isinstance(polynomial, Mapping):
        return None
    coefficients = polynomial.get("coefficients")
    if not isinstance(coefficients, Sequence) or isinstance(coefficients, (str, bytes, bytearray)):
        return None
    values: list[float] = []
    for coefficient in coefficients:
        value = _as_finite_float(coefficient)
        if value is None:
            return None
        values.append(value)
    if not values:
        return None
    order = _norm(polynomial.get("coefficient_order") or "ascending")
    if order == "descending":
        values = list(reversed(values))

    def evaluate(x: float) -> float:
        return float(sum(coefficient * (x ** power) for power, coefficient in enumerate(values)))

    return evaluate(float(travel)) - evaluate(0.0)


def _lut_travel_at(transform: Mapping[str, Any], travel: float) -> Optional[float]:
    lut = transform.get("lut")
    if not isinstance(lut, Sequence) or isinstance(lut, (str, bytes, bytearray)):
        return None
    points: list[tuple[float, float]] = []
    for item in lut:
        if not isinstance(item, Mapping):
            continue
        x = _as_finite_float(item.get("input"))
        y = _as_finite_float(item.get("output"))
        if x is not None and y is not None:
            points.append((x, y))
    if not points:
        return None
    points.sort(key=lambda item: item[0])
    xs = np.asarray([item[0] for item in points], dtype=float)
    ys = np.asarray([item[1] for item in points], dtype=float)
    return float(np.interp(float(travel), xs, ys))


def _fmt_mm(value: Any) -> str:
    number = _as_finite_float(value)
    return "unknown" if number is None else f"{number:g} mm"


def _fmt_setting(value: Any) -> str:
    number = _as_finite_float(value)
    if number is not None:
        return f"{number:g}"
    text = "" if value is None else str(value).strip()
    return text or "unknown"


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
        out["adc_bit_count"] = int(out.get("adc_bit_count", 12))
    except Exception:
        raise ValueError("data.syn.bike export config 'adc_bit_count' must be an integer") from None
    if out["adc_bit_count"] <= 0:
        raise ValueError("data.syn.bike export config 'adc_bit_count' must be > 0")

    raw_scale_mode = str(out.get("raw_scale_mode", "as_is"))
    if raw_scale_mode not in {"as_is", "calibrated_full_scale", "processed_wheel_travel"}:
        raise ValueError(
            "data.syn.bike export config 'raw_scale_mode' must be "
            "'as_is', 'calibrated_full_scale', or 'processed_wheel_travel'"
        )
    out["raw_scale_mode"] = raw_scale_mode

    raw_full_scale_by_end = out.get("raw_full_scale_by_end", {})
    if not isinstance(raw_full_scale_by_end, Mapping):
        raise ValueError("data.syn.bike export config 'raw_full_scale_by_end' must be a mapping")
    normalized_full_scales: dict[str, float] = {}
    for key, value in raw_full_scale_by_end.items():
        numeric = _as_finite_float(value)
        if numeric is None or numeric <= 0:
            raise ValueError("data.syn.bike export config 'raw_full_scale_by_end' values must be positive numbers")
        normalized_full_scales[_norm(key)] = float(numeric)
    out["raw_full_scale_by_end"] = normalized_full_scales
    out["clip_raw_to_adc_range"] = bool(out.get("clip_raw_to_adc_range", True))

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
        "adc_bit_count": int(config["adc_bit_count"]),
        "adc_max_count": int(config["adc_max_count"]),
        "invert_raw_by_end": dict(config["invert_raw_by_end"]),
        "invert_raw_columns": list(config["invert_raw_columns"]),
        "raw_scale_mode": str(config["raw_scale_mode"]),
        "raw_full_scale_by_end": dict(config["raw_full_scale_by_end"]),
        "clip_raw_to_adc_range": bool(config["clip_raw_to_adc_range"]),
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
