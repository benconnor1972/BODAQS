# BODAQS CAN-FD sensor network design

Status: architecture, mature hardware, and discovery-path implementation
Originally recorded: 20 September 2026  
Last updated: 3 November 2026

## 1. Purpose and scope

This is the living design record for the BODAQS distributed CAN-FD sensor
network. It records the agreed requirements, architecture, current KiCad
implementation, firmware responsibilities, protocol boundaries, engineering
risks, and remaining decisions.

The system connects up to four remote sensor nodes to an A8 logger through a
CAN-FD master. Each node is more than an IMU satellite: the current design
contains a local high-rate six-axis IMU, two analogue inputs, and two
independent external I2C sensor interfaces.

The first logger-firmware stage retains one authoritative configuration file.
Multiple selectable configuration files are explicitly deferred; the initial
work is concerned with making one configuration scale cleanly across local and
remote providers.

Routed four-layer production-candidate PCB layouts exist for the full sensor
node and the G3518 master. Derived no-IMU, no-I2C, and IMU-only node projects
also exist, but are at different levels of layout maturity. The full node and
master pass automated ERC and have no unconnected or schematic-parity errors;
minor footprint-library and silkscreen warnings remain. The first G3518 master
and an IMU-only node have completed MCU, clock, logger-SPI and physical CAN-FD
discovery/status bring-up. The first master PCB has a known buck-converter
symbol/pin-mapping defect; corrected hardware is pending, and current network
testing uses a bypassed branch-power path.

The direct-I2C four-BMI270 work is a separate exploratory implementation. It
has informed the acquisition, timestamping, recovery, diagnostics, and BDQ v2
work, but it is not the intended route to 1 kHz measurement bandwidth.

## 2. Agreed requirements and decisions

- The initial system contains four remote sensor nodes.
- Each node provides:
  - one local high-rate accelerometer and gyroscope;
  - two analogue inputs; and
  - two independent external I2C sensor inputs.
- Acceleration signals up to approximately 1 kHz are important.
- Approximately 1 kHz gyro bandwidth is desirable, but acceleration is the
  priority.
- Sixteen-bit IMU samples are sufficient.
- More than 1 dB of amplitude error may be acceptable, subject to final
  measurement validation.
- A relative phase error of about 10 degrees, or slightly more, may be
  acceptable.
- Real-time transmission beyond the logger is not required.
- Low node BOM cost is desirable, while spending more on the master for useful
  buffering and implementation margin is acceptable.
- CAN-FD was selected over RS-485 because it provides arbitration, robust
  shared-bus behavior, established fault handling, and a useful path for other
  distributed sensors.
- All nodes use one logical CAN bus and one linear trunk.
- The master may be located physically in the middle of the trunk.
- The current master design has front and rear physical trunk connectors. They
  share the same CAN nets and one logical SYNC source; separate series resistors
  and ESD devices create front and rear SYNC branch nets. They are not separate
  CAN buses. Their 5 V feeds are separately current-limited and fault-monitored.
- Node boards retain bus-in and bus-out connections for daisy-chain wiring.
- Connections are intended to be hard-wired through through-hole pads or
  connectors.
- SMD components are fitted on one side to keep prototype assembly economical.
  The current routed boards use four copper layers.
- The master connects to the A8 through SPI, ground, and selectable 3.3 V or
  VSYS power. The master connector also provides an optional interrupt line for
  later A8 revisions; A8 v1.0 must remain usable without it.
- A dedicated hardware synchronization conductor is carried alongside CAN-FD.
- The trunk therefore uses five conductors: `5V`, `GND`, `CANH`, `CANL`, and
  `SYNC`.
- BDQ v2 is the intended logger file format for the independent remote sensor
  streams.
- The logger target is 32 configured logical sensors. Each logical sensor may
  emit at most one native-rate stream, in addition to the logger's primary
  stream.
- Physical endpoints have exclusive ownership within a configuration. Muting a
  sensor does not release its endpoint.
- Logging is best effort: a sensor-specific configuration, presence, or runtime
  problem excludes the affected sensor but does not prevent independent healthy
  sensors from logging.
- A CAN node's two-bit strap address is its configuration identity. A device
  UID is retained only as provenance and diagnostic evidence, so compatible
  replacement hardware inherits the saved configuration and installation data.
- Each remote external I2C port supports one configured sensor. Local logger
  I2C buses retain their existing multidrop behavior.
- Configuration and installation changes should be applied without restarting
  the logger. Configuration editing remains unavailable while logging.
- Discovery runs at startup, after a log is finalized, and on explicit user
  request. It reports evidence and suggested actions but does not silently
  rewrite the desired configuration.

## 3. System architecture

```text
                         A8 logger
              SPI + power + ground + optional IRQ
                              |
                      CAN-FD master board
                    - SPI peripheral to A8
                    - CAN-FD controller
                    - sync generation/capture
                    - aggregation and buffering
                    - protected 5 V trunk power
                              |
              5 V / GND / CANH / CANL / SYNC trunk
                 +-------------+-------------+-------------+
                 |             |             |             |
              node 0        node 1        node 2        node 3
                 |             |             |             |
          IMU + 2xAIN +  IMU + 2xAIN +  IMU + 2xAIN +  IMU + 2xAIN +
             2xI2C          2xI2C          2xI2C          2xI2C
```

The drawing is logical rather than a recommendation for star wiring. CANH and
CANL must form a linear trunk with short node stubs. The master's front and rear
connectors provide a convenient physical pass-through when the master is in the
middle of the installation.

CAN termination belongs only at the two physical ends of the trunk. The current
node and master designs have the split-termination resistors populated and two
normally-open solder jumpers controlling each termination network. Both jumpers
must be closed to enable a terminator and both must remain open when that board
is not at a physical end. In particular, the master termination remains disabled
when the master is in the middle of the trunk.

