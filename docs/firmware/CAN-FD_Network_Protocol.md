# BODAQS CAN-FD network protocol

Status: discovery/status subset implemented for first-node bring-up  
Date: 3 November 2026

## 1. Purpose

This document defines the CAN-FD boundary between the BODAQS master and up to
four strap-addressed sensor nodes. It is separate from the logger-to-master SPI
protocol and the BDQ v2 storage contract.

The first implementable subset is deliberately small:

- discover a node and establish its strap address, hardware identity, firmware
  version, capabilities and boot identity;
- report node health and transport faults;
- associate hardware synchronization captures with master and node clocks; and
- carry a loss-detectable, efficiently batched six-axis IMU stream.

The identifier allocation also reserves space for configuration, analogue and
external-I2C streams. Their payload schemas remain provisional until the node
I/O contract and supported sensor profiles are frozen.

## 2. Relationship to other contracts

- `CAN-FD_Sensor_Network_Design.md` owns the system architecture, physical
  endpoint model and user-facing configuration principles.
- `CAN-FD_Master_SPI_Protocol.md` owns the logger-to-master transport. Its
  four-page node-inventory transfer is implemented; configuration,
  flow-control and sample-transfer extensions remain undefined.
- `BDQ_v2_Multi_Stream_Contract.md` owns persisted stream records and timing
  observations. CAN batching must preserve the source sequence, native timing,
  discontinuity and loss evidence required by that contract.

The logger remains the source of truth for desired configuration. A node strap
address is its configuration identity. A hardware UID is diagnostic provenance
and must not prevent a compatible replacement node from inheriting the
configuration for that address.

## 3. Conventions

- Multi-byte integers are unsigned, little-endian unless explicitly described
  as signed.
- Reserved bytes and bits in known schemas are transmitted as zero and must
  be zero on receipt. Unknown advertised capability bits are preserved by
  gateways and ignored by consumers that do not understand them.
- Receivers validate the CAN identifier, FD/BRS flags, DLC, protocol major,
  message type and all reserved fields before accepting a message.
- Unknown compatible message types are ignored and counted. A message with an
  unsupported protocol major is rejected and reported.
- CAN's frame CRC is the frame-integrity mechanism. Version 1 adds no payload
  CRC. Source sequences and boot/stream epochs provide end-to-end loss and
  continuity evidence; they are not substitutes for the CAN CRC.
- Requirements use **must** and recommendations use **should**.

## 4. Link profiles

All devices on one physical bus use the same statically selected link profile.
There is no in-band bit-rate negotiation. Every version-1 frame uses an 11-bit
standard identifier, CAN-FD format and bit-rate switching.

| Profile | Arbitration | Data | Intended use |
|---|---:|---:|---|
| `BRINGUP_500K_2M` | 500 kbit/s | 2 Mbit/s | Current master/controller and low-load physical-layer bring-up |
| `NORMAL_1M_4M` | 1 Mbit/s | 4 Mbit/s | Candidate production profile for four approximately 3.2/3.33 kHz IMUs |
| `HIGH_1M_5M` | 1 Mbit/s | 5 Mbit/s | Experimental high-rate profile, subject to full-harness signal-integrity validation |

`BRINGUP_500K_2M` must not be treated as the eventual four-node production
rate. A configured acquisition set must pass an admission calculation before
node acquisition starts. The initial target is no more than 70% conservative
continuous bus occupancy, leaving margin for arbitration, status, faults,
configuration traffic and retransmission.

## 5. Addressing and endpoints

Node addresses 0 through 3 come directly from the two hardware straps. Address
changes take effect only after a node reset or power cycle.

Endpoint codes are stable across node variants:

| Code | Endpoint |
|---:|---|
| 0 | local IMU |
| 1 | analogue input 0 |
| 2 | analogue input 1 |
| 3 | external I2C port 0 |
| 4 | external I2C port 1 |
| 5 | GPIO / switch / indicator interface |
| 6-7 | reserved |

An endpoint's absence from a node capability mask is normal for a reduced node
variant. It is not a protocol error.

## 6. CAN identifier allocation

Lower identifiers have higher arbitration priority.

| Identifier | Direction | Purpose |
|---:|---|---|
| `0x020` | master to all | synchronization marker |
| `0x030` | master to all | broadcast discovery or network control |
| `0x040 + node` | master to one node | targeted request or configuration |
| `0x050 + node` | node to master | response or configuration result |
| `0x060 + node` | node to master | asynchronous fault/event |
| `0x070 + node` | node to master | discovery announcement |
| `0x080 + node` | node to master | periodic node status |
| `0x090 + node` | node to master | stream anchor or synchronization capture |
| `0x100 + node * 8 + endpoint` | node to master | endpoint stream data |
| `0x120-0x7FF` | - | reserved |

A node must transmit only identifiers containing its sampled strap address.
The master is the sole transmitter of master-to-node identifiers.

Two physical nodes with the same strap address will share transmit identifiers.
That is an installation fault, not a supported operating mode. Discovery uses
UID-derived response delay so the master can normally observe both UIDs and
report the duplicate instead of relying on simultaneous responses to collide.

## 7. Control-message envelope

Control, discovery, status, event, stream-anchor and synchronization messages
begin with this eight-byte envelope. High-rate stream-data frames use the
compact format in section 12 instead.

| Offset | Size | Field | Meaning |
|---:|---:|---|---|
| 0 | 1 | `protocol_major` | `1` |
| 1 | 1 | `message_type` | value from section 8 |
| 2 | 1 | `body_version` | initially `1` for every defined body |
| 3 | 1 | `flags` | message-specific; zero when unused |
| 4 | 2 | `transaction` | request sequence, echoed by its response; zero for unsolicited messages |
| 6 | 1 | `body_length` | meaningful bytes following this envelope |
| 7 | 1 | `reserved` | zero |

The received payload length must be at least `8 + body_length`. Any bytes added
to reach a legal CAN-FD DLC are zero padding. Valid CAN-FD payload lengths are
0-8, 12, 16, 20, 24, 32, 48 and 64 bytes.

## 8. Message types

| Value | Name | CAN identifier |
|---:|---|---|
| `0x01` | `DISCOVERY_REQUEST` | `0x030` |
| `0x02` | `NODE_ANNOUNCE` | `0x070 + node` |
| `0x03` | `NODE_STATUS` | `0x080 + node` |
| `0x04` | `NODE_EVENT` | `0x060 + node` |
| `0x10` | `CONFIG_REQUEST` | `0x040 + node` |
| `0x11` | `CONFIG_RESULT` | `0x050 + node` |
| `0x20` | `SYNC_MARKER` | `0x020` |
| `0x21` | `SYNC_CAPTURE` | `0x090 + node` |
| `0x22` | `STREAM_ANCHOR` | `0x090 + node` |

The exact `CONFIG_REQUEST`, `CONFIG_RESULT` and general `NODE_EVENT` bodies are
reserved in draft 0.1. Implementations must not send them until their body
versions are added to this contract.

## 9. Discovery

### 9.1 `DISCOVERY_REQUEST`

The body is eight bytes:

| Body offset | Size | Field |
|---:|---:|---|
| 0 | 4 | `nonce` |
| 4 | 2 | `response_window_ms` |
| 6 | 2 | reserved |

`response_window_ms` must be at least 16 ms. Each node schedules one
`NODE_ANNOUNCE` within the window using a deterministic hash of its 64-bit UID,
the nonce and its address. Repeating discovery with a new nonce changes the
response phase and makes duplicate-address nodes observable. A node may also
announce once after boot, after first reaching error-active state.

### 9.2 `NODE_ANNOUNCE`

The body is 24 bytes and the total payload is 32 bytes:

| Body offset | Size | Field |
|---:|---:|---|
| 0 | 1 | `node_address` |
| 1 | 1 | `hardware_type` |
| 2 | 2 | `endpoint_mask` |
| 4 | 4 | `firmware_version` |
| 8 | 4 | `capabilities` |
| 12 | 8 | `hardware_uid` |
| 20 | 4 | `boot_id` |

The address in the body must match the address encoded in the identifier.
`firmware_version` uses `major << 16 | minor << 8 | patch`. `boot_id` is a
nonzero 32-bit value generated from the MSPM0G3507 TRNG on every MCU boot; it
must not be derived solely from uptime. The initial hardware-type values are:

| Value | Hardware |
|---:|---|
| 1 | full node: IMU, two analogue inputs and two external I2C ports |
| 2 | no-IMU node |
| 3 | no-I2C node |
| 4 | IMU-only node |

Capability bit assignments will be added with the corresponding implemented
features. Unknown bits are preserved by gateways and ignored by receivers.

The master inventory is keyed by strap address. If it observes different UIDs
for one address during one powered interval, it must mark that address
duplicated and must not configure or accept measurement data from it.

## 10. Node status and liveness

`NODE_STATUS` has a 24-byte body and 32-byte total payload:

| Body offset | Size | Field |
|---:|---:|---|
| 0 | 4 | `boot_id` |
| 4 | 4 | `uptime_ms` |
| 8 | 4 | `status_flags` |
| 12 | 4 | `can_rx_frames` |
| 16 | 4 | `can_tx_frames` |
| 20 | 2 | `can_error_events` |
| 22 | 2 | `queue_high_water` |

Initial status flags are:

| Bit | Meaning |
|---:|---|
| 0 | configuration accepted and effective |
| 1 | acquisition active |
| 2 | CAN controller error-passive |
| 3 | a CAN bus-off recovery occurred during this boot |
| 4 | source FIFO overflow occurred |
| 5 | node acquisition queue loss occurred |
| 6 | CAN transmit queue loss occurred |
| 7 | synchronization capture is healthy |
| 8 | local clock or crystal fault |
| 9 | sensor fault currently active |

Fault-history bits remain set for the rest of the current boot. A future
control extension may add explicit acknowledgement and clearing. Counters wrap
modulo their field width.

