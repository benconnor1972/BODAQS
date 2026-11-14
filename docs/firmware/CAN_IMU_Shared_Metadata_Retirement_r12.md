# r12: shared timing metadata after participant retirement

Fix the r11 partial-failure stall in the logger recording coordinator. Keep the
512-byte v5 protocol, 1200 us minimum spacing, exact r10 master/node images,
CRC/identity/ACK rules, priorities, stacks, queues and ADC-off bench admission.
Installation remains manual. Do not relax clock distrust in this change.

Configured membership and local file-acceptance membership are different. A peer
whose admission gate is permanently closed and whose producer callback has
retired cannot accept further timing metadata in this recording. Retire only
that peer's contribution to a shared SYNC/bridge fan-out. Do not label its bytes
accepted, reopen its gate, remove source-object custody, or bypass STOP/fence.
Gate-closed with a still-active callback is not producer retirement.

Attempt every outstanding live participant even if an earlier one temporarily
blocks. Retain exact per-object/per-class fan-out progress: successfully accepted
contributions are not copied twice. Release the shared transport object only
after every applicable contribution is accepted or explicitly retired locally.
All-retired optional timing fan-outs can retire without a live destination;
record each omitted contribution. Raw sample/evidence objects addressed to an
individual node still obey the existing custody and administrative fence rules.

Expose saturating per-source counts of omitted SYNC objects and bridge
observations in the final summary after acquisition-owner retirement. These are
fan-out contributions, not unique sensor samples or source-loss counts. The
footer extension is additive. Existing failure/tail/boundary truth remains intact.
No cross-recording counter, pending mask or acceptance state may leak on restart.

## Validation at the previously agreed public seams

Use the actual recording coordinator/control/master -> storage owner -> BDQ ->
independent decoder composition. First reproduce two PREPARE backend failures
with reason CLOCK_UNTRUSTED, preserving acquisition by healthy nodes. Publish
real shared objects through the master and prove they retire and appear once
in each live companion stream, while failed peers receive none. Cover new
objects after startup and runtime source failure through this composed seam.
Use the existing coordinator lifecycle seam to hold a callback active, then
close its gate and retire it while a fan-out is pending: the public acquisition
callback has no scheduler-pause interface, and optional queue pressure normally
sheds metadata rather than blocking it. This directly controlled interleaving
is ownership evidence, not a claim of an independently decoded pending-object
hardware capture. Cover both shared classes, including bridge omissions
during normal tail retirement. Existing whole-feature scenarios cover live queue
pressure, cancellation, restart, ordinary STOP and lost requests/proofs without
relaxing custody. The lifecycle seam also checks saturation, all-retired fan-out
and counter/progress reset through a successor configuration. Do not equate
queue pressure with a permanently closed gate.
Host service timing is not physical qualification.

Build a logger-only r12 kit at the existing 1200 us spacing after fresh review
and the complete host suite. Keep r11 as the reference. A physical capacity
attempt requires fresh board restarts and actual four-source START/data
participation; nine catalog entries alone are insufficient.