## 4. Controller choices

### 4.1 Node controller

The selected node MCU is the `MSPM0G3507SRHBR`:

- 80 MHz Arm Cortex-M0+;
- 128 KB flash and 32 KB SRAM;
- one CAN-FD controller;
- two SPI controllers;
- two I2C controllers;
- two simultaneous-sampling 12-bit ADCs;
- seven DMA channels; and
- RHB VQFN-32 package.

This is considered sufficient for the defined node role if the firmware stays
bounded and purpose-built. The node is expected to use static buffers, DMA and
interrupt-driven acquisition, a fixed set of supported sensor drivers, and no
filesystem, UI, web stack, or logger-side analysis.

The two I2C peripherals are fully allocated by the two external I2C interfaces.
The product contract should therefore treat them as two bounded sensor ports,
not as unlimited general-purpose multidrop expansion buses. The intended
starting assumption is one locally connected sensor per port at rates of a few
hundred hertz or less. Higher loads must be included explicitly in the node and
CAN budgets.

A plausible seven-channel DMA allocation is:

- IMU SPI receive and transmit: two channels;
- timer-triggered ADC acquisition: one channel;
- I2C receive: one channel per controller; and
- two channels retained for ping-pong buffering or implementation needs.

Short I2C command writes can be interrupt-driven rather than permanently
consuming more DMA channels.

The analogue converters are natively 12-bit. Hardware averaging can improve
effective resolution, but this is not equivalent to a true 16-bit precision
measurement chain. The analogue accuracy, bandwidth, input range, source
impedance, filtering, and calibration requirements must be specified
independently of the 16-bit IMU sample requirement.

Initial resource targets for the completed node firmware are:

- leave at least approximately 20 KB of flash unused;
- leave at least approximately 8 KB of measured SRAM headroom after queues and
  stacks are included;
- use the IMU's FIFO as the first acquisition buffer;
- keep the main MCU-side IMU queue at or below approximately 8 KB unless tests
  demonstrate a clear need for more; and
- report FIFO, software-queue, and CAN high-water marks and losses separately.

### 4.2 Master controller

The selected master MCU is the `MSPM0G3518SPMR` in the 64-pin PM LQFP package:

- 80 MHz Arm Cortex-M0+;
- 256 KB dual-bank flash and 128 KB SRAM;
- two CAN-FD controllers;
- three SPI and three I2C controllers; and
- twelve DMA channels.

The extra master SRAM is the primary benefit. The master is the concentration
and buffering boundary between four asynchronous nodes and the A8 SPI service
cadence. More RAM provides useful tolerance for CAN bursts and short A8 service
pauses, as well as space for diagnostics and protocol state.

The master and node therefore deliberately use different packages and require
distinct build targets, startup files, linker configurations, and pinmux
definitions. The adopted master part is recorded in the current BOM as LCSC
`C49262735`. The older G3507 master project is retained only as design history;
it is not a footprint-compatible alternate fit for the current master PCB.

### 4.3 CAN data-rate limit

The TCAN1044A transceiver can operate at higher data rates than the selected
MCUs, but both the G3507 and G3518 CAN-FD controllers are specified for a
maximum 5 Mbit/s bit rate. The design must therefore not rely on an 8 Mbit/s
data phase. A 1 Mbit/s nominal arbitration rate and 4 Mbit/s data phase remain
a reasonable bench starting point, with 5 Mbit/s considered only after harness
signal-integrity testing.

## 5. Current hardware designs

### 5.1 Sensor node

Project directory:

`C:\Users\benco\OneDrive\BODAQS-private\CANBUS_IMU`

The current node schematic uses:

| Function | Part | Package | LCSC reference in design |
|---|---|---|---|
| MCU | MSPM0G3507SRHBR | VQFN-32 RHB | C20618748 |
| IMU | LSM6DSO32XTR, +/-32 g, SPI | LGA-14, 3 x 2.5 mm | C3663738 |
| Local 3.3 V regulator | TPS7A2033PDBVR | SOT-23-5 | C2862740 |
| CAN-FD transceiver | TCAN1044AVDRBRQ1 | VSON-8 DRB | C3234119 |
| CAN protection | PESD2CANFD27V-QBZ | DFN1110D-3 | C3715372 |
| Clock | KYX K2B160000810, 16 MHz | SMD 2016-4 | C2835986 |

Other current design features include:

- `BUS_IN` and `BUS_OUT` five-wire through-hole connections carrying 5 V,
  ground, CAN, and SYNC;
- local 3.3 V regulation from the trunk supply;
- SPI between MCU and IMU, plus IMU interrupt and synchronization signals;
- two analogue input channels with input filtering and protection;
- 3.3 V analogue-sensor excitation from the node regulator;
- two independent I2C buses on the external I2C connector, with interrupt
  inputs, protection, and a shared 3.3 V supply;
- an external switch/status-LED interface;
- two node-ID strap bits, sufficient for four fixed node addresses;
- SWD programming connection;
- status LED and CAN-FD protection; and
- split CAN termination enabled by closing both `TERM_H` and `TERM_L` solder
  jumpers.

The full node outline is 30 x 30 mm. The IMU is deliberately placed centrally.
All SMD parts are on the front side, with through-hole external connections.
The board uses four copper layers.

The firmware-relevant G3507 assignments in the live schematic are:

| Function | MCU signal |
|---|---|
| CAN transmit / receive | PA26 / PA27 |
| CAN standby | PA18 |
| IMU SPI chip-select / PICO / POCI / clock | PA8 / PA9 / PA10 / PA11 |
| IMU interrupts 1 / 2 | PA3 / PA22 |
| External I2C port 1 SDA / SCL / interrupt | PA0 / PA1 / PA23 |
| External I2C port 2 SDA / SCL / interrupt | PA16 / PA15 / PA12 |
| Analogue inputs 1 / 2 | PA14 / PA17 |
| SYNC capture | PA25 / TIMA0_C3 |
| Node-ID straps 0 / 1 | PA2 / PA4 |
| External switch / status LED | PA13 / PA7 |
| Local status LED | PA21 |
| 5 V trunk monitor | PA24 / ADC0 channel 3 |

