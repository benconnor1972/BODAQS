"""Identity helpers for Library API resources."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable


_DEFAULT_MAX_LENGTH = 72
_ID_CHARS_RE = re.compile(r"[^a-z0-9]+")
_HYPHEN_RE = re.compile(r"-+")
_OBJECT_ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,70}[a-z0-9])?$")


def derive_object_id(
    display_name: str,
    *,
    fallback: str = "item",
    max_length: int = _DEFAULT_MAX_LENGTH,
) -> str:
    """Derive a filename-safe, URL-friendly object id from a display name."""

    fallback_id = _slugify(fallback, max_length=max_length) or "item"
    value = _slugify(display_name, max_length=max_length)
    return value or fallback_id


def make_unique_object_id(
    display_name: str,
    existing_ids: Iterable[str],
    *,
    fallback: str = "item",
    max_length: int = _DEFAULT_MAX_LENGTH,
) -> str:
    """Derive an object id and append a numeric suffix if needed."""

    existing = {str(item) for item in existing_ids}
    base = derive_object_id(display_name, fallback=fallback, max_length=max_length)
    if base not in existing:
        return base

    for suffix_num in range(2, 10000):
        suffix = f"-{suffix_num}"
        stem_limit = max(1, max_length - len(suffix))
        stem = base[:stem_limit].strip("-") or derive_object_id(
            fallback,
            fallback="item",
            max_length=stem_limit,
        )
        candidate = f"{stem}{suffix}"
        if candidate not in existing:
            return candidate

    raise ValueError("Could not derive a unique object id")


def make_session_key(run_id: str, session_id: str) -> str:
    run = str(run_id).strip()
    session = str(session_id).strip()
    if not run or not session:
        raise ValueError("run_id and session_id must be non-empty")
    return f"{run}::{session}"


def make_session_ref_id(library_id: str, session_key: str) -> str:
    library = str(library_id).strip()
    key = str(session_key).strip()
    if not library or not key:
        raise ValueError("library_id and session_key must be non-empty")
    return f"{library}|||{key}"


def is_valid_object_id(value: str) -> bool:
    return bool(_OBJECT_ID_RE.fullmatch(str(value or "")))


def parse_session_key(session_key: str) -> tuple[str, str]:
    text = str(session_key)
    parts = text.split("::", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Invalid session_key: {session_key!r}")
    return parts[0], parts[1]


def _slugify(value: str, *, max_length: int) -> str:
    if max_length < 1:
        raise ValueError("max_length must be >= 1")

    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = _ID_CHARS_RE.sub("-", text)
    text = _HYPHEN_RE.sub("-", text).strip("-")
    if len(text) > max_length:
        text = text[:max_length].strip("-")
    return text
