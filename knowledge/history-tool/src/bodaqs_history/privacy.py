"""Local-only redaction before any optional external request."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Pattern:
    name: str
    expression: re.Pattern[str]
    replacement: str


DEFAULT_PATTERNS = (
    Pattern("openai_api_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b"), "<OPENAI_API_KEY>"),
    Pattern("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"), "<GITHUB_TOKEN>"),
    Pattern("bearer_token", re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._-]{16,}"), r"\1<TOKEN>"),
    Pattern("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "<EMAIL>"),
    Pattern("windows_user_path", re.compile(r"(?i)[A-Z]:\\Users\\[^\\\s]+"), "<WINDOWS_USER_PATH>"),
)


def load_patterns(path: Path | None) -> tuple[Pattern, ...]:
    if path is None:
        return DEFAULT_PATTERNS
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    custom = []
    for item in raw:
        custom.append(
            Pattern(
                name=str(item["name"]),
                expression=re.compile(str(item["regex"])),
                replacement=str(item.get("replacement", f"<{item['name'].upper()}>")),
            )
        )
    return DEFAULT_PATTERNS + tuple(custom)


def redact_text(text: str, patterns: tuple[Pattern, ...]) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    redacted = text
    for pattern in patterns:
        redacted, count = pattern.expression.subn(pattern.replacement, redacted)
        if count:
            counts[pattern.name] = counts.get(pattern.name, 0) + count
    return redacted, counts
