# Buffered ADC candidates for local acquisition

Research date: 2026-11-20. Primary-source component screening; no component selection, schematic change, or firmware implementation is implied.

## Requirement and interpretation

The working BODAQS target is an ADC serving **four channels at 500 samples/s each OR two channels at 1,000 samples/s each**: **2,000 results/s per chip**. These are alternatives, not six concurrent channels. Keep ordinary ground-referenced sensor wiring, approximately 3.0 V ratiometric excitation/reference, 3.3 V digital interfaces, and at least the 12 bits currently retained. The prospective A8 architecture needs acquisition to continue while the ESP32 services other work. Existing analog-interface context is recorded in [the A8 architecture review](A8_CAN_Master_Mixed_Load_Architecture_Review.md); its earlier scheduling measurements are not used as current timing evidence here.

A useful FIFO preserves several unread conversion results in order. A latest-value register, an averaging accumulator, and channel-sequence instruction memory do not satisfy that requirement. A FIFO also does not prove autonomous acquisition: some devices finish one commanded scan and require another trigger.

Qualification below assumes regularly interleaved sampling, rather than collecting long bursts from one channel while other channels go unmeasured. The permissible host-service delay remains a design input; FIFO capacity alone cannot establish that the complete logger will meet its deadlines. Nominal remaining capacity is `(FIFO depth − unread occupancy) / aggregate result rate`; this assumes steady acquisition and excludes transfer/response margins. A finite, fast capture burst does not automatically provide that duration of uninterrupted coverage.

## Screening result

| Candidate | Qualification for this request |
|---|---|
| ADS125P08 | Strongest investigated candidate: continuous autonomous scans and a deep result FIFO; electrical and timing details below. |
| AD4130-8 | Genuine autonomous FIFO, but fails the requested regularly interleaved multichannel rate. |
| MAX11131 | Genuine FIFO and ample conversion speed; acquisition still needs scan/conversion triggers. Conditional alternative. |
| MAX11627 / MAX11626 | Genuine FIFO and ample conversion speed; commanded scans/bursts need rearming. Conditional alternatives. |
| ADS7142-Q1 | Autonomous monitoring and a capture buffer; its buffer cannot be drained during active acquisition. Fails continuous acquisition plus background draining. |

## ADS125P08: strongest candidate to evaluate

