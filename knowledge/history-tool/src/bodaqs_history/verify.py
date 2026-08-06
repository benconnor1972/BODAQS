"""Targeted local checks for record source, code, and Git references."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from .common import write_json
from .config import Config


def _front_matter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    _, header, _ = text.split("---\n", 2)
    return yaml.safe_load(header) or {}


def _git_commit_exists(repository: Path, commit: str) -> bool:
    completed = subprocess.run(["git", "-C", str(repository), "cat-file", "-e", f"{commit}^{{commit}}"], capture_output=True, text=True, check=False)
    return completed.returncode == 0


def run_verify(config: Config) -> dict[str, int]:
    repositories = {repository.id: repository.path for repository in config.repositories}
    results = []
    for path in sorted((config.private_work / "drafts").glob("*.md")):
        metadata = _front_matter(path)
        checks = []
        for code_ref in metadata.get("code_refs", []):
            exists = any((repository / code_ref).exists() for repository in repositories.values())
            checks.append({"kind": "code_ref", "reference": code_ref, "exists": exists})
        for source_ref in metadata.get("source_refs", []):
            parts = str(source_ref).split(":")
            checks.append({"kind": "source_ref", "reference": source_ref, "exists": len(parts) >= 2})
        for reference in metadata.get("git_refs", []):
            parts = str(reference).split(":", 2)
            repository = repositories.get(parts[0]) if parts else None
            exists = bool(repository and len(parts) > 1 and _git_commit_exists(repository, parts[1]))
            checks.append({"kind": "git_ref", "reference": reference, "exists": exists})
        results.append({"draft": path.name, "checks": checks, "passed": all(check["exists"] for check in checks)})
    write_json(config.private_work / "reports" / "verification-report.json", {"records": results})
    return {"records": len(results), "failed": sum(not item["passed"] for item in results)}