An idle configured node should report status once per second with a stable
UID/address-derived phase. The master should consider a node stale after three
expected status intervals, but a delayed heartbeat alone must not stop healthy
independent nodes from logging.

## 11. Synchronization

The dedicated SYNC conductor supplies the measurement edge. CAN does not supply
that edge; it associates captures with a sequence and transports the evidence.

The master emits a `SYNC_MARKER` after driving each selected hardware edge. Its
eight-byte body is:

| Body offset | Size | Field |
|---:|---:|---|
| 0 | 4 | `sync_sequence` |
| 4 | 4 | `master_tick_at_edge` |

Each node captures the same edge in hardware and emits one `SYNC_CAPTURE` with
a 16-byte body:

| Body offset | Size | Field |
|---:|---:|---|
| 0 | 4 | `sync_sequence` |
| 4 | 4 | `node_tick_at_edge` |
| 8 | 4 | `boot_id` |
| 12 | 2 | `capture_flags` |
| 14 | 2 | reserved |

The marker's transaction field contains the low 16 bits of `sync_sequence`.
The master and node native-tick frequencies and rollover moduli are reported in
their effective configuration. Missing or ambiguous captures produce timing
diagnostics and continuity boundaries; packet receive time is not substituted
for a hardware capture.

## 12. Stream anchors and IMU data

### 12.1 Stream identity and continuity

The CAN identifier supplies the node address and endpoint. Every active stream
also has an eight-bit `stream_epoch`. A node increments the epoch whenever that
endpoint's acquisition is restarted or its effective record format changes.
The combination of hardware UID, `boot_id`, endpoint and stream epoch defines a
continuity segment.

Before accepting stream data, the master must receive a `STREAM_ANCHOR` for the
same boot and epoch. The node repeats an anchor at least once per second and
immediately after any reset, discontinuity, queue loss or timing-model change.

`STREAM_ANCHOR` has a 20-byte body and is padded to a 32-byte payload:

| Body offset | Size | Field |
|---:|---:|---|
| 0 | 1 | `endpoint` |
| 1 | 1 | `format` |
| 2 | 1 | `stream_epoch` |
| 3 | 1 | `anchor_flags` |
| 4 | 4 | `source_sequence` |
| 8 | 4 | `native_tick` |
| 12 | 4 | `tick_step_numerator` |
| 16 | 2 | `tick_step_denominator` |
| 18 | 2 | reserved |

The tick increment per sample is `tick_step_numerator /
tick_step_denominator`. The denominator must be nonzero. A receiver uses exact
integer/rational accumulation rather than repeatedly rounding the increment.

### 12.2 Six-axis IMU format 1

Format 1 is `IMU6_I16_LE`. Each sample is 12 bytes in this order:

```text
int16 accel_x
int16 accel_y
int16 accel_z
int16 gyro_x
int16 gyro_y
int16 gyro_z
```

Scale, range, ODR, filtering, axis mapping and physical units belong to the
effective endpoint configuration and BDQ stream catalog. They are not repeated
in each frame.

The compact stream-data header is four bytes:

| Offset | Size | Field |
|---:|---:|---|
| 0 | 2 | low 16 bits of the first sample's `source_sequence` |
| 2 | 1 | `stream_epoch` |
| 3 | 1 | count and flags |

Bits 0-2 of byte 3 contain a sample count from 1 through 5. Bits 3-7 are:

| Bit | Meaning |
|---:|---|
| 3 | discontinuity before the first sample |
| 4 | source FIFO or acquisition-queue loss before the first sample |
| 5 | CAN transmit-queue loss before the first sample |
| 6 | timing degraded |
| 7 | final partial batch before an orderly stop |

One through five 12-byte samples follow. Normal continuous transmission uses
five samples and a 64-byte payload. Shorter batches are sent only to bound
startup/stop latency or report a boundary; padding required by the CAN-FD DLC
is zero.

The master extends the low 16-bit sequence using the most recent anchor and
accepted frames. A gap of 32768 or more samples is ambiguous: data is rejected
until a new anchor arrives. The source sequence increments once per emitted
sample and is preserved in BDQ v2. Native ticks are reconstructed from the
anchor and rational tick step. A flagged discontinuity starts a new timing fit
even if the stream epoch did not change.

Other endpoint formats will use the same identifier allocation but need not use
this compact header. Analogue and external-I2C formats must be added here before
their data is emitted.

## 13. Configuration semantics reserved for version 1

The exact bodies are not yet frozen, but the following behavior is contractual:

- configuration is addressed by strap address and endpoint, never by hardware
  UID;
- every request has a logger-assigned configuration generation and transaction;
- requests are idempotent so the master may retry after a lost result;
- a node validates the complete requested endpoint configuration before making
  it effective and reports accepted, rejected or accepted-with-adjustment;
- the result reports the effective configuration, not just success;
- configuration and installation activity may stop and rebuild acquisition but
  must not require an MCU or logger restart;
- configuration is not changed while logging;
- an incompatible or rejected endpoint is excluded without blocking healthy
  independent endpoints; and
- endpoint ownership remains exclusive even when its logical sensor is muted.

### 13.1 Agreed configuration/effective-state decisions (3 November 2026)

The decisions below were agreed during the node configuration/effective-state
interview. Section 13.9 consolidates them for shared-understanding review and
lists explicit deferrals. Wire bodies are not yet frozen; this section does not
enable the reserved messages or claim implementation/hardware verification.

- The control contract covers both logger-to-master SPI and master-to-node
  CAN. The initial endpoint schema is IMU-only, with an extensible envelope for
  future endpoint schemas. IMU acquisition and sample transport follow as
  separate implementation stages.
- An endpoint request is a complete replacement, not a patch. Endpoints apply
  independently: rejection on one must not block healthy independent endpoints.
  All settings within one endpoint are validated together before hardware is
  changed. Validation rejection preserves its previous effective state. If
  hardware application fails, the endpoint is faulted and excluded until
  recovery verifies a known configuration; the old state must not be claimed
  to have survived without evidence.
- Exact acceptance is the default. Adjustment is allowed only to alternatives
  explicitly permitted by the request. Every difference is reported without
  rewriting desired configuration. Admission calculations and stream metadata
  use the effective settings.
- Applied node configuration is volatile. A rebooted node is unconfigured with
  acquisition stopped until the logger reconciles it. Observations from an
  earlier boot are historical until fresh application and readback succeed.
  A node reboot during recording excludes that node for the remainder of the
  recording. Healthy participants continue; the reset and stream interruption
  are reported, and reconciliation waits until recording ends. Automatic
  same-session reboot recovery is deferred.
- Configuration-effective and acquisition-active are separate states.
  Applying settings leaves acquisition stopped. Starting requires an explicit
  operation, verified effective configuration and an admitted participation
  plan. Stopping preserves configuration; reconfiguration requires acquisition
  to be stopped, in addition to the prohibition on changes while logging.

### 13.2 Agreed identity, readback and interpretation decisions

- Desired configuration generation, applied revision, operation transaction,
  node boot identity and control-session identity have distinct meanings.
  Desired generation identifies requested settings; applied revision identifies
  verified application changes; transaction identifies an operation; node boot
  identity invalidates earlier-boot observations. Control-session identity
  prevents accidental reuse of old command identities after logger restarts.
  A retry does not advance applied revision. Inventory generation is not a
  configuration generation. Identity widths and operation rollover are defined
  in section 13.6; endpoint revision semantics are defined in section 13.8.
- An apply timeout leaves the logger's knowledge uncertain, not proof of
  rejection or preservation of the old state. Retry the identical request with
  the same operation identity; different content under that identity is an
  error. Use bounded retries followed by readback, excluding the endpoint while
  effective state remains uncertain. Retry and timeout budgets are defined in
  section 13.7.
- Effective-state readback is a coherent, complete endpoint descriptor. It
  includes identity/revision, actual configured rates, ranges, filters, output
  format, units/scales, axis convention and native-clock definition. Nominal
  settings and measured timing evidence are distinguished. Multi-message
  descriptors must identify one snapshot; mixed revisions are rejected.
- Nodes emit raw sensor-axis values, apply acquisition settings and report
  hardware scaling and axis conventions. The logger owns user calibration and
  mounting transforms and records these alongside effective acquisition
  settings, preserving raw measurements for later analysis.
- Fitted endpoint presence, supported configuration schemas, effective
  configuration and acquisition readiness are reported independently. Firmware
  features are advertised explicitly rather than inferred from endpoint masks.
  Configuration support alone does not establish recording eligibility:
  acquisition and sample transport must also be implemented. Unsupported
  schemas receive a structured rejection.

### 13.3 Agreed authority, persistence, admission and verification decisions

- A master restart invalidates its command authority until the logger
  establishes a fresh control session. The master routes logger-authorized
  operations and never autonomously restores configuration or starts
  acquisition. Before new authority is established, it may discover and read
  state but must not mutate it. Old-session commands are rejected. Behavior of
  already-running nodes on authority loss is governed by the acquisition lease
  in section 13.4.
- Invalid configuration input leaves saved configuration unchanged. A valid
  desired configuration remains saved when its node is absent or rejects it.
  Any known previous effective state is preserved as an observation, the
  disagreement is displayed, and the endpoint is excluded until its settings
  satisfy the current desired configuration or permitted alternatives. A
  superseded configuration must not silently be used for recording.
- Disabling an endpoint is an explicit complete configuration operation while
  idle, with acknowledgement that acquisition is stopped and start is
  prohibited. Saved sensor identity and installation data remain retained.
  Muting still reserves endpoint ownership.
- Admission is calculated from verified effective descriptors while acquisition
  is stopped. Admission failure does not undo successfully applied settings.
  A participant set exceeding capacity requires an explicit settings or
  participant change: rates must not silently be reduced, and otherwise healthy
  sensors must not be silently selected for exclusion. Independent local
  logging remains available.
