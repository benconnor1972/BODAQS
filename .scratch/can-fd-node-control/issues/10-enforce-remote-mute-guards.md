# 10: Reconcile remote mute safely and enforce recording-time restrictions

## What to build

Make idle remote mute/unmute produce explicit verified disabled/enabled node
configuration, while continuing to reserve endpoint ownership. During a
recording, reject remote mute/configuration changes clearly without a hidden
deferred action. Preserve the existing local runtime mute behavior.

## Acceptance criteria

- [ ] Idle remote mute/unmute goes through the shared application path and changes node engine state only after the corresponding explicit transaction.
- [ ] Muted/unassigned supported endpoints reconcile to disabled state; muting does not release desired endpoint ownership or installation information.
- [ ] Web/API/menu attempts to change remote mute/configuration during recording fail before mutation, with an actionable explanation and no later queued change.
- [ ] Node-side recording/active-state guards and independent fault containment are exercised through the control state machine without implementing reserved acquisition/lease commands.
- [ ] End-to-end checks preserve local runtime mute and healthy local recording, and confirm configuration-only remote endpoints remain excluded from acquisition until its deferred prerequisites exist.

## Blocked by

- Preview 07: Save and verify the initial remote LSM6DSO32X profile.

## Publication preview

Repository: benconnor1972/BODAQS. Intended labels: enhancement, ready-for-agent,
when available. No source parent issue was supplied. Preview only; not published.
