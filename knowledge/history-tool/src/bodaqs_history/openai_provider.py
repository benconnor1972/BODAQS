"""Optional OpenAI Responses API adapter, isolated behind explicit opt-in."""

from __future__ import annotations

import json
import os
from typing import Any

from .config import Config


class ExternalApiDisabledError(RuntimeError):
    pass


def _require_external_access(config: Config, allow_external: bool) -> None:
    if not config.external_api_allowed or not allow_external:
        raise ExternalApiDisabledError(
            "External API use is disabled. Set llm.external_api_allowed: true and pass --allow-external."
        )
    if config.llm_provider != "openai":
        raise ValueError(f"Unsupported LLM provider: {config.llm_provider}")
    if not config.llm_model:
        raise ValueError("Set llm.model before enabling external drafting.")
    if not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY is required only when external drafting is enabled.")


def draft_record(config: Config, allow_external: bool, source_bundle: dict[str, Any]) -> dict[str, Any]:
    _require_external_access(config, allow_external)
    try:
        from openai import OpenAI
    except ImportError as error:
        raise RuntimeError("Install the optional dependency with: pip install -e .[openai]") from error
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string"},
            "kind": {"type": "string", "enum": ["decision", "problem-resolution", "experiment", "topic", "open-question"]},
            "topics": {"type": "array", "items": {"type": "string"}},
            "status": {"type": "string", "enum": ["draft", "current", "resolved", "open", "uncertain", "superseded"]},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "summary": {"type": "string"},
            "evidence_notes": {"type": "array", "items": {"type": "string"}},
            "proposal": {"type": "string"},
            "decision": {"type": "string"},
            "implementation": {"type": "string"},
            "verification": {"type": "string"},
            "uncertainties": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title", "kind", "topics", "status", "confidence", "summary", "evidence_notes", "proposal", "decision", "implementation", "verification", "uncertainties"],
    }
    instructions = (
        "Draft one cautious BODAQS engineering knowledge record from the supplied redacted conversation material. "
        "Use only supported facts. Treat recommendations as proposals, not decisions. Do not invent dates, versions, "
        "test results, code changes, or adoption. Use 'unknown' where evidence is incomplete."
    )
    client = OpenAI()
    request: dict[str, Any] = {
        "model": config.llm_model,
        "instructions": instructions,
        "input": json.dumps(source_bundle, ensure_ascii=False),
        "text": {"format": {"type": "json_schema", "name": "bodaqs_knowledge_record", "strict": True, "schema": schema}},
    }
    if config.llm_reasoning_effort:
        request["reasoning"] = {"effort": config.llm_reasoning_effort}
    response = client.responses.create(**request)
    return json.loads(response.output_text)
