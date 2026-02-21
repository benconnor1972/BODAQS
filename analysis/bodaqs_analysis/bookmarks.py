# -*- coding: utf-8 -*-
"""
bodaqs_analysis.bookmarks — Per-user bookmark store (JSON) for BODAQS analysis UIs.

Design goals:
- Dependency-light (stdlib only)
- Versioned JSON schema with tolerant round-trip (unknown fields preserved)
- Atomic saves (temp + replace)
- Optional drift warnings against a loaded session
"""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

STORE_SCHEMA = "bodaqs.bookmarks.store"
STORE_VERSION = 1

DEFAULT_FILENAME = "bookmarks_v1.json"
DEFAULT_DIRNAME = ".bodaqs"


# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------

def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_bookmark_id() -> str:
    return "bkmk_" + uuid.uuid4().hex


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


def _deep_get(d: Dict[str, Any], path: Tuple[str, ...], default=None):
    cur: Any = d
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _finite(x: Any) -> bool:
    try:
        v = float(x)
        return v == v and v not in (float("inf"), float("-inf"))
    except Exception:
        return False


# -----------------------------------------------------------------------------
# Validation
# -----------------------------------------------------------------------------

class BookmarkError(ValueError):
    pass


class BookmarkValidationError(BookmarkError):
    pass


def validate_store(obj: Dict[str, Any]) -> None:
    if not isinstance(obj, dict):
        raise BookmarkValidationError("Store must be an object")
    if obj.get("schema") != STORE_SCHEMA:
        raise BookmarkValidationError("Invalid store schema")
    if int(obj.get("version", -1)) != STORE_VERSION:
        raise BookmarkValidationError("Invalid store version")
    if not isinstance(obj.get("bookmarks"), list):
        raise BookmarkValidationError("'bookmarks' must be a list")


def validate_entry(entry: Dict[str, Any]) -> None:
    if not isinstance(entry, dict):
        raise BookmarkValidationError("Entry must be an object")

    if not isinstance(entry.get("bookmark_id"), str) or not entry["bookmark_id"]:
        raise BookmarkValidationError("bookmark_id required")

    sk = _deep_get(entry, ("scope", "session_key"))
    if not isinstance(sk, str) or not sk:
        raise BookmarkValidationError("scope.session_key required")

    t0 = _deep_get(entry, ("window", "t0"))
    t1 = _deep_get(entry, ("window", "t1"))

    if not _finite(t0) or not _finite(t1):
        raise BookmarkValidationError("t0/t1 must be finite")

    if float(t0) > float(t1):
        raise BookmarkValidationError("t0 must be <= t1")


# -----------------------------------------------------------------------------
# Store path helpers
# -----------------------------------------------------------------------------

def user_store_path() -> Path:
    return Path.home() / DEFAULT_DIRNAME / DEFAULT_FILENAME


# -----------------------------------------------------------------------------
# BookmarkStore
# -----------------------------------------------------------------------------

