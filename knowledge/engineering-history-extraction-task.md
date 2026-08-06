# Task: Build the BODAQS Engineering Knowledge Corpus

## Objective

Build a local, repeatable knowledge-harvesting tool that turns historical BODAQS conversations and relevant Git repositories into a curated engineering knowledge corpus that is useful to both people and future agents.

The initial run is expected to be substantial because it covers roughly one year of project history. Future runs will normally occur about every three months and should process only new or changed material.

The task ends when the first iteration has produced a reviewed, useful corpus and the incremental workflow is documented. This is not a requirement to build a general-purpose evidence-management platform.

## What the corpus must capture

The corpus should make the following easy to find and understand:

* current engineering decisions and their rationale;
* resolved technical problems and tested fixes;
* important experiments and their results or limitations;
* significant changes of direction or superseded approaches;
* open technical questions;
* uncertainties that need a human decision or further testing;
* concise historical context where it changes how current code, hardware, or analysis should be interpreted.

Do not attempt to turn every message, suggestion, or code edit into a formal record. Prefer a small number of accurate, useful topic records over an exhaustive event database.

## Implementation location and naming

Implement the tool and its documentation under:

```text
bodaqs/knowledge/
  history-tool/
  engineering-history/
```

Use `bodaqs_history` as the Python package and command-line name if a package is needed.

`engineering-history/` is the human- and agent-facing corpus. `history-tool/` contains the implementation, configuration examples, and its documentation. Adjust the exact internal layout only where the existing repository conventions require it.

The initial reviewed corpus is private. Keep generated records under the configured private output location (currently beneath `C:\Users\benco\OneDrive\BODAQS-private`) rather than in the repository. The repository location may contain the tool, documentation, templates, and examples, but not derived private conversation material.

## Working principles

### Source material is read-only

Do not alter, rename, move, or delete source archives or repositories. Treat all source directories as read-only.

### Accuracy over apparent completeness

Conversation history records discussion, proposals, hypotheses, and reported results. It does not necessarily describe the current implementation.

Use evidence in this order where it is available:

1. current code and approved documentation;
2. reproducible test logs or data;
3. Git commits and inspected diffs;
4. explicit project-owner confirmation in conversation;
5. assistant recommendations;
6. inference.

An assistant recommendation alone is never an adopted project decision. Mark incomplete or conflicting conclusions as uncertain rather than forcing an answer.

### Lightweight source references

Each knowledge record must retain enough information for a reviewer to revisit important claims, without requiring forensic-grade source locations for every sentence.

For material claims, retain where available:

* source archive and conversation/session identifier;
* approximate date or date range;
* relevant Git commit and file path;
* a concise evidence note or short quotation for contested or high-impact claims.

Use durable internal references such as:

```text
[Codex:workstation:session-456]
[ChatGPT:main:conversation-123]
[Git:firmware:abcdef1:src/StorageManager.cpp]
```

### Privacy by separation

Keep original archives and unredacted parsed content outside the version-controlled corpus. Generated working data containing raw conversations must be stored in a Git-ignored private directory.

Only reviewed, BODAQS-specific, appropriately redacted knowledge records belong in the project corpus. Do not copy raw archives into the repository.

Before content is sent to an external model, remove or mask obvious secrets, credentials, personal contact details, unrelated personal discussion, customer/employer confidential information, and user-specific private paths. Automated redaction reduces risk but cannot guarantee detection of every sensitive value.

API credentials must be supplied through environment variables, not configuration files committed to Git.

### External LLM use is opt-in

External API use is disabled by default. The tool must require an explicit configuration setting or command-line flag before sending any content externally.

When no local model is configured and external API use is disabled, the tool should still perform inventory, parsing, exact de-duplication, and export of candidate material for manual review. Semantic relevance filtering and drafting may then be deferred rather than silently sending material to an API.

When an LLM is used, retain the model and prompt-version metadata in the run manifest. Ask it to distinguish explicit statements from inference and to allow `unknown`; do not accept unsupported dates, versions, numerical results, or adoption claims.

## Inputs and initial inventory

The available archives and repositories may not match a fixed directory structure. Do not hard-code source paths, archive names, or formats.

Start with a read-only inventory of the supplied inputs. Determine and report the actual ChatGPT and Codex export formats, including unsupported variants, before finalising parser support. Support only formats found in the initial sources plus clearly documented variants that can be tested safely.

Provide a configuration file that identifies:

* source directories and archive labels;
* source type, when known;
* relevant Git repositories;
* project terms and exclusion terms;
* private working directory;
* reviewed corpus output directory;
* optional date range for incremental runs;
* whether an external LLM API is permitted;
* local or external model settings;
* optional redaction patterns.

An example layout is:

```text
sources/                         # supplied externally; never copied into the repo
C:\Users\benco\OneDrive\BODAQS-private\
  engineering-history-work/       # parsed/raw/redacted working data
  engineering-history/            # reviewed private corpus
bodaqs/knowledge/
  history-tool/                   # implementation, templates, and documentation
```

## Required corpus layout

Produce Markdown-first records with YAML front matter in the configured private corpus. A separate YAML, JSON, or CSV version of every record is not required.

```text
<private corpus>/engineering-history/
  README.md
  index.md
  chronological-overview.md
  open-questions.md
  uncertainties.md
  decisions/
  problems/
  experiments/
  topics/
```

Use the smallest set of directories that remains clear. A record can be organised by its primary purpose; avoid duplicate files merely to satisfy multiple categories.

Each record should use front matter similar to:

