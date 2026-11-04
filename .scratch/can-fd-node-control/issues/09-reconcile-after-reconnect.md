# 09: Recover idle configuration after disconnects and node or master restarts

## What to build

Reconcile the saved desired configuration automatically when an idle system
discovers or regains compatible hardware, including a replacement at the same
strap address. Show what remains known, historical or uncertain during faults
and recovery, while preserving independent healthy local logging.

## Acceptance criteria

- [ ] Idle discovery/reconnect and master/node boot changes invalidate stale authority/agreement and establish fresh session/application/readback before reporting agreement.
- [ ] Lost results and superseded caches trigger bounded outcome inspection/readback; neither transport silence nor unknown outcome is treated as rejection or old-state proof.
- [ ] Compatible replacement at an unambiguous strap address inherits saved settings and installation data with new provenance; duplicate-address protection is never bypassed.
- [ ] Stale observations, sensor faults, failed apply and successful recovery remain visible with stable diagnostics; reconciliation waits until recording ends when required.
- [ ] Fault-injection integration checks cover outages/resets/replacement and eventual recovery without restart loops or frozen control slots; hardware recovery evidence is recorded with board/firmware identity.

## Blocked by

- Preview 07: Save and verify the initial remote LSM6DSO32X profile.

## Publication preview

Repository: benconnor1972/BODAQS. Intended labels: enhancement, ready-for-agent,
when available. No source parent issue was supplied. Preview only; not published.
