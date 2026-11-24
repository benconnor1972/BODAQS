# Recording membership and qualification (#227)

The production candidate uses one admission decision for START, the status API,
configuration notices and the idle display. Configuration agreement, coverage by
a qualification profile, and successful resource reservation are separate facts.
Reconciliation does not establish capacity or reserve memory.

`recording_best_effort` defaults to false. Strict START requires every currently
requested participant. Runtime mute overrides are part of the requested selection;
configuration slots remain stable even when earlier slots are CAN assignments or
absent devices. Best-effort mode may exclude unavailable participants, with their
identities and reasons recorded. Unsupported or ambiguous configuration still
blocks START. A failed local initialization or remote PREPARE/COMMIT cannot
silently reduce strict membership. A failed shared reservation blocks both modes.
No admission action changes requested rates to disguise overload.

`RecordingReadiness` consumes a separately supplied, trusted qualification profile
with an identifier, revision, matching board profile and acquisition contract
`a8-count-first-bulk512-v1`. Its bounded coverage callback evaluates the complete
selected load. It must not perform acquisition or control transactions. No general
numerical policy is installed by this integration, and the old fragment-protocol
cost model and exact experiment allow-lists are not production admission policy.
Absent coverage, production START is refused with a qualification reason.

The separately named integration-candidate build can explicitly allow an unknown
qualification result for measurement. That build-only override cannot bypass
invalid configuration, known profile rejection, membership requirements or failed
resource reservation. It is reported as unqualified in UI/API and recordings.
It is not a user configuration option or a production release bypass.

Idle `can_prepare` means sensor membership and qualification permit attempting
START. Storage, power and actual memory/worker reservations are checked during
START. `acquisition_ready` requires actual recording and acquired reservations;
it is no longer a hardcoded false or a synonym for node reconciliation. Resource
failure and retained ownership remain explicit blockers. This adds no recording-
time polling or new scheduling, priority, core or overload-response policy.

The header contains a `bodaqs.recording_membership.v1` preparation declaration,
including a configured-source inventory, requested/selected/excluded masks,
qualification provenance and explicit zero-data exclusions. The bounded final
summary records the final admission selection and reservation outcome. A header
selection cannot prove a source subsequently started. Source faults after START
remain separately identified in operational completion/failure evidence.

Normal import exposes this inventory in session metadata and reports exclusions.
Missing or inconsistent final membership leaves its outcome unknown; it never
creates samples, declares full delivery or invents a final admitted selection.
Historical recordings without the declaration remain readable.

Host validation exercises strict/best-effort, invalid/unknown qualification,
candidate scope, registration ownership, missing participants, slot holes,
resource failure and metadata/import uncertainty. Target builds and host models
do not qualify a load envelope. General policy, representative physical START/
STOP and sustained mixed-load checks remain release gates.
