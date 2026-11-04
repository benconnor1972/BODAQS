# BODAQS logger-to-master SPI bootstrap protocol

Status: identity, status, and node-inventory exchange implemented  
Protocol version: 1  
Last updated: 3 November 2026

## Purpose

This protocol is the small bootstrap boundary between an A8 logger and the
optional CAN-FD master daughterboard. Version 1 currently supports bounded
presence, compatibility, identity, master-status probing, and transfer of the
master's four-address node inventory. It deliberately does not yet define
configuration exchange, sample transport, flow control, or CAN-FD framing;
those will be added only after their throughput and buffer contracts are
specified.

The logger is the SPI controller and the master is the SPI peripheral. A8 v1.0
has no usable master interrupt connection, so polling is the required baseline.
Later logger hardware may use an interrupt as a prompt, but correctness must
not depend on it.

## Electrical settings

- SPI mode 0
- most-significant bit first
- 4 MHz initial clock
- one chip-select-bounded transaction per fixed-size slot
- A8/RC3 logger chip select: GPIO 40
- A8 v1.0 interrupt: absent

These values are held in the logger board profile rather than in the user
configuration. The user chooses only whether the master is `off`, `auto`, or
`required`.

## Slot format

Every transaction transfers one 84-byte slot. Multibyte integers are unsigned
little-endian values.

| Offset | Size | Field |
|---:|---:|---|
| 0 | 4 | ASCII magic `BCM1` |
| 4 | 1 | protocol version, currently `1` |
| 5 | 1 | message type |
| 6 | 2 | flags, initially zero |
| 8 | 4 | request/response sequence |
| 12 | 2 | payload length, 0 to 64 |
| 14 | 2 | reserved, transmit as zero |
| 16 | 64 | payload, unused bytes transmitted as zero |
| 80 | 4 | CRC-32 of bytes 0 through 79 |

The CRC uses the reflected polynomial `0xEDB88320`, initial state
`0xFFFFFFFF`, and final inversion. It is the conventional CRC-32/ISO-HDLC
calculation used by the logger implementation.

## Transaction model

SPI is full duplex, so the response to a newly transmitted request will
usually not be available in that same transaction. The logger:

1. sends a request slot with a nonzero sequence;
2. accepts a matching response if the master already had one queued;
3. otherwise sends up to three `FetchResponse` slots; and
4. accepts only a valid-CRC response whose sequence matches the request.

The logger leaves at least 1 ms between every pair of master chip-select
assertions, including between one completed exchange and the next request. The
master treats chip-select release as the slot boundary: after RX DMA completes,
it waits for chip select to become inactive before rearming either DMA channel.
Both rules avoid beginning a new slot while the preceding transaction is still
being retired by the other processor.

The bounded exchange prevents an absent or faulty daughterboard from blocking
the logger. The logger probes at startup, when requested from the Health screen,
after logging ends, and periodically while idle. It does not poll the master
during a recording. SPI access is serialized with the A8 ADS1220 ADC traffic.

## Implemented messages

| Value | Name | Direction | Meaning |
|---:|---|---|---|
| `0x01` | `ProbeRequest` | logger to master | request identity and protocol range |
| `0x02` | `FetchResponse` | logger to master | clock out a pending response |
| `0x03` | `StatusRequest` | logger to master | request a runtime status snapshot |
| `0x04` | `DiscoveryRequest` | logger to master | request one node-inventory page |
| `0x81` | `IdentityResponse` | master to logger | identity response to a probe |
| `0x83` | `StatusResponse` | master to logger | runtime status snapshot |
| `0x84` | `DiscoveryResponse` | master to logger | one node-inventory page |
| `0xFF` | `ErrorResponse` | reserved | future structured error response |

The 20-byte `IdentityResponse` payload is:

| Offset | Size | Field |
|---:|---:|---|
| 0 | 4 | master firmware version, encoded by master firmware |
| 4 | 4 | capability bitset |
| 8 | 8 | hardware UID |
| 16 | 2 | minimum supported bootstrap protocol version |
| 18 | 2 | maximum supported bootstrap protocol version |

The logger considers the master compatible when the range includes protocol
version 1. The UID is diagnostic provenance, not configuration identity.

