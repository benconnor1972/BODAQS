# 05: Establish and release reset-safe node control authority

## What to build

Allow the idle logger to establish node control using a fresh challenge and
inspect its authority through existing diagnostics. Bind/release changes
authority only: it must not start acquisition, alter hardware settings or
silently relabel old configuration agreement as belonging to a new session.

## Acceptance criteria

- [ ] Nonzero boot/session/challenge identities and five-second challenge expiry follow the confirmed scopes; read and mutation sequences remain distinct.
- [ ] Identical bind retries preserve sequence state; stale/expired challenges and invalid authority changes are rejected without hardware effects.
- [ ] Release requires idle/unlocked state and retains the specified retry tombstone without allowing stale-session mutations.
- [ ] Operation queries identify both target session and sequence; superseded/unknown evidence is distinct from original rejection, and prior accepting-session provenance remains visible.
- [ ] End-to-end tests cover lost bind/release replies, retries, stale boots/sessions, authority preconditions and observable reset invalidation; affected builds pass.

## Blocked by

- Preview 03: Inspect node control state through the logger.

## Publication preview

Repository: benconnor1972/BODAQS. Intended labels: enhancement, ready-for-agent,
when available. No source parent issue was supplied. Preview only; not published.
