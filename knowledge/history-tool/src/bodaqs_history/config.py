"""Configuration loading for the private history workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Source:
    id: str
    type: str
    path: Path
    label: str


@dataclass(frozen=True)
class Repository:
    id: str
    path: Path


@dataclass(frozen=True)
class Config:
    path: Path
    project_name: str
    keywords: tuple[str, ...]
    exclusion_terms: tuple[str, ...]
    sources: tuple[Source, ...]
    repositories: tuple[Repository, ...]
    private_work: Path
    corpus: Path
    redact_patterns_file: Path | None
    llm_provider: str
    llm_model: str | None
    llm_reasoning_effort: str | None
    llm_max_input_characters: int
    external_api_allowed: bool


def _path(value: str | Path, config_path: Path) -> Path:
    candidate = Path(value).expanduser()
    return candidate if candidate.is_absolute() else (config_path.parent / candidate).resolve()


def _required(mapping: dict[str, Any], key: str) -> Any:
    if key not in mapping or mapping[key] in (None, ""):
        raise ConfigError(f"Missing required configuration value: {key}")
    return mapping[key]


def load_config(path: str | Path) -> Config:
    config_path = Path(path).resolve()
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except OSError as error:
        raise ConfigError(f"Cannot read configuration: {config_path}") from error
    except yaml.YAMLError as error:
        raise ConfigError(f"Invalid YAML configuration: {config_path}") from error

    project = raw.get("project", {})
    output = raw.get("output", {})
    llm = raw.get("llm", {})
    privacy = raw.get("privacy", {})
    sources = tuple(
        Source(
            id=str(_required(item, "id")),
            type=str(item.get("type", "auto")),
            path=_path(_required(item, "path"), config_path),
            label=str(item.get("label") or item["id"]),
        )
        for item in raw.get("sources", [])
    )
    if not sources:
        raise ConfigError("At least one source is required.")
    repositories = tuple(
        Repository(id=str(_required(item, "id")), path=_path(_required(item, "path"), config_path))
        for item in raw.get("repositories", [])
    )
    patterns = privacy.get("redact_patterns_file")
    return Config(
        path=config_path,
        project_name=str(project.get("name", "BODAQS")),
        keywords=tuple(str(value) for value in project.get("keywords", [])),
        exclusion_terms=tuple(str(value) for value in project.get("exclusion_terms", [])),
        sources=sources,
        repositories=repositories,
        private_work=_path(_required(output, "private_work"), config_path),
        corpus=_path(_required(output, "corpus"), config_path),
        redact_patterns_file=_path(patterns, config_path) if patterns else None,
        llm_provider=str(llm.get("provider", "openai")),
        llm_model=str(llm["model"]) if llm.get("model") else None,
        llm_reasoning_effort=str(llm["reasoning_effort"]) if llm.get("reasoning_effort") else None,
        llm_max_input_characters=int(llm.get("max_input_characters", 60000)),
        external_api_allowed=bool(llm.get("external_api_allowed", False)),
    )
