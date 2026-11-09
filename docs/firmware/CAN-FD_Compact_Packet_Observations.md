# Compact IMU packet observations v1

The restricted first-recording build adds `bodaqs.can_imu_packets.v1` to the
existing BDQ v2 container. Ordinary builds retain `bodaqs.can_imu6.v1` and old
readers remain unchanged. New readers validate the additive record layout.
The existing per-source catalog freezes node/master boot and UID, recording,
session/context, effective descriptor and physical-axis scaling. Source continuity
segments and stream epochs remain explicit; neither clock rollover nor nominal
sample rate supplies sequence high bits.

Records are fixed 100-byte, little endian, one received CAN sample packet each:

| Offset | Type | Meaning |
|---|---|---|
| 0 | u32 | Packet observation index (not sample sequence) |
| 4 | u32 | Logger creation observation in nominal microseconds |
| 8 | u16 | Status; timing degraded/unreconstructed |
| 10 | 2 bytes | Reserved zero |
| 12 | u32 | Source continuity segment |
| 16 | u32 | Latest full-sequence floor from START/raw snapshot |
| 20 | u32 | Master reception tick, validity from reception flags |
| 24, 28 | u32 each | Global master reception ordinal low/high |
| 32 | u16 | Original packet first-sample low sequence |
| 34 | u8 | Original stream epoch |
| 35 | u8 | Original packet flags, including count in bits0..2 |
| 36 | u16 | Original CAN payload length |
| 38 | u8 | Original reception flags |
| 39 | byte | Reserved zero |
| 40 | 5 x 6 x i16 | Exact ax,ay,az,gx,gy,gz slots; unused slots zero |

All 1..5-sample packet lengths accepted by the canonical CAN format remain
supported. Nonzero unused CAN padding or reserved header bit7 is rejected.
The packet's raw low sequence/epoch/flags and six-axis association survive
without an applicable model, estimated native tick, or earlier companion write.
The packet floor is interpretation metadata carried with each record; it is not
a timing model. A full packet queue blocks RAM acceptance, leaving the real
master head retained. RAM acceptance never promises SD durability.

The independent `read_can_imu_packets` reader uses forward/backward ordering
constraints between full-sequence floors and the normal STOP final sequence.
A later floor bounds preceding packets because node acquisition flushes sample
packets before publishing its next raw snapshot. Normal STOP's last sequence
is inclusive. Sequence high bits are exposed only when both constraint passes
agree. Ordinary low16 wrap works; ambiguous multi-wrap loss is not guessed.
Exact bounded duplicates produce one decoded reading per source sequence;
conflicting values/sequence bounds are invalid. Known five-sample gaps retain
their exact extent. Unresolved intervals are reported separately.

The output includes untimed six-axis readings and raw timing companions.
It deliberately has no per-sample `native_tick` or `time_s`. A torn tail can
retain packet axes with unresolved full sequence; these readings carry
`sequence=None` and retain low sequence and packet identity for later forensic
work. This is a readable partial observation prefix, not proof of full sample
identity or a successful functional recording. Missing optional timing models
or clock snapshots does not discard readings when remaining sequence bounds
are sufficient. Raw observations may appear after related packets.

Current allocation is 2048 packet records (204800 bytes), rather than 8192
expanded sample queue entries; the separate 512 x 224-byte companion queue and
existing provenance/model cache allocations remain. This is a memory accounting
fact, not an SD blackout or throughput qualification. Actual target allocation,
maps and physical storage behavior are checked in subsequent slices.
