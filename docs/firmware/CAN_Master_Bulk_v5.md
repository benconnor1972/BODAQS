# Experimental bulk v5 bench contract

This opt-in matched logger/master profile extends v4 custody and four-source
fairness. Existing v1–v4 builds and recordings retain their layouts. Nodes, CAN,
128-reception ingress queues, 16 MHz SPI, 600 us minimum start spacing, 5 us CS
setup and 25 us rearm guard are unchanged. Installation is manual.

## Wire and ownership

One CS transaction clocks either 512 or 1024 bytes in both directions. MOSI has
exactly 128 meaningful command bytes; the remaining clocks carry ignored dummy
bytes. MISO protects the entire physical response. Each direction uses the BM
header (20 bytes), a body, a 16-byte trailer and a final CRC32. Command body size
is 88; response body size is physical length minus 40. Trailer byte 3 identifies
geometry (1 for 512, 2 for 1024); other trailer fields retain v4 semantics.
Command retirement and availability fields must be zero. Command CRC covers
bytes 0..123. A response CRC covers every byte preceding its last four bytes.
Version and geometry must match before any command, ACK or data is accepted.
Legacy mode negotiation also binds version and physical size before acquisition.

Sample units keep the original 16-byte origin header, complete original 64-byte
CAN payloads and canonical identity-bound origin CRC32. Maximum payload counts
are 7 or 15; logical totals are 468 or 980. Evidence/control units, independent
evidence service, four immutable sample slots per node, receiver credit, exact
retirement proof and fail-closed identifier exhaustion retain v4 rules.

SPI DMA cells remain private through CS retirement; main owns a copied command.
Expanded adapter/window buffers belong in BANK1. No SPI lock spans CRC work,
minimum-spacing waits or a group of exchanges. No IRQ is used.

## Recording and budgets

New bulk sample streams use `bodaqs.can_imu_units.v2`. Their catalog explicitly
declares the raw unit-word columns and record extent; the prefix remains 44 bytes.
The independent decoder validates allowed geometry, canonical origin identity,
CRC, padding and original CAN payloads before expanding readings. v1 remains
readable. Per-source sample queue payload stays within the old 66,560-byte
allocation; record count decreases as records grow. Evidence queues are unchanged.
Admission remains the existing ADC-off four-IMU experimental exception.
The bulk logger stores pending ACKs as compact identities plus their eight-byte
body, expanding them only for transmission. This changes its internal inbox
representation; legacy builds keep their existing type. The bulk acquisition
task reserves 6144 bytes, and the selected master reserves 5120 bytes of stack.
Its drain diagnostic moves to BANK1 to provide that margin without reducing
ingress capacity. Allocation reporting includes the actual sample-unit queues.

## Selection and validation

Screen both sizes at the agreed public codec, actual master/logger transport and
recording-to-independent-decoder seams. Inject lost requests/proofs, origin
corruption, interleaved control/evidence, STOP, cancellation and restart. Compare
with an independent input ledger. Compile targets to inspect banks and stacks.
Host elapsed time never certifies MSPM0 capacity or ADC freshness.

At 16 MHz raw uninterrupted transfers last 256/512 us. Shared ADC service costs
about 159 us per conversion in earlier measurements, roughly 35% bus wall time
at four channels near 500 Hz. Selection considers blocking as well as sample
goodput. First physical run: unchanged four IMUs, ADCs off, approximately 60 s,
normal STOP, finalized BDQ, serial and master phase counters. Compare source-
bounded delivery, balance, integrity, final boundaries, ingress and sink pressure
against r9. Physical mixed-ADC qualification follows a promising result; this
contract does not expand admission or require artificial storage-stall testing.

## r10 selection: 512 bytes

The actual logger/master host composition offered four equal 3333.3-reading/s
sources and 40 evidence receptions/s/source for ten modeled seconds, with one
service opportunity per 600 us and finite response delays. This models protocol
work, not MSPM0 CPU cost, ADC scheduling or SD performance. All sizes preserved
the ledger's source identity and strictly increasing original CAN sequences.

| Geometry | No-erasure physical requests | Delivered readings/source | With half the requests erased, delivered/source |
|---|---:|---:|---:|
|256|16638|33330|19710..20550|
|512|15668|33320|33285..33320|
|1024|15101|33320|33250|

The final unfinished units explain the small no-erasure tails. All sources kept
evidence progress. With 20% request erasure and three-turn publication delay,
both bulk geometries retained 33320 readings/source, with 398..400 of 400
evidence receptions observed before the ten-second cutoff. No lossless physical
claim follows from these host results; the 256-byte host case also performs much
better than the CPU-limited physical r9 reference.

At those no-erasure request counts, raw SPI occupies about 40.1% for 512 bytes
and 77.3% for 1024 bytes, excluding setup/HAL and software. Adding the earlier
four-channel 500 Hz ADC service observation (~35% bus wall time) makes 1024
unsuitable as the first shared-bus candidate at this polling rate. The 512-byte
choice also halves maximum uninterrupted transport blocking. Neither calculation
certifies ADC deadlines; a physical mixed test remains required.

Both geometries passed host custody/STOP/recording/independent-decode checks.
Preliminary target links fit both buffer layouts, but 1024 increases nested stack
frames substantially; only 512 is enabled in the TI target build. The 1024 codec
and recording geometry remain host-screen options, not an installable profile.
The next physical test selects 512 with per-request decode/dispatch/encode timing.
