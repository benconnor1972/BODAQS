from __future__ import annotations

import hashlib
import io
import json
import os
from datetime import datetime, timezone
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

FIT_INSPECTION_INDEX_SCHEMA = "bodaqs.fit_inspection_index"
FIT_INSPECTION_INDEX_VERSION = 1
FIT_INSPECTION_PARSER_VERSION = 1
FIT_INSPECTION_INDEX_RELATIVE_PATH = Path(".bodaqs") / "fit_index_v1.json"

_SEMICIRCLES_TO_DEGREES = 180.0 / (2 ** 31)


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _iter_fit_record_rows_from_fileish(fileish: Any) -> tuple[list[dict[str, Any]], dict[str, Optional[str]]]:
    FitFile = _get_fitfile_class()
    fit_file = FitFile(fileish)
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


def _iter_fit_record_rows(path: str | Path) -> tuple[list[dict[str, Any]], dict[str, Optional[str]]]:
    return _iter_fit_record_rows_from_fileish(str(path))


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
        "record_count": len(rows),
        "available_fields": available_fields,
        "field_units": {k: v for k, v in field_units.items() if k in available_fields},
    }


def _fit_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()
    for path in sorted(root.glob("*.fit")) + sorted(root.glob("*.FIT")):
        try:
            key = str(path.resolve()).lower()
        except Exception:
            key = str(path).replace("\\", "/").lower()
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        paths.append(path)
    return paths


def _read_fit_inspection_index(path: Path) -> tuple[dict[str, Any], bool]:
    empty = {
        "schema": FIT_INSPECTION_INDEX_SCHEMA,
        "version": FIT_INSPECTION_INDEX_VERSION,
        "parser_version": FIT_INSPECTION_PARSER_VERSION,
        "updated_at": _utcnow_iso(),
        "entries": {},
    }
    if not path.exists():
        return empty, False
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return empty, False
    if not isinstance(obj, dict):
        return empty, False
    if obj.get("schema") != FIT_INSPECTION_INDEX_SCHEMA:
        return empty, False
    if int(obj.get("version", -1)) != FIT_INSPECTION_INDEX_VERSION:
        return empty, False
    if int(obj.get("parser_version", -1)) != FIT_INSPECTION_PARSER_VERSION:
        return empty, False
    if not isinstance(obj.get("entries"), dict):
        return empty, False
    return obj, True