The LSM6DSO32X replaced the earlier ICM-45686 proposal. It provides the
required +/-32 g accelerometer range and high native ODR, but its actual
amplitude response, phase/group delay, FIFO behavior, and usable performance
through the required 1 kHz band still require bench validation.

The external analogue and I2C sensor supplies are unswitched connections to the
node's 3.3 V rail. Their combined load, together with the MCU, transceiver, IMU,
and indicators, must remain within the TPS7A2033 and trunk-power budgets. The
current hardware provides no separate per-port current limiting or power
switching.

The standard KiCad `Texas_DRB0008A` footprint currently assigned to U5 on the
full, no-IMU, and no-I2C nodes contains exposed pad 9, but the live node symbol
does not connect that pad to ground. Before fabricating those designs, use the
corrected exposed-pad-to-ground footprint already present in the G3518 master
and IMU-only node, or make the equivalent symbol/footprint correction. Automated
schematic-parity checking does not detect an extra un-netted footprint pad.

### 5.2 Master board

Project directory:

`C:\Users\benco\OneDrive\BODAQS-private\CANBUS_master_G3518`

The current master schematic uses:

| Function | Current part | Package | LCSC reference in design |
|---|---|---|---|
| MCU | MSPM0G3518SPMR | LQFP-64 PM | C49262735 |
| CAN-FD transceiver | TCAN1044AVDRBRQ1 | VSON-8 DRB | C3234119 |
| 5 V buck-boost | TPS631000DRLR | SOT-583-8 | C5219190 |
| Front/rear power switches | TPS2553DBVR | SOT-23-6 | C55266 |
| CAN protection | ESD2CAN24DCKRQ1 | SOT-323 / SC-70 | C7469913 |
| Clock | KYX K2B160000810, 16 MHz | SMD 2016-4 | C2835986 |

Other current design features include:

- an eight-pin A8 connector carrying SPI, 3.3 V, VSYS, ground, and optional
  `A8_IRQ`;
- selectable converter input for existing and revised A8 hardware;
- a regulated 5 V trunk supply;
- front and rear trunk connectors sharing CAN and one logical hardware SYNC
  signal, with separate 100 ohm source resistors and ESD protection on the two
  SYNC branches;
- separately current-limited and fault-monitored front and rear 5 V feeds;
- an SPI-peripheral connection to the A8;
- SWD programming, status indication, CAN-FD protection, and optional CAN
  termination; and
- a 44 x 29 mm four-layer outline.

The two trunk connectors are two physical access points to one logical CAN
trunk. They must not be treated as independently terminable CAN buses.

Both converter-input zero-ohm resistors are populated. `JP2` is bridged by
default to select VSYS and `JP1` is open. For an existing A8 without a usable
VSYS connection, open `JP2` and close `JP1` to select 3.3 V. Never close both
input-selection jumpers simultaneously.

The master provides `A8_IRQ`, but A8 v1.0 does not expose a matching interrupt
connection. The SPI protocol and logger firmware must therefore support a
polling mode. A later A8 revision may use the interrupt without making it a
requirement for backward-compatible operation.

The firmware-relevant G3518 assignments in the live schematic are:

| Function | MCU signal |
|---|---|
| CAN transmit / receive | PA26 / PA27 |
| A8 SPI chip-select / PICO / POCI / clock | PA8 / PA9 / PA10 / PA11 |
| Optional A8 interrupt | PA13 |
| SYNC output | PA25 / TIMA0_C3 |
| Front / rear power enables | PA7 / PA12 |
| Front / rear power faults | PA21 / PA22 |
| Buck-boost enable | PA18 |
| Status LED | PA14 |

The two five-pin SWD connections are not pin-for-pin identical: node J3 uses
pin 2 for SWCLK and pin 3 for SWDIO, while master J4 uses pin 2 for SWDIO and
pin 3 for SWCLK. Pins 1, 4, and 5 are respectively 3.3 V, NRST, and ground on
both boards.

### 5.3 Node variants

The following derived node projects exist:

| Project | Fitted sensor interfaces | Outline | Current layout status |
|---|---|---:|---|
| `CANBUS_IMU` | IMU, two analogue, two I2C | 30 x 30 mm | Primary full node; routed |
| `CANBUS_NODE_NO_IMU` | Two analogue, two I2C | 30 x 30 mm | Schematic clean; PCB retains dangling copper from the removed circuit |
| `CANBUS_NODE_NO_I2C` | IMU, two analogue | 25 x 25 mm | Schematic clean; copper-to-edge errors remain after outline reduction |
| `CANBUS_NODE_IMU_ONLY` | IMU only | 20 x 20 mm | Routed; symbol/library and schematic/PCB metadata parity require reconciliation |

The IMU-only node has a single trunk connector rather than the bus-in/bus-out
pair used by the full node. It must therefore be installed as an endpoint or by
using a harness junction that preserves the linear CAN topology.

### 5.4 Design maturity

The full-node and G3518-master schematics and routed PCBs have received detailed
electrical, BOM, placement, routing, and manufacturing review. On 26 October
2026, KiCad 10.0.1 reported zero ERC violations for both projects, zero
unconnected items, and zero schematic-parity issues. The full node retained four
non-electrical DRC warnings and the master retained one footprint-library
warning. Before fabrication or release they still require:

- firmware-level pinmux validation against the exact G3507 RHB and G3518 PM
  packages using TI SysConfig or an equivalent authoritative check;
