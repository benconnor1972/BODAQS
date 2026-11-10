# Paired CAN SPI phase trial: r7

**Load the logger and CAN master from the SAME mode directory pair.** Keep the
existing IMU node, wiring, SD card and sensor configuration. A mode1 logger with
a mode0 master (or the reverse) is an incompatible physical link. Do not start
a recording during the changeover. Normal production firmware remains mode0.

| Pair | Logger application | CAN master, MSPM0G3518 |
|---|---|---|
| Matched control: mode0 | `artifacts/logger-mode0/firmware.bin` | `artifacts/master-mode0/bodaqs_can_master.out` |
| Trial: mode1 | `artifacts/logger-mode1/firmware.bin` | `artifacts/master-mode1/bodaqs_can_master.out` |
| Exact r6 B rollback: mode0 | `artifacts/fixed-logger/firmware.bin` | `artifacts/fixed-rollback-master/bodaqs_can_master.out` |

The node reference is `artifacts/fixed-node/bodaqs_can_node.out`; leave the
installed node unchanged. Hashes, source commit, commands, compiled board
contracts, logger recipe IDs and paired image identities are in
`BUILD_MANIFEST.json` and `SHA256SUMS.txt`. The normal A8 logger image is an
application for offset `0x10000`, not a merged full-flash image. Companion
bootloader (`0x0`), partition (`0x8000`) and boot_app0 (`0xe000`) references are
included in each logger directory. Preserve the existing configuration; do not
erase flash. Use the existing logger upload method with the selected variant.

## Run the matched control, then mode1

1. With logging stopped, load the **mode0 master** onto the CAN master target in
   CCS and the **mode0 logger application** onto the A8 logger. Do not load a
   master image onto the IMU node. Restart the logger and both CAN boards, and
   leave both CAN targets running freely through recording and cleanup.
2. Confirm the logger startup name includes `imu_adc_mode0_r7`, and the printed
   CAN-FD master wiring line reports `mode=0`. Capture the full serial output.
   On the stopped logger, confirm `/api/v1/sensors` has `can:0`/`imu`, desired
   enabled, effective current and configuration reconciled. The existing
   unqualified smoke mode can report `acquisition_ready=false` while stopped.
3. Retain multistream binary,500Hz primary rows, one AnalogPot on ain0 and one
   on ain4, LINEAR output, `include_raw=false`, and one3333Hz CAN IMU. Keep other
   sensors muted. Both ADCs must report one channel and1000configuredSPS. Keep
  16MHz requested CAN measurement SPI,500us start spacing and5us selected-CS
   setup. This trial changes the CAN link's clock phase, not its clock speed.
4. Start with the normal logging button. Require `[Storage] BDQ v2 begin streams=3`
   and both ADC workers. Stop early for streams1, PREPARE failure, repeated DRDY
   timeouts or persistent link unavailability. Preserve failed-start evidence.
5. Otherwise record approximately45seconds. Stop normally, leave both CAN boards
   running until `[Storage] Log file closed.`, then copy the finalized BDQ.
   Retain paired start/STOP/DRAIN/FLOW serial as **r7 mode0**. If cleanup remains
   pending after15seconds, retain the existing Wi-Fi-toggle REMOTEIMU diagnostic
   before resetting. A closed file alone does not prove complete IMU delivery.
6. With logging stopped, load **both mode1 images**, then restart all three boards.
   Confirm startup `imu_adc_mode1_r7`, printed CAN `mode=1`, and the same stopped
   sensor reconciliation. Repeat steps3–5 for the same approximately45seconds.
   Label the BDQ and complete serial **r7 mode1**. Send both finalized BDQ paths
   and serial logs. No extra debugger snapshot or scope acquisition is needed
   initially.

The matched rebuilt mode0 pair is necessary because the unchanged r5 logger in
r6 predates later source/diagnostic changes. It must reproduce the active mixed
fault before a clean mode1 result can be credited to phase. This is a new phase
comparison, not another priming A/B repeat: **both masters keep priming enabled**.

If mode1 cannot discover/reconcile the master, check that both selected images
belong to mode1 and both targets are running. Retain the serial evidence; restore
the complete r6 B pair if necessary. Do not attempt automatic phase discovery or
change physical mode during a recording. Rollback also requires both endpoints.

