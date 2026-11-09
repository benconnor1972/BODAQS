# CAN-FD IMU acquisition and sample transport contract

Date: 4 November 2026. **Design confirmed; interview closed at Q147.**
Accepted requirements are Q71-Q147 in [the network contract](CAN-FD_Network_Protocol.md),
section 13.17.
Q139 accepts acquisition control layouts, Q140 mode-recovery semantics, Q141
evidence-before-data persistence, and Q142 sections 2/4/5 packet layouts. Q135
accepted 192 bytes; Q143 extends the companion schema to 224 bytes. Q144-Q146
complete cleanup transport, protected classes and emission budgets. The user
confirmed shared understanding at Q147. No implementation or qualification is implied.
Existing Q1-Q70 [control allocations](CAN-FD_Node_Control_Contract.md) remain
binding. Preserve historical numerical profiles and deferred bench tests.

9 November authorization update (#180): the coordinated node/logger acquisition
lease is now 5000ms, with normal fresh renewal attempts once per 1000ms.
Challenge validity stays 300ms. The node derives its deadlines from challenge
issuance; the logger confirms a conservative deadline of local request dispatch
plus 5000ms, never reply arrival plus 5000ms. Lost challenges/results and explicitly
retryable busy/aged/timeout outcomes allow another bounded fresh attempt while
the previous confirmed lease remains valid. Neither sending a request nor an
unmatched/stale response extends local authority. STOP, expiry, identity faults
and terminal node responses remain terminal, with no automatic rejoin. Initial
PREPARE still requires a successful fresh proof. This update does not establish
physical STOP/expiry latency or authorize a workload. The longer fallback tail
must be reconciled separately in the first-recording lifecycle implementation.

## 1. Accepted architecture and boundaries

- Tagged continuous FIFO, timestamp every slot, acceleration DRDY on INT1,
  watermark on INT2; nominal 4 MHz sensor SPI and bounded DMA bursts.
- Nominal 1 MHz node/master capture clocks, explicit extension/rollover,
  separate sensor timestamp clock. Six-axis items pair validated FIFO slots;
  timestamps refer to acceleration output-ready, modeled where necessary.
- Preparation is leased, discards samples, and precedes explicit START.
  Recording membership, source continuity, timing models and clock epochs
  are distinct. STOP/cancel is terminal; membership requires explicit release.
- Compact CAN samples remain unchanged. Additional raw timing evidence is
  retained selectively. Master forwards receptions; logger expands BDQ records.
- 8 MHz/64-byte measurement SPI, fragmented immutable batches, 1 KiB maximum,
  complete logger-RAM acknowledgement, per-node retention/fairness. Existing
  84-byte/4 MHz bootstrap remains compatible outside measurement mode.
- Per-node companion evidence streams and a new 28-byte LSM sample schema.
  Unknown alignment does not prevent recording. The 10 us pairwise target is
  unverified and does not establish sensor/filter phase performance.

## 2. Accepted physical measurement slot (Q142)

All integers little-endian. Magic is ASCII `BM`; version is 1.

| Offset | Bytes | Field |
|---:|---:|---|
| 0 | 2 | Magic |
| 2 | 1 | Measurement version |
| 3 | 1 | Kind: sample/evidence/control fragment, poll, ACK, status or error |
| 4 | 8 | Negotiated measurement context ID |
| 12 | 4 | Immutable batch/object ID |
| 16 | 1 | Node address 0-3, or master-wide 0xFF |
| 17 | 1 | Fragment index |
| 18 | 2 | Logical total length |
| 20 | 40 | Fragment bytes, unused bytes zero |
| 60 | 4 | CRC-32/ISO-HDLC of bytes 0-59 |

For fragment kinds, offset is `index * 40`, count is `ceil(total / 40)`, and
final meaningful size follows from total. Total is 1-1024 including the
logical trailing CRC; actual object minima are schema-specific. At most 26
fragments are needed. Logical CRC covers canonical context, node, object
class/identity/length and content, excluding its own checksum. Section 2.1
defines the canonical prefix; CRC is integrity, not authentication.

An ACK echoes context, node, object identity, total and logical checksum.
It means complete validated RAM acceptance, never SD persistence. Incomplete,
mixed, conflicting, unknown-context or invalid-CRC objects are not published.
Retain the selected batch and duplicate result through trustworthy same-boot
SPI recovery. A physical slot sequence cannot replace existing CAN operation
identity. Separate control assembly from the single selected sample/evidence
batch per node, so a pinned data batch cannot obstruct renewals or STOP.

The registry below defines identity, polling, acknowledgement and errors.
Never silently wrap object IDs or use mutable queue position as identity.

### 2.1 Accepted registry and bounded transfer state (Q142)

Physical kinds: IDLE=0, POLL=1, SAMPLE_FRAGMENT=2, EVIDENCE_FRAGMENT=3,
CONTROL_FRAGMENT=4, ACK=5, STATUS=6, ERROR=7, CONTEXT_CONFIRM=8,
CONTEXT_EXIT=9, BRIDGE_REQUEST=10, BRIDGE_RESPONSE=11,
AUTHORIZATION_FRAGMENT=12, MASTER_EVIDENCE_FRAGMENT=13 (Q145). Others reject.
Fragment families use the section 2 length/index rule. Transport-management
messages have kind-specific fixed payloads, zero unused bytes and slot CRC;
they are not sample/evidence batches.

Canonical logical-checksum prefix (20 bytes): context u64, object ID u32,
node u8, object class u8, direction u8 (logger-to-master=0, reverse=1), zero u8,
total length u16, zero u16. Append content excluding its final checksum, then
calculate the existing ISO-HDLC CRC. Object IDs are nonzero and never reused
within context/node/class/direction. Zero selects a head only in POLL; it is
not a mutable identity. ID exhaustion fails closed rather than wraps.

POLL body byte 0 selects object class; remaining bytes zero. A nonzero header
object ID/index asks for that immutable fragment; zero asks for an eligible
head. Responses are pipelined and demultiplexed by identity, not assumed to
answer the MOSI request in the same transaction. ACK body is class u8,
disposition u8 (accepted=1, duplicate=2), reserved u16, logical checksum u32,
32 zero bytes. Its header echoes the original object ID/total, index zero.
Retain one last-accepted identity/checksum per ordered class/node/direction;
older objects are rejected, equal objects return the cached ACK, conflicting
equal identities are integrity faults. Cache lifetime is the context. Separate
control assembly/cache prevents pinned samples from obstructing authorization.

Management ERROR body: referenced class u8, reason u8, field u16,
detail u32, 32 zero bytes. Reasons: 1 version, 2 length, 3 checksum,
4 context, 5 conflicting identity, 6 stale identity, 7 incomplete, 8 busy,
9 capacity, 10 not quiescent, 11 cleanup pending, 12 timeout, 13 unsupported,
14 untrusted state. These are a new namespace, not existing node result codes.
Invalid-CRC/unknown-context input never changes authority or accepted data.

### 2.2 Management and bridge encodings

STATUS uses master-wide node 0xFF, index/total zero, and a fresh observational
query token in object ID. Request body is zero. Response body is current master
boot u64, owning session u64, recording ID u64, actual context u64, phase u8,
reason u8, reserved u16 and flags u32 (40 bytes). Header echoes query context/
token even for an unbound read-only query; the payload reports actual state.
Such a response never activates that context or accepts a data object. This
allows bounded 64-byte inspection without an unbudgeted legacy probe during
local recording. Validate fresh correlation; a preloaded reply is not fresh
authority evidence. STATUS flags: active=bit0, fence-complete=1, cleanup-needed=2,
native-clock-trusted=3; other bits zero. These are observations, not grants.

CONTEXT_CONFIRM/EXIT use node 0xFF, object ID equal to the staged legacy request
sequence, index/total zero. Body: version u16, maximum logical bytes u16,
physical bytes u16, reserved u16, inactive-CS us u32, SPI Hz u32, then 24 zero
bytes. Require exact staged limits and context. Confirm activates staged entry;
EXIT marks staged closure only when authorization and fences permit. Reply is
correlated STATUS. Management IDLE has index/total/object zero and zero body.

Bridge request/response use class 6, node 0xFF and nonzero token in object ID.
Request content is token u32; response content is token u32, observed master
tick u32, master clock epoch u32. Append canonical logical CRC (lengths 8 and
16); unused physical bytes zero. Cache duplicate token replies with the same
original observation. Logger retains the original L0 across retries; only a
new token establishes a new request bracket. Never wrap tokens within context.
Expire a still-incomplete exchange at 300 ms without extending the deadline;
record missing/unknown bridge evidence and continue under Q80/Q92. No bounded
observation is emitted from an incomplete or mismatched exchange.

Sample/control/evidence object minima are schema-specific. Control objects
are exactly 64 unchanged wrapper/record bytes plus CRC4, on class 3 or 4;
node remains 0-3. Authorization class 4 admits GET_LEASE_CHALLENGE, RENEW_LEASE
and urgent STOP, preserving each opcode's existing sequence meaning. Master
evidence class 5 is distinct from received CAN: header schema u16, kind u8,
flags u8, count u16, reserved u16; each event is kind u8, reserved u8, flags
u16, SYNC sequence u32, master edge tick u32, master clock epoch u32. Master
SYNC event kind is 1. Total includes CRC4; a single event is 28 logical bytes.

## 3. Mode negotiation and acquisition control

Negotiate full master boot, logger control session, acquisition recording ID,
context ID, version and capacity before measurement slots. Section 3.2 defines
entry/exit, activation and restart recovery. Preserve context during Q119
recovery; retire it at recording end.
Do not use an unsolicited bootstrap exchange during recording as an assumed
safe fallback; its mutex occupancy differs from the measurement requirement.

Transport the unchanged 12-byte SPI wrapper plus 52-byte common control record
as a fragmented logical control object, with its own logical checksum. Do not
change existing mutation, retry, result or uncertainty semantics. Section 3.1
defines acquisition commands in reserved 0x20-0x2F. Renewal has its own
deadline service, never wait behind a one-second configuration retry.

**Accepted ownership (Q127):** Defined FIFO/interrupt/timestamp lifecycle writes
are verified acquisition-runtime transitions: preserve applied revision,
advance state epoch and publish phase-appropriate current register proof.
Desired profile edits remain forbidden under membership. Historical proof cannot
establish active readiness. Add preparation verification and a separate active
readiness predicate; retain stopped configuration reconciliation. START is a
logical boundary without sensing-engine or clock reprogramming.

### 3.1 Accepted acquisition operations (Q139)

New opcodes below use the existing 52-byte common record and node-wide endpoint
0xFF. Initial participation is IMU bit 0 only; reject unsupported bits rather
than infer future endpoint support. Existing allocations and descriptor lengths
are unchanged. Q139 accepts these layouts; sections 2, 3.2 and 5.1 complete
transport/status/reason encoding.

| Opcode | Operation | Correlation |
|---:|---|---|
| 0x20 | BEGIN_PREPARE | Ordinary staged mutation |
| 0x21 | WRITE_PREPARE_PAGE | Same staged operation/transfer |
| 0x22 | COMMIT_PREPARE | Same operation, fresh initial lease proof |
| 0x23 | ABORT_PREPARE_STAGING | Staging only, never accepted acquisition |
| 0x24 | START | Ordinary mutation |
| 0x25 | STOP | Ordinary mutation with protected dispatch/cancellation |
| 0x26 | GET_LEASE_CHALLENGE | Independent read/authorization request |
| 0x27 | RENEW_LEASE | Independent authorization sequence |
| 0x28 | OPEN_ACQ_STATE | Immutable observational snapshot |
| 0x29 | RELEASE_MEMBERSHIP | Ordinary mutation naming observed record |
| 0x2A | FENCE_OLD_DATA | Ordinary mutation, stopped/invalid authorization only |
| 0x2B-0x2F | Reserved | Unsupported |

Use schema 4/v1 for a 112-byte preparation request: schema u16, version
u16, length u16, participant mask u8, reserved u8 (bytes 0-7); recording ID u64
at 8; expected configuration revisions u64[6] at 16; expected endpoint state
epochs u64[6] at 64. Unused endpoint entries are zero. BEGIN data is schema/
version/length/mask/reserved at 0-7, recording ID at 8-15, eight reserved zeros.
WRITE pages carry 24/24/24/24/16 bytes. Apply existing immutable staging,
completeness, conflict and five-second staging-lifetime rules. No collection
or membership acceptance occurs merely from receiving pages.

Issue the initial challenge after complete staging; bind it to that immutable
transfer. COMMIT data is recording ID u64, challenge u64, renewal sequence u32,
reserved u32. Revalidate all boot/session/profile-revision/state-epoch/mask
identities before acquiring membership and starting preparation. Q113's five
seconds of readiness begins at successful COMMIT acceptance, not BEGIN.

GET_LEASE_CHALLENGE data: recording ID u64, next renewal sequence u32, purpose
u8, frozen mask u8, reserved u16 (16 bytes). Initial purpose additionally
identifies the staged transfer through common transfer_id; renewal uses zero.
Response data: challenge u64, issuance tick u32, response deadline u32,
authorized-through deadline u32, renewal sequence u32 (24 bytes). Proof is
bound to boot/session/record/mask/purpose/sequence and the completed stage when
initial. Identical retries return identical deadlines, never fresh permission.

RENEW data uses COMMIT's 24-byte proof layout. Reply data is recording
ID u64, authorized-through tick u32, accepted sequence u32, endpoint state epoch
u64. Renewal sequence is nonzero, strictly increasing, never wraps within its
authorization. Expired/terminal authorization cannot be renewed. Unchanged
valid-to-valid renewal is not a new hardware readiness transition; validity or
health changes still advance state epoch under Q127. Do not advance ordinary
mutation high-water from this protected lane. Do not queue catch-up renewals.

START data: recording ID u64, expected prepared IMU state epoch u64, expected
IMU configuration revision u64. Keep its operation pending until its actual
first complete post-acceptance slot establishes Q105's boundary. STOP data:
recording ID u64, reason u8, fifteen zero bytes. Terminality prevents later
collection/renewal; stopping and register verification remain single-owner.
Preserve first/final boundaries independently of the latest ordinary reply
until membership cleanup/successor retirement. Known-empty, boundary pending
and boundary unknown are distinct validity states, not zero-value inference.

Use schema 5/v1 for a 128-byte acquisition snapshot opened with recording
ID u64 (zero means inspect current membership) and otherwise zero request data.
Reuse unchanged snapshot metadata, READ_PAGE and RELEASE_SNAPSHOT; one immutable
node snapshot at a time for up to five seconds. Snapshot layout:

| Offset | Bytes | Acquisition state |
|---:|---:|---|
| 0 | 8 | Schema u16, version u16, length u16, phase u8, frozen mask u8 |
| 8 | 8 | Owning recording ID |
| 16 | 8 | Owning control session |
| 24 | 4 | Node boot |
| 28 | 4 | State/result/validity flags |
| 32 | 4 | Authorization deadline |
| 36 | 4 | Current challenge response deadline |
| 40 | 4 | Preparation deadline |
| 44 | 4 | Last authorized renewal sequence |
| 48 | 4 | Captured node tick |
| 52 | 4 | Node clock epoch |
| 56 | 4 | Sensor clock epoch |
| 60 | 4 | Reason u16 and reserved u16 |
| 64 | 8 | Endpoint state epoch |
| 72 | 8 | IMU configuration revision |
| 80 | 8 | Reserved zero; no redundant runtime counter |
| 88 | 16 | First recorded boundary |
| 104 | 16 | Final recorded boundary |
| 120 | 8 | Reserved zero |

Boundary16: source sequence u32, node tick u32, stream epoch u8, validity u8,
six reserved zeros. Phases: no membership=0, preparing=1, prepared=2,
recording=3, stopping=4, terminal=5. State flags bits 0-10 respectively:
lease-valid, native-ready, excluded, first-valid, final-valid, known-empty,
hardware-stopped, preparation-accepted, fence-complete, challenge-valid,
membership-locked; others zero. Boundary validity bits: sequence=0, tick=1,
epoch=2, tick-estimated=3; others zero. Absence is a clear validity flag, not a
sentinel tick/sequence. Inter-node alignment quality alone does not clear native
readiness or set a clock fault. Unchanged live renewals and routine model
refreshes do not advance state epoch; eligibility/phase/health changes do.
The logger assigns persisted segment IDs from the verified source context;
the node does not invent a file-local stream identity.

RELEASE_MEMBERSHIP data is observed recording ID u64 plus sixteen zeros. Require
stopped acquisition, invalid/expired authorization and old-data fence completion;
clear membership explicitly without changing desired settings. For Q109, active
authority can differ from the observed abandoned membership's owning session.

### 3.2 Turnover fence and mode transition (Q139/Q140/Q144)

FENCE_OLD_DATA names the old recording ID and is legal only after acquisition
stops and its authorization is invalid. Cancel/drain old node sample queues and
CAN data transmission requests, wait until no old transmission remains, then
acknowledge; report discarded tails. This is after orderly tail-drain attempts,
not permission to discard the normal five-second tail silently. Master then
retires old CAN reception/retention and SPI/DMA objects; logger retires old
assemblies/ACK state. Preserve closed files and known incomplete-tail evidence.
Only a completed fence permits Q95 epoch reuse. Anchor reception is no substitute.

Bootstrap additions: identity capability bit 3 for measurement mode;
entry request/response 0x08/0x88, exit 0x09/0x89. Existing 0x01-0x07 and
0x81-0x87 remain unchanged. Negotiate full identities and limits at 4 MHz while
quiescent, confirm the bound context using valid 64-byte measurement frames,
then allow preparation authorization. Exit only after stopped/invalid producer
authorization and data retirement. Pending transition parsing must distinguish
actual CS-bounded length, magic and CRC; a partial or lost acknowledgement
cannot silently activate acquisition. Ambiguous entry fails unavailable, with
no lease grant. Retrying the same negotiation is idempotent and does not extend
deadlines. Active-recording recovery remains in its retained 64-byte context;
bootstrap is not an unbudgeted live fallback. Sections 2.2 and 3.2 define
confirmation/status payloads; driver boundary handling still requires qualification.

Q138 timing: master measurement RX/TX rearmed within 25 us of CS release;
logger keeps master CS inactive at least 25 us between measurement slots, with
the SPI mutex released and ADC work allowed in the gap. The gap is not part
of the 100 us ownership budget. Account for it wherever it cannot be hidden by
other admitted work. This is a target to qualify, not existing performance.
The current driver waits for all 84 DMA bytes before observing CS release;
it cannot already retire a 64-byte partial slot. Transition parsing requires
new length-aware boundary handling, not just changing the SPI clock.

Read-only recovery addition: MODE_INFO 0x0A/0x8A, available even when
64-byte mode is active. Its 16-byte request is fresh nonce u64 plus expected
master boot u64 (zero only for observational discovery). The first MISO data
can be a previously prepared measurement response; it is not the answer.
Retrieve the matching 84-byte response through existing request/fetch
correlation and verify the echoed nonce. Recognizing an 84-byte request does
not itself clear measurement context or grant authority.

The 64-byte negotiation/status payload is:

| Offset | Bytes | Field |
|---:|---:|---|
| 0 | 8 | Expected/current master boot |
| 8 | 8 | Expected/observed owning control session |
| 16 | 8 | Acquisition recording ID |
| 24 | 8 | Measurement context ID |
| 32 | 2 | Measurement version |
| 34 | 2 | Maximum logical length |
| 36 | 2 | Physical slot length |
| 38 | 1 | Action in requests, phase in responses |
| 39 | 1 | Reserved zero |
| 40 | 4 | Selected SPI clock, Hz |
| 44 | 4 | Minimum inactive CS interval, us |
| 48 | 8 | Caller control session; MODE_INFO response instead echoes nonce |
| 56 | 2 | Result reason |
| 58 | 2 | Validity/fence flags |
| 60 | 4 | Reserved zero |

Actions: stage=0, inspect=1, abort=2, close=3. Phases: legacy=0, entry-pending=1,
measurement=2, exit-pending=3, failed=4. Use the new mode-error namespace.
MODE_INFO returns observations, never permission to resume an old recording.
Legacy observational node inspection must likewise not create authorization.
A restarted logger establishes node stopped/expired state, binds fresh authority
and performs Q109 cleanup over the Q144 allowlisted route in section 9.2 before
replacing the old context. Typed request/poll/receipt formats remain unchanged;
the retained measurement owner's session is not an extra authorization
requirement for this restricted legacy route. Node boot/challenge/current-session
checks and stopped/expired predicates remain authoritative. Never forward an
acquisition grant through that route.

Total entry/exit handshake deadline: one second, retries do not extend
it. Full identities/limits are staged in legacy mode, confirmed in matching
measurement frames, and acknowledged before any PREPARE proof is sent. Retain
read-only discovery after an ambiguous switch; do not grant acquisition on a
timed blind format change. Exit requires stopped/invalid authorization and
data retirement. Old-format discovery must be response-length aware and
preserve application queues/identity. A driver waiting only for 84-byte DMA
completion is insufficient. Logger restart recovery is quiescent inspection
and cleanup, never automatic same-recording rejoining.

## 4. Accepted compact CAN reception object (Q142)

| Record offset | Bytes | Field |
|---:|---:|---|
| 0 | 2 | CAN identifier |
| 2 | 1 | Payload length |
| 3 | 1 | Reception flags |
| 4 | 4 | Master receive tick |
| 8 | 4 | Master global reception ordinal, low part |
| 12 | 64 | CAN payload; unused bytes zero |

Logical header: schema version u16 (=1), class u8, node u8, node boot u32,
reception-ordinal high part u32, count u16, flags u16: 16 bytes. Split
at ordinal high-part changes; ordinary wrap is not reset. Node address is
validated against CAN IDs. No invented CAN reception for locally generated
master observations: those require a declared separate object kind.

`16 + 13 * 76 + 4 = 1008` bytes: thirteen normal packets represent 65 samples.
With 40-byte physical fragments, this is 26 fragments; separately charging
one poll and one ACK gives 28 slots. Partial batches, evidence/control traffic,
startup/stop boundaries and retries need separate accounting. The 20 ms fill
limit is not a delivery deadline. Preserve master acceptance gates for anchors,
boot, epochs and duplicate-address exclusion before forwarding samples.

## 5. Accepted node timing snapshot (Q142)

Use the existing eight-byte CAN control envelope, body version 1,
body length 56, total payload 64; Q142 accepts the section 5.1 allocation.

| Body offset | Bytes | Field |
|---:|---:|---|
| 0 | 4 | Node boot |
| 4 | 1 | Endpoint |
| 5 | 1 | Stream epoch |
| 6 | 2 | Association/quality flags |
| 8 | 4 | Node evidence ordinal |
| 12 | 4 | Related source sequence |
| 16 | 4 | Sensor clock epoch |
| 20 | 4 | Node clock epoch |
| 24 | 4 | Raw sensor timestamp |
| 28 | 4 | Captured acceleration DRDY node tick |
| 32 | 4 | Acceleration capture ordinal |
| 36 | 4 | Referenced SYNC sequence |
| 40 | 4 | Node capture for that SYNC |
| 44 | 4 | Timing-model ID |
| 48 | 3 | Complete acceleration/gyro/timestamp FIFO tags |
| 51 | 1 | Field-presence mask |
| 52 | 4 | Selected FIFO-slot ordinal |

Slot pairing, timestamp association, DRDY association and model validity need
separate flags. Missing observations have validity clear and zero payload, not
fabricated zero measurements. Catalog metadata binds full UID, node/master boot,
recording/control/context identity and each physical clock domain.

Model and boundary/loss messages require their own bodies. Model evidence must
identify anchor source sequence/tick, rational step, clock/source identities,
validity span/duration, input evidence ordinals and uncertainty validity. Match
the existing anchor's uint16 denominator bound. A fit residual alone is not a
guaranteed uncertainty bound. Unknown uncertainty is not zero. Define ordering
when a model and its anchor/data use different CAN identifiers; receipt order
alone is not a barrier. Do not declare a model current without its complete
associated evidence and boundary.

Q130 requires source-sequence applicability, retention of all queued references
and separate timing boundaries where needed; ordinary model updates do not
restart source sequences or clocks. Q131 bounds native-association recovery to
100 ms and three attempts per rolling second. Q132 treats interpretation
metadata exhaustion as endpoint exclusion, while ordinary periodic evidence
loss degrades alignment without excluding trustworthy native samples.

Model body (56 bytes, alongside a matching STREAM_ANCHOR):

| Offset | Bytes | Model field |
|---:|---:|---|
| 0 | 4 | Node boot |
| 4 | 1 | Endpoint |
| 5 | 1 | Stream epoch |
| 6 | 2 | Validity/association flags |
| 8 | 4 | Model ID |
| 12 | 4 | Node clock epoch |
| 16 | 4 | Sensor clock epoch |
| 20 | 4 | First applicable source sequence / anchor sequence |
| 24 | 4 | Anchor modeled node tick |
| 28 | 4 | Tick-step numerator |
| 32 | 2 | Tick-step denominator |
| 34 | 1 | Model kind |
| 35 | 1 | Reserved zero |
| 36 | 4 | Maximum applicable sample span |
| 40 | 4 | Conservative reconstruction uncertainty, us; valid only by flag |
| 44 | 4 | Maximum applicable acquisition duration, us |
| 48 | 4 | First input evidence ordinal |
| 52 | 4 | Last input evidence ordinal |

Q136 accepts refreshing the local model at 10 Hz, with limits of 500 samples and
150,000 us from its anchor, whichever is reached first. These limits concern
the sample's acquisition position, not its later delivery time. Unknown finite
uncertainty does not by itself invalidate established native association.
Recipe, rounding, association/rejection rules and validity bits need final
review; a measured residual alone does not establish a conservative bound.

Q133 accepts keeping Q70's ordinary exchange lane
unchanged and add one bounded protected authorization/STOP exchange slot per
node. Renewal uses its authorization sequence rather than ordinary mutation
high-water. STOP can terminate pending preparation under one hardware owner,
without overlapping register writes or inferring cancellation from a timeout.
Define exact timing and result retention with the acquisition command layouts.

### 5.1 Accepted evidence registry and boundary body (Q142)

CAN message types: TIMING_SNAPSHOT=0x23, TIMING_MODEL=0x24,
SOURCE_BOUNDARY_OR_LOSS=0x25, each body version 1 on 0x090+node with the
existing envelope. Existing SYNC/anchor allocations remain unchanged.

Snapshot flags (bits 0-8): validated slot pair, sensor timestamp association,
DRDY association, SYNC reference, model reference, timing degraded, evidence
gap before, capture loss, clock-domain change. Other bits zero. Presence byte
bits 0-7 respectively identify acceleration tag, gyro tag, timestamp tag, raw
sensor timestamp, DRDY capture, node SYNC capture, FIFO-slot ordinal, source
sequence. Never derive a valid association from mere field presence.

Model flags: native association=bit0, uncertainty known=1, input range known=2,
timing boundary before=3, recovered=4; others zero. Model kind 1 is rational
acceleration-output-ready estimation. Evaluate
`tick(s) = (anchor_tick + floor((s-anchor_sequence)*numerator/denominator)) mod 2^32`
with wide integer intermediates. Include rounding in any finite bound. Publish
matching canonical model/anchor origins and retain referenced revisions; do not
independently rebase repeated anchors and lose rational phase. Conflicting
definitions at one applicability boundary are errors, not arrival-order choice.

Boundary/loss body, 56 bytes:

| Offset | Bytes | Field |
|---:|---:|---|
| 0 | 4 | Node boot |
| 4 | 1 | Endpoint |
| 5 | 1 | Stream epoch to which this event applies |
| 6 | 1 | Event kind |
| 7 | 1 | Loss/recovery stage |
| 8 | 4 | Node evidence ordinal |
| 12 | 4 | Sensor clock epoch |
| 16 | 4 | Node clock epoch |
| 20 | 4 | Related source sequence |
| 24 | 4 | First affected sequence/ordinal |
| 28 | 4 | Last affected sequence/ordinal |
| 32 | 4 | Known source-loss delta |
| 36 | 4 | Known capture-loss delta |
| 40 | 4 | Known evidence-loss delta |
| 44 | 2 | Reason |
| 46 | 2 | Validity flags |
| 48 | 4 | Elapsed native-recovery time, us |
| 52 | 4 | Boundary node tick |

Kinds: end-source=1, begin-source=2, loss=3, recovery-start=4,
recovery-complete=5, recovery-failed=6, clock-reset=7, stop-boundary=8.
Validity bits 0-10: related sequence, affected range, source count, evidence
count, capture count, clock epochs, boundary tick, actual clock reset,
first boundary, final boundary, known-empty. Remaining bits zero. Zero counts
are valid only when their validity bit is set. Split wider known deltas across
events rather than truncate them.

Stages: FIFO=1, decoder=2, node acquisition queue=3, CAN TX queue=4,
master ISR queue=5, master retention=6, SPI assembly=7, logger sample queue=8,
logger evidence queue=9, storage=10, capture queue=11, essential metadata=12,
unresolved CAN transport=13. A stage records observed evidence, never a guessed
cause. End/begin events explicitly distinguish old/new epochs at recovery.
Q134 coalesces repeated known queue drops, not essential epoch changes.

New common-control reasons 27-36: native-not-ready, recording-mismatch,
lease-expired, authorization-terminal, essential-metadata-unavailable,
recovery-budget-exceeded, fence-incomplete, model-conflict, clock-untrusted,
measurement-context-mismatch. Preserve all existing reasons 0-26, especially
Q70 reason 26's uncertainty meaning. Add field codes 20-26 for recording ID,
phase, state epoch, native clock, timing model, data fence, stream epoch;
preserve 0-19. Unknown values remain errors/unknown diagnostics, never success.

## 6. Persisted schemas: 28-byte sample and 224-byte companion

Accepted sample: prefix 0-11, segment u32 at 12, acceleration XYZ int16 at
16/18/20, gyro XYZ int16 at 22/24/26; total 28. Segment IDs are nonzero and
never reused within that recording's sample stream. Preserve reserved-zero prefix,
estimated-tick flags and per-sample segment identity. Do not modify BMI schemas.

Q135 accepted the initial 192-byte companion mapping with non-overlapping declared
channels for snapshot, model, synchronization, host bridge, boundary and loss
kinds; Q143 accepts the 224-byte completion in section 9.1. Include sample stream/segment/sequence,
clock epochs, raw sensor/DRDY/SYNC ticks and tags, model parameters/validity,
logger bounds and bridge token, source/evidence/capture loss validity/counts,
and original transport identity/order. Represent 64-bit quantities as explicit
low/high uint32 channels under the existing BDQ channel types; never repurpose
reserved fields. Q135 accepts the following offsets; event values, validity
allocations and catalog schema names still require the final wire review.

| Offset | Bytes | Companion field |
|---:|---:|---|
| 0 | 12 | Existing BDQ prefix: own event sequence, logger creation tick, flags, reserved zero |
| 12 | 4 | Kind u8, endpoint u8, stream epoch u8, reserved u8 |
| 16 | 4 | Field-group validity mask |
| 20 | 4 | Related sample source-segment ID |
| 24 | 4 | Related sample sequence |
| 28 | 4 | Node boot |
| 32 | 4 | Sensor clock epoch |
| 36 | 4 | Node clock epoch |
| 40 | 4 | Master clock epoch |
| 44 | 4 | Model ID |
| 48 | 4 | Node evidence ordinal |
| 52 | 4 | Raw sensor timestamp |
| 56 | 4 | Acceleration DRDY node tick |
| 60 | 4 | Acceleration capture ordinal |
| 64 | 4 | SYNC sequence |
| 68 | 4 | Node SYNC capture |
| 72 | 4 | Master SYNC capture |
| 76 | 4 | Master reception tick |
| 80 | 4 | Master reception ordinal low32 |
| 84 | 4 | Three raw FIFO tags and association flags |
| 88 | 4 | Model anchor source sequence |
| 92 | 4 | Model anchor node tick |
| 96 | 4 | Rational step numerator |
| 100 | 4 | Rational step denominator, uint16 CAN value widened |
| 104 | 4 | Conservative reconstruction uncertainty, us |
| 108 | 4 | Maximum model sample span |
| 112 | 4 | Maximum model duration, us |
| 116 | 4 | Selected FIFO-slot ordinal |
| 120 | 8 | Logger lower bound, explicit uint32 low/high channels |
| 128 | 8 | Logger upper bound, explicit uint32 low/high channels |
| 136 | 4 | Master bridge-observation tick |
| 140 | 4 | Bridge method u16, boundary/loss reason u16 |
| 144 | 4 | Bridge exchange token |
| 148 | 4 | Per-event source-loss delta |
| 152 | 4 | Per-event evidence-loss delta |
| 156 | 4 | Per-event capture-loss delta |
| 160 | 4 | First affected sequence/evidence ordinal |
| 164 | 4 | Last affected sequence/evidence ordinal |
| 168 | 4 | Loss stage and count-validity flags |
| 172 | 4 | First model-input evidence ordinal |
| 176 | 4 | Last model-input evidence ordinal |
| 180 | 4 | Clock/bound validity flags |
| 184 | 4 | Original message type/version/length, reserved u8 |
| 188 | 4 | Master reception ordinal high32 |

Kinds are snapshot=1, model=2, node SYNC=3, master SYNC=4, host bridge=5,
boundary=6 and loss=7. Every channel is declared at its exact offset; kind and
validity identify meaningful fields. Invalid payload is zero, not an observed
zero value. The related sample stream is a static catalog reference for the
initial IMU-only node. Raw reception order composes fields 188/80, not arrival
order of companion records. Per-event loss deltas must fit without truncation:
split known deltas into multiple events if needed; final totals use wider
counters. A missing count has validity clear. Metadata must define methods,
validity bits, clock domains, estimation and tag decoding before implementation.

**Accepted prefix clock (Q129):** Companion prefix uses low32 logger monotonic
microseconds at record creation, explicitly a receipt/creation observation,
while payload fields carry separately identified raw source clocks. Never fit
sample time from this prefix. Evidence sequence is logger-generated per-node
event order; retain node evidence ordinal separately to detect upstream loss.

Register all descriptors before data. Stream budget is primary + configured
native streams + node companions: four IMUs plus four companions plus primary
is nine. Current writer limit is sixteen; preserving the broader 32-logical-
sensor target requires explicit capacity planning, not silently consuming its
remaining stream slots. Section 6.1 defines the derived implementation capacity
and explicit admission obligation; 16 is not a new product limit.

### 6.1 Validity, catalog binding and dependency ordering

Companion validity-mask bits 0-22 respectively identify source context, node
clock epoch, sensor clock epoch, master clock epoch, related source sequence,
raw sensor tick, DRDY capture, node SYNC, master SYNC, CAN reception tick,
full reception ordinal, raw tags, model parameters, model uncertainty,
logger interval, host bridge, source-loss count, evidence-loss count,
capture-loss count, affected range, model-input range, FIFO-slot ordinal,
reason/method. Bits 23-31 are zero. Raw masks in the appended fields preserve
the original wire presence/association flags independently. A bit clear means
unknown/not present; zero numeric payload never manufactures an observation.

Catalog bindings include provider UID/address/boot, requested/effective profile
and raw verification phase, desired generation/applied revision/session,
calibration and mounting transforms, actual payload schemas, source-clock IDs,
nominal rates/moduli and known/measured/historical masks. Represent new 64-bit
identities as decimal strings in JSON metadata. Do not advertise nominal rates,
derived model estimates or unqualified filter delays as physical measurements.
Sample native clock is the declared node counter; companion prefix is low32
logger monotonic microseconds at creation. Both nominal moduli are 2^32 with
1 MHz nominal frequency, but different clock IDs. Sensor timestamps retain
their separate nominal 40 kHz clock. Do not share clock_id across oscillators
or counter domains. Wider bounds/orders use explicit low/high uint32 channels.

Per-node companion events duplicate shared master SYNC/host-bridge observations
into each participating node's companion, identified by the same original
master epoch/SYNC sequence or bridge token. Analysis must recognize this shared
evidence rather than count duplicates as independent measurements. No extra
global evidence stream is needed. Canonically identical anchor repeats can be
coalesced into their persisted model evidence; record changed origins/models
and all essential boundaries before dependent samples.

Reference-count essential definitions across queued, selected, in-flight,
decode-pending and SD-pending samples. Acquisition-time validity does not permit
evicting definitions still needed by delayed data. Protect held old heads even
when newer data is dropped during an SD stall. Append the complete essential
evidence chunk before a dependent sample chunk (Q141); do not require an fsync
per event. Valid-prefix recovery must stop before an incomplete predecessor.
Periodic snapshot loss is different and retains Q132's degraded-quality policy.

New LSM parsing uses segment identity plus unwrapped source sequence and model
applicability, not a dictionary keyed only by the low32 sequence. Ordinary
tick/capture/receive-ordinal wraps are not resets; only declared clock resets
advance clock epochs. Unknown wrap/reset association is never guessed. IDs
(context/object/model/segment/record/renewal) cannot silently wrap in scope.
Preserve old BMI parsing; implement explicit new-payload handling and retain
unknown evidence fields numerically when rewriting.

Current writer/catalog code has a 16-stream implementation limit. Dimension
tables for the derived upper bound of 37 streams (primary + at most 32 native
logical-sensor streams + four node companions); this preserves the established
32-logical-sensor target without silently spending its slots on evidence.
Actual driver/rate/RAM admission still applies, and no maximum-rate combination
is thereby promised. Four IMUs with four companions and primary use nine slots.

## 7. Master-to-logger clock bridge

Relative node alignment via shared hardware SYNC does not establish absolute
logger monotonic time. Q128 accepts a fresh software exchange token at 10 Hz:
logger records
L0 before request; master samples M only after validating that request; logger
records L1 after receiving the matching validated response. Retain L0/L1/M,
token, master clock epoch and method. Include capture/quantization uncertainty.
Preloaded responses or queued receive ticks cannot inherit this bracket.

The interval may be much broader than 10 us. Keep relative inter-node target
separate from this bridge and sensor/filter delay. Compose BDQ bounded mapping
observations only when all required mappings have defensible finite bounds;
otherwise retain raw evidence and unknown alignment. Section 2.2 defines the
request/response encoding and retry bracket.

## 8. Capacity calculation, not admission or qualification

Nominal four-node ingress: 13,332 samples/s; 159,984 axis bytes/s; 2,666.4 normal
CAN packets/s. Sample storage is 373,296 B/s before evidence/chunks; four
4096-entry sample queues at exactly 28 bytes cost 458,752 bytes. Actual heap,
alignment, local queues and companion coverage must be allocated before start.

The candidate 1008-byte reception object gives
`2666.4 / 13 * 28 * 64 = 367552.98` SPI wire B/s, or 36.7553% at 8 MHz.
This assumes full normal batches; 20 ms partials and boundaries can cost more.
Two ADS workers at their 2000-conversion/s ceilings require 32% wire time at
1 MHz, before per-transaction software costs. Actual admitted worker rates
must be used, not merely the logger row cadence.

Planning slot allowances (not qualified upper costs):

| Traffic | Slots/s | Wire occupancy at 8 MHz |
|---|---:|---:|
| Normal samples in full 13-packet batches | 5743.0154 | 36.7553% |
| 160 authorization request/result objects, four slots each | 640 | 4.096% |
| 40 selected snapshots, five slots each | 200 | 1.28% |
| 50 SYNC observations, conservatively five slots each | 250 | 1.6% |
| 40 local models, five slots each | 200 | 1.28% |
| 40 matching anchors, five slots each | 200 | 1.28% |
| Four node statuses, five slots each | 20 | 0.128% |
| Ten bridge request/response pairs | 20 | 0.128% |
| Empty sample polling ceiling | 200 | 1.28% |
| Optional diagnostics: four requests plus results, four slots each | 32 | 0.2048% |

Mandatory rows before empty polling/diagnostics give 46.5473% SPI wire, or
78.5473% with the conservative 32% ADC ceiling. Charging both optional ceilings
gives 80.0321% before software and non-overlapped guards. Charging every 25 us
guard separately adds 18.7625 percentage points and fails Q137 before software.
Thus useful guard overlap and sufficiently low qualified software costs are
essential for this maximum-ADC example; it is not an admitted configuration.
Small partials, real fetch/ACK/IDLE latency, boundary bursts, retries and storage
CPU contention must be charged from the implemented schedule, not assumed away.
The 1.25-times catch-up test must be evaluated separately with mandatory traffic
still active, not inferred from nominal wire headroom.

At 224 bytes, conservatively duplicating global observations into four
companions produces 200 normal evidence events/s = 44,800 B/s. Samples plus
normal evidence are 418,096 B/s before chunk headers/local streams. Counting
80 coalesced report/anchor events plus 96 recovery events gives 457,520 B/s
as a conservative remote persistence allowance. Identical anchors need not
be redundantly persisted if their canonical model evidence is already present.
Four 4096-entry sample queues plus four 128-entry evidence queues cost
573,440 bytes at exact record sizes, before metadata, refs, alignment, primary/
local queues and workspace. This is a planning allocation, not detected free
PSRAM or a memory qualification result.

At the accepted 100 us maximum mutex hold, sample slots alone can charge
57.4302% rather than 36.7553%; adding ADC ceiling and these auxiliary slots
exceeds 100%. Therefore a per-slot limit does not establish sustainable
admission. Measure/derive qualified scheduling costs, account for all traffic
and reject unsupported combinations rather than silently reduce desired rates.

Q137 admission limits: at most 85% steady shared-SPI scheduling occupancy,
including qualified software/CS/arbitration costs and non-overlapped rearm gaps;
leave 15% for bounded bursts/recovery. Additionally demonstrate at least 1.25
times admitted sample ingress drain capacity with mandatory ADC/control/time
traffic active. Apply the stricter test. Use actual selected worker traffic
and worst-case scheduling costs, not nominal wire rate or average timing.
These are accepted requirements to qualify, not measured performance. Queue coverage
also needs a burst/service-envelope proof, not only an average-rate comparison.

Conservative CAN sample load is 52.3281% at 1M/4M. Charge every auxiliary
frame as 196.25 us: 160 authorization +40 snapshot +50 SYNC +40 model +40
anchor +4 status = 334/s, giving 58.88285%. Eight optional diagnostic request/
result frames give 59.03985%. Eighty coalesced report/anchor frames plus 96
recovery frames give 62.49385%, before exceptional STOP/start/fence bursts,
controller errors and retransmissions. Those finite bursts and critical service
latencies must be proved against Q146; the 70% target is not an average-only
permission to overflow essential queues. Fault safety permits explicit sample
loss/exclusion under the selected rules; it does not promise lossless operation
under every simultaneous maximum fault and storage-stall scenario.

Node FIFO: 9,999 nominal words/s; conservative capacity 511 words. A 96-word
burst at 4 MHz costs 1.346 ms wire. Nominal grouped-arrival bound gives roughly
200 words before service at the 10 ms deadline, at most 215 before completing
that burst, and up to 119 afterward: repeated bursts are required. Include
ODR tolerance/status/decoding/DMA/interrupt costs before qualification. Source:
[exact-part timing research](CAN-FD_IMU_Acquisition_Timing_Research.md).

## 9. Accepted consistency corrections (Q143-Q146)

### 9.1 Lossless companion extension (Q143)

Q135 accepted 192 bytes, but review found no dedicated storage for all accepted
boundary/recovery fields or the complete raw flag masks. Do not silently reuse
model/tag/slot fields. Q143 extends to 224 bytes, retaining bytes 0-191:

| Offset | Bytes | Added field |
|---:|---:|---|
| 192 | 4 | Boundary node tick |
| 196 | 4 | Native recovery elapsed time, us |
| 200 | 1 | Original boundary event kind |
| 201 | 1 | Original snapshot presence mask |
| 202 | 1 | Original model kind |
| 203 | 1 | Reserved zero |
| 204 | 2 | Complete original snapshot flags |
| 206 | 2 | Complete original model flags |
| 208 | 2 | Complete original boundary validity flags |
| 210 | 14 | Reserved zero |

The lower snapshot association byte at 87 remains a checked low-byte copy;
offset 204 preserves all flags including bit 8. Raw source kind/validity fields
make known-empty, first/final and actual-reset evidence explicit. No overlapping
BDQ channels or invented values. Payload schema IDs are bodaqs.can_imu6.v1 and
bodaqs.can_timing_evidence.v1, declared in acquisition.payload_schema. Preserve
the existing fixed_mixed_v2 record_format and common BDQ envelope; these IDs
describe new payloads, not reinterpretations of existing BMI records.

### 9.2 Restarted-logger administrative route (Q144)

MODE_INFO alone cannot bind/fence/release nodes while the old measurement
context remains bound to its former owner. Q144 establishes a strictly allowlisted
legacy administrative route: observational challenge/state/snapshot/operation
queries, then fresh BIND_SESSION, FENCE_OLD_DATA and RELEASE_MEMBERSHIP after
verified stopped acquisition and expired/invalid old authorization. Enforce all
existing expected master/node boot, challenge/session and observed-record
checks. No APPLY, PREPARE, START or RENEW through this active-mode cleanup route.
It cannot auto-resume or implicitly clear a live lease. Retire the old context
only after the explicit fences; a new context then follows ordinary negotiation.

### 9.3 Explicit lane classes (Q145)

To keep ordinary replies from blocking authorization or poisoning its last-ACK
cache, use AUTHORIZATION_FRAGMENT=12 and MASTER_EVIDENCE_FRAGMENT=13, adding
to Q142's registry without changing byte offsets. Object classes: samples=1,
node evidence=2, ordinary control=3, authorization/urgent STOP=4, master-local
evidence=5, clock bridge=6. Master-wide node address is 0xFF; normal node addresses
are 0-3. Class/node/direction identities, assembly and ACK caches are independent.
One sample/evidence batch per node remains; each control lane has separate
bounded state. Master-local observations are never fabricated CAN receptions.

### 9.4 Bounded fault/control emission (Q146)

Cap each native-recovery attempt at eight unsolicited essential CAN frames,
including its boundary/model/anchor evidence. With Q131 this is at most 24
clustered frames/node and 96/s across four nodes; reserve capacity before
attempting recovery, otherwise exclude safely under Q132. Coalesced known-loss
cycles remain at most 10 Hz/node, at most one report plus one anchor per cycle.

Charge retries to the same bounded service budget rather than add unbounded
catch-up traffic. Authorization request budget: 20 requests/s/node,
burst two, plus at most one response per request. Urgent STOP preempts renewal
and is limited to three identical attempts inside 300 ms; unresolved outcome
remains uncertain, renewal ceases, and Q114 tail deadline still applies.
Budget at most four ordinary diagnostic requests/s globally, burst four,
including retries; discovery remains idle-only. Optional diagnostics may be
busy/cached with explicit age, never block renewal/STOP. Empty sample polls are
bounded to 50/s/node, burst one, with acquisition service deadlines preserved.
All actual traffic and non-overlapped costs must pass Q137, not merely these
rate ceilings. These limits do not assert maximum-rate admission.

## 10. Final consistency checkpoint and validation debt

Q71-Q147 settle the design decisions and reviewed corrections. The user
confirmed shared understanding on 4 November 2026; qualification evidence is
still outstanding. Implementation is not
authorized by this interview. Final review covers lost replies, conflicting
fragments, partial pairs, wrap/reset ambiguity, retained model references,
metadata-before-data ordering, restart cleanup and stale-data fencing.

Required implementation validation: independent codec vectors and malformed
inputs; authorization/terminal replay and delayed challenges; pending PREPARE
with renewal/STOP; model applicability and essential-evidence ordering;
per-node fairness, backpressure and partial batches; known/unknown losses;
capture/tick/source-sequence rollover and actual reset; immutable snapshots;
storage stalls/fatal errors and quiescent recovery; legacy control compatibility;
full node/master/A8 builds. Do not infer a physical result from host tests.

Acquisition support/readiness remains unavailable until its required driver,
protocol, storage and timing prerequisites are implemented and verified. In
particular, FIFO-slot/DRDY association must be demonstrated rather than assumed;
ambiguous native pairing/timing follows the selected failure rules. Unverified
10 us alignment alone is not an exclusion gate. If physical source association
or timing targets cannot be qualified, revisit the design explicitly.

Operator-reported happy-path evidence is not timing/electrical qualification.
Disconnect/reconnect, CCS halt/resume and node/master reset fault tests remain
deferred until a practical harness exists. No physical SPI/FIFO/SYNC timing,
signal amplitude/phase, four-node load, stack-watermark or lease-budget pass is
claimed. Existing known FRONT_FAULT bench telemetry remains explained by the
reported bypass wiring; this work does not suppress or re-diagnose it.
