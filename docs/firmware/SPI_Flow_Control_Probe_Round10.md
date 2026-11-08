# Clock-only exchange experiment, round 10

Round9 queue4 reduced ACK-confirmed throughput in all three matched profiles:
125.8->85.1,154.8->95.7 and183.1->138.7 decimal kB/s. Drops decreased, but
queue waits, reply age and repeated work increased. The physical cases900..906
are the red-capable performance loop; software clocks cannot predict capacity.

## Question and predictions

Does removing work submission from exchanges used only to clock replies reduce
the repeated-work/backlog feedback? If so, master repeats and logger clocking
replays should decrease and ACKed throughput should improve. If distinct work
still exceeds service capacity, queue1 can still lose requests, while queue4 can
still add delay. If the new boundary comparison costs too much, retirement or ADC
timing may regress. Measure each rather than assuming clock-only is free.

This is a controlled bench extension, not full readiness/credit flow control.
Keep the existing four pending requests,5ms retry interval,8 retries,500us start
spacing,25us guard,800us row reserve,1008-byte immutable object per node, exact
payload/frame/object CRC and ACK-after-RAM-accept rules. No production changes,
new pins, dynamic profiles, relaxed evidence checks or automatic device access.

## Additive bench wire operation

Wire version1 gains CLOCK opcode7. Its canonical request uses case/object/node/
fragment/logicalCRC/payload length zero, zero padding, and size-only profile0,1,2
for64,128,256 bytes. Clock and node-count bits are zero; the physical link still
uses the selected case's clock. These inert bytes convey no session authority.

After RX DMA disable, FIFO drain and excess-byte detection establish physical
length, the actual adapter compares every byte against the canonical encoding.
Header/zero fields and independently derived fixed CRC bytes must all match.
There is no runtime CRC calculation, template initialization, allocation or
selected-object access in this boundary path. Ordinary requests fail the opcode
check early. Exact CLOCK increments one boot counter and bypasses the receive
queue even when it is full. Every other frame follows existing queue/drop and
main decode/rejection behavior. The helper rejects NULL and unsupported lengths
before accessing bytes. Short/oversize frames cannot borrow stale backing bytes.

The existing transmit publication and peripheral/DMA reset/rearm sequence still
runs. MISO shifted during this exchange came from the already active buffer;
a prepared reply published at this boundary is visible only on a future CS.
CLOCK produces no response of its own and cannot ACK, select, stop, restart,
fence or retire a logical object. It is safe before BEGIN and after STOP solely
because it has no such authority. Full physical retirement remains unchanged.

The common engine does not dispatch CLOCK as ordinary work. An adapter that
does not implement this bypass must not advertise the capability. New main-owned
STATS7 snapshots, copied under the existing IRQ fence, contain schema1,feature1,
bypassed-clock boot counter, then seven reserved zero words. Counters wrap uint32;
BEGIN/STOP do not reset them. This counter is not a delivered-reply count, physical
ready indication, processing credit or physical retirement proof. STATS pages
retain independent control-inclusive scopes. Do not equate their deltas.

## Logger and reports

New `owner_flow` keeps the same single-owner ADC/cache and500Hz bounded RAM row
path as `owner_pipe`. When the window is full and a retry is not due, send CLOCK
instead of repeating pending POLL/ACK. CLOCK does not allocate a pending entry or
extend retry deadlines. Genuine deadline retries retain the old bounded policy.
Returned MISO still passes the same frame, identity, payload and acceptance checks.

`owner_pipe` remains the repeat-request control. Both modes use new images, so
their boundary matcher and instrumentation costs match. The logger must receive
recognized STATS7 capability before entering timed `owner_flow`; missing/unknown
capability fails entry with zero timed exchanges, followed by normal STOP handling.
Optional-page queries still finish with universally supported STATS0, draining
ordered control errors before data. Unsupported optional diagnostics remain unknown.

Result schema v10 adds master.flow_measured,flow_before/after10-word arrays.
ADC-only flag/pages remain false/zero. Analyzer accepts v1..v9 unchanged, validates
v10 flags/pages and reports observed/unknown/invalid/not_applicable flow evidence.
Reserved nonzero words or fewer observed bypasses than definitely transferred
timed CLOCK requests are invalid. Modular counter differences are supported.
The before/after scope encloses the timed window but also includes controls.
The synthetic runtime peer reports its simulated bypass honestly; it does not
pretend to implement real adapter queue/timing pages. Keep native CAN drops and
SPI losses visible; all production/admission flags remain false.

## Validation and manual sequence

The actual-adapter regression first failed on round9 because CLOCK was queued.
Validate independent zlib encodings, every bit mutation, CRC-valid noncanonical
identities/profiles, truncation/excess, full queues, delayed main, publication
interleavings, STOP/new BEGIN and STATS7 through actual extracted CS/DMA/main
bodies for both queue capacities and CRC modes. Existing object/ACK/metadata/
epoch/wrap/production lifecycle regressions remain. Public runtime exercises real
logger/client/ADC/cache/shared SPI with a six-exchange simulated reply latency,
forcing the four-request window full; cover lost POLL and ACK reply, capability
failure, rows and analyzer accounting. IRQs, clocks and peripherals are simulated.
Obtain fresh boundary review and archive/artifact audit before sealing.

Use one new table-CRC logger and queue1/queue4 table-CRC masters. User flashes
manually; logger firmware.bin is the application at0x10000. Start queue1:
1000 ADC-only, then control1001/flow1002 at128B8MHz; control1003/flow1004 at256B8MHz;
control1005/flow1006 at256B16MHz. Run cases separately and review before switching
only the master to queue4:1007/1008,1009/1010,1011/1012 with the same profile pairs.
All are10seconds,4 synthetic nodes,two ADCs,mask3/core1/cycle0,cachedCRC,500us spacing
(ADC-only interval0). Compare ACK-confirmed throughput, drops,retries,clock
requests,bypasses,master repeat work,reply age,queue waits and ADC freshness/lag.
Capture baseline and controls from the new build rather than relying on round9.

Require5000 fresh rows per ADC,zero missed/reused/no-sample/timeout/wire/accept
errors and no exhausted retries. Failures stay visible; no claim of production
qualification or200kB/s until measured. Actual SCK, simultaneous native CAN/IMU,
SD/BDQ and long-run electrical/reliability qualification remain outside this round.
