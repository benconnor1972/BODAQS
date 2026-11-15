# r19: bounded initialization without changing valid bytes

Baseec772853/r18, comparing performance to r17. Retain RAM CRC, direct ACK-fetch, P3 logger, four nodes,512-byte geometry,1200us spacing and ADC-off configuration.

Sample window allocation clears only its16-byte header. Every retained payload contributes a complete64-byte copy before count increments; sealing reads header + those payloads and overwrites the CRC at their exact end. Unused storage may retain old data but is never sealed/emitted. Header reserved bytes14/15 remain zero.

Fragment emission clears the struct prefix before body and the suffix after the complete copied extent, including unused body, proof fields and ABI padding. Valid payload is copied once, and failure-before-emission behavior is unchanged. No wire format, CRC, identity, validation, credits or retirement change.

Fine work timing now has an independent0/1 BODAQS_MASTER_WORK_TIMING option (default1 preserves r18). The selected master explicitly sets0 while retaining PHASE_TIMING=1. No fine clock/counter events remain at operation sites. Coarse steady/dispatch snapshots are unchanged. WorkInfo's second word is named disabled instead of reserved, same152-byte layout; initialized to1 for this build. Exporter verifies this flag and exports only the existing four coarse blocks. r18 work parser expects0 and must not be used on the disabled build.

Tests poison all sample storage and reply structs, exercise every short/full batch, all fragment classes and body-boundary lengths, and compare valid object bytes plus complete encoded replies to the predecessor at256/512/1024. Synthetic omitted-header-reserved and omitted-reply-tail mutations are rejected by the poison oracle. Poison tests simulate stale storage; actual retirement/fence/reuse behavior is covered by separate existing lifecycle tests. Opt-out test requires zero work hooks with coarse callbacks retained. Complete common/master suites, integrated512 recording/lifecycle, target and canonical CRC/Cinit audit required. Physical throughput benefit remains unproven until the bench comparison.

Compare r17's82.08%/~10536readings/s and ACK_FETCH transfer394.78us, rather than attributing every difference from heavily instrumented/storage-pressured r18 to initialization. Check full valid30s steady scope, allfour terminal boundaries, exact identity, duplicates, rejected replies, primary drops and storage pressure. No artificial storage-stall or mixedADC test added.
