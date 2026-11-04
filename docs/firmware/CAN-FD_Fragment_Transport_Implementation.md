# Fragmented measurement transport implementation (#167)

Implemented on 4 November 2026 against measurement-mode base `918fa87` and
[specification #164](https://github.com/benconnor1972/BODAQS/issues/164), with
storage integration merged before final verification. Binding wire definitions
remain in [the acquisition contract](CAN-FD_Acquisition_Transport_Contract.md),
sections 2, 4 and 9.3-9.4. This record reports software evidence.

Production master `bodaqs_master_service_process_transfer` now routes confirmed
64-byte measurement slots into bounded fragment assembly, immutable retention,
class-specific polling and complete-RAM ACK handling. The shared codec binds
context, object ID, node, class, direction and total in the logical ISO-HDLC
checksum. Physical CRC remains the accepted BM slot codec. It rejects mixed
identity/length, conflicting fragments, stale objects, invalid padding, invalid
logical CRC and unsupported schema. The last accepted identity/checksum and
idempotent ACK cache survive same-context SPI recovery. IDs fail closed at
exhaustion. Receiving a fragment never grants acquisition authorization.

Each node has one 1024-byte retention buffer shared between sample and node
evidence classes. It holds at most thirteen compact 76-byte reception records:
1008 logical bytes including header and checksum, transferred in 26 fragments.
A partial seals when serviced at its 20 ms fill deadline, including on ingress
before any later append. A full, selected or unacknowledged head is immutable;
backpressure is explicit and counted. Wildcard head selection rotates nodes.
Class changes and ordinal-high changes seal the old head instead of mixing it.
The production CAN ISR assigns the global reception ordinal before queueing,
including traffic subsequently rejected or lost; forwarded records preserve
that order, CAN identifier/payload and captured receive tick. The production
forwarder rejects duplicate/stale addresses and requires a retained same-boot,
same-epoch anchor and unambiguous sequence before compact IMU data acceptance.

Ordinary control and authorization/urgent STOP have independent assembly,
result retention, ACK caches and CAN exchanges. Their 64 wrapper/record bytes
remain unchanged, with four checksum bytes appended. Ordinary exchange retry,
result and uncertainty rules remain in the existing exchange module. In active
measurement mode ordinary CAN attempts use a global four/s, burst-four budget.
Protected attempts use twenty/s/node, burst two; STOP preempts renewal and has
three identical attempts at 100 ms intervals, uncertain at 300 ms. Every CAN
attempt consumes budget even if hardware enqueue fails. A protected STOP can
replace incomplete renewal assembly and a pending renewal, without changing
ordinary sequence state. Node authorization semantics belong to #168. Master
SYNC evidence uses a separate bounded class-5 buffer and declared event schema;
it is never represented as a fabricated CAN reception.

The master SysTick now advances in 1 ms increments so the 20 ms fill limit is
representable. LED heartbeat remains 500 ms, health checks 100 ms and discovery
retains its existing interval. Receive ticks currently represent captured
milliseconds multiplied by 1000; they are quantized to 1 ms. They do not provide
a qualified native capture clock or phase bound. #170 supplies native-clock
identity/extension and synchronization evidence.

Logger integration seams for #168/#169:

- Allocate `CanMasterManager::MeasurementTransport` in persistent bounded RAM,
  with its cost included in later admission. It owns independent class/node
  inboxes and ordinary/protected outboxes. Keep it across trustworthy same-boot
  SPI recovery; explicitly retire/reinitialize it after the context fence.
- Allocate command IDs through `nextMeasurementObjectId(class, node)`, retain
  the ID and exact bytes for retry, then `queueMeasurementControl(...)`.
  `serviceMeasurementTransport(...)` performs at most one physical slot per call,
  prioritizes protected outgoing traffic, and demultiplexes MISO by its own
  identity even during another lane's poll, outgoing fragment or ACK. Queued
  control transport expires at 300 ms without extending on identical retry;
  timeout/error is not a claim that the CAN operation did not execute.
- A return of 1 supplies a complete validated inbox. Consume/copy the whole
  object into the next bounded RAM owner before `releaseMeasurementObject`.
  The bank sends its ACK on subsequent service; that ACK means RAM acceptance,
  never SD persistence. Duplicates do not produce another insertion. Keep
  servicing each admitted node and protected lane; the helper has no task or
  hidden background loop. Head polls are capped at fifty/s/node, burst one.
- `queryMeasurementNodeState(...)` demonstrates the existing read through this
  link. The single-inbox/blocking convenience methods are for repeated service
  of one lane; interleaved acquisition uses the bank API above.
- Diagnostics at `can_fd_master.measurement` report accepted/duplicate objects,
  transport failures, submitted control, assembly bytes and last class/node/ID.
  Existing master SPI queue depth/high-water fields now include retained objects;
  master retention/drop/ACK counters are also inspectable in `BodaqsMasterService`.

Validation passed:

- Full common host suite with the new fragment/production-master tests: independent
  canonical CRC literal `0xf80a184b` (Python struct/zlib), out-of-order fragments,
  corrupt/mixed/conflicting/stale objects, incomplete rejection, duplicate RAM
  delivery suppression, lost/duplicate ACKs, pinned immutable heads, full
  thirteen-packet/26-fragment batches, 20 ms partials, round-robin fairness,
  backpressure, protected STOP retry/preemption, master-local evidence and
  same-boot/epoch anchor admission.
- `test_measurement_runtime.py` runs the production logger manager and master
  service over pipelined SPI: real existing node-state query, four alternating
  nodes with protected control in flight, complete delivery and RAM ACKs during
  interleaving, negotiation/recovery/exit, and diagnostics.
- Existing recording-handoff, recovery and runtime-mute production-manager
  regressions, plus storage-worker and logging-start integration regressions.
- Explicit MSPM0G3518 master TI build (SDK 2.11.00.07 / TI Arm Clang):
  FLASH 31,104 bytes; SRAM bank 0 14,089 bytes including reserved stack.
- Explicit A8 PlatformIO environment `bodaqs_s3_mini_n4r2` build:
  static RAM 217,140 bytes; flash 1,952,341 bytes.

No board was flashed. These checks do not qualify physical SPI/CS/DMA timing,
CAN bandwidth, sustained four-node admission, capture-clock precision, stack
watermarks or memory availability at runtime. #168 supplies leased membership,
terminal node STOP and lifecycle fencing; #169 supplies recording persistence;
#170 supplies native timing; #171/#172 supply loss/recovery containment;
#173 supplies aggregate resource admission. Physical #175/#176 remain deferred.