The part offers 16 single-ended inputs, 24-bit conversion, and SPI. Continuous-sequence mode repeats without per-sample host commands. Single-ended wiring uses grounded AINCOM. [TI product page](https://www.ti.com/product/ADS125P08), [datasheet, sections 4 and 7.3.10.2.4](https://www.ti.com/lit/ds/symlink/ads125p08.pdf#page=56).

The 512-result FIFO accepts new results while the host drains batches, with programmable DRDY thresholds and CRC. Its nominal storage horizon at the target is **512 / 2,000 = 256 ms**; actual scheduling must reserve headroom for interrupt latency and draining. At a watermark of 256 results, nominal remaining headroom is **128 ms**. [TI application brief SBAA877, FIFO Buffer](https://www.ti.com/document-viewer/lit/html/SBAA877/GUID-32F03D60-8C98-46C9-B729-11A8C8FAA109).

Low-voltage feasibility follows from the actual settled-channel latency, rather than the headline maximum data rate:

| Example setting | Settled result interval with one conversion per sequence step, zero added delay | Calculated aggregate capacity |
|---|---:|---:|
| Speed mode 1, sinc3, OSR 128 | 248.4 microseconds | approximately 4,026 results/s |

Thus four channels have approximately 1,006 samples/s/channel capacity, or two have approximately 2,013. Programmable step delay can pace acquisition towards the requested 2,000 aggregate; exact settings and clock tolerance need validation. [Datasheet, Table 7-9 and section 7.3.10.5, equation 22](https://www.ti.com/lit/ds/symlink/ads125p08.pdf#page=40).

Electrical conditions matter:

- Modes 0/1 require AVDD−AVSS of 3.0–5.5 V; IOVDD permits 3.3 V.
- With AVSS=0 and AVDD=3.3 V, input buffers **on** allow −0.05 to 3.1 V: compatible in principle with ground to 3.0 V sensors.
- A 3.0 V external reference at AVDD=3.3 V requires the REFP buffer **off**; enabled REFP buffering requires 0.7 V positive-rail headroom. Verify excitation/reference drive and settling.

Use 3.3 V analog power with adequate tolerances; nominal 3.0 V excitation is at the minimum analog-supply limit. [Datasheet, section 5.3 and section 7.3.4](https://www.ti.com/lit/ds/symlink/ads125p08.pdf#page=6).

Overflow rejects subsequent results until reads free space. The documented underflow flag is unreliable after data have entered the FIFO; check overflow and bound reads by available depth, rather than reading until an underflow flag appears. [Datasheet, section 7.3.9.2](https://www.ti.com/lit/ds/symlink/ads125p08.pdf#page=49).

## AD4130-8: real FIFO, insufficient interleaved throughput

This 24-bit SPI ADC has a 256-sample FIFO and smart sequencer, with up to 16 pseudo-differential inputs, 1.71–3.6 V supplies, and external-reference support. Ground-referenced operation requires the appropriate input/PGA configuration. [ADI product page](https://www.analog.com/en/products/ad4130-8.html).

The 2,400 samples/s headline applies to an already-settled channel. For an equal-configuration scan collecting one result per channel, the fastest sinc3 setting uses FS=1, minimum settling of 32 master-clock cycles, and 96 conversion cycles. Digital postprocessing overlaps the next channel's settling. At nominal 76.8 kHz:

```text
Scan result interval = (32 + 3 × 32) / 76,800 = 1.6667 ms
Aggregate scan rate = 600 results/s
Four channels: 150 samples/s/channel
Two channels: 300 samples/s/channel
```

Long repeats on each channel can improve average throughput, but create gaps while other channels are sampled. They do not establish regular 500/1,000 Hz sampling. [AD4130-8 datasheet Rev. A, Digital Filters / Sequencer, Tables 59 and 63–66, pages 63–66](https://www.analog.com/media/en/technical-documentation/data-sheets/ad4130-8.pdf#page=65).

## MAX11131: queued scans, still needs triggers

This 12-bit, 16-channel SAR ADC provides single-ended inputs, SPI, a 16-result FIFO, 2.35–3.6 V analog supply, separate 1.5–3.6 V I/O supply, and an external reference spanning 1 V to VDD. Its conversion throughput easily exceeds the target.

The FIFO is used for internally clocked conversion sequences. CNVST or the software-conversion option starts acquisition; SWCNV must be reasserted for another operation. Repeat mode captures a finite 4/8/12/16-result burst of one channel. A custom internal scan captures selected channels. This reduces bus occupancy but does not establish a continuously self-paced multichannel logger. Hardware-timed triggers could make it useful, with extra trigger/timing design.

The **256-entry SampleSet memory stores sequence instructions, not 256 unread samples**; SampleSet operates with an external clock. FIFO overflow overwrites oldest results. At the target rate, 16 entries represent only **8 ms** of nominal history. [MAX11129–MAX11132 datasheet, Internal FIFO, Internal Clock, Repeat Mode, Tables 2–3, pages 17–25](https://www.analog.com/media/en/technical-documentation/data-sheets/MAX11129-MAX11132.pdf#page=17).

## MAX11627 / MAX11626: simpler SAR options with the same autonomy caveat

These 12-bit, four-channel, single-ended SPI ADCs have a 16-result FIFO and external-reference option (1 V to VDD). MAX11627 supports 2.7–3.6 V supply; MAX11626 requires 4.75–5.25 V, making MAX11627 the relevant electrical fit. Their 300 ksamples/s headline is externally clocked.

Internally timed scans start from a CNVST event or conversion-register command, then complete the requested operation and wait. They do not continuously repeat a programmable slow scan unattended. A hardware-trigger design remains possible, but must maintain triggering and read sequencing; asserting CS before EOC goes low can corrupt the FIFO. Overflow overwrites oldest results.

The 16 entries again give **8 ms** at 2,000 results/s. Reading a FIFO does not eliminate acquisition-trigger timing responsibilities. SAR input drive also needs checking: the datasheet qualifies sources below 300 ohms at its minimum internally timed acquisition interval; higher impedance may require longer acquisition, local capacitance, or a driver. [MAX11626–MAX11633 datasheet Rev. 5, Features, Internal FIFO, and clock modes, pages 1, 12–18](https://www.analog.com/media/en/technical-documentation/data-sheets/MAX11626-MAX11633.pdf#page=12).

## ADS7142-Q1: capture buffer, not a continuously drainable result queue

This two-channel, 12-bit I2C ADC supports ground-referenced inputs, 1.65–3.6 V analog/digital supplies, and a 16-word buffer. AVDD supplies its conversion reference, so using the 3.0 V excitation as AVDD would provide the intended ratio in principle.

Its autonomous start-burst mode fills the buffer and stops. Stop-burst and pre/post-alert modes provide other finite capture behaviors. Critically, reads during an active sequence return zeros with DATA_VALID=0. Valid FIFO-style readout follows stopping/completion, and starting the next sequence resets the buffer. Consequently it cannot continuously accumulate sensor history while the ESP32 drains earlier results. Its adequate conversion speed does not remedy this limitation. [ADS7142-Q1 datasheet Rev. B, sections 7.3.7.2 and 7.4.3.2, plus section 5](https://www.ti.com/lit/ds/symlink/ads7142-q1.pdf#page=24).

## Prior objective: preliminary FIFO recommendation and remaining evidence

Evaluate **ADS125P08 first** if the objective is to remove a local sampling MCU while allowing the ESP32 to read batches. This is a candidate for validation, not a pin-compatible ADS1220 replacement or a purchasing decision. It addresses analog acquisition; buffering separate UART/I2C sensors remains a separate requirement.

Before selecting a part, confirm the sensor/output impedance and reference source, supply tolerances, filter/bandwidth needs, and maximum ESP32 service gap. Bench checks should establish regular per-channel timing, input/reference settling after channel changes, usable 12-bit performance across the sensor range, FIFO draining during acquisition, and explicit gap detection/recovery after overload. FIFO order and channel identity do not themselves supply acquisition timestamps; the logger still needs a clock/sequence-to-time mapping.

If the required service gap exceeds the available FIFO margin, an ADC FIFO alone is insufficient. A local MCU with RAM or another acquisition/buffering architecture remains an option. No firmware build or hardware test was performed for this research note.

## Revised shortlist: local MCU supplies buffering

Revision date: **2026-11-20**. The preceding FIFO screening addresses the prior objective of removing the local sampling MCU. The revised architecture retains an MCU for capture and RAM buffering, so an ADC FIFO is optional. Priorities are channel count, throughput, simple MCU capture and cost ahead of resolution beyond 12 bits. The minimum remains four channels at 500 samples/s or two at 1,000 samples/s per chip; greater channel/rate headroom is desirable. Preferred electrical conditions remain ground-referenced 0–3 V sensors, ratiometric 3 V excitation/reference and 3.3 V digital interfaces.

### Supplier cost snapshot

Observed **2026-11-20**, **USD per IC**, excluding shipping/tax. Stock and prices are volatile; quantity tiers beyond listed stock do not establish availability at that quantity. LCSC product-image pages supplied readable price/stock tables. These are component costs, excluding MCU, conditioning, reference drivers and power supplies.

| Exact orderable part | LCSC ID and source | Stock | 1+ | 10+ | 100+ or stated tier |
|---|---|---:|---:|---:|---:|
| ADS131A04IPBSR | [C882747](https://www.lcsc.com/product-image/C882747.html) | 2,126 | $7.1183 | $6.2640 | $5.0892 at 100+ |
| ADS131M08IPBS | [C2685451](https://www.lcsc.com/product-image/C2685451.html) | 354 | $5.0925 | $4.4200 | $4.0218 at 30+; $3.6186 at 250+ |
| ADS8588SIPMR | [C575544](https://www.lcsc.com/product-image/C575544.html) | 1,714 | $10.0577 | $8.8053 | $7.4008 at 100+ |
| AD7606BSTZ | [C398827](https://www.lcsc.com/product-image/C398827.html) | 5,000 | $18.4902 | $16.4367 | $14.2101 at 100+ |
| AD7606BBSTZ | [C443885](https://www.lcsc.com/product-image/C443885.html) | 794 | $22.1114 | $19.7288 | $17.1478 at 100+ |

### Preferred candidates and electrical tradeoffs

**ADS131A04: preferred four-channel candidate for direct 3 V ratiometric inputs.** Four simultaneous 24-bit delta-sigma channels reach 128 kSPS/channel. With 5 V analog power, external 3 V reference, gain 1 and negative inputs grounded, positive inputs can cover 0–3 V. With its charge pump disabled, absolute inputs span AVSS to AVDD; external reference must be 2.0 V to AVDD minus 0.5 V. Thus 3 V reference needs at least 3.5 V analog power; 3.3 V digital operation is supported. The interface offers 16-bit output to reduce transfer size. All channels share the output rate and sinc3 filtering. Clock selection is needed for an exact 500 Hz rate: the nominal 4.096 MHz modulator clock gives a quoted 1 kSPS minimum. Approximately 130 kΩ input impedance at that clock means sensor drive and filtering need validation. [TI datasheet, recommended conditions, digital filter and section 9.5.1.5.1](https://www.ti.com/lit/ds/symlink/ads131a04.pdf).

Two A04s provide eight simultaneous channels across synchronized devices for approximately **$14.24 at one-off prices**, or **$10.18 at 100+ IC pricing**, before support circuitry. Cross-chip clock/start synchronization and capture still require validation.

**ADS131M08: preferred inexpensive eight-channel option if conditioning is acceptable.** Eight simultaneous 24-bit delta-sigma channels reach 32 kSPS/channel; 3.3 V analog/digital operation and multichip synchronization are supported. Typical consumption is 6 mW at 3 V supplies. External reference is supported, but only **1.1–1.3 V**, nominal 1.25 V. Gain-1 differential full scale is **±0.96 × external reference**, hence ±1.2 V at 1.25 V. Grounding negative inputs is possible, but 0–3 V signals need attenuation. Deriving the reference from the same excitation can preserve ratios; reference drive, divider loading and tolerances need design work. Gain-1 input impedance is approximately 330 kΩ at the nominal clock. Filtering introduces response delay. [TI datasheet, sections 6.3 and 8.3](https://www.ti.com/lit/ds/symlink/ads131m08.pdf).

**ADS8588S: preferred eight-channel SAR option for simple sensor inputs, conditional on reference scaling and power.** Eight simultaneous 16-bit channels reach 200 kSPS/channel. Its ground-referenced ±5 V range accepts 0–3 V directly through 1 MΩ front ends. It needs 5 V analog power; 3.3 V I/O is supported. External reference is **2.475–2.525 V**, so direct 3 V reference is unsuitable. A buffered scaled reference could retain ratiometric measurement. The sensor uses 30% of the ±5 V span: about 19,661 ideal codes, or **14.26 code-resolution bits**, not measured ENOB. Typical analog current is 12.4 mA without conversions and 17.5 mA at 200 kSPS, approximately 62/87.5 mW at 5 V. Maximum serial throughput uses both data outputs during conversion. [TI datasheet, sections 7 and 8](https://www.ti.com/lit/ds/symlink/ads8588s.pdf).

**AD7606 family: useful throughput alternatives, weaker cost fit.** Original AD7606 provides eight simultaneous 16-bit channels at 200 kSPS/channel, ±5/±10 V inputs, 5 V analog power and nominal 2.5 V external reference. AD7606B increases this to 800 kSPS/channel; its extra ±2.5 V range cannot cover 0–3 V. AD7606C-16 reaches 1 MSPS/channel and adds 0–5 V unipolar inputs, but retains 5 V analog power and nominal 2.5 V reference. Retain B as a premium-speed alternative; its extra headroom has value if the MCU and downstream link can exploit it. [Original datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/AD7606_7606-6_7606-4.pdf), [B datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/ad7606b.pdf), [C-16 datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/ad7606c-16.pdf).

### Other options and validation boundary

AD7388-4 remains an engineering candidate: four simultaneous 12-bit channels at 4 MSPS. **AD7388 without “-4” has two converters with 2:1 multiplexers**, not four simultaneous converters. Primary LCSC price/stock could not be confirmed for AD7388-4. AD7386-4 has listing C22550736, but its own price/stock also remain unverified; substitute-associated snippets do not establish availability. Neither is commercially preferred on current evidence. [ADI dual-converter family](https://www.analog.com/en/products/ad7388.html), [ADI quad-converter family datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/ad7386-4-7387-4-7388-4.pdf), [LCSC AD7386-4 listing](https://www.lcsc.com/product-detail/C22550736.html).

An ADC with an autonomous channel sequencer remains a cost baseline when simultaneous sampling is unnecessary: it cycles its internal multiplexer without MCU channel selection. Exact SKU cost is not established here.

Datasheet headline rates are **not guarantees for one MCU SPI input**, nor guarantees of sustained logger delivery. Validate channel timing, clock synchronization, analog/reference settling, useful 12-bit performance, filter response, MCU DMA/RAM capture, overflow detection and downstream service gaps. No hardware test or firmware build was performed.

## Eight-channel circuit cost comparison

Costed on **2026-11-20**, in **USD per eight-channel board**. These are preliminary circuit budgets, not release BOMs or validated schematics. The local sampling MCU and RAM are common to all options and excluded. The comparison assumes eight ground-referenced sensors spanning 0 V to their nominal 3 V excitation, with source impedance not yet qualified. It therefore includes eight source-buffer channels for every candidate, including the SAR option; the M08 also includes eight drivers after its input dividers.

### Existing A8 baseline

The [A8 v1.0 fabrication BOM](../../hardware/bodaqs-a8/v1_0/fab/BODAQS_A8_board_v1_0-BOM.csv) identifies **U10 and U11 as ADS1220IRVAR, LCSC C2651338**. The [analog-input schematic](../../hardware/bodaqs-a8/v1_0/design/Analog_inputs.kicad_sch) uses eight 100-ohm / 10-nF input filters without op-amp buffers. The existing pair contains two converters, each behind a four-input multiplexer; it is not equivalent to eight simultaneous 500-sample/s channels. [TI ADS1220 datasheet](https://www.ti.com/lit/ds/symlink/ads1220.pdf).

The current [LCSC ADS1220 listing](https://www.lcsc.com/product-image/C2651338.html?whichImg=sch) reports **8 ICs in stock**, at $2.9895 each at 1+, $2.5995 at 10+, and $2.1335 at 100+. Thus the two-IC baseline is **$5.9790 / $5.1990 / $4.2670** at those respective IC tiers, before supporting components. The higher tiers are price references, not evidence that the quoted stock can fill those orders.

### Verified support-component prices

The following low-quantity unit prices were readable on the linked LCSC pages. Totals below use these prices and the ADC prices in the preceding supplier snapshot. They describe material fitted to one board, **not checkout cost after minimum order quantities**, and exclude shipping and tax.

| Exact component | LCSC source | Unit price used | Quantity tier |
|---|---|---:|---:|
| TI TLV9064IPWR, quad signal buffer | [C779410](https://www.lcsc.com/product-image/C779410.html) | $0.4084 | 5+ |
| TI TLV333IDBVR, single reference buffer | [C473369](https://www.lcsc.com/product-image/C473369.html) | $0.3867 | 1+ |
| YAGEO RT0603BRD0710KL, 10 kΩ, 0.1%, 25 ppm/°C | [C95204](https://www.lcsc.com/product-image/C95204.html) | $0.0258 | 20+ |
| YAGEO RT0603BRD0715KL, 15 kΩ, 0.1%, 25 ppm/°C | [C326733](https://www.lcsc.com/product-image/C326733.html) | $0.0352 | 20+ |
| YAGEO RT0603BRD0718KL, 18 kΩ, 0.1%, 25 ppm/°C | [C309650](https://www.lcsc.com/product-image/C309650.html) | $0.0402 | 20+ |
| TI REF3030EAIDBZR, precision 3 V excitation source | [C54120492](https://www.lcsc.com/product-image/C54120492.html) | $0.9667 | 1+ |

TLV9064 is a quad RRIO, unity-gain-stable amplifier operating from 1.8–5.5 V; TLV333 provides lower offset for the shared reference divider. These specifications establish plausible budget candidates, not proven ADC drivers. Resistor tolerances and temperature coefficients are individual specifications, not guaranteed ratio tracking. [TLV9064 datasheet](https://www.ti.com/lit/ds/symlink/tlv9064.pdf), [TLV333 datasheet](https://www.ti.com/lit/ds/symlink/tlv333.pdf), [YAGEO RT series specification](https://yageogroup.com/component-documentation/download/specsheet/RT0603BRD0718KL).

### Preliminary ratiometric circuits

**Two ADS131A04s:** retain the common 3 V excitation as the external reference, use gain 1, ground each negative input, and provide 5 V analog power with 3.3 V digital power. Eight source buffers require two TLV9064s, costing **$0.8168**. No input/reference scaling resistors are needed in this budget. A shared clock and synchronized startup are required for the two devices. The approximately 130 kΩ ADC input loading is a reason to retain the buffers until sensor drive is qualified. [ADS131A04 datasheet, recommended conditions and analog inputs](https://www.ti.com/lit/ds/symlink/ads131a04.pdf).

**One ADS131M08:** derive its reference from the same excitation using 15 kΩ above / 10 kΩ below a divider, followed by a TLV333 follower. Each sensor passes through a source buffer, then an 18 kΩ above / 10 kΩ below divider, then an ADC driver; ground AIN− and use gain 1. The first buffer avoids loading an unbuffered potentiometer with the 28 kΩ divider; the second avoids loading the divider with the ADC's nominal 330 kΩ input. Four TLV9064 packages supply the sixteen signal-buffer channels, costing **$1.6336**. [ADS131M08 datasheet, sections 6.3 and 8.3.3–8.3.4](https://www.ti.com/lit/ds/symlink/ads131m08.pdf).

```text
Vref = Vexc × 10 / (15 + 10) = 0.4 × Vexc = 1.2000 V at 3 V excitation
Vin_ADC = Vsensor × 10 / (18 + 10) = 0.357143 × Vsensor
Vin_ADC maximum = 1.07143 V at Vsensor = Vexc = 3 V
ADC positive full scale = 0.96 × Vref = 1.152 V
Positive-range use = 1.07143 / 1.152 = 93.0%
Vin_ADC / Vref = (25 / 28) × (Vsensor / Vexc)
```

The ideal ratio therefore cancels excitation variation while leaving approximately 7% positive-range headroom. The external reference must remain within 1.1–1.3 V; the existing excitation tolerance is comfortably inside that window after nominal 0.4 scaling. Eighteen precision resistors cost `8 × ($0.0402 + $0.0258) + $0.0352 + $0.0258 = $0.5890`. Including the TLV333 gives **$0.9757 for input/reference scaling**, before bypass/filter allowances.

**One ADS8588S:** select its ±5 V input range, use eight source buffers, and derive 2.5 V reference from the excitation through six equal 10 kΩ resistors in series, taking the tap above the lower five resistors. A TLV333 buffers this `Vref = (5/6) × Vexc` node. The six resistors cost **$0.1548**; the reference-scaling subtotal is **$0.5415**. Its integrated 1 MΩ front ends may allow omitting both external TLV9064s after checking source loading and settling, saving **$0.8168**. [ADS8588S datasheet, sections 7.6 and 8.3](https://www.ti.com/lit/ds/symlink/ads8588s.pdf).

The SAR reference must stay within **2.475–2.525 V**. The A8's existing TPS7A2030 excitation regulator has up to ±1.5% output error, so simple 5/6 scaling cannot guarantee that limit. This budget adds a **REF3030E precision 3 V excitation source** and takes no credit for removing the old regulator. REF3030E specifies 0.1% initial accuracy, 15 ppm/°C maximum drift and ±10 mA output; assume total excitation load, including the divider, is at most 10 mA. Eight 10 kΩ potentiometers draw 2.4 mA, plus 50 µA for the reference divider. Higher load requires another drive stage with cost still to be determined. A complete excitation error and transient budget remains necessary. [TPS7A20 datasheet](https://www.ti.com/lit/ds/symlink/tps7a20.pdf), [REF30E datasheet](https://www.ti.com/lit/ds/symlink/ref30.pdf).

### Board-level budget, including explicit planning allowances

The support allowances below are **estimates, not supplier quotes**:

- **ADC clock: $0.50–$1.50** per delta-sigma board, shared by both A04s or used by the single M08. This could be zero if a qualified MCU hardware clock supplies the required timing. The SAR uses MCU conversion triggers instead.
- **Battery-capable 5 V analog supply: $1.00–$2.00** for A04 or SAR. The existing battery-powered A8 does not provide this rail. A preliminary 5.3 V boost followed by a 5 V LDO could use TPS61023DRLR ([C919459, $0.2354 at 5+](https://www.lcsc.com/product-image/C919459.html)) and TPS7A2050PDBVR ([C2864504, $0.2413 at 5+](https://www.lcsc.com/product-image/C2864504.html?whichImg=0)); the inductor, capacitors and feedback components have not been selected. Headroom, ripple and regulation require validation. [TPS61023 datasheet](https://www.ti.com/lit/ds/symlink/tps61023.pdf), [TPS7A20 datasheet](https://www.ti.com/lit/ds/symlink/tps7a20.pdf).
- **Additional filters and bypassing: $0.30–$0.70** per option, covering added IC decoupling, reference capacitors and driver isolation/filter components. This is in addition to the existing eight common input filters.

| Eight-channel option | ADCs | Signal buffers | Input/reference scaling | Precision excitation upgrade | Verified parts subtotal | Planning allowances | Estimated material per board |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2 × ADS131A04IPBSR | $14.2366 | $0.8168 | $0 | $0 | **$15.0534** | $1.80–$4.20 | **$16.8534–$19.2534**, approximately **$17–$19.5** |
| 1 × ADS131M08IPBS | $5.0925 | $1.6336 | $0.9757 | $0 | **$7.7018** | $0.80–$2.20 | **$8.5018–$9.9018**, approximately **$8.5–$10** |
| 1 × ADS8588SIPMR | $10.0577 | $0.8168 | $0.5415 | $0.9667 | **$12.3827** | $1.30–$2.70 | **$13.6827–$15.0827**, approximately **$14–$15.5** |

Excluded common items are the eight existing 100-ohm / 10-nF input filters, connectors, MCU/RAM, common 3.3 V power and existing 3 V excitation rail. PCB fabrication, assembly, shipping and tax are also excluded. The SAR's new precision excitation source is included without credit for the retired LDO. No additional excitation drive beyond the stated 10 mA assumption is included.

**M08 is the strongest cost case if its reference and driver validation succeeds.** A04 has simpler analog scaling and fewer signal-buffer stages, at higher cost. SAR provides much greater conversion-rate headroom, with a 5 V supply, higher ADC power and a precision-excitation upgrade. The buffer power also matters, especially for the sixteen-channel M08 circuit; ADC-only consumption does not represent total acquisition power.

Before selecting parts, check sensor source impedance and excitation current, amplifier offset and output swing near 0 V, full-scale margin over temperature, reference noise/loading, startup, capacitive-load stability, filter settling and clock quality. In particular, the M08 datasheet does not establish the external reference-drive current needed to qualify the proposed TLV333 stage. Rail clipping and offset can impair endpoint accuracy even when the nominal ratios fit. Any required negative bias rail, higher-current excitation driver or different precision amplifier would change this budget. No simulation, schematic/ERC review, firmware build or bench test was performed for this comparison.
