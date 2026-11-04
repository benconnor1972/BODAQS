# 07: Save and verify the initial remote LSM6DSO32X profile

## What to build

Let a user configure the canonical remote LSM IMU type and initial profile,
save through the shared idle path, and see verified settings from the physical
node without restarting. Enabled-stopped runs the programmed sensing engines
but does not collect, sequence, batch or transport samples.

## Acceptance criteria

- [ ] The canonical LSM type/profile accepts existing CAN provider/IMU assignment syntax and shared logical calibration/mounting metadata without BMI-specific acquisition validation or decoding.
- [ ] Profile 1/version 1 programs matched nominal 3.33 kHz, +/-32 g, +/-2000 degrees/s and the confirmed filter/register policy; the profile catalog advertises only implemented support.
- [ ] Saved desired settings, pending apply, verified effective settings, explicit rejection/adjustment and fault evidence are distinct in API/UI; valid desired settings survive remote application failure.
- [ ] Fresh no-op verification, revision behavior, nominal scales, accepting-session provenance and explicit unknown timing/performance fields match the contract; acquisition readiness stays false.
- [ ] Integration tests and all affected builds pass; on-device acceptance records SPI/register evidence and enabled-stopped versus disabled behavior without claiming FIFO/sample or signal-response validation.

## Blocked by

- Preview 01: Apply idle sensor edits consistently across configuration entry points.
- Preview 06: Reconcile an IMU endpoint to verified disabled state.

## Publication preview

Repository: benconnor1972/BODAQS. Intended labels: enhancement, ready-for-agent,
when available. No source parent issue was supplied. Preview only; not published.
