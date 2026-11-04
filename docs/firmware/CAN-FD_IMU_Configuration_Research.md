# CAN-FD IMU configuration research

Research date: 2026-11-03. Status: interview evidence and proposed configuration-only baseline; no firmware implementation or physical validation.

Interview update after research: Q45-Q46 selected the candidate numerical
profile below, with sensing engines running for an enabled-but-stopped endpoint.
The power-down image below is an alternative examined during research, not the
agreed enabled state. Use ODR code 9 (`CTRL1_XL=94h`, `CTRL2_G=9Ch`) for that
enabled state, with FIFO/interrupt collection disabled; explicit disable uses
ODR zero. The authoritative decisions are in section 13.11 of
[the network contract](CAN-FD_Network_Protocol.md). Exact register policy and
profile identifiers still need specification; no physical result is claimed.

## Scope and sources

The exact part is **LSM6DSO32XTR**, on the MSPM0G3507 production IMU-only node. The [network design](CAN-FD_Sensor_Network_Design.md), sections 3 and 7, requires ±32 g acceleration and useful acceleration content through approximately 1 kHz; approximately 1 kHz gyro bandwidth is desirable. Neither native ODR nor register readback establishes that measurement performance.

Primary references inspected:

- [ST DS13607, LSM6DSO32X datasheet, Rev 1, March 2021](https://www.st.com/resource/en/datasheet/lsm6dso32x.pdf) (162 pages; printed page numbers used below).
- [ST AN5640, Rev 2, August 2023](https://www.st.com/resource/en/application_note/an5640-lsm6dso32x-alwayson-3d-accelerometer-and-3d-gyroscope-stmicroelectronics.pdf) (114 pages).
- [ST exact-part register driver header](https://github.com/STMicroelectronics/lsm6dso32x-pid/blob/master/lsm6dso32x_reg.h), inspected on research date. This moving branch must be pinned if incorporated into firmware. Driver enum values are API encodings, not necessarily raw register bytes.

Do not substitute LSM6DSO32 or another LSM6DSO-family configuration. Some prose in the exact-part datasheet abbreviates the family name; the register tables and exact-part driver are the evidence used here.

## Candidate profile and decisions

**Proposal requiring agreement:** one initial profile, matched nominal 3.33 kHz acceleration/gyro, acceleration ±32 g, gyro ±2000 dps, high-performance modes, accelerometer optional LPF2 bypassed, both high-pass paths disabled, gyro optional LPF1 bypassed. This is a bring-up candidate, not an approved production transfer function.

The exact-part [driver header](https://github.com/STMicroelectronics/lsm6dso32x-pid/blob/master/lsm6dso32x_reg.h) provides `LSM6DSO32X_XL_ODR_3333Hz`, `LSM6DSO32X_GY_ODR_3333Hz` (both code 9), `LSM6DSO32X_32g` (1), `LSM6DSO32X_2000dps` (6), and `LSM6DSO32X_BYPASS_MODE` (0). DS13607 pp.50–51 supports matched 12.5, 26, 52, 104, 208, approximately 416/417, 833, 1667, 3333 and 6667 Hz choices. The documentation inconsistently rounds the higher rates as 3.33/6.66 kHz; retain the named native mode rather than treating those labels as calibrated clock frequencies.

| Field | Supported choice / candidate | Decision implication |
|---|---|---|
| Acceleration full scale | ±4/±8/±16/±32 g; choose ±32 g | Existing requirement; `FS_XL[1:0]=01` |
| Gyro full scale | ±125/±250/±500/±1000/±2000 dps; propose ±2000 | User must choose required headroom versus scale resolution |
| Native matched ODR | Propose code 9, approximately 3.33 kHz | Code 8 is below the Nyquist minimum for 1 kHz; code 10 increases transport load |
| Acceleration output filter | HP off, optional LPF2 off | Avoid widest LPF2 cutoff ODR/4 ≈833 Hz at candidate rate |
| Gyro output filter | HP off, optional LPF1 off | Avoid enabled LPF1 choices whose highest overall bandwidth at 3333 Hz is 559.20 Hz |

Range encodings: [DS13607 pp.50–51](https://www.st.com/resource/en/datasheet/lsm6dso32x.pdf). Filter implication: [AN5640 pp.16–17, Table 10; pp.21–23, Table 14](https://www.st.com/resource/en/application_note/an5640-lsm6dso32x-alwayson-3d-accelerometer-and-3d-gyroscope-stmicroelectronics.pdf). With optional filters bypassed, ST lists acceleration LPF1 cutoff ODR/2 and gyro overall bandwidth **1320.70 Hz at 3333 Hz**. These values do not specify flat response or acceptable phase at 1 kHz. User agreement is still needed on allowable amplitude error, phase/group delay, noise and aliasing, followed by bench validation. HP off preserves DC/gravity for acceleration; this is a proposed behavior choice.

## Stopped configuration versus acquisition

Power-down uses ODR fields zero. SPI remains operational and configuration registers retain their contents while powered; outputs hold previous samples. Thus a stopped node can install and verify range/filter settings, but must retain the requested running ODR in software. It cannot read back ODR code 9 from a powered-down sensor. Reset or power loss requires reapplication. Source: [AN5640 p.15, §3.1](https://www.st.com/resource/en/application_note/an5640-lsm6dso32x-alwayson-3d-accelerometer-and-3d-gyroscope-stmicroelectronics.pdf).

Proposed configuration-only behavior: leave both ODRs zero, FIFO in bypass, batching off, all INT1/INT2 routing off, embedded engines off, and sensor timestamp off. Do not enable MCU IMU interrupts or read samples. A later start applies the agreed ODR and acquisition machinery. Describe this stage as **profile installed and read back while stopped**, not sampling-ready.

The following candidate image assumes a completed software reset and unchanged unsupported features. Values are proposed firmware policy derived from [DS13607 p.40 reset map and pp.44–60 register definitions](https://www.st.com/resource/en/datasheet/lsm6dso32x.pdf); preserve reserved bits and only compare documented fields. These are sensor settings, not a proposed wire format.

| Register (address) | Reset | Candidate stopped value | Fields / verification |
|---|---:|---:|---|
| `FUNC_CFG_ACCESS` (01h) | 00h | 00h | User bank; access mask C0h |
| `FIFO_CTRL1/2/3/4` (07h–0Ah) | 00h each | 00h each | No watermark/compression/batching; `FIFO_MODE` mask 07h = bypass |
| `COUNTER_BDR_REG1/2` (0Bh–0Ch) | 00h each | 00h each | Counters inactive; latched DRDY is unused |
| `INT1_CTRL/INT2_CTRL` (0Dh–0Eh) | 00h each | 00h each | No DRDY, FIFO or counter routes |
| `WHO_AM_I` (0Fh), read only | 6Ch | Expect 6Ch | Identity check, not a unique serial number or exclusive part authentication |
| `CTRL1_XL` (10h) | 00h | 04h | ODR mask F0h=0; FS mask 0Ch=04h; LPF2 enable 02h=0; future candidate running value 94h |
| `CTRL2_G` (11h) | 00h | 0Ch | ODR mask F0h=0; FS mask 0Ch=0Ch; FS_125 mask 02h=0; future candidate running value 9Ch |
| `CTRL3_C` (12h) | 04h | 44h | BDU 40h=1, IF_INC 04h=1, SIM 08h=0 (4-wire); active-high push-pull interrupt policy, unrouted |
| `CTRL4_C` (13h) | 00h | 0Ch | I2C_disable 04h=1; DRDY_MASK 08h=1; gyro LPF1 enable 02h=0; SLEEP_G 40h=0 |
| `CTRL5_C` (14h) | 00h | 00h | Self-test, rounding and ultra-low-power off |
| `CTRL6_C` (15h) | 00h | 00h | XL_HM_MODE 10h=0 (HP); FTYPE mask 07h=0, unused while LPF1 bypassed; DEN off |
| `CTRL7_G` (16h) | 00h | 00h | G_HM_MODE 80h=0 (HP); HP_EN_G 40h=0; accelerometer user offset output off |
| `CTRL8_XL` (17h) | 00h | 00h | HP_SLOPE_XL_EN 04h=0; HPCF mask E0h=0; reference/fast settling off |
| `CTRL9_XL` (18h) | E0h | E2h | I3C_disable 02h=1; DEN stamping disabled; preserve default axis-selection bits E0h |
| `CTRL10_C` (19h) | 00h | 00h | TIMESTAMP_EN 20h=0 |
| `MD1_CFG/MD2_CFG` (5Eh–5Fh) | 00h each | 00h each | No embedded-function routes |

Other registers retain documented reset values after reset; do not bulk-zero reserved addresses. In particular `PIN_CTRL` resets to **3Fh**, not zero, and `CTRL9_XL` resets to E0h. Embedded function and sensor-hub engines are not enabled by this profile. For an implementation using ST APIs, inspect each setter's affected registers before adopting an image/readback mask.

## SPI and production pin constraints

The [design pin table](CAN-FD_Sensor_Network_Design.md) maps CS/PICO/POCI/SCK to **PA8/PA9/PA10/PA11**, and INT1/INT2 to **PA3/PA22**. Current [`node.syscfg`](../../firmware/can-fd/node/node.syscfg) configures CAN, identity straps, LED and clocks; it does **not** configure SPI or IMU pins. Adding them is hardware integration work, not an already available peripheral. Use the production G3507 VQFN-32 mapping, not LaunchPad pin assumptions.

Proposed bring-up: GPIO CS initially high, 4-wire SPI mode 3, conservative initial clock (e.g. 1 MHz), bounded transactions, CS held low throughout command plus payload. ST specifies a 10 MHz maximum and mode-3 timing, not proof that the board works at 10 MHz. Source: [DS13607 p.14 and SPI interface section](https://www.st.com/resource/en/datasheet/lsm6dso32x.pdf). Initial SPI frequency is a firmware engineering choice for agreement, not a sensor profile requirement.

Keep MCU PA3 and PA22 as inputs without driven-high pulls during IMU startup. **INT1 must be low or unconnected during power-on for SPI/I2C operation; INT2 defaults to an output forced low.** Do not drive PA22 as a synchronization output merely because the pin also supports DEN. Source: [AN5640 p.3, pin status table and footnotes](https://www.st.com/resource/en/application_note/an5640-lsm6dso32x-alwayson-3d-accelerometer-and-3d-gyroscope-stmicroelectronics.pdf). Disabling I2C and I3C removes their internal CS pull-up; the MCU must continue to hold idle CS high.

## Initialization, readback and verification proposal

1. Respect power-on boot time (AN5640 p.25 says approximately 10 ms); use a finite startup allowance. Initialize safe GPIO/SPI levels.
2. Read WHO_AM_I and require 6Ch. Set `CTRL3_C.SW_RESET` (01h mask); poll until it self-clears with a bounded timeout; recheck identity and expected stopped/reset control state. `BOOT` (80h) reloads memory and is distinct from software reset. Source: [DS13607 pp.49,52](https://www.st.com/resource/en/datasheet/lsm6dso32x.pdf).
3. Apply the agreed stopped image. Enable BDU and IF_INC explicitly. BDU protects individual low/high byte pairs; it does not guarantee coherent six-axis samples or synchronization. Source: [AN5640 p.26 §4.4](https://www.st.com/resource/en/application_note/an5640-lsm6dso32x-alwayson-3d-accelerometer-and-3d-gyroscope-stmicroelectronics.pdf).
4. Read back every owned documented configuration field, including powered-down ODR, batching, bypass and interrupt routes. Separate transport errors, identity mismatch, reset timeout and configuration mismatch. Report installed only after all checks pass; fail closed with acquisition stopped. This is proposed software behavior, not an ST-provided transaction protocol.
5. On-device acceptance for this stage: correct CS/SCK/SDI/SDO waveform and levels, repeated reset/configure/readback, no IMU interrupts/FIFO accumulation while stopped, and failure reporting with absent/misbehaving sensor. Record board revision and firmware version. No board-level result is claimed here.

## Deferred acquisition prerequisites

At the candidate rate, cold start settling is significant: acceleration discards 10 samples with optional LPF2/HP bypassed; gyro power-down to HP requires **70 ms plus 270 discarded samples** with LPF1 bypassed (roughly another 81 ms). **DRDY_MASK is insufficient for high-rate gyro settling:** its gyro LPF2 protection applies only at ODR ≤833 Hz. Sources: [AN5640 p.20 Tables 11–12; p.24 Tables 16–17; p.26 §4.3.1](https://www.st.com/resource/en/application_note/an5640-lsm6dso32x-alwayson-3d-accelerometer-and-3d-gyroscope-stmicroelectronics.pdf). A later acquisition stage must implement and physically verify the startup discard/timing policy; configuration readback cannot verify settling.

Profile ID/version assignment, nominal-rate representation, range choice, permitted reconfiguration states, reboot persistence and failure reporting need agreement before implementation. Native-clock calibration, cross-axis timing, DRDY/FIFO service, FIFO tags, timestamps, source continuity, synchronization and CAN sample transport can be deferred because this stage produces no samples. FIFO compression must not be assumed available later: AN5640 p.94 excludes simultaneous accel/gyro compression at maximum ODR ≥1.66 kHz. Preserve the existing [network protocol](CAN-FD_Network_Protocol.md) and [design](CAN-FD_Sensor_Network_Design.md) as authoritative contracts until interview decisions are reconciled there.
