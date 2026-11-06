# Master processing cost, round 7

Bench question: how much master service time is spent decoding, handling a
request and encoding a reply, and how much can an equivalent CRC implementation
recover? This is a throwaway measurement candidate, not production admission.

## Evidence motivating the change

Round6 cases601..605 retained fresh500Hz rows throughout and decoded55408 frames
without wire errors. The request window raised useful128-byte/8MHz throughput
from38.6 to90.3kB/s. Larger256-byte frames yielded73.1kB/s at8MHz and76.4kB/s at
requested16MHz. Mean exchange time fell299 to172us, while measured master
processing remained approximately987 to1002us/request. SPI receive drops rose
4114 to5147. Raw captures/reports remain outside source under the sibling
drain-capacity-evidence/spi-prototype/round6/runs/first-physical directory.

## Controlled prototype

Keep the round6 single-owner ADC scheduler,500Hz RAM row publication,800us row
reserve,4-request window,5000us retry interval and8-retry limit. Keep one immutable
1008-byte object per node, physical frame sizes, requested clocks, SPI mode0,
25us guard, exact payload and both frame/object CRC checks. No queue/DMA/CS
publication, flow-control, acquisition or production protocol changes are made.

Build two otherwise identical instrumented MSPM0 images from one clean commit:

- `BODAQS_SPI_PROBE_CRC_TABLE=0`: original reflected bitwise IEEE CRC32.
- `BODAQS_SPI_PROBE_CRC_TABLE=1`: same polynomial, initial/final XOR and byte order,
  using a256-entry constant table (1024 flash bytes). This applies to the master's
  frame CRC and synthetic object CRC. It does not skip any validation or cache a
  received checksum as evidence of valid data.

The logger remains bitwise in both comparisons; its `cached` option still caches
only the expected synthetic object's CRC as in previous rounds. The public codec
API and rejection order remain. Internal engine codec helpers accept an explicit
timing owner; stateless public encode/decode calls have no timing side effects.
The source-derived logger identity and result schema advance to v7.

## Component instrumentation

The main-owned probe engine has an optional clock callback installed by the real
master after clock initialization. No global timing owner, ISR instrumentation,
allocation, serial logging or live algorithm switch is introduced. Engine init
clears callback/counters; BEGIN and STOP retain cumulative boot observations.

Additive wire-v1 STATS pages3 and4 carry40-byte payloads:

| Page3 indices | Meaning |
|---|---|
|0,1|decode calls, total microseconds|
|2,3|command calls, total microseconds|
|4,5|encode calls, total microseconds|
|6,7|frame CRC calls, total microseconds|
|8,9|new synthetic object CRC calls, total microseconds|

Page4 indices: schema1, algorithm0/1, last observed clock epoch, sticky invalid
flag, clock callback installed0/1, then five reserved zeros. An unsupported STATS
page remains a prompt explicit ERROR. The new reader reports old masters as
unmeasured; an ADC-only case has no master traffic or component measurements.

Each interval reads the existing software clock before and after work. Epoch0,
an epoch change within/between observations, or restoration after such a change
leaves sticky invalid timing until engine initialization. Tick and cumulative
count/total arithmetic use uint32 modular subtraction. Epoch/algorithm/invalid
metadata are endpoint states, never counter deltas. A wrapped timestamp within
one epoch is supported; multiple counter wraps cannot be reconstructed.

Frame CRC is nested within decode/encode; object CRC is nested within command.
Do not add these five totals together. Command also includes synthetic byte
generation, selection/ACK logic and control handling. These measurements include
instrumentation and interrupt time, not pure CPU execution or physical bounds.

STATS3 copies the main-owned component counters while that STATS request is being
processed: its decode has completed, command/encode have not. Endpoints therefore
span control exchanges and are wider than the active acquisition window, with
small phase-count offsets. No ISR mutates these counters. STATS4 validates epoch,
algorithm and measurement availability; it is not a physical artifact hash.

## Logger and analyzer

Every v7 result adds master.processing_measured and four10-value arrays:
processing_before/after and processing_meta_before/after. The measured flag means
both STATS pages were received at both endpoints, not that their timing is valid.
Existing page0/1/2 fields retain their scope. Read failure is unknown, never zero
processing cost. Original wire requests/control and object retirement stay intact.

The analyzer retains v1..v6 reports and adds master_processing_components to v7:
status, stable recognized crc_algorithm, endpoint metadata, modular counter deltas
and per-phase calls/total/mean. Missing callback or unsupported metadata is unknown;
changing algorithm/epoch or sticky invalid timing is invalid and prevents successful
candidate evidence. Inactive ADC-only results are not_applicable. Every mode
remains diagnostic; no production/admission flags become true.

## Validation and remaining debt

Run both CRC implementations against independent Python zlib vectors, all byte
values, lengths0..1024 and independently generated synthetic object data. Compare
all wire bytes through complete real engine transactions, including repeats/ACKs,
and retain independent fixed vectors and first-rejection tests. Test nested phase
counts, malformed input, tick wrap, invalid epoch, STOP/init behavior and real
adapter CS/DMA/publication regressions with both algorithms. Clock/peripheral
boundaries in host tests are simulated and cannot prove physical speedup.

Build logger probe and normal A8 images, both instrumented master variants with
explicit acquisition CAN profile, and normal master firmware. Use a fresh source
boundary review and final artifact audit. The user flashes manually: logger plus
instrumented bitwise master first, then only the table master at the A/B boundary.
Verify reported algorithm and timing status before comparing throughput.

Keep SD/BDQ, native IMU/CAN workload, production admission, actual SCK and long-run
electrical qualification outside this synthetic RAM benchmark. A faster checksum
does not itself resolve receive pressure or prove the full four-node capacity.
