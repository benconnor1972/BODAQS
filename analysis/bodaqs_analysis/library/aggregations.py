# -*- coding: utf-8 -*-
"""Aggregation stores for canonical and local library workflows."""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence

import pandas as pd

from bodaqs_analysis.artifacts import ArtifactStore, list_runs, list_sessions
from bodaqs_analysis.widgets.contracts import (
    AggregationDefinition,
    EventSchemaPolicy,
    RegistryPolicy,
    SessionKey,
)

LOCAL_STORE_SCHEMA = "bodaqs.session_aggregations.store"
CANONICAL_STORE_SCHEMA = "bodaqs.library_aggregations.store"
STORE_VERSION = 1
LOCAL_DEFAULT_FILENAME = "session_aggregations_v1.json"
CANONICAL_DEFAULT_FILENAME = "aggregations_v1.json"
DEFAULT_DIRNAME = ".bodaqs"


class AggregationStoreError(ValueError):
    pass


class AggregationStoreValidationError(AggregationStoreError):
    pass


class AggregationStore(Protocol):
    path: Path

    def load(self) -> None: ...

    def save(self) -> None: ...

    def list(self) -> List[AggregationDefinition]: ...

    def get(self, aggregation_key: str) -> Optional[AggregationDefinition]: ...

    def create(
        self,
        *,
        title: str,
        member_session_keys: Sequence[str],
        registry_policy: RegistryPolicy = "union",
        event_schema_policy: EventSchemaPolicy = "union",
        note: str | None = None,
        aggregation_key: str | None = None,
    ) -> AggregationDefinition: ...

    def update(self, aggregation_key: str, *, patch: Mapping[str, Any]) -> AggregationDefinition: ...

    def delete(self, aggregation_key: str) -> bool: ...


class AggregationProvider(Protocol):
    def list(self) -> List[AggregationDefinition]: ...

    def get(self, aggregation_key: str) -> Optional[AggregationDefinition]: ...


@dataclass(frozen=True)
class AggregationCatalogRow:
    aggregation_key: str
    scope: str
    title: str
    n_members: int
    n_resolved_members: int
    missing_member_count: int
    registry_policy: RegistryPolicy
    event_schema_policy: EventSchemaPolicy
    created_at_utc: str | None
    updated_at_utc: str | None
    note: str | None
    member_session_keys: tuple[str, ...]


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_aggregation_key() -> str:
    return "agg_" + uuid.uuid4().hex


def user_store_path() -> Path:
    return Path.home() / DEFAULT_DIRNAME / LOCAL_DEFAULT_FILENAME


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


def is_valid_session_key(session_key: str) -> bool:
    if not isinstance(session_key, str):
        return False
    if "::" not in session_key:
        return False
    run_id, session_id = session_key.split("::", 1)
    return bool(run_id.strip()) and bool(session_id.strip())


def _validate_policy(policy: str, *, field: str) -> None:
    if policy not in {"union", "intersection", "strict"}:
        raise AggregationStoreValidationError(
            f"{field} must be one of: 'union', 'intersection', 'strict'"
        )


def _coerce_members(values: Sequence[str]) -> tuple[SessionKey, ...]:
    out: List[SessionKey] = []
    seen: set[str] = set()
    for value in values:
        session_key = str(value)
        if session_key in seen:
            continue
        seen.add(session_key)
        out.append(session_key)
    return tuple(out)


def validate_aggregation_definition(agg: Mapping[str, Any]) -> None:
    key = agg.get("aggregation_key")
    if not isinstance(key, str) or not key.strip():
        raise AggregationStoreValidationError("aggregation_key is required")

    title = agg.get("title")
    if not isinstance(title, str) or not title.strip():
        raise AggregationStoreValidationError("title is required")

    members = agg.get("member_session_keys")
    if not isinstance(members, (list, tuple)) or len(members) == 0:
        raise AggregationStoreValidationError("member_session_keys must be a non-empty list")

    for session_key in members:
        if not is_valid_session_key(str(session_key)):
            raise AggregationStoreValidationError(f"Invalid member session key: {session_key!r}")

    _validate_policy(str(agg.get("registry_policy", "union")), field="registry_policy")
    _validate_policy(str(agg.get("event_schema_policy", "union")), field="event_schema_policy")


def validate_store(obj: Mapping[str, Any], *, schema: str) -> None:
    if not isinstance(obj, Mapping):
        raise AggregationStoreValidationError("Store must be an object")
    if obj.get("schema") != schema:
        raise AggregationStoreValidationError("Invalid store schema")
    if int(obj.get("version", -1)) != STORE_VERSION:
        raise AggregationStoreValidationError("Invalid store version")
    aggregations = obj.get("aggregations")
    if not isinstance(aggregations, list):
        raise AggregationStoreValidationError("'aggregations' must be a list")

    seen: set[str] = set()
    for row in aggregations:
        if not isinstance(row, Mapping):
            raise AggregationStoreValidationError("aggregation entries must be objects")
        validate_aggregation_definition(row)
        key = str(row["aggregation_key"])
        if key in seen:
            raise AggregationStoreValidationError(f"Duplicate aggregation_key: {key}")
        seen.add(key)