- Successful application requires hardware evidence, including successful
  initialization and readback of readable configuration fields, with
  sensor-specific checks for settings that cannot be read directly.
  Unavailable evidence is explicit. Verification establishes programmed
  acquisition settings; sample production, timing accuracy and physical
  performance require separate checks in later stages.

### 13.4 Agreed lease, stale-command, operation and schema decisions

- Acquisition requires an explicit, periodically renewed logger-authorized
  control-session lease. Expiry stops acquisition, preserves effective
  configuration and records the interruption. Communication returning does
  not resume acquisition: explicit authorization is required. Lease and renewal
  timing budgets remain open.
- Every mutation identifies the expected node boot and control session.
  Configuration mutations also identify the expected applied revision.
  Mismatches and stale revisions are rejected before hardware is touched.
  Compatible replacement nodes inherit desired settings only through fresh
  discovery and reconciliation; UID remains provenance, not configuration
  identity. Binding and renewal semantics are defined in sections 13.5 and
  13.6; their wire encodings are deferred.
- Version 1 serializes mutating operations per node. The node retains the
  latest operation identity, request content and result for retries, and
  rejects older operations rather than executing them again. This does not
  change independent endpoint acceptance semantics. Readback remains available
  during a pending operation and explicitly reports that operation's state.
  Identity widths and operation rollover are defined in section 13.6. Exact
  encodings and completion-cache storage are wire-specification work.
- IMU requests use explicitly versioned, complete acquisition profiles, not
  arbitrary register writes or unrestricted overrides. Results expand profiles
  into the complete effective descriptor. Firmware advertises only profiles
  it can apply and verify. Proposed profiles are distinct from supported ones;
  at least one concrete profile and its register-verification procedure must
  be specified before enabled configuration is implemented (section 13.10).
  Physical acquisition performance requires later validation.
- Operations distinguish pending, accepted, accepted-with-permitted-adjustment
  and rejected outcomes, with stable reason codes and field-specific evidence.
  Effective state and endpoint health are separate from operation outcome.
  Hardware application failure may leave effective state unknown; validation
  rejection preserves the previous verified state. Q64's reply encodings are
  in section 7 of `CAN-FD_Node_Control_Contract.md`.

### 13.5 Agreed asynchronous exchange, paging and lease-expiry decisions

- SPI submission acknowledges receipt promptly; eventual node results are
  polled separately using end-to-end operation identity. Master receipt is not
  node application success. Configuration must not depend on completion within
  the bootstrap request's three-fetch exchange.
- Descriptors are transferred as requested pages, not unsolicited bursts.
  Pages contain at most 32 descriptor bytes; a descriptor is at most 512 bytes.
  Request one page at a time and bind pages to endpoint, boot, control session
  and snapshot identity. Incomplete or mixed snapshots are never adopted.
  These are agreed protocol bounds, not measured throughput claims. Snapshot
  retention is defined in section 13.7; exact framing is deferred.
- Acquiring authority requires current node boot identity and a fresh node-issued
  single-use challenge. Retries of the same successful binding return the same
  result. A different session cannot displace a live acquisition lease.
  Replacing authority requires acquisition stopped and the previous lease
  expired or explicitly released. Binding does not change configuration or
  start acquisition.
- An endpoint whose acquisition lease expires is excluded for the rest of that
  recording, like a rebooted node. Report the interruption, continue healthy
  participants and reconcile after recording ends. Automatic rejoining is
  outside the first release. Leases are retained after explicit discussion of
  their renewal overhead and sensitivity to communication interruptions.
- Configuration submission, application and snapshot transfer have finite,
  independently specified deadlines. Lease duration and renewal cadence will
  be frozen during acquisition/transport design against its logger service-pause
  budget. Acquisition readiness must not be advertised until those values and
  recording-time servicing are implemented and verified.

### 13.6 Agreed recording lock, replay, identity and staging decisions

- Recording membership and acquisition activity are separate. An admitted
  node rejects configuration mutations until explicitly released after the
  recording ends. Lease expiry stops acquisition but does not release this
  recording lock. A reboot loses the volatile lock; the logger still excludes
  the rebooted node and sends no configuration until recording ends.
- Lease renewals have monotonically increasing sequence numbers within their
  acquisition authorization. Only a new renewal extends expiry; duplicates do
  not. Once expired, that authorization rejects all renewals. The master only
  forwards logger renewals and never renews autonomously.
- Control-session identifiers are 64-bit. Operation sequences are 32-bit and
  never wrap within a session: establish a fresh session while idle before
  exhaustion. Desired generations and boot-scoped applied revisions are
  64-bit. The existing 16-bit CAN transaction field correlates exchanges but
  is not the duplicate-suppression key. Zero represents unset identity/revision
  where applicable. The wire contract defines field-specific initialization
  and scopes, including the session accepting a desired generation.
- Before admission, reconcile every supported endpoint of a node. Muted and
  unassigned endpoints are explicitly configured disabled rather than omitted.
  Muted endpoints retain desired ownership and installation data. Acquiring a
  new control session must not silently reuse a previous session's acquisition
  eligibility.
- Multi-page requests are staged completely in bounded storage. Receiving pages
  does not change hardware. An explicit commit identifies the complete request
  and starts validation/application after completeness checks. Missing,
  conflicting or expired pages cause no hardware changes.

### 13.7 Agreed lease scope, fault containment, deadlines and eligibility

- One acquisition lease covers a node's frozen participant endpoint mask for
  the recording. Expiry stops all participating endpoints on that node.
  Endpoint-specific faults may exclude an endpoint while verified healthy,
  independent endpoints continue.
- A failure is endpoint-local only when the node verifies that the failed
  endpoint is stopped and shared resources remain healthy. Otherwise the node
  is ineligible. Node bus-off stops acquisition and invalidates its acquisition
  authorization; controller recovery alone does not resume participation in
  that recording.
- Retain one immutable descriptor snapshot per node for up to five seconds or
  until explicitly released. Pages describe the captured state, with identity
  and revision attached. Live state changes do not modify that snapshot and
  invalidate recording eligibility until fresh reconciliation. An expired
  snapshot requires a new transfer.
- A transport step permits one second per attempt, at most three attempts with
  the same identity. A complete request must be staged within five seconds;
  expiry discards it without application. Application must finish within two
  seconds of node acceptance of commit. After sending commit, the logger waits
  at most five seconds for a definitive result, then marks its knowledge
  uncertain and uses readback. Descriptor transfer has a five-second total
  deadline which retries cannot extend. These are design requirements to
  validate, not measured hardware performance. Profiles unable to meet the
  application deadline must not be advertised as supported.
- Per-endpoint effective state, agreement, health and readiness determine
  recording eligibility. Node-wide status is a compact diagnostic summary;
  neither its configuration-effective bit nor endpoint presence permits
  recording on its own. Q65's summary aggregation is in section 8 of
  `CAN-FD_Node_Control_Contract.md`.

### 13.8 Agreed endpoint revisions and permitted profile selection

- Each endpoint has its own 64-bit, boot-scoped applied revision. Revision zero
  denotes unconfigured state. Advance the revision after a successfully
  verified effective configuration change, including enable/disable. Retries
  and identical no-op applications do not advance it. A no-op may acknowledge
  a new desired generation without restarting hardware. After application
  failure, the last verified descriptor is historical and current effective
  state is unknown.
- A request identifies one preferred profile by ID and version, followed by an
  ordered list of at most eight explicitly permitted alternatives, also
  identified by ID and version. Select the preferred profile if supported;
  otherwise select the first supported permitted alternative and report
  accepted-with-adjustment. If none is supported, reject before changing
  hardware. A hardware failure applying the selected profile produces a fault,
  not automatic attempts with the remaining alternatives.

### 13.9 Consolidated review checkpoint and explicit deferrals

The user confirmed shared understanding of the following semantic contract on
3 November 2026. The follow-up interview addresses the wire specification still
needed before configuration/effective-state implementation; IMU acquisition
and sample transport remain later stages.

| Boundary | Agreed behavior | Detail |
|---|---|---|
| Ownership | Logger owns saved desired configuration; strap address and endpoint identify the assignment | Sections 2, 13.1, 13.3 |
| Apply | Complete endpoint replacement, staged then committed while idle; independently accepted endpoints | Sections 13.1, 13.6 |
| Verification | Hardware-backed effective readback; uncertainty and health remain explicit | Sections 13.2, 13.3, 13.4 |
| Profiles | Preferred versioned profile with up to eight ordered permitted alternatives | Sections 13.4, 13.8 |
| Identity | Distinct session, operation, desired generation, endpoint revision and node boot; stale mutations rejected | Sections 13.2, 13.4, 13.6, 13.8 |
| Control path | Asynchronous SPI receipt/completion; one mutation per node; bounded, coherent paging | Sections 13.4, 13.5, 13.6 |
| Participation | Reconcile all supported endpoints, explicitly disable muted/unassigned ones, then admit using effective settings | Sections 13.3, 13.6, 13.7 |
| Acquisition | Explicit start/stop separate from configuration; one renewable node lease and frozen participant mask | Sections 13.1, 13.4, 13.7 |
| Recording lock | Stopped acquisition or expired lease does not authorize configuration changes during recording | Section 13.6 |
| Recovery | Reboot, lease expiry or bus-off excludes the node for the remaining recording; healthy independent participants continue | Sections 13.1, 13.5, 13.7 |
| Interpretation | Raw sensor axes and hardware scaling from node; user calibration and mounting transforms owned by logger | Section 13.2 |

The bounded control-plane requirements are:

| Quantity | Requirement |
|---|---|
| Descriptor size / page data | At most 512 bytes / 32 bytes |
| Transfer window | One requested page at a time |
| Mutations | One outstanding per node |
| Transport step | One second per attempt, at most three attempts |
| Request staging | Five seconds total |
| Node application | Two seconds from node acceptance of commit |
| Logger result wait | Five seconds from sending commit, then uncertain/readback |
| Snapshot retention / descriptor transfer | At most five seconds each; retries do not extend transfer deadline |