```yaml
---
title: SD writes and sampling timing
kind: problem-resolution # decision | problem-resolution | experiment | topic | open-question
topics:
  - firmware.storage
  - firmware.sampling
status: resolved # draft | current | resolved | open | uncertain | superseded
applies_to:
  - ESP32-S3 logger
date_range: 2025-11 to 2026-01
confidence: high # high | medium | low
source_refs:
  - Codex:workstation:session-456
  - Git:firmware:abcdef1:src/StorageManager.cpp
code_refs:
  - src/StorageManager.cpp
review_status: draft # draft | reviewed | needs-more-evidence
---
```

The record body should plainly state, where applicable:

* the context or problem;
* observations and supporting evidence;
* options or hypotheses considered;
* the decision, experiment, or resolution;
* implementation and verification status;
* limitations, applicability, and remaining uncertainty.

Use concise source notes or quotations for high-impact, disputed, or numerical claims. Do not expose unrelated raw conversation content.

## Initial workflow

Implement a small, inspectable command-line workflow. Commands may be combined where that improves clarity; do not create separate passes merely for formality.

Suggested commands:

```bash
python -m bodaqs_history inventory --config config/project.yaml
python -m bodaqs_history ingest --config config/project.yaml
python -m bodaqs_history candidates --config config/project.yaml
python -m bodaqs_history draft --config config/project.yaml
python -m bodaqs_history verify --config config/project.yaml
python -m bodaqs_history generate --config config/project.yaml
python -m bodaqs_history all --config config/project.yaml
```

The first iteration should proceed as follows:

1. Inventory the supplied archives and repositories, identify actual formats, hash files, and report anything unsupported or unreadable.
2. Parse supported sources into a private, common representation that preserves conversation/session identity, message order, dates when available, and source paths. Do not silently discard malformed material.
3. Identify likely BODAQS material using project terms and, when configured, semantic classification. Retain enough surrounding context for interpretation. Place borderline material in a candidate queue for human review.
4. Group the selected material into practical topic/date candidates. This may be approximate; it is not a requirement to perfectly segment every episode.
5. Draft a limited number of high-value knowledge records spanning several areas, such as firmware storage and sampling, calibration, IMU selection or processing, analysis methodology, and Garmin/timestamp integration.
6. For important claims, inspect current code and relevant Git diffs or test artifacts. Git inspection is targeted verification, not a requirement to build a complete Git-history database.
7. Generate the Markdown corpus, index, chronological overview, open-questions list, and uncertainties list.
8. Support a human review step before records are described as current project knowledge.

## Candidate selection and factual checks

Prefer topics with one or more of the following:

* an implementation that affects current hardware, firmware, or analysis;
* repeated troubleshooting or recurring confusion;
* a decision with meaningful alternatives or constraints;
* numerical results that influence a design limit or default;
* a later reversal, conflict, or unknown that could mislead future work.

For each drafted conclusion, distinguish these dimensions when relevant:

```text
proposal / decision / implementation / verification
```

For example, a favourable discussion may support a proposal, a merged diff may support implementation, and a test log may support verification. Do not combine those claims without evidence.

Where code, Git history, and discussion disagree, explain the disagreement in the record or `uncertainties.md` and request human review.

## Incremental updates

The initial run is the primary effort. Subsequent runs should normally be conducted roughly quarterly.

Track processed input hashes, source/session identifiers, and the most recent source date in a Git-ignored run manifest. On a later run:

* identify new or changed archives and conversations;
* process only new or changed material where possible;
* identify existing records that may need amendment;
* create draft additions rather than overwrite reviewed content;
* produce a short run summary listing proposed additions, amendments, and newly discovered uncertainties.

Exact duplicate detection is required. Near-duplicate detection, automated cross-archive clustering, and automatic record merging are explicitly deferred unless the initial material demonstrates a practical need.

## Validation and tests

Validation should be proportionate and should fail clearly on structural errors. Check at least:

* input sources are not modified;
* expected Markdown front matter is valid;
* source references resolve to known imported sources where retained;
* record paths and titles are unique;
* Git references point to known repositories/commits when repositories are available;
* reviewed corpus output does not contain secrets detected by the configured redaction checks.

Use small synthetic fixtures to test the parsers for the actual discovered ChatGPT and Codex formats, malformed input, timestamp handling, exact duplicate detection, redaction, and incremental-run tracking. Do not include private conversation content in tests.

## Documentation

Provide a concise README for the tool covering:

* purpose and limits of the corpus;
* supported source formats discovered during the initial inventory;
* configuration and commands;
* private working-data and redaction model;
* external-API opt-in behaviour;
* review workflow;
* how to run an incremental update;
* known limitations and unsupported formats.

Clearly state that generated drafts are not approved engineering truth until reviewed.

## First-iteration deliverables

The first iteration must produce:

1. a source inventory and supported-format report;
2. a private normalised/candidate dataset sufficient to reproduce the drafting process;
3. a candidate queue for borderline or uncertain BODAQS material;
4. a reviewed initial Markdown knowledge corpus spanning the priority technical areas;
5. an index, chronological overview, open-questions list, and uncertainties list;
6. targeted code/Git checks for the highest-impact current claims;
7. a documented incremental workflow and run manifest;
8. a README with commands, privacy limitations, and known unsupported inputs.

## Completion criteria

The task is complete when:

* the supplied sources have been inventoried and their supported/unsupported formats reported;
* relevant BODAQS discussions can be identified and used to draft records with lightweight source references;
* the corpus captures major decisions, resolved problems, important experiments, open questions, and uncertainties;
* key current claims have been checked against code, Git, or test evidence where practical;
* generated records have been reviewed before being presented as current project knowledge;
* the sources remain unchanged;
* a future archive addition can be incorporated incrementally without reprocessing all known material; and
* the README documents operation, privacy limitations, and the next review/update workflow.

Before concluding the task, provide a concise implementation summary, the final directory tree, commands used, tests and results, unsupported formats or limitations, privacy/redaction limitations, highest-priority review items, and recommended next steps.
