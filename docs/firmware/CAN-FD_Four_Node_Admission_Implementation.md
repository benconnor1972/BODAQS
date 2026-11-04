# Four-node recording and resource admission (#173)

Software evidence, 5 November 2026. Based on #170 `f52e24a`, #171
`c2fdbbd`, and verified #172 `fd34b6f`; the acquisition/network contracts remain
authoritative. Physical qualification #175/#176 is deferred. No device was
probed or flashed.

## Recording ownership and startup barrier

`RemoteImuRecording` owns four independent participant state machines. Each has
its own stream, revisions/epochs, outcome correlation, producer gate, object
progress, terminal STOP, five-second tail and fence/release progress. The shared
measurement context exits only after all participants finish; one excluded peer
cannot stop healthy local acquisition or force healthy peers to relinquish leases.
Shared SYNC/bridge objects fan out once to each selected companion, preserving
partial fan-out progress across bounded backpressure. They remain shared
observations, not independent measurements.

All selected endpoint identities/configurations and explicit link capabilities
are checked before allocation. Allocate all remote queues/model/catalog buffers
while stopped, then the existing sole asynchronous storage owner allocates the
primary/native queues, catalog, descriptors, workspace/output and writes the
frozen candidate catalog. Only `StorageManager_recordingReady()` permits
`resourcesReady()` to create the control task/measurement context and enqueue
PREPARE. Storage failure never authorizes PREPARE. Remote workspace/output
allocation cannot silently halve its requested size. The catalog freezes admitted
candidates; final summaries preserve exclusion and admission reason/qualification.

PREPARE and START each have a ten-second gate; the START gate begins at its actual
request, so a ready wait cannot consume that deadline. STOP's original operator
time controls the tail deadline. Complete producer quiescence precedes final
loss evidence/fencing. Existing #171 management-loss and #172 terminal exclusion,
optional health observations, unavailable-context cleanup and binding semantics
are preserved. Context IDs mix fresh 64-bit entropy with full session and the
nonwrapping session-scoped recording allocation; recording/context ownership is
separate. Unknown physical alignment remains recordable.

## Explicit links and conditional scheduling admission

See [link profile implementation](CAN-FD_Link_Profile_Implementation.md). Both TI
builds preserve default `CAN_LINK_PROFILE=bringup` (500 kbit/s / 2 Mbit/s) and
explicit `CAN_LINK_PROFILE=acquisition` (1 Mbit/s / 4 Mbit/s). Runtime MCAN readback
must agree before application TX. Selected profiles advertise existing capability
bits 28/29; neither/both is unknown. Logger eligibility requires an observed
acquisition profile from both master and each node. Protocol compatibility and
an absent/silent node never establish link compatibility.

**Production has no qualified scheduling profile.** It reports an explicit
unqualified/unsupported admission before PREPARE, preserving healthy local
logging and all desired rates. `setAdmissionProfile` is a stopped-only seam for a
future qualified profile and deterministic host examples; no application startup
installs synthetic costs. Passing mathematical examples is not hardware support.

A profile must supply a finite maximum source ingress rate (at least nominal
3333/s), source/service blackout bounds, finite exceptional CAN/SPI burst/rate
bounds, independent drain service, and bounded whole-slot software/CS/arbitration/
non-overlapped rearm costs. The <=100 us mutex hold is checked separately from
whole-slot scheduling cost. ADC costs use actual configured continuous worker SPS,
actual board SPI Hz, an independently bounded attempt multiplier, three distinct
transaction costs, ten wire bytes per attempt, and bounded status/poll traffic.
Logger row cadence is not used as ADC conversion traffic. Unqualified oscillator,
attempt, polling or scheduler bounds cannot become a production qualification.
Nonfinite/negative costs and overflowing coverage inputs fail closed.

The conservative traffic inventory is explicit in `ImuAdmission.cpp`:

