from __future__ import annotations
import json
import logging
from pathlib import Path
import re
from typing import Any, Optional, Sequence
import numpy as np
import pandas as pd

from .sensor_aliases import canonical_sensor_id, normalize_sensor_token
from .signalname import SignalNameParts, format_signal_name, SignalNameError


_SIDECAR_BINDING_KEY = "_bodaqs_sidecar_binding"
logger = logging.getLogger(__name__)


def infer_sidecar_path(path: str) -> Optional[str]:
    """
    Return a same-stem JSON sidecar path when present.
    """
    candidate = Path(path).with_suffix(".json")
    return str(candidate) if candidate.exists() else None


def load_logger_sidecar(path: str) -> dict[str, Any]:
    """
    Load and lightly validate a logger sidecar JSON document.
    """
    p = Path(path)
    obj = json.loads(p.read_text(encoding="utf-8"))

    if not isinstance(obj, dict):
        raise ValueError(f"Logger sidecar must contain a JSON object: {path}")

    contract = obj.get("contract")
    if not isinstance(contract, dict):
        raise ValueError(f"Logger sidecar missing required object 'contract': {path}")

    if not isinstance(contract.get("name"), str) or not contract["name"].strip():
        raise ValueError(f"Logger sidecar missing required string 'contract.name': {path}")
    if not isinstance(contract.get("version"), str) or not contract["version"].strip():
        raise ValueError(f"Logger sidecar missing required string 'contract.version': {path}")

    streams = obj.get("streams")
    if not isinstance(streams, dict) or not streams:
        raise ValueError(f"Logger sidecar missing required non-empty object 'streams': {path}")

    columns = obj.get("columns")
    if not isinstance(columns, dict) or not columns:
        raise ValueError(f"Logger sidecar missing required non-empty object 'columns': {path}")

    return obj


