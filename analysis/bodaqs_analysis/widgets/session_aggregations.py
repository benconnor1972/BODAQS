# -*- coding: utf-8 -*-
"""Local per-user store for persisted session aggregations."""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from bodaqs_analysis.widgets.contracts import (
    AggregationDefinition,
    EventSchemaPolicy,
    RegistryPolicy,
    SessionKey,
)

STORE_SCHEMA = "bodaqs.session_aggregations.store"
STORE_VERSION = 1
DEFAULT_FILENAME = "session_aggregations_v1.json"
DEFAULT_DIRNAME = ".bodaqs"


class SessionAggregationError(ValueError):
    pass


class SessionAggregationValidationError(SessionAggregationError):
    pass


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_aggregation_key() -> str:
    return "agg_" + uuid.uuid4().hex


def user_store_path() -> Path:
    return Path.home() / DEFAULT_DIRNAME / DEFAULT_FILENAME


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
        raise SessionAggregationValidationError(
            f"{field} must be one of: 'union', 'intersection', 'strict'"
        )


def _coerce_members(values: Sequence[str]) -> tuple[SessionKey, ...]:
    out: List[SessionKey] = []
    seen: set[str] = set()
    for v in values:
        sk = str(v)
        if sk in seen:
            continue
        seen.add(sk)
        out.append(sk)
    return tuple(out)


def validate_aggregation_definition(agg: Mapping[str, Any]) -> None:
    key = agg.get("aggregation_key")
    if not isinstance(key, str) or not key.strip():
        raise SessionAggregationValidationError("aggregation_key is required")

    title = agg.get("title")
    if not isinstance(title, str) or not title.strip():
        raise SessionAggregationValidationError("title is required")

    members = agg.get("member_session_keys")
    if not isinstance(members, (list, tuple)) or len(members) == 0:
        raise SessionAggregationValidationError("member_session_keys must be a non-empty list")

    for sk in members:
        if not is_valid_session_key(str(sk)):
            raise SessionAggregationValidationError(f"Invalid member session key: {sk!r}")

    _validate_policy(str(agg.get("registry_policy", "union")), field="registry_policy")
    _validate_policy(str(agg.get("event_schema_policy", "union")), field="event_schema_policy")


def validate_store(obj: Mapping[str, Any]) -> None:
    if not isinstance(obj, Mapping):
        raise SessionAggregationValidationError("Store must be an object")
    if obj.get("schema") != STORE_SCHEMA:
        raise SessionAggregationValidationError("Invalid store schema")
    if int(obj.get("version", -1)) != STORE_VERSION:
        raise SessionAggregationValidationError("Invalid store version")
    aggs = obj.get("aggregations")
    if not isinstance(aggs, list):
        raise SessionAggregationValidationError("'aggregations' must be a list")

    seen: set[str] = set()
    for a in aggs:
        if not isinstance(a, Mapping):
            raise SessionAggregationValidationError("aggregation entries must be objects")
        validate_aggregation_definition(a)
        key = str(a["aggregation_key"])
        if key in seen:
            raise SessionAggregationValidationError(f"Duplicate aggregation_key: {key}")
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
    d = asdict(defn)
    d["member_session_keys"] = list(defn.member_session_keys)
    return d


class SessionAggregationStore:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path).expanduser() if path else user_store_path()
        self._data: Optional[Dict[str, Any]] = None

    def _empty(self) -> Dict[str, Any]:
        ts = now_utc_iso()
        return {
            "schema": STORE_SCHEMA,
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
            validate_store(obj)
        except Exception as exc:
            try:
                shutil.copy2(self.path, self.path.with_suffix(".corrupt"))
            except Exception:
                pass
            self._data = self._empty()
            raise SessionAggregationError("Failed to load session aggregation store") from exc

        self._data = dict(obj)

    def save(self) -> None:
        d = self.data
        d["updated_at_utc"] = now_utc_iso()

        validate_store(d)
        _backup(self.path)
        _atomic_write(self.path, json.dumps(d, indent=2, ensure_ascii=False))

    def list(self) -> List[AggregationDefinition]:
        out: List[AggregationDefinition] = []
        for row in self.data.get("aggregations", []):
            if isinstance(row, Mapping):
                out.append(definition_from_mapping(row))
        out.sort(key=lambda x: x.updated_at_utc or x.created_at_utc, reverse=True)
        return out

    def get(self, aggregation_key: str) -> Optional[AggregationDefinition]:
        for a in self.list():
            if a.aggregation_key == str(aggregation_key):
                return a
        return None

    def _upsert(self, defn: AggregationDefinition) -> None:
        rows = list(self.data.get("aggregations", []))
        key = str(defn.aggregation_key)
        repl = definition_to_mapping(defn)
        replaced = False
        for idx, row in enumerate(rows):
            if isinstance(row, Mapping) and str(row.get("aggregation_key")) == key:
                rows[idx] = repl
                replaced = True
                break
        if not replaced:
            rows.append(repl)
        self.data["aggregations"] = rows

    def add(self, defn: AggregationDefinition) -> AggregationDefinition:
        if self.get(defn.aggregation_key) is not None:
            raise SessionAggregationValidationError(
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
            raise SessionAggregationError("Aggregation not found")

        obj = definition_to_mapping(current)
        for k, v in patch.items():
            obj[k] = v

        obj["aggregation_key"] = str(current.aggregation_key)
        obj["updated_at_utc"] = now_utc_iso()
        if "member_session_keys" in obj:
            obj["member_session_keys"] = list(_coerce_members([str(x) for x in obj["member_session_keys"]]))

        validate_aggregation_definition(obj)
        updated = definition_from_mapping(obj)
        self._upsert(updated)
        return updated

    def delete(self, aggregation_key: str) -> bool:
        key = str(aggregation_key)
        before = len(self.data.get("aggregations", []))
        self.data["aggregations"] = [
            a
            for a in self.data.get("aggregations", [])
            if not (isinstance(a, Mapping) and str(a.get("aggregation_key")) == key)
        ]
        return len(self.data.get("aggregations", [])) != before
