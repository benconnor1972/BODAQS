# BODAQS node configuration and effective-state wire contract

Status: decisions through Q70 confirmed; pre-implementation interview closed
on 4 November 2026.
No implementation or physical validation is claimed.
Created: 3 November 2026. Last updated: 4 November 2026.

The authoritative behavior is section 13 of
[the network protocol](CAN-FD_Network_Protocol.md). This document specifies the
control extension on that CAN boundary and on
[the logger-to-master SPI boundary](CAN-FD_Master_SPI_Protocol.md), without
changing bootstrap message layouts. Acquisition/sample transport is a later
stage. The implementation gates and any remaining questions are explicit in
section 11.

## 1. Common record layout

Derived from Q44's agreed 52-byte record and 24-byte descriptor pages. All
multi-byte fields are little-endian. Offsets are relative to the common record,
not the transport envelope. Exact offsets agreed in Q54:

| Offset | Bytes | Field |
|---:|---:|---|
| 0 | 1 | `opcode` |
| 1 | 1 | `endpoint` (0-5; `0xFF` for node-wide operations) |
| 2 | 1 | `page_index` (zero-based; zero for non-page records) |
| 3 | 1 | `data_length` (0-24) |
| 4 | 4 | `operation` (mutation sequence or independent read request ID) |
| 8 | 4 | `node_boot_id` |
| 12 | 8 | `control_session_id` (zero for observational reads) |
| 20 | 8 | `transfer_id` (staging or snapshot identity) |
| 28 | 24 | `data` (unused bytes zero) |

CAN uses the existing 8-byte control envelope, `CONFIG_REQUEST=0x10` or
`CONFIG_RESULT=0x11`, body version 1 and body length 52. The resulting 60 bytes
are zero-padded to 64 bytes (DLC 15). The existing 16-bit envelope transaction
correlates an exchange; it does not replace the end-to-end operation identity.

SPI puts a 12-byte wrapper before this record in its existing 64-byte payload.
Wrapper offsets agreed in Q54:

| Offset | Bytes | Field |
|---:|---:|---|
| 0 | 8 | `expected_master_boot_id` (responses report current master boot) |
| 8 | 1 | `node_address` (0-3) |
| 9 | 1 | `record_version` (1) |
| 10 | 1 | reserved, zero |
| 11 | 1 | reserved, zero |
| 12 | 52 | common record |

The SPI slot sequence remains transport correlation only. Response body version
and reserved fields must validate before a record is interpreted. Master boot
and node boot are different identities and have different scopes.

## 2. Agreed allocations (Q54)

Keep both transport major versions at 1. The new record version is 1; future
unsupported versions are not silently decoded as version 1. Advertise the
extension through master identity capability bit 2, preserving bits 0-1.

| SPI type | Name | Purpose |
|---:|---|---|
| `0x05` | `ControlInfoRequest` | obtain master boot identity and control limits |
| `0x06` | `ControlSubmitRequest` | submit a wrapped common request record |
| `0x07` | `ControlPollRequest` | poll the matching submitted exchange |
| `0x85` | `ControlInfoResponse` | master control information |
| `0x86` | `ControlReceiptResponse` | master receipt, not node success |
| `0x87` | `ControlPollResponse` | pending state or completed node result |

Existing `FetchResponse` only clocks a prepared SPI response. It does not poll
an eventual CAN operation result. Info/receipt/poll layouts are in section 7.

Agreed control opcodes, inside existing CAN configuration message types:

| Opcode | Request | Role |
|---:|---|---|
| `0x01` | `GET_CHALLENGE` | observational node challenge request |
| `0x02` | `BIND_SESSION` | establish authority, no acquisition/configuration |
| `0x03` | `RELEASE_SESSION` | release idle authority |
| `0x04` | `GET_NODE_STATE` | inspect authority, lock and pending-operation state |
| `0x05` | `OPEN_CAPABILITIES` | capture immutable endpoint capability descriptor |
| `0x06` | `OPEN_EFFECTIVE` | capture immutable endpoint effective descriptor |
| `0x07` | `READ_PAGE` | read one captured descriptor page |
| `0x08` | `RELEASE_SNAPSHOT` | release captured descriptor |
| `0x10` | `BEGIN_APPLY` | fix metadata and allocate bounded staging |
| `0x11` | `WRITE_PAGE` | stage one request page |
| `0x12` | `COMMIT_APPLY` | validate complete request then apply/verify |
| `0x13` | `ABORT_STAGING` | discard staging only; not rollback/cancel of hardware apply |
| `0x14` | `GET_OPERATION` | inspect pending/cached mutation outcome |
| `0x20-0x2F` | reserved | later recording/start/stop/lease operations |
| `0x7F` | `CONTROL_ERROR` (result only) | correlated command rejection, including failed opaque reads |

