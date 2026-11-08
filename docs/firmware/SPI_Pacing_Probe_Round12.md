# Request pacing experiment, round12

Round11 completed forward5/10/20ms and reverse20/10/5ms retry runs using the same
logger and queue4 master. Both5ms cases produced183.1 decimal kB/s,912 retries
and911 master repeated fragments. Both10ms cases produced191.9kB/s with neither
retries nor repeated fragments.20ms produced the same1904 accepted objects;
one logger ACK confirmation remained pending at each timed cutoff. All cases
retained5000 fresh rows per ADC. Receive drops per run were2/1/0 at5/10/20ms;
10 background native CAN software drops per transport run remain visible.

## Question and predictions

Does the existing500us minimum exchange-start interval limit useful throughput
or reply collection under the fixed ADC schedule? Change only that interval.

1. If pacing leaves recoverable gaps, shorter intervals increase ACK-confirmed
   throughput and/or reduce reply age while preserving fresh ADC rows.
2. If master service/queue or the fixed four-request window dominates, shorter
   spacing increases CLOCK exchanges, queue waits, drops or retries without
   useful throughput gain. Preserve this negative evidence.
3. If the shared schedule is the limiting factor, achieved start intervals stop
   decreasing materially or ADC freshness degrades. A completed command alone
   cannot establish a useful profile.

This measures a scheduling contribution to reply turnaround. Master processing,
DMA/CS publication, readiness/credit signaling and the transport window do not
change. No inference that shorter spacing is automatically safe or faster.

## Exact reuse and fixed settings

No firmware source, wire operation, schema or binary changes are needed. The
existing public command supports start_interval_us0..5000. Use the exact round11
logger built from49161727dd6f0e009c829ddda3723e27f74d8225:

`spi-probe-v11-49161727dd6f-4645b81238807df4a0f9-crc1`

Logger application SHA256:
`303924903089bf2dc3542160d454479695aa3e02f11a2d24b05624e7454cb9af`.

Keep the round10 queue4 table-CRC master fromab7799b89517191d027e2e367b09bd420bf4b08b,
SHA256 `471616b236bb4dedf2e006b063898fa7d836d4e4835c7f36288665580cf410a8`.
No node changes. The source revision of this experiment document is separate
from the unchanged logger and master artifact revisions. Result schema remains
`bodaqs.spi-probe.v11`; do not expect a v12 boot message or relabel old binaries.

Hold CLOCK mode,256-byte frames,requested16MHz,4 synthetic nodes,1008-byte objects,
cached/table CRC,10ms retry interval,8 retries,4 pending requests,25us inter-CS
guard,800us row reserve,500Hz rows and the two configured1000SPS ADC channels fixed.
Keep single-owner SPI, exact identity/payload/CRC checks and ACK-after-RAM-accept.
Requested pacing is a minimum, not an achieved cadence; measure actual intervals.

## Sequence and stop criteria

Start with1200 ADC-only, then run1201..1204 at500,450,400,350us minimum spacing.
After reviewing the first pass, run1205..1208 at350,400,450,500us respectively.
All physical cases last10s. Run each separately and return the full capture before
proceeding. Keep case IDs increasing; they may continue after1106 without reboot.

Require5000 fresh rows per ADC, zero missed/reused/no-sample/read-timeout/transfer/
wire/accept/command errors and no exhausted retries. Stop this sequence on any
integrity/freshness failure, failed/unconfirmed STOP, changed/invalid clock epoch
or unknown/invalid capability/queue/CRC metadata. Preserve the failed capture.
SPI receive drops, benign stale/duplicate replies and non-exhausted retries are
measurements for review, not justification to conceal errors or automatically
advance to more aggressive spacing. Keep background native CAN losses visible.

Compare ACKed goodput, accepted/ACKed objects at cutoff, new/retry/CLOCK requests,
observed CLOCK bypasses, repeated fragments/duplicate ACKs, receive drops, queue
wait, reply age, actual start interval, cadence phase observations, ADC achieved
read rates and row freshness/lag. More exchanges or fewer CLOCKs alone is not
success. Wider STATS scopes include controls, boot maxima may predate the case,
and overlapping timing totals must not be added as pure CPU time.

## Offline checks and qualification limits

Check every original bundle checksum before reusing exact images/analyzer and
archive their provenance. Verify the new worktree has no firmware diff against
the logger revision. Exercise the nine commands at short simulated duration via
the real public parser/client/ADC-cache/shared-SPI harness. Require exact reported
settings, achieved request intervals at least the requested minimum,800us reserve
preserved, fresh rows, valid objects and confirmed STOP. Run the captures through
the unchanged sealed analyzer. Host clocks/peripherals/IRQs and the engine peer
are simulated; they do not validate physical pacing, adapter queue timing or capacity.

No target rebuild is needed: flashed code is unchanged and retains its original
target build/recovery/CRC/adapter validation. No new ownership/raw-wire/identifier
lifecycle boundary is crossed. Do not probe or flash hardware automatically.

The round11 best is still about8.1kB/s below the200kB/s margin. Actual SCK, native
CAN/IMU plus SD/BDQ and long-run reliability remain unqualified. This experiment
cannot establish a hardware ceiling or select a production pacing/retry policy.
