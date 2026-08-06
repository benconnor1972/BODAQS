"""Draft private Markdown records from selected conversation candidates."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from .common import read_jsonl, slugify, utc_now, write_json
from .config import Config
from .openai_provider import draft_record
from .privacy import load_patterns, redact_text


def _render_record(front_matter: dict[str, Any], body: dict[str, Any]) -> str:
    header = yaml.safe_dump(front_matter, sort_keys=False, allow_unicode=True).strip()
    sections = [body["summary"]]
    for heading, key in (("Evidence notes", "evidence_notes"), ("Proposal", "proposal"), ("Decision", "decision"), ("Implementation", "implementation"), ("Verification", "verification"), ("Uncertainties", "uncertainties")):
        value = body.get(key)
        if not value or value == "unknown" or value == []:
            continue
        sections.extend([f"## {heading}", ""])
        if isinstance(value, list):
            sections.extend(f"- {item}" for item in value)
        else:
            sections.append(str(value))
    sections.extend(["## Sources", ""])
    sections.extend(f"- `{reference}`" for reference in front_matter["source_refs"])
    return f"---\n{header}\n---\n\n" + "\n\n".join(sections).strip() + "\n"


def _local_draft(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": candidate["title"],
        "kind": "topic",
        "topics": candidate["matched_terms"][:4] or ["needs-classification"],
        "status": "uncertain",
        "confidence": "low",
        "summary": "Candidate BODAQS discussion. Semantic drafting was not enabled; review the linked source before making technical claims.",
        "evidence_notes": [candidate["reason"]],
        "proposal": "unknown",
        "decision": "unknown",
        "implementation": "unknown",
        "verification": "unknown",
        "uncertainties": ["Requires human or opt-in LLM review."],
    }


def _select_context(messages: list[dict[str, Any]], matched_terms: list[str], maximum: int) -> list[dict[str, Any]]:
    """Keep keyword-centred context and impose a deterministic request-size ceiling."""
    terms = tuple(term.lower() for term in matched_terms)
    matching = [index for index, message in enumerate(messages) if any(term in message["content"].lower() for term in terms)]
    selected_indexes = set()
    for index in matching:
        selected_indexes.update(range(max(0, index - 1), min(len(messages), index + 2)))
    if not selected_indexes:
        selected_indexes.update(range(min(len(messages), 20)))
    selected: list[dict[str, Any]] = []
    used = 0
    for index in sorted(selected_indexes):
        message = messages[index]
        remaining = maximum - used
        if remaining <= 0:
            break
        content = message["content"][:remaining]
        selected.append({**message, "content": content})
        used += len(content)
    return selected


def run_draft(config: Config, allow_external: bool = False, limit: int | None = None) -> dict[str, int]:
    candidates = read_jsonl(config.private_work / "candidates" / "candidates.jsonl")
    messages = {message["message_id"]: message for message in read_jsonl(config.private_work / "ingest" / "messages.jsonl")}
    conversations = {item["conversation_id"]: item for item in read_jsonl(config.private_work / "ingest" / "conversations.jsonl")}
    patterns = load_patterns(config.redact_patterns_file)
    output = config.private_work / "drafts"
    output.mkdir(parents=True, exist_ok=True)
    drafted = 0
    redaction_counts: dict[str, int] = defaultdict(int)
    for candidate in candidates:
        if candidate["relevance"] not in {"definite", "possible"}:
            continue
        if limit is not None and drafted >= limit:
            break
        all_messages = [messages[message_id] for message_id in candidate["message_ids"] if message_id in messages]
        selected = _select_context(all_messages, candidate["matched_terms"], config.llm_max_input_characters)
        redacted_messages = []
        for message in selected:
            text, counts = redact_text(message["content"], patterns)
            for name, count in counts.items():
                redaction_counts[name] += count
            redacted_messages.append({"role": message["role"], "timestamp": message["timestamp"], "text": text})
        conversation = conversations[candidate["conversation_id"]]
        bundle = {"candidate": {key: candidate[key] for key in ("title", "date_range", "matched_terms", "reason")}, "conversation": {"source_id": conversation["source_id"], "source_native_id": conversation["source_native_id"]}, "messages": redacted_messages}
        body = draft_record(config, allow_external, bundle) if allow_external else _local_draft(candidate)
        source_ref = f"{conversation['source_id']}:{conversation['source_native_id']}"
        front_matter = {
            "title": body["title"],
            "kind": body["kind"],
            "topics": body["topics"],
            "status": body["status"],
            "date_range": " to ".join(value for value in candidate["date_range"] if value) or "unknown",
            "confidence": body["confidence"],
            "source_refs": [source_ref],
            "code_refs": [],
            "review_status": "draft",
            "generated_at": utc_now(),
        }
        filename = f"{slugify(body['title'])}-{candidate['candidate_id'][-6:]}.md"
        (output / filename).write_text(_render_record(front_matter, body), encoding="utf-8")
        drafted += 1
    write_json(config.private_work / "reports" / "redaction-report.json", {"counts": dict(redaction_counts), "external_api_used": bool(allow_external), "generated_at": utc_now()})
    return {"drafts": drafted, "redactions": sum(redaction_counts.values())}