These are protocol requirements to validate, not measured timing or performance
claims. The following work is explicitly deferred rather than silently assumed:

- **Wire specification before implementation:** CAN/SPI message allocations,
  exact request/result/capability/effective-descriptor layouts, schema versions,
  legal-DLC padding, page/commit correlation, session/challenge encoding,
  stable reason codes, pending-operation representation, completion-cache
  storage and node-summary bit aggregation. This was the original checkpoint's
  deferral; Q39-Q69 subsequently settled the control wire contract in
  `CAN-FD_Node_Control_Contract.md`. Implementation and its validation remain
  separate work; existing reserved messages stay disabled until implemented.
- **Before hardware configuration implementation:** at least one concrete
  LSM6DSO32X profile ID/version, numerical rates/ranges/filters and its
  register-verification procedure (section 13.10). This refines the earlier
  deferral of all concrete profiles to acquisition work.
- **Initial profile selection:** Q46 agreed matched nominal 3.33 kHz, +/-32 g,
  +/-2000 degrees/s and high-performance mode, with optional accel LPF2 and
  gyro LPF1 bypassed and high-pass paths disabled. Profile wire IDs and exact
  register policy still need specification; see section 13.11 and the linked
  primary-source research.
- **IMU acquisition stage:** native-clock source/frequency/rollover and evidence
  for sample production and physical performance. Proposed profiles are not
  advertised as supported.
- **Acquisition/transport stage:** recording/start/stop/release and lease-renewal
  wire operations, renewal cadence and lease duration, logger recording-time
  service path and maximum pause, queue/flow-control budgets, synchronization,
  and sample transport. Acquisition readiness stays false until its required
  support and timing budgets are implemented and verified.
- **Later extensions:** non-IMU endpoint schemas and automatic same-recording
  rejoining after reboot, lease expiry or bus-off.

Implementation validation must exercise lost results and duplicate commits,
same-identity/different-content requests, stale boot/session/revision rejection,
partial/expired/mixed page transfers, exact/adjusted/rejected profiles, hardware
apply failure, no-op revisions, disabled/muted endpoints and independent fault
containment. Later acquisition validation must also exercise recording locks,
lease renewal/replay/expiry, reset and bus-off exclusion, and continued operation
of healthy independent participants. Host tests and builds do not establish
physical timing or measured signal performance.

### 13.10 Agreed pre-implementation scope and wire foundations (Q39-Q43)

- The first configuration implementation includes physical IMU configuration
  and register verification with sample acquisition disabled. At least one
  initial numerical profile and its verification procedure must be settled
  beforehand using primary sources. Register verification does not prove
  bandwidth, phase or sample timing. FIFO acquisition and sample transport
  remain later stages.
- SPI carries typed configuration/control operations rather than arbitrary
  CAN-frame tunneling. A shared end-to-end representation has explicit
  transport adapters. The master validates routing, identity, bounds and
  operation state; the node performs sensor-specific validation/application.
  Descriptors are preserved without requiring master knowledge of IMU registers.
- Version 1 uses fixed, explicitly versioned binary records with specified
  field widths, offsets, units and meaningful lengths. Unsupported schemas and
  nonzero reserved fields in known schemas are rejected. CAN DLC padding is
  zero. Unknown advertised capability bits are preserved without interpretation.
  Optional additions use advertised capabilities and new schema versions.
- The control extension advertises a control-information exchange with a fresh
  master boot identity. Submissions and results bind to that identity. A change
  invalidates pending operations and cached control observations. Existing
  bootstrap identity/status layouts remain intact so older combinations can
  still discover one another.
- Bounded discovery, capability and effective-state inspection are available
  before command authority exists. Such snapshots are observational; alone
  they do not establish configuration agreement or recording eligibility.
  Session establishment and fresh reconciliation are required before admission.

### 13.11 Agreed frame packing, stopped behavior, profile and rejection (Q44-Q48)

- Version 1 uses 24 descriptor data bytes per page (within the agreed at-most-32
  limit). Repeat full transfer identity in each page: 64-bit control session,
  existing 32-bit node boot ID, 32-bit operation/read identifier, 64-bit
  transfer/snapshot identifier, endpoint, page index, byte count and opcode.
  These occupy a 28-byte header and 24-byte data area: a 52-byte common record.
  The CAN envelope adds eight bytes and the 60 meaningful bytes are zero-padded
  to DLC 64. A 12-byte SPI routing/master-boot wrapper fits the same record
  exactly in the existing 64-byte slot payload. Opening/commit records bind
  expected applied revision, desired generation and total descriptor length
  immutably to the transfer. Exact field offsets are still to be specified.
- For this release, enabled-but-stopped means the IMU sensing engines may run
  under the programmed profile, but the node does not collect, sequence or
  transmit samples. FIFO is bypassed and acquisition interrupt routes are
  disabled. Explicit endpoint disable powers down both sensing engines.
  Engine power state and firmware acquisition activity are separately reported.
- The initial version-1 profile uses matched nominal 3.33 kHz accel/gyro ODR,
  +/-32 g, +/-2000 degrees/s and high-performance operation. Accel optional
  LPF2 and gyro optional LPF1 are bypassed and high-pass paths are disabled.
  Use raw six-axis output semantics and describe remaining filter paths.
  This is a bring-up candidate pending measured amplitude/phase and acquisition
  timing; successful register verification does not establish readiness.
  Evidence and the power-down alternative considered during research are in
  `CAN-FD_IMU_Configuration_Research.md`; this contract's Q45 decision governs
  enabled-but-stopped behavior.
- Descriptors distinguish verified values, unavailable values and historical
  observations using explicit validity/state fields. Required acquisition
  setting readback must succeed for acceptance. Unavailable clock, measured-rate
  and performance evidence is unknown, not a plausible zero or a nominal value
  presented as measured. Missing acquisition prerequisites block readiness,
  not honest configuration-only readback.
- Malformed framing, length, padding or reserved fields cause no mutation and
  are discarded/counted without an application response. Structurally valid
  requests receive correlated rejections for unsupported schemas/profiles,
  stale identities/revisions, conflicting transfers, busy state or recording
  lock. Transport silence remains uncertain to the caller, not rejection.

### 13.12 Agreed transfer, replay, capability, disable and hardware rules (Q49-Q53)

The byte layouts and allocations are collected in
[CAN-FD_Node_Control_Contract.md](CAN-FD_Node_Control_Contract.md). Decisions
through Q70 are confirmed; the user closed the pre-implementation interview on
4 November 2026. Its checkpoint is in section 12 of the wire contract.
Implementation validation is separate. Agreement does not
enable reserved messages.

- Opening fixes endpoint, schema/version, total length, desired generation and
  expected applied revision. Pages have zero-based indices, exact byte counts
  and zero unused bytes. Identical duplicates are acknowledged without
  extending deadlines. A conflicting duplicate invalidates staging. Commit
  requires every expected byte, original metadata and no trailing content;
  incomplete/conflicting/expired staging has no hardware effects.
- After checking boot/session identity, duplicate-operation recognition occurs
  before current-revision checks. An identical completed operation returns its
  cached result, even though successful application advanced the revision.
  Different content under the same identity is rejected. Only new operations
  undergo current-revision checks. Retain the latest operation's request/result
  until replaced by another operation or session end; older operations are
  superseded and never execute again.
- Capability reporting separates fitted endpoints, supported endpoint schemas,
  configuration/readback support, acquisition support, synchronization support
  and supported profile ID/version pairs. Zero supported profiles is valid;
  version 1 permits at most 16 per endpoint. Advertise the single agreed IMU
  profile once its backend exists. Explicit wire capabilities are mapped into
  logger capabilities; acquisition support is not inferred from endpoint masks.
- Disabled mode uses zero profile ID/version, no alternatives and no leftover
  profile payload. Success requires verification that both sensing engines are
  powered down, FIFO bypassed and acquisition interrupt routes disabled.
  Acquisition-only descriptor fields are not applicable, distinct from unknown
  and historical. Saved desired settings remain on the logger.
- Initial hardware access uses four-wire SPI mode 3 at 1 MHz, safe idle GPIO
  levels and unrouted IMU interrupts. Require expected identity; perform bounded
  software reset when initialization or a changed configuration requires it,
  then write/verify documented owned fields with masks. Reset completion has a
  100 ms timeout within the two-second application budget. Verified identical
  no-op requests do not reset hardware. These are implementation requirements
  pending board validation; see `CAN-FD_IMU_Configuration_Research.md` for
  primary-source evidence and pin constraints.

### 13.13 Agreed wire allocations, schemas and implementation boundaries (Q54-Q58)

Q54-Q55 freeze the common record/SPI wrapper offsets, transport and command
allocations, schema/profile IDs and 44-byte IMU request in sections 1-4 of
[CAN-FD_Node_Control_Contract.md](CAN-FD_Node_Control_Contract.md). Acquisition
commands stay reserved; staging abort is not hardware rollback/cancellation.

Q56-Q58 select a fixed 192-byte effective descriptor with explicit field-group
applicability, knowledge and history; bounded main-loop processing outside
interrupts; one mutation context and one immutable snapshot per node; and
endpoint-scoped logger control/effective observations with string-encoded new
64-bit JSON identities/revisions. See section 5 of that wire contract. These
decisions do not authorize firmware implementation during this interview.

### 13.14 Agreed identity lifecycle, operation admission and baseline (Q59-Q63)

Section 6 of [CAN-FD_Node_Control_Contract.md](CAN-FD_Node_Control_Contract.md)
records the agreed random master/session identities, challenge lifetime,
independent read sequences, session-scoped endpoint desired generations,
mutation-sequence consumption at begin admission, unknown-versus-rejected
query outcomes, fresh verification for new no-op requests and initial IMU
register baseline. These refine the earlier semantic decisions without
enabling acquisition or claiming hardware verification.

