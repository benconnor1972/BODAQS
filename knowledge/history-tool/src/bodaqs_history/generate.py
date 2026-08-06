"""Publish draft copies into a private corpus without touching reviewed records."""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from .config import Config


def _metadata(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    return yaml.safe_load(text.split("---\n", 2)[1]) or {}


def run_generate(config: Config) -> dict[str, int]:
    drafts = sorted((config.private_work / "drafts").glob("*.md"))
    draft_destination = config.corpus / "drafts"
    draft_destination.mkdir(parents=True, exist_ok=True)
    for draft in drafts:
        shutil.copy2(draft, draft_destination / draft.name)
    records = []
    for path in sorted(config.corpus.rglob("*.md")):
        if path.name in {"README.md", "index.md", "chronological-overview.md", "open-questions.md", "uncertainties.md"}:
            continue
        metadata = _metadata(path)
        if metadata:
            records.append((path, metadata))
    index_lines = ["# BODAQS engineering knowledge index", "", "All generated records are drafts until reviewed.", "", "| Record | Kind | Status | Confidence |", "|---|---|---|---|"]
    for path, metadata in records:
        relative = path.relative_to(config.corpus).as_posix()
        index_lines.append(f"| [{metadata.get('title', path.stem)}]({relative}) | {metadata.get('kind', '')} | {metadata.get('status', '')} | {metadata.get('confidence', '')} |")
    (config.corpus / "index.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    open_items = [metadata.get("title", path.stem) for path, metadata in records if metadata.get("kind") == "open-question" or metadata.get("status") in {"open", "uncertain"}]
    (config.corpus / "open-questions.md").write_text("# Open questions\n\n" + "\n".join(f"- {item}" for item in open_items) + "\n", encoding="utf-8")
    (config.corpus / "uncertainties.md").write_text("# Uncertainties\n\nReview records with `status: uncertain` or `review_status: needs-more-evidence`.\n", encoding="utf-8")
    (config.corpus / "chronological-overview.md").write_text("# Chronological overview\n\nThis overview is intentionally built during review; generated drafts retain their source date ranges.\n", encoding="utf-8")
    readme = config.corpus / "README.md"
    if not readme.exists():
        readme.write_text("# BODAQS engineering history\n\nPrivate working corpus. Records are drafts until reviewed.\n", encoding="utf-8")
    return {"drafts_published": len(drafts), "records_indexed": len(records)}