Capability bit 0 indicates support for `StatusRequest`, and bit 1 indicates
support for the four-page node inventory. The logger requests
status after each successful compatible identity probe. A failed status request
does not make an otherwise compatible master absent, but it is reported as a
separate diagnostic failure.

The 52-byte `StatusResponse` payload is:

| Offset | Size | Field |
|---:|---:|---|
| 0 | 2 | status schema version, currently `1` |
| 2 | 2 | state flags |
| 4 | 4 | uptime in milliseconds |
| 8 | 4 | reset cause |
| 12 | 4 | SPI slots received |
| 16 | 4 | malformed SPI slots |
| 20 | 4 | probe requests received |
| 24 | 4 | status requests received |
| 28 | 4 | SPI transport recoveries |
| 32 | 4 | CAN frames received |
| 36 | 4 | CAN frames transmitted |
| 40 | 4 | CAN error events |
| 44 | 2 | CAN receive-queue depth |
| 46 | 2 | CAN receive-queue high-water mark |
| 48 | 2 | SPI transmit-queue depth |
| 50 | 2 | SPI transmit-queue high-water mark |

Status flags currently assign bit 0 to buck enabled, bits 1 and 2 to front and
rear branch enabled, bits 3 and 4 to front and rear fault, bit 5 to CAN
initialized, bit 6 to CAN bus-off, and bit 7 to clock fault. Unimplemented CAN
and queue fields transmit as zero.

### Node-inventory snapshot

The master owns a fixed inventory for strap addresses 0 through 3. The logger
reads it as four independent pages after each successful compatible identity
probe. A `DiscoveryRequest` has this 8-byte payload:

| Offset | Size | Field |
|---:|---:|---|
| 0 | 1 | inventory schema version, currently `1` |
| 1 | 1 | requested node address, 0 through 3 |
| 2 | 2 | reserved, zero |
| 4 | 4 | expected generation; zero for the first page |

Each `DiscoveryResponse` occupies the complete 64-byte payload:

| Offset | Size | Field |
|---:|---:|---|
| 0 | 1 | inventory schema version, currently `1` |
| 1 | 1 | node address |
| 2 | 1 | page count, currently `4` |
| 3 | 1 | record flags |
| 4 | 4 | inventory generation |
| 8 | 1 | node hardware type |
| 9 | 1 | reserved, zero |
| 10 | 2 | endpoint mask |
| 12 | 4 | node firmware version |
| 16 | 4 | node capabilities |
| 20 | 8 | hardware UID |
| 28 | 8 | conflicting UID when a duplicate address is observed |
| 36 | 4 | boot ID |
| 40 | 4 | last-seen time in the master's uptime domain |
| 44 | 4 | node uptime |
| 48 | 4 | node status flags |
| 52 | 4 | node CAN RX frames |
| 56 | 4 | node CAN TX frames |
| 60 | 2 | node CAN error events |
| 62 | 2 | node transmit-queue high-water mark |

Record flag bit 0 means present, bit 1 stale, bit 2 duplicate address, and bit
3 that the status fields match the announced boot ID. Unsupported or absent
addresses still return a page, with the relevant fields zero.

The generation is nonzero and advances whenever an accepted announcement or
status changes the master inventory, or when an entry first becomes stale. The
logger adopts the first page's generation and requires all remaining pages to
match it. If it changes during the read, the logger retries the complete
snapshot up to two times. A failed refresh marks `inventory.valid` false but
does not discard the last coherent observations; losing or replacing the
master does clear them.

## Logger policy and diagnostics

`can_master_mode` has these values:

- `off`: do not probe or use the daughterboard;
- `auto`: probe when idle, but do not warn merely because no master is fitted;
- `required`: probe as above and show a prominent warning when it is not
  present and compatible.

An unavailable master never prevents otherwise valid local sensors from
logging. Remote sensors configured on CAN endpoints remain independently
excluded by the sensor-diagnostic model when their providers are absent.