### 13.15 Agreed final encodings and logger integration (Q64-Q69, 4 November 2026)

Sections 7-9 of [CAN-FD_Node_Control_Contract.md](CAN-FD_Node_Control_Contract.md)
define the agreed control information/replies, explicit `CONTROL_ERROR=0x7F`,
reason/field codes, capability/effective descriptor layouts, accepting-session
provenance, endpoint state epoch and session/read retry rules. Sections 10-11
record logger compatibility and implementation gates.

The canonical remote IMU type/profile are `lsm6dso32x_imu` and
`imu6_3333_32g_2000dps_v1`. Preserve local BMI270 behavior and keep legacy remote
BMI270 placeholders readable but unresolved, with an explicit migration action.
Shared idle-time config application covers web, JSON and applicable menu paths;
saved assignment is included in JSON readback. New 64-bit JSON values are decimal
strings. Remote mute changes are rejected during recording, with no hidden
queued change; local runtime mute remains unchanged. No firmware implementation
or physical verification is claimed by this agreement.

### 13.16 Agreed bounded master exchange recovery (Q70, 4 November 2026)

The master retries an unanswered CAN application request using the same record
identity/transaction, at most three one-second attempts. Identical SPI
submissions neither add attempts nor extend deadlines. On exhaustion it frees
the pending slot and reports receipt state 5, transport-outcome-uncertain,
reason 26, CAN exchange timeout. This does not reject or cancel node application.
Later operation queries/readback use a new exchange; late expired/replaced
exchange replies are ignored/counted. See wire contract section 7 for encoding
and section 12 for the consolidated pre-implementation checkpoint.

### 13.17 Acquisition/transport interview: accepted requirements (Q71-Q147, 4 November 2026)

The acquisition/transport interview remains open. The following requirements
were accepted; they do not enable acquisition or establish measured performance.

- **Q71 — Recoverable sample loss:** FIFO or queue loss may be followed by
  continued acquisition within the recording while the node remains healthy
  and its acquisition lease remains valid. Record the loss and a continuity
  boundary, with an exact missing-sample count where knowable and an explicit
  unknown count otherwise. Resume only after sample pairing and timing are
  trustworthy; otherwise exclude the affected endpoint. Existing reboot,
  bus-off and lease-expiry exclusion rules remain binding.
- **Q72 — Timing allocation:** Target at most 10 us of relative inter-node
  sample-time uncertainty attributable to capture and clock reconstruction,
  leaving part of the existing approximately 10-degree phase allowance at
  1 kHz for sensor timing differences. This is a design and later validation
  target, not measured capability or proof of complete sensor phase performance.
- **Q73 — Preparation and recording boundary:** Pressing Record may enter a
  visible Preparing phase. Complete required settling, startup discards and
  initial usable timing evidence before recording valid samples. Discard
  preparation samples; retain no pre-roll. Resolve admission before starting,
  applying the existing best-effort policy to unavailable sensors rather than
  waiting indefinitely. Physically simultaneous first samples are not required.
  Preparation duration, deadlines and detailed start sequencing remain open.
- **Q74 — Recording-time priorities:** Acquisition servicing and existing local
  sensor requirements take priority. Optional web/UI work and background
  maintenance may be restricted or deferred where needed; Stop and essential
  status remain available. Derive a service-pause envelope from actual logger
  paths before selecting queue sizes or lease timing. Physical timing
  verification remains outstanding.
- **Q75 — Degraded alignment during recording:** Retain raw samples and timing
  evidence when sample order and native timestamps remain trustworthy but
  inter-node alignment no longer meets Q72. Mark the affected interval as
  timing-degraded; downstream analysis must not treat it as meeting the target.
  Missing or ambiguous captures introduce timing boundaries as already required.
  Untrustworthy native sample timing or pairing instead invokes Q71.
- **Q76 — Software sample queue overflow:** Preserve existing queued contents
  and reject the newest incoming complete batch. Count the loss and mark the
  boundary before the next subsequently accepted sample. Hardware FIFO overflow
  requires a separate recovery procedure; this policy does not imply hardware
  support for dropping the newest sample.
- **Q77 — Master-to-logger ownership transfer:** Release a transferred batch
  from the master only after the logger acknowledges validation and acceptance
  of the complete batch into a bounded RAM queue. Transfer identities prevent
  duplicate insertion after a lost acknowledgement. Failed or incomplete
  transfers leave the master's copy available for retry. Acknowledgement means
  RAM acceptance, not SD persistence. Subsequent storage backpressure and logger
  queue loss remain observable; power-loss recovery remains bounded by the last
  complete CRC-valid file chunk. This SPI retry policy does not change the CAN
  sample stream's prohibition on application-level retransmission.
- **Q78 — SPI measurement mode:** Extend SPI with a separately versioned,
  explicitly negotiated high-throughput measurement-transfer mode, preserving
  existing bootstrap/control compatibility. Transfer sizes and pacing require
  their own capacity/timing contract; bootstrap slots and guard times are not
  assumed sufficient for recording throughput.
- **Q79 — Recording-time service task:** One dedicated task owns recording-time
  master communication, including sample draining and forwarding logger-issued
  lease renewals, independently of main-loop SD writes. Coordinate shared SPI
  access with ADC tasks using bounded transactions. Priorities, transaction
  limits, queue sizes and a verified service-pause bound remain open. This does
  not authorize autonomous master renewal.
- **Q80 — Timing quality is not an admission gate:** Admit otherwise eligible
  sensors even when inter-node timing cannot meet Q72; only some analyses
  require tightly aligned timing. Retain samples with explicit timing quality
  and available uncertainty evidence from the beginning of the recording.
  Q72 remains a design/validation target, not an admission requirement. Q73's
  preparation gate requires trustworthy native sample timing and pairing, not
  proof of the inter-node target. Analyses requiring tight alignment must use
  the recorded quality/evidence to determine suitability.
- **Q81 — Orderly stop and finalization:** Stop sample production first, then
  allow a finite drain interval for remaining accepted samples, with a visible
  Finalizing phase and a specified deadline. Preserve final partial batches
  where possible and explicitly report undelivered tails and uncertain counts.
  Do not wait indefinitely for a failed participant. Recording membership
  remains until recording ends and explicit release occurs. The deadline and
  exact stop/release exchanges remain open.
- **Q82 — Combined timing evidence:** Develop acquisition around tagged FIFO
  samples with sensor timestamps, supplemented by hardware-captured IMU
  data-ready edges and trunk SYNC. FIFO tags/timestamps establish sample order
  and slot identity; captures relate sensor output timing to the node clock.
  Preserve sufficient evidence for downstream uncertainty assessment. Mark
  ambiguous associations rather than deriving exact times from nominal ODR.
  Association algorithms, capture rates and stored evidence remain open; this
  direction does not establish the Q72 target.
- **Q83 — Hardware FIFO policy:** Use continuous FIFO mode with timestamp
  insertion for every FIFO slot. After overrun, use ST's documented timestamp
  resynchronization approach: discard entries until a fresh timestamp supplies
  a reconstruction boundary, then resume only once pairing and native timing
  are trustworthy. Missing counts remain explicitly unknown where evidence
  cannot establish them. This hardware overwrite-oldest behavior is separate
  from Q76's software drop-newest policy. See the exact-part evidence in
  [the acquisition timing research](CAN-FD_IMU_Acquisition_Timing_Research.md).
- **Q84 — Protected control and timing service:** Reserve bounded queue capacity
  and service opportunities for lease renewals, Stop, status and timing
  evidence. Sample backlog must not consume all of these resources. Prefer
  explicit sample loss to avoidable lease expiry or loss of interpretation
  evidence. Exact reservations and scheduling limits remain capacity work;
  this does not imply protection from physical bus faults or indefinite stalls.
- **Q85 — Six-axis item identity:** One recorded six-axis item contains
  acceleration and gyro outputs from the same validated FIFO slot. Pair using
  decoded slot identity, not merely adjacent entries. Discard incomplete or
  ambiguous pairs with explicit loss/boundary evidence. Slot membership does
  not assert simultaneous physical measurements; retain the distinction
  between slot timing and sensor-specific measurement/filter delay for analysis.
- **Q86 — Conservative preparation:** The first implementation applies a full
  conservative settling/discard sequence at every recording preparation,
  including already-running sensing engines. The research's cold-start gyro
  allowance of 70 ms plus 270 discarded samples and ten acceleration samples
  inform the procedure, not its complete duration or measured sufficiency.
  Shortening preparation using warm-up history is a later evidence-supported
  optimization. Detailed sequencing remains to be specified.
- **Q87 — Per-stream stop boundaries:** Request stopping promptly and drain
  each stream through its own confirmed final sample-sequence boundary. Record
  the operator's Stop request time separately; do not trim all streams to that
  instant. An unconfirmed final boundary at the finalization deadline leaves
  the tail explicitly incomplete or uncertain. This does not require tight
  inter-node alignment to finish recording.
- **Q88 — Separate timing evidence:** Retain the existing compact five-sample
  CAN axis-data packets and transport additional timing evidence in explicitly
  defined messages associated with sample sequences and continuity segments.
  Preserve selected raw sensor timestamps and hardware-capture values. Times
  reconstructed from a constant rational tick step are modeled times with
  supporting evidence and uncertainty, not individually observed captures.
  Evidence-message and stored-schema definitions remain open.
- **Q89 — Bounded timing evidence retention:** Inspect per-slot timing evidence
  on the node, but transport and store a bounded selection sufficient to assess
  the timing model: startup, periodic checks, discontinuities and detected
  inconsistencies. Record evidence loss explicitly. Selection cadence and
  uncertainty rules require specification and validation. Downstream analysis
  cannot reconstruct every discarded raw observation; insufficient alignment
  quality does not by itself prohibit recording.
