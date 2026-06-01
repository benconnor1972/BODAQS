"""Library discovery and catalog helpers for the BODAQS Library API adapter."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from bodaqs_analysis.artifacts import (
    ArtifactStore,
    list_event_types,
    list_metric_event_types,
    list_runs,
    list_sessions,
)

from .errors import InvalidRequestError
from .ids import derive_object_id, make_session_key, make_session_ref_id
from .models import library_payload


LIBRARY_DEFINITION_FILENAME = "library_definition.json"
RUNS_DIRNAME = "runs"
SESSION_CATALOG_SCHEMA = "bodaqs.session_catalog"
SESSION_CATALOG_VERSION = 1
SESSION_CATALOG_ROW_SCHEMA = "bodaqs.session_catalog_row"
SESSION_CATALOG_ROW_VERSION = 1


def discover_libraries(libraries_root: str | Path) -> list[dict[str, Any]]:
    """Discover processed BODAQS libraries under one libraries root."""

    root = Path(libraries_root).expanduser()
    if not root.exists():
        raise InvalidRequestError(
            "Libraries root does not exist.",
            details={"libraries_root": str(root)},
        )
    if not root.is_dir():
        raise InvalidRequestError(
            "Libraries root is not a directory.",
            details={"libraries_root": str(root)},
        )

    libraries: list[dict[str, Any]] = []
    seen_ids: dict[str, Path] = {}
    for child in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name.lower()):
        discovered = _discover_library_dir(child)
        if discovered is None:
            continue

        library_id = str(discovered["library_id"])
        previous = seen_ids.get(library_id)
        if previous is not None:
            raise InvalidRequestError(
                "Duplicate library_id discovered under libraries root.",
                details={
                    "library_id": library_id,
                    "first_root": str(previous),
                    "second_root": str(child),
                },
            )
        seen_ids[library_id] = child
        libraries.append(discovered)

    return libraries


def build_session_catalog(
    library_root: str | Path,
    *,
    library_id: str | None = None,
) -> dict[str, Any]:
    """Build a compact JSON-serializable catalog for one processed library."""

    root = Path(library_root).expanduser()
    if not root.exists() or not root.is_dir():
        raise InvalidRequestError(
            "Library root does not exist or is not a directory.",
            details={"library_root": str(root)},
        )

    store = ArtifactStore(root)
    rows: list[dict[str, Any]] = []
    for run_id in list_runs(store):
        run_manifest = _read_json_object(store.path_run_manifest(run_id)) or {}
        for session_id in list_sessions(store, run_id):
            rows.append(
                _build_session_catalog_row(
                    store,
                    library_id=library_id,
                    run_id=str(run_id),
                    session_id=str(session_id),
                    run_manifest=run_manifest,
                )
            )

    return {
        "schema": SESSION_CATALOG_SCHEMA,
        "version": SESSION_CATALOG_VERSION,
        "library_id": library_id,
        "generated_at": _utcnow_iso(),
        "row_count": len(rows),
        "rows": rows,
    }


def _discover_library_dir(path: Path) -> dict[str, Any] | None:
    definition_path = path / LIBRARY_DEFINITION_FILENAME
    definition = _read_json_object(definition_path)
    has_definition = definition is not None
    has_runs = _has_runs(path)
    if not has_definition and not has_runs:
        return None

    library_id = _metadata_text(definition, "library_id") if definition else None
    display_name = _metadata_text(definition, "display_name") if definition else None

    if not library_id:
        library_id = derive_object_id(path.name, fallback="library")
    if not display_name:
        display_name = _display_name_from_id(library_id)

    return library_payload(
        library_id=library_id,
        display_name=display_name,
        root=path.resolve(),
        definition=definition,
    )


def _build_session_catalog_row(
    store: ArtifactStore,
    *,
    library_id: str | None,
    run_id: str,
    session_id: str,
    run_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    session_key = make_session_key(run_id, session_id)
    session_manifest = _read_json_object(store.path_session_manifest(run_id, session_id)) or {}
    session_meta = _read_json_object(store.path_session_meta(run_id, session_id)) or {}

    note_status, note_fields = _note_summary(store, run_id=run_id, session_id=session_id)
    event_summary, event_schema = _event_summary(store, run_id=run_id, session_id=session_id)
    metric_summary = _metric_summary(store, run_id=run_id, session_id=session_id)
    provenance = _provenance_summary(
        run_manifest=run_manifest,
        session_manifest=session_manifest,
    )

    run_description = _optional_text(run_manifest.get("description"))
    session_description = _optional_text(session_manifest.get("description"))
    session_label = session_description or session_id
    label_parts = [
        str(note_fields.get("bike")).strip() if note_fields.get("bike") is not None else "",
        session_label,
    ]
    display_label = " - ".join(part for part in label_parts if part) or session_key

    row = {
        "schema": SESSION_CATALOG_ROW_SCHEMA,
        "version": SESSION_CATALOG_ROW_VERSION,
        "library_id": library_id,
        "session_ref_id": make_session_ref_id(library_id, session_key) if library_id else None,
        "session_key": session_key,
        "run_id": run_id,
        "session_id": session_id,
        "display": {
            "label": display_label,
            "run_label": run_description or run_id,
            "session_label": session_label,
        },
        "timestamps": _timestamp_summary(run_manifest, session_meta),
        "note_status": note_status,
        "note_fields": note_fields,
        "qc_summary": _qc_summary(session_meta, session_manifest),
        "provenance": provenance,
        "event_schema": event_schema,
        "available_signals": _available_signals(
            session_meta,
            dataframe_path=store.path_session_df(run_id, session_id),
        ),
        "event_summary": event_summary,
        "metric_summary": metric_summary,
    }
    return row


def _available_signals(
    session_meta: Mapping[str, Any],
    *,
    dataframe_path: Path,
) -> list[dict[str, Any]]:
    signals = session_meta.get("signals")
    if not isinstance(signals, Mapping):
        return []

    known_columns = _parquet_columns(dataframe_path)
    out: list[dict[str, Any]] = []
    for column, raw_info in signals.items():
        column_text = str(column)
        if known_columns is not None and column_text not in known_columns:
            continue
        if not isinstance(raw_info, Mapping):
            continue
        info = {str(k): v for k, v in dict(raw_info).items()}
        if str(info.get("kind") or "").strip().lower() == "qc":
            continue

        signal = {
            "signal_id": _signal_id(column_text, info),
            "column": column_text,
            "display_name": _signal_display_name(column_text, info),
        }
        for key in (
            "end",
            "domain",
            "quantity",
            "unit",
            "processing_role",
            "kind",
            "sensor",
            "origin",
        ):
            value = info.get(key)
            if value is not None:
                signal[key] = value
        out.append(signal)
    return sorted(out, key=lambda item: str(item.get("column") or "").lower())


def _event_summary(
    store: ArtifactStore,
    *,
    run_id: str,
    session_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    event_type_dirs = list_event_types(store, run_id, session_id)
    total_count = 0
    by_type: dict[str, int] = {}

    for event_type in event_type_dirs:
        path = store.path_events_df(run_id, session_id, event_type)
        try:
            df = pd.read_parquet(path)
        except Exception:
            continue
        total_count += int(len(df))
        if "schema_id" in df.columns:
            counts = df["schema_id"].astype(str).value_counts(dropna=False)
            for key, value in counts.items():
                by_type[str(key)] = by_type.get(str(key), 0) + int(value)
        else:
            by_type[str(event_type)] = by_type.get(str(event_type), 0) + int(len(df))

    schema_ids = sorted(set(event_type_dirs))
    schema_id = schema_ids[0] if len(schema_ids) == 1 else None
    event_schema = {
        "schema_id": schema_id,
        "schema_ids": schema_ids,
        "display_name": _display_name_from_id(schema_id) if schema_id else None,
    }
    return {"total_count": total_count, "by_type": by_type}, event_schema


def _metric_summary(
    store: ArtifactStore,
    *,
    run_id: str,
    session_id: str,
) -> dict[str, Any]:
    schema_ids = list_metric_event_types(store, run_id, session_id)
    metric_columns: set[str] = set()
    event_ids: set[str] = set()
    row_count = 0

    for schema_id in schema_ids:
        path = store.path_metrics_df(run_id, session_id, schema_id)
        try:
            df = pd.read_parquet(path)
        except Exception:
            continue
        row_count += int(len(df))
        metric_columns.update(str(col) for col in df.columns if str(col) not in _METRIC_ID_COLUMNS)
        if "event_id" in df.columns:
            event_ids.update(str(value) for value in df["event_id"].dropna().unique())

    return {
        "metric_count": len(metric_columns),
        "event_count_with_metrics": len(event_ids) if event_ids else row_count,
        "schema_ids": sorted(set(schema_ids)),
    }


_METRIC_ID_COLUMNS = {
    "session_id",
    "event_id",
    "schema_id",
    "schema_version",
    "event_name",
    "signal",
    "signal_col",
    "signals",
    "start_idx",
    "end_idx",
    "start_time_s",
    "end_time_s",
    "trigger_idx",
    "trigger_time_s",
    "trigger_datetime",
    "detector_version",
    "params_hash",
    "qc_flags",
    "score",
    "meta",
}


def _note_summary(
    store: ArtifactStore,
    *,
    run_id: str,
    session_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = store.path_session_notes(run_id, session_id)
    base = {
        "status": "missing",
        "has_note": False,
        "draft": False,
        "template_id": None,
        "template_version": None,
    }
    if not path.exists():
        return base, {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        status = dict(base)
        status.update(
            {
                "status": "missing",
                "has_note": True,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        return status, {}

    if not isinstance(data, Mapping) or str(data.get("schema") or "") != "bodaqs.session_notes.document":
        status = dict(base)
        status.update({"status": "missing", "has_note": True, "error": "invalid_note_document"})
        return status, {}

    values = data.get("values") if isinstance(data.get("values"), Mapping) else {}
    custom_values = data.get("custom_values") if isinstance(data.get("custom_values"), Mapping) else {}
    draft = bool(data.get("draft", False))
    status = {
        "status": "draft" if draft else "edited",
        "has_note": True,
        "draft": draft,
        "template_id": _optional_text(data.get("template_id")),
        "template_version": _optional_text(data.get("template_version")),
    }
    projected = {}
    for field_id in ("bike", "rider"):
        value = values.get(field_id, custom_values.get(field_id))
        if value is not None:
            projected[field_id] = value
    return status, projected


def _timestamp_summary(
    run_manifest: Mapping[str, Any],
    session_meta: Mapping[str, Any],
) -> dict[str, Any]:
    started = _optional_text(session_meta.get("t0_datetime"))
    processed_at = _optional_text(run_manifest.get("created_at"))
    return {
        "started_at_utc": _utc_timestamp_or_none(started),
        "started_at_local": started,
        "processed_at": processed_at,
        "imported_at": processed_at,
    }


def _qc_summary(
    session_meta: Mapping[str, Any],
    session_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    qc = session_meta.get("qc")
    if not isinstance(qc, Mapping):
        summary = session_manifest.get("summary")
        qc = summary.get("qc") if isinstance(summary, Mapping) else {}
    if not isinstance(qc, Mapping):
        qc = {}

    warnings = qc.get("warnings")
    errors = qc.get("errors")
    warning_count = len(warnings) if isinstance(warnings, list) else 0
    error_count = len(errors) if isinstance(errors, list) else 0
    status = "alert" if error_count else ("warning" if warning_count else "ok")
    return {
        "status": status,
        "warning_count": warning_count,
        "error_count": error_count,
    }


def _provenance_summary(
    *,
    run_manifest: Mapping[str, Any],
    session_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    source = session_manifest.get("source")
    source = source if isinstance(source, Mapping) else {}
    pipeline_config = run_manifest.get("pipeline_config")
    pipeline_config = pipeline_config if isinstance(pipeline_config, Mapping) else {}
    import_source = pipeline_config.get("import_source")
    import_source = import_source if isinstance(import_source, Mapping) else {}
    archive_import = pipeline_config.get("archive_import")
    archive_import = archive_import if isinstance(archive_import, Mapping) else {}
    remote_source = source.get("remote_source")
    remote_source = remote_source if isinstance(remote_source, Mapping) else {}

    out = {
        "source_type": _first_text(source.get("import_source_type"), import_source.get("source_type")),
        "source_id": _first_text(source.get("import_source_id"), import_source.get("source_id")),
        "logger_id": _first_text(remote_source.get("logger_id"), source.get("logger_id")),
        "archive_name": _optional_text(source.get("original_archive_filename")),
        "processing_key": _first_text(source.get("processing_key"), archive_import.get("processing_key")),
    }
    return {key: value for key, value in out.items() if value is not None}


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return dict(value) if isinstance(value, Mapping) else None


def _has_runs(path: Path) -> bool:
    runs_dir = path / RUNS_DIRNAME
    if not runs_dir.is_dir():
        return False
    return any(child.is_dir() for child in runs_dir.iterdir())


def _metadata_text(definition: Mapping[str, Any] | None, key: str) -> str | None:
    if not isinstance(definition, Mapping):
        return None
    value = definition.get(key)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _display_name_from_id(value: str) -> str:
    words = str(value).replace("_", " ").replace("-", " ").strip()
    return words.title() if words else "Library"


def _parquet_columns(path: Path) -> set[str] | None:
    if not path.exists():
        return None
    try:
        import pyarrow.parquet as pq

        return {str(name) for name in pq.read_schema(path).names}
    except Exception:
        try:
            return {str(name) for name in pd.read_parquet(path).columns}
        except Exception:
            return None


def _signal_id(column: str, info: Mapping[str, Any]) -> str:
    explicit = _optional_text(info.get("signal_id"))
    if explicit:
        return explicit
    semantic_parts = [
        _optional_text(info.get("end")),
        _optional_text(info.get("domain")),
        _optional_text(info.get("quantity")),
        _optional_text(info.get("unit")),
    ]
    semantic = "-".join(part for part in semantic_parts if part)
    return derive_object_id(semantic or column, fallback="signal")


def _signal_display_name(column: str, info: Mapping[str, Any]) -> str:
    explicit = _optional_text(info.get("display_name"))
    if explicit:
        return explicit
    semantic_parts = [
        _optional_text(info.get("end")),
        _optional_text(info.get("domain")),
        _optional_text(info.get("quantity")),
    ]
    text = " ".join(part for part in semantic_parts if part)
    if text:
        return text.replace("_", " ").title()
    return str(column).split("[", 1)[0].replace("_", " ").strip().title() or str(column)


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _optional_text(value)
        if text is not None:
            return text
    return None


def _utc_timestamp_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if text.endswith("Z") or "+00:00" in text:
        return text
    return None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