| Class | Conservative rate/cost |
|---|---|
| Sample CAN | maximum native samples/s / five |
| Authorization CAN | 40 frames/s/node, retries inside the bounded budget |
| Snapshot, node SYNC, model, anchor, status CAN | 41 frames/s/node |
| Master SYNC CAN | 10 frames/s globally, even for one node |
| Coalesced loss/recovery CAN | 20 + 24 frames/s/node |
| Optional ordinary diagnostics | four commands/s globally, request+reply; every OPEN, six READs, RELEASE and retry consumes that same bucket |
| Normal SPI auxiliary | 365 slots/s/node plus 150 global master-SYNC/bridge/retry slots |
| Loss/recovery SPI | 44 objects/s/node, conservatively five slots each |
| Empty polls and diagnostics SPI | 50 slots/s/node + 32 global slots/s |
| Samples SPI | 28 slots / 65 samples, plus three extra slots for each of 94 possible partial-head boundaries/s/node |
| Management ERROR observations | 80 report/retry slots/s/node for four stage/class lanes at 10 Hz |
| Exceptional traffic | independently bounded CAN frames and SPI slots, added to the same service envelope |

All CAN frames are charged at least 196.25 us at the acquisition profile. At
four exact-3333/s synthetic sources, CAN occupancy is 0.6249385 before exceptional
bursts. SPI sample demand is 6871.0154 slots/s and auxiliary demand 3042 slots/s.
At synthetic 64 us whole-slot cost this is 0.6344329846 occupancy before ADC.
Two independent exact-600-SPS/1-MHz ADC examples add 0.096, and are conditionally
admitted with a 14000-slot/s supplied drain bound; two 2000-SPS examples exceed
85% and reject. Separate tests reject insufficient drain, CAN overload, excessive
coverage, missing qualification, NaN, negative costs and UINT32_MAX bursts.
The examples declare exact independent clocks and zero additional software/poll
costs; they deliberately establish no real-board cost bound.

Enforce <=70% conservative CAN including exceptional one-second burst charge,
<=85% SPI including exceptional burst charge, and >=1.25 sample drain ratio with
mandatory ADC/control/time/evidence traffic still active inside the 85% service
envelope. Finite burst duration must also fit the declared stage blackout bounds.
Recovery remains bounded; these reservations do not promise losslessness during
arbitrary repeated controller faults or simultaneous essential exhaustion.

## Joint occupancy and actual allocation

The node TX queue is 64 actual 68-byte entries (4352 bytes), with eight protected
recovery slots. A healthy 50 ms blackout requires 34 nominal packets plus partial,
hardware/inflight and evidence reserve (46 conservatively charged). The actual
adapter test is lossless at 50 ms. Deliberate 110 ms overload still produces exact
loss counts and preserves older records/essential evidence.

The master's ingress is enlarged from 96 to 128 actual 92-byte entries per node.
Node backlog release is an additional arrival burst during a 100 ms master stall;
nominal joint demand is 116 entries including selected/inflight reserve. Each
selected immutable 1024-byte head is separately resident. Four ingress rings and
heads occupy 51200 bytes; complete bridge/control/timer/native ownership and the
2048-byte reserved stack are included in the rebuilt bank-0 map, not assumed free
bank-1 capacity. A full/pinned node cannot consume another node's ring/service.

The logger allocates 8192 sample entries/node, each **32 bytes**, including its
28-byte native sample and four-byte evidence dependency. Conservatively treating
all full node64/master128 records as sample arrivals, with selected13-packet head,
held consumer, 128 writer records and a one-second blackout, requires 4487 rows.
An 8192-entry power-of-two queue covers this; the former 4096 did not.

Likewise 512 actual 224-byte companion entries/node cover the conservative joint
502-event requirement: 160/s normal+fault+local reports (50 normal +44 native
loss/recovery +40 master management lanes +20 logger-local reports, rounded
upward), full upstream64+128, selected13,
held1, writer128 and protected8. The eight reserved essential slots remain
protected. At 524 periodic arrivals the independent pressure fixture reports
exactly 20 omitted events; essential exhaustion retains all 512 older records and
fails explicitly. Expanded samples keep exact bytes plus evidence serial after
model retirement, through SD chunk acknowledgement. The sample overload fixture
retains 8190 rows while more than 80 model generations retire, reports the exact
five dropped rows8190..8194, and resumes with explicit discontinuity flags.

