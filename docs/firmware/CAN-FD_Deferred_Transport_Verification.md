# Deferred CAN/SPI transport verification

Ticket #154 prepares the existing bootstrap/discovery path for cooperative
control processing. It adds no configuration operations or wire formats.

The master services one completed SPI slot, then one CAN record per main-loop
turn; the node services one CAN record before its announcement, status and
recovery deadlines. CAN interrupts copy only the FIFO fill observed on entry,
capped at the configured hardware depth (master 8, node 4). Records retain the
capture uptime so queue delay does not refresh inventory freshness or restart
the node discovery response window. Decode, inventory mutation/stale updates,
SPI response construction, power enabling and transport recovery run in the
main loop. SysTick only advances time, schedules work and toggles heartbeat.

The fixed queues drop the newest whole record at capacity. CAN software queue
capacity is 8 on the master and 4 on the node; the SPI completion queue has one
84-byte slot because DMA is not rearmed until it is serviced. Each queue exposes
capacity, depth, high-water and saturating dropped counters. The runtime
structures mirror these as `can_rx_capacity`, `can_rx_pending`,
`can_rx_pending_high_water`, `can_rx_dropped`, and master `spi_rx_*` fields.
`can_rx_hardware_losses` counts hardware FIFO loss interrupt observations
(not an exact lost-frame total). Existing SPI status queue fields now report
the CAN software handoff depth/high-water; the wire layout is unchanged.

Main-loop pops mask interrupts only for the metadata/record copy and restore
the previous PRIMASK. Processing happens with interrupts restored. The master
retains the existing bounded chip-select-release guard before DMA rearm and
its malformed-slot recovery. Its RUN-mode requirement for SPI_ERR_02 remains.
No inter-slot delay, CAN bitrate, discovery/status interval, or CS timeout was
changed. Added main-loop latency still requires physical measurement.

## Repeatable automated checks

From the repository root in PowerShell:

```powershell
$env:PATH = 'C:/msys64/ucrt64/bin;' + $env:PATH
& C:/ti/ccs2101/ccs/utils/bin/gmake.exe -C firmware/can-fd/common/test test CXX=C:/msys64/ucrt64/bin/g++.exe
& C:/ti/ccs2101/ccs/utils/bin/gmake.exe -C firmware/can-fd/master/ticlang MSPM0_SDK_INSTALL_DIR=C:/ti/mspm0_sdk_2_11_00_07
& C:/ti/ccs2101/ccs/utils/bin/gmake.exe -C firmware/can-fd/node/ticlang MSPM0_SDK_INSTALL_DIR=C:/ti/mspm0_sdk_2_11_00_07
```

The host suite covers logger/master bootstrap wire compatibility, coherent
inventory generation, malformed records, whole-record overflow/wrap/reuse,
and a queued probe preserving its identity/sequence while a separate CAN queue
is full. Review the IRQ call paths as well: no service/codec, inventory writer,
CS wait, SPI reset/rearm, or CAN mode change belongs in a handler. Builds and
host tests establish software behavior only.

## On-device evidence still required

Do not flash as part of automated verification. With separately authorized
firmware installation, record master/node/logger board revisions, firmware
commit IDs, debugger/probe settings, CAN termination, supply, instrument and
capture files for each run:

1. Cold boot and lower-level debug reset with A8 logger attached. Repeat at
   least 20 bootstraps. Health must obtain valid identity/status and inventory
   without CRC errors or new recoveries. Capture SCLK, CS, MOSI and MISO; measure
   completion-to-rearm latency against the logger's actual shortest request/fetch
   gap, including under CAN load. Confirm rearm always follows CS release and
   RUN mode is retained.
2. Connect all available addresses, inspect coherent inventory generations and
   one-second statuses through Health, then disconnect/reconnect a node. Verify
   stale marking after three seconds, discovery within the five-second cadence,
   and recovery after bus-off without reset. Repeat duplicate-address and boot-ID
   change cases; a pending old status must not become current identity evidence.
3. Run sustained CAN traffic while repeatedly polling Health. Log request/response
   latency and queue counters, and verify Health continues to respond and inventory
   records are complete. Increase burst rate until software drops or hardware loss
   observations occur; high-water must stay within capacity and drops must be
   visible. Stop traffic and confirm discovery/status recovery without reset.
4. Exercise malformed SPI/CRC traffic and hold CS low beyond the existing guard.
   Verify timeout/recovery counters advance and a subsequent valid probe succeeds.
   Capture DMA rearm relative to CS to detect any boundary regression.

No ISR duration, interrupt-masked interval, SPI timing, Health latency, physical
CAN behavior or sensor timing has been established by the portable tests.
Hardware apply/reset/readback will require separate bounded state-machine and
bench validation when configuration support is added.
