# T01 / #177: capacity and service gate

Decision: **NO-GO for dependent implementation of the initial four-IMU,
one-selected-batch design.** Reopen batching/pipelining, transaction costs or the
explicit hardware/rate/workload trade-off before T02 and its dependents. Larger
queues do not cure the sustained deficit. No firmware, admission settings,
device state or existing recording format changes in this ticket.

The measured-cost scenario fails even without ADC. The hardware is **not proved
universally incapable**: a wire-only lower bound passes the no-ADC candidate.
There is no four-node passing candidate supported by defensible complete service
bounds. Conditional smaller workloads are useful planning candidates, not
qualified operating profiles. Physical qualification #175/#176 remains open.

## Reproduce

From the repository root, Python 3.11+, standard library only:

```powershell
python -m unittest discover -s firmware/tools -p test_drain_capacity.py
python firmware/tools/drain_capacity.py --output ../capacity-report.json
```

[inputs.json](inputs.json) enumerates 21 workloads and six cost scenarios. The
126-case JSON report includes effective inputs, individual failed gates, traffic,
coverage, bank allocations and thresholds. It contains no clock-dependent fields.
The CLI verifies all 48 selected source hashes in [baseline.json](baseline.json),
accepting only raw bytes or CRLF-to-LF source normalization. External artifact
hashes remain byte-exact. A changed source baseline fails explicitly.

The public seam is `evaluate(workload, costs)` in
[drain_capacity.py](../../../firmware/tools/drain_capacity.py); `build_report`
adds source verification and the design progression decision. A numerical pass
is `conditional`, always `production_admitted=false`. Only externally justified
`defensible_feasibility_bounds` could permit design progression. None of the
provided scenarios has that evidence class; editing an evidence label does not
create evidence. Production admission additionally requires physical tests.

## Baseline and evidence classes

Verified integration source snapshot: `1b6caad970ef734b25c361dce4a3dbb6b4ee6b46`.
Its 41 copied source/doc files are inherited bench work, separately listed in
the manifest; seven service/build inputs are also hashed. T01 adds only this
model, its public-interface tests and the capacity documentation/data.

The manifest records actual retained master/node ELF and map hashes, logger
binary/ELF/map hashes, source archives/build manifests, and latest BDQ/serial/
debugger-summary hashes. These are offline artifact identities, not device
readback or new build/physical qualification. Master: G3518, 80 MHz, acquisition
CAN profile 2, TI ARM Clang 5.1.1, `-O2`, 2 KiB reserved stack. Node: G3507SRHBR,
same acquisition link. Logger: ESP32-S3 Mini N4R2 smoke environment. The installed
fragment-window logger deliberately retained **bitwise CRC**; the canonical
integration headers use LUT CRC. Neither its measured time nor a prospective
LUT speedup qualifies the new protocol. `SharedSpiBus` already uses ESP32
`transferBytes`; no per-byte-loop improvement is assumed.

| Evidence class | What it supports | What it cannot establish |
|---|---|---|
| Source/linked artifacts | Exact geometry, bank placement, selected build identity | Runtime stack margin, sustained service |
| Short bench window | Actual failure accounting and mixed service observations | Steady rates or bounds for redesigned code |
| Contract/conservative traffic envelope | CAN charge, fault/empty/retry/burst allowances | Measured simultaneous deadline service |
| Physical wire floor | 64 us for 64 bytes at 8 MHz | Encoding, readiness, publication or useful acceptance |
| Unverified planning assumptions | Conditional resource estimates and failure thresholds | Admission or measured performance |
| Qualified redesigned costs | **None available** | Must not be inferred from host tests |

The latest recording is `261106_080610.bdq`, SHA-256
`418c924a6b7f50ec9dd1898bcc9cd56e314f81c6fca6f5cf235ca93d536918df`.
The independently decoded recording contains 1,236 consecutive IMU readings,
sequence 0..1235, then stage-6 reports totaling 220 source samples and one
evidence record lost. Cleanup succeeds and the tail is incomplete. It is not a
successful sustained run.

Frozen first-loss context `10547103591045405970`, 430,963 us:

