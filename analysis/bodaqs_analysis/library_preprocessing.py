from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from bodaqs_analysis.artifacts import (
    ArtifactStore,
    copy_raw_csv_to_source,
    copy_session_aux_sources,
    ensure_run_is_new,
    ensure_session_is_new,
    make_run_id,
    save_session_artifacts,
    write_events_partitioned_by_schema_id,
    write_metrics_partitioned_by_schema_id,
    write_run_manifest,
    write_session_manifest,
)
from bodaqs_analysis.bike_profile import load_bike_profile
from bodaqs_analysis.library_api.catalog_revision import touch_catalog_revision
from bodaqs_analysis.pipeline import preprocess_session
from bodaqs_analysis.preprocess_profile import (
    load_preprocess_config,
    resolve_preprocess_config_paths,
)
from bodaqs_analysis.session_archive import PreparedSessionInput, prepare_session_input, sha256_file
from bodaqs_analysis.session_notes import (
    SessionNoteStore,
    SessionNoteTemplate,
    SessionNoteTemplateStore,
    library_session_note_template_root,
)


ProgressCallback = Callable[[str, Mapping[str, Any]], None]


@dataclass(frozen=True)
class PreprocessBatchRequest:
    """Explicit, notebook-friendly preprocessing request.

    This is intentionally not an Import Manager source. It describes one manual
    batch: selected input files, processing settings, and one target library.
    """

    artifacts_dir: Path
    input_paths: tuple[Path, ...]
    preprocess_profile_path: Path
    bike_profile_path: Path
    run_tz_label: str = "AWST"
    run_description: str | None = None
    session_descriptions: Mapping[str, str] = field(default_factory=dict)
    generic_log_metadata_paths: tuple[Path, ...] = ()
    log_metadata_path: Path | None = None
    fit_dir: Path | None = None
    fit_bindings_path: Path | None = None
    logger_timezone: str | None = None
    include_events: bool = True
    include_metrics: bool = True
    attach_draft_note: bool = False
    session_note_template_path: Path | None = None
    continue_on_error: bool = True

    def __post_init__(self) -> None:
        if not self.input_paths:
            raise ValueError("PreprocessBatchRequest requires at least one input path.")
        object.__setattr__(self, "artifacts_dir", Path(self.artifacts_dir))
        object.__setattr__(self, "input_paths", tuple(Path(p) for p in self.input_paths))
        object.__setattr__(self, "preprocess_profile_path", Path(self.preprocess_profile_path))
        object.__setattr__(self, "bike_profile_path", Path(self.bike_profile_path))
        object.__setattr__(
            self,
            "generic_log_metadata_paths",
            tuple(Path(p) for p in self.generic_log_metadata_paths),
        )
        if self.log_metadata_path is not None:
            object.__setattr__(self, "log_metadata_path", Path(self.log_metadata_path))
        if self.fit_dir is not None:
            object.__setattr__(self, "fit_dir", Path(self.fit_dir))
        if self.fit_bindings_path is not None:
            object.__setattr__(self, "fit_bindings_path", Path(self.fit_bindings_path))
        if self.session_note_template_path is not None:
            object.__setattr__(self, "session_note_template_path", Path(self.session_note_template_path))
        if self.attach_draft_note and self.session_note_template_path is None:
            raise ValueError("attach_draft_note requires an explicit session_note_template_path.")