class BookmarkStore:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path).expanduser() if path else user_store_path()
        self._data: Optional[Dict[str, Any]] = None

    # ------------------ lifecycle ------------------

    def _empty(self) -> Dict[str, Any]:
        ts = now_utc_iso()
        return {
            "schema": STORE_SCHEMA,
            "version": STORE_VERSION,
            "created_at_utc": ts,
            "updated_at_utc": ts,
            "bookmarks": [],
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
        except Exception as e:
            try:
                shutil.copy2(self.path, self.path.with_suffix(".corrupt"))
            except Exception:
                pass
            self._data = self._empty()
            raise BookmarkError("Failed to load bookmark store") from e

        # Deduplicate IDs
        seen = set()
        cleaned = []
        for b in obj["bookmarks"]:
            bid = b.get("bookmark_id") if isinstance(b, dict) else None
            if isinstance(bid, str) and bid not in seen:
                seen.add(bid)
                cleaned.append(b)

        obj["bookmarks"] = cleaned
        self._data = obj

    def save(self) -> None:
        d = self.data
        d["updated_at_utc"] = now_utc_iso()

        validate_store(d)
        for b in d["bookmarks"]:
            validate_entry(b)

        _backup(self.path)
        _atomic_write(self.path, json.dumps(d, indent=2, ensure_ascii=False))

    # ------------------ CRUD ------------------

    def list(self, *, session_key: Optional[str] = None) -> List[Dict[str, Any]]:
        out = []
        for b in self.data["bookmarks"]:
            if not isinstance(b, dict):
                continue
            if session_key is not None:
                if _deep_get(b, ("scope", "session_key")) != session_key:
                    continue
            out.append(b)

        out.sort(key=lambda x: x.get("created_at_utc", ""), reverse=True)
        return out

    def get(self, bookmark_id: str) -> Optional[Dict[str, Any]]:
        for b in self.data["bookmarks"]:
            if b.get("bookmark_id") == bookmark_id:
                return b
        return None

    def add(self, entry: Dict[str, Any]) -> str:
        entry = dict(entry)

        entry.setdefault("bookmark_id", make_bookmark_id())
        entry.setdefault("created_at_utc", now_utc_iso())
        entry["updated_at_utc"] = now_utc_iso()
        entry.setdefault("private", True)

        validate_entry(entry)

        if self.get(entry["bookmark_id"]) is not None:
            raise BookmarkValidationError("Duplicate bookmark_id")

        self.data["bookmarks"].append(entry)
        return entry["bookmark_id"]

    def update(self, bookmark_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        b = self.get(bookmark_id)
        if b is None:
            raise BookmarkError("Bookmark not found")

        for k, v in patch.items():
            b[k] = v

        b["updated_at_utc"] = now_utc_iso()
        validate_entry(b)
        return b

    def delete(self, bookmark_id: str) -> bool:
        before = len(self.data["bookmarks"])
        self.data["bookmarks"] = [
            b for b in self.data["bookmarks"]
            if b.get("bookmark_id") != bookmark_id
        ]
        return len(self.data["bookmarks"]) != before

    # ------------------ widget helper ------------------

    def add_from_view(
        self,
        *,
        session: Dict[str, Any],
        session_key: str,
        t0: float,
        t1: float,
        view: Optional[Dict[str, Any]] = None,
        title: str = "",
        note: str = "",
        private: bool = True,
        time_col: str = "time_s",
    ) -> str:
        if t1 < t0:
            t0, t1 = t1, t0

        df = session.get("df")

        fp: Dict[str, Any] = {"time_col": time_col}
        try:
            if df is not None and time_col in df.columns:
                import pandas as pd, numpy as np
                tt = pd.to_numeric(df[time_col], errors="coerce").to_numpy(float)
                m = np.isfinite(tt)
                if m.any():
                    fp["time_min"] = float(tt[m].min())
                    fp["time_max"] = float(tt[m].max())
                    fp["n_rows"] = int(len(df))
        except Exception:
            pass

        entry = {
            "bookmark_id": make_bookmark_id(),
            "created_at_utc": now_utc_iso(),
            "updated_at_utc": now_utc_iso(),
            "title": title.strip(),
            "note": note.strip(),
            "scope": {
                "session_key": str(session_key),
                "fingerprint": fp,
            },
            "window": {"t0": float(t0), "t1": float(t1), "units": "s"},
            "view": dict(view or {}),
            "private": bool(private),
        }

        if not entry["title"]:
            entry.pop("title")
        if not entry["note"]:
            entry.pop("note")
        if not entry["view"]:
            entry.pop("view")

        return self.add(entry)


# -----------------------------------------------------------------------------
# Drift helpers
# -----------------------------------------------------------------------------

def check_drift(entry: Dict[str, Any], *, session: Dict[str, Any], time_col_default="time_s") -> List[str]:
    warnings: List[str] = []

    t0 = _deep_get(entry, ("window", "t0"))
    t1 = _deep_get(entry, ("window", "t1"))
    if not _finite(t0) or not _finite(t1):
        return ["Invalid bookmark window"]

    fp = _deep_get(entry, ("scope", "fingerprint"), {})
    time_col = fp.get("time_col") or time_col_default

    df = session.get("df")

    if isinstance(fp, dict):
        if "n_rows" in fp and hasattr(df, "shape"):
            if int(fp["n_rows"]) != int(df.shape[0]):
                warnings.append("Row count differs from original session")

        if "time_min" in fp and "time_max" in fp:
            if t1 < fp["time_min"] or t0 > fp["time_max"]:
                warnings.append("Bookmark outside original time range")

    try:
        if df is not None and time_col in df.columns:
            import pandas as pd, numpy as np
            tt = pd.to_numeric(df[time_col], errors="coerce").to_numpy(float)
            m = np.isfinite(tt)
            if m.any():
                cur_min, cur_max = float(tt[m].min()), float(tt[m].max())
                if t1 < cur_min or t0 > cur_max:
                    warnings.append("Bookmark outside current session time range")
    except Exception:
        pass

    return warnings


def coerce_restore_view(
    entry: Dict[str, Any],
    *,
    available_signals: List[str],
    available_event_types: List[str],
) -> Dict[str, Any]:
    view = entry.get("view")
    if not isinstance(view, dict):
        return {}

    out = dict(view)

    if isinstance(view.get("detail_signals"), list):
        avail = set(map(str, available_signals))
        out["detail_signals"] = [s for s in view["detail_signals"] if s in avail]

    if isinstance(view.get("event_types"), list):
        avail = set(map(str, available_event_types))
        out["event_types"] = [s for s in view["event_types"] if s in avail]

    return out