- independent symbol, footprint, value, and current part-availability review;
- routing, return-path, power-plane, clearance, and manufacturability review;
- correction of the un-netted CAN-transceiver exposed pad on the affected node
  designs;
- CAN differential-pair geometry appropriate to the selected PCB stack-up;
- careful placement of protection at cable entries and decoupling at each IC;
- analogue input review covering range, protection, settling, source
  impedance, filtering, accuracy, and calibration;
- mechanical review around the IMU, including stress, mounting, and keep-outs;
- resolution or explicit acceptance of the remaining DRC warnings, plus full
  ERC/DRC completion for each released node variant; and
- Gerber, drill, BOM, and placement-file review.

The full-node production BOM was reconciled with the live schematic on
26 October 2026, including the LSM6DSO32X and the previously omitted crystal
and load-capacitor LCSC references. The schematic PDF in the G3518 project is
still a stale copy of the earlier G3507 drawing; use the live KiCad schematic
until a new PDF is exported.

## 6. Sensor and configuration lifecycle

The A8 remains the owner of the user's desired sensor configuration. The CAN
network distributes and applies that configuration rather than creating a
second unrelated configuration model.

The intended lifecycle is:

1. The A8 stores a versioned desired configuration for each physical node and
   sensor port.
2. The master discovers nodes or validates the expected fixed node IDs and
   routes configuration commands.
3. Each node validates requested settings against its hardware and firmware
   capabilities, applies them, and reports the effective configuration.
4. The A8 distinguishes desired, applied, unsupported, stale, and faulted
   states in its UI and logs.
5. Logging records the effective configuration and firmware/protocol identity,
   not merely the last values requested by the user.

Configuration should be expressed in sensor-level concepts such as sensor
type, enabled state, native profile, range, filtering, sample rate, calibration,
installation orientation, and output streams. Raw register writes may exist as
a development facility, but should not be the stable business-level contract.

Each node and master should report a hardware identity, firmware version,
protocol version, capability descriptor, boot/reset reason, and a monotonically
changing configuration revision. Configuration commands require explicit
acknowledgement and should be idempotent so that reconnect and restart recovery
are deterministic.

### 6.1 Logger configuration model

The logger firmware must not make CAN-FD a special parallel configuration
system. A logger without a CAN master, a logger with one IMU-only node, and a
logger with several mixed-sensor nodes should use the same concepts.

The model should distinguish:

- a **provider**, such as the local A8 board or a CAN node;
- a **physical endpoint**, such as local `AIN4`, node 2 analogue port 1, or the
  IMU fitted to node 0;
- a **logical sensor**, containing user-facing name, semantics, calibration,
  installation information, and requested acquisition settings;
- at most one native-rate **stream** emitted by that sensor, with synchronous
  values otherwise contributing to the logger's primary stream; and
- the transport used to control the provider and receive those streams.

Physical location must be represented by a stable structured identifier rather
than being inferred from a sensor name or from type-specific parameters such as
`i2c_bus`, `i2c_addr`, or `ain`. Existing flat configuration files remain valid
through a compatibility translation layer, but new configuration should not
require every sensor driver and UI page to understand every transport.

Four fully populated nodes can expose twenty sensor endpoints before local A8
sensors are counted. The target is therefore 32 configured logical sensors and
up to 32 native streams, plus the primary stream. The logger now supports 32
flat `SensorSpec` entries and uses a bounded packed text arena for each
parameter store instead of reserving maximum-size key and value arrays for
every possible parameter. Sensor, provider, endpoint, diagnostic, and primary
column limits remain separately bounded.

The initial release continues to use one `/config/loggercfg.txt` file. It does
not include configuration profiles, an active-file selector, or NVS state for
configuration selection. Existing flat local-only entries remain valid through
a compatibility translation layer.

Endpoint ownership is evaluated from the desired configuration, not from the
current mute state. Muted sensors therefore continue to reserve their physical
endpoint. A remote I2C endpoint is identified by node and port because each
external node port supports one sensor; a local I2C endpoint continues to be
identified by bus and address so multiple local devices can share a bus.

### 6.2 Desired, discovered, effective, and health state

Configuration and diagnosis should expose four separate states:

1. **Desired:** what the user has saved.
2. **Discovered:** hardware identity and capabilities currently observed.
3. **Effective:** settings accepted and actually applied by the local driver or
   remote node.
4. **Health:** presence, initialization, timing, data continuity, electrical
   fault, and configuration-agreement status.

This distinction permits useful assistance without silently rewriting user
configuration. Discovery may offer to adopt an unconfigured device, match a
replacement, or repair a clear assignment error, but changes require explicit
user confirmation. A missing device must not be confused with an invalid saved
configuration, and a temporarily offline device must not lose its identity or
calibration.

The two-bit node strap address is the stable provider identity used by desired
configuration. A changed MCU UID at the same strap address is recorded in log
provenance and diagnostics but does not, by itself, invalidate configuration or
produce a user warning. Discovery runs at startup, once after log finalization,
and when requested from Settings. Hardware that appears during an active log is
not added to that recording because its participation plan and stream catalog
are fixed at log start.

Configuration and installation operations must not require a logger restart.
When a type, endpoint, or acquisition change cannot be applied to an existing
driver instance, the logger quiesces and rebuilds the sensor runtime internally
while logging is idle. Calibration and orientation changes may use narrower
live-update paths. Invalid changes leave the previous configuration and runtime
intact. Here, invalid changes mean invalid configuration input. A valid saved
desired configuration may remain unapplied when a remote node is absent or
rejects it; the previous known effective state is retained as an observation,
and that endpoint is excluded until its effective settings satisfy the current
desired configuration or permitted alternatives. The node configuration
contract in section 13 of `CAN-FD_Network_Protocol.md` records the agreed apply,
readback, authority and admission semantics; section 13.9 consolidates the
review checkpoint and explicit deferrals.