def definition_from_mapping(data: Mapping[str, Any]) -> AggregationDefinition:
    validate_aggregation_definition(data)
    members = _coerce_members([str(x) for x in data.get("member_session_keys", [])])
    return AggregationDefinition(
        aggregation_key=str(data["aggregation_key"]),
        title=str(data["title"]),
        member_session_keys=members,
        registry_policy=str(data.get("registry_policy", "union")),  # type: ignore[arg-type]
        event_schema_policy=str(data.get("event_schema_policy", "union")),  # type: ignore[arg-type]
        created_at_utc=str(data.get("created_at_utc", "")),
        updated_at_utc=str(data.get("updated_at_utc", "")),
        note=(None if data.get("note") is None else str(data.get("note"))),
    )


def definition_to_mapping(defn: AggregationDefinition) -> Dict[str, Any]:
    data = asdict(defn)
    data["member_session_keys"] = list(defn.member_session_keys)
    return data


class JsonAggregationStore:
    def __init__(self, *, path: Path, schema: str):
        self.path = Path(path).expanduser()
        self.schema = str(schema)
        self._data: Optional[Dict[str, Any]] = None

    def _empty(self) -> Dict[str, Any]:
        ts = now_utc_iso()
        return {
            "schema": self.schema,
            "version": STORE_VERSION,
            "created_at_utc": ts,
            "updated_at_utc": ts,
            "aggregations": [],
        }

    @property
    def data(self) -> Dict[str, Any]:
        if self._data is None:
            self._data = self._empty()
        return self._data

    def load(self) -> None:
        if not self.path.exists():
            self._data = self._empty()
            return

        try:
            obj = json.loads(self.path.read_text(encoding="utf-8"))
            validate_store(obj, schema=self.schema)
        except Exception as exc:
            try:
                shutil.copy2(self.path, self.path.with_suffix(".corrupt"))
            except Exception:
                pass
            self._data = self._empty()
            raise AggregationStoreError(f"Failed to load aggregation store at {self.path}") from exc

        self._data = dict(obj)

    def save(self) -> None:
        payload = self.data
        payload["updated_at_utc"] = now_utc_iso()
        validate_store(payload, schema=self.schema)
        _backup(self.path)
        _atomic_write(self.path, json.dumps(payload, indent=2, ensure_ascii=False))

    def list(self) -> List[AggregationDefinition]:
        out: List[AggregationDefinition] = []
        for row in self.data.get("aggregations", []):
            if isinstance(row, Mapping):
                out.append(definition_from_mapping(row))
        out.sort(key=lambda x: x.updated_at_utc or x.created_at_utc, reverse=True)
        return out

    def get(self, aggregation_key: str) -> Optional[AggregationDefinition]:
        for agg in self.list():
            if agg.aggregation_key == str(aggregation_key):
                return agg
        return None

    def _upsert(self, defn: AggregationDefinition) -> None:
        rows = list(self.data.get("aggregations", []))
        key = str(defn.aggregation_key)
        replacement = definition_to_mapping(defn)
        replaced = False
        for idx, row in enumerate(rows):
            if isinstance(row, Mapping) and str(row.get("aggregation_key")) == key:
                rows[idx] = replacement
                replaced = True
                break
        if not replaced:
            rows.append(replacement)
        self.data["aggregations"] = rows

    def add(self, defn: AggregationDefinition) -> AggregationDefinition:
        if self.get(defn.aggregation_key) is not None:
            raise AggregationStoreValidationError(
                f"Aggregation already exists: {defn.aggregation_key}"
            )
        ts = now_utc_iso()
        normalized = AggregationDefinition(
            aggregation_key=str(defn.aggregation_key),
            title=str(defn.title),
            member_session_keys=_coerce_members(defn.member_session_keys),
            registry_policy=defn.registry_policy,
            event_schema_policy=defn.event_schema_policy,
            created_at_utc=(defn.created_at_utc or ts),
            updated_at_utc=(defn.updated_at_utc or ts),
            note=defn.note,
        )
        validate_aggregation_definition(definition_to_mapping(normalized))
        self._upsert(normalized)
        return normalized

    def create(
        self,
        *,
        title: str,
        member_session_keys: Sequence[str],
        registry_policy: RegistryPolicy = "union",
        event_schema_policy: EventSchemaPolicy = "union",
        note: str | None = None,
        aggregation_key: str | None = None,
    ) -> AggregationDefinition:
        key = str(aggregation_key or make_aggregation_key())
        defn = AggregationDefinition(
            aggregation_key=key,
            title=str(title).strip() or key,
            member_session_keys=_coerce_members([str(x) for x in member_session_keys]),
            registry_policy=registry_policy,
            event_schema_policy=event_schema_policy,
            created_at_utc=now_utc_iso(),
            updated_at_utc=now_utc_iso(),
            note=(None if note is None else str(note).strip()),
        )
        return self.add(defn)

    def update(self, aggregation_key: str, *, patch: Mapping[str, Any]) -> AggregationDefinition:
        current = self.get(str(aggregation_key))
        if current is None:
            raise AggregationStoreError("Aggregation not found")

        obj = definition_to_mapping(current)
        for key, value in patch.items():
            obj[key] = value

        obj["aggregation_key"] = str(current.aggregation_key)
        obj["updated_at_utc"] = now_utc_iso()
        if "member_session_keys" in obj:
            obj["member_session_keys"] = list(
                _coerce_members([str(x) for x in obj["member_session_keys"]])
            )

        validate_aggregation_definition(obj)
        updated = definition_from_mapping(obj)
        self._upsert(updated)
        return updated

    def delete(self, aggregation_key: str) -> bool:
        key = str(aggregation_key)
        before = len(self.data.get("aggregations", []))
        self.data["aggregations"] = [
            row
            for row in self.data.get("aggregations", [])
            if not (isinstance(row, Mapping) and str(row.get("aggregation_key")) == key)
        ]
        return len(self.data.get("aggregations", [])) != before


