# Prototype review and automation retrospective implementation

Authorized by the user on10 November2026. Review base:
`3ef8a34b3c65b2227d8b616dff606e5d5d193f8d`. The source remains on the current
real-acquisition feature branch. Recommendations are recorded externally in
`drain-capacity-evidence/reviews-2026-11-10/01-prototype-production-review.md`
and `02-automation-retrospective.md`.

## Implementation contract

- Preserve acquisition policy, wire acceptance, scheduling profiles, current
  r5 physical candidate and all sealed evidence. No scope, serial, debugger,
  flash, GitHub or infrastructure access follows from local implementation.
- Implement the five unconditional prototype recommendations: ACK_FETCH
  accounting, single-pass decode reasons, bounded coherent bus provenance,
  source/config build identity and a shared mixed diagnostic build profile.
- Implement the retro's reusable offline run specification, readiness/identity/
  participation checks, immutable evidence intake, scoped completion metrics,
  exact versioned snapshot export, historical contrast, guardrail/workspace
  status and operator packets. Device-facing tooling requires an explicit scope
  before it can connect; no device actions run during this work.
- Extend existing candidate, decoder, CI and UTF-8 tools. Keep mechanical
  validation executable and instructions as navigation pointers.
- The optional larger master trace remains conditional, as the review explicitly
  recommended investigation only after a specific unresolved need/RAM budget.
  Remote CI publication, runner provisioning and controlled storage stalls retain
  their existing separate authorization/deferred status.

## Agreed validation seams

Use actual production SPI adapter/codec/lifecycle bodies for accounting, decoder
and provenance changes; check legacy and diagnostic-disabled equivalence.
Exercise the public candidate/run/evidence CLIs and real BDQ reader/assessment,
using independent historical/synthetic inputs and deliberately invalid identity,
scope, truncation, array and uint64 cases. Existing r5 HAL bounds and mutation
controls remain wired; add boundary coverage only for concrete contracts.
Fresh boundary review precedes dependent packaging; final Standards/Spec review
covers this contract and both originating reports.

## Work and evidence

1. Firmware observation corrections and boundary controls: implemented. Actual
   adapter covers invalid proof, cross-class successor and duplicate retirement;
   decoder and bus/footer tests preserve rejection and owner publication.
2. Build recipe identity, mixed/RX2 profile, declared peer reuse and typed review
   source/evidence binding: implemented in the shared candidate runner.
3. Versioned run spec, complete exact snapshot helper and immutable content-based
   evidence workflow: implemented; missing/rounded/contradictory inputs fail closed.
4. Separate completion/metric scopes, historical source contrast and actual sensor
   participation gates: implemented without relaxing strict delivery acceptance.
5. Offline operator packet, dry-run bounded device scope and workspace/guardrail
   status: implemented. Actual serial/control adapters remain a separately scoped
   later stage; this work deliberately executes no device actions.
6. Existing CI plan/UTF-8 bridge extended; boundary contract inventory and usage
   are in `Bench_Automation.md`. Final whole-change review follows the implementation.

Initial validation: full shared mixed host plan passed (logger, common, master,
node, control, integrated and analysis:602 passed/1 skipped). The selected A8 mixed
logger and acquisition RX2 master target builds passed. Later targeted additions
and independent Standards/Spec review are recorded with the external evidence.
Windows PowerShell/native UTF-8 roundtrip and the bench wrapper passed locally.

The fresh diagnostic boundary review found missing predecessor operation fields
and ambiguous optional v5 layouts. Both were corrected with tests, including
capture-disabled timing, independent decoder output sentinels and footer fields.
The complete CCS helper is validated offline only; live CCS execution remains
unexercised. Branch workflow presence is not a remotely exercised/default-branch
guardrail. See `Bench_Automation.md` for commands and exact remaining scopes.

Whole-change reviews found and corrected: missing recorded-source binding,
identity-free/partially counted whole-run denominators, omitted selected board
JSON, missing ADC buffer source contrast and a review/source race during preflight.
Regression checks cover these paths. Source identity and strict delivery remain
separate verdicts, and no physical or admission qualification is claimed.

Implementation evidence belongs outside the source worktree in
`drain-capacity-evidence/prototype-retro-implementation-2026-11-10`.
Physical first-byte cause and mixed-load qualification remain unresolved.