- 269 CAN records admitted minus 140 actually ACK-retired = 129 retained:
  128 queued plus one selected evidence record.
- Twelve distinct sample batches contain 128 CAN records, mean 10.6667 of 13.
  Sample prepared replies contain 273 fragments, 256 distinct and 17 repeats.
  Prepared fragments are not physical MISO deliveries or logger receipts.
- Of 900 processed requests, 422 poll non-data classes. All class polls total
  765 and ACKs 85; 50 remaining requests are not assigned to those counters.
  Empty replies can perform necessary discovery/deadline work.
- New SPI RX drops: 59 (already a scoped delta); cumulative base 26 therefore
  ends at 85. No new CAN capture losses. Status refresh
  averages 11.449 us, SPI processing 87.796 us, CAN service 38.725 us. These
  timings include instrumentation/interrupt effects and are not exclusive CPU
  utilization or qualified upper costs.

The logger's different scope includes PREPARE: 3,066 exchanges in 1,473,993 us,
451,737 us charged exchange time, mean **147.3376 us**, max 534 us. The timed
function includes guard/transfer/MISO decode but excludes MOSI encode. It does
not include all work between exchanges. Existing acquisition pacing calls
service eight times then `vTaskDelay(1)`; a separate sensitivity scenario charges
a 1 ms tick per eight successful services. Tick duration and deferred/no-transfer
calls need measurement. Dividing all persisted samples by the frozen master
window, or treating these two scopes as one rate measurement, is invalid.

## Geometry and complete candidate envelope

Four nominal 3333 Hz sources produce 13,332 associated samples/s and 2,666.4
five-sample CAN packets/s. A reception batch has 20 bytes envelope/checksum plus
76 bytes per CAN record. Thirteen records give 1008 bytes, or 26 fragments with
40-byte payloads in 64-byte SPI transactions. Thus samples alone require 5,332.8
fragments/s, and **6,666/s at 1.25-times useful drain**. At the observed exchange
mean, the latter alone charges 982.152 ms/s, before MOSI encoding or any other
work. This independently fails the 85% gate. Actual ODR tolerance is still
unqualified; nominal source rates cannot establish a production arrival bound.

The combined ACK/fetch candidate removes a separate ACK transaction; it does not
remove an immutable batch's physical publication delay. Default: one selected
batch per node and two additional selection/publication turns per batch. The
model separately exposes physical retirement, main request processing and reply
publication. Its `64 + processing + retirement + publication` request interval
is a serial-safe planning envelope for the one-RX adapter, **not a universal
physical lower bound**. Actual DMA/main-loop overlap and reject behavior require
measurement. Master request/CAN/batch CPU and logger encoding/persistence CPU
are independently charged. Faster probing is not accepted-request capacity.

Recurring four-node SPI allowances, before 5% bounded request retries:

| Traffic | Slots/s |
|---|---:|
| Challenge + renew request/result exchanges, 1 Hz/node, five-second authority | 64 |
| Candidate 32-byte raw observations, 1 Hz/node | 16 |
| Node SYNC / master SYNC | 160 / 40 |
| Status | 16 |
| Bridge request/result including bounded retries | 100 |
| Coalesced loss/recovery ceilings, 44 CAN frames/s/node | 704 |
| Management-loss reports | 320 |
| Empty participant probes | 200 |
| Ordinary diagnostic request/results | 32 |

Old snapshot/model/anchor traffic is replaced only by the proposed raw-observation
representation; source identity/configuration/association remains required. Its
32-byte payload and 1 Hz cadence are **candidates**, not agreed/qualified timing
coverage. 5 Hz/64-byte and 10 Hz/96-byte sensitivities are supplied. CAN charges
each auxiliary frame conservatively at 196.25 us, preserving 1M/4M and the 70%
gate. Four-node steady CAN is 57.39135%, plus a 64-frame exceptional reserve
of 1.256 percentage points. Existing bounded loss/recovery ceilings are retained
as adverse service reserves, not evidence that normal loss is acceptable.

