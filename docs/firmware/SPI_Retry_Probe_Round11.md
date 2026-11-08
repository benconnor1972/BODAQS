# Retry deadline experiment, round 11

Round10 physical cases1000..1012 are the repeatable performance loop. At queue4,
256 bytes and requested16MHz, CLOCK improved ACK-confirmed throughput from138.7
to183.1 decimal kB/s and receive drops from784 to1. However,910 deadline retries
remained. Reply age reached6.519ms against a5ms retry interval. This does not
prove every retry was unnecessary or establish a worst-case reply bound.

## Question and controlled variable

Does a longer per-request retry interval reduce duplicate work and improve
ACK-confirmed goodput, while retaining bounded recovery? Ranked predictions:

1. Delayed valid replies trigger avoidable retries:10/20ms reduces retries and
   repeats, potentially increasing goodput with no acceptance/freshness loss.
2. Distinct-request processing/cadence is limiting: retries fall but throughput
   stays similar; additional deadline relaxation offers little capacity gain.
3. Recovery delay costs dominate: goodput or long-tail reply age worsens at the
   longer intervals, despite fewer retries. Preserve that negative evidence.

Keep the exact round10 queue4 table-CRC master, CLOCK mode,256-byte frames,
requested16MHz,4 synthetic nodes,1008-byte objects,500us start spacing,25us guard,
four pending requests,800us row reserve,500Hz fresh rows and both ADCs unchanged.
The master and node sources/binaries do not change. No production behavior changes.

## Bench command and result interface

The existing12-token execution command accepts an optional13th token `retry_us`
only for `owner_pipe`/`owner_flow`. Supported values are5000,10000,20000. Omission
resets to5000 for every case. Other values, non-decimal/overflow values, extra
tokens and use on non-pipelined modes fail before starting. The probe-only
transport `begin` gains a trailing defaulted retry argument with the same checks.

Schema `bodaqs.spi-probe.v11` records `profile.retry_us`: selected value for a
pipelined case, zero otherwise. `request_window.retry_us` must agree. Older
v1..v10 reports retain their existing interpretation and fixed5ms window policy.
Source-derived logger identity advances to `spi-probe-v11-...-crc1`.

Only the pending-request comparison changes. First dispatch establishes the
deadline; a real retry updates that request's retry timestamp. CLOCK and other
nodes' progress do not extend it. Eight retries remain the limit; the next due
attempt fails. Nominal exhaustion is around9 intervals after the initial request
(45/90/180ms), plus dispatch/service delay, not a hard real-time guarantee.
Existing4096-slot/500ms no-progress guards and STOP/reboot-required behavior remain.
The longest nominal retry horizon is below500ms. Unsigned elapsed-time arithmetic
and finite identifier ownership/reset scopes are unchanged. No IRQ/DMA/raw wire,
publication, physical retirement, master capability or ACK acceptance changes.

## Offline validation

Exercise real public parser/logger/transport/ADC-cache code with a simulated
common-engine peer. For each interval, inject independently a lost POLL request,
a lost POLL reply after processing, a lost ACK reply after applying the ACK, and
permanent node0 ACK-reply loss while other nodes progress. Require recovery for
single losses, no premature retry, and exhaustion within300ms for permanent loss.
Separately delay loss-free replies with a14-exchange FIFO and require fewer
retries at20ms than5ms. This models latency, not actual adapter service capacity.
Retain old physical reply corruption and exact acceptance/STOP tests. Test invalid
commands, default reset, v11 analyzer policy consistency and unchanged v1..v10
reports. Compile probe and normal A8. Reuse the exact hashed round10 master and
its original queue/CRC/adapter validation; do not rebuild it under another label.

## Manual experiment

Use the unchanged queue4 round10 master. Flash only the new logger application
at0x10000. Check ready/status and run each command separately, returning each
capture for review. Begin1100 ADC-only,1101 CLOCK5ms,1102 CLOCK10ms,1103 CLOCK20ms.
Repeat in reverse order1104 CLOCK20ms,1105 CLOCK10ms,1106 CLOCK5ms to check phase/
order sensitivity. All cases are10seconds. Stop on integrity/freshness failure;
do not interpret a failed run as capacity evidence. The reverse pass remains
subject to review of the first pass.

Compare ACK-confirmed kB/s, accepted vs ACKed objects, pending work, retries,
CLOCK/bypass counts, repeated fragments/duplicate ACKs, receive drops, reply ages,
queue wait, fresh ADC rates and row lag. Fewer retries alone is not success.
Require5000 fresh rows per ADC, no missed/reused/no-sample/timeout/transfer/wire/
accept/command errors and no exhausted retries. Keep background native CAN drops
visible. Maximum boot timing observations may predate the case and are not deltas.

This remains a bench experiment.200kB/s margin is unproven. Actual SCK, native
CAN/IMU plus SD/BDQ, production retry selection and long-run electrical/reliability
qualification remain separate work. No automatic device probing or flashing.
