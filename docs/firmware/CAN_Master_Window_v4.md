# Measurement v4: bounded sample windows and independent evidence

This opt-in continuation of T03/T04 replaces v3's single ordered sample/evidence
head. The two-node, ADC-off bench remains unqualified. Existing v1/v2/v3 builds,
CAN node payloads and the `bodaqs.can_imu_units.v1` recording schema are unchanged.
Use the matched logger/master pair; version negotiation rejects mismatched peers.

## Ownership and wire contract

The physical envelope remains 256 bytes at 16 MHz with the existing 600 us start
spacing and 5 us CS setup. Its version byte is **4**. Sample body geometry,
master-origin CRC, physical CRC and exact RAM-custody ACK are unchanged. There
are four immutable sample units per node, each holding at most three original
CAN payloads. Publication assigns consecutive context-scoped IDs; the ID span
cannot exceed four even if later units are acknowledged before an older one.
An active unit never aliases an ingress entry or physical SPI TX buffer.

Kind **15**, node255, context set, object/index/total zero, advertises bounded
receiver custody space. Bytes0-31 contain four 8-byte source entries:

| Entry offset | Meaning |
|---|---|
|0..3|Next sample-unit ID needed by the ordered downstream consumer, little endian; zero disables new sample delivery for that source|
|4|Low four bits: unavailable positions at base+0..3; validated buffered units or slots still owned by an older unretired ACK cannot be overwritten|
|5..7|Zero|

All other body bytes are zero. Base must be at most UINT32_MAX-4; no wrapped IDs
or credits are allowed. An all-zero entry gives zero delivery credit. This is
a bounded absolute window advertisement, not an additive credit counter; stale
advertisements can cause replay but cannot release any retained unit. The master
selects eligible source/slot round-robin, including selective repair of holes.

ACK_FETCH(kind14) retains its existing exact predecessor identity/checksum and
retirement proof. If the fetch class is samples, bytes16-47 carry that same
32-byte credit advertisement; bytes13-15 and48 onward are zero. Other fetch
classes keep those bytes zero. This is the sole extension to the kind14 body.
The physical CRC covers these new fields. Kind15 and extended kind14 are rejected
by earlier versions. Ordinary IDLE/standalone ACK do not imply new sample credit.

The logger holds four independent sample inboxes per source. A successor can be
received and validated while an earlier unit or ACK is missing. Downstream stream
admission remains in unit-ID order, preserving the existing recording contract.
ACK is queued only after the complete unit enters bounded recording RAM. Lost
retirement proof leaves that exact slot owned and its reuse credit withheld;
replaying the ACK is idempotent. Each master slot keeps its exact prior retirement
identity until its successor retires. Older proofs outside that history are
rejected, never interpreted as acknowledgments of the reused slot.

An origin-CRC failure earns no custody ACK and leaves its credit open for repair.
After at least eight attempted deliveries and 100 ms without usable custody, the
master declares that source's retention failed. This is conservative bounded
source abandonment, not a finer per-unit skip mechanism. Old published bytes
remain retained until the explicit source fence; other sources continue. The
existing fatal-loss/cleanup evidence reports failure and discarded tail. No
potentially already delivered reading is invented as a known missing count;
sequence gaps and missing terminal bounds remain explicit offline. This can
exceed the provisional 20 ms quality target on a faulted source and is not a
qualification pass. Identifier exhaustion also fails closed; restart requires
a new fully bound recording context.

## Essential evidence and control

Sample ingress retains its existing 128 original receptions per source. Evidence
has an independent 16-entry FIFO plus one immutable head per source. Four FIFO
entries are reserved from optional traffic for full-sequence anchors(0x22) and
source boundaries(0x25), including START/STOP. Other compact-mode timing/model
observations may be dropped first, with cumulative evidence-loss reporting. If
even the essential reserve fills, the existing explicit fatal-loss behavior
remains; no old published bytes are replaced and no missing definition is invented.

Evidence can advance with zero sample credits and cannot wait behind a sample
head. Samples arriving before their essential START remain blocked in logger RAM
while the evidence lane advances. Because evidence may overtake older sample
units, their recorded lower sequence bound comes from the observed START rather
than a later snapshot. No nominal-rate acquisition timestamp is manufactured.

The r7 logger corrects ACK scheduling within this same v4 profile. Sample ACKs
rotate across all sixteen source/window positions, including retries awaiting
exact retirement proof. Previously regular head slots had fixed priority and
the extra slots fell behind evidence ACKs; delayed replies could pin one source
while another repeatedly consumed ACK turns.

After four sample ACK attempts, pending evidence ACKs get up to two data-ACK
turns. Evidence selection rotates across sources and repeats a pending selection
on its second turn, avoiding a single periodically erased request consuming its
only opportunity. Empty evidence work never blocks samples. Protected control,
ordinary control and shared timing ACKs retain their higher priorities. These
are scheduling attempts, not custody/retirement proofs. Only the existing exact
proof clears an ACK. All scheduling fields are transport-owned, reset
with recording state, and retained through link inspection/recovery. No static
cross-recording cursor, wire/config/schema change or new allocation is involved.

