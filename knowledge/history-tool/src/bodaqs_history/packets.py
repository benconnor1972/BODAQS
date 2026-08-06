"""Prepare a bounded redacted evidence packet for interactive Codex review."""

from __future__ import annotations

from .common import read_jsonl, utc_now, write_json
from .config import Config
from .drafting import _select_context
from .privacy import load_patterns, redact_text


def prepare_packet(config: Config, candidate_id: str) -> dict[str, int | str]:
    candidates = {item["candidate_id"]: item for item in read_jsonl(config.private_work / "candidates" / "candidates.jsonl")}
    if candidate_id not in candidates:
        raise ValueError(f"Unknown candidate ID: {candidate_id}")
    candidate = candidates[candidate_id]
    messages_by_id = {item["message_id"]: item for item in read_jsonl(config.private_work / "ingest" / "messages.jsonl")}
    selected = [messages_by_id[message_id] for message_id in candidate["message_ids"] if message_id in messages_by_id]
    selected = _select_context(selected, candidate["matched_terms"], config.llm_max_input_characters)
    patterns = load_patterns(config.redact_patterns_file)
    counts: dict[str, int] = {}
    packet_messages = []
    for message in selected:
        content, redactions = redact_text(message["content"], patterns)
        for name, count in redactions.items():
            counts[name] = counts.get(name, 0) + count
        packet_messages.append({"role": message["role"], "timestamp": message["timestamp"], "source_locator": message["source_locator"], "content": content})
    packet = {
        "prepared_at": utc_now(),
        "candidate": {key: candidate[key] for key in ("candidate_id", "conversation_id", "source_id", "title", "date_range", "matched_terms", "relevance", "score", "reason")},
        "messages": packet_messages,
        "redaction_counts": counts,
        "instructions": "Use this material only to draft a cautious record. Separate proposals, decisions, implementation, and verification. Do not invent facts.",
    }
    path = config.private_work / "packets" / f"{candidate_id}.json"
    write_json(path, packet)
    return {"packet": str(path), "messages": len(packet_messages), "redactions": sum(counts.values())}
