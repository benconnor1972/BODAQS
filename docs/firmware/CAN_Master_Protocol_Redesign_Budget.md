# Protocol redesign: first budget and architectural options

13 November 2026. Analytical design aid, not a service guarantee or selected wire
format. The accepted product/quality decisions are in
[the interview](CAN_Master_Protocol_Redesign_Interview.md); architectural direction
is recorded in [ADR0005](../adr/0005-decouple-sensor-transport-progress-and-verification.md).
`Protocol_Redesign_Budget.py` reproduces the geometry calculations without external
dependencies. All full-block, header and efficiency assumptions are explicit.

## Offered load and measured anchors

Four sources at3333six-axis readings/s produce13,332readings/s or159,984raw axis
bytes/s; two sources produce half. Local two-channel500Hz primary records add
about10kB/s in today's20-byte rows, not simply2kB/s of analog values. Timing,
configuration, queue/ACK/control, chunks, gaps and retries are additional.

Existing CAN sample traffic is already compact: five12-byte readings plus4header
bytes in a64-byte CAN-FD payload. The repository's planning model at1M/4M yields
about44.7%base/52.3%conservative CAN load for four IMUs' samples alone. That is
not a verified universal CAN utilization bound; mandatory other traffic and real
retry/bit-stuffing behavior remain to be budgeted. Repacking CAN into fewer SPI
bytes does not reduce the CAN wire load. See `CAN-FD_Network_Protocol.md`.

Measured current256-byte master outer request service is roughly0.39-0.42ms in
frozen observations. Decode, dispatch/hints and encode each contribute substantial
wall time. Logger exchange observations are roughly0.42-0.45ms, compared with
the nominal16MHz uninterrupted wire floor of0.128ms. These populations and intervals
overlap and must not be added or treated as pure CPU/bus utilization. Larger-frame
CRC/copy/HAL costs cannot be inferred by simply reusing those256-byte means.

r23 measured19.10ms sealed-head-to-ACK and14.75ms before all fragments were first
prepared; ordinary progress involved many empty/repeated replies. The main SPI
service currently holds a ready response until a CS retirement boundary. Useful
progress/publication therefore needs redesign alongside byte packing.

## Geometry examples at four full-rate sources

The following counts exclude all non-sample work, empty/repeated replies and
retries. They are logical fragment requirements, not predictions of live slots.
All examples retain40bytes of physical overhead for comparison; the actual new
format might differ. The compact examples assume20bytes of shared logical
header/checksum overhead; fitting the selected semantics must still be shown.

| Example | Logical block | Readings | Physical bytes | Fragments/block | Unique sample turns/s | Nominal wire/block |
|---|---:|---:|---:|---:|---:|---:|
| Existing reception wrappers |1008B|65|256|5|1025.5|640us|
| Group original compact CAN payloads |852B|65|256|4|820.4|512us|
| Same compact CAN payload group |852B|65|512|2|410.2|512us|
| Repack axes into sensor block |860B|70|256|4|761.8|512us|
| Same sensor block |860B|70|512|2|380.9|512us|
| Same sensor block, larger comparison only |860B|70|1024|1|190.5|512us|

The first compact option removes repeated gateway reception wrappers while
retaining the four-byte CAN sample headers and original axis bytes. It may avoid
some master decoding/repacking work and preserve useful existing analysis logic.
The denser option additionally strips/amortizes those packet headers and must
preserve full sequence/epoch/gap semantics. These are alternatives to compare,
not a decision that maximal packing is always fastest.

For these illustrative blocks, doubling physical size256to512halves sample-turn
demand without increasing their total wire time. It doubles **per-transfer** wire
blocking128to256us. It is beneficial only to the extent the larger transfer's
actual service cost grows by less than two, and the ADC deadlines still hold.
Larger1024frames show arithmetic potential but their512us wire blocking is a
larger shared-bus trade-off; they are not proposed as the first experiment.

As an explicit sensitivity, if new sample fragments occupy70%of transfers,
the four-source sensor-block examples require about1088totalturns/s at256B or
544at512B. The70%is an assumption, not evidence that the scheduler achieves it.
The remaining30%must actually cover metadata/control/empty/retry work; neither
percentage is a CPU or bus-occupancy claim. Two-source demands are half.

## Self-contained units after Q19

Q19 accepts fitting each ordinary sample unit in one physical transfer. The
fragmented compact examples above remain comparison arithmetic, not the selected
normal data path. An illustrative 24-byte total unit metadata/checksum budget, in
addition to the assumed 40-byte physical overhead, leaves room for whole existing
64-byte CAN payloads:

| Physical frame | CAN payloads/unit | Readings/unit | Source collection time at3333/s | Four-source sample turns/s |
|---|---:|---:|---:|---:|
|256B|3|15|4.50ms|888.8|
|512B|7|35|10.50ms|380.9|