def _select_primary_stream(sidecar: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    streams = sidecar.get("streams")
    if not isinstance(streams, dict) or not streams:
        raise ValueError("Logger sidecar missing required non-empty object 'streams'")

    if "primary" in streams and isinstance(streams["primary"], dict):
        return "primary", streams["primary"]

    for stream_name, stream_info in streams.items():
        if isinstance(stream_info, dict):
            return str(stream_name), stream_info

    raise ValueError("Logger sidecar does not contain a usable stream definition")


def _sidecar_contract_kind(
    sidecar: dict[str, Any],
    *,
    selected_as_generic: bool = False,
) -> str:
    contract = sidecar.get("contract")
    kind = contract.get("sidecar_kind") if isinstance(contract, dict) else None
    if kind in {"session", "generic"}:
        return str(kind)
    return "generic" if selected_as_generic else "session"


def _expand_generic_sidecar_paths(paths: Optional[Sequence[str | Path]]) -> list[str]:
    if not paths:
        return []

    out: list[str] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for candidate in sorted(p.glob("*.json")):
                try:
                    obj = json.loads(candidate.read_text(encoding="utf-8"))
                except Exception:
                    continue
                contract = obj.get("contract") if isinstance(obj, dict) else None
                if isinstance(contract, dict) and contract.get("sidecar_kind") == "generic":
                    out.append(str(candidate))
        elif p.is_file():
            out.append(str(p))

    # Preserve order while removing duplicates.
    deduped: list[str] = []
    seen: set[str] = set()
    for item in out:
        key = str(Path(item).resolve()).lower()
        if key not in seen:
            deduped.append(item)
            seen.add(key)
    return deduped


def _select_sidecar_path(
    csv_path: str | Path,
    *,
    sidecar_path: Optional[str | Path] = None,
    generic_sidecar_paths: Optional[Sequence[str | Path]] = None,
) -> tuple[Optional[str], bool]:
    if sidecar_path is not None:
        logger.info("Logger sidecar explicitly selected: %s", sidecar_path)
        return str(sidecar_path), False

    same_stem = infer_sidecar_path(str(csv_path))
    if same_stem is not None:
        logger.info("Logger same-stem sidecar found: csv=%s sidecar=%s", csv_path, same_stem)
        logger.info("Logger generic sidecar search skipped because a same-stem sidecar was found")
        return same_stem, False

    expected_same_stem = Path(csv_path).with_suffix(".json")
    logger.info("Logger same-stem sidecar not found: expected=%s", expected_same_stem)

    generic_search_configured = generic_sidecar_paths is not None

    if generic_search_configured:
        logger.info("Logger generic sidecar search path(s): %s", [str(p) for p in generic_sidecar_paths])
    else:
        logger.info("Logger generic sidecar search not configured")

    generic_candidates = _expand_generic_sidecar_paths(generic_sidecar_paths)
    if not generic_candidates:
        if generic_search_configured:
            configured = ", ".join(str(p) for p in generic_sidecar_paths)
            logger.info("Logger generic sidecar search found no usable candidates: %s", configured)
            raise FileNotFoundError(
                "No usable generic sidecar found from configured generic_sidecar_paths: "
                + configured
            )
        logger.info("Logger generic sidecar not found; falling back to legacy header parsing")
        return None, False
    if len(generic_candidates) > 1:
        joined = ", ".join(generic_candidates)
        logger.info("Logger generic sidecar search found multiple candidates: %s", joined)
        raise ValueError(
            "Multiple generic sidecars are available; select one explicitly "
            f"with sidecar_path or pass a single generic_sidecar_paths entry: {joined}"
        )
    logger.info("Logger generic sidecar found: %s", generic_candidates[0])
    return generic_candidates[0], True


def _data_file_header(sidecar: Optional[dict[str, Any]]) -> Optional[bool]:
    if not isinstance(sidecar, dict):
        return None
    data_file = sidecar.get("data_file")
    if not isinstance(data_file, dict):
        return None
    header = data_file.get("header")
    return header if isinstance(header, bool) else None


def _data_file_delimiter(sidecar: Optional[dict[str, Any]]) -> Optional[str]:
    if not isinstance(sidecar, dict):
        return None
    data_file = sidecar.get("data_file")
    if not isinstance(data_file, dict):
        return None
    delim = data_file.get("delimiter")
    return delim if isinstance(delim, str) and len(delim) == 1 else None


def _read_nonempty_lines(path: str | Path) -> list[str]:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return [ln.replace("\0", "").strip() for ln in f if ln.strip()]


def _detect_delimiter(lines: Sequence[str], delimiter: Optional[str]) -> str:
    if isinstance(delimiter, str) and len(delimiter) == 1:
        return delimiter
    sample = "".join(lines[:5])
    return "," if sample.count(",") > sample.count(";") else ";"


def _read_logger_csv_raw(
    path: str | Path,
    *,
    delimiter: Optional[str] = None,
    header: Optional[bool] = None,
) -> pd.DataFrame:
    lines = _read_nonempty_lines(path)
    delim = _detect_delimiter(lines, delimiter)
    read_header = None if header is False else 0
    return pd.read_csv(
        path,
        sep=delim,
        comment="#",
        engine="python",
        on_bad_lines="skip",
        header=read_header,
    )


def _csv_ref_for_column(column_id: str, info: dict[str, Any]) -> dict[str, Any]:
    csv_ref = info.get("csv_ref")
    if isinstance(csv_ref, dict):
        return csv_ref
    # Backward compatibility for the earlier sidecar shape where columns were
    # keyed directly by CSV header.
    return {"by": "header", "header": column_id}


def _resolve_csv_ref(df: pd.DataFrame, csv_ref: dict[str, Any]) -> Any | None:
    by = csv_ref.get("by")
    if by == "header":
        header = csv_ref.get("header")
        return header if header in df.columns else None
    if by == "index":
        idx = csv_ref.get("index")
        if isinstance(idx, int) and 0 <= idx < len(df.columns):
            return df.columns[idx]
    return None


def _canonical_unit(unit: Any) -> Optional[str]:
    if not isinstance(unit, str) or not unit.strip():
        return None
    clean = unit.strip()
    if clean.lower() in {"norm", "normalized", "normalised", "unitless"}:
        return "1"
    return clean


def _safe_signal_token(value: Any, fallback: str) -> str:
    token = normalize_sensor_token(value)
    if token:
        return token
    token = normalize_sensor_token(fallback)
    return token or "signal"


def _analysis_signal_column_name(column_id: str, info: dict[str, Any]) -> str:
    sensor = info.get("sensor")
    sensor_id = canonical_sensor_id(sensor) if isinstance(sensor, str) else ""
    sensor_token = _safe_signal_token(sensor_id, column_id)

    quantity = info.get("quantity")
    quantity_token = normalize_sensor_token(quantity) if isinstance(quantity, str) else ""

    if quantity_token in {"", "disp", "raw"}:
        base = sensor_token
    elif quantity_token in {"vel", "acc"}:
        base = f"{sensor_token}_{quantity_token}"
    else:
        base = f"{sensor_token}_{quantity_token}"

    kind = "raw" if quantity_token == "raw" else ""
    domain = info.get("domain") if isinstance(info.get("domain"), str) and info.get("domain").strip() else None
    unit = _canonical_unit(info.get("unit"))

    try:
        return format_signal_name(
            SignalNameParts(
                base=base,
                kind=kind,
                domain=domain,
                unit=unit,
                ops=(),
            )
        )
    except SignalNameError:
        return column_id


def _analysis_column_name(column_id: str, info: dict[str, Any]) -> str:
    if not isinstance(info.get("csv_ref"), dict):
        return column_id
    if info.get("class") == "signal":
        return _analysis_signal_column_name(column_id, info)
    return column_id


def _is_required_sidecar_column(
    column_id: str,
    info: dict[str, Any],
    *,
    sidecar_kind: str,
    stream_time_columns: set[str],
) -> bool:
    if sidecar_kind == "session":
        return True
    if info.get("class") == "time" or column_id in stream_time_columns:
        return True
    return bool(info.get("required") is True)


def _stream_time_column_ids(sidecar: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    streams = sidecar.get("streams")
    if not isinstance(streams, dict):
        return out
    for stream_info in streams.values():
        if not isinstance(stream_info, dict):
            continue
        time_column = stream_info.get("time_column", stream_info.get("time_col"))
        if isinstance(time_column, str) and time_column.strip():
            out.add(time_column)
    return out


def _bind_sidecar_columns(
    df: pd.DataFrame,
    sidecar: dict[str, Any],
    *,
    sidecar_path: str,
    sidecar_kind: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    columns = sidecar.get("columns")
    if not isinstance(columns, dict):
        raise ValueError(f"Logger sidecar missing required non-empty object 'columns': {sidecar_path}")

    stream_time_columns = _stream_time_column_ids(sidecar)
    resolved: dict[str, dict[str, Any]] = {}
    selected_physical: list[Any] = []
    rename_map: dict[Any, str] = {}
    missing_required: list[str] = []
    missing_optional: list[str] = []
    warnings: list[str] = []

    for column_id_raw, info in columns.items():
        column_id = str(column_id_raw)
        if not isinstance(info, dict):
            continue

        required = _is_required_sidecar_column(
            column_id,
            info,
            sidecar_kind=sidecar_kind,
            stream_time_columns=stream_time_columns,
        )
        csv_ref = _csv_ref_for_column(column_id, info)
        physical = _resolve_csv_ref(df, csv_ref)
        if physical is None:
            if required:
                missing_required.append(column_id)
                logger.info(
                    "Logger sidecar required column missing: sidecar_column_id=%s csv_ref=%s",
                    column_id,
                    csv_ref,
                )
            else:
                missing_optional.append(column_id)
                warnings.append(f"sidecar_optional_column_missing:{column_id}")
                logger.info(
                    "Logger sidecar optional column missing: sidecar_column_id=%s csv_ref=%s",
                    column_id,
                    csv_ref,
                )
            continue

        output = _analysis_column_name(column_id, info)
        resolved[column_id] = {
            "column_id": column_id,
            "class": info.get("class"),
            "required": required,
            "csv_ref": csv_ref,
            "physical_column": physical,
            "physical_column_label": str(physical),
            "dataframe_column": output,
        }
        selected_physical.append(physical)
        rename_map[physical] = output

    if missing_required:
        raise ValueError(
            "Logger sidecar required column(s) not present in CSV: "
            + ", ".join(missing_required)
        )

    if len(selected_physical) != len(set(selected_physical)):
        duplicates = [str(x) for x in selected_physical if selected_physical.count(x) > 1]
        raise ValueError(f"Logger sidecar resolves multiple entries to the same CSV column: {sorted(set(duplicates))}")

    output_names = list(rename_map.values())
    if len(output_names) != len(set(output_names)):
        duplicates = [x for x in output_names if output_names.count(x) > 1]
        raise ValueError(f"Logger sidecar would create duplicate dataframe columns: {sorted(set(duplicates))}")

    resolved_by_physical = {bound["physical_column"]: bound for bound in resolved.values()}
    for physical in df.columns:
        bound = resolved_by_physical.get(physical)
        if isinstance(bound, dict):
            logger.info(
                "Logger CSV column matched sidecar: csv_column=%r sidecar_column_id=%s dataframe_column=%s class=%s",
                str(physical),
                bound.get("column_id"),
                bound.get("dataframe_column"),
                bound.get("class"),
            )
        else:
            action = "error" if sidecar_kind == "session" else "skip"
            logger.info(
                "Logger CSV column has no sidecar match: csv_column=%r sidecar_kind=%s action=%s",
                str(physical),
                sidecar_kind,
                action,
            )

    resolved_physical = set(selected_physical)
    skipped_unknown = [str(c) for c in df.columns if c not in resolved_physical]
    if sidecar_kind == "session" and skipped_unknown:
        raise ValueError(
            "Session sidecar does not describe every CSV column; unknown column(s): "
            + ", ".join(skipped_unknown)
        )

    if sidecar_kind == "generic":
        for col in skipped_unknown:
            warnings.append(f"sidecar_unknown_csv_column_skipped:{col}")

    selected_df = df.loc[:, selected_physical].rename(columns=rename_map, copy=True)
    binding = {
        "sidecar_path": sidecar_path,
        "sidecar_kind": sidecar_kind,
        "columns": resolved,
        "missing_optional_columns": missing_optional,
        "skipped_unknown_columns": skipped_unknown if sidecar_kind == "generic" else [],
        "warnings": warnings,
    }
    return selected_df, binding


def _sidecar_time_hints(sidecar: dict[str, Any]) -> list[dict[str, Any]]:
    binding = sidecar.get(_SIDECAR_BINDING_KEY)
    bindings = binding.get("columns", {}) if isinstance(binding, dict) else {}
    streams = sidecar.get("streams")
    if not isinstance(streams, dict):
        return []

    hints: list[dict[str, Any]] = []
    for stream_name, stream_info in streams.items():
        if not isinstance(stream_info, dict):
            continue
        time_column = stream_info.get("time_column", stream_info.get("time_col"))
        if not isinstance(time_column, str) or not time_column.strip():
            continue
        bound = bindings.get(time_column)
        dataframe_column = bound.get("dataframe_column") if isinstance(bound, dict) else time_column
        unit = stream_info.get("time_unit")
        if unit is None and isinstance(bound, dict):
            info = sidecar.get("columns", {}).get(time_column)
            unit = info.get("unit") if isinstance(info, dict) else None
        hints.append(
            {
                "column": dataframe_column,
                "stream": str(stream_name),
                "encoding": stream_info.get("time_encoding"),
                "unit": unit,
            }
        )
    return hints

# --- Load (robust clock parsing, no float math, per-file offset optional) ---
def parse_clock_column_to_datetime(s: pd.Series) -> pd.Series:
    """
    Parse 'HH:MM:SS.mmm' or 'MM:SS.mmm' (commas or dots) to pandas datetime64[ns]
    on a dummy date, vectorized and without float arithmetic.
    """
    s = s.astype(str).str.strip().str.replace(",", ".", regex=False)

    # Identify 2-part vs 3-part times
    parts = s.str.split(":", n=2, expand=True)
    n_parts = parts.shape[1]

    # Build a normalized 'HH:MM:SS.mmm' string
    if n_parts == 2:
        # MM:SS(.mmm)
        mm = parts[0].str.zfill(2)
        ss = parts[1]
        norm = "00:" + mm + ":" + ss
    elif n_parts == 3:
        # HH:MM:SS(.mmm)
        hh = parts[0].str.zfill(2)
        mm = parts[1].str.zfill(2)
        ss = parts[2]
        norm = hh + ":" + mm + ":" + ss
    else:
        raise ValueError("Unexpected clock format; expected MM:SS(.ms) or HH:MM:SS(.ms)")

    # Ensure milliseconds have at least 3 digits if present
    # e.g. '12:34:56.7' -> '12:34:56.700'
    has_frac = norm.str.contains(r"\.")
    def pad_ms(x: str) -> str:
        if "." not in x: return x
        hms, frac = x.split(".", 1)
        # keep up to microseconds to be safe, pad to 3-6
        frac = (frac + "000000")[:6]
        return hms + "." + frac

    norm = pd.Series(np.where(has_frac, norm.map(pad_ms), norm), index=norm.index)

    # Use a dummy date so we can take accurate timedeltas (no float)
    dt = pd.to_datetime("1970-01-01 " + norm, format="%Y-%m-%d %H:%M:%S.%f", errors="raise")
    return dt

def ensure_time_index(df: pd.DataFrame) -> pd.DataFrame:
    import pandas as pd

    out = df.copy()
    if isinstance(out.index, (pd.DatetimeIndex, pd.TimedeltaIndex)):
        pass
    elif "t" in out.columns:
        out.index = pd.to_timedelta(out["t"].astype(float), unit="s")
        out.index.name = "t"
        out = out.drop(columns=["t"])     # ✅ remove duplicate column
    elif "timestamp" in out.columns:
        dt = pd.to_datetime(out["timestamp"], errors="coerce")
        out = out.loc[dt.notna()]
        out.index = dt
    else:
        raise TypeError("No 't' or 'timestamp' column to build a time index from.")

    # make sure index is clean
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="first")]
    return out

def load_logger_csv(
    path: str,
    *,
    delimiter: Optional[str] = None,
    preferred_time_cols: Optional[Sequence[Any]] = None,
    preferred_time_hints: Optional[Sequence[dict[str, Any]]] = None,
    header: Optional[bool] = None,
) -> pd.DataFrame:
    df = _read_logger_csv_raw(
        path,
        delimiter=delimiter,
        header=header,
    )
    return _canonicalize_loaded_logger_df(
        df,
        preferred_time_cols=preferred_time_cols,
        preferred_time_hints=preferred_time_hints,
    )


def _canonicalize_loaded_logger_df(
    df: pd.DataFrame,
    *,
    preferred_time_cols: Optional[Sequence[Any]] = None,
    preferred_time_hints: Optional[Sequence[dict[str, Any]]] = None,
) -> pd.DataFrame:
    df = df.copy()

    # ---- Canonicalise time to 'time_s' ----
    # Preferred time sources (most stable -> least):
    #  - timestamp_ms (numeric, ms)
    #  - ts_ms / time_ms (numeric, ms)
    #  - time_s / t / time / ts (numeric, seconds-ish; heuristics applied)
    #  - timestamp (clock string "HH:MM:SS.mmm" or "MM:SS.mmm") fallback
    time_s = None
    preferred: list[dict[str, Any]] = []
    if preferred_time_hints is not None:
        preferred.extend([dict(x) for x in preferred_time_hints if isinstance(x, dict)])
    for c in preferred_time_cols or []:
        if c is None:
            continue
        preferred.append({"column": c})
    tried_preferred: set[Any] = set()
    time_source_col: Any | None = None

    def _use_numeric(col: Any, *, scale: Optional[str]) -> None:
        nonlocal df, time_s, time_source_col
        t_num = pd.to_numeric(df[col], errors="coerce")
        mask = t_num.notna()
        if not mask.any():
            return

        df = df.loc[mask].copy()
        t_num = t_num.loc[mask].astype(np.float64)

        if scale == "ms":
            t_sec = t_num * 1e-3
        elif scale == "s":
            t_sec = t_num
        else:
            # Heuristic scale: us / ms / s
            tmax = float(t_num.max()) if len(t_num) else 0.0
            if tmax > 1e12:        # likely microseconds
                t_sec = t_num * 1e-6
            elif tmax > 1e6:       # likely milliseconds (or larger)
                t_sec = t_num * 1e-3
            else:
                t_sec = t_num       # seconds
        time_s = (t_sec - float(t_sec.iloc[0])).to_numpy(dtype=np.float64)
        time_source_col = col

    def _use_clock_string(col: Any) -> None:
        nonlocal df, time_s, time_source_col
        # Use your robust parser (handles MM:SS(.mmm), commas, etc.)
        t_dt = parse_clock_column_to_datetime(df[col])
        mask = t_dt.notna()
        if not mask.any():
            return

        df = df.loc[mask].copy()
        t_dt_f = t_dt.loc[mask]
        # Dummy-date datetime deltas handle midnight rollovers correctly (adds 24h)
        time_s = (t_dt_f - t_dt_f.iloc[0]).dt.total_seconds().to_numpy(dtype=np.float64)
        time_source_col = col

    def _use_preferred(hint: dict[str, Any]) -> None:
        nonlocal time_s
        col = hint.get("column")
        if col not in df.columns or time_s is not None:
            return

        encoding = hint.get("encoding")
        unit = hint.get("unit")
        scale: Optional[str] = None
        if encoding == "epoch_ms" or unit == "ms":
            scale = "ms"
        elif encoding == "elapsed_s" or unit == "s":
            scale = "s"
        elif encoding == "local_time" or unit == "time_of_day":
            _use_clock_string(col)
            return

        series = df[col]
        numeric = pd.to_numeric(series, errors="coerce")
        if numeric.notna().any():
            if scale is None and isinstance(col, str) and col.lower().endswith("_ms"):
                scale = "ms"
            _use_numeric(col, scale=scale)
            return

        _use_clock_string(col)

    if time_s is None:
        for hint in preferred:
            tried_preferred.add(hint.get("column"))
            _use_preferred(hint)
            if time_s is not None:
                break

    # 1) Strong preference: explicit ms column from logger
    if time_s is None and "timestamp_ms" in df.columns and "timestamp_ms" not in tried_preferred:
        _use_numeric("timestamp_ms", scale="ms")

    # 2) Next: other common numeric ms columns
    if time_s is None:
        for cand in ("ts_ms", "time_ms"):
            if cand in df.columns and cand not in tried_preferred:
                _use_numeric(cand, scale="ms")
                if time_s is not None:
                    break

    # 3) Next: other numeric time columns (seconds-ish)
    if time_s is None:
        for cand in ("time_s", "t", "time", "ts"):
            if cand in df.columns and cand not in tried_preferred:
                _use_numeric(cand, scale=None)
                if time_s is not None:
                    break

    # 4) Fallback: human-readable timestamp
    if time_s is None and "timestamp" in df.columns and "timestamp" not in tried_preferred:
        _use_clock_string("timestamp")

        # If that failed, last-resort: treat timestamp as numeric
        if time_s is None:
            _use_numeric("timestamp", scale=None)

    if time_s is None:
        raise ValueError(
            "No usable time column found (expected 'timestamp_ms', 'timestamp', or a numeric time column)."
        )

    df["time_s"] = np.asarray(time_s, dtype=np.float64)

    # ---- Clean numeric columns (leave timestamp as-is) ----
    for c in df.columns:
        if c in ("timestamp", "timestamp_ms") or c == time_source_col:
            continue
        df[c] = (
            df[c]
            .astype(str)
            .str.replace(r"[^0-9eE+\-\.]", "", regex=True)
            .replace("", np.nan)
            .astype(float)
        )

    # Drop NaNs and deduplicate by canonical time
    df = df.dropna().drop_duplicates(subset="time_s", keep="first").reset_index(drop=True)
    df = df[df["time_s"].diff().fillna(0) > 0]  # keep monotonic time

    return df


def load_logger_csv_with_sidecar(
    path: str,
    *,
    sidecar_path: Optional[str] = None,
    generic_sidecar_paths: Optional[Sequence[str | Path]] = None,
) -> tuple[pd.DataFrame, Optional[dict[str, Any]], Optional[str]]:
    """
    Load a logger CSV and, when available, a same-stem, explicitly supplied,
    or single generic fallback JSON sidecar that can provide CSV binding,
    delimiter/time-column hints, and session metadata.
    """
    resolved_sidecar, selected_as_generic = _select_sidecar_path(
        path,
        sidecar_path=sidecar_path,
        generic_sidecar_paths=generic_sidecar_paths,
    )
    sidecar: Optional[dict[str, Any]] = None
    preferred_time_hints: list[dict[str, Any]] = []

    if resolved_sidecar is not None:
        sidecar = load_logger_sidecar(resolved_sidecar)
        sidecar_kind = _sidecar_contract_kind(sidecar, selected_as_generic=selected_as_generic)
        logger.info(
            "Logger sidecar loaded: path=%s sidecar_kind=%s selected_as_generic=%s",
            resolved_sidecar,
            sidecar_kind,
            selected_as_generic,
        )
        raw_df = _read_logger_csv_raw(
            path,
            delimiter=_data_file_delimiter(sidecar),
            header=_data_file_header(sidecar),
        )
        bound_df, binding = _bind_sidecar_columns(
            raw_df,
            sidecar,
            sidecar_path=str(resolved_sidecar),
            sidecar_kind=sidecar_kind,
        )
        sidecar[_SIDECAR_BINDING_KEY] = binding
        preferred_time_hints = _sidecar_time_hints(sidecar)
        df = _canonicalize_loaded_logger_df(
            bound_df,
            preferred_time_hints=preferred_time_hints,
        )
    else:
        df = load_logger_csv(
            path,
            delimiter=None,
            preferred_time_cols=None,
            header=None,
        )

    return df, sidecar, resolved_sidecar


# --- Footer stats parsing (logger-provided QC) ---
_RUN_STATS_BEGIN_RE = re.compile(r"^\s*#\s*run_stats_begin\s*$", re.IGNORECASE)
_RUN_STATS_END_RE   = re.compile(r"^\s*#\s*run_stats_end\s*$", re.IGNORECASE)
_KV_RE = re.compile(r"^\s*#\s*([A-Za-z0-9_\-]+)\s*=\s*(.*?)\s*$")

def parse_run_stats_footer(path: str) -> dict:
    """Parse optional end-of-file run stats emitted by the logger.

    Expected format (example):
        # run_stats_begin
        # samples_dropped=0
        # flush_count=5
        # run_stats_end

    Returns a dict of parsed key/value pairs. Values are converted to int/float where sensible.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception:
        return {}

    # search near end for markers
    start_idx = None
    end_idx = None
    for i in range(len(lines)-1, max(-1, len(lines)-300), -1):
        ln = lines[i].rstrip("\n")
        if end_idx is None and _RUN_STATS_END_RE.match(ln):
            end_idx = i
            continue
        if end_idx is not None and _RUN_STATS_BEGIN_RE.match(ln):
            start_idx = i
            break

    if start_idx is None or end_idx is None or end_idx <= start_idx:
        return {}

    stats: dict = {}
    for ln in lines[start_idx+1:end_idx]:
        m = _KV_RE.match(ln)
        if not m:
            continue
        key = m.group(1)
        val = m.group(2)
        # coerce basic numeric types
        if re.fullmatch(r"[-+]?\d+", val or ""):
            try: stats[key] = int(val)
            except Exception: stats[key] = val
        elif re.fullmatch(r"[-+]?\d*\.\d+(?:[eE][-+]?\d+)?", val or "") or re.fullmatch(r"[-+]?\d+\.\d*(?:[eE][-+]?\d+)?", val or ""):
            try: stats[key] = float(val)
            except Exception: stats[key] = val
        else:
            stats[key] = val
    return stats
