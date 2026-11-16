# r32: essential-evidence margin and lower-impact acquisition profiling

R31's early shutdowns have two causes. A supplemental read-only export, bound
to context234081883280953386, shows sample repair failures1/1/0/0 for nodes0–3;
ISR fatal flags are zero. Nodes0/1 exhausted bounded sample repair; nodes2/3
instead hit the metadata-loss path (identifiers/counters far below exhaustion).
The former claim that all four were essential metadata losses was too broad.
This trial does not change the sample repair limit or weaken fatal-loss checks.

The master retains16 evidence entries/node. Optional admission now stops at8
queued entries rather than12, reserving8 rather than4 for anchors/boundaries.
Essential capacity, FIFO order, pinned immutable heads, checksum/custody proof
and total allocated memory are unchanged. More optional snapshots can be dropped
with degraded timing. Essential-only overload still fails explicitly.

The actual master queue test uses a defined service envelope, not a replay of
r31: four nodes each offer two optional records plus one anchor every100ms,
with20 validated-head retirements/s/node. Both old/new policies survive that
steady overload while dropping optional records. An additional synthetic burst
of8 anchors after a full optional backlog loses4 anchors/node under the old
reserve; the new reserve accepts all8. Optional payloads exercise the envelope
classification but are not complete interpreted node models. This test does not
substitute for the actual logger scheduler, node interpretation or physical IRQs.
Selected whole-path integration remains required.

Profiling preserves r31's schema and timing boundaries, but accumulates current
bin statistics in228 bytes of internal RAM. The acquisition owner copies that
profile to the persistent PSRAM bank only on bin transitions. Backdated parent
intervals update already-flushed bins without rewinding the hot index. The
storage footer reads the last hot bin only after the existing retired/context
gate; reset is acquisition-owned. No hot-path allocation or serial output.
Current/old bank reset, null-owner immutability, cross-bin nested durations and
MOSI equivalence must be tested. The expected selected diagnostic reservation is
18184 bytes (17956 bank/publication baseline plus228 hot state), not a free-heap
claim. Physical reduction in observer cost still needs measurement.

Retain the r31 selector correction and the four-second health interval. Do not
change wire size/rate/pacing, task priorities/core affinity, ACK fairness, sample
ingress, CRC identity or stop/fence behavior. The exact r27 master source is used
with only the evidence-reserve change, preserving300–330s observation settings.
The logger source branch's unrelated master build is not selected.

Hardware intent: establish whether essential metadata survives6.5minutes with
the larger existing-queue reserve and whether reduced-cost profiling changes
service time. Sample repair may still fail; preserve repair counters separately
and do not mistake reason14 alone for proof of metadata overflow. A failure run
is useful evidence and must be exported raw if the late window is incomplete.