The Web API reports state, compatibility, identity, probe counts, malformed
responses, transfer failures, detailed master status, the four inventory
records, and whether the board profile supplies an IRQ. A coherent inventory
snapshot is also translated into transport-independent CAN provider and
endpoint observations for logger configuration diagnostics. If a status or
inventory refresh fails after an earlier success, the last successful snapshot
and its timestamp remain available while its `valid` field becomes false.
The OLED Health screen gives a compact `M:` state and Enter performs a fresh
probe plus sensor discovery.

## Agreed configuration extension scope (3 November 2026)

The next control-plane contract will carry endpoint configuration requests and
effective-state readback end to end between the logger and node. It initially
supports the IMU endpoint and remains extensible to future endpoint schemas.
The agreed apply, adjustment, volatile-state and acquisition-control semantics
are recorded in section 13 of `CAN-FD_Network_Protocol.md`; section 13.9 provides
the consolidated review checkpoint and explicit deferrals.
The SPI extension must preserve operation and control-session identity and
transport coherent effective-state descriptors, including node boot identity
and applied revision. Its slot sequence and inventory generation do not replace
these end-to-end identities. Submission receipt and eventual node completion
are separate asynchronous responses; a bootstrap slot exchange must not block
on node configuration. Descriptor paging is bounded to 32 data bytes per page
and 512 bytes per descriptor, with one page requested at a time. Request pages
are staged without hardware effects; an explicit commit starts validation and
application only once the complete request is available. Immutable snapshots
and descriptor transfers have five-second bounds; transport steps allow one
second per attempt and at most three attempts. Node application has a
two-second limit; the logger's result wait is five seconds from commit send.
These are requirements pending implementation validation, not existing timing
guarantees. Per-endpoint descriptors determine eligibility; master receipt and
node-wide summary flags do not.

SPI control message values, layouts and correlation are defined by the agreed
node-control wire contract linked below. They remain unimplemented; agreement
does not enable the messages. IMU acquisition and sample transport follow in
separate implementation stages.

The pre-implementation interview additionally agreed typed end-to-end control
records, explicit schema versions, a capability-advertised control-information
exchange with fresh master boot identity, and bounded read-only inspection
without mutation authority. See section 13.10 of `CAN-FD_Network_Protocol.md`.
Preserve the existing bootstrap identity/status layouts. Physical IMU
configuration/readback is in scope for the first configuration implementation;
at least one concrete profile must therefore be specified before that work.

Q44-Q48 select a 52-byte common page record (28-byte identity/header plus
24-byte data area) with a 12-byte SPI routing/master-boot wrapper, fitting the
64-byte payload. Exact wrapper offsets are in the node-control wire contract. Effective
descriptors distinguish verified, unavailable and historical state; see section
13.11 of `CAN-FD_Network_Protocol.md` for stopped behavior and rejection rules.

Q49-Q53 additionally require immutable transfer metadata, conflicting-page
invalidation, duplicate-operation lookup before current-revision checks, and
retention of the latest operation's request/result until replacement or session
end. Older operations are superseded and never re-executed. Capabilities remain
independent of presence/health, and profile catalogs are bounded to 16 entries
per endpoint. See section 13.12 of `CAN-FD_Network_Protocol.md`.

The wire layouts are in
[CAN-FD_Node_Control_Contract.md](CAN-FD_Node_Control_Contract.md). Allocations,
requests, replies, descriptors and session rules are agreed through Q70 as of
4 November 2026. The user confirmed shared understanding and closed the
pre-implementation interview that day; section 12 contains its checkpoint.
No control extension is implemented. Q70 completes an unanswered CAN exchange
after at most three one-second application-request attempts with receipt state
5/reason 26, transport-outcome-uncertain, freeing its slot for later inspection.
This does not establish node rejection or cancel application.

## Deliberately unresolved

Before this protocol carries measurement data, specify and test:

- queue ownership and master-to-logger flow control;
- prioritization between samples, synchronization, configuration, and status;
- maximum logger service pause and required master buffer capacity;
- multi-slot messages and restart/resynchronization rules;
- integration of the agreed effective descriptors with recording metadata;
- native sample timestamps, source sequences, loss markers, and sync evidence;
- whether CRC-32 remains sufficient for end-to-end payload integrity; and
- optional interrupt acknowledgement and missed-interrupt behavior.