- **Q90 — Unknown source loss:** Assign source sequences before software
  queues, so subsequent software drops produce exact gaps. Unknown FIFO loss
  ends the old source-sequence continuity segment; recovery establishes a new
  sequence origin and anchor rather than inventing a missing-sample count.
  Clock continuity is separate: FIFO recovery does not itself assert a sensor
  or node clock reset. Exact segment/epoch encoding remains open.
- **Q91 — Stored companion evidence streams:** Register one explicitly defined
  companion timing-evidence stream per participating node before recording,
  separate from its six-axis sample stream. Link evidence to sample sequences
  and source continuity segments, retaining sensor/node/master clock-domain
  identities. This adds an evidence schema, not another configured logical
  sensor, and does not repurpose reserved BDQ observation fields. Account for
  companion streams in the recording stream budget.
- **Q92 — Unknown uncertainty:** Explicitly represent unknown alignment
  uncertainty when no defensible finite bound exists. Retain raw evidence and
  native sample timing, but omit unsupported bounded mapping observations.
  Downstream estimates must be distinguishable from established bounds.
- **Q93 — FIFO servicing:** Use watermark-triggered SPI burst reads with DMA
  and bounded burst buffers; decode outside interrupt handlers. Include bounded
  fallback status checks for missed interrupts and serialize register/config
  access with acquisition. Watermark, burst limits, deadlines and any sensor
  SPI clock change remain to be specified and validated.
- **Q94 — Sensor SPI target:** Target 4 MHz for FIFO acquisition and retain
  1 MHz for initial register bring-up. Electrical timing and reliable burst
  operation require qualification. This target does not change sample rate or
  FIFO capacity and is not evidence of measured board-level operation.
- **Q95 — Epoch reuse and stale-data fence:** Never reuse an eight-bit stream
  epoch within a recording. Advance it for acquisition restarts and unknown
  FIFO-loss recovery; exhaustion excludes the endpoint for the remainder.
  Before reuse across recordings, confirm the old producer is stopped and
  clear or retire stale data throughout node, master and logger transfers.
  A node without an established fence remains unavailable. An anchor alone is
  not a fence across different CAN identifiers. Exact fencing remains open;
  this does not impose a lifetime limit of 256 segments per node boot.
- **Q96 — Persisted source segment identity:** Add a schema-defined source
  continuity segment ID to every new LSM BDQ sample record, leaving the common
  prefix intact. Timing evidence refers to that ID and sample sequence, so
  evidence loss cannot make sample segment identity ambiguous. Define the new
  record schema and corresponding analysis support. Source segments,
  timing-model changes and actual clock resets remain separate concepts.
- **Q97 — Preparation authority:** Establish recording membership and freeze
  the participant endpoint mask before preparation sample collection. The
  recording's explicit acquisition authorization and renewable lease cover
  preparation as well as recording; preparation is not an unleased mode.
  A later explicit start marks the transition to recorded samples. Cancellation
  stops preparation acquisition and explicitly releases membership through a
  defined cleanup sequence. Exact operations remain to be specified.
- **Q98 — Initial acquisition CAN link:** Target 1 Mbit/s arbitration and
  4 Mbit/s data for the initial four-IMU acquisition configuration, subject to
  physical qualification and complete admission calculations against the
  existing 70% conservative utilization target. Compact sample traffic alone
  is approximately 52.3% under the current model, not a complete admission
  result. Retain the slower discovery/control bring-up profile; do not admit
  sample configurations exceeding the active link budget or silently reduce
  sensor rates.
- **Q99 — IMU interrupt allocation:** Route acceleration data-ready to INT1
  for clean hardware timing capture and FIFO watermark to INT2 for servicing.
  Gyro values remain paired by validated FIFO slot identity, without separately
  captured gyro data-ready times; timing quality must reflect this limitation.
  Do not OR watermark onto the acceleration capture signal.
- **Q100 — Acquisition clocks:** Use nominal 1 MHz free-running node and master
  acquisition clocks, hardware edge capture, and explicit extension of the
  16-bit timer into a 32-bit tick domain. Ordinary 65.536 ms hardware wraps and
  approximately 71.6 minute extended wraps are not resets. Detect and mark lost
  overflow/capture evidence rather than guessing. Keep the sensor's nominal
  25 us timestamp clock separately identified. This clock choice does not
  establish the Q72 uncertainty target.
- **Q101 — Sample timestamp convention:** A six-axis item's node-clock
  timestamp represents its associated acceleration output-ready instant,
  reconstructed where necessary. Mark modeled timestamps as estimated and
  retain supporting evidence. Sensor/filter delays remain separate; this
  convention does not assert simultaneous acceleration/gyro measurement.
- **Q102 — Initial FIFO service requirements:** Watermark 96 FIFO words;
  bounded DMA bursts of up to 96 words; fallback status checks at least every
  5 ms; threshold crossing to first FIFO word freed at most 10 ms. Repeat
  draining until below watermark, with at most 1 ms between successive drain
  bursts. These are requirements to validate, not measured capabilities. Final
  proof includes maximum sample-rate variation, status reads, DMA scheduling,
  decoding and interrupt load; unmet requirements require design review before
  readiness is claimed.
- **Q103 — Initial synchronization/evidence cadence:** Target 10 Hz hardware
  SYNC and 10 Hz selected sample-timing evidence snapshots per node, plus
  required boundary/inconsistency evidence. Retain existing per-edge SYNC
  captures separately. Budget actual snapshot message sizes rather than
  assuming one frame each. Cadence requires validation and does not establish
  Q72; unknown or degraded alignment remains recordable under Q80/Q92.
- **Q104 — Acquisition recording identity:** Use a new nonzero 64-bit
  acquisition recording ID shared by participating nodes, unique within the
  logger control session. Bind each node's authorization to node boot, control
  session, recording ID and frozen participant mask. Command operation numbers
  remain separate. Store the association with the existing textual BDQ
  recording_id without changing that field's interface.
- **Q105 — Start boundary:** An explicit START independently selects the first
  recorded sample on each prepared node. On acceptance, discard remaining
  preparation samples; the first subsequent complete validated FIFO slot is
  sequence zero of a fresh stream epoch. Its anchor precedes master acceptance
  of its sample data. Keep the existing lease, sensing engines, clocks and
  renewal history running. Return the actual boundary to distinguish confirmed
  participation from uncertain command outcome. First samples need not be
  simultaneous across nodes.
- **Q106 — Master restart containment:** A confirmed master boot-identity
  change excludes all remote CAN participants for the remainder of the
  recording. Record the interruption, continue healthy local sensors, and
  reconcile CAN after recording ends. Do not automatically rebuild remote
  participation. Still-acquiring nodes stop under existing lease-expiry rules;
  the master never renews autonomously. One missed SPI response alone does not
  establish a master restart.
- **Q107 — Fragmented measurement SPI:** Refine Q78's larger-transfer direction
  into logical batches fragmented over short physical transactions, allowing
  ADC access between fragments. Initially require at most 100 us uninterrupted
  SPI mutex ownership per measurement transaction, including software overhead.
  Select fragment size, clock and pacing to meet this requirement and sustained
  throughput. Q77 acknowledgement remains complete-batch acceptance. Preserve
  bootstrap compatibility outside measurement mode. The limit is not measured
  performance; admission includes local ADC and remote acquisition traffic.
- **Q108 — Fresh renewal authorization:** Use fresh node-issued time-bounded
  challenges bound to the acquisition authorization and a deadline on the node
  clock. A valid logger response authorizes acquisition only through that
  pre-established deadline, not a new full lease period starting on receipt.
  Duplicate or late responses cannot move that deadline forward. Define lease
  duration, cadence, challenge lifetime and messages separately. This avoids
  assuming accurate logger-to-node clock alignment for renewal freshness.
- **Q109 — Abandoned membership cleanup:** While idle after logger restart,
  inspect the abandoned recording identity, establish fresh authority under
  existing rules, verify acquisition stopped and lease expired, then explicitly
  release that observed old membership. Binding never implicitly clears the
  lock. Cleanup enables reconciliation and a new recording, not resumption of
  the abandoned recording.
- **Q110 — Initial buffer/service coverage:** Require 50 ms of node software
  sample-queue coverage for healthy CAN-output backlog, 100 ms of master
  retention without logger acceptance, and one second of logger remote-stream
  RAM coverage for SD-write stalls. Size actual representations for timing
  evidence, boundary bursts and in-flight reserve; allocate the complete budget
  before preparation. Include existing local-sensor buffers in admission.
  Node FIFO service still meets Q102 during CAN backlog. Longer SD stalls may
  cause explicit sample loss but must not block the dedicated lease-service
  task. Planning byte estimates are not final allocations or measured coverage.
- **Q111 — Terminal stop/cancel:** An accepted STOP permanently ends the node's
  acquisition authorization for that recording. Reject later renewals or START
  under that authorization and retain the final boundary/result for idempotent
  retries. Preparation cancellation is also terminal. Membership remains
  locked until explicit release. Starting again requires a new recording.
- **Q112 — Initial lease timing:** Authorization horizon one second from node
  challenge issuance; attempt renewal every 100 ms; challenge response deadline
  300 ms from issuance. Receipt time does not create a fresh full lease.
  Duplicates and late responses cannot extend the deadline. Invalidate at
  expiry and stop firmware acquisition within 10 ms. Previously agreed
  enabled-stopped sensing-engine behavior remains; collection stops. These
  are requirements to validate against the service envelope.
- **Q113 — Remote preparation deadlines:** Node native readiness within five
  seconds of preparation acceptance; logger remote-readiness wait at most ten
  seconds overall. Timed-out nodes are unavailable for that recording; healthy
  participants may proceed. Stop renewal and initiate terminal cancellation
  and cleanup. Late readiness cannot cause joining. These are remote deadlines,
  not bounds on filesystem operations; tight alignment is not an admission gate.
