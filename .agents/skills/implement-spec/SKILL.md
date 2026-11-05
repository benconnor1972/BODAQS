---
name: implement-spec
description: "Implement the result of /to-spec and /to-tickets in code."
disable-model-invocation: true
---

You have been provided a spec. This spec should have tickets associated with it, describing how to implement the spec.

The issue tracker should have been provided to you. If not, tell the user to run `/setup-matt-pocock-skills`.

The goal is the entire spec implemented on a single **integration branch**, with every ticket resolved the way the issue tracker closes work.

The tickets are not a list of steps. They are a **task graph** with blocking relationships between them. This means there is always a **frontier** of tickets which are ready to be grabbed.

Read `docs/agents/issue-tracker.md` and `docs/agents/engineering.md` before tracker
or branch operations. Carry the user's execution scope through every handoff:
working branch/base, local commit/merge authority, authorized remote actions,
validation gates and deferred physical work. Reuse an existing handoff without
asking again. Local completion can satisfy a dependency while its issue stays open.

Start every subagent with a fresh context window.

Communication to and from subagents should be sparse. Communicate primarily through **context pointers**: to the spec, tickets, research notes, and previous commits. Don't duplicate information already available via pointers.

**Implementer subagents** should be run in the background where possible for maximum concurrency.

## Steps

1. Read the spec and tickets to understand the task graph.

2. (optional) Use an **exploration subagent** to conduct any exploration required by the tickets - relevant codebase files or external documentation. Ensure the exploration subagent can save files - it should save its markdown notes in a directory outside the repo, accessible by all future subagents. This lets **implementer subagents** focus on implementation rather than exploration.

3. Create or resume the authorized integration branch. Create a draft PR only
   when the user has authorized that remote action and tracker policy permits it.
   Otherwise keep implementation and evidence local.

4. Use a fresh **implementer subagent** for each ticket, each in its own worktree on its own branch. Each implementer subagent:
   - starts its isolated worktree from the latest verified integration tip and confirms its base; preserves changes when reconciling an unexpected base;
   - calls the Skill tool with `tdd` to build the ticket;
   - merges the integration branch tip into its own branch before reporting done

5. Once an **implementer subagent** completes, merge its work to the integration
   branch with a **merger subagent**. For changes covered by the
   [firmware boundary checkpoint](../../../docs/agents/firmware-validation.md#boundary-review-checkpoint),
   obtain a focused fresh review of that ticket and resolve findings before
   advancing dependents or packaging. Routine changes keep the existing workflow.

6. If this changes the **frontier** of available tickets, kick off more **implementer subagents** to work on the new tickets. This allows for maximum concurrency.

7. Once all tickets are complete, call the Skill tool with `code-review` on the integration branch. Fix all issues raised by the code review in a single fresh **implementer subagent**.

8. Publish, mark a PR ready, or close issues only within the user's authorized
   remote scope and tracker policy. Otherwise report locally verified completion,
   the integration branch and remaining debt; leave remote state intact.

9. Clean up all **implementer subagent** worktrees.
