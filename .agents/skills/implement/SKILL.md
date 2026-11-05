---
name: implement
description: "Implement a piece of work based on a spec or set of tickets."
disable-model-invocation: true
---

Implement the work described by the user in the spec or tickets.

Read `docs/agents/engineering.md` and preserve the user's working branch,
publication scope and deferred validation. For firmware boundary changes, use
the focused review checkpoint linked there before final candidate packaging.

If the user passes a ticket reference, fetch it from the issue tracker and state its title before starting. If the reference is ambiguous, ask.

Call the Skill tool with "tdd" where possible, at pre-agreed seams.

Run typechecking regularly, single test files regularly, and the full test suite once at the end.

Once done, call the Skill tool with "code-review" to review the work.

Commit to the current branch when authorized by the task or repository workflow.
Remote publication and issue changes follow the user's scope and
`docs/agents/issue-tracker.md`.
