# r20: request/reply trace and final-boundary protection

User requests: prepare the next round after neither r19 variant improved sustained
delivery; also fix the persistent missing final source boundary if a simple fix
can be identified. The working reference is the original master plus r18 600 us
logger. Block CRC and CAN-first stay disabled. No IRQ or wiring change is included.

## Purpose and acceptance

The diagnostic logger records two bounded 128-frame windows: leading up to first
reported loss and during STOP, ending when all selected terminal boundaries have
been accepted, a fatal-loss reply appears, or acquisition ownership finishes.
Each frame records actual MOSI target and simultaneous validated MISO identity,
prior receive masks, stale availability hint and wall duration. Aggregate counts
cover the run. Trace data never controls scheduling, receipt, admission or ACK.
No serial output occurs from these hooks during acquisition; export happens
after producer retirement alongside FLOW. Trace storage is about 10 KiB fixed
RAM, included in reserved resource accounting.

The master fix reserves two of the existing 128 per-node ingress entries for
validated source-boundary CAN frames. Ordinary traffic can occupy 126 entries;
queue allocation, FIFO order, immutable selected data and loss accounting stay
unchanged. The reserve is opt-in (MASTER_BOUNDARY_RESERVE=2); defaults stay zero.
It protects START/STOP/recovery boundaries, not every optional observation.
Exhausting the reserve or losing an essential frame at another stage still fails
explicitly. It cannot recover previously lost data or guarantee every tail.

Observed r19 recordings contain repeated fatal stage-6 interpretation-loss
observations immediately after node-1 STOP, while runtime raw-CAN software and
hardware loss counters are zero. The original full master ingress reproduces
rejection of the final boundary. The new regression must retain that boundary
and drain it over actual fragment CRC/ACK retirement in FIFO order. Malformed
envelopes cannot spend reserve; exhausted reserve must retain fatal behavior.

This is a diagnostic round with a separately documented boundary fix. Its raw
throughput is not an isolated scheduling optimization result, and trace overhead
is not assumed free. Compare the final source boundaries, explicit losses and
sequence coverage independently from stored-payload rate.

## First physical run

1. Install artifacts/master-boundary-reserve/bodaqs_can_master.out on the
   MSPM0G3518 master. Debugger checks while stopped:
   gMasterOptimizationInfo=[1,0,0], gMasterBoundaryReserve=2.
2. Install artifacts/logger-pipeline/firmware.bin on the ESP32-S3 logger.
   Application offset is 0x10000. Matching boot/partition/support files are
   bundled for the established full-flash method. Preserve config/NVS.
3. Keep existing node images and wiring. Use Configurations/B_2imu_adc_off.txt:
   nodes 0/1 active, nodes 2/3 and ADCs muted, primary heartbeat 500 Hz.
   It is a private configuration; do not publish its contents.
4. Restart master/nodes first, then logger; allow normal reconciliation (at least
   60 seconds idle, with actual configuration state checked where available).
   Resume any debugger-halted master before START.
5. Start; require streams=5 and no early participant failure. Record about
   105 seconds after the running indication. Normal STOP and full cleanup.
6. Keep serial capture running after file closure and FLOW: wait for the PIPE
   JSON object with type=end. There are at most 256 diagnostic frame lines.
7. Save the finalized BDQ, complete serial.txt, actual loggercfg.txt export and
   available ccs.txt snapshots/marker values under Results/01-pipeline/attempt1.
   Do not halt during logging/cleanup. Export before another recording replaces
   the frozen evidence.

The node firmware is unchanged. Packet validation, CRC strength, lease/STOP/fence
authority, data quotas, buffer allocations, SPI mode 0, requested 16 MHz, 256-byte
slots, 5 us CS setup and 600 us pacing are retained. The sole runtime policy
change is the explicit master ingress boundary reserve.

## Readout and next decision

The offline assessor preserves inputs, checks identities/recipe/config, analyzes
both sources and the equal 100-second payload window, and parses the PIPE trailer.
CCS is optional, with absence explicit. A correct logger recipe does not identify
the installed master image. No missing final boundary or sample identity is
repaired by the tool.

Check whether both actual source-final records reached the file. A successful
control STOP alone is not that proof. Check source loss reports and accepted RAM
versus persisted counts. If final metadata still fails, use the STOP window and
the explicit fatal-loss stage to localize the remaining cause before adding fixes.

For throughput, inspect repeated target/index selection before receipt, duplicate
fragments, idle control targets, backlog hints accompanying empty replies and
candidate request-to-reply slot distances. Current MOSI cannot cause simultaneous
MISO. Multiple earlier identical requests remain ambiguous; overwritten prefixes
and the causal class of an empty reply remain unknown. Availability is a stale
hint, not readiness. Do not add empty/replay percentages or claim all are avoidable.

Select a small scheduling/pipeline change only after this evidence identifies
removable work. No scheduling change is included in this diagnostic image.
The original logger/master rollback images are bundled. If trace overhead is a
concern, the exact 600 us logger may be paired with the boundary-reserve master
as a separate fix-only capture; decide after reviewing the first result.

Four-node/mixed-load qualification and controlled storage-stall tests remain
deferred. The agreed clock-trust conservatism follow-up remains due before
programme completion. Building/preparing this bundle does not flash devices.
