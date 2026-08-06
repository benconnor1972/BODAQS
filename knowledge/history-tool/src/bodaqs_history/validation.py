"""Proportionate structural and secret-pattern validation for the private corpus."""

from __future__ import annotations

from pathlib import Path

import yaml

from .config import Config
from .privacy import load_patterns, redact_text


SKIP = {"README.md", "index.md", "chronological-overview.md", "open-questions.md", "uncertainties.md"}
REQUIRED = {"title", "kind", "status", "confidence", "source_refs", "review_status"}


def _front_matter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("missing YAML front matter")
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        raise ValueError("unterminated YAML front matter")
    value = yaml.safe_load(parts[1])
    if not isinstance(value, dict):
        raise ValueError("front matter must be a mapping")
    return value


def run_validate(config: Config) -> dict[str, int]:
    errors: list[str] = []
    titles: set[str] = set()
    checked = 0
    patterns = load_patterns(config.redact_patterns_file)
    for path in sorted(config.corpus.rglob("*.md")):
        if path.name in SKIP:
            continue
        checked += 1
        try:
            metadata = _front_matter(path)
        except (OSError, ValueError, yaml.YAMLError) as error:
            errors.append(f"{path}: {error}")
            continue
        missing = REQUIRED.difference(metadata)
        if missing:
            errors.append(f"{path}: missing front matter fields: {', '.join(sorted(missing))}")
        title = str(metadata.get("title", ""))
        if title in titles:
            errors.append(f"{path}: duplicate title: {title}")
        titles.add(title)
        text = path.read_text(encoding="utf-8")
        redacted, counts = redact_text(text, patterns)
        if counts and redacted != text:
            errors.append(f"{path}: configured redaction pattern(s) matched: {', '.join(sorted(counts))}")
    if errors:
        raise ValueError("Validation failed:\n- " + "\n- ".join(errors))
    return {"records_checked": checked, "errors": 0}
