from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import yaml

from bodaqs_history.candidates import run_candidates
from bodaqs_history.config import load_config
from bodaqs_history.drafting import run_draft
from bodaqs_history.generate import run_generate
from bodaqs_history.ingest import run_ingest
from bodaqs_history.inventory import run_inventory
from bodaqs_history.packets import prepare_packet
from bodaqs_history.validation import run_validate
from bodaqs_history.verify import run_verify


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _config(tmp_path: Path) -> tuple[Path, Path]:
    sources = tmp_path / "sources"
    sources.mkdir()
    chatgpt = sources / "chatgpt.zip"
    export = [
        {
            "id": "chat-1",
            "title": "BODAQS SD storage test",
            "create_time": 1735689600,
            "update_time": 1735689660,
            "mapping": {
                "one": {"message": {"id": "one", "create_time": 1735689600, "author": {"role": "user"}, "content": {"parts": ["BODAQS ESP32-S3 StorageManager test"]}}},
                "two": {"message": {"id": "two", "create_time": 1735689660, "author": {"role": "assistant"}, "content": {"parts": ["Test at 500 Hz."]}}},
            },
        }
    ]
    with zipfile.ZipFile(chatgpt, "w") as archive:
        archive.writestr("conversations-000.json", json.dumps(export))
    codex_root = sources / ".codex"
    session = codex_root / "sessions" / "2026" / "01" / "01" / "rollout-test.jsonl"
    session.parent.mkdir(parents=True)
    session.write_text(
        "\n".join(
            json.dumps(record)
            for record in (
                {"timestamp": "2026-01-01T00:00:00Z", "type": "session_meta", "payload": {"id": "session-1"}},
                {"timestamp": "2026-01-01T00:00:01Z", "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "BODAQS front_shock calibration"}]}},
                {"timestamp": "2026-01-01T00:00:02Z", "type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Use installed_zero_count."}]}},
            )
        ) + "\n",
        encoding="utf-8",
    )
    payload = {
        "project": {"name": "BODAQS", "keywords": ["BODAQS", "ESP32-S3", "StorageManager", "front_shock"]},
        "sources": [
            {"id": "chatgpt", "type": "chatgpt_zip", "path": str(chatgpt), "label": "ChatGPT"},
            {"id": "codex", "type": "codex_sessions", "path": str(codex_root), "label": "Codex"},
        ],
        "repositories": [{"id": "bodaqs", "path": str(tmp_path)}],
        "output": {"private_work": str(tmp_path / "private"), "corpus": str(tmp_path / "corpus")},
        "llm": {"provider": "openai", "external_api_allowed": False},
    }
    config_path = tmp_path / "project.yaml"
    config_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return config_path, chatgpt


def test_private_pipeline_handles_initial_source_formats(tmp_path: Path) -> None:
    config_path, chatgpt = _config(tmp_path)
    before = _sha(chatgpt)
    config = load_config(config_path)

    manifest = run_inventory(config)
    second_manifest = run_inventory(config)
    counts = run_ingest(config)
    candidates = run_candidates(config)
    candidate_id = json.loads((config.private_work / "candidates" / "candidates.jsonl").read_text(encoding="utf-8").splitlines()[0])["candidate_id"]
    packet = prepare_packet(config, candidate_id)
    drafts = run_draft(config, limit=2)
    verification = run_verify(config)
    generated = run_generate(config)
    validation = run_validate(config)

    assert before == _sha(chatgpt)
    assert manifest["formats"] == {"chatgpt_zip": 1, "codex_rollout_jsonl": 1}
    assert second_manifest["change_summary"] == {"unchanged": 2}
    assert counts == {"conversations": 2, "messages": 4, "errors": 0}
    assert candidates["definite"] == 2
    assert packet["messages"] == 2
    assert Path(packet["packet"]).exists()
    assert drafts["drafts"] == 2
    assert verification == {"records": 2, "failed": 0}
    assert generated["drafts_published"] == 2
    assert validation == {"records_checked": 2, "errors": 0}


def test_redaction_prevents_common_sensitive_values_from_drafts(tmp_path: Path) -> None:
    config_path, _ = _config(tmp_path)
    config = load_config(config_path)
    run_ingest(config)
    messages = (config.private_work / "ingest" / "messages.jsonl").read_text(encoding="utf-8")
    (config.private_work / "ingest" / "messages.jsonl").write_text(messages.replace("500 Hz.", "500 Hz. email owner@example.com and key sk-abcdefghijklmnopqrstuvwxyz"), encoding="utf-8")
    run_candidates(config)
    run_draft(config, limit=2)
    drafts = "\n".join(path.read_text(encoding="utf-8") for path in (config.private_work / "drafts").glob("*.md"))
    assert "owner@example.com" not in drafts
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in drafts
