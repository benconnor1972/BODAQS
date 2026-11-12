# r19: master processing and receive scheduling

The user chose to skip another pacing confirmation. Use the r18 600 us logger as
the experimental baseline. Prior stored payload was about 6118 readings/s in the
first 80 seconds versus 5399 in the latest 500 us return, with both nodes active.
This is a promising measured setting, not a qualified capacity or optimized ceiling.

## Separate hypotheses

| Variant | Block CRC | CAN first | First use |
|---|---:|---:|---|
| Exact retained master | off | off | Existing r18 comparison evidence / rollback |
| crc-block | on | off | First physical capture |
| can-first | off | on | Subsequent isolated scheduling test |

The block implementation advances the same reflected CRC-32/ISO-HDLC state four
bytes at a time using four lookup tables. Wire CRC still covers all 252 preceding
bytes; logical CRC still covers the identical immutable identity prefix and
payload. Canonical checksum calculation processes the prefix and payload as two
consecutive spans rather than selecting between them per byte. No validation,
padding check, source identity, ACK proof or malformed-input rule is relaxed.
There is no hardware CRC register state, IRQ masking, DMA change or new allocation.
Extra lookup data uses flash. Host speed is not evidence of Cortex-M0+ speed.

The CAN-first variant moves the existing bounded CAN receive turn immediately
before SPI receive processing. Each loop still processes at most eight CAN records
and one queued SPI request; refills do not extend the CAN budget. SPI publication
and physical CS ownership remain unchanged. Control processing still follows both
receive turns; current inventory is published before SPI admission and before CAN
dispatch. A larger CAN-first turn might worsen SPI request latency, so this is a
separate experiment, not an assumed improvement or a higher-priority CAN interrupt.
The three SPI runtime debug counters are now sampled after both receive turns.

Both make options default to zero and require the first-recording profile when
enabled. No production default, protocol version, BDQ schema, pin or IRQ use
changes. No combined variant is included. Retained batch sizes/deadlines,
evidence cadence, queues, CAN profile, timing/lease/STOP rules and peer images stay
fixed. Changes to response publication and the clock-trust guard are deferred.

## Install for the first test

The bundle contains source, commands, logs, stack reports, generated configuration,
exact reused peer images and SHA256SUMS. No build/assessment command flashes devices.

1. Install **artifacts/master-crc-block/bodaqs_can_master.out** on the MSPM0G3518
   master using the existing CCS procedure. Select its own ELF symbols.
2. Install **artifacts/fixed-logger/firmware.bin**, the exact r18 600 us logger,
   on the ESP32-S3. The latest 500 us return used a different logger; it must be
   replaced for this test. If already on this exact 600 us image, retain it.
   Application offset is **0x10000**. Matching bootloader/partition/boot_app0 files
   are beside it for the established full-flash procedure; preserve NVS/config.
3. Retain the existing node firmware and physical two-node setup. Load the
   private **Configurations/B_2imu_adc_off.txt** if settings changed. Nodes 0/1
   active, ADCs and nodes 2/3 muted, primary heartbeat 500 Hz. Never print or
   publish the private configuration.
4. Restart master/nodes, then logger. Leave idle at least 60 seconds for
   reconciliation; idle time alone is not readiness proof. Use the usual
   remote-configuration state if the API is available.
5. Optional stopped-target check: **gMasterOptimizationInfo = [1,1,0]** for the
   first test. [1,0,1] means the scheduling variant; do not use that for case 01.
   The old retained master has no marker. Firmware version/BDQ logger recipe
   alone cannot identify the installed master.
6. Resume the master before recording. Start, require streams=5, and stop an
   early participant failure. Descriptors alone do not prove both STARTs worked.
7. Record about **105 seconds after the running indication**, then normal STOP.
   Wait for file closure and full FLOW finished output before copying the BDQ.
8. Save one finalized BDQ, serial.txt and the actual loggercfg.txt export under
   **Results/01-crc-block/attempt1**. Include both existing CCS master snapshots
   in ccs.txt if available, plus the three optimization-marker values. Do not halt
   during acquisition/cleanup. Export before another recording resets evidence.

## Assessment and decision

Run the pinned offline assessor with the existing Python environment. The command
below is one PowerShell line; replace the bundle and report directory placeholders.

    & 'C:/Users/benco/dev/BODAQS-worktrees/drain-capacity-evidence/spi-prototype/tool-venv/Scripts/python.exe' -B '<bundle>/assessor-source/firmware/tools/assess_master_drain_round.py' --case '<bundle>/Results/01-crc-block/attempt1' --variant crc-block --output '<fresh-report-directory-outside-the-input-attempt>'

It checks the bundle hashes, exact 600 us logger recipe/config, both active sources
with recognized START baselines, early failures, file closure and the first
100-second stored-payload window. CCS is optional and its absence stays explicit.
The operator must still establish master image identity. A zero exit is a capture
precheck, not a loss-free or physical qualification claim.

Compare with 261112_185341 at the same 600 us spacing, per node and in equal native
logger observation windows. Count raw six-axis readings separately from bounded
source delivery. Review ambiguity, source-final observations, packet replay,
master first-loss interval, ingress drops, CAN receive losses, request queue age,
decode/dispatch/encode phases, storage stalls and accepted-versus-persisted counts.
Detailed phase timing freezes at first loss or STOP and includes interrupts.
The outer service time and DRAIN exchange time are not pure CPU or wire occupancy.

Promote block CRC as an experimental master setting only if physical useful
delivery or measured service cost improves without integrity/control regressions.
Then test can-first with the exact same 600 us logger/config, changing only the
master to artifacts/master-can-first/bodaqs_can_master.out. This second variant
does not include block CRC, preserving attribution. Review the first result before
deciding whether a combined candidate is worthwhile; do not run a blind matrix.

If a variant regresses, restore artifacts/rollback-master/bodaqs_can_master.out,
keeping the 600 us logger. Four-node and mixed-ADC viability remain unproved.
Controlled storage-stall testing remains deferred. Revisit the agreed conservative
clock-trust behavior before finishing the programme, in its separate work lane.
