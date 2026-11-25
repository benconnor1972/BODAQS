# Reopen the SPI transaction envelope after the capacity no-go

On 6 November 2026, after the T01 capacity gate returned no-go, the user accepted
Q24-Q25: prioritize larger useful payloads together with a higher qualified SPI
clock before adding acknowledgment/pipelining state. Initially retain one
immutable selected batch per node; add outstanding batches only if a revised
budget demonstrates a worthwhile benefit. This revisits the initial 64-byte,
8 MHz choice in [ADR 0002](0002-drain-capacity-redesign-boundaries.md).

Replace the blanket 100 us uninterrupted bus-ownership limit with a bounded
maximum blocking interval justified by supported ADC workloads. Testing must
establish that ADC acquisition meets its required rates and deadlines; any
reduction in supported ADC capability requires an explicit decision. Control and
other participants must also receive timely service. The original 100 us limit
was an initial requirement, not an established measured ADC deadline.

The user accepted Q26-Q28: evaluate 16 MHz as the preferred clock candidate,
retaining 8 MHz for comparison/fallback and using an intermediate rate if needed
for timing margin. Compare 128- and 256-byte physical transactions, preferring
256 bytes only if ADC service remains acceptable. Initially keep logical batches
around 1 KiB; larger physical payloads reduce fragmentation without requiring
longer sample collection. Exact headers and costs require a revised budget.

The first mixed-workload target is four nominal 3.33 kHz IMUs plus one active
analog channel on each of the two ADCs, at a requested 500 Hz logging rate.
The existing selector chooses 1000 conversions/s per ADC worker for this case;
qualification must measure achieved acquisition, freshness and repeated/missed
readings rather than infer them from that setting. Other channel/rate combinations
receive separate admission results.

The user accepted Q29-Q31: the normal mixed-profile target requires a fresh
conversion for each channel's logged row, not merely 500 rows/s containing cached
repeats. Verify this against an ADC-only baseline and the mixed workload; report
baseline shortcomings separately. Select one SPI measurement profile before
acquisition and keep its clock, format and turnaround requirements fixed for that
recording. A slower pre-start fallback must itself support the requested workload;
live errors use bounded retry/recovery rather than automatic profile changes.

The next implementation step is a small transport measurement prototype using
known data and the target ADC workload, initially retaining the 25 us guard.
Measure useful throughput, processing/rearm delays and ADC interference before
committing to the full production redesign. The user performs any device flashing
manually. Prototype evidence is separate from production readiness and complete
qualification, and new transaction costs cannot be inferred by reusing the old
147 us mean for different frames.

The four-node target, capacity margins, shared hardware and honest timing/data
quality rules remain in force. The final qualified profile and numerical ADC
service bound require evidence. Faster clocking does not itself qualify throughput
or electrical reliability. The original T01 inputs and report remain historical
evidence; they must not be silently rewritten into a passing budget. Reevaluate
the revised envelope before dependent production implementation. See the
[SPI revision review](../firmware/CAN-FD_SPI_Transaction_Revision.md).
