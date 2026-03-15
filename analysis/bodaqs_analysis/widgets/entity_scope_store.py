# -*- coding: utf-8 -*-
"""Local per-user persistence for current entity-scope selection."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

import ipywidgets as W
import pandas as pd

from bodaqs_analysis.artifacts import ArtifactStore, list_runs, list_sessions
from bodaqs_analysis.widgets.contracts import (
    EntitySelectionSnapshot,
    PersistedEntityScopeLoadResult,
    PersistedEntityScopeSelection,
    RUN_ID_COL,
    SESSION_ID_COL,
    SESSION_KEY_COL,
    ScopeEntity,
    SessionSelection,
    SessionSelectorHandle,
)
from bodaqs_analysis.widgets.entity_scope import build_entity_selection_snapshot
from bodaqs_analysis.widgets.session_aggregations import SessionAggregationStore

STORE_SCHEMA = "bodaqs.entity_scope_selection.store"
STORE_VERSION = 1
DEFAULT_FILENAME = "entity_scope_selection_v1.json"
DEFAULT_DIRNAME = ".bodaqs"


class EntityScopeStoreError(ValueError):
    pass


class EntityScopeStoreValidationError(EntityScopeStoreError):
    pass


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def user_store_path() -> Path:
    return Path.home() / DEFAULT_DIRNAME / DEFAULT_FILENAME


def _normalize_artifacts_root(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _atomic_write(path: Path, text: str) -> None:
    _ensure_parent(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _backup(path: Path) -> None:
    if path.exists():
        try:
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        except Exception:
            pass


def make_session_key(run_id: str, session_id: str) -> str:
    return f"{run_id}::{session_id}"


def _events_index_df_from_key_to_ref(
    key_to_ref: Mapping[str, tuple[str, str]],
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {SESSION_KEY_COL: sk, RUN_ID_COL: rid, SESSION_ID_COL: sid}
            for sk, (rid, sid) in key_to_ref.items()
        ]
    )


def _all_key_to_ref(store: ArtifactStore) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for run_id in list_runs(store):
        for session_id in list_sessions(store, run_id):
            out[make_session_key(run_id, session_id)] = (run_id, session_id)
    return out


def _read_json_safe(store: ArtifactStore, path: Path) -> dict[str, Any]:
    try:
        return store.read_json(path)
    except Exception:
        return {}


def _get_run_meta(store: ArtifactStore, run_id: str) -> dict[str, str]:
    manifest = _read_json_safe(store, store.path_run_manifest(run_id))
    return {
        "created_at": str(manifest.get("created_at") or "").strip(),
        "description": str(manifest.get("description") or "").strip(),
    }


def _get_session_desc(store: ArtifactStore, run_id: str, session_id: str) -> str:
    manifest = _read_json_safe(store, store.path_session_manifest(run_id, session_id))
    return str(manifest.get("description") or "").strip()


def _format_run_session_label(
    *,
    created_at: str,
    run_id: str,
    run_description: str,
    session_id: str,
    session_description: str,
    show_ids: bool,
) -> str:
    run_desc = run_description.strip()
    sess_desc = session_description.strip()

    if show_ids:
        run_part = f"run_id={run_id} | run_desc={run_desc or '(none)'}"
        sess_part = f"session_id={session_id} | session_desc={sess_desc or '(none)'}"
    else:
        run_part = run_desc or run_id
        sess_part = sess_desc or session_id

    parts = [p for p in (created_at, run_part, sess_part) if p]
    return " | ".join(parts)


def _format_aggregation_label(
    *,
    aggregation_key: str,
    title: str,
    n_members: int,
    show_ids: bool,
) -> str:
    title_s = str(title or "").strip()
    if show_ids:
        return f"Aggregation | title={title_s or '(none)'} | key={aggregation_key} | n={n_members}"
    return f"Aggregation | {title_s or aggregation_key} ({n_members})"


def _build_entity_index(
    *,
    store: ArtifactStore,
    show_ids: bool = False,
) -> dict[str, ScopeEntity]:
    key_to_ref = _all_key_to_ref(store)
    out: dict[str, ScopeEntity] = {}

    for session_key, (run_id, session_id) in sorted(key_to_ref.items()):
        run_meta = _get_run_meta(store, run_id)
        session_desc = _get_session_desc(store, run_id, session_id)
        out[str(session_key)] = ScopeEntity(
            entity_key=str(session_key),
            kind="session",
            label="Session | "
            + _format_run_session_label(
                created_at=run_meta["created_at"],
                run_id=str(run_id),
                run_description=run_meta["description"],
                session_id=str(session_id),
                session_description=session_desc,
                show_ids=show_ids,
            ),
            member_session_keys=(str(session_key),),
        )

    agg_store = SessionAggregationStore()
    try:
        agg_store.load()
    except Exception:
        pass

    for agg in agg_store.list():
        out[str(agg.aggregation_key)] = ScopeEntity(
            entity_key=str(agg.aggregation_key),
            kind="aggregation",
            label=_format_aggregation_label(
                aggregation_key=str(agg.aggregation_key),
                title=str(agg.title),
                n_members=len(agg.member_session_keys),
                show_ids=show_ids,
            ),
            member_session_keys=tuple(map(str, agg.member_session_keys)),
        )

    return out


def validate_persisted_selection(data: Mapping[str, Any]) -> None:
    if not isinstance(data, Mapping):
        raise EntityScopeStoreValidationError("selection must be an object")

    if not isinstance(data.get("artifacts_root"), str) or not str(data.get("artifacts_root")).strip():
        raise EntityScopeStoreValidationError("selection.artifacts_root is required")

    if not isinstance(data.get("saved_at_utc"), str) or not str(data.get("saved_at_utc")).strip():
        raise EntityScopeStoreValidationError("selection.saved_at_utc is required")

    keys = data.get("selected_entity_keys")
    if not isinstance(keys, list):
        raise EntityScopeStoreValidationError("selection.selected_entity_keys must be a list")
    if not keys:
        raise EntityScopeStoreValidationError("selection.selected_entity_keys must not be empty")

    seen: set[str] = set()
    for key in keys:
        skey = str(key).strip()
        if not skey:
            raise EntityScopeStoreValidationError("selection.selected_entity_keys must not contain blanks")
        if skey in seen:
            raise EntityScopeStoreValidationError(f"duplicate selected entity key: {skey}")
        seen.add(skey)

    kinds = data.get("selected_entity_kinds", {})
    if not isinstance(kinds, Mapping):
        raise EntityScopeStoreValidationError("selection.selected_entity_kinds must be an object")
    for entity_key, kind in kinds.items():
        if str(kind) not in {"session", "aggregation"}:
            raise EntityScopeStoreValidationError(
                f"invalid entity kind for {entity_key}: {kind!r}"
            )

    labels = data.get("selected_labels", {})
    if not isinstance(labels, Mapping):
        raise EntityScopeStoreValidationError("selection.selected_labels must be an object")


def validate_store(data: Mapping[str, Any]) -> None:
    if not isinstance(data, Mapping):
        raise EntityScopeStoreValidationError("store must be an object")
    if data.get("schema") != STORE_SCHEMA:
        raise EntityScopeStoreValidationError("invalid store schema")
    if int(data.get("version", -1)) != STORE_VERSION:
        raise EntityScopeStoreValidationError("invalid store version")

    selection = data.get("selection")
    if selection is None:
        return
    if not isinstance(selection, Mapping):
        raise EntityScopeStoreValidationError("selection must be an object or null")
    validate_persisted_selection(selection)


def selection_from_mapping(data: Mapping[str, Any]) -> PersistedEntityScopeSelection:
    validate_persisted_selection(data)
    return PersistedEntityScopeSelection(
        artifacts_root=str(data["artifacts_root"]),
        saved_at_utc=str(data["saved_at_utc"]),
        selected_entity_keys=tuple(map(str, data.get("selected_entity_keys", []))),
        selected_entity_kinds={
            str(k): str(v)  # type: ignore[arg-type]
            for k, v in dict(data.get("selected_entity_kinds", {})).items()
        },
        selected_labels={str(k): str(v) for k, v in dict(data.get("selected_labels", {})).items()},
    )


def selection_to_mapping(selection: PersistedEntityScopeSelection) -> dict[str, Any]:
    data = asdict(selection)
    data["selected_entity_keys"] = list(selection.selected_entity_keys)
    return data


class EntityScopeStore:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path).expanduser() if path else user_store_path()
        self._data: Optional[dict[str, Any]] = None

    def _empty(self) -> dict[str, Any]:
        ts = now_utc_iso()
        return {
            "schema": STORE_SCHEMA,
            "version": STORE_VERSION,
            "created_at_utc": ts,
            "updated_at_utc": ts,
            "selection": None,
        }

    @property
    def data(self) -> dict[str, Any]:
        if self._data is None:
            self._data = self._empty()
        return self._data

    def load(self) -> None:
        if not self.path.exists():
            self._data = self._empty()
            return

        try:
            obj = json.loads(self.path.read_text(encoding="utf-8"))
            validate_store(obj)
        except Exception as exc:
            try:
                shutil.copy2(self.path, self.path.with_suffix(".corrupt"))
            except Exception:
                pass
            self._data = self._empty()
            raise EntityScopeStoreError("Failed to load entity scope store") from exc

        self._data = dict(obj)

    def save(self) -> None:
        payload = self.data
        payload["updated_at_utc"] = now_utc_iso()
        validate_store(payload)
        _backup(self.path)
        _atomic_write(self.path, json.dumps(payload, indent=2, ensure_ascii=False))

    def get_selection(self) -> Optional[PersistedEntityScopeSelection]:
        selection = self.data.get("selection")
        if not isinstance(selection, Mapping):
            return None
        return selection_from_mapping(selection)

    def set_selection(self, selection: PersistedEntityScopeSelection) -> PersistedEntityScopeSelection:
        self.data["selection"] = selection_to_mapping(selection)
        return selection


def save_entity_scope_selection(
    *,
    sel: Mapping[str, Any],
    artifacts_root: str | Path,
    store_path: Optional[Path] = None,
) -> PersistedEntityScopeSelection:
    get_selected_entities = sel.get("get_selected_entities")
    if not callable(get_selected_entities):
        raise ValueError("selector handle must provide get_selected_entities() to persist selection")

    selected_entities = list(get_selected_entities())
    if not selected_entities:
        raise ValueError("No entities are currently selected")

    selection = PersistedEntityScopeSelection(
        artifacts_root=_normalize_artifacts_root(artifacts_root),
        saved_at_utc=now_utc_iso(),
        selected_entity_keys=tuple(str(entity.entity_key) for entity in selected_entities),
        selected_entity_kinds={
            str(entity.entity_key): str(entity.kind)  # type: ignore[dict-item]
            for entity in selected_entities
        },
        selected_labels={str(entity.entity_key): str(entity.label) for entity in selected_entities},
    )

    scope_store = EntityScopeStore(path=store_path)
    try:
        scope_store.load()
    except Exception:
        pass
    scope_store.set_selection(selection)
    scope_store.save()
    return selection


def load_entity_scope_selection(
    *,
    artifacts_dir: str | Path = "artifacts",
    store_path: Optional[Path] = None,
    strict: bool = False,
) -> PersistedEntityScopeLoadResult:
    artifact_store = ArtifactStore(Path(artifacts_dir))
    scope_store = EntityScopeStore(path=store_path)
    scope_store.load()

    source = scope_store.get_selection()
    if source is None:
        raise EntityScopeStoreError("No persisted entity selection has been saved")

    warnings: list[str] = []
    current_root = _normalize_artifacts_root(artifact_store.root)
    if source.artifacts_root != current_root:
        message = (
            "Persisted selection was saved against a different artifacts root: "
            f"{source.artifacts_root} (current: {current_root})"
        )
        if strict:
            raise EntityScopeStoreError(message)
        warnings.append(message)

    entity_index = _build_entity_index(store=artifact_store, show_ids=False)
    selected_entities: list[ScopeEntity] = []
    missing: list[str] = []

    for entity_key in source.selected_entity_keys:
        entity = entity_index.get(str(entity_key))
        if entity is None:
            missing.append(str(entity_key))
            continue
        selected_entities.append(entity)

    if missing:
        warnings.append(
            "Dropped persisted entities that no longer resolve: " + ", ".join(missing[:6])
        )

    if not selected_entities:
        raise EntityScopeStoreError("Persisted selection resolved to no currently valid entities")

    key_to_ref = _all_key_to_ref(artifact_store)
    events_index_df = _events_index_df_from_key_to_ref(key_to_ref)
    snapshot = build_entity_selection_snapshot(
        selected_entities=selected_entities,
        key_to_ref=key_to_ref,
        events_index_df=events_index_df,
    )

    return PersistedEntityScopeLoadResult(
        snapshot=snapshot,
        warnings=warnings,
        source=source,
    )


def make_persisted_entity_scope_handle(
    *,
    artifacts_dir: str | Path = "artifacts",
    strict: bool = False,
    auto_display: bool = False,
) -> SessionSelectorHandle:
    artifact_store = ArtifactStore(Path(artifacts_dir))
    refresh_signal = W.IntText(value=0, layout=W.Layout(display="none"))
    reload_btn = W.Button(description="Reload persisted selection")
    out = W.Output(layout=W.Layout(width="1240px"))

    _snapshot = EntitySelectionSnapshot(
        selected_entities=[],
        entity_to_effective_members={},
        expanded_session_keys=[],
        key_to_ref={},
        events_index_df=pd.DataFrame(columns=[SESSION_KEY_COL, RUN_ID_COL, SESSION_ID_COL]),
    )
    _warnings: list[str] = []
    _source: Optional[PersistedEntityScopeSelection] = None

    def _set_status(lines: Sequence[str]) -> None:
        with out:
            out.clear_output()
            for line in lines:
                print(line)

    def _reload(*_) -> PersistedEntityScopeLoadResult:
        nonlocal _snapshot, _warnings, _source
        result = load_entity_scope_selection(
            artifacts_dir=artifacts_dir,
            strict=strict,
        )
        _snapshot = result.snapshot
        _warnings = list(result.warnings)
        _source = result.source

        lines = [
            f"Using persisted selection saved at {_source.saved_at_utc}.",
            f"Selected entities: {', '.join(_source.selected_entity_keys)}",
        ]
        lines.extend(_warnings)
        _set_status(lines)
        refresh_signal.value = int(refresh_signal.value or 0) + 1
        return result

    def _on_reload(_):
        try:
            _reload()
        except Exception as exc:
            _set_status([f"Reload failed: {exc}"])

    reload_btn.on_click(_on_reload)

    try:
        _reload()
    except Exception as exc:
        _set_status([f"Load failed: {exc}"])

    ui = W.VBox([reload_btn, out, refresh_signal])

    def get_selected() -> list[SessionSelection]:
        return [
            {"run_id": rid, "session_id": sid}
            for _, (rid, sid) in _snapshot.key_to_ref.items()
        ]

    def get_selected_entities() -> list[ScopeEntity]:
        return list(_snapshot.selected_entities)

    def get_entity_snapshot() -> EntitySelectionSnapshot:
        return EntitySelectionSnapshot(
            selected_entities=list(_snapshot.selected_entities),
            entity_to_effective_members={
                str(k): list(map(str, v))
                for k, v in dict(_snapshot.entity_to_effective_members).items()
            },
            expanded_session_keys=list(map(str, _snapshot.expanded_session_keys)),
            key_to_ref=dict(_snapshot.key_to_ref),
            events_index_df=_snapshot.events_index_df.copy(),
        )

    def get_key_to_ref() -> dict[str, tuple[str, str]]:
        return dict(_snapshot.key_to_ref)

    def get_events_index_df() -> pd.DataFrame:
        return _snapshot.events_index_df.copy()

    handle: SessionSelectorHandle = {
        "ui": ui,
        "store": artifact_store,
        "out": out,
        "refresh_signal": refresh_signal,
        "get_selected": get_selected,
        "get_selected_entities": get_selected_entities,
        "get_entity_snapshot": get_entity_snapshot,
        "get_key_to_ref": get_key_to_ref,
        "get_events_index_df": get_events_index_df,
        "load_selection": _reload,
    }
    if auto_display:
        from IPython.display import display

        display(ui)
    return handle
