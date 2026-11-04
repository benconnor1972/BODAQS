# Native synchronization and analysis timing (#170)

Software evidence, 5 November 2026. Based on verified #169 integration
`8f8203b`. The [acquisition contract](CAN-FD_Acquisition_Transport_Contract.md)
and [network protocol](CAN-FD_Network_Protocol.md) remain authoritative.
No physical timing, propagation, drift, throughput or 10 us bound is qualified.

## Production clock and synchronization path

`master_timing.c` reserves TIMA0 and PA25/TIMA0_CCP3 (PINCM55) on G3518.
Its BUSCLK / 80 counter is nominally 1 MHz. A 16-bit 100000-count PWM would
truncate, so the hardware toggles CH3 at each 50000-count ZERO. Rising output
events occur at 10 Hz; their tick is the extended ZERO event position, rather
than the counter read later by the ISR. This is output-generation evidence,
not a measurement of the physical pad edge or branch propagation. The counter
runs across ordinary recording preparation/start/stop. Low32 wrap keeps the
same boot-scoped epoch; an ambiguous service blackout invalidates the clock.
ISR/periodic evidence backpressure retains the older selected observation,
increments the generator sequence at every rising event, counts dropped
observations separately, and does not reset or invalidate the counter.

CAN receptions now capture this native master clock at hardware FIFO dequeue.
Deferred decode preserves that tick and its original 64-bit reception ordinal.
An unknown master receive clock clears receive-tick validity while preserving
ordered, otherwise valid node data. Existing reception-flags bit 0 means receive
tick unavailable; companions retain those raw flags in clock_bound_flags bits
0..7 and clear validity bit 9. This adds no packet fields.
Master SYNC markers carry the original output-event sequence/tick. Shared
master evidence uses the existing class-5 schema and 16-byte SYNC events.

The node retains actual CC3 hardware captures in a bounded eight-entry ring.
A periodic train cannot distinguish a whole-period CAN marker delay, even after
multiple perfect-cadence pairs. No proven delivery bound or unique causal seed
exists in this slice, so absolute sequence association stays explicitly unknown.
Each per-edge SYNC_CAPTURE uses the accepted 24-byte CAN payload with raw node
tick, sequence zero/unknown and capture flags zero. A future proven association
can use capture flag bit 0; analysis requires that flag before composing clocks.
Selected snapshots preserve the raw captured tick and complete original presence/association flags; the
SYNC-reference association flag stays clear. Models and selected snapshots refresh
from acquisition position at approximately 10 Hz. Models retain the observed
32-interval capture-input range and rational phase. Applicability is limited
to 500 records (source deltas 0..499) and acquisition duration <=150000 us.
Delivery or storage delay never extends that range.

## Causal master/logger bridge and persistence

Class 6 uses the accepted request/response lengths, canonical logical CRC and
fresh nonzero token. The master samples M only after full request/context/CRC
validation, and duplicate tokens return the original M/epoch. Tokens never
wrap in a context. The logger retains its original 64-bit L0 through retries,
demultiplexes matching responses on every normal slot, and captures L1 after
validated response receipt. Twenty-ms retry spacing preserves normal data/ACK
opportunities. The original exchange expires at 300 ms, without extending it.

Complete exchanges persist kind-5 companions with method 1, original token,
L0/L1/M and master epoch. Method 2 records an expired/unavailable token only:
validity bits 15 and 22, zero epoch/M/interval payload, and no epoch/interval
validity. It is never a bounded clock observation. The catalog declares these
method meanings. Missing master clock capability produces the same explicit
unknown result. Existing payload sizes and class-5 event registry are unchanged.

`RemoteImuStream` persists complete node SYNC, shared master SYNC and bridge
fields in the existing 224-byte companion layout. Original node CAN type,
length, flags and reception ordinals remain distinct from shared master
observations. The master native epoch is explicitly one per master boot;
discontinuity fails closed rather than inventing a new same-boot epoch.
Catalogs retain separate node/sensor/master/logger identities and nominal
rates, with master UID and boot as decimal strings. Production bounds remain
unknown. Unknown model uncertainty is never encoded as a known zero bound.

Queued expanded samples retain their exact bytes and essential-evidence serial
after model-table retirement. The existing successful-chunk-write gate still
requires the complete essential companion predecessor before dependent data.
Source segments, model revisions, ordinary counter wraps and actual clock
resets remain separate. Recovered-source flags do not manufacture queue loss.

## Analysis and software checks

See [analysis implementation](../analysis/CAN-IMU-Timing-Implementation.md).
Explicit CAN payload interpretation uses source segments/unwrapped sequences,
model applicability, original SYNC identities and causal bridge brackets.
Shared copies contribute once, conflicts remain explicit, and companion
creation time never anchors samples. Raw axes remain usable with unknown
alignment. Legacy BMI interpretation remains covered by the existing suite.

Independent fixtures cover canonical bridge CRC bytes, original L0/M across
pipelined retry/loss and expiry, actual master timer configuration/IRQ adapter,
hardware-event tick versus delayed ISR time, low32 wrap, periodic backpressure,
node marker/capture ordering, exact 224-byte masks and 64-bit fields. The actual
writer output is independently reopened by Python, including complete and
expired bridges and torn essential predecessors. Literal analysis tests cover
rational mappings, 500-record and 150000-us endpoints, delayed revisions,
source/tick/input-ordinal wraps, resets, shared copies/conflicts and artifact
round trips. Host timing is not a physical qualification result.

Validation commands are the firmware host `test` target, common and node host
`test` targets, `test_master_timing_runtime.py`, analysis `pytest -q`, explicit
G3507/G3518 TI SDK 2.11 builds, and PlatformIO `bodaqs_s3_mini_n4r2`.
The node map uses 40208 flash / 10972 SRAM bytes; master uses 38168 flash /
49750 bank-0 SRAM bytes including reserved stack. Bank 1 remains unused.
The A8 target uses 264364 static RAM / 2012097 flash bytes. These static maps
do not prove runtime stack/heap headroom or admission. All firmware host tests,
13 common binaries, node adapter cases 1..10, master adapter fixture and all
three target builds pass. The complete analysis suite reports 588 passed and
one skipped. Existing dependency/compiler warnings remain unchanged.

## Remaining work and capacity seams

#171 retains broader bounded loss/continuity recovery; its node recovery
foundation was integrated alongside the timing edits to avoid competing owners
of the physical FIFO path. #172 owns comprehensive restart/link cleanup.
#173 must charge the actual master timer state, shared-event retention,
logger bridge transport state, companion queues and complete catalog strings;
these additions do not establish four-node admission or measured service costs.
No rate was silently reduced. Qualified capture/propagation/drift bounds,
physical SYNC/FIFO association and the 10 us target remain deferred to #175/
#176. No device was probed, flashed or physically qualified.