class LocalAggregationStore(JsonAggregationStore):
    def __init__(self, path: Optional[Path] = None):
        super().__init__(path=(Path(path).expanduser() if path else user_store_path()), schema=LOCAL_STORE_SCHEMA)


class CanonicalAggregationStore(JsonAggregationStore):
    def __init__(
        self,
        *,
        artifact_store: ArtifactStore | None = None,
        path: Path | None = None,
    ):
        resolved_path = Path(path).expanduser() if path else (
            artifact_store.path_canonical_aggregations() if artifact_store else ArtifactStore().path_canonical_aggregations()
        )
        super().__init__(path=resolved_path, schema=CANONICAL_STORE_SCHEMA)


def bootstrap_canonical_from_local(
    *,
    canonical_store: CanonicalAggregationStore,
    artifact_store: ArtifactStore | None = None,
    local_store: LocalAggregationStore | None = None,
) -> int:
    local = local_store or LocalAggregationStore()
    try:
        canonical_store.load()
    except Exception:
        pass

    if canonical_store.list():
        return 0

    try:
        local.load()
    except Exception:
        return 0

    valid_session_keys: set[str] | None = None
    if artifact_store is not None:
        valid_session_keys = set()
        for run_id in list_runs(artifact_store):
            for session_id in list_sessions(artifact_store, run_id):
                valid_session_keys.add(f"{run_id}::{session_id}")

    migrated = 0
    for agg in local.list():
        if valid_session_keys is not None:
            members = {str(session_key) for session_key in agg.member_session_keys}
            if not members:
                continue
            if not members.issubset(valid_session_keys):
                continue
        try:
            canonical_store.add(agg)
            migrated += 1
        except Exception:
            continue

    if migrated:
        canonical_store.save()
    return migrated


def make_default_aggregation_store(
    *,
    artifact_store: ArtifactStore | None = None,
) -> CanonicalAggregationStore:
    canonical = CanonicalAggregationStore(artifact_store=artifact_store)
    bootstrap_canonical_from_local(canonical_store=canonical, artifact_store=artifact_store)
    return canonical


def build_aggregation_catalog_df(
    *,
    aggregation_store: AggregationProvider,
    scope: str,
    artifact_store: ArtifactStore | None = None,
) -> pd.DataFrame:
    valid_session_keys: set[str] = set()
    if artifact_store is not None:
        for run_id in list_runs(artifact_store):
            for session_id in list_sessions(artifact_store, run_id):
                valid_session_keys.add(f"{run_id}::{session_id}")

    rows: list[dict[str, Any]] = []
    for agg in aggregation_store.list():
        members = tuple(map(str, agg.member_session_keys))
        n_members = len(members)
        n_resolved = (
            sum(1 for session_key in members if session_key in valid_session_keys)
            if valid_session_keys
            else n_members
        )
        rows.append(
            asdict(
                AggregationCatalogRow(
                    aggregation_key=str(agg.aggregation_key),
                    scope=str(scope),
                    title=str(agg.title),
                    n_members=n_members,
                    n_resolved_members=n_resolved,
                    missing_member_count=max(0, n_members - n_resolved),
                    registry_policy=agg.registry_policy,
                    event_schema_policy=agg.event_schema_policy,
                    created_at_utc=(agg.created_at_utc or None),
                    updated_at_utc=(agg.updated_at_utc or None),
                    note=agg.note,
                    member_session_keys=members,
                )
            )
        )

    return pd.DataFrame(rows)