def preprocess_requested_sessions_to_library(
    request: PreprocessBatchRequest,
    *,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Process all requested inputs into one new artifact-library run."""

    _validate_request_paths(request)
    store = ArtifactStore(request.artifacts_dir)
    run_id = _unique_run_id(store, tz_label=request.run_tz_label)
    ensure_run_is_new(store, run_id=run_id, force=False)

    preprocess_profile_path = request.preprocess_profile_path.resolve()
    bike_profile_path = request.bike_profile_path.resolve()
    preprocess_config = resolve_preprocess_config_paths(
        load_preprocess_config(preprocess_profile_path),
        base_dir=preprocess_profile_path.parent,
    )
    schema_path = Path(str(preprocess_config["schema_path"]))
    fit_import = _fit_import_config(
        preprocess_config,
        fit_dir=request.fit_dir,
        fit_bindings_path=request.fit_bindings_path,
    )

    note_template: SessionNoteTemplate | None = None
    if request.attach_draft_note:
        assert request.session_note_template_path is not None
        note_template = SessionNoteTemplateStore().load_template_file(request.session_note_template_path)

    session_ids: list[str] = []
    results: list[dict[str, Any]] = []

    for input_path in request.input_paths:
        _emit(progress_callback, "input_started", input_path=str(input_path), run_id=run_id)
        try:
            result = _process_one_input(
                request=request,
                store=store,
                run_id=run_id,
                input_path=input_path,
                preprocess_profile_path=preprocess_profile_path,
                bike_profile_path=bike_profile_path,
                preprocess_config=preprocess_config,
                schema_path=schema_path,
                fit_import=fit_import,
                note_template=note_template,
            )
        except Exception as exc:
            failure = {
                "status": "failed",
                "input_path": str(input_path),
                "error": f"{type(exc).__name__}: {exc}",
            }
            results.append(failure)
            _emit(progress_callback, "input_failed", **failure)
            if not request.continue_on_error:
                raise
            continue

        results.append(result)
        session_ids.append(str(result["session_id"]))
        _emit(progress_callback, "input_succeeded", **result)

    write_run_manifest(
        store,
        run_id=run_id,
        session_ids=session_ids,
        timezone_label=request.run_tz_label,
        description=request.run_description,
        pipeline_config={
            "purpose": "manual_preprocessing",
            "batch_policy": "one_run_per_requested_batch",
            "input_count": len(request.input_paths),
            "success_count": len(session_ids),
            "failure_count": len([item for item in results if item.get("status") == "failed"]),
            "preprocess_profile_path": str(preprocess_profile_path),
            "preprocess_profile_sha256": sha256_file(preprocess_profile_path),
            "bike_profile_path": str(bike_profile_path),
            "bike_profile_sha256": sha256_file(bike_profile_path),
            "schema_path": str(schema_path),
            "generic_log_metadata_paths": [str(path) for path in request.generic_log_metadata_paths],
            "log_metadata_path": None if request.log_metadata_path is None else str(request.log_metadata_path),
            "fit_dir": None if request.fit_dir is None else str(request.fit_dir),
            "fit_bindings_path": None if request.fit_bindings_path is None else str(request.fit_bindings_path),
            "logger_timezone_fallback": request.logger_timezone,
            "include_events": bool(request.include_events),
            "include_metrics": bool(request.include_metrics),
            "attach_draft_note": bool(request.attach_draft_note),
            "session_note_template_path": (
                None if request.session_note_template_path is None else str(request.session_note_template_path)
            ),
            "results": results,
        },
    )
    catalog_revision = None
    if session_ids:
        catalog_revision = touch_catalog_revision(
            store.root,
            reason="manual_preprocessing_sessions_written",
            actor="library_preprocessing",
            changed_sessions=[
                {
                    "run_id": run_id,
                    "session_id": session_id,
                    "session_key": f"{run_id}::{session_id}",
                }
                for session_id in session_ids
            ],
        )

    response = {
        "schema": "bodaqs.manual_preprocessing.batch_result",
        "version": 1,
        "run_id": run_id,
        "artifacts_dir": str(store.root),
        "session_ids": session_ids,
        "results": results,
        "run_manifest_path": str(store.path_run_manifest(run_id)),
    }
    if catalog_revision is not None:
        response["library_catalog_revision"] = catalog_revision
    return response


def batch_result_to_study_set(batch_result: Mapping[str, Any], *, library_id: str) -> dict[str, Any]:
    """Return an in-memory Study Set-shaped object for freshly processed sessions."""

    run_id = str(batch_result["run_id"])
    sessions: list[dict[str, str]] = []
    for item in batch_result.get("results", []):
        if not isinstance(item, Mapping) or item.get("status") != "succeeded":
            continue
        session_id = str(item["session_id"])
        session_key = f"{run_id}::{session_id}"
        sessions.append(
            {
                "library_id": str(library_id),
                "run_id": run_id,
                "session_id": session_id,
                "session_key": session_key,
                "session_ref_id": f"{library_id}:{session_key}",
            }
        )
    return {
        "schema": "bodaqs.study_set",
        "version": 1,
        "study_set_id": f"unsaved-{run_id}",
        "display_name": f"Unsaved preprocessing batch {run_id}",
        "sessions": sessions,
        "groupings": [],
    }


def _process_one_input(
    *,
    request: PreprocessBatchRequest,
    store: ArtifactStore,
    run_id: str,
    input_path: Path,
    preprocess_profile_path: Path,
    bike_profile_path: Path,
    preprocess_config: Mapping[str, Any],
    schema_path: Path,
    fit_import: Mapping[str, Any] | None,
    note_template: SessionNoteTemplate | None,
) -> dict[str, Any]:
    with prepare_session_input(input_path) as session_input:
        resolved_log_metadata_path = request.log_metadata_path or session_input.log_metadata_path
        processed = preprocess_session(
            str(session_input.csv_path),
            str(schema_path),
            preprocess_profile_path=preprocess_profile_path,
            log_metadata_path=(
                str(resolved_log_metadata_path) if resolved_log_metadata_path is not None else None
            ),
            generic_log_metadata_paths=(
                None
                if resolved_log_metadata_path is not None
                else [str(path) for path in request.generic_log_metadata_paths]
            ),
            bike_profile_path=bike_profile_path,
            fit_import=fit_import,
            timezone=request.logger_timezone,
            strict=bool(preprocess_config.get("strict", True)),
        )

        session = processed["session"]
        session_id = str(session["session_id"])
        events_df = processed.get("events", pd.DataFrame())
        metrics_df = processed.get("metrics", pd.DataFrame())

        ensure_session_is_new(store, run_id=run_id, session_id=session_id, force=False)
        source_sha256 = copy_raw_csv_to_source(
            store=store,
            run_id=run_id,
            session_id=session_id,
            csv_path=session_input.csv_path,
        )
        source_manifest = _source_manifest(
            session_input,
            source_sha256=source_sha256,
            request=request,
            preprocess_profile_path=preprocess_profile_path,
            bike_profile_path=bike_profile_path,
            resolved_log_metadata_path=resolved_log_metadata_path,
        )
        aux_manifest = copy_session_aux_sources(
            store=store,
            run_id=run_id,
            session_id=session_id,
            aux_sources=(session.get("source", {}) or {}).get("aux_sources")
            if isinstance(session.get("source"), Mapping)
            else None,
        )
        if aux_manifest:
            source_manifest["aux_sources"] = aux_manifest

        save_session_artifacts(
            store,
            run_id=run_id,
            session_id=session_id,
            session_df=session["df"],
            session_meta=session["meta"],
            secondary_stream_dfs=session.get("stream_dfs"),
            secondary_stream_meta=session.get("meta", {}).get("secondary_streams"),
        )

        events_written: list[str] = []
        metrics_written: list[str] = []
        if request.include_events and isinstance(events_df, pd.DataFrame) and not events_df.empty:
            events_written = write_events_partitioned_by_schema_id(
                store=store,
                run_id=run_id,
                session_id=session_id,
                events_df=events_df,
                schema_path=schema_path,
            )
        if request.include_metrics and isinstance(metrics_df, pd.DataFrame) and not metrics_df.empty:
            metrics_written = write_metrics_partitioned_by_schema_id(
                store=store,
                run_id=run_id,
                session_id=session_id,
                metrics_df=metrics_df,
            )

        note_record = None
        if request.attach_draft_note and note_template is not None:
            note_record = _write_draft_note_from_template(
                store=store,
                run_id=run_id,
                session_id=session_id,
                template=note_template,
                template_path=Path(request.session_note_template_path),  # type: ignore[arg-type]
                bike_profile_path=bike_profile_path,
            )

        session_description = request.session_descriptions.get(session_id)
        write_session_manifest(
            store,
            run_id=run_id,
            session_id=session_id,
            description=session_description,
            contracts={"session": "v0.x", "events": "v0.x", "metrics": "v0.x"},
            source=source_manifest,
            aux_sources=aux_manifest,
            summary=_session_summary(session, events_df=events_df, metrics_df=metrics_df),
        )

    out = {
        "status": "succeeded",
        "input_path": str(input_path),
        "run_id": run_id,
        "session_id": session_id,
        "session_key": f"{run_id}::{session_id}",
        "session_manifest_path": str(store.path_session_manifest(run_id, session_id)),
        "events_written": events_written,
        "metrics_written": metrics_written,
    }
    if note_record is not None:
        out["session_note"] = note_record
    return out


def _source_manifest(
    session_input: PreparedSessionInput,
    *,
    source_sha256: str,
    request: PreprocessBatchRequest,
    preprocess_profile_path: Path,
    bike_profile_path: Path,
    resolved_log_metadata_path: Path | None,
) -> dict[str, Any]:
    manifest = session_input.source_manifest(
        source_path="source/input.csv",
        source_sha256=source_sha256,
    )
    manifest.update(
        {
            "manual_preprocessing": {
                "preprocess_profile_path": str(preprocess_profile_path),
                "preprocess_profile_sha256": sha256_file(preprocess_profile_path),
                "bike_profile_path": str(bike_profile_path),
                "bike_profile_sha256": sha256_file(bike_profile_path),
                "log_metadata_path": (
                    None if resolved_log_metadata_path is None else str(resolved_log_metadata_path)
                ),
                "generic_log_metadata_paths": [str(path) for path in request.generic_log_metadata_paths],
                "logger_timezone_fallback": request.logger_timezone,
            }
        }
    )
    return manifest


def _write_draft_note_from_template(
    *,
    store: ArtifactStore,
    run_id: str,
    session_id: str,
    template: SessionNoteTemplate,
    template_path: Path,
    bike_profile_path: Path,
) -> dict[str, Any]:
    library_template_path = _copy_template_to_library(
        store=store,
        template=template,
        template_path=template_path,
    )
    bike_profile = load_bike_profile(bike_profile_path)
    source_context = {
        "origin": "manual_preprocessing",
        "bike_profile_id": bike_profile.get("bike_profile_id"),
        "bike_profile_path": str(bike_profile_path),
        "bike_profile_sha256": sha256_file(bike_profile_path),
        "template_id": template.template_id,
        "template_version": template.template_version,
        "template_path": str(template_path),
        "template_sha256": sha256_file(template_path),
        "library_template_path": str(library_template_path),
    }
    note_store = SessionNoteStore(
        store=store,
        template_store=SessionNoteTemplateStore(library_session_note_template_root(store.root)),
    )
    note = note_store.create_note_from_template(
        run_id=run_id,
        session_id=session_id,
        template_id=template.template_id,
        template_version=template.template_version,
        title=template.title,
        draft=True,
        source_context=source_context,
    )
    saved = note_store.save_note(note)
    return {
        "status": "succeeded",
        "path": str(note_store.note_path(run_id=run_id, session_id=session_id)),
        "draft": bool(saved.draft),
        "template_id": saved.template_id,
        "template_version": saved.template_version,
        "template_path": str(template_path),
        "library_template_path": str(library_template_path),
    }


def _copy_template_to_library(
    *,
    store: ArtifactStore,
    template: SessionNoteTemplate,
    template_path: Path,
) -> Path:
    target = (
        library_session_note_template_root(store.root)
        / template.template_id
        / f"{template.template_version}.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    source_sha256 = sha256_file(template_path)
    if target.exists():
        if sha256_file(target) != source_sha256:
            raise ValueError(
                "Library already contains a different session note template for "
                f"{template.template_id}@{template.template_version}: {target}"
            )
        return target
    shutil.copy2(template_path, target)
    return target


def _validate_request_paths(request: PreprocessBatchRequest) -> None:
    for input_path in request.input_paths:
        if not input_path.exists():
            raise FileNotFoundError(f"Input path does not exist: {input_path}")
    if not request.preprocess_profile_path.exists():
        raise FileNotFoundError(f"Preprocess profile does not exist: {request.preprocess_profile_path}")
    if not request.bike_profile_path.exists():
        raise FileNotFoundError(f"Bike profile does not exist: {request.bike_profile_path}")
    if request.log_metadata_path is not None and not request.log_metadata_path.exists():
        raise FileNotFoundError(f"Log metadata path does not exist: {request.log_metadata_path}")
    if request.session_note_template_path is not None and not request.session_note_template_path.exists():
        raise FileNotFoundError(
            f"Session note template path does not exist: {request.session_note_template_path}"
        )


def _unique_run_id(store: ArtifactStore, *, tz_label: str) -> str:
    base = make_run_id(tz_label=tz_label)
    run_id = base
    suffix = 1
    while store.run_dir(run_id).exists():
        run_id = f"{base}_{suffix:02d}"
        suffix += 1
    return run_id


def _fit_import_config(
    preprocess_config: Mapping[str, Any],
    *,
    fit_dir: Path | None,
    fit_bindings_path: Path | None,
) -> dict[str, Any] | None:
    raw = preprocess_config.get("fit_import")
    if not isinstance(raw, Mapping):
        return None
    cfg = dict(raw)
    if bool(cfg.get("enabled", False)):
        cfg["fit_dir"] = str(fit_dir) if fit_dir is not None else None
        cfg["bindings_path"] = str(fit_bindings_path) if fit_bindings_path is not None else None
    return cfg


def _session_summary(
    session: Mapping[str, Any],
    *,
    events_df: Any,
    metrics_df: Any,
) -> dict[str, Any]:
    df = session.get("df")
    summary: dict[str, Any] = {}
    if isinstance(df, pd.DataFrame):
        summary["n_rows"] = int(len(df))
        if not df.empty and "time_s" in df.columns:
            summary["t_start_s"] = float(df["time_s"].iloc[0])
            summary["t_end_s"] = float(df["time_s"].iloc[-1])
    if isinstance(events_df, pd.DataFrame):
        summary["n_events"] = int(len(events_df))
    if isinstance(metrics_df, pd.DataFrame):
        summary["n_metrics"] = int(len(metrics_df))
    return summary


def _emit(callback: ProgressCallback | None, event: str, **payload: Any) -> None:
    if callback is None:
        return
    callback(event, payload)