def _write_fit_inspection_index(path: Path, index: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(
        json.dumps(dict(index), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(tmp_path, path)


def refresh_fit_inspection_index(
    fit_dir: str | Path,
    *,
    index_path: Optional[str | Path] = None,
) -> dict[str, Any]:
    """
    Refresh a rebuildable, profile-independent index of FIT file boundaries.

    The index stores relative paths and complete field inventories. Callers
    apply their current field allowlist only when loading the selected stream.
    """
    root = Path(fit_dir).expanduser().resolve()
    resolved_index_path = (
        Path(index_path).expanduser().resolve()
        if index_path is not None
        else root / FIT_INSPECTION_INDEX_RELATIVE_PATH
    )
    if not root.exists():
        return {
            "index_path": str(resolved_index_path),
            "candidates": [],
            "stats": {
                "files_seen": 0,
                "unchanged": 0,
                "inspected": 0,
                "failed": 0,
                "removed": 0,
                "rebuilt": False,
            },
        }

    index, valid_index = _read_fit_inspection_index(resolved_index_path)
    old_entries = index.get("entries", {})
    entries: dict[str, Any] = {}
    candidates: list[dict[str, Any]] = []
    stats = {
        "files_seen": 0,
        "unchanged": 0,
        "inspected": 0,
        "failed": 0,
        "removed": 0,
        "rebuilt": not valid_index,
    }
    changed = not valid_index

    for path in _fit_paths(root):
        stats["files_seen"] += 1
        relative_path = path.relative_to(root).as_posix()
        stat_before = path.stat()
        fingerprint = {
            "size": int(stat_before.st_size),
            "mtime_ns": int(stat_before.st_mtime_ns),
        }
        existing = old_entries.get(relative_path)
        if (
            isinstance(existing, Mapping)
            and existing.get("fingerprint") == fingerprint
            and str(existing.get("status") or "") in {"ready", "failed"}
        ):
            entry = dict(existing)
            stats["unchanged"] += 1
            if str(entry.get("status") or "") == "failed":
                stats["failed"] += 1
        else:
            changed = True
            try:
                # An empty allowlist intentionally records every available FIT
                # field so profile changes do not invalidate the index.
                summary = inspect_fit_file(path, field_allowlist=())
                stat_after = path.stat()
                if (
                    stat_after.st_size != stat_before.st_size
                    or stat_after.st_mtime_ns != stat_before.st_mtime_ns
                ):
                    raise RuntimeError("FIT file changed while it was being inspected")
                summary = dict(summary)
                summary.pop("path", None)
                entry = {
                    "status": "ready",
                    "relative_path": relative_path,
                    "fingerprint": fingerprint,
                    "fit_sha256": _sha256_file(path),
                    "inspected_at": _utcnow_iso(),
                    "summary": summary,
                }
                stats["inspected"] += 1
            except Exception as exc:
                entry = {
                    "status": "failed",
                    "relative_path": relative_path,
                    "fingerprint": fingerprint,
                    "inspected_at": _utcnow_iso(),
                    "error": f"{type(exc).__name__}: {exc}",
                }
                stats["failed"] += 1
        entries[relative_path] = entry

        if str(entry.get("status") or "") == "ready":
            summary = entry.get("summary")
            if isinstance(summary, Mapping):
                candidate = dict(summary)
                candidate["path"] = str(path.resolve())
                candidate["filename"] = path.name
                candidate["fit_sha256"] = entry.get("fit_sha256")
                candidate["fit_fingerprint"] = dict(fingerprint)
                candidates.append(candidate)

    removed = set(old_entries) - set(entries)
    stats["removed"] = len(removed)
    if removed:
        changed = True

    if changed:
        index = {
            "schema": FIT_INSPECTION_INDEX_SCHEMA,
            "version": FIT_INSPECTION_INDEX_VERSION,
            "parser_version": FIT_INSPECTION_PARSER_VERSION,
            "updated_at": _utcnow_iso(),
            "entries": entries,
        }
        _write_fit_inspection_index(resolved_index_path, index)

    return {
        "index_path": str(resolved_index_path),
        "candidates": candidates,
        "stats": stats,
    }


def inspect_fit_stream(
    fit_input: str | Path | bytes | bytearray | memoryview,
    *,
    field_allowlist: Optional[Sequence[str]] = None,
    source_name: Optional[str] = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]]
    field_units: dict[str, Optional[str]]
    fit_sha256: Optional[str] = None
    path_text: Optional[str] = None
    filename: Optional[str] = None

    if isinstance(fit_input, Path):
        rows, field_units = _iter_fit_record_rows(fit_input)
        fit_sha256 = _sha256_file(fit_input)
        path_text = str(fit_input)
        filename = fit_input.name
    elif isinstance(fit_input, str):
        path = Path(fit_input)
        rows, field_units = _iter_fit_record_rows(path)
        fit_sha256 = _sha256_file(path)
        path_text = str(path)
        filename = path.name
    elif isinstance(fit_input, (bytes, bytearray, memoryview)):
        fit_bytes = bytes(fit_input)
        rows, field_units = _iter_fit_record_rows_from_fileish(io.BytesIO(fit_bytes))
        fit_sha256 = _sha256_bytes(fit_bytes)
        if isinstance(source_name, str) and source_name.strip():
            filename = Path(source_name).name
    else:
        raise TypeError("FIT input must be provided as a path or bytes-like object")

    if not rows:
        raise ValueError("FIT input does not contain any usable record timestamps")

    allowed = {
        _canonical_fit_field_name(x)
        for x in (field_allowlist if field_allowlist is not None else FIT_DEFAULT_FIELDS)
        if isinstance(x, str) and x.strip()
    }

    timestamps = [_coerce_timestamp(row["timestamp"]) for row in rows if row.get("timestamp") is not None]
    if not timestamps:
        raise ValueError("FIT input does not contain any usable record timestamps")

    available_fields = sorted(
        {
            field_name
            for row in rows
            for field_name in row.keys()
            if field_name != "timestamp" and (not allowed or field_name in allowed)
        }
    )

    summary = {
        "start_datetime": timestamps[0].isoformat(),
        "end_datetime": timestamps[-1].isoformat(),
        "available_fields": available_fields,
        "field_units": {k: v for k, v in field_units.items() if k in available_fields},
        "fit_sha256": fit_sha256,
    }
    if path_text is not None:
        summary["path"] = path_text
    if filename is not None:
        summary["filename"] = filename
    return summary


def find_overlapping_fit_candidates(
    candidates: Sequence[Mapping[str, Any]],
    *,
    session_start_datetime: str,
    session_end_datetime: str,
    partial_overlap: str = "allow",
) -> list[dict[str, Any]]:
    session_start = _coerce_timestamp(session_start_datetime)
    session_end = _coerce_timestamp(session_end_datetime)
    if session_end < session_start:
        raise ValueError("session_end_datetime must be >= session_start_datetime")

    overlaps: list[dict[str, Any]] = []
    for raw in candidates:
        if not isinstance(raw, Mapping):
            continue
        summary = dict(raw)
        start_value = summary.get("fit_start_datetime", summary.get("start_datetime"))
        end_value = summary.get("fit_end_datetime", summary.get("end_datetime"))
        if start_value is None or end_value is None:
            continue

        fit_start = _coerce_timestamp(start_value)
        fit_end = _coerce_timestamp(end_value)
        overlap_start = max(session_start, fit_start)
        overlap_end = min(session_end, fit_end)
        overlap_s = max(0.0, (overlap_end - overlap_start).total_seconds())

        if partial_overlap == "reject":
            is_match = fit_start <= session_start and fit_end >= session_end
        else:
            is_match = overlap_s > 0.0 or (session_start == session_end and fit_start <= session_start <= fit_end)

        if not is_match:
            continue

        summary["fit_start_datetime"] = fit_start.isoformat()
        summary["fit_end_datetime"] = fit_end.isoformat()
        summary["overlap_start_datetime"] = overlap_start.isoformat()
        summary["overlap_end_datetime"] = overlap_end.isoformat()
        summary["overlap_s"] = overlap_s
        overlaps.append(summary)

    return overlaps


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
    fit_paths: list[Path] = []
    seen_paths: set[str] = set()

    for path in sorted(root.glob("*.fit")) + sorted(root.glob("*.FIT")):
        try:
            key = str(path.resolve()).lower()
        except Exception:
            key = str(path).replace("\\", "/").lower()
        if key in seen_paths:
            continue
        seen_paths.add(key)
        fit_paths.append(path)

    summaries: list[dict[str, Any]] = []
    for path in fit_paths:
        summaries.append(inspect_fit_file(path, field_allowlist=field_allowlist))

    return find_overlapping_fit_candidates(
        summaries,
        session_start_datetime=session_start_datetime,
        session_end_datetime=session_end_datetime,
        partial_overlap=partial_overlap,
    )


def parse_fit_bindings(value: Mapping[str, Any] | Sequence[Mapping[str, Any]] | str | bytes | Path) -> list[dict[str, Any]]:
    if isinstance(value, Path):
        if not value.exists():
            return []
        obj = json.loads(value.read_text(encoding="utf-8"))
    elif isinstance(value, bytes):
        obj = json.loads(value.decode("utf-8"))
    elif isinstance(value, str):
        obj = json.loads(value)
    elif isinstance(value, Mapping):
        obj = dict(value)
    elif isinstance(value, Sequence):
        return [dict(x) for x in value if isinstance(x, Mapping)]
    else:
        raise TypeError("FIT bindings must be provided as a mapping, list, JSON text/bytes, or Path")

    if isinstance(obj, dict):
        bindings = obj.get("bindings")
        if isinstance(bindings, list):
            return [dict(x) for x in bindings if isinstance(x, Mapping)]
        raise ValueError("FIT bindings payload must contain a 'bindings' list")
    if isinstance(obj, list):
        return [dict(x) for x in obj if isinstance(x, Mapping)]
    raise ValueError("FIT bindings payload must be a JSON object or list")


def load_fit_bindings(path: str | Path) -> list[dict[str, Any]]:
    return parse_fit_bindings(Path(path))


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
    kept, replacement = upsert_fit_binding_records(
        bindings,
        session_id=session_id,
        csv_path=csv_path,
        csv_sha256=csv_sha256,
        fit_file=fit_file,
        fit_sha256=fit_sha256,
        selected_by=selected_by,
        selected_at=selected_at,
    )
    write_fit_bindings(path, kept)
    return replacement


def upsert_fit_binding_records(
    bindings: Sequence[Mapping[str, Any]],
    *,
    session_id: Optional[str],
    csv_path: Optional[str],
    csv_sha256: Optional[str],
    fit_file: str,
    fit_sha256: Optional[str] = None,
    selected_by: str = "user",
    selected_at: Optional[str] = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
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
        if not isinstance(entry, Mapping):
            continue
        if _binding_matches_session(
            dict(entry),
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

    return kept, replacement


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
    bindings: Optional[Sequence[Mapping[str, Any]] | Mapping[str, Any] | str | bytes | Path] = None,
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

    if bindings is not None and bindings_path is not None:
        raise ValueError("Use either bindings or bindings_path, not both")

    if bindings is None and not bindings_path:
        names = ", ".join(sorted(str(x.get("filename", x.get("path"))) for x in items))
        raise ValueError(
            "Multiple overlapping FIT files were found but no bindings file was provided. "
            f"Candidates: {names}"
        )

    resolved_bindings = parse_fit_bindings(bindings) if bindings is not None else load_fit_bindings(bindings_path)
    matching_bindings = [
        entry
        for entry in resolved_bindings
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
        candidate_path = candidate.get("path")
        candidate_filename = candidate.get("filename")
        if isinstance(fit_file, str) and (
            _paths_match(candidate_path, fit_file)
            or (isinstance(candidate_filename, str) and Path(candidate_filename).name == Path(fit_file).name)
        ):
            return candidate
        if isinstance(fit_sha256, str):
            sha = candidate.get("fit_sha256")
            if not isinstance(sha, str) and isinstance(candidate.get("path"), str):
                sha = _sha256_file(Path(candidate["path"]))
                candidate["fit_sha256"] = sha
            if sha == fit_sha256:
                return candidate

    raise ValueError("A FIT binding was found, but it does not resolve to any overlapping candidate FIT file.")


def parse_fit_stream_absolute(
    fit_input: str | Path | bytes | bytearray | memoryview,
    *,
    field_allowlist: Optional[Sequence[str]] = None,
    source_name: Optional[str] = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Parse a FIT stream once while retaining its absolute UTC timebase."""
    source_path: Optional[Path] = None
    fit_sha256: Optional[str] = None
    filename: Optional[str] = None

    if isinstance(fit_input, Path):
        source_path = fit_input
        rows, field_units = _iter_fit_record_rows(source_path)
        fit_sha256 = _sha256_file(source_path)
        filename = source_path.name
    elif isinstance(fit_input, str):
        source_path = Path(fit_input)
        rows, field_units = _iter_fit_record_rows(source_path)
        fit_sha256 = _sha256_file(source_path)
        filename = source_path.name
    elif isinstance(fit_input, (bytes, bytearray, memoryview)):
        fit_bytes = bytes(fit_input)
        rows, field_units = _iter_fit_record_rows_from_fileish(io.BytesIO(fit_bytes))
        fit_sha256 = _sha256_bytes(fit_bytes)
        if isinstance(source_name, str) and source_name.strip():
            filename = Path(source_name).name
    else:
        raise TypeError("FIT input must be provided as a path or bytes-like object")

    if not rows:
        raise ValueError("FIT input does not contain any usable record messages")

    allowed = {
        _canonical_fit_field_name(x)
        for x in (field_allowlist if field_allowlist is not None else FIT_DEFAULT_FIELDS)
        if isinstance(x, str) and x.strip()
    }

    timestamps = [_coerce_timestamp(row["timestamp"]) for row in rows]

    out_rows: list[dict[str, Any]] = []
    resample_columns: list[str] = []
    channel_info: dict[str, dict[str, Any]] = {}

    for row, ts in zip(rows, timestamps):
        out: dict[str, Any] = {"timestamp": ts}
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
                "quantity": role,
                "domain": "world",
                "source": "fit_enrichment",
                "origin": "fit",
                "source_kind": "fit_enrichment",
                "source_columns": [field_name],
            }
        out_rows.append(out)

    df = pd.DataFrame(out_rows)
    if df.empty:
        raise ValueError("FIT input did not yield any allowed numeric fields")

    df = df.sort_values("timestamp", kind="stable").reset_index(drop=True)
    df = df.loc[~df["timestamp"].duplicated(keep="first")].reset_index(drop=True)

    meta: dict[str, Any] = {
        "fit_sha256": fit_sha256,
        "stream_name": "gps_fit",
        "kind": "intermittent",
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
    if source_path is not None:
        meta["path"] = str(source_path)
    if filename is not None:
        meta["filename"] = filename
    return df, meta


def fit_stream_for_session(
    fit_df_absolute: pd.DataFrame,
    fit_meta_absolute: Mapping[str, Any],
    *,
    session_start_datetime: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Project an absolute FIT stream onto one logger session's timebase."""
    if "timestamp" not in fit_df_absolute.columns:
        raise ValueError("Absolute FIT stream is missing timestamp")

    session_start = _coerce_timestamp(session_start_datetime)
    df = fit_df_absolute.copy()
    timestamps = pd.to_datetime(df["timestamp"], utc=True)
    df["time_s"] = (timestamps - session_start).dt.total_seconds().astype(float)
    signal_columns = [column for column in df.columns if column not in {"timestamp", "time_s"}]
    df = df[["timestamp", "time_s", *signal_columns]]

    meta = dict(fit_meta_absolute)
    meta["time_col"] = "time_s"
    meta["timestamp_col"] = "timestamp"
    return df, meta


def parse_fit_stream(
    fit_input: str | Path | bytes | bytearray | memoryview,
    *,
    session_start_datetime: str,
    field_allowlist: Optional[Sequence[str]] = None,
    source_name: Optional[str] = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    fit_df_absolute, fit_meta_absolute = parse_fit_stream_absolute(
        fit_input,
        field_allowlist=field_allowlist,
        source_name=source_name,
    )
    return fit_stream_for_session(
        fit_df_absolute,
        fit_meta_absolute,
        session_start_datetime=session_start_datetime,
    )


def load_fit_stream(
    fit_path: str | Path,
    *,
    session_start_datetime: str,
    field_allowlist: Optional[Sequence[str]] = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    return parse_fit_stream(
        fit_path,
        session_start_datetime=session_start_datetime,
        field_allowlist=field_allowlist,
    )
