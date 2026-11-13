# Measurement v3: T01 walking skeleton

This implements #201's first host end-to-end slice. It is an explicitly selected,
unqualified 256-byte profile, not installed firmware or demonstrated capacity.
Existing v1/v2 builds and historical recording schemas remain unchanged. T02
owns the first physical recording; windows and independent service follow in
later tickets. No node/CAN payload change is required.

## Wire and ownership

Select `BODAQS_SPI_MEASUREMENT_V3=1` on both peers. The existing 256-byte v2
envelope geometry is retained with version byte **3**. Version checking is exact;
a v2 peer cannot accept v3 or silently choose another protocol. Existing mode
entry validates boot/session/recording/context and exact profile limits. Clock,
frame size and turnaround remain fixed for the recording.

The header occupies bytes0-19, body20-235, retirement/availability236-251 and
physical CRC32/ISO-HDLC252-255. The physical CRC covers bytes0-251, including
identity and mutable control/retirement fields. Required zero padding and existing
retirement proof checks remain enforced.

A valid context-scoped IDLE from the logger asks the master for its next eligible
sample unit, selected fairly across nodes. A sample ACK_FETCH retires its exact
predecessor and prepares any next eligible sample head, ignoring a node/fragment
fetch preference. Control/evidence continue through the existing logical lane
payloads and fixed envelope; normal samples never require fragment reassembly.
One selected immutable head per node remains in T01. A failed/lost response is
replayed; unchanged object identities deduplicate at transport and recording
custody. This does not yet implement the multi-unit window from T03.

Samples use kind2, class1, index0 and one to three original CAN payloads padded
to64bytes each. Their logical object is:

| Offset | Bytes | Meaning |
|---:|---:|---|
|0|2|Unit schema2, little endian|
|2|1|Class1|
|3|1|Node0-3|
|4|4|Source boot|
|8|4|Original reception-ordinal high word; retained for existing batch split semantics, not sufficient to reconstruct per-packet receive times/orders|
|12|2|CAN packet count1-3|
|14|2|Zero|
|16|64N|Original compact CAN sample payloads, including low sequence, epoch and count/flags|
|16+64N|4|Master-origin logical CRC|

Total is20+64N:84,148or212bytes. Every packet has1-5readings, bit7 clear and
zero unused bytes. The node/epoch, source definition and required padding are
validated before readings can be interpreted. No raw receive timestamp is invented.

The upstream CRC is generated once when the immutable object is sealed. It covers
the existing canonical20-byte identity prefix followed by content excluding the
checksum: context u64, object u32, node u8, class u8, direction u8=1, zero u8,
total u16, zero u16. T01 retains the existing live logical checksum validation
as well as storing the origin checksum for offline verification. Removing a live
check is not necessary for this walking skeleton and is not claimed as a gain.

ACK still means bounded logger RAM custody, not SD durability or completed offline
interpretation. Existing context-scoped object exhaustion fails closed. Published
bytes and physical TX buffers retain separate ownership; CS retirement, not DMA
completion alone, governs hardware reuse. Existing first-byte priming is preserved.

## Recorded schema

`bodaqs.can_imu_units.v1` uses the existing BDQ v2 container and fixed mixed record
format, with260-byte records. The channel catalog declares the following fields:

| Offset | Meaning |
|---:|---|
|0|Logger unit observation sequence u32|
|4|Logger creation tick u32; not acquisition time|
|8|Timing-degraded status u16|
|10|Zero u16|
|12|Logger source continuity segment u32|
|16|Full-sequence lower bound from existing source evidence u32|
|20|Zero u32|
|24|Canonical upstream prefix20bytes (context exposed as low/high u32 channels)|
|44|Logical unit body padded to216bytes, exposed as54 little-endian u32 words|

The source catalog retains full master/source boot, acquisition ownership and
configuration through the existing provenance object. The sample unit's identity,
boot and context must agree with it. Recorded logger annotations are not claimed
to be master-origin observations. Offline decoding validates exact catalog layout,
unit scope/geometry and the retained upstream CRC before exposing readings, then
uses existing forward/backward sequence bounds and source terminal evidence.
The timing companion's complete source/acquisition identity must match, and each
packet epoch must match its source segment's recorded START boundary. Without
that essential definition raw unit words remain stored but verified readings
are unavailable; a valid CRC cannot substitute for source association.
An unsupported interval remains ambiguous; no nominal-rate time is manufactured.

Decoder packet ordering for these records is a unit-ID/slot ordering token,
**not** an ISR receive ordinal. Existing timing companions retain their actual
observations. Native timing reconstruction and multi-source qualification remain
later work. Corrupt upstream units raise an explicit verification error; the
decoder does not return their readings as verified, even with a valid BDQ CRC.

## Initial resource budget and limitations

At256bytes:40physical overhead +16unit header +192CAN bytes +4upstream CRC =
252bytes;4body bytes remain zero before the physical envelope's retirement area.
There are at most15readings/unit. Four sources at3333/s need at least888.8full
sample transfers/s,113.77ms/s clock-only wire time at16MHz. Metadata, partial
units, replay, control and actual software/bus costs are additional.

For the proposed512-byte comparison, the same overhead arithmetic would allow
seven64-byte packets,35readings and468logical bytes within472body bytes. That
profile is not implemented here; T08 must change and qualify geometry, buffers,
codec bounds and recording width together. Do not send512bytes to this codec.

Each sample-unit queue allocates256*260=66,560bytes rather than the existing
2048*100-byte packet queue. The existing evidence/provenance/model allocations
remain; their current conservative admission estimate is retained rather than
claiming newly qualified spare memory. Master ingress and1024-byte selected-head
buffers are reused, with no new master allocation for this slice. The target map
must still show bank placement and stack reservation, not a runtime watermark pass.

At full units the four-source sample record floor is231,088bytes/s before BDQ
chunks, companions and local rows. This improves representation cost but does not
establish the full useful-service budget. Existing70%CAN/85%shared-SPI,1.25xuseful
drain and50msnode/100msmaster/1slogger coverage gates remain qualification work.
Per-source full-unit coverage is256*15/3333=1.152s; partial units reduce that
coverage. The inherited1slogger coverage target needs the actual partial/burst
envelope and all other buffers charged before admission. Resource sizing and
qualification must prove adequate custody rather than infer a pass here.

The provisional500msrecovery goal is not a lossless master-SPI-stall guarantee:
four raw sources alone accumulate about80kB in500ms, exceeding reported spare
master BANK1 space. Backlog location and excess recovery service matter.

## Local validation

Run the sample-unit recording runtime runner with installed GCC/G++; it uses real
node fixture output, production master/stream/writer code and independent Python
decoding. Its corruption case changes accepted axes and recomputes the BDQ chunk
CRC, requiring the retained origin checksum to reject them. The complete integrated
recording runtime runner also accepts `--first-recording --sample-units`, exercising
actual logger transport/control/storage lifecycle with hardware boundaries stubbed.

Target logger environment: `bodaqs_s3_mini_n4r2_imu_units`. Target master make inputs:
`CAN_LINK_PROFILE=acquisition SPI_MEASUREMENT_PROFILE=first-recording
SPI_SAMPLE_UNITS=1 SPI_RX_CAPACITY=2 SPI_TX_PRIME=1 SPI_DISABLED_INIT=1`.
These are build-only selections. No flashing, electrical/timing pass, analog
amplitude/channel-isolation pass or supported workload admission is implied.
