# Master transmit priming A/B test: r6

**Change only the CAN master image. Keep the r5 logger, IMU node, wiring, probes,
SD card and mixed sensor configuration unchanged.** Use the normal logging
button; this is a real recording test, not a prototype `case` command.

| Image | Exact relative path | Behavior |
|---|---|---|
| A: matched control | [master A](artifacts/master-A/bodaqs_can_master.out) | Existing all-DMA transmit arming |
| B: primed transmit | [master B](artifacts/master-B/bodaqs_can_master.out) | Byte0 explicitly written while SPI is disabled; DMA sends bytes1 onward |
| Original rollback | [old RX2 master](artifacts/fixed-rollback-master/bodaqs_can_master.out) | Exact master from the sealed r5 bundle |

The two new masters share one source commit, SDK, compiler, acquisition CAN link,
measurement v2, RX2 capacity, phase/queue timing and all other flags. They differ
only in `SPI_TX_PRIME=0/1`. A includes the diagnostic accounting changes since the
old master, so it must reproduce the fault before a B improvement is attributed
to priming. Hashes/commands/source pin/review evidence are in `BUILD_MANIFEST.json`
and `SHA256SUMS.txt`. Optional unchanged logger/node files are retained as hashed
references under `artifacts/fixed-logger` and `artifacts/fixed-node`; leave the
currently installed r5 versions in place.

## Run A, then B

1. With logging stopped, select the **CAN master target, MSPM0G3518**, in CCS.
   Manually **Load Program** from the complete master-A path above. Do not load
   it onto the IMU node or rebuild/reload another project image automatically.
2. Freshly restart both CAN boards and the logger; ensure both CAN targets run
   freely (Resume/F8 as applicable). Do not halt either during recording or cleanup.
3. Keep multistream binary,500Hz, one AnalogPot on ain0 and one on ain4, LINEAR
   output with `include_raw=false`, and one3333Hz CAN IMU. Other sensors stay
   muted. Both ADCs should report one channel and1000configuredSPS. The r5 logger
   retains16MHz requested measurement SPI,500us spacing and5us CS setup.
4. Before starting, check the stopped logger's `/api/v1/sensors`: `can:0`/`imu`,
   desired profile `imu6_3333_32g_2000dps_v1`, desired mode enabled, configuration
   reconciled and effective current. `acquisition_ready=false` is expected for
   this unqualified smoke build. Capture the full serial output.
5. Start with the normal button. Require `[Storage] BDQ v2 begin streams=3`
   and both ADC workers. Stop early for streams1, PREPARE failure phase2/reason35,
   or repeated DRDY timeouts. Catalog entries alone do not prove IMU samples.
6. Otherwise record about45seconds. Stop normally and leave the CAN boards running
   until `[Storage] Log file closed.` If cleanup is pending after15seconds, retain
   the existing Wi-Fi-toggle REMOTEIMU diagnostic before resetting. Copy the
   finalized BDQ and save the complete serial start/STOP/DRAIN/FLOW output as A.
7. Repeat steps1–6 with **master B**, keeping all other settings fixed. Label its
   BDQ and serial as B. If A did not start a valid mixed recording, retain the A
   evidence and resolve that control failure before interpreting B.

**Send both finalized BDQ paths and their serial logs, identifying A and B.**
No additional debugger snapshot or scope acquisition is required initially.
The matching installed-image declaration is the operator-selected full path and
its manifest hash; the unchanged logger does not attest the master binary.

If B markedly reduces/eliminates decode failures, a short return-A run using the
same procedure checks that the result follows the image. If probing is retained,
keep the corrected channel/probe/ground settings unchanged across A/B. The
previous bad-prefix trigger can later verify the wire result. A failure to
trigger alone is not proof of zero errors.

## Interpretation

The discriminator is rejected `00 4d 02` versus normal `42 4d 02`, measured in
the logger's frozen counters and four raw rejected replies. Compare equivalent
window counts and denominators, including retries; do not divide final cleanup
failure counts by a shorter running-window slot count. Check actual IMU records,
sequence coverage, ADC freshness, storage and cleanup separately. A closed file
does not itself prove complete source delivery.

- A reproduces, B improves, return-A reproduces: evidence for priming-related
  readiness as a useful control. Confirm useful delivery before adopting it.
- A and B both reproduce: this control did not resolve the physical boundary;
  retain the first-byte captures. Do not weaken CRC or repair received headers.
- A no longer reproduces: the experiment lacks a comparable control; inspect
  changed conditions before crediting B.
- B causes shifted/duplicated bytes, malformed requests or startup failures:
  stop and restore A or the exact original rollback master; retain evidence.

This remains an unqualified single-node mixed bench profile. Source-tail debt,
known-input ADC/mux checks, general admission and controlled storage stalls are
not qualified by a successful header test.

## Engineering contract and validation limits

The known physical capture showed normal MOSI and zeroed first MISO byte with
the remaining header aligned. [TI SPI_ERR_07](https://www.ti.com/lit/pdf/slaz758)
describes a phase0 peripheral FIFO collision whose underrun indication may be
missing and recommends preloaded data or CRC/retry. That makes priming testable,
not an established diagnosis. The TI SDK peripheral DMA example and clean
prototype also rely on DMA; source resemblance alone is not causal evidence.

In B, the selected transmit slot's byte0 is written using SDK `DL_SPI_transmitData8`
with SPI disabled; TX DMA begins at byte1 with capacity-minus-one bytes. RX DMA
retains its full capacity. Both channels are configured before SPI re-enable.
The barrier orders CPU MMIO; it is not proof of completed DMA or physical shifter
readiness. No arbitrary delay, busy-wait, CRC relaxation, queue-depth change,
new wire command, buffer lifetime or CS retirement change is introduced.

The host arming check extracts the actual function, holds DMA off, checks the
primed first byte and exact complete/short byte streams, preserves RX extents and
source buffers, and repeats after simulated FIFO/DMA reset. It covers all-zero
startup and invalid build guards. Missing preload, duplicated prefix and early
enable controls must fail. Reset itself is simulated; the existing separately
tested retirement fixture stubs arm. Thus these checks do not claim an integrated
physical retire-to-first-clock test or a reproduction of silicon behavior.

## Rebuild offline

Use the shared runner from the implementation source, with a passing typed review
for the exact base/head. A fresh external directory is required:

```text
python firmware/tools/build_imu_software_candidate.py --mode candidate --profile mixed-diagnostic --experiment spi-tx-prime-ab --validation-scope master --fixed-bundle PATH_TO_SEALED_R5 --review-base REVIEWED_BASE --review-result REVIEW_JSON --output-dir FRESH_EXTERNAL_DIRECTORY
```

The explicit master scope runs the complete common/master native suites and
candidate-runner checks; unchanged logger/node image bytes are verified and
copied. It omits logger/node/analysis suites and A8/node target rebuilds rather
than claiming them as newly passed. Both master target builds use `-B`; the runner
retains separate artifacts, stack reports, source archive and failure logs.
This command accesses no device. Normal builds default to `SPI_TX_PRIME=0`;
priming1 is restricted to an explicit first-recording v2 build.
