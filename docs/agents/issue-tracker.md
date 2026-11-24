# Issue tracker: GitHub

New BODAQS backlog items and published specifications live in
[benconnor1972/BODAQS Issues](https://github.com/benconnor1972/BODAQS/issues).
Azure Boards is retired for new work. Existing items remain untouched unless the
user explicitly requests migration or changes.

## Access

Use a connected GitHub tool when available; otherwise use GitHub CLI (`gh`).
Always explicitly target `benconnor1972/BODAQS`; never infer an upstream skill
repository as the target.

For a new machine, install GitHub CLI and authenticate:

```powershell
winget install --id GitHub.cli --exact
gh auth login --hostname github.com --git-protocol https --web
gh repo view benconnor1972/BODAQS --json nameWithOwner,url,hasIssuesEnabled
```

Reopen the terminal after installing if `gh` is not on PATH. If access fails or
Issues is disabled, report the prerequisite and keep the proposed issue local;
do not fall back to Azure Boards or silently enable repository settings.

## Write rules

- An explicit request to add/create an issue authorizes that issue. Otherwise
  show the proposed title and body before publishing. Invoking a drafting skill
  alone does not authorize a remote write.
- Do not delete issues, bulk-update issues, or close/reopen issues unless
  explicitly requested. Implementation completion does not authorize closing.
- Do not post comments, change labels, or assign people as incidental cleanup.
  Include intended remote changes in the authorized work or preview them first.
- After creation, report the issue number and URL.
- Do not create issues as part of installing or updating skills.
- **PRs as a request surface: no.**

## CLI examples

Run from the BODAQS root. Read operations:

```powershell
gh issue list --repo benconnor1972/BODAQS --state open --json number,title,labels
gh issue view 123 --repo benconnor1972/BODAQS --json number,title,body,labels,comments
```

For an authorized creation, write the exact multiline body to a UTF-8 temporary
file, then pass it with `--body-file`:

```powershell
gh issue create --repo benconnor1972/BODAQS --title "Approved title" --body-file $issueBodyPath
```

## Specifications and labels

`to-spec` drafts a specification from the conversation; its default instruction
to publish is subject to the write rules above. Scale the specification to the
feature, including acceptance evidence and affected hardware/firmware/software
interfaces. Existing local specifications remain under `docs/specs/`.

Read `triage-labels.md` for the category/state label mapping. Apply labels only
within the authorized tracker operation. If an authorized specification or ticket
publication calls for `ready-for-agent`, use it when that label exists and the scope
is ready for implementation. If missing, publish without it and report the omission;
creating the remote label requires authorization. Installing `triage` does not run it.

## Ticket planning and dependencies

`to-tickets` drafts independently verifiable slices, acceptance criteria, and
blocking relationships from a conversation, local specification, or GitHub issue.
For a referenced GitHub issue, read its body and comments first. Present the
breakdown and dependencies for review before publishing. A planning-only request
stays a preview; an explicit creation request authorizes the approved ticket set.

Create tickets in dependency order and report each issue number and URL. Use
native GitHub blocking relationships when available. If a source issue is the
parent, include the intended sub-issue links in the publication preview. Do not
close or rewrite the parent, or reparent existing issues without authorization.

The REST API works through `gh api` without relying on newer issue CLI flags.
For example, once the issue numbers are known and these relationships are authorized:

```powershell
$blockerId = gh api "repos/benconnor1972/BODAQS/issues/$blockerNumber" --jq .id
gh api --method POST "repos/benconnor1972/BODAQS/issues/$ticketNumber/dependencies/blocked_by" -F "issue_id=$blockerId"
$childId = gh api "repos/benconnor1972/BODAQS/issues/$ticketNumber" --jq .id
gh api --method POST "repos/benconnor1972/BODAQS/issues/$parentNumber/sub_issues" -F "sub_issue_id=$childId"
```

These payloads use numeric database IDs, not issue numbers or `node_id`.
Verify created links with read operations. When native linking is unavailable,
retain explicit `Blocked by: #123` and `Parent: #456` references in the new issue
bodies and report the limitation. Check all blockers are closed before treating a
ticket as startable; a `ready-for-agent` label alone does not imply it is unblocked.

API references: [issue dependencies](https://docs.github.com/en/rest/issues/issue-dependencies)
and [sub-issues](https://docs.github.com/en/rest/issues/sub-issues).
