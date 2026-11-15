# r22: boot-only on-target CRC benchmark

Basecd01addc/r17; BODAQS_CRC_BENCH=1 only in experiment build, absent from normal builds. Runs after SYSCFG before CAN setup and acquisition IRQ enable. Exclusive CRCP access and PRIMASK protection are diagnostic-only; production integration must separately handle shared main/ISR callers. No acquisition path switches to hardware CRC.

MSPM0G3518 CRCP driver:32-bit normal polynomial04C11DB7, reflected input/output, little-endian feed, no result byte swap, seedFFFFFFFF and final complement. Reset?enable?32cycle delay. Two methods feed bytes or alignment-safe memcpy32 words plus byte tail. Includes init/polynomial/seed overhead per call.

Golden123456789 and16deterministic Python-zlib size vectors; compare all0..1024lengths at offsets0..3 against canonical RAM-table software. Expected4117checks, zero mismatches, state2. Data stays within1028staticBANK1 bytes. Results368bytes inBANK1, debugger read only after completion.

Time64calls at each of16sizes, including124command CRC bytes,508reply CRC bytes,112evidence and484sample-object identity-bound checksum bytes. SysTick80MHz24-bit downcounter differences per call; each call far below one wrap. Volatile function pointer prevents invariant call hoisting. Restore PRIMASK and SysTick setup before normal startup; reset VAL phase is harmless at this boot-only seam. IRQ-free cycle costs are not live-acquisition latency or end-to-end throughput predictions.

Device script checks expected master UID and stopped acquisition, programs/verifies MAIN only, reads completed benchmark then restores/verifies exact r17 and startup. No complete flash backups. Logger separately restores exact r14 P3/1200us. Restart allboards before any future acquisition. Fresh reviewer confirmed SDK semantics, bounds, golden constants and raw ownership; target link/Cinit audit passed. Normal host behavior unchanged by default-off hook; physical checks replace a mocked peripheral timing claim.