Default partial sealing charges three extra slots at each observation/SYNC/
status/loss/recovery boundary. Actual small batches are also evaluated directly:
one CAN record seals 96 bytes and needs three fragments. A 20 ms sealing target,
5% retries, 128 exceptional SPI slots and 64 exceptional CAN frames are explicit.
Finite START/STOP/fence burst counts and interleavings remain unverified. Steady
SPI plus the finite burst must fit 85%; catch-up independently drains at 1.25x
with all concurrent mandatory traffic. CPU, one-RX service and worker pacing
apply stricter limits when necessary. The 15% reserve is retained.

ADC traffic uses **configured worker conversion rates**, not logger rows. The
current selector rounds `ceil(rows * active_channels / .7)` upward through its
discrete rate table. Two single-channel 100 Hz workers therefore select 175 sps
each; at 500 Hz they select 1000 sps each. The ceiling case charges 2000 each.
Every conversion sends WREG(5 bytes), START(1), RDATA(4): 80 us at 1 MHz in three
transactions. Two ceiling workers need 32% wire time before retries/software;
the default 1.05 attempts and 5 us software per transaction raise this to 39.9%.
Waiting for DRDY does not own SPI. Local BDQ rows and 4096-row buffering are also
charged: a conservative 32 bytes/row for the two-channel mixed candidates.

## Results and sensitivity

Observed mean plus explicit unverified costs: MOSI encode 5 us, retirement and
publication 5 us each, ADC software 5 us/transaction, batch work 30 us, persistence
encoding .05 us/byte, background 2%. These are illustrative assumptions, not
measured redesign bounds. The no-pacing case favors the redesign.

| Candidate | Steady SPI | 1.25x SPI | Result |
|---|---:|---:|---|
| One IMU, no ADC | 34.32% | 40.06% | Conditional planning candidate |
| Two IMUs, no ADC | 65.89% | 77.38% | Conditional planning candidate |
| Two IMUs, two 175 sps ADC workers | 69.38% | 80.87% | Conditional planning candidate |
| One IMU, two 1000 sps workers | 54.27% | 60.01% | Conditional planning candidate |
| One IMU, two 2000 sps workers | 74.22% | 79.96% | Conditional planning candidate |
| Three IMUs, no ADC | 97.46% | 114.69% | No-go |
| Four IMUs, no ADC | 129.04% | 152.00% | No-go |
| Four IMUs, hypothetical 100 us total slot cost | 84.70% | 99.78% | No-go |
| Four IMUs, 64 us wire floor | 54.21% | 63.86% | Conditional lower-bound only |
| Four IMUs, wire + wholly unoverlapped 25 us gap | 75.39% | 88.80% | No-go under that gap assumption |

The last two rows distinguish physical possibility from service feasibility.
Zero software/rearm cost is not a supported implementation. With the complete
candidate envelope, four-node no-ADC catch-up needs **total slot cost <=85.1882
us**, including encode and non-overlapped guard: only 21.1882 us beyond wire.
The serial-safe request interval must be <=100.2214 us. At two publication turns,
full unoverlapped 25 us gaps already exceed the SPI budget. Gap overlap with ADC
or other work must be demonstrated, not credited twice. At the maximum ADC
envelope the slot threshold is 51.5138 us, below 64 us wire; **that simultaneous
traffic envelope is impossible at these transaction sizes/rates**, even with
zero remote software cost. This does not prove every hardware/rate combination
impossible, nor authorize removing reserves to produce a pass.

| Four-node no-ADC variation | Catch-up slots/s including retries | Max total slot us |
|---|---:|---:|
| Full 13-record batches, two publication turns | 9977.91 | 85.1882 |
| 10-record batches | 10139.43 | 83.8311 |
| One-record batches | 19938.45 | 42.6312 |
| Four publication turns | 10516.32 | 80.8268 |
| 5 Hz, 64-byte observations | 10095.51 | 84.1959 |
| 10 Hz, 96-byte observations | 10536.51 | 80.6719 |

These are necessary resource thresholds; meeting one alone is insufficient.
The JSON exposes corresponding ADC, serial-request, CPU and delivery limits.
At observed costs the four-node concurrent useful drain ratio is only .5206
under this envelope. No physical candidate is admitted by that calculation.

