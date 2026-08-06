"""Parsers for the initial ChatGPT ZIP and Codex rollout JSONL formats."""

from __future__ import annotations

import json
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .common import content_hash, normalise_timestamp, stable_id, text_from_value, write_json, write_jsonl
from .config import Config, Source
from .inventory import detect_format, run_inventory, source_files


def _chatgpt_message_text(message: dict[str, Any]) -> str:
    content = message.get("content") or {}
    return text_from_value(content.get("parts") if isinstance(content, dict) else content)


def _chatgpt_conversation(source: Source, archive_member: str, raw: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    native_id = str(raw.get("id") or content_hash(raw))
    conversation_id = stable_id("CONV", source.id, native_id)
    nodes = list((raw.get("mapping") or {}).values())
    sortable = []
    for index, node in enumerate(nodes):
        message = node.get("message") if isinstance(node, dict) else None
        if message:
            sortable.append((message.get("create_time") or float("inf"), index, message))
    messages = []
    for sequence, (_, _, message) in enumerate(sorted(sortable), start=1):
        text = _chatgpt_message_text(message)
        if not text.strip():
            continue
        native_message_id = str(message.get("id") or sequence)
        messages.append(
            {
                "message_id": stable_id("MSG", source.id, native_id, native_message_id),
                "conversation_id": conversation_id,
                "source_id": source.id,
                "source_native_id": native_message_id,
                "sequence": len(messages) + 1,
                "role": str(((message.get("author") or {}).get("role")) or "unknown"),
                "timestamp": normalise_timestamp(message.get("create_time")),
                "content": text.replace("\r\n", "\n"),
                "source_locator": f"{archive_member}:{native_id}:{native_message_id}",
            }
        )
    conversation = {
        "conversation_id": conversation_id,
        "source_id": source.id,
        "source_type": source.type,
        "source_native_id": native_id,
        "title": raw.get("title") or "Untitled ChatGPT conversation",
        "started_at": normalise_timestamp(raw.get("create_time")),
        "ended_at": normalise_timestamp(raw.get("update_time")),
        "source_path": archive_member,
        "content_hash": content_hash(messages),
    }
    return conversation, messages


def _codex_content_text(content: object) -> str:
    if isinstance(content, list):
        return "\n".join(text_from_value(item) for item in content if text_from_value(item)).strip()
    return text_from_value(content)


def _codex_rollout(source: Source, path: Path) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[str]]:
    session_id: str | None = None
    messages: list[dict[str, Any]] = []
    errors: list[str] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                errors.append(f"{path}:{line_number}: {error.msg}")
                continue
            payload = record.get("payload") or {}
            if record.get("type") == "session_meta":
                session_id = str(payload.get("id") or session_id or path.stem)
            if record.get("type") != "response_item" or not isinstance(payload, dict):
                continue
            role = payload.get("role")
            if role not in {"user", "assistant", "developer", "system", "tool"}:
                continue
            text = _codex_content_text(payload.get("content"))
            if not text:
                continue
            native_id = f"{line_number}:{len(messages) + 1}"
            messages.append(
                {
                    "message_id": stable_id("MSG", source.id, session_id or path.stem, native_id),
                    "conversation_id": "",  # filled after the session identity is known
                    "source_id": source.id,
                    "source_native_id": native_id,
                    "sequence": len(messages) + 1,
                    "role": role,
                    "timestamp": normalise_timestamp(record.get("timestamp")),
                    "content": text.replace("\r\n", "\n"),
                    "source_locator": f"{path.name}:{line_number}",
                }
            )
    if not messages and not session_id:
        return None, messages, errors
    native_id = session_id or path.stem
    conversation_id = stable_id("CONV", source.id, native_id)
    for message in messages:
        message["conversation_id"] = conversation_id
    first_user = next((message["content"] for message in messages if message["role"] == "user"), "")
    conversation = {
        "conversation_id": conversation_id,
        "source_id": source.id,
        "source_type": source.type,
        "source_native_id": native_id,
        "title": first_user.strip().splitlines()[0][:120] if first_user else path.stem,
        "started_at": messages[0]["timestamp"] if messages else None,
        "ended_at": messages[-1]["timestamp"] if messages else None,
        "source_path": str(path),
        "content_hash": content_hash(messages),
    }
    return conversation, messages, errors


def _chatgpt_zip(source: Source, path: Path) -> Iterable[tuple[dict[str, Any], list[dict[str, Any]]]]:
    with zipfile.ZipFile(path) as archive:
        for member in sorted(name for name in archive.namelist() if Path(name).name.startswith("conversations-") and name.endswith(".json")):
            payload = json.loads(archive.read(member).decode("utf-8"))
            if not isinstance(payload, list):
                continue
            for raw in payload:
                if isinstance(raw, dict):
                    yield _chatgpt_conversation(source, member, raw)


def run_ingest(config: Config) -> dict[str, int]:
    if not (config.private_work / "manifest" / "source-manifest.json").exists():
        run_inventory(config)
    conversations: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = []
    errors: list[str] = []
    seen_conversations: set[str] = set()
    for source in config.sources:
        for path in source_files(source):
            format_name = detect_format(path, source.type)
            try:
                if format_name == "chatgpt_zip":
                    parsed = _chatgpt_zip(source, path)
                    for conversation, conversation_messages in parsed:
                        if conversation["conversation_id"] in seen_conversations:
                            continue
                        seen_conversations.add(conversation["conversation_id"])
                        conversations.append(conversation)
                        messages.extend(conversation_messages)
                elif format_name == "codex_rollout_jsonl":
                    conversation, conversation_messages, parse_errors = _codex_rollout(source, path)
                    errors.extend(parse_errors)
                    if conversation and conversation["conversation_id"] not in seen_conversations:
                        seen_conversations.add(conversation["conversation_id"])
                        conversations.append(conversation)
                        messages.extend(conversation_messages)
            except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as error:
                errors.append(f"{path}: {error}")
    conversations.sort(key=lambda item: (item.get("started_at") or "", item["conversation_id"]))
    messages.sort(key=lambda item: (item["conversation_id"], item["sequence"]))
    ingest_dir = config.private_work / "ingest"
    write_jsonl(ingest_dir / "conversations.jsonl", conversations)
    write_jsonl(ingest_dir / "messages.jsonl", messages)
    write_json(ingest_dir / "parse-errors.json", {"errors": errors})
    return {"conversations": len(conversations), "messages": len(messages), "errors": len(errors)}
