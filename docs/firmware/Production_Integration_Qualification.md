# A8 production-integration qualification

This is the remaining acceptance plan for #230, against the confirmed Q1–Q32
scope. It is not a qualification result. Software evidence and physical evidence
must remain separate. The destination remains `feat-CAN-firmware`; final
integration follows review and the representative checks below.

## Candidate and evidence ownership

Use the packaged `bodaqs_a8_integration_candidate` for measurements. Its explicit
unqualified status must appear in readiness and recordings. Ordinary
`bodaqs_a8_production` must refuse an uncovered configuration; it must not silently
inherit candidate admission. Reconciliation alone does not prove capacity.

Before installation, record package manifest, logger recipe and actual image
hashes, A8 board identity, matching master/node identities, SD card and test
configuration. Use the package's exact offsets and installation guidance. Never
substitute an app from one package into another recovery image.

For each case, preserve a directory containing `serial.txt`, the configuration
actually used, finalized BDQ, applicable master export, and an assessment. Record
the boards restarted, test duration, operator actions and any missing evidence.
Copy recordings only after visible finalization; uncertain prefixes remain
useful evidence but cannot establish a clean STOP. No complete flash backup is
required. Keep private network settings out of shareable evidence/packages.

## Representative hardware gates

| Gate | Procedure | Required observation |
|---|---|---|
| Unattended boot | Boot with no serial console; repeat after using Wi-Fi. | Controls become responsive without benchmark prompts. START reservation failure is visible and retryable; no unexplained boot wait. |
| Migration | Load a retained old configuration, inspect web and physical review, accept once, reboot. Also inspect an unsupported source. | Exact proposed changes and preserved original; acceptance persists. Unsupported settings stay visible and block START. Rejected/failed saves do not claim application. |
| Lifecycle | START, STOP, repeat STOP, then START a second session without power cycling; exercise read-only navigation while stopping. | Visible preparation/running/retirement/finalization; no mutations or new START while ownership remains. Successful finalization restores controls and releases resources. |
| ADC layouts | Exact and fractional common row rates; unequal channel counts, sparse subsets and one idle ADC. | Source/count order matches configuration, no dummy participants or silently changed rates. Missed appointments and reused/unavailable readings remain explicit. No simultaneous-sampling claim. |
| Native sensor smoke | Available analog/string-pot, rotary, local BMI270, GPS and CAN sources, with preview closed and open. | Supported paths record typed counts/native observations and settings. Preview does not consume FIFO data, trigger extra reads or advance wrap tracking. Unavailable hardware is recorded as untested. |
| Membership | Strict missing source; explicit best effort with one unavailable source; no eligible sources. | Strict refuses; best effort identifies each exclusion; no empty ghost session. Requested/selected/final membership and reservation status agree across UI, API and file. |
| Node preparation | Four-node cold boot, saved profile change, node arrival/reboot and one failing peer. | Measure request-to-ready for each healthy peer and overall readiness, including blocker. Failing peer does not monopolize controls/progress. Reuse never crosses stale identity/context. |
| Normal import | Import finalized native recordings and a recoverable incomplete copy through the normal Import Manager; read retained BDQ-v1 and export CSV. | Embedded calibration supplies supported engineering values. Missing calibration remains usable raw data. Counts, identity, gaps and uncertain tails survive. No fabricated engineering values, time alignment or completeness. |

Measure preparation against the preserved pre-integration behavior under the same
node/configuration conditions. Do not substitute modeled service time for a
physical latency result, or report a fixed boot deadline without measurements.

## Sustained mixed-load comparison

Use one established reference load first: four native 3333 Hz CAN IMUs with one
1000 Hz channel per ADC, subject to the exact configuration being permitted by
the candidate. Preserve the r133 reference assessment rather than treating its
short run as a sustained guarantee. Run the agreed representative sustained
duration (ten minutes is the existing practical reference), and perform normal
STOP plus a second START afterward.

Assess useful retained ADC row rate, missed rows, reused/unavailable values and
freshness; source-bounded IMU delivery and explicit gaps; storage/receiver/master
queue peaks and losses; timing uncertainty; and finalization outcome. Compare
the same definitions and source bounds, not wire traffic or scheduled rows alone.
Keep separate each cause of loss and whether final source boundaries are known.

Capture internal free heap, largest available block and relevant queue headroom
at idle, after preparation, during the run and after finalization/restart where
existing bounded diagnostics allow it. Record unavailable measurements. The
49,392-byte static DRAM reduction measured during path retirement is an ELF
result; it does not establish runtime free heap or fragmentation improvement.
No increase in the admission envelope follows from that number alone.

## Deliberately outstanding work

General numerical admission-policy development, known-voltage/MUX accuracy and
settling qualification, controlled storage stalls, expanded I2C mixing and the
deferred physical fault campaign remain unperformed unless separately recorded.
Host fault models cover ownership/error semantics; they do not replace device
fault tests. Implemented but untested profiles remain unqualified.

Only mark each gate complete with linked actual evidence. Software build/test
success, source inspection and a reproducible package are necessary inputs, not
a qualified release or permission to claim every selectable load works.
