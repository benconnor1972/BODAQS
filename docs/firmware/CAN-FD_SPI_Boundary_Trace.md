# r8 correlated SPI boundary trace

This is an opt-in, unqualified mode0 mixed bench diagnostic. Both endpoints must
be the r8 trace pair; retain priming,16MHz,256bytes,500us spacing,5us CS setup,
ADC settings and strict CRC. Normal builds do not enable the diagnostic.

## Required discriminator

For the first confirmed rejected reply, preserve the logger's complete MOSI/MISO
bytes and a frozen master record for that same physical exchange. A later live
memory snapshot, a matching poll kind or an unrelated good exchange is insufficient.

The master keeps eight completed CAN-CS transactions, including receive-queue
overflows. Each record contains the full transmit source at arm and at retirement,
full received request, physical extent, selected source address and raw SPI/DMA
register observations at arm and CS-high retirement. Observe before any fence
rewrite or selected-buffer swap. Do not read TXDATA/RXDATA for diagnostics.
DMA addresses are raw SDK getter values; counts are masked DMASZ.SIZE values.
There is no new CS-falling ISR. Arm/retirement observations do not prove readiness
at the exact first clock. Measure/retain diagnostic observation cost.

## Correlation and freeze contract

SharedSpiBus assigns a saturating per-CS sequence under its existing mutex,
including all callers on that CS. Sequence saturation invalidates correlation.
After the first saved confirmed rejection, the acquisition owner sends one
diagnostic-only request through the same transfer path. Normal request bytes are
unchanged. The marker has a canonical256-byte v2 frame/CRC, kind0, node255,
index/total0, nonzero context/object; body0..3=`TRC8`, body4=1, bytes5..7=0,
body8..11=failed request CRC,12..15=received reply CRC,16..19=failed per-CS sequence,
20..23=failed measurement slot. The object equals that slot; other bytes/proofs
are zero. This adds a bench request semantic, not a production protocol version.

The master recognizes this exact validated marker at physical retirement, before
application enqueue. It freezes the preceding ring, stores the marker identity
and physical ordinal, and publishes frozen last behind a memory barrier. It
does not dispatch the marker to the service or grant/revoke permission. The
normal physical reset/rearm and retirement-proof path still runs. The marker's
pipelined MISO is discarded; retained application transport can retry it.

The logger saves whether the marker transfer completed and whether its per-CS
sequence is exactly the failed sequence+1. Completion is not an acknowledgement
of master freeze. Only a frozen master export proves that. Analysis requires
same context/master boot, valid nonsaturated sequences, adjacency, preceding
master ordinal/extent and exact full MOSI equality. It then compares actual
received MISO to both source copies, without header repair. Duplicate or missing
identity, wrong context, overflow, truncated export or a nonadjacent marker is
inconclusive. Fingerprints alone are not unique identity.

Capture is single-shot per master boot, immutable after freeze until reset. Reset
all boards before the run. An unobserved/lost marker leaves an unfrozen trace and
must not be interpreted. Counters saturate rather than recycle.

## Ownership, impact and evidence

The existing physical retirement owner exclusively mutates the ring; startup
initializes it before interrupts. No service reads from ISR are introduced.
Place trace storage in the existing awake BANK1 section, with a compile-time
size bound. Preserve DMA buffers, extents, queue semantics and source ownership.
No allocation or per-slot logging is permitted. Only marker recognition computes
an additional wire CRC, after the fault being captured. Observation copies and
register reads before the fault can perturb timing; absence of the fault is not
proof of a fix. Freeze/probe work is not a throughput qualification measurement.

Host tests must cover actual arm/retirement integration, marker CRC/scope and
strict tag/reserved validation, both queues including overflow, selected source
before fence rewrite, source immutability, short frames, ring rollover, sequence
saturation, frozen publication and a repeated/foreign marker. Logger tests must
retain original rejected bytes/request and prove same-CS adjacency including an
intervening foreign caller; no probe when unconfirmed or no valid sequence.
Offline join tests must reject ambiguous/mismatched data and include a literal
zero-first-byte fixture plus clean and mutated source controls. Simulated SPI/DMA
does not reproduce silicon behavior.

The operator flashes manually. Capture a finalized BDQ/serial and export the
frozen master block only after STOP/file closure, using exact r8 symbols. The
exporter must read, not program/reset the target, preserve uint64 identities and
resume after reading. No device access is authorized by building this bundle.
Source-final delivery, general admission and controlled SD stalls remain separate.
