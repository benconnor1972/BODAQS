# -*- coding: utf-8 -*-
"""Bookmark list/label helpers for session window browser widget."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from bodaqs_analysis.bookmarks import BookmarkStore


BOOKMARK_N_RE = re.compile(r"^\s*Bookmark\s+(\d+)\s*$", re.IGNORECASE)


def deep_get(d: Mapping[str, Any], path: Sequence[str], default=None):
    cur: Any = d
    for k in path:
        if not isinstance(cur, Mapping) or k not in cur:
            return default
        cur = cur[k]
    return cur


def format_bookmark_label(entry: Mapping[str, Any]) -> str:
    title = str(entry.get("title") or "").strip()
    t0 = float(deep_get(entry, ("window", "t0"), 0.0))
    t1 = float(deep_get(entry, ("window", "t1"), 0.0))
    base = title if title else f"{t0:.2f}-{t1:.2f}s"
    return f"{base}  ({t0:.2f}-{t1:.2f}s)"


def next_default_bookmark_title(entries: Sequence[Mapping[str, Any]]) -> str:
    nmax = 0
    for e in entries:
        t = str(e.get("title") or "")
        m = BOOKMARK_N_RE.match(t)
        if m:
            try:
                nmax = max(nmax, int(m.group(1)))
            except Exception:
                pass
    return f"Bookmark {nmax + 1}"


def build_bookmark_options(
    *,
    store: BookmarkStore,
    session_key: str,
) -> list[tuple[str, str]]:
    entries = store.list(session_key=str(session_key))
    opts: list[tuple[str, str]] = [("(New bookmark...)", "")]
    for e in entries:
        if not isinstance(e, Mapping):
            continue
        bid = e.get("bookmark_id")
        if not isinstance(bid, str) or not bid:
            continue
        opts.append((format_bookmark_label(e), bid))
    return opts

