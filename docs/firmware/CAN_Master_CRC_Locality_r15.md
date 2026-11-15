# r15: 512-byte CRC table locality and steady service costs

Keep the exact installed r14 priority3 logger, r13 capture32/service8 master
settings, ingress128/node, nodes/config,16KB storage buffer,512-byte v5,
16MHz,1200us pacing,5us setup,25us guard and no IRQ. No checksum removal,
polynomial, canonical bytes, validation/admission, fairness or fence changes.

Candidate B moves the canonical256-entry byte CRC32 table to one immutable
1024-byte BANK1 array. A retains the existing flash table. This is the same
byte-at-a-time algorithm, not the slower r19 slicing-by-four experiment.
Main and ISR may read the shared immutable table concurrently without locks.
C runtime must initialize the array (writable data section for startup copying;
no runtime writer and read-only codec accesses). Verify symbol placement and initialized
data in the selected target and actual RAM bytes during the bench export.
Keep the feature opt-in/default0; only0 or1 allowed.

Both A and B include identical main-owner gMasterSteadyInfo diagnostics. The
original first-loss gMasterDrainInfo behavior and ABI remain intact. New scope
starts at admitted acquisition, waits5s, then records a bounded30s window of
successful decoded requests: existing four request/reply phase groups,
decode/dispatch/encode wall totals/maxima and reply-kind counts. Interrupts are
included; this is not task CPU time. Empty/repair/unique-delivery interpretation
requires existing FLOW and BDQ, not reply kind alone. Loss does not freeze the
steady window. STOP, changed context/recording or clock invalidity freezes it.
New recording scope resets it. Read after normal STOP/cleanup only.

Verify independent zlib CRC and actual master identity/custody vectors for both
placements and512/1024 host geometry. Exercise real adapter profile accumulation,
wrap, loss independence, bounded freeze, STOP/new scope and epoch invalidation.
Review in fresh Standards and Spec contexts before sealing; run whole host suite
and both selected TI target builds. Inspect BANK0/1 and stack reservation. No host
elapsed-time result establishes MSPM0 throughput or physical timing.

Physical round: four IMUs/ADCoff, fresh restart all boards, normal60s recording,
STOP and finalized BDQ. A then B, preserving attempts/config/serial and master
binary exports separately. Compare equal-window service cost by request class,
source-bounded delivery, useful reading rate, empty/replay fractions, ingress
loss and storage pressure. A versus previousr14 also exposes measurement overhead.
Prefer a meaningful overall gain, not an isolated microbenchmark result.
If B does not help, retain A/reference and stop this optimization lane.
No logger/node flash or SD configuration change is required.