## Interpretation and stopping rule

Compare matching frozen running-window decode failures/exchanges. Keep later
cleanup-inclusive failure counts separate from that earlier denominator. Check
actual IMU data, gaps/unresolved identities, ADC freshness, storage and cleanup.
Use the existing first-byte capture and strict production decoder replay.

- Mode0 reproduces and mode1 removes or greatly reduces `00 4d 02` rejects:
  phase is a useful discriminator and a possible workaround. Confirm useful data
  and ADC freshness before adopting it. This does not uniquely prove an erratum.
- Both reproduce at comparable rates with the same signature: changing phase
  was insufficient; retain both results and return to the reset/rearm/selected
  transmit-state boundary. Do not add further phase/preload variations blindly.
- Mode0 no longer reproduces: this rebuilt control changed the experiment; do
  not attribute a clean mode1 run to phase until that difference is understood.
- Shifted/duplicated bytes, request corruption or failed startup: retain evidence
  and restore the complete r6 B mode0 pair. Never relax CRC or repair headers.

If a later scope capture is needed, mode1 captures on **falling** SCLK edges;
the earlier mode0 rising-edge SPI decoder setting is incompatible. Keep CH1 SCLK,
CH2 CAN CS, CH3 MOSI and CH4 MISO, with corrected probe attenuation/ground.

## Basis and validation limits

The A/B/A priming results were10.74%,6.68%,15.18% rejected replies in their
respective running windows; all saved rejects still began `00 4d 02`. A prior
physical capture established that signature on MISO while MOSI was normal.
The phase0-sensitive FIFO collision in [TI SPI_ERR_07, SLAZ758E, p22](https://www.ti.com/lit/pdf/slaz758)
remains a lead, not a confirmed cause. SPI_ERR_10 concerns receive-timeout DMA
triggering; this implementation uses RX threshold triggering instead. The main
loop does not enter WFI sleep, so no new sleep workaround is introduced.

Ranked predictions for this round:

1. Phase0 transmit/shifter timing: mode1 substantially reduces the first-byte
   signature at the same bit rate and priming configuration.
2. Reset/rearm leaves inconsistent transmit state: the signature persists in
   both modes; a subsequent bounded state observation at arm/CS would help.
3. Shared ADC/CAN interaction: failures depend on preceding ADC traffic. Mode1
   also matches the ADC phase, so improvement cannot distinguish phase0 silicon
   behavior from mode-switch interaction by itself. Do not claim it can.

The shared compile-time selector defaults to0;1 requires explicit v2 bench
firmware, mixed logger admission and priming on the master. The logger applies
its existing board profile to both legacy and measurement exchanges. The master
sets Motorola4 polarity0 phase1 only while disabled, before preload, on startup
and each retirement rearm. RX extent, TX suffix, ownership/publication, physical
CS retirement, wire bytes, CRC, sample clocks and acquisition settings are retained.

Host checks execute the actual master arm function with simulated registers/DMA,
including reset/rearm, disabled-state phase selection, exact whole/short bytes,
RX extents and unchanged source buffers. Missing-phase and enabled-phase-write
controls must fail. Compiled logger board-table checks retain the same pins,
ADC clocks and legacy rate while changing CAN mode. Existing transport/lifecycle
suites cover protocol behavior. These checks validate configuration and byte
contracts, **not** reproduction or elimination of the physical first-byte fault.
Only the real recording comparison can settle this experiment.

The source-final boundary, whole-recording delivery, known-input ADC/mux tests,
general admission and controlled storage-stall qualification remain open. No
devices are accessed by the builder; flashing is performed manually by the user.

## Offline rebuild

Commit the source and retain a passing typed review for the exact base/head:

```text
python firmware/tools/build_imu_software_candidate.py --mode candidate --profile mixed-diagnostic --experiment spi-mode-ab --fixed-bundle PATH_TO_SEALED_R6 --review-base REVIEWED_BASE --review-result REVIEW_JSON --output-dir FRESH_EXTERNAL_DIRECTORY
```

This full host/analysis validation builds paired acquisition-profile master and
A8 logger images. It reuses the exact node and retains the r6 B rollback pair;
it does not rebuild node targets or claim newly built bring-up-profile images.
Both logger recipes and compiled board contracts are included. A failure keeps
logs and a failed manifest without a source archive.
