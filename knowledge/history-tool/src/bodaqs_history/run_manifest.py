"""Private run history used to make later archive updates inspectable."""

from __future__ import annotations

from typing import Any

from .common import read_json, utc_now, write_json
from .config import Config


def record_run(config: Config, command: str, result: dict[str, Any]) -> None:
    path = config.private_work / "manifest" / "processing-manifest.json"
    existing = read_json(path, {"runs": [], "known_sources": {}})
    source_manifest = read_json(config.private_work / "manifest" / "source-manifest.json", {"entries": []})
    known_sources = {
        entry["path"]: {"sha256": entry.get("sha256"), "source_id": entry.get("source_id"), "format": entry.get("format")}
        for entry in source_manifest.get("entries", [])
        if entry.get("sha256")
    }
    # The complete inventory already lives in source-manifest.json. Keep run history
    # compact so quarterly updates do not duplicate every file record indefinitely.
    result_summary: dict[str, Any] = result
    if command == "inventory":
        result_summary = {
            "generated_at": result.get("generated_at"),
            "formats": result.get("formats", {}),
            "change_summary": result.get("change_summary", {}),
        }
    run = {"at": utc_now(), "command": command, "result": result_summary}
    runs = [*existing.get("runs", []), run][-100:]
    write_json(path, {"last_run": run, "runs": runs, "known_sources": known_sources})
