# CAN-FD IMU acquisition and timing research

Research date: 4 November 2026. Scope: exact **LSM6DSO32XTR** on the production
MSPM0G3507 IMU node. This is primary-source evidence for the open acquisition
interview, not an implementation, timing qualification, or new design decision.
No device or fault tests were performed.

## Binding project context

[The network contract, sections 13.11–13.17](CAN-FD_Network_Protocol.md) owns the
accepted answers. The initial `profile1v1` uses both native nominal 3333 Hz modes
(ODR code 9), ±32 g, ±2000 dps, high performance, optional acceleration LPF2 and
gyro LPF1 bypassed, and high-pass filtering off. Enabled-but-stopped engines
continue running while FIFO/timestamp collection is off. Historical proposals
in [the configuration research](CAN-FD_IMU_Configuration_Research.md) do not
override those decisions.

Q71–Q77 allow recovery only once native pairing/timing are trustworthy; require
observable loss boundaries; set a **target**, still unverified, of at most 10 µs
relative inter-node uncertainty from capture/reconstruction; allow Preparing
with discarded samples and no pre-roll; prioritize acquisition; retain raw data
under degraded inter-node alignment; drop the newest complete software batch
on queue overflow; and release master batches only after logger RAM acceptance
with duplicate suppression. RAM acceptance does not mean SD persistence.

[The production wiring table](CAN-FD_Sensor_Network_Design.md) gives SPI
CS/PICO/POCI/SCK on PA8/PA9/PA10/PA11, INT1 on PA3, INT2 on PA22, and trunk SYNC
on PA25/TIMA0_C3. A direct trunk SYNC connection to the sensor is **not
established**. No conclusion below assumes one.

## Primary-source record

Only exact-part ST material and TI device/timer material support hardware claims:

