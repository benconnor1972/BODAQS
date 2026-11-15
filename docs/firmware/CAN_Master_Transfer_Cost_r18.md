# r18: attribute remaining transfer cost

Reference r17 cd01addc. Retain direct validated sample ACK-fetch, RAM CRC, P3 logger, all four nodes, ADC-off configuration,512-byte geometry and1200us pacing. Master-only timing instrumentation; no wire, authority, ownership or retirement change.

The existing steady and dispatch ABI remain intact. New gMasterWorkInfo version1 is152bytes: version/reserved uint32, context/recording uint64, calls[8]/max_us[8] uint32, total_us[8] uint64. Main-owner only, reset on the same acquisition context/recording as steady, records only state2, freezes with steady. Full valid5s warmup +30s steady window and exact context/recording match required. Unsigned clocks preserve low32 wrap; epoch faults invalidate the enclosing steady snapshot.

Stages:0 combinedACK retirement including refill;1 sample-fetch staging/loss poll including refill;2 sample selection including advance/emission;3 all window_advance calls including background main-loop work;4 sample buffer initialization zeroing only;5 sample object seal/CRC;6 evidence object seal/CRC;7 sample fragment emission/copy. Stage3 is a wrapper around the entire existing function, retaining early returns.

Intervals are inclusive and nested. Stage0/1/2 may include stage3, which includes4/5/6; stage2 also includes7. Stage3 may occur outside SPI request handling. Never sum these counters as exclusive cost, subtract global stage3 from per-request timing, or treat a mean call as a mean physical exchange. Counter updates and additional clock reads perturb timing and are partly included in enclosing intervals; this diagnostic is not an optimization.

Purpose: determine whether remaining transfer work is dominated by refill/object CRC sealing versus selection/emission/retirement. Compare per-call cost and frequency, source-bounded delivery, allfour terminal boundaries, integrity, storage and queue pressure. Preserve all CRC/identity/credit/retirement guarantees. No measured throughput improvement is claimed.

Regression scope: complete common/master host suites; integrated selected512 recording/lifecycle; positive hook wiring for0/1/2/3/7, accumulation/max/freeze/reset; phase-enabled predecessor fullwire/terminal equivalence512/1024; scripted-clock timing/wire equivalence; TI target and canonical RAM table/Cinit audit. Stages4/5/6 are verified by placement inspection, not positive assertions in the direct-fetch fixture. Physical performance remains for the bench run.
