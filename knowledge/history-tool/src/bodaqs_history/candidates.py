"""Deterministic candidate discovery; semantic classification remains opt-in."""

from __future__ import annotations

from collections import defaultdict

from .common import read_jsonl, stable_id, write_jsonl
from .config import Config


def _is_session_scaffolding(message: dict) -> bool:
    text = message["content"].lstrip().lower()
    return text.startswith("# agents.md instructions") or text.startswith("<environment_context>") or text.startswith("<developer")


def run_candidates(config: Config) -> dict[str, int]:
    conversations = read_jsonl(config.private_work / "ingest" / "conversations.jsonl")
    messages_by_conversation: dict[str, list[dict]] = defaultdict(list)
    for message in read_jsonl(config.private_work / "ingest" / "messages.jsonl"):
        if message.get("role") in {"user", "assistant", "tool"} and not _is_session_scaffolding(message):
            messages_by_conversation[message["conversation_id"]].append(message)
    candidates = []
    keywords = tuple(term.lower() for term in config.keywords if term.strip())
    exclusions = tuple(term.lower() for term in config.exclusion_terms if term.strip())
    for conversation in conversations:
        selected_messages = messages_by_conversation[conversation["conversation_id"]]
        text = "\n".join(message["content"] for message in selected_messages).lower()
        matches = [term for term in keywords if term in text]
        excluded = [term for term in exclusions if term in text]
        if excluded and not matches:
            relevance = "excluded"
        elif len(matches) >= 2:
            relevance = "definite"
        elif matches:
            relevance = "possible"
        else:
            relevance = "unclassified"
        candidates.append(
            {
                "candidate_id": stable_id("CAND", conversation["conversation_id"]),
                "conversation_id": conversation["conversation_id"],
                "source_id": conversation["source_id"],
                "title": conversation["title"],
                "date_range": [conversation.get("started_at"), conversation.get("ended_at")],
                "matched_terms": matches,
                "excluded_terms": excluded,
                "relevance": relevance,
                "score": round(min(0.98, 0.45 + 0.15 * len(matches)), 2) if matches else 0.0,
                "message_ids": [message["message_id"] for message in selected_messages],
                "reason": "Deterministic project-term match; semantic classification has not been run.",
            }
        )
    write_jsonl(config.private_work / "candidates" / "candidates.jsonl", candidates)
    counts: dict[str, int] = defaultdict(int)
    for candidate in candidates:
        counts[candidate["relevance"]] += 1
    return dict(counts)
