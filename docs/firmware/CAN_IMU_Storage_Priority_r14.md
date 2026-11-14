# r14: normal-write scheduling comparison

Starting from r13, change only logger storage task priority2 to3. Keep acquisition
priority2, current500Hz primary rows, four3333Hz IMUs, ADCs muted,16KB writer
workspace/output buffer, sample queues128, master capture32/service8,512-byte
v5 transfers,16MHz,1200us spacing,5us setup,25us guard and noIRQ unchanged.
No firmware C/C++, data format, config or master/node firmware change is needed.

Existing diagnostics measure physical write wall time, write count/size, flushes,
logger queue pressure, sample delivery and transport proof delays. They do not
separate card busy time from task preemption. A priority comparison tests whether
scheduling contributes materially; it does not identify bare card media speed.

Fresh r13 A return is needed if B improves, because SD performance varied across
earlier attempts. Install priority3 B first, record about60s with normal STOP,
then retain results before any A return. Fresh restart all boards per attempt.
Preserve the SD card/settings and do not format or apply artificial storage stalls.
If B starves acquisition, record that failure rather than treating it as an SD
result. Compare source delivery/STOP boundaries, stage5/6 losses, queue pressure,
write wall time per byte/call and proof delays. Favor overall useful delivery,
not merely shorter write calls.

Validate selected target and resolved single priority3 (no priority2 definition),
unchanged remaining compiler options and source hashes, both fresh reviews,
and package checksum/recipe binding. Reuse r13 complete host acceptance explicitly
for unchanged C/C++/analysis code; no implementation-mirroring test is required
for this reversible build configuration. Flash only the logger after sealing.
