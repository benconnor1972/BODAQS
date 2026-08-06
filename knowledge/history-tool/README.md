# BODAQS history tool

This private, local-first tool converts the initial BODAQS ChatGPT ZIP and Codex rollout-session archives into a reviewable engineering-knowledge corpus.

It deliberately does not build a general-purpose event database or copy raw conversation data into the repository.

## Installation

From this directory, create or use a Python 3.11+ virtual environment and install the base tool:

```powershell
python -m pip install -e .
```

Install OpenAI support only if you intend to use the opt-in external drafting path:

```powershell
python -m pip install -e ".[openai]"
```

Copy `config/project.example.yaml` to `config/project.local.yaml` and replace every placeholder. The local file is ignored by Git.

The reviewed corpus should initially be configured beneath `C:\Users\benco\OneDrive\BODAQS-private`, not in this repository. Keep raw archives and `private_work` outside the repository as well.

## Commands

```powershell
python -m bodaqs_history inventory --config config/project.local.yaml
python -m bodaqs_history ingest --config config/project.local.yaml
python -m bodaqs_history candidates --config config/project.local.yaml
python -m bodaqs_history draft --config config/project.local.yaml --limit 10
python -m bodaqs_history verify --config config/project.local.yaml
python -m bodaqs_history generate --config config/project.local.yaml
python -m bodaqs_history validate --config config/project.local.yaml
```

`all` runs the same sequence. Without `--allow-external`, drafting creates cautious local candidate records and makes no network request.

## Interactive Codex workflow

The recommended no-API-cost workflow is to run `candidates`, deliberately select one candidate, then prepare a bounded redacted packet for interactive review:

```powershell
python -m bodaqs_history prepare --config config/project.local.yaml --candidate CAND-...
```

The packet is stored privately in `private_work/packets/`. Review it in Codex, generate a cautious Markdown record, verify important code/Git claims, and promote the reviewed record into the private corpus. Do not use `--allow-external` for this workflow.

To use OpenAI, set `llm.external_api_allowed: true`, set `llm.model` (and optional `llm.reasoning_effort`), set `OPENAI_API_KEY` in the process environment, and explicitly add `--allow-external` to `draft` or `all`. `llm.max_input_characters` is a hard cap on redacted text included in each request:

```powershell
$env:OPENAI_API_KEY = "..."
python -m bodaqs_history draft --config config/project.local.yaml --allow-external --limit 10
```

No API key is read or required for inventory, ingest, candidate discovery, validation, or local drafting.

## Initial source support

The first implementation supports the source formats found in the supplied archive:

* a ChatGPT ZIP containing chunked `conversations-*.json` exports;
* Codex `sessions/**/rollout-*.jsonl` archives from the workstation and laptop.

It intentionally ignores Codex caches, SQLite databases, credentials, configuration, plugins, and other non-session files.

## Privacy and review

Raw normalised messages, candidates, redacted LLM bundles, manifests, reports, and drafts remain in `private_work`.

The tool applies basic local redaction immediately before an optional external request. It masks common API-token shapes, email addresses, bearer tokens, and Windows user paths, but it cannot guarantee removal of every sensitive value. Review material before enabling an external call.

`generate` publishes copies to the configured private corpus under `drafts/`; it never overwrites a manually reviewed record. Promote and amend records manually until a more formal review workflow is needed.

## Incremental updates

Run `inventory` after adding new archives. Source hashes and normalised source/session IDs make exact duplicates visible. `private_work/manifest/processing-manifest.json` retains the last run and a bounded run history. The initial implementation keeps drafts separate, but deliberately defers automatic near-duplicate merging and automatic amendment of reviewed records.

## Known limitations

* Semantic candidate classification is not yet separate from OpenAI drafting; deterministic keyword candidates are always available.
* Git verification currently validates explicitly supplied code/Git references in drafts. It does not infer commit-to-topic relationships.
* The current `chronological-overview.md` is an intentional review scaffold, not an auto-generated narrative.