- **Q114 — Remote final drain:** Five-second deadline from the operator Stop
  request for remote tail collection. Send STOP promptly, collect final
  boundaries and drain accepted remote batches within this interval. At the
  deadline report missing tails/uncertain boundaries and stop waiting for
  remote completion. SD persistence/file finalization need separate failure
  handling; this is not a total file-close deadline.
- **Q115 — Measurement SPI physical target:** Target 8 MHz and 64 total wire
  bytes per physical measurement transaction, including headers and CRC.
  Nominal wire time is 64 us, leaving 36 us inside Q107 for software and CS
  handling. Fragment logical batches and release the bus between slots. This
  is separate from the 4 MHz sensor SPI target. Preserve 84-byte/4 MHz bootstrap
  exchanges. Board timing, overhead, rearming and sustained throughput require
  qualification; chip capability is not measured board performance.
- **Q116 — Measurement integrity:** Protect each physical slot and each complete
  logical batch with CRC-32/ISO-HDLC. Bind fragments and acknowledgements to
  immutable batch identity, length and fragment position, never mutable queue
  position. Publish to logger RAM only after complete validation; duplicate
  acknowledgement must not duplicate insertion. Exact fields/coverage remain
  wire-layout work.
- **Q117 — Per-node fairness:** Reserve sample-retention capacity and bounded
  service opportunities per node. Use per-node queues and round-robin fragment
  service for initial equal-rate IMUs alongside Q84 protected traffic. Size
  reservations from admitted rates and Q110 coverage. Interleaved control does
  not mutate the selected sample batch.
- **Q118 — Confirmed writer failure:** A confirmed unrecoverable writer failure
  stops the entire recording, including local and remote acquisition. Report
  storage failure, request remote STOP, cease lease renewal, and preserve
  recoverable complete chunks. Claim clean finalization only if successful.
  This changes the current writer-failure behavior. A still-outstanding slow
  write is distinct; exceeding one-second buffer coverage alone is not proof
  of permanent failure.
- **Q119 — Same-boot measurement recovery:** Permit up to 300 ms for SPI
  measurement resynchronization while recording/batch/deduplication state stays
  trustworthy. Require matching master boot and acquisition recording identity
  before resumed acceptance. Preserve accepted batches and immutable pending
  transfers. Deadline failure or untrustworthy retained state excludes remote
  participants for the remainder, stops renewal, and leaves healthy local
  recording running. Loss beyond coverage is explicit. Confirmed master reboot
  follows Q106 immediately.
- **Q120 — Unresponsive storage:** An SD operation outstanding for five seconds
  triggers acquisition shutdown and visible Storage unresponsive state. Isolate
  recording I/O behind one storage worker; monitoring and Stop handling remain
  outside it. Stop acquisition without waiting for blocked I/O. Do not forcibly
  kill the worker, concurrently close its file or unmount beneath it. Report
  finalization unsuccessful or pending, never falsely clean. One-second buffer
  coverage is not this failure threshold.
- **Q121 — Post-failure recording:** Require explicit operator start only after
  outstanding I/O finishes and storage passes a health check. Never resume the
  failed recording automatically or reuse its file as uninterrupted recording.
  New recording remains unavailable while old operations are outstanding.
- **Q122 — Bounded measurement batches:** Limit logical sample/evidence batches
  to 1 KiB and at most one unacknowledged batch per node. Keep the selected
  batch immutable until acknowledgement, permit control/other-node fragments
  between its fragments, and preallocate assembly storage. Other queue retention
  follows Q110/Q117.
- **Q123 — Initial LSM BDQ record:** Use a new 28-byte record: unchanged BDQ
  prefix at bytes 0-11; uint32 source-continuity segment ID at 12-15; six raw
  int16 axes, acceleration then gyro, at 16-27. Segment IDs are nonzero and
  never reused within that sample stream in the recording. Evidence identifies
  sample stream, segment and sequence. Mark reconstructed ticks as estimated.
  Existing BMI270 records retain their format.
- **Q124 — Compact reception forwarding:** The master forwards compact CAN
  reception records retaining identifier, length, payload, master receive tick
  and reception ordering. Preserve master stream-acceptance checks; construct
  final 28-byte BDQ sample records in the logger. Do not expand per-sample BDQ
  prefixes on the SPI link.
- **Q125 — Bound measurement context:** Negotiate a fresh 64-bit context ID
  bound to full master boot, logger control session, acquisition recording ID
  and protocol version. Every fragment carries context, batch identity, node,
  position, length and CRC; reject unknown/stale contexts. Preserve context
  through trustworthy same-boot resynchronization and retire at recording end.
  Compact context references do not replace full identity checks at negotiation
  and recovery.
- **Q126 — Partial logical batches:** Stop normal sample-batch filling once
  the oldest received packet has waited 20 ms. Full batches become eligible
  immediately; startup, stop and discontinuity boundaries also trigger partial
  batches. Control/timing evidence does not wait for normal sample filling.
  Delivery still obeys scheduling and retention requirements; 20 ms is not an
  end-to-end delivery guarantee.
- **Q127 — Acquisition runtime ownership:** Treat defined PREPARE/STOP FIFO,
  interrupt-routing and sensor-timestamp changes as verified acquisition-runtime
  transitions, preserving applied configuration revision and advancing state
  epoch. Desired profile settings stay locked. Publish phase-appropriate current
  register proof and separate preparation/active-readiness checks; retain stopped
  reconciliation for stopped configuration. Historical stopped proof alone is
  insufficient. This explicitly extends stopped-baseline register ownership,
  without authorizing recording-time profile edits.
- **Q128 — Causal master/logger bridge:** Add a 10 Hz exchange with a fresh
  token: logger time before request, master clock sampled after request
  validation, logger time after matching validated response. Persist token,
  raw master tick and logger interval. Preloaded responses/old receive ticks
  cannot inherit the bracket. Bounds can exceed 10 us; absolute logger mapping
  is separate from the inter-node target.
- **Q129 — Companion prefix clock:** Use logger monotonic time at evidence
  record creation in the companion BDQ prefix. Explicitly label this observation
  creation time, not sample time. Payload fields separately identify raw sensor,
  node and master clocks and validity. Companion event sequence is distinct
  from node evidence ordinal and linked sample sequence; unknown node-time
  association does not prevent evidence storage.
- **Q130 — Model applicability:** Each model revision declares its exact
  source-sequence applicability boundary. Match model, anchor and source/clock
  identities before accepting dependent samples. Retain definitions referenced
  by queued data; arrival recency is not model selection. Ordinary model
  revisions do not reset source sequence, stream epoch or clocks. Record a
  timing boundary where continuity is not established.
- **Q131 — Native recovery limits:** FIFO-overrun or native sample/capture
  association recovery has a 100 ms deadline and at most three attempts in any
  rolling second. Timeout or another required attempt beyond that limit excludes
  the endpoint for the remaining recording. Healthy independent participants
  continue only with verified shared-resource health. Ordinary software queue
  loss and degraded inter-node alignment do not consume these attempts.
- **Q132 — Essential versus periodic metadata:** Missing source/clock/model
  boundaries prevent acceptance of dependent samples. Protect essential
  interpretation metadata and referenced definitions; inability to preserve
  essential state in bounded storage excludes the endpoint. Periodic snapshot
  loss instead reports an evidence gap and unknown/degraded alignment while
  samples with trustworthy native timing continue.
- **Q133 — Protected authorization exchange:** Add one bounded protected
  authorization/urgent-STOP exchange slot per node alongside the unchanged
  ordinary Q70 lane. Renewals use their authorization sequence, not ordinary
  mutation high-water. STOP cancels pending preparation through the single
  hardware owner without concurrent register writes. This explicitly extends
  the earlier one-exchange arrangement so pending work cannot block leases.
- **Q134 — Coalesced known queue loss:** Aggregate repeated known software
  queue-drop reports, limiting additional loss-triggered anchors/reports to
  10 Hz per node. Preserve sample gap flags and exact counters, baseline anchors
  and model updates. Require a fresh anchor for ambiguous sequence extension.
  This refines the earlier immediate-per-loss rule to avoid congestion storms.
  Essential source/clock/model boundaries still precede dependent samples;
  unknown FIFO loss retains its separate recovery rules.
- **Q135 — Companion schema:** Adopt the review draft's fixed 192-byte companion
  record with snapshot/model/SYNC/host-bridge/boundary/loss kinds, logger-time
  prefix, explicit validity and separately identified raw clocks. Encode wider
  quantities through declared uint32 low/high channels. Include actual traffic
  and RAM in admission. Field layout is in section 6 of
  [the acquisition contract](CAN-FD_Acquisition_Transport_Contract.md).
- **Q136 — Local model cadence/validity:** Refresh local sample-to-node models
  at 10 Hz; limit applicability to 500 samples or 150 ms from the anchor,
  whichever comes first. Apply limits to acquisition position, not delivery
  time. Unknown uncertainty alone does not invalidate established native
  association. Samples beyond every valid model wait for fresh association
  under bounded recovery. These are initial requirements to validate.
- **Q137 — Shared-SPI admission:** Require at most 85% steady scheduling
  occupancy and at least 1.25 times admitted sample-ingress drain capacity while
  mandatory ADC/control/timing traffic remains active. Include qualified
  software, arbitration, CS and non-overlapped rearming costs, and prove queue
  coverage against bursts/service pauses. Apply the stricter test; explicit
  capacity diagnostics replace unsupported combinations, never silent rate
  reduction. These are qualification requirements, not universal rate support.
- **Q138 — Measurement rearming:** Target master rearm within 25 us of CS
  release and require at least 25 us inactive master CS between measurement
  transactions. Release the SPI mutex during this gap; allow ADC work and count
  non-overlapped gaps in admission. Existing fixed-length transport needs
  changes; failure to qualify requires protocol/configuration review.
