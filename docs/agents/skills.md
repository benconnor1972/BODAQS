# Project-local engineering skills

Installed for BODAQS on 2026-11-03 in `.agents/skills/`, the project-local Codex
discovery directory. No global skill installation or auto-updating plugin is used.

Source: https://github.com/mattpocock/skills

Pinned upstream commit: `4ae2317ddb22b046e26455e4f9c9b3aaaf62212d`.

Upstream license: `.agents/MATT-POCOCK-LICENSE.md` (MIT).

## Installed bundle

All 27 skills listed in upstream's `.claude-plugin/plugin.json` are installed:
the original nine plus the remaining 18. This includes the complete published
engineering and productivity sets. Upstream `in-progress`, `misc`, and deprecated
directories are outside that published bundle and are not installed.

| Skill | Purpose |
| --- | --- |
| `grill-with-docs` | Clarify a design and capture agreed terminology/decisions |
| `grilling` | Supporting design interview discipline |
| `domain-modeling` | Supporting glossary and decision-record discipline |
| `to-spec` | Draft a specification from agreed conversation context |
| `diagnosing-bugs` | Reproduce, isolate, and verify a bug fix |
| `tdd` | Implement behavior through agreed test interfaces |
| `codebase-design` | Supporting module/interface design discipline |
| `code-review` | Supporting standards and specification review |
| `setup-matt-pocock-skills` | Retained for future reconfiguration |
| `to-tickets` | Split a plan or specification into verifiable tickets with blockers |
| `ask-matt` | Choose a skill or workflow for the current task |
| `triage` | Evaluate incoming issues and propose triage outcomes |
| `improve-codebase-architecture` | Survey module design and improvement opportunities |
| `wayfinder` | Resolve a large effort through linked decision tickets |
| `implement` | Implement an agreed specification or ticket |
| `implement-spec` | Coordinate implementation of a specification's task graph |
| `prototype` | Explore design questions through throwaway prototypes |
| `research` | Investigate a question using primary sources |
| `pr` | Structure a pull request description and evidence |
| `retro` | Review a session for environment and workflow improvements |
| `wizard` | Prepare a guided script for steps a human must perform |
| `grill-me` | Clarify an idea through a design interview |
| `handoff` | Capture context so another session can continue |
| `teach` | Teach a concept in the workspace |
| `to-questionnaire` | Prepare questions for someone outside the session |
| `wait-what` | Explain an unclear message with missing context |
| `writing-for-agents` | Write concise instructions for coding agents |

Full skill directories, including templates and scripts, are vendored unchanged.
BODAQS-specific policy lives in root `agents.md` and `docs/agents/`, so it can be
reviewed independently from upstream updates. Configuration is already written;
there is no need to run the setup skill before first use.

Triage labels are mapped in `triage-labels.md`. Installing skills does not create
GitHub labels or issues, start triage, commit changes, or close completed tickets.
The existing `skills/firmware-build/` skill remains in place and is referenced from
root instructions.

## First use

The local skills should be available on the next turn. If the client retains a
cached skill list, start a new session at the BODAQS root. Invoke a skill by name,
for example:

> Use grill-with-docs to work through this sensor integration, including electrical,
> firmware, and logged-data acceptance criteria.

Or:

> Use to-spec to draft the design we just agreed. Show me the issue before publishing.

For ticket planning:

> Use to-tickets to break docs/specs/<spec>.md into tickets with acceptance criteria
> and blocking dependencies. Show me the breakdown before creating GitHub issues.

`to-tickets` is ready to use with the GitHub tracker configuration. Approving a
breakdown and authorizing publication are distinct: preserve existing authorization,
and publish only when the user has requested creation of those issues. For an
explicit creation request, review the breakdown as the skill requires, then create
the approved tickets without asking for the same authorization again.

GitHub CLI is a separate runtime prerequisite when no GitHub connector is available;
see `issue-tracker.md` for installation, authentication, and access checks.
Changing trackers here does not migrate Azure Boards items or enable GitHub Issues
on the remote repository.

## Updating

1. Choose an upstream commit explicitly and download it into a temporary directory.
2. Review changes to the installed skill directories, including their resources,
   and compare the bundle manifest for additions or removals.
3. Replace only those directories after checking for local edits; preserve other
   project skills and all BODAQS policy files.
4. Copy the upstream license if changed and update the commit recorded here.
5. Check metadata, relative resource links, and compatibility with BODAQS tracker
   authorization and engineering validation rules before adopting the update.

Do not update from a moving branch or install the same set globally as incidental
maintenance. No upstream hooks or bundled scripts run during installation.
