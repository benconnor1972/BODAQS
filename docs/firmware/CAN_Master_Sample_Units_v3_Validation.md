# T01 sample-unit validation

13 November 2026. Implements #201's host walking skeleton on
`design/imu-protocol-redesign`. Firmware code is in `db28d7a3`; independent epoch
association correction is in `34176a60`. No issue is closed by this report.

## Outcome

Known unchanged-node fixture output reaches production master service, scoped
logger RAM custody, the new compact BDQ schema and independent decoding. All65
known signed six-axis readings and source sequences survive. A lost sample ACK
replays without duplicate recorded units/readings. Physical framing remains256B,
with at most3CAN payloads/15readings per sample unit and one immutable selected
head per node; multi-unit windows are not claimed.

The new profile also passes the existing complete recording fixture through the
production logger master-link manager, acquisition coordinator, recording gate,
storage owner/writer and independent decoder. Hardware clocks/SPI/filesystem
boundaries are substituted there; it is not physical qualification.

## Checks and evidence

- Initial red: the existing implementation rejected the new test's required v3
  profile (`1 != 3`). The complete node-to-recording slice now passes.
- New focused runtime:65expected readings; lost ACK; invalid physical CRC;
  truncated frame; CRC-valid v2 version mismatch; foreign context; wrong-object
  ACK; retained-object replay. Invalid input does not retire the observed head.
- Offline corruption test: change accepted axes and recompute the BDQ payload
  CRC. The master-origin checksum rejects the data before exposing readings.
- Semantic association test: change packet epoch and recompute **both** upstream
  and storage CRCs. The decoder rejects attachment to another source segment.
- Full host runner passed: firmware, common protocol, master adapter, node,
  sample-unit runtime, control regression, existing integrated recording and full
  analysis. Analysis result: **638passed,1skipped**,7warnings. This is host mode
  with working edits, not a source-sealed release candidate.
- Supplemental complete v3 recording fixture passed with
  `--first-recording --sample-units`; that command is now included in future
  candidate/host plans as well as the focused unit runner.
- Focused historical analysis regressions:56passed. Candidate-runner unit tests:
  13passed. Windows PowerShell rendered unittest's stderr as a native-error
  record despite the Python log reporting `OK`; the test result is taken from
  the actual completed unittest report, not that shell formatting artifact.
- A8 target `bodaqs_s3_mini_n4r2_imu_units` compiled successfully. Static RAM
  266,932/327,680bytes; flash2,077,213/4,063,232bytes. These are build figures,
  not dynamic/PSRAM/stack-watermark qualification.
- MSPM0 master acquisition target compiled with `SPI_SAMPLE_UNITS=1`, RX2,
  TX priming and disabled-SPI initialization. Map reports BANK0unused1,135bytes,
  BANK1unused63,744bytes and4,096bytes reserved stack. No runtime margin is inferred.

Owned local evidence directories alongside the source worktree:

- `protocol-units-t01-host-20261113`: full host manifest/logs/scenarios.
- `protocol-units-t01-integrated-20261113`: supplemental v3 files/control ledgers.
- `protocol-units-t01-targets-20261113`: local build logs, images, map and SHA256
  manifest. These are unqualified working-tree target builds, not a sealed bundle.

Image hashes:

| Image | SHA256 |
|---|---|
| Logger binary | `a7f789a23830da070fb2d6907d629744576ba9771d982a9946b64170dd87865f` |
| Master ELF | `2fb38b3c174e798adfbe7acba17349322de6922c4ad40bbee2b2559c820c836e` |

## Review and remaining debt

Fresh Standards and Spec/boundary reviews used baseline `c5ed857a` against
`db28d7a3`. Standards found no documented breaches or material heuristic smells;
Spec found no initial confirmed T01 scope/ownership defects. Standards additionally
identified the missing independent packet-epoch/source-segment association check.
Both reviewers inspected `db28d7a3...34176a60` and confirmed that finding resolved
with no further confirmed findings. Exact CS/first-byte physical behavior remains
a hardware validation task despite passing adapter regressions and compilation.

No device discovery, probe or flashing occurred. No throughput, ADC freshness,
analog amplitude/isolation, native timing accuracy, IRQ or workload admission pass
is claimed. The sample-unit decoder deliberately returns unreconstructed timing;
later tickets own reconstruction and multi-source qualification. Missing essential
source definitions leave raw unit words retained and readings explicitly unverified.

T02 (#202) is the next physical milestone. Its ticket still depends on #201 in
the tracker; implementation completion does not authorize automatically closing
#201 or altering its parent/dependencies. Existing profiles remain unchanged and
no production admission is enabled by this unqualified build.