Normal results echo the request opcode; direction is determined by transport
message type. Q64 adds result-only `CONTROL_ERROR=0x7F` for correlated command
errors, including failed opaque page reads. Acquisition opcodes remain
unavailable in this stage. Unknown well-formed opcodes receive structured
unsupported-operation rejection. Response data encoding is in section 7.

## 3. Agreed configuration and profile identifiers (Q55)

| Identifier | Value | Meaning |
|---|---:|---|
| IMU configuration schema | 1, version 1 | complete enabled/disabled request |
| Capability descriptor schema | 2, version 1 | explicit implementation support and profile catalog |
| Effective descriptor schema | 3, version 1 | current knowledge, historical evidence and acquisition fields |
| Initial IMU profile | 1, version 1 | matched nominal 3.33 kHz, +/-32 g, +/-2000 degrees/s; Q46 filter/mode policy |

Schema and profile IDs/versions are unsigned 16-bit values. Zero profile
ID/version is reserved for disabled mode. Initial profile name:
`IMU6_3333_32G_2000DPS_V1`. The symbolic name is descriptive; numerical
ID/version is authoritative. Exact register policy follows the primary sources
in [the research note](CAN-FD_IMU_Configuration_Research.md), with Q45's running
engines for enabled-but-stopped operation. Do not reuse a BMI270 profile ID or
interpret this profile through the BMI270 serializer.

## 4. Agreed request layouts (Q55)

`BEGIN_APPLY` uses all 24 data bytes. `COMMIT_APPLY` repeats the same metadata;
the session/operation/transfer/endpoint header must also match.

| Data offset | Bytes | Field |
|---:|---:|---|
| 0 | 2 | schema ID |
| 2 | 2 | schema version |
| 4 | 2 | total descriptor length (1-512, exact schema length required) |
| 6 | 2 | reserved, zero |
| 8 | 8 | desired generation |
| 16 | 8 | expected endpoint applied revision |

Complete IMU request descriptor, fixed 44 bytes:

| Descriptor offset | Bytes | Field |
|---:|---:|---|
| 0 | 2 | schema ID (1) |
| 2 | 2 | schema version (1) |
| 4 | 1 | mode: disabled=0, enabled=1 |
| 5 | 1 | permitted alternative count (0-8) |
| 6 | 2 | reserved, zero |
| 8 | 2 | preferred profile ID |
| 10 | 2 | preferred profile version |
| 12 | 32 | eight alternative ID/version pairs, four bytes each |

Unused pairs are zero. Enabled mode requires a nonzero preferred ID/version;
disabled mode requires all profile/count fields zero. The descriptor schema
must match its transfer metadata. An enabled request occupies pages of 24 and
20 meaningful bytes; the final four bytes of the second page data area are zero.

## 5. Agreed effective representation, execution and logger mapping (Q56-Q58)

The effective descriptor is fixed at 192 bytes for version 1. It distinguishes
current verified, historical, unknown and not-applicable field groups using
explicit applicability, knowledge and historical-provenance masks. It contains
state/health, desired generation, endpoint applied revision, profile, nominal
rates, ranges/scales, filter descriptions, engine/acquisition state and clock
information. Unknown and not-applicable payload fields are zero but have
different mask states. Historical values do not establish current agreement or
readiness. Exact offsets/mask bits are in section 8.

Interrupt handlers do bounded transport work and hand records to the main loop.
Configuration processing, including reset/readback, runs outside interrupts.
Use at most one mutation context and one immutable snapshot per node, fixed
capacity buffers, no unbounded command queue, and busy responses at capacity.
Polling and pending-state inspection remain serviceable during hardware apply.

