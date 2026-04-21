from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence

import pandas as pd

FIT_DEFAULT_FIELDS: tuple[str, ...] = (
    "position_lat",
    "position_long",
    "altitude",
    "enhanced_altitude",
    "speed",
    "enhanced_speed",
    "distance",
    "grade",
    "heading",
)

_SEMICIRCLES_TO_DEGREES = 180.0 / (2 ** 31)


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _coerce_timestamp(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _canonical_fit_field_name(field_name: str) -> str:
    return str(field_name).strip().lower()


def _format_generic_fit_column(field_name: str, unit: Optional[str]) -> str:
    base = f"gps_fit_{_canonical_fit_field_name(field_name)}_dom_world"
    unit_text = (unit or "").strip()
    return f"{base} [{unit_text}]" if unit_text else base


def _convert_semicircles_to_degrees(value: Any) -> Any:
    if value is None:
        return None
    try:
        return float(value) * _SEMICIRCLES_TO_DEGREES
    except Exception:
        return None


_FIELD_SPECS: Dict[str, Dict[str, Any]] = {
    "position_lat": {
        "column": "gps_fit_position_latitude_dom_world [deg]",
        "unit": "deg",
        "converter": _convert_semicircles_to_degrees,
        "sensor": "gps_fit",
        "role": "position_latitude",
    },
    "position_long": {
        "column": "gps_fit_position_longitude_dom_world [deg]",
        "unit": "deg",
        "converter": _convert_semicircles_to_degrees,
        "sensor": "gps_fit",
        "role": "position_longitude",
    },
    "altitude": {
        "column": "gps_fit_altitude_dom_world [m]",
        "unit": "m",
        "converter": float,
        "sensor": "gps_fit",
        "role": "altitude",
    },
    "enhanced_altitude": {
        "column": "gps_fit_enhanced_altitude_dom_world [m]",
        "unit": "m",
        "converter": float,
        "sensor": "gps_fit",
        "role": "altitude",
    },
    "speed": {
        "column": "gps_fit_speed_dom_world [m/s]",
        "unit": "m/s",
        "converter": float,
        "sensor": "gps_fit",
        "role": "speed",
    },
    "enhanced_speed": {
        "column": "gps_fit_enhanced_speed_dom_world [m/s]",
        "unit": "m/s",
        "converter": float,
        "sensor": "gps_fit",
        "role": "speed",
    },
    "distance": {
        "column": "gps_fit_distance_dom_world [m]",
        "unit": "m",
        "converter": float,
        "sensor": "gps_fit",
        "role": "distance",
    },
    "grade": {
        "column": "gps_fit_grade_dom_world [%]",
        "unit": "%",
        "converter": float,
        "sensor": "gps_fit",
        "role": "grade",
    },
    "heading": {
        "column": "gps_fit_heading_dom_world [deg]",
        "unit": "deg",
        "converter": float,
        "sensor": "gps_fit",
        "role": "heading",
    },
}


def _get_fitfile_class():
    try:
        from fitparse import FitFile
    except ImportError as exc:
        raise ImportError(
            "FIT parsing requires the optional 'fitparse' package. "
            "Install it to enable Garmin FIT import."
        ) from exc
    return FitFile


def _iter_fit_record_rows(path: str | Path) -> tuple[list[dict[str, Any]], dict[str, Optional[str]]]:
    FitFile = _get_fitfile_class()
    fit_file = FitFile(str(path))
    rows: list[dict[str, Any]] = []
    field_units: dict[str, Optional[str]] = {}

    for message in fit_file.get_messages("record"):
        row: dict[str, Any] = {}
        for field in message:
            name = _canonical_fit_field_name(field.name)
            row[name] = field.value
            if name not in field_units:
                unit = getattr(field, "units", None)
                field_units[name] = str(unit) if unit is not None else None
        if "timestamp" in row:
            rows.append(row)

    return rows, field_units


def _convert_fit_value(
    field_name: str,
    value: Any,
    *,
    units: Optional[str],
) -> Any:
    spec = _FIELD_SPECS.get(field_name)
    if spec is not None:
        converter: Callable[[Any], Any] = spec["converter"]
        try:
            return converter(value)
        except Exception:
            return None

    if value is None:
        return None

    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    return None


def _canonical_column_for_field(field_name: str, *, units: Optional[str]) -> tuple[str, Optional[str], Optional[str]]:
    spec = _FIELD_SPECS.get(field_name)
    if spec is not None:
        return str(spec["column"]), spec.get("sensor"), spec.get("role")
    clean_unit = (units or "").strip()
    return _format_generic_fit_column(field_name, clean_unit or None), "gps_fit", field_name


def inspect_fit_file(
    path: str | Path,
    *,
    field_allowlist: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    rows, field_units = _iter_fit_record_rows(path)
    if not rows:
        raise ValueError(f"FIT file does not contain any usable record timestamps: {path}")

    allowed = {
        _canonical_fit_field_name(x)
        for x in (field_allowlist if field_allowlist is not None else FIT_DEFAULT_FIELDS)
        if isinstance(x, str) and x.strip()
    }

    timestamps = [_coerce_timestamp(row["timestamp"]) for row in rows if row.get("timestamp") is not None]
    if not timestamps:
        raise ValueError(f"FIT file does not contain any usable record timestamps: {path}")

    available_fields = sorted(
        {
            field_name
            for row in rows
            for field_name in row.keys()
            if field_name != "timestamp" and (not allowed or field_name in allowed)
        }
    )

    p = Path(path)
    return {
        "path": str(p),
        "filename": p.name,
        "start_datetime": timestamps[0].isoformat(),
        "end_datetime": timestamps[-1].isoformat(),
        "available_fields": available_fields,
        "field_units": {k: v for k, v in field_units.items() if k in available_fields},
    }


def find_overlapping_fit_files(
    *,
    fit_dir: str | Path,
    session_start_datetime: str,
    session_end_datetime: str,
    field_allowlist: Optional[Sequence[str]] = None,
    partial_overlap: str = "allow",
) -> list[dict[str, Any]]:
    root = Path(fit_dir)
    if not root.exists():
        return []

    session_start = _coerce_timestamp(session_start_datetime)
    session_end = _coerce_timestamp(session_end_datetime)
    if session_end < session_start:
        raise ValueError("session_end_datetime must be >= session_start_datetime")

    candidates: list[dict[str, Any]] = []

    for path in sorted(root.glob("*.fit")) + sorted(root.glob("*.FIT")):
        summary = inspect_fit_file(path, field_allowlist=field_allowlist)
        fit_start = _coerce_timestamp(summary["start_datetime"])
        fit_end = _coerce_timestamp(summary["end_datetime"])

        overlap_start = max(session_start, fit_start)
        overlap_end = min(session_end, fit_end)
        overlap_s = max(0.0, (overlap_end - overlap_start).total_seconds())

        if partial_overlap == "reject":
            is_match = fit_start <= session_start and fit_end >= session_end
        else:
            is_match = overlap_s > 0.0 or (session_start == session_end and fit_start <= session_start <= fit_end)

        if not is_match:
            continue

        summary["fit_start_datetime"] = summary.pop("start_datetime")
        summary["fit_end_datetime"] = summary.pop("end_datetime")
        summary["overlap_start_datetime"] = overlap_start.isoformat()
        summary["overlap_end_datetime"] = overlap_end.isoformat()
        summary["overlap_s"] = overlap_s
        candidates.append(summary)

    return candidates


def load_fit_bindings(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []

    obj = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(obj, dict):
        bindings = obj.get("bindings")
        if isinstance(bindings, list):
            return [x for x in bindings if isinstance(x, dict)]
        raise ValueError(f"FIT bindings file must contain a 'bindings' list: {path}")
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    raise ValueError(f"FIT bindings file must be a JSON object or list: {path}")


def write_fit_bindings(path: str | Path, bindings: Sequence[Mapping[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "bodaqs.fit_bindings",
        "version": 1,
        "bindings": [dict(x) for x in bindings if isinstance(x, Mapping)],
    }
    p.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def upsert_fit_binding(
    path: str | Path,
    *,
    session_id: Optional[str],
    csv_path: Optional[str],
    csv_sha256: Optional[str],
    fit_file: str,
    fit_sha256: Optional[str] = None,
    selected_by: str = "user",
    selected_at: Optional[str] = None,
) -> dict[str, Any]:
    bindings = load_fit_bindings(path) if Path(path).exists() else []
    replacement = {
        "session_id": session_id,
        "csv_path": csv_path,
        "csv_sha256": csv_sha256,
        "fit_file": fit_file,
        "fit_sha256": fit_sha256,
        "selected_by": selected_by,
        "selected_at": selected_at,
    }

    kept: list[dict[str, Any]] = []
    replaced = False
    for entry in bindings:
        if _binding_matches_session(
            entry,
            session_id=session_id,
            csv_path=csv_path,
            csv_sha256=csv_sha256,
        ):
            if not replaced:
                kept.append(replacement)
                replaced = True
            continue
        kept.append(entry)

    if not replaced:
        kept.append(replacement)

    write_fit_bindings(path, kept)
    return replacement


def _paths_match(lhs: str | Path | None, rhs: str | Path | None) -> bool:
    if lhs is None or rhs is None:
        return False
    left = Path(str(lhs))
    right = Path(str(rhs))
    if left.name and right.name and left.name == right.name:
        return True
    try:
        return left.resolve() == right.resolve()
    except Exception:
        return str(left).replace("\\", "/") == str(right).replace("\\", "/")


def _binding_matches_session(
    entry: dict[str, Any],
    *,
    session_id: Optional[str],
    csv_path: Optional[str],
    csv_sha256: Optional[str],
) -> bool:
    matched_any = False

    if isinstance(entry.get("session_id"), str):
        matched_any = True
        if session_id != entry["session_id"]:
            return False

    if isinstance(entry.get("csv_path"), str):
        matched_any = True
        if not _paths_match(entry["csv_path"], csv_path):
            return False

    if isinstance(entry.get("csv_sha256"), str):
        matched_any = True
        if csv_sha256 != entry["csv_sha256"]:
            return False

    return matched_any


def select_fit_candidate(
    *,
    session_id: Optional[str],
    csv_path: Optional[str],
    csv_sha256: Optional[str],
    candidates: Sequence[dict[str, Any]],
    ambiguity_policy: str = "require_binding",
    bindings_path: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    items = [dict(x) for x in candidates if isinstance(x, dict)]
    if not items:
        return None
    if len(items) == 1:
        return items[0]

    if ambiguity_policy == "latest_start":
        return max(items, key=lambda x: x.get("fit_start_datetime", ""))
    if ambiguity_policy == "largest_overlap":
        return max(items, key=lambda x: float(x.get("overlap_s", 0.0)))

    if ambiguity_policy != "require_binding":
        raise ValueError(f"Unsupported FIT ambiguity_policy: {ambiguity_policy}")

    if not bindings_path:
        names = ", ".join(sorted(str(x.get("filename", x.get("path"))) for x in items))
        raise ValueError(
            "Multiple overlapping FIT files were found but no bindings file was provided. "
            f"Candidates: {names}"
        )

    bindings = load_fit_bindings(bindings_path)
    matching_bindings = [
        entry
        for entry in bindings
        if _binding_matches_session(
            entry,
            session_id=session_id,
            csv_path=csv_path,
            csv_sha256=csv_sha256,
        )
    ]
    if not matching_bindings:
        names = ", ".join(sorted(str(x.get("filename", x.get("path"))) for x in items))
        raise ValueError(
            "Multiple overlapping FIT files were found and no matching binding exists. "
            f"Candidates: {names}"
        )
    if len(matching_bindings) > 1:
        raise ValueError("Multiple FIT bindings matched the same session; resolve the ambiguity in the bindings file.")

    binding = matching_bindings[0]
    fit_file = binding.get("fit_file")
    fit_sha256 = binding.get("fit_sha256")

    for candidate in items:
        if isinstance(fit_file, str) and _paths_match(candidate.get("path"), fit_file):
            return candidate
        if isinstance(fit_sha256, str):
            sha = candidate.get("fit_sha256")
            if not isinstance(sha, str):
                sha = _sha256_file(Path(candidate["path"]))
                candidate["fit_sha256"] = sha
            if sha == fit_sha256:
                return candidate

    raise ValueError("A FIT binding was found, but it does not resolve to any overlapping candidate FIT file.")


def load_fit_stream(
    fit_path: str | Path,
    *,
    session_start_datetime: str,
    field_allowlist: Optional[Sequence[str]] = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows, field_units = _iter_fit_record_rows(fit_path)
    if not rows:
        raise ValueError(f"FIT file does not contain any usable record messages: {fit_path}")

    allowed = {
        _canonical_fit_field_name(x)
        for x in (field_allowlist if field_allowlist is not None else FIT_DEFAULT_FIELDS)
        if isinstance(x, str) and x.strip()
    }

    session_start = _coerce_timestamp(session_start_datetime)
    timestamps = [_coerce_timestamp(row["timestamp"]) for row in rows]

    out_rows: list[dict[str, Any]] = []
    resample_columns: list[str] = []
    channel_info: dict[str, dict[str, Any]] = {}

    for row, ts in zip(rows, timestamps):
        out: dict[str, Any] = {
            "timestamp": ts,
            "time_s": float((ts - session_start).total_seconds()),
        }
        for field_name, value in row.items():
            if field_name == "timestamp":
                continue
            if allowed and field_name not in allowed:
                continue

            units = field_units.get(field_name)
            converted = _convert_fit_value(field_name, value, units=units)
            if converted is None:
                continue

            column_name, sensor, role = _canonical_column_for_field(field_name, units=units)
            out[column_name] = converted
            if column_name not in resample_columns:
                resample_columns.append(column_name)
            channel_info[column_name] = {
                "unit": _FIELD_SPECS.get(field_name, {}).get("unit", (units or None)),
                "sensor": sensor,
                "role": role,
                "source_columns": [field_name],
            }
        out_rows.append(out)

    df = pd.DataFrame(out_rows)
    if df.empty:
        raise ValueError(f"FIT file did not yield any allowed numeric fields: {fit_path}")

    df = df.sort_values("time_s", kind="stable").reset_index(drop=True)
    df = df.loc[~df["time_s"].duplicated(keep="first")].reset_index(drop=True)

    p = Path(fit_path)
    meta: dict[str, Any] = {
        "path": str(p),
        "filename": p.name,
        "fit_sha256": _sha256_file(p),
        "stream_name": "gps_fit",
        "kind": "intermittent",
        "time_col": "time_s",
        "timestamp_col": "timestamp",
        "fit_start_datetime": timestamps[0].isoformat(),
        "fit_end_datetime": timestamps[-1].isoformat(),
        "available_fields": sorted(
            {
                field_name
                for row in rows
                for field_name in row.keys()
                if field_name != "timestamp"
            }
        ),
        "loaded_fields": sorted(
            {
                field_name
                for row in rows
                for field_name in row.keys()
                if field_name != "timestamp" and ((not allowed) or field_name in allowed)
            }
        ),
        "field_units": dict(field_units),
        "resample_columns": list(resample_columns),
        "channel_info": channel_info,
    }
    return df, meta
