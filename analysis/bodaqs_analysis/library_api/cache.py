"""Small in-memory cache helpers for the Library API adapter."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Mapping


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float | None


@dataclass
class PersistentCacheRecord:
    namespace: str
    key: str
    value: Any
    metadata: dict[str, Any]
    created_at_epoch_s: float
    expires_at_epoch_s: float | None

    def remaining_ttl_s(self) -> float | None:
        if self.expires_at_epoch_s is None:
            return None
        return max(0.0, self.expires_at_epoch_s - time.time())


class InMemoryLruCache:
    """Bounded, TTL-aware process-local cache.

    The cache intentionally deep-copies values on read/write. API payloads are
    mutable dictionaries, and callers should not be able to mutate cached state
    by accident.
    """

    def __init__(self, *, max_entries: int = 512, default_ttl_s: float | None = 900.0) -> None:
        self.max_entries = max(1, int(max_entries))
        self.default_ttl_s = default_ttl_s
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = RLock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get(self, namespace: str, key: str) -> Any | None:
        cache_key = self._cache_key(namespace, key)
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(cache_key)
            if entry is None:
                self._misses += 1
                return None
            if entry.expires_at is not None and entry.expires_at <= now:
                self._entries.pop(cache_key, None)
                self._misses += 1
                return None
            self._entries.move_to_end(cache_key)
            self._hits += 1
            return copy.deepcopy(entry.value)

    def has(self, namespace: str, key: str) -> bool:
        """Return whether a live cache entry exists without counting as a hit."""

        cache_key = self._cache_key(namespace, key)
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(cache_key)
            if entry is None:
                return False
            if entry.expires_at is not None and entry.expires_at <= now:
                self._entries.pop(cache_key, None)
                return False
            return True

    def set(self, namespace: str, key: str, value: Any, *, ttl_s: float | None = None) -> None:
        cache_key = self._cache_key(namespace, key)
        ttl = self.default_ttl_s if ttl_s is None else ttl_s
        expires_at = None if ttl is None else time.monotonic() + max(0.0, float(ttl))
        with self._lock:
            self._entries[cache_key] = _CacheEntry(value=copy.deepcopy(value), expires_at=expires_at)
            self._entries.move_to_end(cache_key)
            self._prune_locked()

    def get_or_set(
        self,
        namespace: str,
        key: str,
        factory: Callable[[], Any],
        *,
        ttl_s: float | None = None,
    ) -> Any:
        cached = self.get(namespace, key)
        if cached is not None:
            return cached
        value = factory()
        self.set(namespace, key, value, ttl_s=ttl_s)
        return copy.deepcopy(value)

    def invalidate_namespace(self, namespace: str) -> int:
        prefix = f"{namespace}:"
        with self._lock:
            keys = [key for key in self._entries if key.startswith(prefix)]
            for key in keys:
                self._entries.pop(key, None)
            return len(keys)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            namespaces: dict[str, int] = {}
            for cache_key in self._entries:
                namespace = cache_key.split(":", 1)[0]
                namespaces[namespace] = namespaces.get(namespace, 0) + 1
            return {
                "entry_count": len(self._entries),
                "max_entries": self.max_entries,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "namespaces": {
                    namespace: {"entry_count": count}
                    for namespace, count in sorted(namespaces.items())
                },
            }

    def _prune_locked(self) -> None:
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
            self._evictions += 1

    @staticmethod
    def _cache_key(namespace: str, key: str) -> str:
        return f"{namespace}:{key}"


def stable_cache_digest(payload: Any) -> str:
    """Return a stable SHA-256 digest for a JSON-like payload."""

    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


PERSISTENT_CACHE_ENTRY_SCHEMA = "bodaqs.library_api.persistent_cache_entry"
PERSISTENT_CACHE_ENTRY_VERSION = 1


class PersistentJsonCache:
    """Small JSON-backed cache store for restart-friendly API payloads."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()

    def get(self, namespace: str, key: str) -> PersistentCacheRecord | None:
        path = self._entry_path(namespace, key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        record = self._record_from_payload(namespace, key, payload)
        if record is None:
            return None
        if self._is_expired(record):
            self._unlink_silent(path)
            return None
        return record

    def has(self, namespace: str, key: str) -> bool:
        return self.get(namespace, key) is not None

    def set(
        self,
        namespace: str,
        key: str,
        value: Any,
        *,
        ttl_s: float | None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        now = time.time()
        expires_at = None if ttl_s is None else now + max(0.0, float(ttl_s))
        path = self._entry_path(namespace, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": PERSISTENT_CACHE_ENTRY_SCHEMA,
            "version": PERSISTENT_CACHE_ENTRY_VERSION,
            "namespace": str(namespace),
            "key": str(key),
            "created_at_epoch_s": now,
            "expires_at_epoch_s": expires_at,
            "metadata": dict(metadata or {}),
            "value": copy.deepcopy(value),
        }
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp_path, path)

    def prune_namespace(self, namespace: str, *, max_entries: int | None = None) -> dict[str, int]:
        namespace_dir = self._namespace_dir(namespace)
        summary = {
            "removed_expired": 0,
            "removed_invalid": 0,
            "removed_excess": 0,
            "kept": 0,
        }
        if not namespace_dir.exists():
            return summary

        records: list[tuple[Path, PersistentCacheRecord]] = []
        for path in namespace_dir.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                if self._unlink_silent(path):
                    summary["removed_invalid"] += 1
                continue
            record = self._record_from_payload(namespace, path.stem, payload)
            if record is None:
                if self._unlink_silent(path):
                    summary["removed_invalid"] += 1
                continue
            if self._is_expired(record):
                if self._unlink_silent(path):
                    summary["removed_expired"] += 1
                continue
            records.append((path, record))

        if max_entries is not None:
            max_count = max(0, int(max_entries))
            if len(records) > max_count:
                records.sort(key=lambda item: item[1].created_at_epoch_s)
                excess_count = len(records) - max_count
                for path, _record in records[:excess_count]:
                    if self._unlink_silent(path):
                        summary["removed_excess"] += 1
                records = records[excess_count:]

        summary["kept"] = len(records)
        return summary

    def iter_records(self, namespace: str) -> list[PersistentCacheRecord]:
        namespace_dir = self._namespace_dir(namespace)
        if not namespace_dir.exists():
            return []
        records: list[PersistentCacheRecord] = []
        for path in sorted(namespace_dir.glob("*.json"), key=lambda item: item.name):
            record = self.get(namespace, path.stem)
            if record is not None:
                records.append(record)
        return records

    def delete(self, namespace: str, key: str) -> bool:
        """Delete one cache entry without disturbing sibling entries."""

        return self._unlink_silent(self._entry_path(namespace, key))

    def invalidate_namespace(self, namespace: str) -> int:
        namespace_dir = self._namespace_dir(namespace)
        if not namespace_dir.exists():
            return 0
        count = 0
        for path in namespace_dir.glob("*.json"):
            if self._unlink_silent(path):
                count += 1
        return count

    def stats(self) -> dict[str, Any]:
        namespaces: dict[str, dict[str, int]] = {}
        if self.root.exists():
            namespace_dirs = [path for path in self.root.iterdir() if path.is_dir()]
            for namespace_dir in sorted(namespace_dirs, key=lambda path: path.name):
                total = 0
                live = 0
                expired = 0
                for path in namespace_dir.glob("*.json"):
                    total += 1
                    try:
                        payload = json.loads(path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        continue
                    record = self._record_from_payload(namespace_dir.name, path.stem, payload)
                    if record is None:
                        continue
                    if self._is_expired(record):
                        expired += 1
                    else:
                        live += 1
                namespaces[namespace_dir.name] = {
                    "entry_count": live,
                    "file_count": total,
                    "expired_count": expired,
                }
        return {
            "root": str(self.root),
            "namespaces": namespaces,
            "entry_count": sum(namespace["entry_count"] for namespace in namespaces.values()),
            "file_count": sum(namespace["file_count"] for namespace in namespaces.values()),
            "expired_count": sum(namespace["expired_count"] for namespace in namespaces.values()),
        }

    def _entry_path(self, namespace: str, key: str) -> Path:
        return self._namespace_dir(namespace) / f"{self._safe_component(key)}.json"

    def _namespace_dir(self, namespace: str) -> Path:
        return self.root / self._safe_component(namespace)

    @staticmethod
    def _safe_component(value: str) -> str:
        text = str(value or "").strip()
        safe = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in text)
        return safe or "cache"

    @staticmethod
    def _record_from_payload(namespace: str, key: str, payload: Mapping[str, Any]) -> PersistentCacheRecord | None:
        if not isinstance(payload, dict):
            return None
        if payload.get("schema") != PERSISTENT_CACHE_ENTRY_SCHEMA:
            return None
        if int(payload.get("version") or -1) != PERSISTENT_CACHE_ENTRY_VERSION:
            return None
        if str(payload.get("namespace") or "") != str(namespace):
            return None
        if str(payload.get("key") or "") != str(key):
            return None
        metadata = payload.get("metadata")
        return PersistentCacheRecord(
            namespace=str(namespace),
            key=str(key),
            value=copy.deepcopy(payload.get("value")),
            metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
            created_at_epoch_s=float(payload.get("created_at_epoch_s") or 0.0),
            expires_at_epoch_s=(
                None
                if payload.get("expires_at_epoch_s") is None
                else float(payload.get("expires_at_epoch_s") or 0.0)
            ),
        )

    @staticmethod
    def _is_expired(record: PersistentCacheRecord) -> bool:
        return record.expires_at_epoch_s is not None and record.expires_at_epoch_s <= time.time()

    @staticmethod
    def _unlink_silent(path: Path) -> bool:
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError:
            return False