The logger adds endpoint-scoped control/effective observations; the existing
provider-level 32-bit revision is not the authoritative endpoint revision.
Preserve desired/discovered/effective/health separation and current/historical
provenance. New 64-bit JSON identities/revisions are documented strings.
Structured failures map to stable diagnostics. Configuration-only success is
separate from acquisition readiness and does not block healthy local logging.

## 6. Agreed identity, operation lifecycle and baseline (Q59-Q63)

Master boot and logger session IDs are fresh nonzero 64-bit values generated
using platform randomness; node boot ID retains its existing 32-bit format.
Nonzero 64-bit transfer/snapshot IDs are never reused within their boot/session
scope. Binding challenges expire after five seconds. Read-request sequences
are independent of mutation sequences. Desired generations are endpoint-scoped
within the logger control session; a new session may restart them without NVS
persistence. Persisted user settings remain the desired source of truth.

Admitting `BEGIN_APPLY` reserves its mutation sequence. Abort, staging expiry
and rejection are terminal; another attempt needs a new sequence. Malformed or
busy requests not admitted do not consume one. New operations cannot replace
a pending operation. Identical retries retrieve existing state without extending
deadlines. Outcome queries distinguish query success/failure, whether the
original outcome is known, and that outcome. Superseded or unknown-operation
evidence does not establish that the earlier operation failed to apply.

A new operation with identical settings requires fresh hardware readback before
no-op acceptance. A match avoids reset and revision advance. A mismatch uses
the normal validated apply/verify path within its deadline; failure leaves
current effective state unknown and the endpoint excluded. A cached retry
returns its original result without repeating hardware work.

Initial profile baseline: `CTRL1_XL=94h`, `CTRL2_G=9Ch`, BDU/address increment
enabled, four-wire SPI, high-performance modes, agreed filter bypasses,
auxiliary interfaces/embedded functions disabled. FIFO/batching, acquisition
interrupt routes and sensor timestamp are disabled. Explicit disable sets both
ODR fields to zero. Compare documented owned fields with masks and preserve
reserved bits/reset defaults. See the primary-source register table in
[the research note](CAN-FD_IMU_Configuration_Research.md), applying Q45's running
engines rather than the power-down alternative for enabled-but-stopped mode.
Settling, FIFO servicing and timestamp acquisition remain later-stage work.

## 7. Agreed control information and replies (Q64)

`ControlInfoRequest` has no payload. Its 32-byte response is:

| Offset | Bytes | Field |
|---:|---:|---|
| 0 | 8 | current master boot ID |
| 8 | 4 | control feature bits: typed control=bit 0, observational reads=bit 1 |
| 12 | 2 | minimum common-record version (1) |
| 14 | 2 | maximum common-record version (1) |
| 16 | 2 | maximum descriptor bytes (512) |
| 18 | 1 | descriptor data bytes per page (24) |
| 19 | 1 | maximum profiles per endpoint (16) |
| 20 | 1 | address count (4) |
| 21 | 1 | maximum mutations per node (1) |
| 22 | 2 | reserved, zero |
| 24 | 2 | control-info schema version (1) |
| 26 | 6 | reserved, zero |

Submit and poll requests use the full 64-byte wrapper/common-record payload.
Polling echoes the submitted header (including opcode/page) but has data length
zero and zero data. There is at most one outstanding CAN exchange per address.
A new exchange replaces the completed exchange cache, not a pending one.

Q70: the master owns CAN application-request retry, up to three
one-second attempts with identical common record and CAN envelope transaction.
Deduplicated SPI resubmission does not start an extra attempt or reset timing.
On exhaustion, finish the exchange as transport-outcome-uncertain, release its
pending slot and retain that terminal exchange result until replaced. Later
`GET_OPERATION`/readback uses a new exchange. Do not cancel node application or
label the original mutation rejected. A late reply from an expired/replaced
exchange is ignored/counted; match transaction plus common-record identity,
opcode and page, allowing assigned transfer IDs only for challenge/snapshot
opening replies.

Receipt responses use the same wrapper/header with four data bytes: receipt
state (byte 0), reason (1), field (2), original request opcode (3); remaining
data is zero. Receipt states are queued=0, waiting-for-node=1, duplicate=2,
busy=3, rejected=4, transport-outcome-uncertain=5. Master receipt never
establishes node application success.