Existing separate STOP/renewal/control lanes, three-of-four data selection and
idle-control reclamation remain. The five-second authority horizon,
once-per-second renewal and fresh challenges are unchanged. Sample credits never
gate those lanes. The CAN hardware/ISR queue and physical CS/DMA retirement rules
are unchanged; this does not claim a new bound on upstream hardware loss or a
lossless master SPI outage. Physical fence confirmation clears every window slot
and queued evidence; it is distinct from a RAM-custody ACK.

The management loss-counter correction is independent of this protocol: fatal
reports carry no cumulative counter and therefore no longer reset the remembered
count. Repeated cumulative/fatal notifications cannot recount an old loss delta.

## Budget and verification

`BodaqsMasterWindowStorage` is caller-owned and explicitly placed in SRAM_BANK1
on the target. It contains 16 unit buffers/states, 64 evidence reception entries,
bounded cursors and repair counters. The original service remains in BANK0;
physical RX/TX buffers remain separately owned. The linker map is authoritative
for actual target sizes and bank/stack allocation. The current target build gives:

| Allocation | Bytes |
|---|---:|
|BANK0 used / unallocated|64,409 /1,127|
|BANK1 used / unallocated|12,768 /52,768|
|Original service in BANK0, including the window pointer|57,368|
|Window storage in BANK1|10,912|
|16 unit slots, including immutable and replay ACK states|4,992 (312 each)|
|64 retained evidence entries|5,888 (92 each)|
|Window cursors/counters/padding|32|
|Window wire-observation diagnostic cache|64|
|Logger transport: old / window profile|27,968 /43,928|

The window adds15,960 bytes to logger static custody. These allocations do not
consume task stack or add hot-path heap allocations. The stack reservation remains
4096 bytes, not a measured runtime watermark. BANK1 is not promised across deep
sleep; the existing awake SPI service constraint remains.

Each sample follows one ingress-to-unit copy, one logical-to-physical copy and
the existing logger recording copy. Origin CRC runs once at sealing; physical
CRC runs per exchange. Window selection scans at most four sources by four slots
and formation seals at most four units per invocation. Each logical sample is
84/148/212 bytes, giving at most 60 retained readings/source in the window, about
18 ms at3333 readings/s. That window is not the whole ingress/backlog allowance.
The logger adds twelve inboxes; `AcquisitionControl::reservedBytes()` charges the
actual static transport allocation. The original per-source recording queues and
storage priority2 remain; SD-stall qualification is still deferred.

Automated checks:

- `test_remote_imu_loss_runtime.py`: original fatal/cumulative replay defect;
  58934 then replay then five new losses must record58939, with failure sticky.
- `test_window_ack_fairness_runtime.py`: equal live3333.3-reading/s sources under
  one injected service turn/ms, one- through four-turn response pipelines, and
  periodic request loss. The original code reproduced33330 versus10650 admitted
  readings in10s. The fixed selector keeps both above33000 in the moderate-loss
  cases and all400 offered full-sequence anchors/source progress. At50% request
  loss, substantial equal progress is required rather than lossless delivery.
- `test_master_window_runtime.py`: four sources/four outstanding units, zero
  credits, immutable content, bad/stale ACKs and slot reuse, optional shedding,
  essential START/STOP under full sample ingress, bounded repair failure and
  healthy-source progress; real streams/BDQ writer/independent Python decoder
  check60 exact readings/source with distinct axes. Its repair-exhaustion
  recording demonstrates45 missing readings on one source while the other three
  each retain all60, with independent full bounds.
- `test_integrated_imu_recording_runtime.py --window --idle-control-fetch`:
  actual two-source manager/coordinator/control/stream/storage lifecycle; delayed
  first unit while its successor reaches MISO, independently lost ACK and proof,
  valid physical CRC with bad origin CRC, partial STOP, short write, cancellation
  and stale authorization on restart. The final good BDQ has64 exact readings
  per source and both source terminal boundaries. Existing renewal/STOP bounds
  are asserted under an injected host schedule, not inferred physical timing.
  A separate host-only pressure case fills both sample queues and advertises all
  four positions unavailable while renewal and STOP continue. The decoded tail
  gaps are292 readings/source. The legacy hardware stub's UID0 and minimal footer
  deliberately keep its overall qualification unknown; the separate four-source
  fixture provides complete identity bounds.
  The r7 regression also runs the actual coordinator/control/writer lifecycle
  with a three-turn delayed reply pipeline, independently decodes both complete
  64-reading streams and checks their final source boundaries. Existing
  cancellation, short-write and stale-authorization restart cases remain.

The full host candidate includes these regressions alongside historical suites.
Target builds and fresh boundary/Standards/Spec review precede the bench package.
Next physical comparison keeps the r5 two-IMU ADC-off configuration/card unchanged.
Measure decoded useful readings, sequence gaps and final boundaries as well as
unique/repeated transfers. Do not qualify four IMUs, mixed ADCs, a delivery-rate
gain, native timing quality or outage recovery from host results or compilation.