The compatibility syntax implemented in the flat file is:

- omitted `provider`, or `provider=local`, retains the existing local `ain`,
  `i2c_bus`/`i2c_addr`, UART, and board-profile assignment rules;
- `provider=can:N` (also accepted as `canN`) selects strapped node `N`, where
  `N` is 0 through 3; and
- remote `endpoint` is `imu`, `analog:0`, `analog:1`, `i2c:0`, or `i2c:1`.

Remote providers remain discovered as absent until the master reports their
strap-address inventory; their logical sensors are then matched against the
reported endpoint mask and health state. They are not accidentally instantiated
as local drivers. The logger-side SPI bootstrap now detects and identifies a
compatible daughterboard and reads a coherent four-page node snapshot. Remote
data acquisition remains unimplemented, so discovered endpoints are not yet
instantiated as live sensor drivers.

The logger detects assignment conflicts, performs bounded I2C identity probes,
records startup reports, and exposes BDQ v2 stream descriptors. These
mechanisms now feed a structured list of diagnostic issues rather than a
single first-error result.
Each issue should carry a stable code, severity, affected provider/endpoint or
sensor, concise summary, detailed evidence, and one or more suggested actions.

On-logger assistance is feasible for node discovery, duplicate node IDs,
firmware/protocol incompatibility, absent or unexpected devices, capability
mismatch, rejected settings, trunk power faults, bus-off state, FIFO or queue
loss, stale data, and many known-address I2C failures. It cannot reliably infer
the semantic identity of an analogue sensor, distinguish every I2C wiring fault,
or prove that a sensor is mechanically installed correctly. Analogue open/short
or range checks must therefore be presented as evidence or warnings rather than
certain automatic diagnosis.

### 6.3 Implemented logger foundation (3 November 2026)

The first logger-only implementation stage and the daughterboard bootstrap are
now present in the A8 firmware:

- fixed-capacity provider, endpoint, inventory, and multi-issue diagnostic
  models;
- stable diagnostic code keys and per-issue severity, scope, impact, related
  sensor, endpoint, and evidence fields;
- exclusive endpoint ownership across configured sensors, including muted
  sensors;
- a frozen best-effort session participant set, with sensor-specific faults
  excluding both claimants to a conflict or the individual unavailable sensor;
- sensor startup before catalog creation and acquisition scheduling after file
  creation, so the stream/column layout cannot change after it is declared;
- bounded sensor teardown and complete runtime rebuilding after saved add,
  delete, type, endpoint, or acquisition changes;
- explicit release of I2C scheduler registrations, BMI270 acquisition state,
  and GPS task/UART/mutex/heap ownership during a rebuild;
- local discovery at startup, after log finalization, after configuration
  rebuilding, and on request from the OLED Health screen;
- a transport-facing injection boundary for simulated or future CAN provider
  and endpoint observations;
- web configuration warnings which list stable issue codes and suggested
  corrective actions while making clear that healthy sensors can still log;
- session exclusion warnings in JSON log metadata;
- a fixed A8/RC3 board-profile descriptor for the daughterboard connection
  (shared SPI bus, GPIO 40 chip select, 4 MHz mode 0, polling on current
  hardware);
- a shared, mutex-protected SPI transaction service used by both the ADS1220
  external ADCs and the master driver;
- `can_master_mode=off|auto|required`, applied without a logger restart;
- bounded CRC-protected master identity and status probing, protocol
  compatibility state, periodic idle/post-log polling, API diagnostics, and
  OLED Health status;
- generation-consistent transfer of the master's four-address inventory,
  translation into provider and endpoint observations, and raw Web API
  diagnostics for absent, stale, and duplicate nodes; and
- a versioned bootstrap contract in `CAN-FD_Master_SPI_Protocol.md`.

The provider model and SPI bootstrap are not the CAN data plane. The logger can
identify the daughterboard, retrieve its power-fault and transport status, and
consume the node inventory built by the implemented CAN discovery/status
subset. Remote effective-configuration exchange and remote stream ingestion
are not included in this stage.

## 7. Timing and measurement model

Sampling rate and usable signal bandwidth are not interchangeable. The final
IMU operating data rate and digital filter must be chosen from the required
1 kHz measurement band, allowable amplitude error, phase/group delay, noise,
and anti-aliasing performance. Sampling just above 2 kHz does not by itself
guarantee useful 1 kHz measurements.

A 10-degree phase allowance corresponds to:

| Signal frequency | Time represented by 10 degrees |
|---:|---:|
| 100 Hz | 277.8 us |
| 500 Hz | 55.6 us |
| 1 kHz | 27.8 us |

The 1 kHz case therefore requires synchronization and timestamp reconstruction
at a few tens of microseconds, with a defensible uncertainty bound. CAN frame
arrival time is not an adequate sample timestamp because arbitration,
buffering, batching, retry, and firmware latency vary.

The intended model is:

- each node maintains a free-running hardware clock;
- IMU samples retain source sequence and native timing through FIFO and CAN
  batching;
- analogue sampling is timer-triggered and associated with the same node
  clock;
- I2C samples are timestamped at a defined acquisition point, preferably using
  a sensor data-ready edge where available, otherwise with documented request
  and completion timing bounds;
- the master provides hardware synchronization observations relating every
  node clock to the master/logger timebase;
- the host reconstructs a separate clock fit for each continuity segment; and
- raw samples and timing evidence remain authoritative, while fitting,
  resampling, and known filter-delay correction occur downstream.

The exact SYNC electrical and protocol semantics remain to be designed. A
likely approach is simultaneous timer capture at each node, potentially also
driving an IMU synchronization input if the selected IMU behavior proves
useful. Driver topology, edge rate, series damping, pulse rate, missed-pulse
handling, and operation over the real harness all require validation.