- **Q139 — Acquisition control layouts:** Adopt section 3.1 of the acquisition
  contract: reserved-range opcodes, 112-byte staged PREPARE request, 128-byte
  acquisition snapshot, existing common record/paging interfaces, initial
  challenge after staging, actual START boundary, known-empty versus unknown
  final state, explicit membership release and old-data fence. Mode handover
  and final registry/error details remain separate review work.
- **Q140 — Read-only mode recovery:** Accept a legacy-format MODE_INFO query
  while measurement mode is active. Return observed identities/mode with a
  fresh echoed nonce and validated request/fetch response; initially preloaded
  measurement data is not the query result. Inspection cannot clear context,
  renew or authorize takeover. A restarted logger verifies stopped/expired
  nodes and explicitly cleans up before new recording. Entry/exit handshakes
  have a one-second total deadline that retries cannot extend. Ambiguous entry
  leaves acquisition unavailable.
- **Q141 — Evidence-before-data persistence:** Append complete essential
  source/clock/model evidence chunks before dependent sample chunks, preserving
  this order through the storage worker and valid-prefix recovery. This does
  not require a physical SD flush after every evidence record. Periodic
  diagnostic snapshots retain the separate loss-tolerant policy.
- **Q142 — Packet layout package:** Adopt acquisition-contract sections 2, 4
  and 5: 20-byte measurement header, 40-byte fragment, CRC, scoped immutable
  identities and acknowledgement/error rules; compact reception objects;
  snapshot/model/boundary bodies and registries. Preserve existing control
  values and reserved-zero rules. Final consistency review and shared-
  understanding confirmation remain before implementation.
- **Q143 — Complete companion persistence:** Extend the new companion schema
  from 192 to 224 bytes, preserving offsets 0-191 and appending boundary tick,
  recovery duration, original event kind/presence and complete flag masks.
  Recalculate evidence RAM/storage costs. LSM samples remain 28 bytes. This
  explicitly supersedes Q135's size to fix the reviewed mapping gap.
- **Q144 — Restart cleanup transport:** Permit strictly allowlisted legacy
  administrative exchanges while an old measurement context is retained:
  inspection, then fresh binding/fencing/membership release after verified
  stopped acquisition and expired/invalid authorization. Preserve boot/session/
  challenge checks. No APPLY/PREPARE/START/RENEW on this cleanup route. Retire
  the context only after explicit fences; no automatic old-record resumption.
- **Q145 — Explicit protected fragment classes:** Add physical kinds 12 and 13
  for authorization and master-local evidence, respectively, with independent
  assembly/acknowledgement state and unchanged header size. Ordinary transfers
  cannot supersede authorization replies; local observations are not invented
  CAN receptions. This extends Q142's registry explicitly.
- **Q146 — Bounded emission:** Adopt acquisition-contract section 9.4 budgets:
  eight unsolicited essential CAN frames per native recovery attempt;
  coalesced loss cycles at most 10 Hz/node with one report plus one anchor;
  authorization requests 20/s/node with burst two and one response per request;
  urgent STOP up to three identical attempts within 300 ms, preempting renewal;
  ordinary diagnostics four requests/s globally, burst four, retries included;
  empty polls 50/s/node, burst one. No catch-up traffic beyond these budgets.
  Discovery stays idle-only; insufficient essential capacity follows Q132.
  Complete scheduling qualification remains required.
- **Q147 — Shared understanding confirmed:** The user confirmed the combined
  design and closed the acquisition/transport interview on 4 November 2026.
  Implementation and physical qualification remain separate. The subsequent
  to-tickets request authorizes drafting; tracker publication follows the
  repository preview/write rules. Existing bench deferrals remain in force.

Operator-reported functional happy-path evidence remains distinct from physical
qualification. CAN disconnect/reconnect, CCS halt/resume and node/master reset
fault tests remain deferred until a practical harness is available. No result
is claimed for these tests, broader fault tests, physical SPI/reset/apply timing,
multi-node load or stack-watermark qualification.

## 14. Streaming and recovery rules

- CAN automatic retransmission is enabled.
- Streaming data has no application-level retransmission. Late samples are less
  useful than explicit loss evidence, and retry storms must not consume the bus.
- Control and configuration transactions may be retried with the same
  transaction and generation.
- Each transmitter preserves order within an identifier. Receivers must not
  assume ordering between different identifiers beyond CAN arbitration.
- A node entering bus-off stops acquisition transmission, records a continuity
  break, performs bounded controller recovery and announces again. Recovery
  policy and counters are reported in status.
- Software sample queue overflow rejects the newest incoming complete batch
  (Q76), never a partial batch. Mark the loss before the next subsequently
  accepted sample, without attributing that future gap to older queued samples.
  Hardware FIFO overwrite and recovery follow Q83 separately.
- Master and node queues expose capacity, current depth, high-water and exact
  drop counters through diagnostics.
- The master must retain the CAN identifier, payload length, payload, reception
  ordering and a master receive timestamp until the logger-side SPI data-plane
  contract defines its final decoded representation.

## 15. Preliminary utilization model

The normal IMU frame carries five 12-byte samples and the four-byte compact
header. The estimates below model a standard-ID 64-byte FD+BRS frame as 30
nominal-rate and 550 data-rate bit times before variable stuffing. The
conservative column allows 33 nominal-rate and 653 data-rate bit times. It is a
planning bound, not a substitute for controller traces on the real harness.

Four nodes produce `4 * ODR / 5` normal IMU frames per second:

| Link profile | Four at 3.2 kHz, base / conservative | Four at 6.4 kHz, base / conservative |
|---|---:|---:|
| 500 kbit/s / 2 Mbit/s | 85.8% / 100.5% | 171.5% / 201.0% |
| 1 Mbit/s / 4 Mbit/s | 42.9% / 50.2% | 85.8% / 100.5% |
| 1 Mbit/s / 5 Mbit/s | 35.8% / 41.9% | 71.7% / 83.8% |

At the LSM6DSO32X nominal rates commonly described as approximately 3.33 and
6.67 kHz, the corresponding figures are:

| Link profile | Four at 3.33 kHz, base / conservative | Four at 6.67 kHz, base / conservative |
|---|---:|---:|
| 500 kbit/s / 2 Mbit/s | 89.3% / 104.7% | 178.7% / 209.3% |
| 1 Mbit/s / 4 Mbit/s | 44.7% / 52.3% | 89.3% / 104.7% |
| 1 Mbit/s / 5 Mbit/s | 37.3% / 43.6% | 74.7% / 87.3% |

Consequences:

- 500 kbit/s / 2 Mbit/s is a bring-up profile, not a four-IMU data profile.
- 1 Mbit/s / 4 Mbit/s has useful margin for four approximately 3.2/3.33 kHz
  raw six-axis streams.
- Four approximately 6.4/6.67 kHz streams do not have acceptable worst-case
  margin at 4 Mbit/s. Even 5 Mbit/s exceeds the initial 70% conservative target.
  Supporting that combination would require measured acceptance of lower
  margin, fewer simultaneous high-rate nodes, a more efficient encoding, or a
  reduced ODR. It must not be advertised by version 1 without further work.
- Control, status, anchors, synchronization and minor sensors still need to be
  added to the final admission calculation. A minimum 20% production reserve is
  desirable after measured stuffing and retry behavior are included.

## 16. First implementation slice

The first physical-network slice implements only:

1. the `BRINGUP_500K_2M` link profile;
2. `DISCOVERY_REQUEST` and `NODE_ANNOUNCE`;
3. one-second `NODE_STATUS` frames;
4. master RX accounting and a bounded four-address inventory; and
5. debugger-visible duplicate, stale, malformed, unsupported-version and queue
   diagnostics.

No sensor acquisition, stream data, or branch-power automation is required to
prove this slice. The implemented follow-on bootstrap slice transfers the
master's bounded inventory to the logger as a generation-consistent four-page
snapshot; see `CAN-FD_Master_SPI_Protocol.md`. The master buck converter must
power the master CAN transceiver, while both protected trunk branches may
remain disabled if the test node is independently powered.

## 17. Acceptance criteria

Before extending the protocol beyond the first slice:

- portable codecs have golden-vector and malformed-length/version tests;
- the master discovers each address and retains UID, firmware, capabilities,
  hardware type and boot identity;
- repeated nonce-based discovery exposes two different UIDs using one address
  as a duplicate installation;
- node unplug, reset and reconnect produce stale, boot-change and restored
  states without resetting the logger or master;
- unknown messages and incompatible versions are counted without disturbing
  valid traffic;
- CAN error-passive and bus-off recovery are exercised deliberately;
- measured frame timing agrees with the utilization model; and
- the physical test runs for at least ten minutes with no unexplained malformed
  frames, queue loss or controller recovery.

## 18. Deferred decisions

- final analogue and external-I2C record formats and rates;
- exact configuration request/result bodies and capability bits;
- native timer frequencies and the final SYNC cadence;
- master-to-logger flow-control and sample-transfer messages;
- queue sizes and the maximum tolerated logger service pause;
- whether a production 5 Mbit/s profile is accepted on the complete harness;
- whether any high-rate compression is sufficiently simple, deterministic and
  loss-observable to justify inclusion; and
- firmware update over CAN.

## 19. References

- Bosch, *CAN FD Protocol*, ISO 11898-1:2015 overview and technical papers:
  <https://www.bosch-semiconductors.com/products/ip-modules/can-protocols/can-fd/>
- STMicroelectronics, *LSM6DSO32X datasheet*:
  <https://www.st.com/resource/en/datasheet/lsm6dso32x.pdf>
- STMicroelectronics, *AN5640: LSM6DSO32X always-on 3-axis accelerometer and
  3-axis gyroscope*:
  <https://www.st.com/resource/en/application_note/an5640-lsm6dso32x-alwayson-3axis-accelerometer-and-3axis-gyroscope-stmicroelectronics.pdf>
