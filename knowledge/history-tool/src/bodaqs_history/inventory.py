"""Read-only source inventory for the formats found in the initial archive."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Iterable

from .common import ensure_directory, read_json, sha256_file, utc_now, write_json
from .config import Config, Source


def source_files(source: Source) -> Iterable[Path]:
    """Return only potential conversation files, never Codex caches or credentials."""
    if source.path.is_file():
        yield source.path
        return
    if not source.path.exists():
        return
    if source.type == "codex_sessions":
        sessions = source.path / "sessions"
        if sessions.exists():
            yield from sessions.rglob("rollout-*.jsonl")
        return
    yield from source.path.rglob("*.json")
    yield from source.path.rglob("*.jsonl")
    yield from source.path.rglob("*.zip")


def detect_format(path: Path, source_type: str) -> str:
    if source_type == "chatgpt_zip" or path.suffix.lower() == ".zip":
        return "chatgpt_zip"
    if source_type == "codex_sessions" and path.name.startswith("rollout-"):
        return "codex_rollout_jsonl"
    if path.suffix.lower() == ".jsonl":
        return "jsonl_unknown"
    if path.suffix.lower() == ".json":
        return "json_unknown"
    return "unsupported"


def run_inventory(config: Config) -> dict:
    manifest_path = config.private_work / "manifest" / "source-manifest.json"
    previous = read_json(manifest_path, {})
    previous_hashes = {entry.get("path"): entry.get("sha256") for entry in previous.get("entries", [])}
    entries = []
    formats: Counter[str] = Counter()
    for source in config.sources:
        if not source.path.exists():
            entries.append({"source_id": source.id, "path": str(source.path), "status": "missing"})
            continue
        for path in source_files(source):
            detected = detect_format(path, source.type)
            formats[detected] += 1
            stat = path.stat()
            entry = {
                    "source_id": source.id,
                    "source_label": source.label,
                    "path": str(path),
                    "relative_path": str(path.relative_to(source.path)) if source.path.is_dir() else path.name,
                    "format": detected,
                    "size_bytes": stat.st_size,
                    "modified_at": stat.st_mtime_ns,
                    "sha256": sha256_file(path),
                    "status": "ready" if detected in {"chatgpt_zip", "codex_rollout_jsonl"} else "unsupported",
                }
            prior_hash = previous_hashes.get(entry["path"])
            entry["change"] = "new" if prior_hash is None else ("unchanged" if prior_hash == entry["sha256"] else "changed")
            entries.append(entry)
    manifest = {
        "generated_at": utc_now(),
        "entries": entries,
        "formats": dict(formats),
        "change_summary": dict(Counter(entry.get("change", entry["status"]) for entry in entries)),
    }
    manifest_dir = ensure_directory(config.private_work / "manifest")
    write_json(manifest_dir / "source-manifest.json", manifest)
    write_json(manifest_dir / "file-hashes.json", {entry["path"]: entry.get("sha256") for entry in entries if entry.get("sha256")})
    report_lines = ["# Source coverage report", "", f"Generated: {manifest['generated_at']}", "", "| Format | Files |", "|---|---:|"]
    report_lines.extend(f"| {format_name} | {count} |" for format_name, count in sorted(formats.items()))
    failures = [entry for entry in entries if entry["status"] != "ready"]
    if failures:
        report_lines.extend(["", "## Attention required", ""])
        report_lines.extend(f"- `{entry['path']}`: {entry['status']}" for entry in failures)
    report_path = ensure_directory(config.private_work / "reports") / "source-coverage-report.md"
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    return manifest
