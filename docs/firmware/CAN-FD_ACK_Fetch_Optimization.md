# ACK_FETCH dispatch optimization

LOG0004's version3 master snapshot contains1440 measured requests. ACK_FETCH is
688 of them; its dispatch mean is245.52us and this dispatch alone accounts for
28.28% of outer request-service wall time. The current experiment targets that
bounded path. It is not a scheduling, queue-size, frame-format or CRC change.

## Implementation

The old combined handler copied the entire measurement slot, cleared the fetch
fields to form a canonical ACK, passed it through the general core, rewrote and
cleared the command as a poll, then passed through the core again. The first
core pass also initialized a full response even though successful ACK retirement
needs no separate response.

The new private retirement helper is shared with ordinary ACK handling. For
ordinary ACKs it still uses the original full canonical ACK validator. For
ACK_FETCH it checks the original retained identity/disposition directly after
the combined handler validates the fetch fields and reserved tail. It compares
complete state, kind/index, context, object, node, total, class, disposition and
checksum. Fields removed by the old normalized ACK view remain fetch fields;
they are not silently treated as acknowledgment proof.

On success, only a zero-initialized poll command is constructed and the existing
general fetch path selects the successor. Context reset/binding checks, immutable
head retirement, already-retired replay matching, object counters and fresh-next
selection are preserved. Proof errors retain the same normalized ACK error bytes;
malformed requests retain the same service result. Class5's rejection behavior
is preserved. Explicit retired identity/checksum and availability trailers are
unchanged. No large response initialization is done for a successful ACK-only
substep. The only public interfaces remain the existing wire/API contracts.

The original standalone ACK branch is routed through the shared helper, so
legacy host tests remain required alongside v2. No ISR, DMA, physical-boundary
publication, logger or node code is changed by this optimization.

## Equivalence and sensitivity checks

`firmware/tools/test_ack_fetch_differential.py` accepts a saved pre-change
`bodaqs_master_service.c` through --reference-source. The bundle retains source
from7dc4dada3929a9ed5bee435e2a18c2cc005c0026, not a reimplementation of the expected
algorithm. Separate executables run the same deterministic corpus against old
and new handlers, comparing result, every physical response byte and the entire
master service state after each request. Native clock callbacks are null in this
fixture, so the state comparison has no process-specific pointers.

The11594-request corpus covers all five ACK classes and applicable node lanes,
first retirement and idempotent replay, bad identities/checksums/dispositions,
physical-codec-valid single-byte mutations, reserved-tail rejection, cross-class
fetches, fetch indices, queued successors, shared/control/data heads and terminal
object identifiers. It includes standalone ACK and stale replay sequences.
It compares668139032 bytes per implementation. This proves equality over the
corpus, not every possible protocol history. Full production wire/lifecycle,
loss, fence, delayed-proof and uncertain-exit suites provide complementary checks.

The corpus was first run against identical old source. After optimization it
passes. A deliberate checksum-bypass mutation is rejected, establishing that the
comparison catches a concrete integrity regression. The deliberately invalid
source is external test evidence only and must never be compiled for hardware.

## Hardware comparison

Retain the500us logger and original acquisition node. Build only the master,
CAN_LINK_PROFILE=acquisition, SPI_MEASUREMENT_PROFILE=first-recording and
SPI_PHASE_TIMING=1, exactly matching LOG0004's instrumentation. Keep the phase
counter version3 so ACK_FETCH dispatch cost can be compared directly. Record
approximately30seconds and save the finalized BDQ, serial output and expanded
phase arrays after file closure, before another recording resets the snapshot.

Compare phase row0 column1 mean against245.52us, original outer mean414.84us,
and independently decoded useful sample coverage. First-loss time, repeats and
empty replies remain context. A reduced code path/host execution time or passing
target build is not evidence of physical throughput improvement. Sustained
capacity, terminal tail reconciliation and production admission remain unqualified.