Bulky immutable provenance/model/anchor buffers use the existing capability-aware
PSRAM-first allocator with explicit failure/cleanup. Atomic indices, gates and
synchronization owners remain in ordinary internal static state. No stream object
is copied into PSRAM. The A8 ELF verifies each stream's allocated buffer footprint
is 383616 bytes: sample262144 + evidence114688 + provenance3072 + models3200 +
anchors512. Four streams total **1534464 dynamic bytes**, leaving 562688 bytes of
a nominal 2 MiB PSRAM before other allocations. Allocation success, not that
subtraction, decides whether the actual configuration can proceed.

The A8 ELF has four participant owners2752 bytes, acquisition peer/mailbox/outcome/
transport state with configured4096-byte stack charged by `reservedBytes()`30900,
and CAN diagnostics10560. This records a remote/control accounting base of
**1578676 bytes**, mixing dynamic and already-static ownership. Do not add it to
the firmware static map as if it were all extra heap.

Storage's actual configured sizes are published independently by
`StorageManager_recordingAllocation()`: primary queue, exact workspace/output,
transient catalog/column payloads, metadata payload, static writer/schema/37
descriptors/marks/primary-owner/sink, and configured storage stack. On the A8 ELF
the listed storage static state is26032 bytes and stack reservation12288; add the
configuration-dependent primary/workspace/output/catalog/metadata sizes observed
at the barrier. These dynamic sizes depend on local schemas/rates and catalog
strings; no universal fixed maximum configuration is claimed. The report adds
these actual requested allocations to the remote/control accounting once.
Other local sensor queues are allocated by their real driver startup before the
barrier. Existing driver/rate checks and allocation failures remain binding.
Heap allocator/RTOS/filesystem overhead, internal heap fragmentation and actual
stack watermarks are not measured; the complete target static map and explicit
allocation results supplement these requested-size observations.

Metadata remains the established37-stream maximum: primary +32 logical sensors
(local and remote together) +four companions. No reduction of the32-logical-sensor
target and no promise that every maximum-rate driver combination fits.

## Validation and limits

- Complete firmware host target passes, including production logging/storage,
  acquisition, stream, native writer and independent BDQ reader fixtures.
- Common14 binaries, node adapter modes1..12, and master timing adapter pass.
  Four actual lifecycle peers run PREPARE/snapshot/START/renewal/STOP/tail/fence/
  release/context exit. Actual first/second-peer allocation failures occur before
  PREPARE and free prior allocations. A separate four-peer bus-off case keeps
  the three healthy peers recording/leased through the excluded peer's tail.
- #172 node/master reboot, lease expiry, lost transfer, same-boot recovery and
  explicit unavailable-context cleanup regressions remain passing.
- Full Python analysis suite:588 passed, one skipped; existing seven warnings.
- TI SDK2.11/Arm Clang5.1.1 acquisition builds: node flash41456/SRAM13169;
  master flash41352/bank0 SRAM62139, including reserved2048-byte stacks.
  Master bank1 remains unused; bank0 has3397 unallocated bytes.
- Both bring-up and acquisition target link selectors were built and portable
  timing/readback/failure/compatibility vectors pass. A8 explicit
  `bodaqs_s3_mini_n4r2`: staticRAM260460, flash2020553 bytes.

No physical FIFO/DRDY/SPI/DMA/SYNC timing, ODR/ADC oscillator tolerance, CAN
retransmission/error bound, measured shared-bus throughput, heap/stack watermark,
four-node load or 10 us alignment pass is asserted. Unknown qualified scheduling
costs deliberately keep production remote acquisition unavailable. #174 owns
integrated software acceptance; #175/#176 own deferred physical qualification.