## Memory, persistence and latency

Coverage retains 50 ms node backlog, 100 ms master retention and one second
logger buffering, including full independently resident upstream queues/reserves.
Node needs 50 packet slots including pending/hardware/burst/evidence allowances,
within 64 allocated (4352 bytes). Master needs 120 packets/node: 67 arrivals +
34 upstream backlog + 13 selected + two in flight + four burst, within 128.
All four master retention rings and selected buffers remain allocated, even in
a one-node workload: 51,200 bytes inside the existing service allocation.

The hashed master map uses 62,723/65,536 BANK0 bytes, including the 2 KiB reserved
stack; BANK1 is empty. A provisional 2048-byte metadata allowance leaves **765
bytes** in BANK0. Spare BANK1 is not implicitly usable without explicit placement
and lifetime review. The hashed node map uses 13,185/32,768 bytes; a 1024-byte
candidate allowance leaves 18,559. These are linked static allocations plus
planning allowances, not measured stack/RAM margins.

Logger allocates candidate 1024 packet records and 512 observation records/node,
112 and 128 bytes respectively; requirements for the four-node baseline are
1005 and 419. It also charges existing 23,936-byte transport state, 32 KiB writer
workspace/output, primary/local queues, 8 KiB ADC stacks, 16 KiB control/metadata
allowance and local backlog. Four-node no-ADC total is **857,328 bytes**, compared
with an assumed 1.6 MB available. Exact internal RAM/PSRAM placement, alignment,
allocation success and runtime stack margin remain unqualified. Mixed workloads
charge larger primary queues and local rows separately.

Four-node no-ADC persistence requires 350,942 B/s including compact packet/raw
observation records, local rows and 2% chunk allowance. The assumed 500 kB/s
writer service is unmeasured. A one-second writer blackout is covered in the
allocation; it is not a five-second authorization buffer. RAM ACK still precedes
SD persistence. Larger metadata/layout/chunk costs must rerun the model.

The provisional 100 ms delivery calculation explicitly assumes 1.5 ms source
packet formation, 10 ms FIFO service, 20 ms batch seal and 10 ms normal scheduler
gap, plus serialized batch service and both finite bursts. It is a **conditional
estimate**, not a proven bound; overloaded cases report no applicable estimate.
Passing observed-mean one/two-node no-ADC candidates estimate 78.5/84.0 ms.
FIFO/scheduler/ADC service tails and queue age must be measured independently.

## Interface changes and remaining evidence

Required coordinated, versioned changes remain proposed: negotiated combined
RAM-ACK/fetch requests and availability hints; node raw full-sequence/clock
observations and five-second authorization with fresh challenge renewal;
compact packet-observation BDQ schema with essential identity/configuration;
analysis reconstruction and untimed sequence access; and measured workload-based
admission profiles. Preserve checksums, duplicate/stale reply safety, immutable
selection, STOP/fence/restart identity scope and existing BDQ readability.
This ticket implements none of those wire/recording changes.

Before reconsidering the gate, obtain physical/implementation evidence for
accepted requests versus attempted slots; CS/retirement/rearm/publication and
response-latency distributions; MOSI/MISO codecs and target CRC variants; main-loop
CAN/batch CPU; ADC selected/actual rates and deadline tails; actual batch-size
distribution and partial sealing; finite control/STOP/fence/retry bursts; storage
service/stalls; allocation/stack margins; and observation reconstruction coverage
and uncertainty against independent clocks. Then demonstrate sustained useful
RAM-accepted/ACK-retired drain at >=1.25x with mandatory ADC/control/time work,
bounded queue age and the existing CAN/SPI/ownership limits. A short recording,
host pass or target compile cannot substitute for these measurements.

Independent worked tests cover frozen accounting, full/one-record fragmentation,
ADC wire demand, ownership and request-capacity failures, separate physical floor,
literal CAN and SPI threshold crossings, memory/persistence failures, invalid
inputs, deterministic reports and changed-source rejection. Red/green logs and
full generated outputs are retained outside the repository in the T01 execution
evidence directory. No device was probed or flashed.