## 8. BDQ v2 relationship

The accepted BDQ v2 multi-stream contract is:

`C:\Users\benco\dev\BODAQS\docs\firmware\BDQ_v2_Multi_Stream_Contract.md`

Important consequences are:

- each remote sensor stream has its own stream identity and native timebase;
- a remote stream's `native_tick` is the node/sample clock, not CAN receive
  time;
- source sequence information must survive batching;
- IMU, analogue, and I2C streams may have different native rates and timing
  quality;
- diagnostics must distinguish sensor FIFO loss, node software-queue loss,
  CAN transport loss, master queue loss, and source reset;
- synchronization evidence should be recorded as bounded clock observations;
- packet receive timestamps are transport observations only; and
- clock fitting is performed separately across continuity segments.

The BDQ contract does not define the CAN-FD or A8-to-master wire protocols.

## 9. Firmware responsibilities

### 9.1 Sensor node

The node firmware should:

- configure the LSM6DSO32X using explicitly versioned acquisition profiles;
- report native ODR, accelerometer and gyro ranges, filter settings, and known
  nominal delay;
- drain the IMU FIFO using watermark interrupts, DMA, and burst reads;
- configure and acquire both analogue inputs from a hardware-timed ADC
  sequence;
- configure and schedule supported devices on both external I2C ports;
- prioritize time-critical unbuffered acquisitions without risking IMU FIFO
  overflow;
- timestamp each sensor stream at a defined acquisition point;
- preserve source sequence and native timing when batching data into CAN-FD
  frames;
- capture hardware synchronization events with a timer peripheral;
- accept validated configuration and control messages;
- report effective configuration and capability information;
- report sensor errors, FIFO overflow, queue loss, CAN enqueue/transmit failure,
  reset reason, clock/sync health, bus-off recovery, temperature, and useful
  supply health; and
- begin with SWD programming, deferring CAN-based firmware update.

### 9.2 Master

The master firmware should:

- operate as an SPI peripheral to the A8 and a CAN-FD controller on the trunk;
- generate or coordinate hardware synchronization events;
- discover nodes or validate a fixed four-node configuration;
- route versioned configuration and control transactions;
- validate frame version, source, sequence, length, and integrity;
- preserve native sample timing and distinguish transport loss from source
  loss;
- buffer traffic between CAN and SPI with explicit occupancy, overflow, and
  backpressure diagnostics;
- prioritize data, timing, configuration, and diagnostic traffic explicitly;
- forward node metadata, samples, sync observations, and health events to the
  A8;
- control and monitor both protected trunk-power branches; and
- recover deterministically from node reset, CAN bus-off, master reset, A8
  restart, and temporary disconnection.

### 9.3 A8 logger

The A8 firmware should:

- drive the master over SPI;
- remain the source of truth for desired node and sensor configuration;
- expose node discovery, capabilities, configuration, and effective state
  through the existing configuration and UI model;
- create one BDQ v2 stream per remote sensor stream;
- store native samples, sequence information, timing observations,
  discontinuities, configuration identity, and diagnostics;
- avoid interpolating or resampling remote streams in the logger; and
- present unambiguous node, sensor, bus, profile, synchronization, and loss
  status to the user.

The current master connector provides an `A8_IRQ` conductor, but A8 v1.0 does
not expose it. The SPI contract must support polling as the compatibility
baseline and may use the interrupt when later A8 hardware provides it. This
choice affects latency, power, CPU load, and master buffer sizing; operation
must remain correct if the interrupt is absent or missed.

## 10. Protocol contracts

### 10.1 CAN-FD application protocol

The first version is now drafted in `CAN-FD_Network_Protocol.md`. It defines an
implementable discovery/status subset, reserves the complete identifier space,
and proposes synchronization and compact IMU-stream formats. Configuration and
non-IMU stream bodies remain deferred pending the node I/O contract.

The complete protocol must cover:

- arbitration-ID allocation and priority;
- node identity, discovery, and expected-node behavior;
- protocol version and capability negotiation;
- separate stream identities for IMU, analogue, and I2C sources;
- sample packing and batching into 64-byte CAN-FD payloads;
- source sequence, native timestamp, batch-base time, and per-sample timing;
- status, diagnostics, reset, and synchronization messages;
- configuration read, write, acknowledgement, rejection, and effective-state
  messages;
- end-to-end integrity protection if the CAN frame CRC alone is insufficient;
- congestion, retry, bus-off, reset, and partial-node behavior; and
- explicit overflow and continuity-break semantics.

### 10.2 Synchronization protocol

Define:

- the owner of the master timebase;
- the relationship between SYNC edges and timestamp messages;
- pulse frequency and sequence identification;
- capture points and latency bounds in master, node, ADC, I2C, and IMU paths;
- clock-fit observations and uncertainty stored in BDQ v2;
- oscillator expectations and holdover behavior; and
- startup, reset, missed-sync, and loss-of-sync handling.

### 10.3 A8-to-master SPI protocol

The implemented version-1 bootstrap is specified in
`CAN-FD_Master_SPI_Protocol.md`. It fixes an 84-byte, little-endian,
CRC-protected slot and pipelined probe/fetch exchanges for master identity and
status. Polling is the compatibility baseline. This is intentionally only the
control-plane seed; the following data-plane matters remain to be defined:

Remaining definition work includes:

- flow control and bounded buffering;
- command/response and streaming priorities;
- restart, timeout, resynchronization, and partial-transfer handling; and
- access to diagnostics without starving sample traffic.

These contracts should be independently testable and should not depend on
particular application class layouts or compiler packing.

## 11. Throughput and buffering

A six-axis sample containing six signed 16-bit axes is 12 bytes before timing,
sequence, identity, configuration, and CAN framing overhead.

For four nodes, raw IMU axis payload alone is:

| Full six-axis rate per node | Raw payload across four nodes |
|---:|---:|
| 3.2 ksample/s | 153.6 kB/s, or 1.229 Mbit/s |
| 6.4 ksample/s | 307.2 kB/s, or 2.458 Mbit/s |

An illustrative fully populated node adds:

- two analogue channels at 1 kHz stored as 16-bit values: approximately
  4 kB/s per node; and
- two I2C sensors at 500 Hz with four-byte values: approximately 4 kB/s per
  node before metadata.

Across four nodes that example adds roughly 32 kB/s, or 0.256 Mbit/s, before
timestamps and CAN overhead. The actual budget must use the selected sensors,
rates, fields, batching, arbitration IDs, bit stuffing allowance, and retry
margin.

One CAN frame per sample is unacceptable. Measurements must be batched into
large CAN-FD payloads while preserving their native timing. The 6.4 ksample/s
profile may be tight once complete timing and protocol overhead are included,
especially because the MCU limit is 5 Mbit/s. Options include efficient batch
base timestamps, transmitting only required fields, selecting a lower native
ODR if the measured bandwidth permits it, and giving ancillary sensors bounded
rates and priorities.

Buffers absorb bursts and short service pauses; they cannot fix a sustained
average-rate mismatch. Every queue needs a calculated capacity, high-water
diagnostic, explicit overflow policy, and continuity indication.

## 12. Power architecture and risks

The current master design accepts either 3.3 V or VSYS from the A8-side
connection, generates a 5 V trunk supply with a TPS631000 buck-boost converter,
and feeds the front and rear trunk connectors through separate TPS2553
current-limited switches. Nodes regulate the distributed 5 V to local 3.3 V.

Both input zero-ohm resistors are populated. The default solder-jumper state is
VSYS selected (`JP2` bridged) and 3.3 V unselected (`JP1` open). Existing A8
hardware without a usable VSYS connection requires the opposite jumper state.
The mutually exclusive supply paths must never be bridged simultaneously.

Before committing the boards, establish:

- continuous and transient current available from each supported A8 variant;
- converter input range, efficiency, startup, thermal behavior, and stability;
- worst-case master and per-node current, including external analogue and I2C
  sensor loads;
- front and rear switch current-limit values and tolerance;
- cable and connector resistance and voltage at the furthest node;
- ground offset during CAN, IMU, and external-sensor activity;
- inrush when one or both branches and all nodes are connected; and
- connector and regulator fault behavior under shorts and hot connection.

Power for external sensors must be included explicitly. On the present node,
the analogue and I2C connectors use the same unswitched 3.3 V rail as the node
electronics. The interface specification must define a combined external-sensor
current budget and make clear that the ports do not have individual current
limiting or power switching.

## 13. Physical-bus guidance

- Use a true linear CAN trunk rather than a multiway star.
- Keep node stubs short.
- Enable exactly two termination networks, one at each physical end.
- Close both termination jumpers on an end board; leave both open otherwise.
- Leave master termination disabled when the master is in the middle.
- Treat the master's front and rear connectors as one continuous logical bus.
- Route CANH and CANL as a coupled pair and place protection at cable entry.
- Keep noisy switching, digital, and trunk-current paths away from the IMU,
  analogue inputs, reference supplies, and crystal.
- Give the IMU a mechanically quiet central location and observe manufacturer
  land-pattern and keep-out guidance.
- Treat SYNC as a transmission-line signal when harness length and edge rate
  require it; validate it over the real loom.
- Define connector keying and pin order to reduce reversal and wiring faults.
- Keep external I2C connections local to the node; they are not extensions of
  the long CAN trunk.

## 14. Open decisions

1. Repeat production-part availability/lifecycle checks before ordering.
2. Select accelerometer and gyro ODRs, ranges, FIFO format, and filter settings.
3. Measure amplitude response and group delay through the 1 kHz band.
4. Define supported analogue ranges, accuracy, calibration, and native rates.
5. Define the initial supported I2C sensor types, rates, interrupt behavior,
   power budget, and configuration schema.
6. Freeze nominal and data-phase CAN rates within the 5 Mbit/s MCU limit.
7. Define CAN-FD IDs, priorities, layouts, batching, versioning, and exact bus
   utilization.
8. Define native node-clock resolution, rollover, oscillator performance, and
   continuity rules.
9. Define hardware SYNC generation, capture, reporting, and uncertainty.
10. Decide whether and how the IMU synchronization input is used.
11. Extend the implemented A8-to-master bootstrap into a complete flow-control
    and streaming contract, retaining polling for A8 v1.0 and making `A8_IRQ`
    optional on later hardware.
12. Prove A8 power headroom and the supported harness and external-sensor load.
13. Freeze cable, connector, wire gauge, shielding/twisting, trunk length, and
    maximum stub length.
14. Correct and verify the CAN-transceiver exposed-pad connection on all node
    variants released for fabrication.
15. Decide which node variants are product candidates and complete their
    individual ERC, DRC, BOM, and manufacturing review.
16. Decide whether future CAN firmware update justifies its flash, protocol,
    security, and recovery cost.

## 15. Implementation and validation sequence

1. **Align the logger concepts — implemented as the logger foundation.** Define transport-independent provider,
   endpoint, logical-sensor, stream, identity, and desired/discovered/effective
   state models. Preserve the single existing configuration file and local-only
   entries through an explicit compatibility adapter. Establish bounded support
   for 32 configured sensors without merely doubling the current fixed
   per-sensor parameter stores.
2. **Prototype inventory and diagnosis without CAN hardware — implemented for
   local hardware and injectable remote observations.** Feed the new
   model from existing board profiles and local sensor startup results, produce
   structured multi-issue diagnostics, and exercise the Web UI and OLED using
   local devices and a simulated remote provider. Add restart-free sensor-runtime
   rebuilding, exclusive endpoint ownership across muted sensors, best-effort
   session planning, and startup/post-log/on-request discovery before adding the
   physical CAN transport.
