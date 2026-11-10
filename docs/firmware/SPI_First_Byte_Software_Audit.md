# First-byte SPI fault: prototype versus production software audit

This audit follows the clean round17 prototype and r3/r4 production-path captures.
It establishes one memory-safety defect and prepares a small buffer-restoration
comparison. It does not establish the physical cause of the captured00 first byte.

## Evidence and reference scope

The round17 source is `e0b58bc9372d6a0263bf43470768573383b0fadd`, with clean
physical cases1702/1703/1704:256-byte requested16MHz SPI, real ADC acquisition,
5000fresh rows per ADC, no wire/transfer/accept errors. Synthetic data, rather
than real IMU ingress, supplied its transport. Its decoder checked nonzero
first magic byte53 and a full-frame CRC; first-byte zeroing would not be hidden.
This is strong evidence against a general wiring/rate problem on this bench.

The current r4 source is `e7613577c92bb1ab88e7c8db59d474864daa11d0`. Actual mixed
recording `261110_125739.bdq` retained7586 rejected replies and four raw examples.
Each starts004d instead of424d. Replacing only00 with42 in offline copies makes
the stored CRC match and the canonical decoder accept. Production still rejects
the original bytes. The requested5us selected-CS delay did not remove the pattern.

## Compared seams

| Seam | Working prototype | Production path | Finding |
| --- | --- | --- | --- |
| Master SPI config | Peripheral, MOTO4 mode0,8-bit MSB, CS0, DMA | Same generated settings | No basic mode/config mismatch found |
| Logger transfer | Shared mutex, beginTransaction, CS low, transferBytes, CS high | Same hardware API with per-CS pacing | No explicit byte0 clear found |
| Logger CAN wire buffers | Static256-byte arrays | Local256-byte arrays | r4 ELF places TX atSP+44 and RX atSP+300: both word-aligned. Driver synchronously copies through registers; static storage is not required by this path. Stack exhaustion remains unmeasured, not an identified cause |
| ADC command | Aligned4-byte backing,1byte on wire | One-byte `cmd` object | Driver reads one full source word beyond the object |
| ADC setup | Aligned8-byte WREG backing | Six-byte combined WREG+START array | Driver reads two words:8source bytes for6wire bytes |
| ADC read | Explicitly aligned4-byte TX/RX | Four-byte arrays without explicit alignment | Restore explicit word alignment required by driver pointer casts |
| Master response storage | Two static aligned DMA slots, prototype publication/trace | Two aligned slots in BANK1, real service and smaller RX queue | Important differences, but no first-byte-only overwrite identified |

The single-byte command defect predates the recent ADC optimization in the
production lineage (`b840736` already passes `&cmd`). The tested prototype had
its own protective fix. The six-byte backing was introduced with combined
WREG+START (`af8a4a7`). Do not describe both as newly introduced by r4/r5.

## Actual driver contract and regression

The installed Arduino ESP32 `spiTransferBytesNL` casts the source to `uint32_t*`,
rounds the source-word count upward and reads `data[i]` for every such word.
Its wire-bit length remains the requested byte count. Extra backing bytes are
required for safe memory access, not extra SPI clocks. The same driver writes
full aligned words to RX for full-word chunks.

`firmware/tools/test_spi_buffer_bounds_runtime.py` compiles the actual production
ADC helper definitions and installed driver loop. The ADC-call adapter retains
array object extents; the driver source-word pointer alone is replaced by checked
reads using memcpy, so an out-of-bounds or alignment error is detected without
performing undefined host loads. Peripheral registers/auto-clearing hardware flags
are simulated. The old one-byte command and old six-byte setup each fail a bounds
assertion; padded/aligned helpers pass. Independent assertions require wire
lengths1,6,4. Existing command-oracle ADC synchronous/worker tests additionally
check actual emitted command bytes, explicit START, restore, mux and failures.
The installed HAL path can be supplied explicitly; changes to its source-pointer
declaration fail the extraction guard and require re-auditing the test adapter.

The test is a red-capable memory-contract regression. It is not a reproduction
of the zeroed CAN header. Reading adjacent TX bytes does not itself explain a
write into CAN RX byte0; a successful bounds test cannot qualify physical SPI.

## Master publication/lifetime audit

Both paths encode into the inactive transmit slot, publish ready only after
encoding and a memory barrier, select the new slot at a CS boundary, reset/rearm
the peripheral and DMA, and retain the selected slot. Production's main writer
returns while a reply is ready; with readyfalse, an ISR cannot swap the slot
being written before publication. The prototype adds observer metadata/critical
publication fencing; no concrete production interleaving that overwrites only
byte0 after CRC was found in this comparison. Retirement payload rewriting is
limited to requested cleanup; captured r4 failures already occur in active
acquisition. No speculative master publication/DMA change is made.

BANK1 placement, lower RX capacity, service workload and altered ADC command
grouping remain differences to investigate if the targeted buffer control fails.
No DMA bus-access or physical timing claim follows from source inspection.

## r5 comparison decision

Restore only padded/aligned ADC wire buffers. Keep combined WREG+explicit START,
conversion settings, measurement format/clock, CRC validation, capture, per-CS
pacing and the r4 requested5us delay constant. Firmware identity changes to
`bodaqs_a8_imu_adc_buffers_r5`. The5us value is retained for one-variable
comparison, not endorsed as an optimization. No dynamic allocation, public API,
CAN buffer lifetime or wire-format change is introduced.

If the real first-byte pattern persists, the bounds defect is fixed but is not
the explanation. Then a short correlated CS/SCLK/MISO trace remains useful to
distinguish incorrect wire output from the logger receive path. Do not continue
static-buffer or delay trials solely because their code differs historically.
Real mixed throughput, ADC freshness and received data/tail integrity still need
the same finalized-BDQ assessment. General admission policy and controlled SD
stall tests remain deferred.