Q70 defines receipt state 5, `transport-outcome-uncertain`, with reason 26,
`CAN exchange timeout`, field `record` (1) and original request opcode. Return
this using `ControlReceiptResponse=0x86`, with the normal 64-byte wrapper/common
record and receipt `data_length=4`; all remaining data stays zero. A terminal
uncertain result is returned on polls and identical resubmissions until a new
exchange replaces it. It is distinct from node `CONTROL_ERROR` and from a
master admission rejection.

A poll returns `ControlReceiptResponse` while CAN completion is pending and
`ControlPollResponse` with the actual node common record when ready. Polling a
cached node `pending` reply does not refresh hardware state: submit
`GET_OPERATION` to obtain an updated mutation outcome. `FetchResponse` only
clocks the already prepared SPI reply. Repeated identical submissions do not
enqueue a second exchange or extend deadlines.

The new result-only common opcode `0x7F`, `CONTROL_ERROR`, removes
ambiguity between an opaque descriptor page and a failed page request. It uses
the reply layout below; `request_opcode` identifies the failed request. Normal
successful results still echo their request opcode. This is an explicit
addition to Q54's registry, not a reinterpretation of a reserved field.

Generic acknowledgements, operation replies and `CONTROL_ERROR` use 24 bytes:

| Data offset | Bytes | Field |
|---:|---:|---|
| 0 | 1 | reply kind |
| 1 | 1 | reason code |
| 2 | 1 | field code |
| 3 | 1 | request opcode |
| 4 | 4 | target mutation sequence (zero for non-mutation commands) |
| 8 | 8 | endpoint applied revision, zero for node-wide commands |
| 16 | 8 | accepted desired generation, zero when not applicable |

Reply kinds: command-success=0, command-rejected=1, mutation-pending=2,
mutation-accepted=3, mutation-adjusted=4, mutation-rejected=5,
outcome-unavailable=6. The last kind means a successful outcome query lacks
the original result; it is not rejection of the original mutation. Generic
command rejection does not alter an already admitted mutation's outcome.

Reason codes (unsigned byte):

| Code | Reason | Code | Reason |
|---:|---|---:|---|
| 0 | none | 1 | unsupported opcode |
| 2 | unsupported descriptor schema/version | 3 | unsupported profile |
| 4 | stale node boot | 5 | stale control session |
| 6 | stale applied revision | 7 | busy |
| 8 | recording locked | 9 | conflicting transfer |
| 10 | transfer/snapshot expired | 11 | incomplete request |
| 12 | identity reused with different content | 13 | superseded outcome |
| 14 | sensor SPI failure | 15 | sensor identity mismatch |
| 16 | sensor reset timeout | 17 | register verification mismatch |
| 18 | application deadline exceeded | 19 | unknown operation outcome |
| 20 | challenge invalid/expired | 21 | acquisition or lease active |
| 22 | sequence/identity space exhausted | 23 | unsupported endpoint |
| 24 | invalid request value | 25 | stale master boot |
| 26 | CAN exchange timeout (master uncertainty) | - | - |

Reason 26 reports master transport uncertainty, not node mutation rejection.

Field codes: none=0, record=1, schema=2, profile=3, mode=4, node-boot=5,
session=6, master-boot=7, revision=8, desired-generation=9, length=10,
page=11, recording-lock=12, engine-state=13, sensor-identity=14,
reset=15, register=16, challenge=17, sequence=18, endpoint=19.
Detailed register evidence is in the effective descriptor. Unknown future
reason/field values are preserved numerically and shown as unknown reasons;
they never imply success. Malformed common/envelope records are discarded
without these replies, as agreed in Q48.

## 8. Agreed capability and effective descriptors (Q65)

The capability descriptor is fixed at 128 bytes (six pages: five full plus
eight bytes). Unused profile pairs and reserved bytes are zero.

| Offset | Bytes | Field |
|---:|---:|---|
| 0 | 2 | schema ID (2) |
| 2 | 2 | schema version (1) |
| 4 | 1 | endpoint code |
| 5 | 1 | sensor family (LSM6DSO32X=1; unknown=0) |
| 6 | 1 | supported profile count (0-16) |
| 7 | 1 | reserved |
| 8 | 4 | implemented features |
| 12 | 4 | readiness prerequisites currently satisfied |
| 16 | 4 | health flags |
| 20 | 2 | supported configuration schema ID (1) |
| 22 | 2 | supported configuration schema version (1) |
| 24 | 2 | effective schema ID (3) |
| 26 | 2 | effective schema version (1) |
| 28 | 2 | maximum descriptor length (512) |
| 30 | 1 | page data bytes (24) |
| 31 | 1 | reserved |
| 32 | 2 | fitted endpoint mask |
| 34 | 2 | reserved |
| 36 | 4 | node firmware version |
| 40 | 8 | hardware UID, provenance only |
| 48 | 16 | reserved |
| 64 | 64 | sixteen profile ID/version pairs |

