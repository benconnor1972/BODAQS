# Restricted measurement transport v2

Opt-in compile definition: `BODAQS_SPI_MEASUREMENT_V2=1`, coordinated on logger
and master. Defaults remain version1/64bytes/requested8MHz. Bootstrap is still
the existing version1 84-byte/4MHz protocol; its MODE_ENTRY descriptor explicitly
requests measurement version2, maximum1024, physical256, requested16000000Hz,
guard25us. An incompatible peer rejects before acquisition. There is no automatic
rate fallback. Publication occurs only at physical CS boundaries, with no CS-high
publication path. Requested SCK remains distinct from measured SCK.

The measurement frame is 256 bytes, little endian:

| Offset | Meaning |
|---|---|
| 0..3 | `BM`, version2, kind |
| 4..11 | Recording-bound measurement context |
| 12..15 | Object identity |
| 16,17 | Node, fragment index |
| 18..19 | Actual logical object total |
| 20..235 | 216-byte body (unused bytes zero) |
| 236,237 | Confirmed retired class/node, zero if absent |
| 238,239 | Confirmation present (0/1), reserved zero |
| 240..243 | Confirmed retired object identity |
| 244..245 | Confirmed retired actual total |
| 246..247 | Availability hint bits0..3 samples, bits4..7 evidence |
| 248..251 | Confirmed retired immutable object checksum |
| 252..255 | CRC32/ISO-HDLC of bytes0..251 |

Confirmation covers the same context as the frame. Requests cannot carry a
response confirmation or availability. Availability observes selected/queued
work and can already be stale: it grants neither physical readiness nor RAM
acceptance. The first implementation preserves bounded empty polling rather
than assuming an asserted hint guarantees a response.

Existing object kinds and the context-bound immutable logical CRC remain. A
1008-byte real13-reception batch takes five fragments; a96-byte one-reception
batch takes one. Logical lengths, CRCs and body geometry are checked independently.
No fake payload pads a logical batch to make retirement provable.

Kind14 ACK_FETCH requests carry the accepted old object's node/object/actual
total in the header and its class/disposition/checksum at body offsets0/1/4.
Body2/3 select next class/node; body8..11 and12 optionally select next object/index.
Other body bytes are zero. The master validates and retires (or recognizes a
previous matching retirement) before selecting further work. The response carries
explicit confirmation even if no next object exists. A later failed/empty fetch
cannot undo a completed retirement. The same request can be repeated after loss.

This confirmation means the retained logical batch was retired after logger RAM
acceptance. It is distinct from physical DMA retirement at the recording fence
and from SD durability. Old encoded MISO frames may still arrive; immutable
identity/CRC and recorded acceptance prevent them from inserting new readings.

The logger retains its old pending ACK until matching context/class/node/object/
total/checksum confirmation. If the next object arrives without that confirmation
(for example after a whole reply was lost), it stays assembled but is withheld
from the downstream consumer. A late old confirmation cannot clear a newer ACK.
There is one pending retirement per class/node; no outstanding-window expansion.

Implementation evidence so far: actual master retained CAN fixtures cover full,
short and empty next objects, invalid proof and duplicate ACK/fetch. Independent
Python zlib checks the full physical CRC and literal wire version/offsets. The
production logger/master pipelined fixture demonstrates RAM acceptance waits for
explicit confirmation after a lost reply and bounded idle polls. Production
lifecycle tests pass at both compile-time profiles. Adapter memory placement,
DMA/CS regressions and target builds are still required before packaging.

## Adapter and target evidence

The v2 master has four receive cells, each retaining its own measured length.
SPI RX/TX DMA buffers, queue storage and main-owned wire copy occupy an explicit
`.bodaqs_spi_buffers` section in SRAM_BANK1. The master remains awake; this does
not authorize STOP/STANDBY bank-retention assumptions. Main/ISR ownership and
generation/context fence proof remain distinct from logical ACK retirement.
Only complete prepared TX frames publish, at CS boundaries.

TI ARM Clang5.1.1 acquisition-profile build succeeds. The checked map uses
64357/65536 bytes of BANK0 (1179 free), with an explicit4096-byte stack, and
2304 bytes of BANK1. Compiler `-fstack-usage` reports individual frames of
376 bytes for main,856 for process_transfer,312 for the ACK/fetch wrapper,
304 for the core, and344 for retirement scrubbing. Their call/interrupt paths
motivated raising the v2 stack from2048 to4096. Legacy retains2048. These are
compiler/static evidence, not physical stack watermarks or timing qualification.
The logger restricted/v2 target also compiles (265084/327680 static RAM bytes
at this stage; final packaging rebuilds exact source).

The production CS/DMA adapter fixture tests four queued cells and exact lengths,
full256, short255 and excess257 transfers, immutable fence generation/context,
and retirement before ring release. It imports the actual production storage
declarations as well as function bodies. Existing legacy adapter regressions
remain passing. Full physical TX shifting and actual25us readiness remain manual
qualification debt.

V2 uses the same-boot START boundary to establish source epoch/origin even if
optional timing anchors/models are absent. It retains raw low16 data across
large gaps for offline resolution; it does not infer a full sequence from those
low bits. Master/ISR loss counters retain known counts without claiming a full
interval. Timing21/22/23/24 records are optional under pressure; source boundaries
remain essential. The raw CAN ISR distinguishes each type's epoch layout and
does not interpret SYNC timestamp bytes as an epoch. Compact logger model-queue
pressure likewise records evidence loss without ending interpretable axes.

Additional wire tests cover mismatched old context/class/node/object/total/
disposition, malformed next selection, response proof on requests, reserved
trailer bytes, individually mismatched logger confirmation fields, and identity
exhaustion with a retirement still outstanding. At exhaustion, the final valid
retirement remains confirmed but new batch publication fails explicitly instead
of wrapping. Python checks both physical and identity-bound logical CRCs.
