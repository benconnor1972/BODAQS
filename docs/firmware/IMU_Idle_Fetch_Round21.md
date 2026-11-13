# r21: reclaim idle control fetches

This is one bounded scheduling experiment following r20. The r20 source-boundary
reserve succeeded; its diagnostic capture stored 5,854.61 combined readings/s
over the first 100-second logger window, versus the earlier r18 reference of
6,124.60. It showed 31,014 / 154,899 fetch targets on control lanes without a
pending command. Many such exchanges carried useful ACKs. Neither their count
nor the empty-reply count is a promised recoverable-capacity percentage.

## Change and limits

The logger's default-off `BODAQS_RECLAIM_IDLE_CONTROL_FETCH=1` experiment requires
measurement v2. During owned acquisition with an active data consumer, it keeps
real control selections and searches the bounded existing 16-position control
cursor when the selected lane is idle. Real work includes a pending exchange,
queued outgoing command, partial/unaccepted result or outstanding ACK retirement,
on any of the four nodes, including nodes outside recording membership.

If no real control work needs that turn, select data for a participating node:
finish known partial objects first, otherwise honor existing per-node/class
empty-head budgets and refuse complete unaccepted RAM heads. Selection is fair
across participating nodes using the existing data cursor. If nothing is eligible,
retain the original control/drain opportunity. Urgent protected control, actual
outgoing transport, ACK priority and timing-bridge selection keep their existing
authority. Both pure POLL and ACK_FETCH use the new target before wire encoding;
the ACK identity, admission and retirement proof are unchanged.

No queues, public APIs, wire fields, file formats, membership rules, leases,
renewal deadlines, CRC checks or requested ADC rates change. The r20 pipeline
observer, mode 0, requested 16 MHz, 256-byte slots, 5 us CS setup, 600 us pacing,
ACK sweep and existing worker priorities remain enabled. No IRQ is introduced.
Defaults and earlier build environments retain their behavior.

The master is the exact r20 reserve=2 image; node images and configuration are
unchanged. This round requires only a logger update when the r20 master remains
installed. Device programming is authorized by the user, after artifact checks.
Do not flash nodes or start a recording automatically.

## Validation before flashing

The focused regression must fail on the original idle control wire target, then
pass on the new logger. It compiles the real acquisition owner, transport and
master codec, observes actual encoded requests, and tests pure POLL, ACK_FETCH
identity, genuine work on unselected nodes, urgent protected work, partial result,
control ACK retirement, retired cached results, unavailable data and cursor
fairness. Synthetic lane-state injections test selection boundaries; real delayed,
lost-ACK, overrun, STOP, fence and restart paths remain covered by full composition.

Run the complete logger host suite and actual v2 acquisition/lifecycle tests with
the experiment enabled. The late-renewal harness must withhold the complete v2
one-fragment result rather than assume legacy two-fragment geometry. The legacy
split-fragment case remains a legacy-only test, not a weakened v2 assertion.
Retain fresh Standards/Spec and ownership-boundary review at exact source commits.
Build the explicit `bodaqs_s3_mini_n4r2_imu_idle_fetch` target and audit its recipe,
image/boot identities, RAM use, source archive and unchanged peers/configuration.

## First run

1. Use the uploaded r21 logger and retained r20 boundary-reserve master. If the
   master is verified already installed, do not reprogram it. Debugger markers
   are `gMasterOptimizationInfo=[1,0,0]`, `gMasterBoundaryReserve=2`.
2. Keep the nodes and wiring. Use `Configurations/B_2imu_adc_off.txt`: nodes 0/1
   active, 2/3 and ADCs muted, primary heartbeat 500 Hz. The configuration is
   private; preserve it without printing credentials.
3. Restart master/nodes first, then logger; allow at least 60 seconds for normal
   reconciliation. Resume a debugger-halted master before START.
4. Start normally. Require five BDQ streams and no early participant failure.
   Record about 105 seconds after the running indication, then normal STOP.
5. Wait for file closure, FLOW and the complete PIPE JSON `type=end` trailer.
   Preserve finalized BDQ, complete `serial.txt`, actual `loggercfg.txt` export
   and available stopped-state `ccs.txt` under `Results/01-idle-fetch/attempt1`.

From the bundle directory, using the existing analysis Python:

```powershell
& 'C:/Users/benco/dev/BODAQS-worktrees/drain-capacity-evidence/spi-prototype/tool-venv/Scripts/python.exe' -B assessor-source/firmware/tools/assess_pipeline_round.py --case Results/01-idle-fetch/attempt1 --output ../imu-idle-fetch-r21-attempt1-report
```

The shared pipeline assessor verifies the candidate's own recipe/configuration
and binds trace context to both sources. Missing CCS stays explicit. The logger
recipe alone cannot authenticate the master image. It preserves missing boundaries
and loss instead of repairing the capture. Compare the first 100-second payload
window with r20 (same observer) and r18, separately from whole-source delivery.

Success means more useful stored payload and fewer idle control targets without
weaker lifecycle/retirement behavior, new unresolved source identity, missing final
boundaries or storage losses. Report per-node fairness and sample loss as well as
the total. This is one test, not a guarantee of a 10/25% increase or four-IMU capacity.
If its gain is modest, review a larger pipeline/protocol change rather than more
small CRC/processing experiments. The exact r20 logger rollback is bundled.

## Separate STOP-tail issue

The r20 boundaries arrived, but the last three readings of each node were missing.
Current node `flush(true)` sets bit 7 while the logger/compact observation contract
reserves and rejects it. An offline reproducer is being retained as separate
evidence. Do not change node firmware or relax packet validation in this experiment;
installed-node provenance and any conforming sender fix need their own controlled
scope. Tail warnings may therefore recur without invalidating the scheduling
comparison. They must remain explicitly reported.

Four-node/mixed-load qualification, controlled storage stalls, analog accuracy,
IRQ and the agreed clock-trust conservatism follow-up remain separate work.