Feature bits: config=0, readback=1, acquisition=2, SYNC capture=3,
raw IMU6 format=4. These are bit positions, not masks. Presence is the fitted
endpoint mask; support is not inferred from it. Prerequisite bits are
config-verified=0, acquisition-backend-ready=1, transport-ready=2,
clock-ready=3. This stage leaves the latter three clear. The logger still
checks authority, desired agreement, health and admission separately.

The effective descriptor is exactly 192 bytes (eight full pages):

| Offset | Bytes | Field |
|---:|---:|---|
| 0 | 2 | schema ID (3) |
| 2 | 2 | schema version (1) |
| 4 | 1 | effective state |
| 5 | 1 | engine power bits: accel=bit 0, gyro=bit 1 |
| 6 | 1 | firmware acquisition active (0 or 1) |
| 7 | 1 | recording lock (0 or 1) |
| 8 | 4 | applicable field-group mask |
| 12 | 4 | known field-group mask |
| 16 | 4 | historical field-group mask |
| 20 | 4 | endpoint health flags |
| 24 | 8 | accepted desired generation |
| 32 | 8 | endpoint applied revision |
| 40 | 2 | effective profile ID |
| 42 | 2 | effective profile version |
| 44 | 2 | output format (`IMU6_I16_LE`=1) |
| 46 | 1 | axis convention (native chip axes=1) |
| 47 | 1 | filter model (`LSM6DSO32X_OUTPUT_CHAIN_V1`=1) |
| 48 | 4 | nominal accel rate numerator, Hz |
| 52 | 4 | nominal accel rate denominator |
| 56 | 4 | nominal gyro rate numerator, Hz |
| 60 | 4 | nominal gyro rate denominator |
| 64 | 4 | accel full scale, millig |
| 68 | 4 | gyro full scale, millidegrees/s |
| 72 | 4 | nominal accel sensitivity numerator, g/count |
| 76 | 4 | nominal accel sensitivity denominator |
| 80 | 4 | nominal gyro sensitivity numerator, degrees/s/count |
| 84 | 4 | nominal gyro sensitivity denominator |
| 88 | 4 | optional filter flags |
| 92 | 2 | native clock source ID (unknown=0) |
| 94 | 2 | native clock flags, zero until defined |
| 96 | 8 | native tick frequency numerator, Hz |
| 104 | 4 | native tick frequency denominator |
| 108 | 4 | register-verification node uptime, ms (modulo 2^32) |
| 112 | 8 | native tick rollover modulus |
| 120 | 4 | measured accel rate numerator, Hz |
| 124 | 4 | measured accel rate denominator |
| 128 | 4 | measured gyro rate numerator, Hz |
| 132 | 4 | measured gyro rate denominator |
| 136 | 4 | accel filter delay, signed nanoseconds |
| 140 | 4 | gyro filter delay, signed nanoseconds |
| 144 | 8 | control session that accepted the desired generation |
| 152 | 24 | register image: addresses 07h-19h inclusive, then 01h, 5Eh, 5Fh; final two bytes zero |
| 176 | 2 | mismatch register address |
| 178 | 1 | expected masked register value |
| 179 | 1 | observed masked register value |
| 180 | 1 | comparison mask |
| 181 | 3 | reserved |
| 184 | 8 | endpoint state epoch |

Effective states: unconfigured=0, verified-disabled=1, verified-enabled=2,
current-unknown=3. State/health remain current even when prior setting groups
are retained as historical evidence. Health bits: sensor-present=0,
initialization-ok=1, sensor-fault=2, clock-fault=3, transport-fault=4,
configuration-unknown=5. Healthy/unhealthy is not inferred from a profile name.

