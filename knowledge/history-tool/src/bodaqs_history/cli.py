"""Command line entry point for the small, inspectable workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .candidates import run_candidates
from .config import ConfigError, load_config
from .drafting import run_draft
from .generate import run_generate
from .ingest import run_ingest
from .inventory import run_inventory
from .packets import prepare_packet
from .run_manifest import record_run
from .validation import run_validate
from .verify import run_verify


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bodaqs-history")
    parser.add_argument("command", choices=("inventory", "ingest", "candidates", "prepare", "draft", "verify", "generate", "validate", "all"))
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--allow-external", action="store_true", help="Permit the configured external LLM provider for this invocation.")
    parser.add_argument("--limit", type=int, help="Maximum number of candidate drafts to create.")
    parser.add_argument("--candidate", help="Candidate ID to prepare for interactive review.")
    return parser


def _run(command: str, config, allow_external: bool, limit: int | None, candidate_id: str | None = None) -> dict:
    if command == "inventory":
        return run_inventory(config)
    if command == "ingest":
        return run_ingest(config)
    if command == "candidates":
        return run_candidates(config)
    if command == "prepare":
        if not candidate_id:
            raise ValueError("--candidate is required for prepare.")
        return prepare_packet(config, candidate_id)
    if command == "draft":
        return run_draft(config, allow_external, limit)
    if command == "verify":
        return run_verify(config)
    if command == "generate":
        return run_generate(config)
    if command == "validate":
        return run_validate(config)
    outputs = {
        "inventory": run_inventory(config),
        "ingest": run_ingest(config),
        "candidates": run_candidates(config),
        "draft": run_draft(config, allow_external, limit),
        "verify": run_verify(config),
        "generate": run_generate(config),
        "validate": run_validate(config),
    }
    return outputs


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config)
        result = _run(args.command, config, args.allow_external, args.limit, args.candidate)
        record_run(config, args.command, result)
    except (ConfigError, OSError, ValueError, RuntimeError) as error:
        print(f"error: {error}")
        return 2
    except Exception as error:
        # Optional provider dependencies raise their own typed exceptions. Keep
        # an API failure actionable without exposing an implementation traceback.
        if error.__class__.__module__.startswith("openai"):
            print(f"error: OpenAI API request failed: {error}")
            return 2
        raise
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0
