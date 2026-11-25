# Mixed-load acquisition: primary-source research

Research date: 12 November 2026. Scope: scheduling buffered remote CAN-FD
streams alongside local analog, UART and I2C acquisition; local buffering;
ADC architecture alternatives; independent output rates. This is research and
an evaluation framework, not a hardware selection or a qualified workload.

## Context and evidence boundaries

The user subsequently specified an aggressive target of eight analog sensors at
500 Hz or four at 1 kHz, plus UART GPS at 25 Hz and two I2C rotary sensors at
500 Hz each. Alignment within one or two periods of each local source is adequate.
The preferred order is firmware changes, then master hardware changes, then
logger hardware changes. The main review applies these constraints to the
alternatives below; this shortlist does not imply a simultaneous ADC or a logger
PCB revision is necessary.

GPS hardware remains unidentified, so 25 Hz is a selection requirement rather
than an assumption about the existing DAN-F10N driver. AS5600 is the representative
rotary sensor. Its fixed 0x36 address conflicts with the A8 fuel gauge on bus0;
two such sensors need isolated addresses/branches. The main review evaluates an
external bus1 mux before moving rotary acquisition to new master hardware.
[AS5600 datasheet](https://www.infineon.com/assets/row/public/documents/30/49/infineon-as5600-datasheet-en.pdf),
[TCA9548A switch example](https://www.ti.com/lit/ds/symlink/tca9548a.pdf).

The architecture-review handoff identifies an ESP32-S3 A8 logger, two ADS1220
single-shot multiplexed ADCs sharing SPI with an MSPM0G3518 CAN-FD master,
and SD_MMC on a separate interface. Active implementation evidence is in
`C:/Users/benco/dev/BODAQS-worktrees/imu-first-recording-design`, reviewed at
commit `d7e286d53f987444131738ec0ef6c9b2e9d258cf`. Its ADRs 0002–0004 and
`docs/firmware/CAN-FD_First_Real_IMU_Recording_Design.md` distinguish accepted
design changes, transport experiments and real acquisition. The canonical
checkout used for this note has older bootstrap documentation: its 84-byte,
4 MHz probe protocol must not be mistaken for the active measurement transport.

The review handoff reports production use of 256-byte transactions,
requested 16 MHz and ACK/fetch, a synthetic transport result of
223.773 kB/s, and a real one-IMU plus two-ADC 500 Hz result. Those are project
observations to audit in the main architecture review, not results established
by external literature or independently reproduced here. Synthetic throughput
does not qualify native ingress, SD persistence, four nodes, or other ADC profiles.

The A8 schematic/netlist and active BoardProfile/AnalogInputManager inspected
for the main review identify single-ended analog sensors powered by a 3.0 V
excitation/reference rail, 3.3 V digital supply, 100 ohm/10 nF input networks,
and a current 24-bit-to-12-bit nonnegative software conversion. This makes
reference tracking, full input swing and timing at least as relevant as nominal
ADC resolution. No requirement for retaining 24-bit readings is assumed.

The existing [BDQ v2 contract](BDQ_v2_Multi_Stream_Contract.md) already separates
streams, native clocks and timing observations. Its current primary-row behavior
does not imply that local sensors already have independent native streams.
The [October I2C experiment](I2C_Scheduling_Experiment_Summary_2026-10-10.md)
is local evidence that smaller FIFO reads can increase setup costs and degrade
timing observations even when continuity improves. Neither document establishes
timing bounds for the new mixed SPI workload.

## Conclusions supported by the research

- A mixed buffered/unbuffered logger is an established scheduling problem with
  multiple deadlines and queues. A global row rate is insufficient to describe it.
- Buffering helps only downstream of the point where a reading is actually
  captured. An ESP32 RAM queue cannot recover an analog conversion or overwritten
  sensor register that the acquisition worker never obtained.
- Simultaneous conversion removes multiplexing skew and conversion sharing;
  it does not imply a FIFO deep enough to tolerate long SPI transactions.
- Higher ADC rates can make the shared-bus deadline harder even when aggregate
  bandwidth remains adequate. Dedicated capture hardware or a second bus can be
  more useful than increasing converter speed alone.
- Per-channel acquisition and output rates are feasible, but they need explicit
  timing, filtering, queue and data-format contracts. Independent output rates
  do not automatically mean independent hardware converter rates.

The following sections give the primary-source basis and distinguish mathematical
models from BODAQS-specific engineering deductions.

## Independent scheduling results and their limits

### Nonpreemptive service: average utilization is insufficient

Jeffay, Stanat and Martel's original 1991 paper studies independent periodic or
sporadic tasks on one processor, with execution cost `c`, minimum recurrence `p`,
deadline equal to `p`, no preemption and no inserted idle time. It gives
utilization and interval-demand conditions; utilization alone cannot guarantee
deadlines. Its EDF universality result is restricted to the paper's task-set
model and scheduling class, not all offset-constrained concrete periodic
schedules. [Original author-hosted paper, Sections 2 and 4–6](https://www.cs.unc.edu/~jeffay/papers/RTSS-91.pdf).

**BODAQS application:** a shared SPI bus is one serial resource even on a
dual-core ESP32. Once started, a transaction blocks another device. Model an
ADC service action and a bounded master transfer as jobs, with measured resource
occupancy and release jitter. Conversion time outside SPI ownership is a separate
resource stage. A device mode change, bus lock held across several transfers, or
driver queue that commits future transfers changes the blocking model. The paper
does not prove that adding EDF to the current loop makes it schedulable.

Davis, Burns, Bril and Lukkien corrected the original CAN response-time analysis:
earlier analysis could declare a workload safe that missed deadlines. Use the
revised analysis rather than an unqualified first-message recurrence or a
preemptive CPU utilization bound. [Authors' publication record](https://www.cs.york.ac.uk/rts/publications/Davis2006a.html),
[published paper and DOI](https://link.springer.com/article/10.1007/s11241-007-9012-7).

**Applicability limit:** this work concerns classical CAN fixed-priority message
arbitration and its modeled release/queue behavior. CAN-FD needs its own frame
transmission times, arbitration/data phases, stuffing and error assumptions.
An ESP32 SPI polling scheduler and a FIFO inside the master are additional
resources; CAN priority does not automatically prioritize those stages. A
complete guarantee must cover every stage and actual controller queue discipline.

### Buffer bounds: traffic envelopes and guaranteed service

Le Boudec and Thiran bound queue backlog by the maximum vertical distance
between arrival curve `alpha` and service curve `beta`, and virtual delay by
their maximum horizontal distance. For an affine arrival envelope
`alpha(t) = b + r*t` and rate-latency service `beta(t) = R*max(0,t-L)`, with
`R >= r`, the bounds simplify to:

```text
backlog <= b + r*L
FIFO delay <= L + b/R
```

Here `b` is burst size, `r` sustained arrival rate, `R` guaranteed service rate,
and `L` worst service latency. FIFO/order preservation is required to interpret
virtual delay as each item's delay; packetization must be represented consistently.
The envelopes must hold for all relevant intervals, not just on average.
Series service curves compose by min-plus convolution. [Authors' book,
Sections 1.2–1.4, especially Theorems 1.4.1, 1.4.2 and 1.4.6](https://leboudec.github.io/netcal/latex/netCalBook.pdf).

**BODAQS deduction:** record separate queue occupancy and guaranteed service for
sensor FIFO, node retention, master retention, ESP32 acquisition queues and SD
queues. A slow downstream stage can fill an upstream queue through credits or
acknowledgments. A bound for one queue does not establish another queue's safety.
If the system cannot establish finite `L` or arrivals can indefinitely exceed
guaranteed service, no finite RAM allocation proves lossless operation.

Illustrative arithmetic, not a measured budget: four six-axis `int16` IMUs at
3333 Hz generate `4*3333*6*2 = 159,984` raw bytes/s before envelopes, timing,
checksums or logging metadata. A completely unserved 100 ms interval therefore
accumulates about 16 kB of raw IMU readings; 250 ms accumulates about 40 kB.
This is buffer demand at the stage actually blocked, not necessarily ESP32 RAM.
If service resumes at 200 kB/s while ingress continues at 160 kB/s, draining a
16 kB backlog takes another 400 ms. A 100 ms blackout and eventual recovery
are therefore different from meeting a 100 ms acquisition-to-RAM latency target.

### Freshness and complete history are different objectives

Costa, Codreanu and Ephremides analyze a single status-update link with random
arrivals and exponential service, including discard-on-busy, one waiting packet,
and replacement by a newer waiting packet. They explicitly exclude a penalty
for discarded samples and point out that consecutive samples may be valuable
for estimation. Their results concern freshness at a receiver; they do not
justify dropping raw measurement history in a logger. [Original author-submitted
paper, Introduction and Sections II–IV](https://arxiv.org/html/1506.08637).

Sun and coauthors analyze a source that can generate updates when desired,
with observed delivery and a stationary ergodic Markov transmission-time model,
an age penalty and an optional average update-frequency constraint. Sending a
new reading immediately after every delivery is not always age-optimal under
that model. This is not a prescription to introduce sampling gaps into a
fixed-ODR vibration recording. [Original author-submitted paper, Sections III–V](https://arxiv.org/html/1601.02284).

**BODAQS deduction:** use a loss-accounted historical queue for recording and
optionally a latest-value view for UI/control. Track acquisition time/sequence,
availability time and record-write time separately. Repeating a cache entry in
a later row does not make the measurement newer. Conversely, a delayed but
correctly timestamped FIFO batch can preserve useful vibration history despite
being unsuitable for a low-latency live display.

## A practical mixed-load model

This is a proposed evaluation method, not a claim about the implemented scheduler.

For each source, specify effective acquisition rate, minimum recurrence or
burst envelope, sample size, capture timestamp semantics, permissible acquisition
jitter, maximum acquisition-to-RAM delay, queue capacity, overflow policy and
recovery behavior. Separately measure CPU execution, wire occupancy and time for
which a software lock excludes another client. SD_MMC's separate pins remove
SPI wire contention, but CPU, memory and interrupt delays still need measurement.

| Work | Deadline origin | Useful buffering | What still needs prompt service |
|---|---|---|---|
| ADS1220 single-shot channel | Required conversion-start/read cadence and freshness | RAM after completed reads | Start next conversion, collect and identify the result |
| Free-running ADC with shallow results storage | Time before result storage overwrites | Small hardware results buffer, then RAM | Read every result before overwrite |
| FIFO I2C IMU | FIFO headroom, timestamp-anchor requirements | Sensor FIFO, host batch queue | Bounded FIFO drains and useful timing observations |
| I2C register-only sensor | Requested observation cadence and device update behavior | RAM after reads | Read at the intended times; later reads cannot reconstruct prior register contents |
| UART stream | RX FIFO/ring headroom and parser deadlines | Hardware RX FIFO and driver ring | ISR/receiver must keep up before host-level queues help |
| Remote CAN-FD stream | Node/master headroom, acceptance deadline, authorization/control deadlines | Every explicitly budgeted retention stage | Fair, bounded useful drain service and control completion |

A useful scheduler candidate gives ADC starts/reads explicit deadlines, gives
each remote participant bounded service, and dispatches a bounded eligible job
at each transaction boundary. Deadline urgency may increase as FIFO headroom
shrinks. Reserve service for mandatory control and timing observations; cap
empty polls, retries and failed-device work. A single permanently failing
participant must not consume the service reserved for healthy streams.

For a steady producer with known occupancy `Q`, capacity `F`, margin `M` and
arrival rate `r`, `(F-Q-M)/r` is a first estimate of available headroom time.
Use an arrival envelope, oscillator tolerance and stale-occupancy allowance for
a conservative deadline. The estimate does not include time already queued or
the time to complete the drain. Polling without an interrupt requires a bounded
discovery interval, including when the previous poll found no work.

Do not hold the shared SPI lock while an ADS1220 converts, waits for its next
poll, or while a master-specific turnaround guard elapses if another device can
legally use the wires. Conversely, include a guard in blocking if the actual
implementation holds the lock throughout it. Batching can reduce per-reading
setup overhead while increasing the longest blocking interval: optimize both,
then validate freshness and queue bounds simultaneously.

## What local buffering can change

1. **RAM queue after today's polling:** separates acquisition from formatting and
   SD writes, retaining already acquired readings. It leaves ADC start jitter,
   mux sequencing and shared-bus contention in the capture path.
2. **Autonomous sequencer with hardware FIFO:** continues acquisition while the
   host serves CAN. It transfers the deadline to FIFO drain, subject to converter
   sequencing/settling limits and finite headroom.
3. **Simultaneous ADC plus peripheral DMA:** captures all channels at a common
   hardware cadence and transfers results with less CPU work. It still needs an
   appropriate trigger/read mechanism and enough pre-RAM storage to survive bus
   contention. A DMA-capable SPI peripheral is not itself an ADC FIFO.
4. **A dedicated local acquisition MCU:** can own timing, mux sequencing and a
   larger queue, presenting batches like a remote node. This moves the timing
   problem to a smaller collector and adds clock correlation, firmware, flow
   control and hardware cost. Sharing the same downstream SPI still requires an
   aggregate transport budget.

Espressif's UART driver documents RX buffering and separate FIFO-overflow and
RX-buffer-full events. Preserve these distinctions in diagnostics: increasing a
software ring cannot undo an overflow that occurred before its ISR copied data.
[Official ESP32-S3 UART guide](https://docs.espressif.com/projects/esp-idf/en/v5.2/esp32s3/api-reference/peripherals/uart.html).

## ADC architecture shortlist

These are comparison cases, not purchase recommendations. Consult the cited
revision's electrical tables, not just feature-page sample rates. None is a
drop-in replacement for the A8 wiring/reference arrangement.

| Family | Primary-source capability | Scheduling benefit | Important fit/limit |
|---|---|---|---|
| Existing ADS1220 | One mux converter; two differential/four single-ended inputs; up to 2 kSPS in turbo mode; single-shot timing includes wake/start effects | Retains existing ratiometric design; two chips can convert concurrently between bus commands | Per-channel rates share each converter; mux, configuration and software delays consume cadence. [TI Rev. D, Sections 8.3.7 and 8.4](https://www.ti.com/lit/ds/symlink/ads1220.pdf) |
| ADS131M08 | Eight simultaneous differential channels, 24-bit words, up to 32 kSPS, common OSR/clock setting; two results buffered per channel | Eliminates interchannel mux time; predictable channel frames | Shallow FIFO; normally ten SPI words per frame. Internal-reference input span is approximately +/-1.2 V at gain 1, not 0–3 V. External reference is nominally 1.25 V, so preserving A8 ratiometry needs a new signal/reference design. [TI Rev. B, Sections 8.3.3–8.3.5 and 8.5.1.7–8.5.1.9.1](https://www.ti.com/lit/ds/symlink/ads131m08.pdf) |
| ADS131E08 | Eight simultaneous channels; 1–64 kSPS settings; **16-bit output at 32/64 kSPS**, 24-bit through 16 kSPS | More simultaneous precision channels without mux sharing | Common data rate; filter delay and result-read deadlines remain. Differential/common-mode and reference-drive requirements need checking for grounded 0–3 V sensors. Approximately 2 mW/channel headline, 64-pin package. [TI Rev. C, Sections 9.4, 9.5 and Table 13](https://www.ti.com/lit/ds/symlink/ads131e08.pdf) |
| ADS8588S / ADS8598H SAR family | Eight simultaneous channels; 16-bit/200 kSPS or 18-bit/500 kSPS; +/-5 V or +/-10 V inputs, 5 V analog supply, serial/parallel interfaces | Hardware conversion trigger; integrated input drivers; avoids mux skew and permits much higher acquisition rates | Industrial bipolar ranges use only part of their span for A8's 0–3 V sensors. Reference tracking, power, package/pins and transfer bandwidth need redesign; optional oversampling adds timing/filter tradeoffs. [ADS8588S Rev. A](https://www.ti.com/lit/ds/symlink/ads8588s.pdf), [ADS8598H](https://www.ti.com/lit/ds/symlink/ads8598h.pdf) |
| AD4130-8 autonomous mux/FIFO example | One 24-bit converter; up to 16 single-ended/eight differential inputs; sequencer; up to 2.4 kSPS on a settled channel; **256 conversion results total**, optional per-result channel header | Actual on-chip batching reduces host visit frequency | Not simultaneous; channel changes require front-end and digital-filter settling. Repeat conversions amortize switching but create bursts/gaps per channel. Compatible reference arrangements still require electrical review. [ADI Rev. A, ADC Configuration, Digital Filters and FIFO sections](https://www.analog.com/media/en/technical-documentation/data-sheets/ad4130-8.pdf) |

**ADS1220 timing deduction:** Table 8-4 gives normal-mode 1000-SPS single-shot
conversion time as 4242 cycles at 4.096 MHz, approximately 1.036 ms, with up to
50 us additional internal-oscillator wake time. Turbo 2000-SPS single-shot is
2130 cycles, approximately 0.520 ms, with up to 25 us wake time. These are
converter timing components, excluding host scheduling/configuration/read time;
the requested row rate is not either converter's guaranteed fresh result rate.
[TI conversion-time table and accompanying text](https://www.ti.com/lit/ds/symlink/ads1220.pdf).

**AD4130-8 caution:** minimum channel-change front-end settling is 32 master
clocks, approximately 416.6 us at 76.8 kHz, before filter first-conversion and
postprocessing costs. Its 2.4 kSPS headline therefore cannot establish two
500 Hz channels or eight 500 Hz channels. At an aggregate 2400 results/s,
256 results represent about 106.7 ms of empty-to-full storage; real headroom is
less once occupancy, watermark, drift and drain time are included. This is
aggregate storage, not 256 samples for every input. [ADI Tables 63–65 and FIFO
register descriptions](https://www.analog.com/media/en/technical-documentation/data-sheets/ad4130-8.pdf).

### Shared-bus calculations expose the important tradeoff

The following are derived lower bounds, not achieved timings. Assume the SPI
clock is actually 16 MHz and a master physical transfer is 256 bytes. The wire
time is `256*8/16e6 = 128 us`, before setup, chip-select and processing costs.
A requested clock must be measured on the board before using it in a bound.

For the ADS131M08's normal ten-word, 24-bit frame, wire demand is:

| Acquisition rate for eight channels | SPI frame rate | Frame traffic | Fraction of a 16 MHz wire |
|---:|---:|---:|---:|
| 4 kSPS/channel | 4000/s | 120 kB/s | 6% |
| 16 kSPS/channel | 16000/s | 480 kB/s | 24% |
| 32 kSPS/channel | 32000/s | 960 kB/s | 48% |

Under a two-slot model, an initially empty FIFO with an arrival immediately after
service fills on the next two arrivals and needs space before the third, two
periods later. This gives idealized horizons of 500, 125 and 62.5 us respectively;
existing occupancy and read completion reduce the usable allowance. At 16/32 kSPS,
a single 128 us master transfer can exceed this horizon; read execution and
other work make it worse. At 4 kSPS it may fit, but average wire occupancy and
this comparison do not prove the complete schedule. This follows from the
specified shallow storage, not a measured ADS131M08 failure in BODAQS.
It is not a manufacturer-qualified two-period interrupt-latency guarantee:
TI also requires special double-read or synchronization handling after a pause,
and a driver must preserve sample association and predictable DRDY behavior.

SAR headline rates can exceed the proposed shared link even before control
traffic: `8*16*200000 = 25.6 Mbit/s` for ADS8588S and
`8*18*500000 = 72 Mbit/s` for ADS8598H. These are raw sample-bit minima, not
serial timing qualifications. Dual-output or parallel read modes can alter the
physical interface budget; they require appropriate ESP32 wiring, peripheral
support and firmware. Operating these converters much slower is a valid option.

For ADS131E08, eight-channel readback is 216 bits/frame at 24-bit settings and
152 bits/frame at 32/64 kSPS. Disabling channels does not shorten the ordinary
frame. Thus setting lower output rates in the logger alone does not necessarily
save ADC SPI traffic. [TI readback-length section 9.4.5.4](https://www.ti.com/lit/ds/symlink/ads131e08.pdf).

## ESP32-S3 capture capabilities and limits

The official ESP32-S3 SPI guide identifies SPI2 and SPI3 as independent general
purpose controllers; SPI0/1 serve memory. It supports DMA and queued transactions
but explicitly defines transactions as atomic. Small-transfer performance includes
setup, queues and ISR costs, not just clock rate. Polling trades lower overhead
for CPU occupancy. A second available and routable controller can remove ADC/CAN
wire contention, subject to the actual board's pin and memory configuration.
This is a board-change option, not a claim that A8 can reroute its existing
shared traces. [Official versioned SPI guide](https://docs.espressif.com/projects/esp-idf/en/v4.4.7/esp32s3/api-reference/peripherals/spi_master.html).

ESP32-S3 has two I2S peripherals, with standard and TDM receive capability and
DMA buffering. The target table marks built-in I2S ADC/DAC mode unsupported
on S3. I2S can capture a compatible external I2S/TDM ADC; an arbitrary
SPI/DRDY ADC does not become compatible merely because it emits serial bits.
The guide sizes DMA descriptors using frame rate, slot count and the maximum
read-service interval, with a 4092-byte per-buffer limit in this documented
driver. [Official I2S guide, target table and data-loss guidance](https://docs.espressif.com/projects/esp-idf/en/v5.2/esp32s3/api-reference/peripherals/i2s.html).

The separate on-chip ADC continuous driver supports conversion patterns, DMA
results and an internal result pool; it reports pool overflow if consumption
lags. This is an alternative capture architecture, not proof of adequate analog
accuracy, simultaneity or a drop-in replacement for external ratiometric inputs.
[Official ADC continuous guide](https://docs.espressif.com/projects/esp-idf/en/v5.2/esp32s3/api-reference/peripherals/adc_continuous.html).

These links deliberately identify ESP-IDF versions. Before implementation,
match APIs, DMA memory requirements, supported modes and Arduino integration to
the exact framework/toolchain in the chosen BODAQS environment. A newer API in
documentation is not evidence that the current Arduino driver uses it. DMA
reduces CPU copying; it does not prove bounded interrupt latency or remove bus
and memory contention.

In the Arduino-ESP32 2.0.17 HAL identified by the main review,
`spiTransferBytes` and `spiTransferBytesNL` move data through FIFO-sized chunks
of at most 64 bytes and poll transfer completion. The ordinary locked function
retains its mutex across the chunk loop. Those internal chunks do not establish
256-byte protocol-level preemption points; chip-select ownership and the
application lock remain decisive. Moving to the ESP-IDF queued/DMA interface is
a candidate driver change requiring benchmark and concurrency validation, not
an optimization already supplied by this HAL path. [Official tagged source](https://raw.githubusercontent.com/espressif/arduino-esp32/2.0.17/cores/esp32/esp32-hal-spi.c).

## Independent per-channel output rates

Separate four quantities: requested configuration, effective hardware conversion
rate, delivered distinct readings, and output row/record rate. For a mux ADC,
per-channel rates compete for the same conversion/settling budget. For common-rate
simultaneous ADCs, acquire at one hardware cadence and derive lower-rate channel
outputs using filters; separate device clocks or independently configurable
converters are needed when the hardware itself must run at different rates.

For equal round-robin service on one converter, an idealized upper bound is
`f_channel <= f_aggregate/N`. In real single-shot operation,
`period_per_channel = sum(conversion + channel-change + read/start + scheduling
delay for every visit in its cycle)`. Weighted visits can give different averages,
but increase some channels' longest gaps; qualify both rate and maximum interval.
Two independent converters have separate conversion budgets even though their
SPI actions still contend.

The reported example of about 500 distinct readings/s per channel emitted into
700 rows/s implies at least `(700-500)/700 = 28.6%` reused rows in sustained
steady state, assuming one new reading is used at most once and no initial
backlog. Bursts, phase alignment and discarded intermediate readings can make
the result worse. A per-channel RAM FIFO cannot create the missing conversions;
emitting 500 native records/s can describe the available evidence honestly.

Three explicit output policies serve different purposes:

- Retain every distinct native reading with sequence and acquisition timing;
  process or resample later. This best preserves measurement evidence.
- Produce a slower derived channel after filtering, documenting cutoff, phase,
  delay, decimation ratio and discontinuity handling.
- Expose a latest-value snapshot with source sequence/time and age. Repeats can
  be meaningful for display or legacy rows, provided they are identifiable.

Sampling requires controlling out-of-band energy before irreversible aliasing.
Higher acquisition rates can relax analog filter transition requirements, but
downsampling still needs a filter appropriate to the new Nyquist band. Taking
every Nth raw sample or copying a cache into sparse rows is not, by itself,
an adequate decimator. [Walt Kester's manufacturer-authored sampling tutorial](https://www.analog.com/media/en/training-seminars/tutorials/MT-002.pdf).

For the reviewed A8 schematic's 100 ohm/10 nF input network, the isolated RC pole is about
159 kHz. That calculation alone cannot characterize the complete sensor/ADC
anti-alias response; sensor bandwidth, source impedance, converter digital
filter and any additional network also matter. Lower-rate outputs do not repair
aliasing already introduced during acquisition.

## Evidence needed for an architecture decision

Record a workload table covering channel counts, requested/effective rates,
ADC mode, native payload, timing-observation traffic, CAN load, SPI profile,
queue sizes, storage representation and acceptance deadlines. Compare ADC-only,
remote-only and mixed operation at the same settings, including the four-node
target separately from the demonstrated one-node milestone.

Measure actual SCK and chip-select durations; complete lock-ownership intervals;
conversion-start/DRDY/read timestamps; fresh sequence rate and repeated rows;
maximum inter-acquisition gaps; useful accepted payload per interval; empty
polls, retry/control/timing costs; per-stage occupancy/high-water/drop counters;
and SD stall duration. Include startup, STOP/drain and one failed or slow device.
Use a changing input or sequence instrumentation: equal analog values do not
prove cache reuse, and differing values do not establish correct sampling time.

For FIFO hardware candidates, test worst-phase interference against a full
master transfer, not just a favorable aligned run. For any new ADC, validate
0–3 V range/common-mode margins, ratiometric reference loading, source settling,
noise at the chosen rate, anti-alias response, power and input fault behavior.
Simultaneous electrical sampling still requires documenting filter group delay
and cross-device clock relationships for phase comparisons.

Measured maxima and percentiles are evidence within their tested conditions.
A deterministic service curve requires a justified bound under the declared
failure and workload envelope. Report an empirical envelope as such when a
hard bound is unavailable. No firmware build, host test or datasheet maximum
substitutes for this on-device qualification.

No firmware/hardware was modified, flashed or qualified by this research.