3. **Add and validate the logger-to-master bootstrap — implemented.** Encode the
   fixed daughterboard wiring in A8/RC3 board profiles, serialize shared SPI
   access, support polling without IRQ, expose `off`, `auto`, and `required`
   policy, probe versioned master identity and status, and recover malformed
   SPI slots without yet fixing the sample data plane.
4. **Transfer the master inventory into the logger model — implemented.** Read
   the four strap-address records as a generation-consistent paged snapshot,
   retain stale and duplicate evidence, expose raw API diagnostics, and inject
   provider/endpoint observations without creating remote sensor drivers.
5. **Freeze candidate measurement profiles.** Review and bench-characterize
   the LSM6DSO32X ODR and filter choices for amplitude and phase through 1 kHz.
6. **Freeze the node I/O contract.** Define analogue performance and the first
   supported devices and rates for both I2C ports.
7. **Specify the protocols.** Write versioned CAN-FD, synchronization, and A8
   SPI contracts, including configuration, diagnostics, and recovery.
8. **Calculate worst-case throughput and buffers.** Include all node streams,
   frame overhead, arbitration, retries, A8 service pauses, and explicit
   margins.
9. **Validate power.** Measure A8 supply capability and model converter,
   harness, node, and external-sensor loads.
10. **Validate MCU pinmux choices.** Validate the G3507 RHB node and G3518 PM
   master assignments with authoritative tooling and encode them in separate
   firmware board definitions.
11. **Complete the hardware design.** Recheck parts and footprints, route both
   boards, run ERC/DRC, and complete manufacturing review.
12. **Bring up one node.** Validate rails, clocks, SWD, IMU SPI/FIFO, both ADC
   inputs, both I2C ports, CAN-FD, native timestamps, and SYNC capture.
13. **Bring up the master.** Exercise CAN receive buffering and A8 SPI under
   synthetic worst-case traffic and deliberate A8 service stalls.
14. **Scale to four nodes.** Validate utilization, queue margins, priority,
    recovery, resets, and at least ten minutes of loss-free operation.
15. **Integrate BDQ v2.** Confirm that every stream, configuration identity,
    native timing observation, diagnostic, and discontinuity survives into
    desktop processing.
16. **Validate relative timing.** Use a common excitation or electrical timing
    fixture, fit each node clock, and measure phase uncertainty.
17. **Validate the real installation.** Repeat power, signal-integrity, loss,
    synchronization, EMC, analogue-noise, and thermal tests on the complete
    harness and bike.

## 16. Initial acceptance criteria

- Four fully populated nodes log continuously for at least ten minutes at the
  selected production profile without unexplained sample loss.
- Acceleration response through 1 kHz meets the agreed amplitude-error limit.
- Relative inter-node phase uncertainty at 1 kHz meets the agreed target;
  10 degrees corresponds to approximately 27.8 us.
- Gyro performance and usable bandwidth are documented.
- Both analogue channels meet their specified range, accuracy, noise, and
  timing requirements.
- Both I2C ports meet their specified rates without causing IMU FIFO loss or
  unacceptable timing uncertainty.
- Sensor FIFO loss, node queue loss, CAN loss, master queue loss, resets, and
  loss of synchronization are separately detectable in BDQ output.
- Recovery from node reset, CAN bus-off, master reset, A8 restart, or temporary
  disconnection is deterministic and records an explicit continuity break.
- Worst-case current, voltage drop, inrush, and temperature remain within
  component and wiring limits.
- The real harness operates at the selected CAN rate with documented error
  counts and adequate margin.
- A8 logging and desktop import preserve all remote streams and diagnostics
  without logger-side resampling.
- Final node and master release builds meet their agreed flash, SRAM, stack,
  CPU, DMA, and queue-headroom targets.

## 17. Relevant files

- Node project: `C:\Users\benco\OneDrive\BODAQS-private\CANBUS_IMU`
- Node schematic: `C:\Users\benco\OneDrive\BODAQS-private\CANBUS_IMU\CANBUS_IMU.kicad_sch`
- Node PCB: `C:\Users\benco\OneDrive\BODAQS-private\CANBUS_IMU\CANBUS_IMU.kicad_pcb`
- Node production BOM: `C:\Users\benco\OneDrive\BODAQS-private\CANBUS_IMU\production\bom.csv`
- No-IMU node project: `C:\Users\benco\OneDrive\BODAQS-private\CANBUS_NODE_NO_IMU`
- No-I2C node project: `C:\Users\benco\OneDrive\BODAQS-private\CANBUS_NODE_NO_I2C`
- IMU-only node project: `C:\Users\benco\OneDrive\BODAQS-private\CANBUS_NODE_IMU_ONLY`
- Master project: `C:\Users\benco\OneDrive\BODAQS-private\CANBUS_master_G3518`
- Master schematic: `C:\Users\benco\OneDrive\BODAQS-private\CANBUS_master_G3518\CANBUS_master.kicad_sch`
- Master PCB: `C:\Users\benco\OneDrive\BODAQS-private\CANBUS_master_G3518\CANBUS_master.kicad_pcb`
- Master BOM: `C:\Users\benco\OneDrive\BODAQS-private\CANBUS_master_G3518\CANBUS_master_BOM.csv`
- BDQ v2 contract: `C:\Users\benco\dev\BODAQS\docs\firmware\BDQ_v2_Multi_Stream_Contract.md`
- Logger-to-master bootstrap protocol: `C:\Users\benco\dev\BODAQS\docs\firmware\CAN-FD_Master_SPI_Protocol.md`
- CAN-FD network protocol: `C:\Users\benco\dev\BODAQS\docs\firmware\CAN-FD_Network_Protocol.md`