- [ST DS13607 Rev 1](https://www.st.com/resource/en/datasheet/lsm6dso32x.pdf),
  especially §§6.4–6.5, FIFO/status/tag register tables, and §9.41.
- [ST AN5640 Rev 2](https://www.st.com/resource/en/application_note/an5640-lsm6dso32x-alwayson-3axis-accelerometer-and-3axis-gyroscope-stmicroelectronics.pdf),
  especially §§4.3, 4.8, 6.4, 8.2, 8.4–8.5 and 8.11.
- ST exact-part C driver, revision
  `c2787664e60c19a9947858832fef90625811be15`, resolved from upstream HEAD on
  the research date: [header](https://github.com/STMicroelectronics/lsm6dso32x-pid/blob/c2787664e60c19a9947858832fef90625811be15/lsm6dso32x_reg.h)
  and [implementation](https://github.com/STMicroelectronics/lsm6dso32x-pid/blob/c2787664e60c19a9947858832fef90625811be15/lsm6dso32x_reg.c).
- [TI SLASEX6C, October 2025](https://www.ti.com/lit/ds/symlink/mspm0g3507.pdf),
  Table 6-2 and timer summary.
- [TI SLAU846, June 2023, official TI-hosted copy](https://e2e.ti.com/cfs-file/__key/communityserver-discussions-components-files/908/MSPM0-G_2D00_Series-TRM.pdf),
  §§23.2.3.1–23.2.3.1.2.1. The current
  [TI TRM URL](https://www.ti.com/lit/ug/slau846/slau846.pdf) exceeded the browser's
  document-size limit; the cited historical revision was inspected. Reconcile
  these timer details against the current revision before implementation.

## FIFO identity, order, pairing and timestamp evidence

DS13607 establishes seven-byte FIFO words (tag plus six data bytes), a word
count in `DIFF_FIFO`, selectable timestamp batching factors 1/8/32, and a 32-bit
timestamp with nominal 25 µs resolution. Continuous mode overwrites oldest
words; FIFO mode stops when full; bypass resets FIFO contents. Overrun means at
least one old sample was overwritten. Gyro filtering includes a mandatory LPF2
whose response differs from acceleration filtering. These statements concern
storage and filtered output, not simultaneous physical sampling.
[DS13607 §§6.4–6.5, §9.41](https://www.st.com/resource/en/datasheet/lsm6dso32x.pdf).

The exact driver header defines `tag_sensor` in bits 7:3, `tag_cnt` in 2:1 and
`tag_parity` in bit 0. Sensor tags are gyro noncompressed=1,
acceleration noncompressed=2, temperature=3, timestamp=4 and configuration
change=5; compressed/delayed and external-sensor tags also exist. Timestamp
batching selectors explicitly separate disabled, decimation 1, 8 and 32.
[ST exact-part header, `lsm6dso32x_fifo_data_out_tag_t`, `lsm6dso32x_fifo_tag_t`, `lsm6dso32x_odr_ts_batch_t`](https://github.com/STMicroelectronics/lsm6dso32x-pid/blob/c2787664e60c19a9947858832fef90625811be15/lsm6dso32x_reg.h).

AN5640's two-bit counter identifies slots at the fastest main BDR; timestamp
words describe slots and are inserted on main/external events. Figure 23 shows
gyro then acceleration writes. Equal-rate slots do not specify analog phase.
§8.11 says timestamp-every-slot overrun recovery discards words before the next
timestamp; counter-only reconstruction is discouraged with overruns. DRDY marks
available output; pulsed DRDY lasts 75 µs. Timestamp wraps at 32 bits; both
engines powered down freeze it.
[AN5640 §§4.3, 6.4, 8.4–8.5, 8.11](https://www.st.com/resource/en/application_note/an5640-lsm6dso32x-alwayson-3axis-accelerometer-and-3axis-gyroscope-stmicroelectronics.pdf).

The C driver resets timestamp by writing `AAh` to `TIMESTAMP2`; enabling it uses
`CTRL10_C.TIMESTAMP_EN`. `timestamp_raw_get` reads four bytes little-endian.
`fifo_sensor_tag_get` returns sensor identity, omitting counter/parity from its
API result. `fifo_out_raw_get` reads six payload bytes. `odr_cal_reg_get`
documents signed two's-complement `FREQ_FINE` with 0.15% steps describing ODR
and timestamp-rate deviation. The driver supplies register access rather than
a complete FIFO-slot-to-host-time reconstruction algorithm.
[ST exact-part C implementation, named functions](https://github.com/STMicroelectronics/lsm6dso32x-pid/blob/c2787664e60c19a9947858832fef90625811be15/lsm6dso32x_reg.c).

**Implications and gaps:** Pair using validated identity and reconstructed slot
context, not alternating read positions. Figure 23 supports understanding the
write sequence; it is not a sufficient contract for assuming adjacent words
always form a complete six-axis sample after startup, loss or reconfiguration.
Keep the complete raw tag if counter/parity evidence matters. A two-bit slot
counter alone cannot distinguish arbitrary multi-slot losses.

The reviewed evidence does not establish a numerical bound for acceleration
versus gyro conversion phase, output-ready delay, or group-delay mismatch at
`profile1v1`. Same ODR, same FIFO slot, and simultaneous SPI readout each need
separate interpretation. Do not call a slot timestamp a proven common analog
measurement instant.

Nominal wrap duration is a calculation: `2^32 * 25 µs = 107374.1824 s`
(about 29.83 hours). Distinguish wrap from intentional reset, device reset,
disabled counter, and lost evidence; a backward value alone cannot establish
which happened. An SPI timestamp-reset write is not evidence of an exact
physical sampling epoch. No reviewed guarantee relates the reset transaction
edge to the next acceleration/gyro sample with a stated uncertainty.

## DRDY hardware capture and sample-time authority choices

TI's exact G3507 pin table supports PA3/TIMA0_C2, PA22/TIMA0_C1 and
PA25/TIMA0_C3, each using pin function 5. Thus the documented wiring permits
three separate channels on one timer at the pin/peripheral level. TIMA0 is
16-bit, so an extended epoch needs wrap handling.
[TI SLASEX6C Table 6-2 and timer summary](https://www.ti.com/lit/ds/symlink/mspm0g3507.pdf).

TI capture mode records the counter on an event and supports selected edge
polarity. CCP input always passes through synchronization: the input state must
last longer than one TIMCLK; the first clock has timing uncertainty; capture
requires an additional TIMCLK cycle. Input filtering is configurable.
[TI SLAU846 §§23.2.3.1–23.2.3.1.1](https://e2e.ti.com/cfs-file/__key/communityserver-discussions-components-files/908/MSPM0-G_2D00_Series-TRM.pdf).

**Inference:** Capturing INT1, INT2 and trunk SYNC against the same timer is a
credible mechanism for investigating output-ready-to-SYNC timing. This is
hardware routing feasibility, not measured accuracy. Configuration, timer
clock/prescaler, pin direction, debug/low-power behavior, wrap extension,
capture consumption and missed-event detection remain implementation work.
Reading a timer inside a GPIO ISR additionally includes interrupt latency;
it must not silently be substituted for peripheral capture evidence.

The authority choice remains open:

| Candidate authority | What it could establish | Evidence still needed |
|---|---|---|
| Native FIFO timestamps mapped to MCU time | Buffered order and sensor-clock progression, with host synchronization anchors | Sensor-clock-to-MCU mapping, quantization/error model, phase/drift tracking, loss and reset epochs |
| Captured per-sensor DRDY mapped to FIFO slots | MCU-clock time of each routed output-ready edge relative to SYNC | Unique slot association across startup and loss, missed capture handling, output-ready versus measurement delay |
| Native timestamp plus DRDY/SYNC captures | Independent anchors and consistency checks | A defined estimator, uncertainty bounds, rejection rules and complete provenance |
| DEN marking/selection | Possible identification of samples associated with an external event | Safe signal ownership, mode compatibility and any missing quantitative timing bounds |

These are research options, not a selected design. A 25 µs native tick alone
does not demonstrate a 10 µs relative timing bound. It also does not prove the
target impossible if additional independently justified timing evidence is
used. Capture resolution alone cannot establish the entire sample-time error.
For illustration, 10 µs corresponds to 3.6 degrees at 1 kHz; this arithmetic
does not account for sensor/filter phase.

## Interrupt routing and FIFO servicing resource constraints

Both acceleration and gyro DRDY may route to either INT output. Selected
sources on a given output are combined by logical OR. The FIFO watermark
remains asserted while occupancy is at or above the threshold, so sharing it
with DRDY can mask subsequent DRDY transitions. Reading status later identifies
causes but cannot recover masked edge times.
[DS13607 sections 9.9-9.10](https://www.st.com/resource/en/datasheet/lsm6dso32x.pdf),
[AN5640 sections 4.3, 5.1 and 8.2](https://www.st.com/resource/en/application_note/an5640-lsm6dso32x-alwayson-3axis-accelerometer-and-3axis-gyroscope-stmicroelectronics.pdf).

Thus two separate engine DRDY outputs plus a dedicated watermark output need
three independently observable signals; the documented two-INT wiring cannot
supply all three at once. Options include one engine DRDY plus a dedicated
watermark, or separate engine DRDY outputs with bounded FIFO-status checks
that start DMA when the watermark condition is observed. Selecting one is a
design decision, not established by the earlier combined-evidence direction.

## DEN and INT2 constraints

DEN uses INT2 as input, defaults to gyro, and can extend to acceleration at
matched ODR. Edge mode selects the first subsequent sample; DEN is read before
register update, allowing next-ODR recognition. Edge/FIFO-enable modes prohibit
timestamp batching (`DEC_TS_BATCH=00`) and configuration-change batching and
require matching BDR/ODR. Stamping replaces selected data LSBs.
[AN5640 §4.8, including mode-specific limitations](https://www.st.com/resource/en/application_note/an5640-lsm6dso32x-alwayson-3axis-accelerometer-and-3axis-gyroscope-stmicroelectronics.pdf).

**Implications:** DEN is not evidence that the external edge starts an
instantaneous conversion or phase-locks the sensor clock. Its modes cannot be
combined indiscriminately with a native FIFO timestamp design. An external
marker stamped into an axis also changes that raw axis representation.

The production PA22 connection might allow an MCU-generated DEN signal, but
this would require explicitly resolving output/input ownership and safe
transitions first. INT2 is initially a low output according to AN5640's pin
status table; it must not be driven by the MCU before sensor input-mode
configuration is established.
[AN5640 pin-status table](https://www.st.com/resource/en/application_note/an5640-lsm6dso32x-alwayson-3axis-accelerometer-and-3axis-gyroscope-stmicroelectronics.pdf).
Forwarding a PA25 event through software to PA22 is an additional timing path,
not a direct trunk-to-sensor wire. No such forwarding behavior is selected here.

## Loss recovery and admission questions

The hardware overrun flag does not supply an exact missing-sample count.
`FIFO_OVR_IA` clears after a FIFO-word read; the latched overrun indicator
clears on reading `FIFO_STATUS2`. With BDU enabled, read `FIFO_STATUS1` before
`FIFO_STATUS2`.
[DS13607 FIFO_STATUS1/FIFO_STATUS2 register descriptions](https://www.st.com/resource/en/datasheet/lsm6dso32x.pdf).

**Implications for Q71:** The cited ST recovery procedure supplies a possible
resynchronization point for its timestamp-every-slot approach. It does not
prove a particular decoder, six-axis pairing policy or inter-node estimator
recovers correctly. A bounded-loss implementation would need to preserve
overrun evidence around draining, discard ambiguous words/partial pairs,
establish a new trustworthy native epoch, record the continuity boundary and
continue only under the contract's health/lease conditions. State an unknown
loss count whenever the available evidence cannot resolve it. A FIFO reset is
another discontinuity, not restoration of missing data.

Q76's software policy cannot be assumed to change sensor FIFO behavior. Q75's
alignment-degraded retention is appropriate only while native timing/order
remain trustworthy; uncertain native pairing belongs to Q71's recovery or
endpoint-exclusion decision. Logger RAM acknowledgement addresses batch
ownership, not sample-time authority.

Questions still needing a concrete design answer before implementation:

1. Is a delivered six-axis item defined by FIFO slot membership, two separately
   timed sensor outputs, or an explicitly modeled measurement-time convention?
2. Which evidence is authoritative, what is its uncertainty calculation, and
   what precisely invalidates an alignment interval or native epoch?
3. Which FIFO mode, timestamp decimation, watermark and drain envelope meet
   the actual logger service-pause budget without ambiguous recovery?
4. What sample discard and initial-anchor conditions end Preparing? Fixed
   startup/settling assumptions must account for the already-running stopped
   engines and any reset/reconfiguration; no preparation samples become pre-roll.
5. How are capture loss, timestamp wrap/reset, SPI failures, unexpected tags,
   counter discontinuity and partial pairs represented and recovered?

## Validation status and deferred work

This document was checked against the cited primary sources and the accepted
contract; it introduces no register changes or wire-format changes. No compile
or automated implementation test is relevant to this documentation-only change.

The 10 µs allocation remains unverified. Later physical work needs identified
board/firmware revisions and simultaneous observations of SYNC, both routed
DRDY signals and SPI, plus recorded native tags/timestamps/captures. It must
separate capture uncertainty from sensor phase and test the chosen mapping and
loss estimator under the actual service envelope. CAN disconnect/reconnect,
CCS halt/resume, node/master reset and broader fault bench tests remain
explicitly deferred until a practical harness is available; none is claimed
complete here.
