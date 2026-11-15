# r16: dispatch cost attribution

Retain r15 RAM CRC table, exact r14 P3 logger, four nodes and ADC-off configuration. Master only diagnostic: no protocol, CRC, capacity, pacing, control or retirement changes.

Management check, measurement transfer and availability hint costs partition the dispatch phase. The two additional clock reads add small measurement overhead, so this round attributes work rather than measuring a performance optimization. Skipped transfer is still bracketed and includes branch/clock overhead. All durations include interrupt execution.

Main-owner gMasterDispatchInfo (version1,184-byte TI ABI) records rows ACK_FETCH, other empty, other fragment, other reply; columns management, transfer, hints. It resets on the same new acquisition scope as gMasterSteadyInfo, accumulates only during that snapshot's collecting state and freezes with it. Export requires matching context, recording and row counts, full valid30-second steady window after5-second warmup. Existing snapshot layouts remain unchanged. Requests rejected before encoding are excluded from both sets.

Compare this diagnostic to r15 B provisionally; split costs cannot identify every operation inside transfer, and clock reads/extra counter updates may perturb scheduling. Inspect dominant transfer work before choosing an optimization; preserve object identity, CRC and retirement guarantees. No new physical capacity or mixed ADC qualification is claimed.
