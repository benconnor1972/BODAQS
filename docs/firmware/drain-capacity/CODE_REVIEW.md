# T01 independent review and resolution

Fixed point: `1b6caad970ef734b25c361dce4a3dbb6b4ee6b46`.
Initial reviewed tip: `c30f0eac46a28c7c9000fc52e6ea570787e066ff`.
Resolution reviewed tip: `7e97877674f22dfa3cb049a265e9b64f6e19b779`.
The initial diff includes T01 and the approved execution tracking document;
review does not assert completion of T02-T11.

## Standards

Initial finding: **one P2**. The shallow workload merge retained the shared
default ADC-rate list. Mutating the returned effective workload changed later
default evaluations, conflicting with the repository rule against hidden global
coupling. No additional meaningful documented-standard breaches or baseline
smells were found.

Resolution: normalization copies the ADC-rate list, isolating defaults, caller
inputs and returned reports. Fresh independent verification found **zero
outstanding Standards findings**. Public regressions use independent literal
expectations and fail when the copy is removed. All 14 tests pass.

## Spec

Initial finding: **one P2**. Delivery and SPI-burst recovery used slot cost alone,
ignoring the modeled serial-safe request and worker-pacing constraints. A
one-node request-processing scenario incorrectly passed the provisional 100 ms
gate. T01 requires those pipeline/service constraints to be included.

Resolution: delivery and burst estimates use constrained capacity after ADC,
request and worker limits, with continuing traffic charged. Fresh independent
verification found **zero outstanding Spec findings**. Request-constrained SPI
burst recovery reproduces 304.215 ms; a worker-pacing sensitivity reproduces
42.133 ms. These are declared planning envelopes, not physical guarantees.
The report distinguishes adverse simultaneous bursts from the normal delivery
target; no universal fault-lossless requirement was introduced.

Verification confirms all 14 tests pass, 126 cases reproduce, NO-GO remains,
dependents stay disabled and every production-admission flag is false. Installed
bitwise-CRC measurements, unqualified LUT/redesigned costs and conditional wire
floors remain separate. The independent measured-cost four-node failure is
unaffected by either fix.

Summary: Standards 1 P2 resolved, 0 outstanding; Spec 1 P2 resolved,
0 outstanding. Both fixes were implemented together in one fresh isolated
implementer branch, merged by a fresh merger and verified in fresh contexts.
Detailed red/green logs, reports and handoffs remain in the external execution
evidence directory. No target code changed in T01, so no target build or
physical qualification is claimed.
