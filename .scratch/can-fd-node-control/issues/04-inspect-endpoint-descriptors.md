# 04: Inspect coherent endpoint capabilities and effective state

## What to build

Let the logger inspect a node endpoint before acquiring command authority.
Transport immutable capability and effective-state snapshots through both links
and display current versus unknown/historical observations honestly. Initially
an unconfigured IMU may have zero enabled profiles and no acquisition readiness.

## Acceptance criteria

- [ ] The confirmed 128-byte capability and 192-byte effective descriptors traverse requested 24-byte pages end to end with strict schema/mask validation.
- [ ] One snapshot per node is immutable and bounded to five seconds; retries do not renew it, and mixed, incomplete, expired or conflicting snapshots are never adopted.
- [ ] Presence, implemented support, profile catalog, health and readiness remain separate; endpoint presence does not manufacture acquisition/SYNC capabilities.
- [ ] JSON/Health diagnostics distinguish observational snapshots, verified/current data, historical data, unknown fields and fields that do not apply.
- [ ] Host integration checks exercise multi-page corruption/loss, field masks, nominal-versus-measured values and unavailable hardware evidence; affected builds pass.

## Blocked by

- Preview 03: Inspect node control state through the logger.

## Publication preview

Repository: benconnor1972/BODAQS. Intended labels: enhancement, ready-for-agent,
when available. No source parent issue was supplied. Preview only; not published.