Field-group bits: config identity/profile=0 (24-43 and 144-151), format/axes=1 (44-46),
nominal rates=2 (48-63), ranges=3 (64-71), nominal sensitivities=4 (72-87),
filters=5 (47 and 88-91), engines=6 (5), native clock=7 (92-107 and 112-119),
measured rates=8 (120-135), filter delays=9 (136-143), register proof=10
(108-111 and 152-175), mismatch evidence=11 (176-180). Historical must be a subset of known,
and known a subset of applicable. Not-applicable groups have all masks clear;
applicable/unknown groups have only applicable set; both have zero payload.
Known current groups have applicable/known set; historical groups set all three.
Reserved/mask bits not defined here are zero in version 1. Valid rationals have
nonzero denominators; zero unknown payload is not decoded as a rational.

Profile 1/v1 uses nominal rate 3333/1 Hz for both engines, full scales
32000 millig and 2000000 millidegrees/s, nominal sensitivities 122/125000 g/count
and 7/100 degrees/s/count. These are nominal datasheet conventions, not measured
frequency or per-unit calibration. The exact-part sources round ODR differently;
native ODR code 9 remains authoritative. Sensitivities come from
[DS13607 Table 2](https://www.st.com/resource/en/datasheet/lsm6dso32x.pdf), not
full-scale divided by 32768. Optional filter flags are accel LPF2=bit 0,
accel HP=1, gyro LPF1=2, gyro HP=3; all clear for profile 1. Model 1 retains
the documented internal accel LPF1/gyro LPF2 paths; measured delay is unknown.

The endpoint state epoch is a nonzero boot-scoped 64-bit counter. Advance it
when effective settings, accepted desired generation or eligibility-relevant
knowledge/health changes, not merely on heartbeat or repeated verification.
Snapshot pages remain immutable. Before admission, compare the captured epoch
with a fresh `GET_NODE_STATE` for that endpoint; a mismatch requires fresh
reconciliation. This does not replace endpoint applied revision or permit
settings changes during recording.

Desired generation is interpreted with its accepting control session, not by
its number alone. Binding a new session preserves that old acceptance identity
and hardware settings; it does not relabel prior agreement as current-session
agreement. An explicit apply (including verified no-op) establishes the new
accepting session/generation. Admission checks that identity as well as profile,
revision, health and current state epoch.

Node status bit 0 means at least one endpoint has current verified effective
configuration (including explicit disable); bit 1 means any acquisition active.
Both remain summaries, never authority for admission. Other existing status
bits retain their meanings.

## 9. Agreed session and read operation details (Q66)

Read-only records may use session zero and do not change command authority.
Reads need current expected node boot identity from discovery. Node-wide
operations use endpoint FFh; endpoint snapshots use a fitted endpoint code.
Read IDs are nonzero and separate from mutating sequences. Missing/zero IDs,
nonzero unused command fields and invalid endpoint selectors are malformed.

`GET_CHALLENGE` is a node-wide observational read: transfer zero; data is the
proposed new session ID (8 bytes). Its result places the nonzero challenge in
the transfer field and returns its lifetime in ms (4 bytes, 5000). Pin the
challenge to proposed session, boot and read ID. An identical retry returns
the same challenge without renewing its original expiry. Only one challenge
exists per node; a different admitted challenge request replaces it.

`BIND_SESSION` uses the proposed session ID, mutation sequence 1, challenge
as transfer ID and no data. On success, consume the challenge, initialize the
mutation sequence high-water mark to 1 and preserve all hardware configuration.
It cannot displace live acquisition authority. Retain successful bind identity
separately: a repeated identical bind returns success without resetting sequence
state or extending permission, even after later configuration operations.
Binding never starts acquisition or clears a recording lock.

`RELEASE_SESSION` uses the next mutation sequence, transfer zero and no data.
Require no acquisition, lease, recording lock or pending mutation. Release does
not change hardware settings. Retain a release-only tombstone (identity/request
and result) until next bind or node boot so a lost release reply can be retried
idempotently after authority has ended. Old released-session mutations still
fail; the tombstone does not authorize them.

`GET_NODE_STATE` uses no data/transfer. Its 24-byte result is active session ID
(8), endpoint state epoch (8, zero for node-wide query), state flags (4), pending
mutation sequence (4, zero when absent). Flag bits are session-bound=0,
recording-locked=1, lease-active=2, acquisition-active=3, applying=4,
staging=5, duplicate-address=6, clock-fault=7, any-verified-effective=8,
any-unknown-effective=9. Endpoint queries report endpoint flags where relevant;
node-wide queries aggregate them. Acquisition/lease/recording flags remain clear
in this configuration-only stage.

Snapshot open uses no data/transfer; it assigns a snapshot ID in its result
header and returns 24 metadata bytes: schema ID (2), version (2), total length
(2), page count (1), reserved zero (1), captured applied revision (8), captured
endpoint state epoch (8). Capture at most one snapshot per node. Repeating the
same open read returns the same immutable snapshot without extending expiry.
Capability metadata has revision/epoch zero; effective metadata matches its
descriptor. Other opens while pinned return busy. Reads/releases retain the
opening read ID/session/endpoint and supplied snapshot ID. `READ_PAGE` requests
have no data and return raw descriptor bytes, `data_length` and index; errors
use `CONTROL_ERROR`, never page-shaped error bytes. Snapshot release has no
data and returns command acknowledgement. Expiry/release does not change
hardware settings. Observational snapshots cannot prove session reconciliation.

`GET_OPERATION` uses a new read ID in the common operation field, the nonzero
target session in the common session field, and the target mutation sequence
as four data bytes, transfer zero. Unlike general observational reads, it does
not accept session zero: a sequence has meaning only within its session. The
session must be the active session or the retained release tombstone's session;
otherwise reject stale session without implying an original mutation outcome.
The generic result echoes the target sequence separately. The read never
consumes a mutation sequence. Sequence zero
means no operation and is not a valid target. Only the latest admitted mutation
has detailed cached evidence; earlier ones return outcome-unavailable/superseded.

BEGIN/COMMIT use section 4 metadata. WRITE uses descriptor data and page index.
ABORT uses the same mutation/session/transfer/endpoint and no data; it is valid
only while staging. Once commit begins hardware application, ABORT is rejected
without cancelling the apply. Staging expiry marks that mutation rejected,
reason expired; it is not revived by a late page or commit. Rejected authority
binding, busy begin and malformed records do not consume a mutation sequence.
Always check current node boot first. Normal configuration mutations then
check active session before duplicate lookup. BIND instead validates the
proposed session/challenge or its separately retained identical bind result;
RELEASE permits an identical retained release-tombstone retry without restoring
authority. These narrow exceptions never admit old-session configuration or
reset sequence state. Duplicate completed operations are looked up before expected-revision checks; newly
admitted operations are revalidated at commit before hardware writes.

## 10. Agreed logger interfaces and compatibility (Q67-Q69)

The new canonical flat-file sensor type is `lsm6dso32x_imu`, with initial
`profile=imu6_3333_32g_2000dps_v1`, `provider=can:N` (existing `canN` input alias
retained) and `endpoint=imu`. This profile string maps to wire profile 1/v1.
Use sensor-specific LSM validation and the shared logical metadata model for
name, calibration and mounting information; do not apply BMI270 register/profile
validation or metadata decoding to it. Configuration-only support does not
enable assisted installation operations requiring live samples.

Local BMI270 meanings and behavior are unchanged. Legacy remote BMI270
placeholder entries remain readable/preserved but unresolved with an explicit
migration action to choose the LSM type and supported profile. Do not silently
translate BMI profiles or rewrite the saved configuration. Unsupported legacy
remote entries remain excluded; this does not block healthy local logging.

Web forms, JSON sensor APIs and applicable menu configuration actions use a
shared idle-time validation/save/runtime-rebuild/reconciliation path. Invalid
input and failed persistence preserve the previous saved configuration. A
successful save is distinguished from remote apply pending/rejected/unknown;
valid desired settings remain saved when hardware cannot fulfil them.
Remove the need to restart after successful sensor edits by rebuilding runtime
and scheduling bounded remote reconciliation, not by blocking HTTP/menu handling
until hardware application completes. Mutations are rejected while recording.

Sensor JSON readback includes the saved provider/endpoint assignment, not only
driver-specific parameter definitions. Add structured desired/effective/health/
operation observations, preserving current versus historical provenance and
existing bootstrap diagnostics. All new unsigned 64-bit JSON identities,
generations, revisions and epochs are decimal strings; do not change existing
unrelated field representations. Configuration success and acquisition
readiness remain separate.

Remote mute changes are rejected during recording with a clear recording-lock
explanation. Do not queue hidden changes for later. Idle-time remote mute
changes reconcile the node's explicit enabled/disabled configuration through
the shared path; muted sensors still own their endpoints. Preserve existing
local runtime mute behavior.

## 11. Review and implementation gates

Q1-Q70 decisions are recorded. The final consistency review's lost-reply
deadlock is resolved by Q70's bounded exchange completion in section 7. No
unanswered control-plane design question remains in this interview's scope.
The user confirmed shared understanding of the consolidated checkpoint in
section 12 on 4 November 2026, closing this interview. Firmware implementation
is separate work.

Implementation must use bounded state machines so reset polling/application
does not block control inspection. Fixed storage contains one latest mutation
request/staging buffer (512 bytes maximum), one snapshot (512 maximum), one
cached result and endpoint effective observations; no unbounded queues.
Transport queues have explicit capacity/drop counters and whole-record failure.
A transport timeout is uncertain and does not cancel an accepted hardware apply.

Validation must use independent wire vectors for offsets, lengths, endian
encoding, zero padding, schemas and result kinds; exercise retries/replay and
all semantic failure/recovery cases in network section 13.9. Compile both
production MSPM0 targets and the A8 logger. On-device checks must establish
GPIO/SPI levels, reset/apply/readback bounds, enabled-stopped versus disabled
behavior, no FIFO/sample output, and bounded failure reporting. Record board
revision, firmware version and evidence. No upload is authorized by this design
interview. No sample-timing, signal-response or lease-budget proof is claimed.

Previously agreed deadlines, recording rules and deferred acquisition work
continue to apply. A wire draft is not permission to enable acquisition.

## 12. Consolidated pre-implementation checkpoint

The earlier semantic checkpoint was confirmed on 3 November 2026. Q39-Q70
settle the remaining pre-implementation scope and encodings. The user confirmed
shared understanding of this wire checkpoint on 4 November 2026. The
configuration/effective-state pre-implementation interview is closed.

| Area | Agreed implementation scope |
|---|---|
| Transports | Typed CAN/SPI control with fixed records, explicit versions, strict lengths/reserved fields and unchanged bootstrap layouts |
| State and authority | Boot/session/operation/transfer identities, per-endpoint desired generation/applied revision/state epoch, idempotent staging/commit and coherent snapshots |
| Recovery | Three one-second master CAN application-request attempts, then explicit transport uncertainty and a freed slot for inspection; no inferred rejection/cancellation |
| Physical IMU | LSM6DSO32X profile 1/v1, nominal 3.33 kHz, +/-32 g, +/-2000 degrees/s, specified filter/register policy and bounded hardware verification |
| Stopped/disabled | Enabled-stopped sensing engines run, but no firmware collection, FIFO batching or sample transport; explicit disable powers engines down |
| Descriptors | 44-byte request, 128-byte capabilities, 192-byte effective state; 24 data bytes per page; validity/history and nominal-versus-measured evidence remain explicit |
| Runtime | Fixed-capacity buffers and main-loop state machines; inspection stays serviceable; no unbounded queue or interrupt-time hardware apply |
| Logger | New LSM type/profile, explicit legacy remote BMI migration, shared idle-time save/rebuild/reconcile, complete assignment readback, decimal-string new 64-bit JSON values, remote recording-time mute rejection |
| Verification | Independent protocol/state-machine host tests, both production MSPM0 target builds, A8 build, and separately recorded on-device SPI/reset/readback/failure evidence |

The following remain intentionally outside this implementation stage:

- IMU sample/FIFO acquisition, settling/discard policy, timestamp production,
  source continuity, synchronization and measurement-data transport.
- Recording/start/stop/lease-renewal wire operations and actual lease timing,
  service-pause and flow-control budgets. Their agreed semantic requirements
  remain binding on the later acquisition/transport stage.
- Measured sample rates, signal amplitude/phase/group delay, native-clock
  calibration and production measurement-profile qualification.
- Non-IMU endpoint schemas and automatic same-recording rejoining.

Configuration support must not advertise acquisition readiness before the
deferred prerequisites exist. This checkpoint creates no tickets, commits,
uploads or firmware changes.