These assume full units and exclude control, metadata, empty/repeated transfers
and repairs. Neither prefix size nor resulting packing is selected or proven to
cover all identity/ACK semantics. Q25's master-origin checksum must fit within
this illustrative total or the geometry must be recalculated; it is not free
additional capacity. Collection time is not acquisition-to-RAM
latency or the maximum gap after loss. Smaller units allow finer repair and loss
accounting; selective recovery must still meet the provisional delivery targets.
Two/four 512-byte units per source across four sources would occupy 4/8KiB for
the unit buffers alone. This replaces neither the full memory budget nor the
separate 500ms recovery-backlog requirement.

In particular, about80kB of raw axes for a four-source 500ms pause exceeds the
currently reported unused62,280bytes in master BANK1 even before overhead and
other reserves. Do not promise lossless500ms operation with the SPI path blocked:
the recovery target needs a stage-specific buffer/service budget, and may be
infeasible on that fault path. Logger-side storage backlog can use different
memory while SPI continues; the two cases must not be conflated.

## ADC, memory and persistence constraints

Two500Hzchannels, one per ADS1220, select1000SPS workers that continuously convert;
they do not issue exactly500conversions/s. The measured sustained one-IMU mixed
case ran about707conversions/s per ADC. Summed observed setup/read ownership
phases imply roughly23.5-23.9%shared-bus time, compared with11.3%clock floor.
These elapsed phases include HAL/preemption and are observations, not certified
worst-case exclusions. Row reuse was about0.37%, consistent with the newly accepted
provisional99.5%freshness target in that one-IMU case, not qualification for2/4IMUs.
No replacement for the old100us blocking target has been qualified.512B therefore
needs real mixed-load freshness/age checks, not wire arithmetic alone.

The current logger uses Arduino `transferBytes`, busy-waiting through64-byte FIFO
chunks. It is not already a fully asynchronous DMA transport. The TI byte-DMA
transfer count accepts0..65535, but current buffers, exact256-byte codec offsets,
initial-byte priming, CS retirement and rearm assumptions all need explicit review
before resizing. DMA count capacity alone is not physical support/qualification.

r23 master allocation has887unused bytes in BANK0 and62,280in BANK1. Two/four1KiB
immutable blocks per source occupy8/16KiB total; state, RX/TX/queue copies, control
reserve and stack are extra. New state must be deliberately placed; the maps do
not establish runtime stack margin. There is enough apparent BANK1 allocation
space to investigate a bounded window, not a proof of its complete budget.

Today's compact packet recording uses100bytes for five readings:266.64kB/s of
sample records at full four-source rate, before metadata/local rows/chunks. Raw
axes need160kB/s. The illustrative compact CAN payload groups need174.75kB/s of
logical blocks; repacked sensor blocks163.79kB/s. These are not finished BDQ
record layouts; container prefixes, partial-block handling and metadata remain
additional. Reducing both stored bytes and per-packet queue/formatting operations
is a significant opportunity under the accepted new-schema permission.

Current per-node logger packet/evidence/provenance/model/anchor allocation is
about326kB/node or1.305MBfor four, PSRAM-first. A redesign should budget byte/block
custody buffers and control reserves explicitly rather than inherit every old
queue. A500ms pause accumulates about80kBof raw four-IMU axes, plus framing/local/
metadata; where that backlog resides depends on which stage stops. Positive
excess downstream service is needed to recover; more buffering cannot cure a
sustained deficit. Controlled stall testing remains deferred.

## Accepted architectural direction; mechanisms still open

Investigate master-selected ready data frames rather than a mandatory explicit
node/object/fragment fetch before every data reply. Retain logger-directed
control, bounded credits/backpressure and exact acknowledgment identity. Use a
bounded immutable window and independent sample/evidence/control progress.

Compare256and512physical profiles; do not assume512will meet ADC service. Make
ready IRQ optional, level/latch-based so a missed edge does not lose work, and
retain bounded polling/control opportunities when it is absent or stuck. A signal
is not a substitute for frame validation or physical first-byte/CS ownership proof.

For the first implementation slice, retain existing node CAN payloads/profile
unless a revised budget demonstrates that node changes are necessary. Prefer
the lowest-cost encoding with adequate margin; evaluate actual master service,
useful physical progress and BDQ/storage cost together. Q15-Q21 accept this broad
direction, self-contained sample units, selective recovery and reserved essential
control service. They do not select exact layouts or authorize implementation.

## Fact sources

- `firmware/can-fd/common/protocol/bodaqs_master_service.{h,c}` and
  `bodaqs_measurement.h`: current representation and ownership.
- `firmware/src/RemoteImuStream.cpp`, `SharedSpiBus.cpp`: recording allocation and
  logger hardware API.
- Installed TI SDK `source/ti/driverlib/dl_dma.h`: byte-DMA count limits; installed
  Arduino core `esp32-hal-spi.c`: blocking FIFO transfer implementation.
- r23 map: `C:/Users/benco/dev/BODAQS-worktrees/imu-batch-investigation-r23-r2/artifacts/master-diagnostic/bodaqs_can_master.map`.
- Owned r23, r18, r19 and sustained ADC r13 assessments under
  `C:/Users/benco/dev/BODAQS-worktrees/drain-capacity-evidence/first-real-imu-implementation/`.
  Header geometry examples are analytical assumptions, not measurements from
  those reports. No new firmware or physical test is performed for this budget.
