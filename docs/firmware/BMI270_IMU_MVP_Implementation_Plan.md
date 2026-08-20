# BMI270 IMU MVP Implementation Plan

- Status: Accepted; Phases 0-4.5 firmware implementation complete; hardware acceptance pending
- Target outcome: A rideable single-IMU prototype that produces trustworthy data for collection-performance assessment and initial post-processing design
- Related roadmap: [BMI270 IMU Firmware Roadmap](BMI270_IMU_Roadmap.md)
- Normative data contract: [BMI270 IMU MVP Data Contract](BMI270_IMU_MVP_Data_Contract.md)

## 1. MVP definition

The MVP is complete when BODAQS can record all native 200 Hz accelerometer and gyroscope samples from one frame-mounted BMI270 during representative rides, make loss and timing quality observable, and decode the result into a dense IMU stream for quality review.

The MVP is deliberately not an orientation estimator. Its output must be good enough to decide whether:

- the selected range, rate, filtering, bus, mount, and storage path work in the field;
- timing is adequate for single-IMU orientation experiments;
- startup gyro observations and temperature are useful calibration inputs;
- any firmware evidence is missing before an offline pipeline is designed; and
- the programme should advance beyond a single-IMU prototype.

## 2. Assumptions and dependencies

The implementation plan assumes:

- the target logger board exposes a usable second I2C bus at 3.3 V logic levels;
- the selected BMI270 module has appropriate local decoupling and pull-ups, or the harness provides them;
- the frame mount is rigid, weather-protected as required, and has an unambiguous orientation;
- 500 Hz logging remains usable with the normal ride sensor set and SD card;
- BDQ is used for the validation rides;
- no BMI270 interrupt signal is available for the first prototype; and
- a host Python environment is available immediately after rides for decode and QC.

Bus electrical quality, connector assignment, module schematic, and mount design are hardware dependencies rather than firmware details. They must be reviewed before the first soak test. If the target board cannot provide the assumed bus or logging rate, revisit the architecture rather than silently lowering fidelity.

## 3. Fixed MVP decisions

| Area | MVP decision |
|---|---|
| Sensor | One Bosch BMI270 over I2C |
| Placement | Rigidly mounted to the sprung bicycle frame |
| Body frame | Right-handed: X forward, Y left, Z up |
| IMU rate | Accelerometer and gyroscope at 200 Hz |
| Initial ranges | Accelerometer plus or minus 16 g; gyroscope plus or minus 2000 degrees per second |
| Bus | 400 kHz, normally I2C bus 1 where the board profile exposes it |
| Acquisition | BMI270 FIFO drained by the existing asynchronous I2C scheduler |
| Interrupt | Not required; polling is the baseline |
| Logger rate | 500 Hz while the MVP IMU is active |
| Row behaviour | Each native IMU sample emitted once; other rows explicitly invalid |
| Authoritative data | Raw signed counts, estimated native sample ticks, sequence, status, timing observation, temperature |
| Calibration | Record mounting and stationary startup observation; do not modify raw samples |
| File format | BDQ is the validated full-rate format; CSV is diagnostic only |
| Fusion | Offline and out of MVP |

If testing invalidates one of these decisions, update this document and the named profile rather than introducing an undocumented special case.

## 4. Architecture

### 4.1 Data path

    BMI270 accel/gyro at 200 Hz
        |
        v
    BMI270 hardware FIFO with sensor-time information
        |
        v
    I2C scheduler callback drains all complete frames
        |
        v
    Fixed-capacity IMU sample queue
        |
        v
    Existing 500 Hz SensorManager row sampler
        |
        +-- queued frame available: emit it once with sample_valid=1
        |
        +-- no frame available: emit neutral placeholders with sample_valid=0
        |
        v
    BDQ mixed-type sample frame
        |
        v
    Host decoder extracts valid rows and reconstructs native 200 Hz time

The sensor callback must not allocate memory, wait on storage, or perform expensive transformations. It should read the FIFO, parse complete frames, update counters, and enqueue fixed-size sample records.

Session boundaries need explicit treatment. Starting a log must discard and count pre-session FIFO/queue contents before the first accepted sample. Stopping must stop new sensor production, perform a final FIFO drain, write the remaining queued samples, publish final counters, and only then close the log. No sample should cross silently from one session to another.

### 4.2 Why the logger runs at 500 Hz

The existing BODAQS logger expresses the row period as an integer number of milliseconds. It can represent 200 Hz but not the BMI270's 400 Hz profile exactly. More importantly, a nominal 200 Hz producer and nominal 200 Hz consumer have independent clocks, so the producer can gradually outrun the consumer.

Using the existing 500 Hz row rate gives the 200 Hz queue a strict average drain-rate margin without changing the global timebase. The validity channel is mandatory so that the 300 empty rows per second cannot be mistaken for repeated samples.

Firmware resolves the highest safe sparse-row IMU output rate for the effective
logger rate, up to the configured `max_output_rate_hz`; it must not reject a
log solely because a low logger rate cannot carry the user's maximum. The
current profile resolves 10/20/50/100/200/500+ Hz logger rates to
5/10/25/50/100/200 Hz IMU output respectively. Integrity and hardware faults
still reject log start.

`gyro_bias_mode` remains an explicit advanced sensor choice because it changes
the provenance of logged gyro counts. The optional `ioc_diagnostics` register
trace is deliberately hidden from the normal configuration UI and API schema;
it remains a persisted experimental setting for directed IOC experiments.

### 4.3 Sample record

The internal queued record should contain fixed-width fields:

- signed 16-bit accelerometer X, Y, and Z;
- signed 16-bit gyroscope X, Y, and Z;
- unsigned 32-bit internal firmware sequence, with its low 24 bits emitted to the current row path;
- unsigned 32-bit estimated sample tick on the BMI270 24-bit sensor-time grid;
- host monotonic time associated with the timing anchor or acquisition;
- signed temperature sample or explicit temperature reference;
- status flags.

No dynamic allocation is permitted in the acquisition path. Queue capacity must cover measured worst-case logger latency with margin. The selected capacity and its time coverage must be documented after measurement.

### 4.4 Logged columns

Proposed column names for a sensor named frame_imu are:

| Suffix | Storage | Unit | Invalid-row value | Meaning |
|---|---|---|---|---|
| accel_x_raw | int16 | count | 0 | Native accelerometer X |
| accel_y_raw | int16 | count | 0 | Native accelerometer Y |
| accel_z_raw | int16 | count | 0 | Native accelerometer Z |
| gyro_x_raw | int16 | count | 0 | Native gyroscope X |
| gyro_y_raw | int16 | count | 0 | Native gyroscope Y |
| gyro_z_raw | int16 | count | 0 | Native gyroscope Z |
| sensor_time_u24 | uint32 | tick | 0 | Estimated sample tick on the 24-bit sensor clock grid |
| seq_u24 | uint32 | count | 0 | Low 24 bits of the firmware sequence assigned to native samples |
| temperature_raw | int16 | count | 0 | Associated or most recent die-temperature reading |
| sample_age_us | float32 | us | NaN | Time from estimated sample instant to logger row |
| status_flags | uint16 | bitfield | 0 | Timing, FIFO, temperature, and recovery state |
| sample_valid | uint16 | boolean | 0 | One only when this row carries a new native sample |

Post-processing must filter sample_valid before using any other sample value. The metadata should declare:

- source semantics: asynchronous FIFO, emitted once;
- invalid-row policy;
- sensor-time tick period and wrap modulus;
- whether temperature is per sample, per drain, or held;
- definitions for every status bit;
- sample-age definition and clock domain.

The 24-bit sequence is intentional. Current sensor rows use float32 intermediates, which represent every integer only through 2^24. A modulo-2^24 sequence remains exact and wraps after about 23 hours at 200 Hz; the host unwraps it in the same way as sensor time. Wider cumulative counters belong in the session diagnostic summary rather than ordinary sensor columns unless the row value representation is redesigned.

### 4.5 Timing model

The driver should use the BMI270 sensor-time information to assign native sample order and time within FIFO batches. A host monotonic timestamp around FIFO acquisition provides the cross-clock observation. Post-processing can then unwrap the 24-bit counter and fit or validate the mapping to logger time.

The logger row timestamp alone is not the native sample timestamp. sample_age_us records the estimated age when a native sample is emitted into a row. If the driver cannot form a trustworthy age for a sample, it stores NaN and sets a degraded-timing flag.

The first implementation does not need a continuously fitted clock model in firmware. It does need to retain enough anchors and flags for the host to evaluate offset, jitter, drift, FIFO batching, and counter wrap.

## 5. Firmware and host areas affected

Expected firmware touchpoints:

- firmware/platformio.ini — pinned BMI270 driver dependency or reproducible vendored source;
- firmware/src/SensorTypes.h — new BMI270 IMU sensor type;
- firmware/src/Sensor.h — explicit column storage type and IMU metadata support;
- firmware/src/SensorRegistry.cpp — construction and configuration;
- firmware/src/ConfigManager.cpp — strict sensor-type parsing and validation;
- firmware/src/BdqLogWriter.cpp — signed 16-bit and unsigned 32-bit column serialization;
- firmware/src/LoggingManager.cpp — start-time rate validation and IMU diagnostics integration;
- firmware/src/BMI270ImuSensor.h and .cpp — transport, configuration, FIFO service, row adapter, metadata, diagnostics;
- firmware/src/ImuSampleQueue.h — fixed-capacity queue and counters, if not private to the driver;
- firmware test files for queue, sparse-row, storage-conversion, and configuration behaviour.

Expected documentation and host touchpoints:

- docs/firmware/BDQ_v1_format.md — additive storage types and IMU row semantics;
- analysis/bodaqs_analysis/io_bdq.py — signed 16-bit decoder support;
- analysis/bodaqs_analysis/imu.py — extraction, timing reconstruction, scaling, and QC summary;
- analysis/tests/test_io_bdq.py — signed and unsigned boundary fixtures;
- analysis/tests/test_imu.py — valid-row extraction, tick wrap, gaps, flags, and metrics;
- an example sensor configuration under firmware/configs once the supported board and connector are confirmed.

Exact file placement may follow adjacent repository conventions discovered during implementation, but the responsibilities above should remain separated.

## 6. Implementation phases

### Phase 0 — Freeze the contract and test fixtures (complete)

Purpose: define the observable behaviour before hardware code.

Tasks:

1. Add the BMI270 sensor type, canonical name, and firmware-version impact.
2. Define the orientation_200 profile, coordinate convention, mounting transform syntax, channel names, storage types, flags, and invalid-row policy.
3. Define the timing observation and sample_age_us semantics.
4. Define session metadata and final diagnostic summary fields.
5. Create synthetic batches covering signed extrema, normal frames, missing frames, skipped FIFO frames, queue overflow, and sensor-time wrap.

Acceptance checks:

- A reviewer can determine the physical and timing meaning of every column without reading driver code.
- The fixture distinguishes zero acceleration from an invalid row.
- Loss, recovery, and degraded timing all have explicit representations.
- The contract has no on-device orientation or silently applied calibration.

### Phase 1 — Extend BDQ typed-column support (complete)

Purpose: store negative raw counts and full-width sequence/timing values without coercion.

Tasks:

1. Add an explicit storage-type field to SensorColumnDescriptor with a legacy/default option.
2. Preserve current storage selection for every existing sensor descriptor using the default.
3. Add int16 serialization and confirm uint32 serialization through the mixed-row writer for values no greater than 2^24.
4. Add range checks or well-defined conversion behaviour at the writer boundary.
5. Update BDQ documentation and the Python decoder.
6. Add round-trip fixtures at -32768, -1, 0, 32767, and representative exactly representable uint32 values through 0xFFFFFF.

Implementation notes:

- Do not reinterpret all existing raw columns as signed.
- Keep the BDQ magic and established chunks if the additive type can be decoded from schema metadata.
- If compatibility analysis shows that existing readers cannot safely skip the new type, name and document the schema revision explicitly before proceeding.
- Document that the current float row buffer cannot carry arbitrary uint32 column values exactly; the IMU uses only 24 significant bits.

Acceptance checks:

- Existing BDQ fixtures decode identically.
- New signed counts and 24-bit sequence/timing values round-trip bit exactly.
- A reader produces a clear unsupported-type error rather than misaligning later fields.
- Existing firmware sensors compile and retain their current column storage.

### Phase 2 — Integrate the BMI270 driver and transport

Purpose: reliably identify and configure one physical unit.

Tasks:

1. Select the Bosch-maintained BMI270 SensorAPI and pin an exact revision; record its licence and provenance.
2. Implement scheduler-safe I2C read, write, and delay callbacks through the existing I2C manager.
3. Validate chip identity and load the BMI270 configuration image.
4. Configure orientation_200 and read back the effective configuration.
5. Put the sensor in a defined state on start, stop, and failed initialization.
6. Add bounded retry/recovery behaviour and counters.
7. Define session start/stop sequencing so configuration, FIFO state, and counters have unambiguous boundaries.

Implementation notes:

- Use the board profile rather than hard-coded ESP32 pins.
- Default to the less-contended bus exposed for external sensors.
- Do not hold an I2C mutex while waiting for a sensor delay.
- Do not enable internal offset compensation or write BMI270 NVM.

Acceptance checks:

- Correct device identity is reported at addresses 0x68 and 0x69.
- Missing device, wrong chip, invalid bus, and bus errors fail visibly.
- Requested and effective profile values appear in metadata.
- Existing display, fuel-gauge, RTC, and angle-sensor I2C clients still operate.

### Phase 3 — Implement FIFO acquisition and bounded buffering

Purpose: acquire every native sample without blocking the logger.

Tasks:

1. Enable accelerometer, gyroscope, and sensor-time FIFO content.
2. Poll at an initial 200 Hz and drain all complete available frames on each scheduled service.
3. Use the Bosch parser where practical; isolate any BODAQS-specific ordering and timing logic for unit testing.
4. Translate FIFO skip, overflow, partial-frame, and parser errors into counters and flags.
5. Enqueue fixed-size sample records in order.
6. Define deterministic queue-full behaviour: drop the newly arrived batch or oldest records, increment exact counters, and mark the next stored sample with a discontinuity flag.
7. Measure callback duration, FIFO depth, and queue high-water mark.
8. Implement a final FIFO drain and queue flush before BDQ finalization.

Implementation notes:

- Choose the queue-full policy once and document it. Dropping newest samples is the simpler evidence-preserving default because already-queued order remains intact.
- Do not silently reset sequence across bus recovery.
- Handle the 24-bit sensor-time wrap explicitly; the raw value remains stored.
- Treat a parser ambiguity as degraded timing, not a reason to invent timestamps.

Acceptance checks:

- Synthetic multi-frame batches preserve order and axes.
- A run longer than one sensor-time wrap reconstructs continuously.
- Forced scheduler stalls produce counted and visible loss.
- FIFO draining performs no heap allocation after initialization.
- Measured queue headroom covers the intended system stalls with margin.
- Back-to-back sessions contain no stale samples and do not silently lose the final queued batch.

### Phase 4 — Add the sparse-row sensor adapter and configuration

Purpose: make the queued stream available through the existing logger without presenting held values as fresh data.

Tasks:

1. Register bmi270_imu_i2c and expose the minimal configuration fields.
2. Validate unique sensor identity, supported bus/address, named profile, and any accepted assisted-orientation matrix.
3. Reject unknown sensor types instead of falling back to AnalogPot.
4. Consume no more than one queued sample per 500 Hz logger row.
5. Emit sample_valid=0 and documented placeholders when no sample is available.
6. Calculate sample_age_us from the best available native-to-host timing observation.
7. Enforce the supported logger-rate relationship at logging start.
8. Publish all channel and session metadata.
9. Coordinate logger shutdown with the driver's final drain and diagnostic-summary publication.

Suggested configuration:

    sensor1.type=bmi270_imu_i2c
    sensor1.name=frame_imu
    sensor1.imu_id=frame_imu_001
    sensor1.domain=frame
    sensor1.end=rear
    sensor1.mount_point=
    sensor1.i2c_bus=1
    sensor1.i2c_addr=104
    sensor1.profile=orientation_200
    sensor1.startup_bias_capture_s=5
    sensor1.calibration_ref=

Acceptance checks:

- Exactly one valid row is written for every successfully enqueued native sample.
- No sample is duplicated when the logger runs faster than the IMU.
- Queue backlog drains while maintaining sequence order.
- Invalid accepted orientation matrices and unsupported logger rates prevent a misleading session; an unset orientation still permits sensor-native raw logging.
- Existing configurations remain valid, while unknown type names now fail visibly.
- Session start and stop preserve the defined FIFO/queue boundary semantics.

### Phase 4.5 — Consolidate IMU signal semantics

Purpose: make IMU vectors first-class signals before calibration observations and host-derived channels extend the contract.

Tasks:

1. Classify the mechanically co-moving mounting domain as `unsprung`, `frame`, or `steering`, qualified by `end=front|rear|none` under the documented constraints.
2. Retain optional `mount_point` as descriptive installation detail without making it a primary semantic selector.
3. Mark raw accelerometer and gyro axes with explicit `component`, sensor-local `vector_group`, and `coordinate_frame=sensor_native` metadata.
4. Record the static installation transform as `sensor_native` to `body_local`; do not apply it to raw firmware samples.
5. Preserve these additive fields through CSV sidecars, embedded BDQ schemas, channel metadata, and the analysis signal registry.
6. Continue reading the original `location` configuration key as a compatibility alias for `domain`.

Domain/end constraints:

| domain | permitted end | meaning |
|---|---|---|
| `unsprung` | `front`, `rear` | Assembly moving predominantly with the corresponding axle, including fork lowers, caliper or rear-triangle mounting |
| `frame` | `front`, `rear`, `none` | Main sprung frame; front/rear is a coarse mounting region |
| `steering` | `front` | Sprung assembly rotating about the steering axis |

Acceptance checks:

- Existing `location=frame` configuration remains valid and produces canonical `domain=frame` metadata.
- Invalid domain/end combinations prevent logging with an actionable error.
- Each raw accel/gyro triplet is groupable without parsing column names.
- Firmware still writes sensor-native raw values and performs no coordinate rotation.
- CSV-sidecar and BDQ ingestion preserve the new fields in `meta.signals`.

### Phase 5 — Add calibration observations and diagnostics

Purpose: give field data enough context to assess quality and develop bias handling.

Tasks:

1. During the configured start window, accumulate gyro mean and variance, accelerometer magnitude mean/variance, temperature, and sample count.
2. Accept the observation only if explicit stationarity thresholds pass; otherwise store a rejection reason.
3. Record the result but do not subtract it from raw gyro samples.
4. Add saturation counters for each accelerometer and gyro axis.
5. Add I2C, FIFO, parser, queue, sequence, timing, and recovery diagnostics.
6. Put cumulative results in the final session summary and enough per-sample flags in the data to localize incidents.
7. Provide a manual bench health/self-test path if the selected Bosch API supports it without compromising normal session startup; otherwise document it as the first post-MVP item.

Acceptance checks:

- A stationary start produces repeatable statistics and a valid result.
- Moving the unit during the window rejects the result.
- A deliberate clipping, FIFO overflow, I2C error, or queue overflow is visible and localized.
- Raw samples are identical regardless of whether a startup observation is accepted.

### Phase 6 — Build host extraction and QC

Purpose: turn a ride log into evidence about the collection system without prematurely choosing an orientation algorithm.

Tasks:

1. Decode int16 and uint32 IMU fields.
2. Extract only sample_valid rows into a dense IMU table or session secondary stream.
3. Unwrap the 24-bit sensor clock and detect sequence/tick discontinuities.
4. Convert counts to SI using effective profile metadata while preserving raw columns.
5. Apply the mounting transform as a reversible derived operation.
6. Calculate a compact QC report:
   - decoded native sample count and effective ODR;
   - sequence gaps, duplicates, and out-of-order samples;
   - FIFO, queue, timing, and recovery flags;
   - acquisition-age percentiles and maximum;
   - sensor-clock drift/residual relative to logger time;
   - saturation fraction and event locations per axis;
   - temperature range;
   - stationary gyro mean and standard deviation;
   - duration and file-size rate.
7. Produce basic time-series and spectrum-ready outputs without implementing fusion.

Acceptance checks:

- Synthetic wrap and loss cases produce the expected dense timebase and warnings.
- Missing metadata produces a clear failure or explicitly degraded result.
- A valid ride log can be plotted in raw counts, SI units, and bicycle axes.
- QC output is deterministic and suitable for comparing rides.

### Phase 7 — Bench and system verification

Purpose: prove the acquisition path before riding.

Tests:

1. Static six-face placement for signs, axis map, gravity magnitude, and offsets.
2. Known hand rotations around each body axis for gyro signs and cross-axis plausibility.
3. At least a 12-minute run to cross the approximately 655-second sensor-time wrap.
4. A minimum one-hour soak at 500 Hz logging with the normal sensor set.
5. Forced FIFO overflow and software queue overflow.
6. Temporary I2C disconnect or injected bus error and documented recovery behaviour.
7. Warm-up from ambient to steady temperature while stationary.
8. Simultaneous GPS and existing analogue/angle sensors where available.
9. A sharp tap or other common physical event visible to independent channels for coarse timing validation.
10. SD-card stress using the expected full sensor configuration.

Acceptance checks:

- All loss is either zero or exactly observable through counters/discontinuities.
- No logger reset, watchdog event, corrupt BDQ frame, or material UI regression occurs.
- Host reconstruction remains monotonic across native clock wrap and recovery.
- Axis signs agree with the documented body frame.
- Callback duration, queue high-water mark, bus use, and SD queue use have recorded margins.

### Phase 8 — Ride validation and go/no-go review

Purpose: establish whether the prototype is good enough to shape post-processing.

Ride set:

1. Smooth-surface baseline with steady-speed sections.
2. Braking, acceleration, climbing, descending, and representative cornering.
3. Rough surface or trail features representative of the intended use.
4. Repeated short section, where practical, to assess session-to-session repeatability.

Operating protocol:

- inspect and rigidly secure the sensor and cable;
- record sensor identity, location, mounting transform, bicycle, tyre/suspension setup, and ride notes;
- begin with at least ten seconds stationary;
- perform a visible tap/tilt marker where safe;
- ride normally without protecting the sensor from representative inputs;
- finish with another stationary period and a repeatable final orientation;
- retain the original BDQ and generated QC report together.

Provisional exit criteria:

- at least three representative rides and two cumulative hours of logged IMU data;
- no unreported loss, corrupt frames, resets, or logging-queue drops;
- any reported loss is sufficiently rare and localized to permit analysis, with a provisional target below 0.01 percent during normal riding;
- reconstructed native rate is stable around the configured 200 Hz and has no unexplained discontinuities;
- acquisition age is bounded and stable, with a provisional target below 15 ms at the 99th percentile;
- cross-clock timing residual is measured, with a provisional target below 1 ms after host reconstruction;
- gyroscope clipping is zero in normal riding;
- accelerometer clipping is absent or rare enough that its affected manoeuvres are explicitly understood;
- mounting remains secure and axes/configuration remain unambiguous;
- startup stationary observations are usually accepted and sufficiently repeatable to seed offline bias work;
- existing sensor logging and logger usability remain acceptable;
- the host can produce a dense, scaled, body-frame IMU stream and QC report from every accepted ride.

The numeric thresholds are initial engineering targets, not product guarantees. The review should report measured distributions and decide whether to tighten, relax, or replace them.

## 7. Test implementation

### Firmware automated tests

Add or extend tests for:

- explicit column storage selection and legacy defaults;
- signed and unsigned serialization boundaries;
- fixed queue ordering, wrap, high-water mark, and overflow policy;
- FIFO batches, partial frames, skip frames, sensor-time frames, and wrap;
- sparse-row one-shot emission;
- start flush, final drain, and back-to-back session boundaries;
- invalid-row placeholders and validity;
- mounting-transform validation;
- unknown sensor-type rejection;
- supported logger-rate validation;
- startup-stationarity acceptance and rejection;
- diagnostic counter saturation or rollover policy.

### Host automated tests

Add fixtures and tests for:

- old BDQ logs with no IMU;
- new mixed rows containing int16, uint16, uint32, and float32;
- valid-row filtering;
- native clock wrap;
- missing and duplicate sequence values;
- timing-degraded flags;
- scale conversion and mounting transform;
- saturation and acquisition-age metrics;
- absent or inconsistent metadata.

### Build and regression commands

Use the repository's normal environments and test commands. At minimum:

    cd firmware
    pio run

    cd analysis
    pytest -q tests/test_io_bdq.py tests/test_imu.py

If firmware native/unit-test environments exist or are introduced, run those separately and record them in the implementation handoff.

## 8. Work order and dependencies

| Order | Work package | Depends on | Relative effort |
|---|---|---|---|
| 1 | Contract and fixtures | None | Small |
| 2 | BDQ typed storage and host decoding | Contract | Medium |
| 3 | BMI270 transport and profile | Contract | Medium |
| 4 | FIFO acquisition and fixed queue | Driver transport | Large |
| 5 | Registry, sparse-row adapter, metadata | Typed storage and queue | Medium |
| 6 | Calibration observations and diagnostics | Working acquisition | Medium |
| 7 | Host extraction and QC | Typed decoder and metadata | Medium |
| 8 | Bench/fault/soak verification | Integrated firmware and QC | Medium |
| 9 | Ride campaign and review | Bench gate passed | Medium |

The first vertical slice should be one BMI270 producing valid signed samples into a synthetic or short BDQ file and decoding them on the host. Diagnostics and timing fidelity are then completed before ride testing.

## 9. Pull-request boundaries

Prefer small, reviewable changes:

1. BDQ descriptor/storage extension, documentation, decoder, and round-trip tests.
2. BMI270 dependency, I2C transport, profile initialization, and hardware smoke test.
3. FIFO decoder, fixed queue, diagnostics, and unit tests.
4. Sensor registry/configuration, sparse-row emission, metadata, and integration tests.
5. Startup observation, session summary, host IMU extraction/QC, and tests.
6. Example configuration plus recorded bench and ride-validation results.

Do not combine an orientation filter, GPS fusion, multi-IMU format redesign, or unrelated sensor refactor into these changes.

## 10. Definition of done

MVP implementation is done when:

- one documented configuration creates a rideable 200 Hz frame-IMU session;
- all native samples that reach firmware are stored once and only once;
- hardware FIFO loss, software queue loss, I2C failures, saturation, and timing degradation are visible;
- raw signed values, identity, profile, mounting, temperature, native time, and calibration observation are preserved;
- existing sensor configurations and BDQ logs remain compatible;
- automated tests, all supported firmware builds, bench checks, and soak checks pass;
- the ride-validation set meets or explicitly disposes of every exit criterion;
- a host report demonstrates that accepted logs can seed post-processing work;
- remaining limitations and the next calibration/timing decisions are recorded from evidence rather than assumed.

## 11. Post-MVP decision record

At the final review, record answers to:

1. Is 200 Hz sufficient for the useful single-IMU spectrum?
2. Are plus or minus 16 g and plus or minus 2000 degrees per second appropriate?
3. Is FIFO polling adequate, or is an interrupt required?
4. Is reconstructed timing adequate for orientation and GPS comparison?
5. Is simple per-session gyro bias enough, or is temperature modelling justified?
6. Does six-position accelerometer calibration materially improve the intended outputs?
7. What GPS receiver-time and accuracy fields must be added before fusion experiments?
8. Is the sparse-row representation acceptable for continued single-IMU work?
9. What storage and clock model should replace it before multi-IMU work?
10. Is I2C viable for the intended physical sensor locations?

Only after this review should the project commit to the offline estimator scope or to higher-rate and multi-IMU firmware architecture.

## 12. Phase 0/1 implementation record

Completed on 2026-08-06:

- accepted roadmap and implementation-plan status recorded;
- normative `bodaqs.bmi270_imu_mvp.v1` data contract added initially and superseded by v2 for assisted rotation-matrix installation orientation;
- stable `bmi270_imu_i2c` type key and enum value added without exposing the unfinished driver in the sensor-choice UI;
- explicit Automatic, Int16, UInt16, Int32, UInt32, and Float32 sensor-column storage selections added;
- legacy Automatic storage inference preserved;
- BDQ int16/uint32 packing and schema emission implemented with range/error handling;
- host int16 decoding implemented;
- committed fixtures added for signed extrema, exact 24-bit values, legacy storage types, and unsupported-type failure;
- BDQ v1 parser contract updated.

Validation:

- 14 focused host parser tests passed;
- the default PlatformIO environment passed;
- production builds passed for `thingplus_s3_usb_cdcserial`, `thingplus_s3_usb_uartserial`, `thingplus_s3_usb_cdcserial_uart_i2c1`, `thingplus_s3_usb_cdcserial_bodaqs_4f`, and `bodaqs_s3_mini_n4r2`;
- the optional native host C++ test target was not run because GNU Make and a host C++ compiler were not available in the execution environment.

## 13. Phase 2 implementation record

Firmware implementation completed on 2026-08-06:

- Bosch's official BMI270 SensorAPI is pinned to Git revision `41129fcfe39c583ee5462d79195741945d51c1fe`; its upstream licence is BSD-3-Clause and the pinned BMI270 header identifies API version 2.86.1;
- a reproducible PlatformIO pre-build manifest constrains the upstream package to `bmi2.c` and `bmi270.c`, avoiding accidental compilation of hardware-specific upstream examples;
- `BMI270I2CTransport` adapts the Bosch callbacks to `I2CManager`, uses its per-bus mutex, performs repeated-start register reads, bounds transfer sizes and lock waits, and releases the bus before Bosch-requested delays;
- transport diagnostics distinguish invalid arguments, unavailable buses, lock timeouts, register/payload failures, transaction failures, short requests, and short reads, with operation, failure, streak, and recovery counters;
- `BMI270Device` validates bus and address, probes the BMI270 chip ID, loads Bosch's configuration image, records its version and internal status, and exposes explicit lifecycle and failure-step diagnostics;
- the `orientation_200` profile configures both sensors at 200 Hz, plus or minus 16 g and plus or minus 2000 degrees per second, with the accepted bandwidth/performance choices, explicitly disables accelerometer and gyroscope offset compensation, enables accelerometer, gyroscope, and temperature, and requires exact configuration read-back;
- initialization is limited to three attempts with a fixed 25 ms inter-attempt delay, fails immediately for invalid parameters or the wrong chip, and attempts to quiesce enabled sensing after a later initialization failure while preserving the primary fault;
- suspend, resume, recovery, and shutdown behaviour are explicit and do not write BMI270 NVM; and
- pure profile matching and mismatch tests were added independently of the Bosch and Arduino headers.

The driver layer is intentionally not registered in the sensor UI or configuration factory yet. FIFO acquisition and bounded buffering are Phase 3 prerequisites; exposing a selectable sensor before those exist would create a configuration that appears usable but cannot record the agreed data contract.

Software validation:

- a clean PlatformIO dependency installation compiled only the two intended Bosch sources;
- production builds passed for `thingplus_s3_usb_cdcserial`, `thingplus_s3_usb_uartserial`, `thingplus_s3_usb_cdcserial_uart_i2c1`, `thingplus_s3_usb_cdcserial_bodaqs_4f`, and `bodaqs_s3_mini_n4r2`;
- the 14 focused BDQ host parser tests continued to pass; and
- compile-time assertions bind every raw profile code to the pinned Bosch constants.

Hardware acceptance remains open until a BMI270 fixture is available. The smoke test must exercise both valid addresses, missing and wrong-device cases, injected bus failures, configuration read-back, suspend/resume/recovery, and concurrent operation of the display, fuel gauge, RTC, and existing angle sensors. The Phase 2 code is complete, but the phase must not be represented as hardware-accepted before those checks pass.

## 14. Phase 3 implementation record

Firmware implementation completed on 2026-08-06:

- `BMI270FifoAcquisition` implements the existing `I2CAsyncClient` contract at a fixed 200 Hz target rate and remains muted outside an explicit logging session;
- BMI270 FIFO configuration is explicit header mode with accelerometer, gyroscope, and sensor-time content, filtered data, no downsampling, stream-on-full behaviour, no interrupt watermark, and exact read-back of the managed configuration, filter, downsample, and watermark fields;
- FIFO data is read in one I2C burst, as required by the device FIFO semantics; a bounded read plan accounts for complete samples that can arrive during the transfer, the four-byte sensor-time frame (header plus payload), and an over-read marker, with a 2304-byte transport buffer covering the 2048-byte FIFO worst case;
- a BODAQS parser handles the interleaved combined gyro/accelerometer, sensor-time, skip, input-configuration, over-read, invalid, unpaired, and partial-frame cases without allocation;
- the custom parser is used because the Bosch extraction APIs produce separate accelerometer and gyroscope arrays and collapse control-frame position, which would prevent exact attachment of skip/recovery evidence to the next paired sample; compile-time assertions bind the parser's raw headers to the pinned Bosch definitions;
- native combined frames are translated into fixed-width `BMI270ImuSample` records with raw axes, raw temperature, full internal sequence, estimated per-sample 24-bit native ticks, acquisition timing/span, and contract status flags;
- a 512-record lock-free single-producer/single-consumer queue provides 2.56 seconds of nominal coverage at 200 Hz, uses a documented drop-newest policy, and has a compile-time guarantee that its atomic indices are lock-free;
- queue overflow preserves already-buffered order, advances sequence for every parsed sample, counts each rejected new sample, and marks the first later stored sample with `QUEUE_DROP_BEFORE`;
- hardware skip frames advance the sequence by the reported loss count and mark the first following stored sample with `FIFO_DISCONTINUITY_BEFORE`;
- raw sensor-time anchors are aligned down to the BMI270's 200 Hz sample grid and per-sample ticks are back-filled at 128 native ticks modulo 2^24; every derived value carries `SENSOR_TIME_ESTIMATED`, inconsistent consecutive anchors mark a discontinuity, and a missing first anchor remains unavailable rather than inventing a zero-time host observation;
- the parser retains the sensor-time frame's byte position so its raw tick can be correlated to an interpolated point within the host-observed I2C transfer; older samples are projected backwards from that observation, while batches extrapolated from a prior anchor use a degraded midpoint observation;
- die temperature is observed independently at 10 Hz, held between observations, and marked stale after 250 ms or before the first successful observation;
- three consecutive drain failures trigger one bounded device recovery attempt; failed recovery is followed by a one-second scheduler-call backoff, successful recovery reconfigures and flushes the FIFO without resetting sequence, and the next stored sample is marked with recovery and discontinuity flags;
- session start suspends production, counts and clears the old queue, resets session sequence/diagnostics, flushes the hardware FIFO, and resumes sensing; session stop first suspends new production, performs a bounded final drain, and deliberately leaves the queue available for the Phase 4 row adapter; and
- all cumulative diagnostics use saturating 64-bit counters with an explicit saturation indicator, while sequence wrap remains intentional.

The provisional acquisition object is compile-time limited to 32 KiB. It is not yet instantiated by a registered sensor, so the current linked-image RAM report does not include that per-sensor allocation. Phase 4 must account for it when the adapter is registered, and field measurements must determine whether the 512-record queue is larger than necessary or provides useful logger-stall margin.

Automated test coverage added:

- signed combined-frame decoding and gyro-before-accelerometer payload order;
- multi-frame ordering;
- FIFO skip propagation;
- unpaired, partial, invalid, and bounded-output behaviour;
- 24-bit native-time back-fill, continuation, skip spacing, and wrap;
- full-capacity queue use, deterministic drop-newest behaviour, FIFO ordering, reuse after a pop, and boundary clearing.

Software validation:

- production builds passed for `thingplus_s3_usb_cdcserial`, `thingplus_s3_usb_uartserial`, `thingplus_s3_usb_cdcserial_uart_i2c1`, `thingplus_s3_usb_cdcserial_bodaqs_4f`, and `bodaqs_s3_mini_n4r2`;
- the 14 focused BDQ host parser tests continued to pass; and
- the new FIFO/parser/queue tests are wired into the native test target, but could not be executed in this environment because no host C++ compiler or Make implementation is installed.

Hardware acceptance remains open. A BMI270 fixture must confirm real FIFO byte ordering, sensor-time association, single-burst I2C reads under backlog, queue and FIFO headroom during forced scheduler stalls, continuous reconstruction across at least one native-clock wrap, final-drain behaviour, callback-duration bounds, recovery after injected bus faults, and coexistence with the logger's other I2C clients. Phase 3 is software-complete but not hardware-accepted until those measurements are recorded.

## 15. Phase 4 implementation record

Firmware implementation completed on 2026-08-06:

- `bmi270_imu_i2c` is registered as a usable sensor and exposed by both the HTML configuration route and configuration API;
- the adapter exposes stable identity, location, bus/address, the fixed `orientation_200` profile, body-axis mapping, startup observation duration, and host calibration-reference fields;
- logging startup rejects unknown sensor types, more than one active BMI270 (the explicit MVP boundary), duplicate configured sensor names, duplicate active IMU identities, duplicate active BMI270 bus/address pairs, unsupported addresses or profiles, unavailable or non-400 kHz buses, invalid or left-handed mounting transforms, failed BMI270 initialization, and any effective logger rate other than 500 Hz;
- a newly added or materially reconfigured BMI270 must be activated by restarting the logger; startup compares the live adapter with persisted configuration and refuses to record mismatched metadata;
- a pure mounting-map validator requires a signed permutation of the three native axes with determinant +1; raw logged axes remain sensor-native and the body mapping is metadata only;
- the adapter publishes the 12 canonical contract columns with explicit int16, uint16, uint32, and float32 BDQ storage, emits at most one queued native sample per logger row, and uses zero placeholders plus `NaN` sample age when `sample_valid=0`;
- the sample-age descriptor explicitly permits `NaN`, so the contract placeholder is preserved without setting the BDQ frame-level sensor-error flag on normal sparse rows;
- valid rows contain the low 24 bits of sensor time and sequence exactly once, with `sample_age_us` calculated from the projected native-sample observation in the host monotonic clock domain;
- session metadata records the contract and driver revisions, physical identity, requested and effective configuration codes, FIFO policy, native timebase, temperature semantics, mounting transform, calibration reference, sparse-row validity policy, and firmware provenance;
- both BDQ final summaries and CSV sidecars publish the currently available exact FIFO, parser, queue, I2C, recovery, pre-session-discard, final-drain, and emitted-sample counters; the additional statistical diagnostics and startup stationary observation remain Phase 5 work;
- logger shutdown now quiesces the sampler, stops the I2C scheduler, suspends the BMI270, performs the final hardware FIFO drain, drains the existing storage queue, emits one ordered tail row per remaining IMU record, and only then finalizes the log;
- a failed tail-row enqueue or non-progressing queue is logged, while the final queue depth remains visible in the summary and any residue is counted and cleared at the next session boundary; and
- the registered acquisition object is included in the linked RAM image. The Thing Plus CDC build uses approximately 140580 bytes of 327680 bytes (42.9 percent), leaving useful prototype headroom while retaining the provisional 512-record queue.

Automated coverage added:

- accepted identity and rotated right-handed mounting maps;
- duplicate-axis, left-handed, unsigned, and non-canonical mounting-map rejection;
- native-to-host time projection at the 200 Hz interval and across the 24-bit sensor-time wrap; and
- the existing signed FIFO, queue, and mixed-storage cases remain wired into the native target.

Software validation:

- the `thingplus_s3_usb_cdcserial` production environment builds and links successfully with the registered adapter;
- all 14 focused BDQ parser/storage tests pass;
- the repository-wide analysis suite currently reports 329 passed, 1 skipped, and 9 failures in unrelated import-manager, catalog-version, and preprocessing tests; and
- the C++ native tests remain unexecuted because this environment has no host C++ compiler or GNU Make.

Hardware acceptance remains open. Phase 4 requires a real logger/IMU run to verify sparse-row counts (`samples_enqueued == samples_emitted + queue_drops + documented final residue` as applicable), no duplicate sequence values, sensible acquisition age, accurate final draining, metadata contents, 500 Hz storage performance, I2C coexistence, and the practical RAM/queue margin. Phase 5 should not apply startup bias correction; it adds the accepted stationary observation and quality diagnostics while preserving raw samples.

## 16. First ride remediation record

Firmware changes completed on 2026-08-06 after inspection of the first recorded BMI270 session:

- corrected the FIFO over-read from three bytes to a complete four-byte sensor-time frame and removed transaction splitting, which had produced partial frames and prevented any sensor-time anchor from being parsed;
- added a deterministic transfer-time/read-length model so a single burst can empty the FIFO despite samples arriving while the read is in progress, without imposing a large fixed over-read on normal small batches;
- enlarged the ESP32 Wire buffer for the IMU bus at initialization and increased its transaction timeout to cover the bounded full-FIFO burst;
- corrected the distinction between the raw sensor-time observation and the 200 Hz sample grid, and correlated the observation with its actual position inside the I2C transfer;
- made a first unanchored batch produce unavailable sample age rather than a plausible-looking time derived from a zero sensor tick;
- lowered I2C scheduler tasks to the same FreeRTOS priority as Arduino `loopTask`, allowing storage service to receive CPU time on their shared core under sustained I2C load; and
- persisted drain/load, timing-frame, parser, queue, temperature, recovery, FIFO-bound, duration, transport-operation, failure-streak, last-failure, and per-I2C-stage counters in final diagnostics. The storage writer's buffering and write strategy were deliberately not changed.

Focused native tests now cover burst planning, sensor-time frame position, 200 Hz phase alignment, wrap and skip behavior, missing initial anchors, cross-batch discontinuities, and native-to-host interpolation. The RC3 PlatformIO environment builds successfully after these changes, using 140856 of 327680 bytes RAM (43.0 percent) and 1668585 of 2097152 bytes flash (79.6 percent). Native tests remain unexecuted on this Windows host because a host C++ compiler and Make are not installed.

The next hardware smoke test should treat `sensor_time_frames > 0`, `partial_frames == 0`, `missing_sensor_time_batches == 0` after startup, no unexplained sequence discontinuities, a bounded `maximum_fifo_bytes_observed`, and no queue drops as the primary gates. `overread_frames > 0` is expected and confirms that a burst reached the normal FIFO over-read marker. Storage throughput remains a separately deferred issue if drops persist after scheduler fairness and reduced I2C load are verified.

## 17. Shared-bus MVP coordination

Firmware changes completed on 2026-08-07 after the second smoke-test log demonstrated complete 200 Hz collection but periodic bus-lock timeouts and timing degradation:

- the BMI270 now reserves its I2C bus across the FIFO-length read, read-plan calculation, and FIFO-data burst, eliminating the window in which another device could make the observed length stale;
- native-to-host timing uses timestamps recorded around the actual FIFO_DATA wire operation after the bus lock is obtained, excluding time spent waiting for another device;
- the transport lock timeout is 50 ms as a safety margin for an already-started display transaction, while lock attempts, timeouts, total wait, and maximum wait are persisted separately from transfer and drain duration;
- the BMI270 reapplies the board-profile clock whenever it obtains the bus;
- the SSD1306 is constructed with the configured bus clock as both its transfer and restore clock, correcting the upstream library default that otherwise restored shared Wire operation to 100 kHz;
- while logging, full OLED refreshes are limited to 1 Hz and deferred until all participating FIFO clients have enough declared service-gap margin for a conservative 30 ms transfer plus a 5 ms guard; deferred content remains pending and is presented in the next admissible window; and
- the BMI270 declares a provisional 50 ms maximum low-priority service gap, limiting the intentional OLED-induced backlog to approximately ten 200 Hz frames. This is a latency policy, not a FIFO-capacity limit.

This slice deliberately does not introduce the full multi-IMU deadline scheduler. The roadmap records the future single-owner arbiter, per-client deadline/duration/backlog declarations, fairness, optional page-sized display transfers, per-bus admission budgets, and multi-clock synchronization work.

Hardware acceptance requires another shared-bus smoke test. Primary gates are zero bus-lock timeouts, zero partial frames and missing sensor-time batches during steady logging, sensor-time increments of 128 ticks except explicitly flagged boundary events, lower maximum drain duration and sample-age percentiles, continued zero queue/storage drops, and a responsive but no-more-than-1-Hz logging display. Nonzero lock wait is expected and should now be bounded and observable.

## 18. Silent state-loss recovery

Firmware changes completed on 2026-08-09 after ride logs showed one FIFO-length read failure followed by successful I2C polling of a permanently empty FIFO. A later ESP32 deep-sleep wake reran initialization and restored acquisition, supporting the conclusion that the BMI270 had remained responsive while losing volatile sensor or FIFO configuration:

- session start now validates chip identity, BMI270 internal configuration status, the effective accelerometer and gyroscope profile, sensor enable state, and the complete managed FIFO configuration while sensing is suspended;
- a failed session-start validation captures the observed state and invokes the existing full device/FIFO recovery before sensing is resumed;
- active acquisition now supervises parsed native-frame progress with a provisional 250 ms timeout rather than treating successful empty FIFO reads as proof of health;
- a stalled stream is validated after the current drain, so a scheduler delay that leaves real FIFO backlog does not cause a false recovery;
- validation snapshots persist the issue mask, API result, chip ID, internal status, power-control value, FIFO configuration, watermark, downsampling, and filter selections before recovery overwrites the evidence;
- full reinitialization continues to preserve the firmware sequence and marks the first later sample with recovery, discontinuity, and degraded-timing status;
- three recovery attempts without a genuinely parsed later frame are permitted; parsed progress restores that budget, while an exhausted budget or three failed recoveries terminally mutes only the IMU bus client so other logger channels can continue;
- recovery reason, attempts, successes, failures, no-progress duration/events, attempts without progress, terminal fault state, and session-start validation counts are added to BDQ and CSV-sidecar final diagnostics; and
- the stored 12-column IMU sample contract, profile, configuration keys, and raw-data authority are unchanged.

Persisted recovery-reason codes are `0=none`, `1=consecutive_drain_failures`, `2=session_start_validation`, and `3=no_sample_progress`. The validation issue mask assigns `0x001` to unexpected software state; `0x002/0x004` to chip-ID read/mismatch; `0x008/0x010` to internal-status read/mismatch; `0x020/0x040` to profile read/mismatch; `0x080/0x100` to power-control read/mismatch; `0x200/0x400` to FIFO read/mismatch; and `0x800` to no parsed-sample progress despite completed polling.

Pure native coverage was added for watchdog arming, timeout boundaries, progress reset, 32-bit microsecond wrap, bounded recovery attempts, and budget restoration after real sample progress. The native executable remains unrun on this Windows host because GNU Make and a host C++ compiler are unavailable.

The RC3 `bodaqs_s3_mini_n4r2` PlatformIO environment builds successfully, using 140928 of 327680 bytes RAM (43.0 percent) and 1673745 of 2097152 bytes flash (79.8 percent). Existing ArduinoJson deprecation warnings remain unrelated.

Hardware acceptance requires a normal ride/soak with no false recovery and a controlled BMI270 reset, supply interruption, or equivalent configuration-loss injection. The latter must produce a bounded gap, a successful recovery marker, resumed sequence/tick progression, and the expected validation/recovery diagnostics without rebooting the logger. A persistent fault must reach the terminal IMU state without disrupting other configured sensors.

## 19. Phase 4.5 semantic consolidation and GPS session isolation

Firmware and host-contract changes completed on 2026-08-10:

- BMI270 configuration now uses canonical `domain`, `end`, and optional `mount_point` fields, enforcing `unsprung/front|rear`, `frame/none|front|rear`, and `steering/front` combinations;
- the original `location` configuration key remains accepted as a compatibility alias, and the original IMU metadata field remains temporarily emitted alongside the canonical fields;
- raw accelerometer and gyroscope columns now publish explicit `component`, `vector_group`, and `coordinate_frame=sensor_native` metadata without changing the twelve stored fields or their values;
- the original Phase 4.5 mounting transform recorded `sensor_native -> body_local` using a signed-axis permutation; the later assisted-orientation slice replaces this in contract v2 with a full rotation matrix;
- CSV-sidecar and embedded BDQ metadata writers, BDQ ingestion, channel metadata, the signal registry, and semantic selectors preserve the new fields;
- GPS semantic resolution now keeps latitude, longitude, motion, and QC channels on one identified GPS sensor/source and refuses cross-source position pairs; and
- GPS session start invalidates the previous cached snapshot and discards queued UART input when restarting acquisition, so position remains unavailable until the new session receives a new PVT observation.

Verification completed with 62 passing targeted analysis tests covering logger sidecars, BDQ types/metadata, signal registry behavior, GPS grouping, and route construction. The RC3 `bodaqs_s3_mini_n4r2` firmware environment builds successfully at 147072 of 327680 bytes RAM (44.9 percent) and 1682113 of 2097152 bytes flash (80.2 percent). Existing ArduinoJson deprecation warnings remain unrelated.

Hardware acceptance should confirm that an existing `location=frame` configuration migrates without intervention, canonical domain/end metadata appears in both CSV-sidecar and BDQ logs, and the first finite GPS point of every session is a newly received observation rather than the prior session endpoint.

## 20. Phase 5 calibration-observation and quality-diagnostics record

Firmware implementation completed on 2026-08-10:

- the configured startup window now accumulates fixed-memory running statistics for raw gyro bias, gyro stability, acceleration magnitude, and fresh BMI270 temperature observations;
- the observation is accepted or rejected against the contract thresholds, with an additive rejection mask and a display-oriented primary reason, and never alters the raw accelerometer or gyro samples;
- FIFO, queue, recovery, and degraded-timing incidents during the window invalidate the observation, while a zero-second window is explicitly reported as disabled;
- accelerometer and gyro near-rail events are flagged on the affected stored sample and counted independently for all six axes;
- cumulative diagnostics now include degraded-timing sample count, discontinuities between emitted sequence values, native-clock-anchor discontinuity events, session temperature range, and fixed-memory acquisition-age median, p95, p99, exact range, unavailable count, and histogram-clipping count;
- the CSV sidecar and embedded BDQ final summaries publish the same versioned startup observation and session-quality evidence; and
- parser tests now distinguish a native-clock-anchor discontinuity from other FIFO discontinuities, and native tests cover accepted, moving, quality-invalidated, and disabled startup windows plus deterministic acquisition-age statistics.

The selected Bosch API contains component self-test entry points, but those operations reconfigure the BMI270 and need an explicit maintenance-mode lifecycle, restoration verification, and user-facing result contract. They are therefore retained in Milestone 2 rather than being run automatically at session startup.

The RC3 `bodaqs_s3_mini_n4r2` production build compiles and links successfully at 147076 of 327680 bytes RAM (44.9 percent) and 1689537 of 2097152 bytes flash (80.6 percent). The focused native test source compiles with the ESP32-S3 C++ toolchain; executing the host-native test target still requires a host C++ compiler and Make implementation. Hardware acceptance requires stationary and deliberately moving starts, a controlled near-rail stimulus where practical, and confirmation that the final sidecar and BDQ summaries agree. The separate state-loss/disconnect recovery exercise is tracked in Azure DevOps User Story 74.

## 21. Phase 6 host extraction and QC record

Host implementation completed on 2026-08-10:

- logger CSV and BDQ session loading now preserves the versioned `imu_configs` metadata and automatically builds one `imu_<sensor>` secondary stream for each complete IMU semantic group;
- extraction filters `sample_valid=1` rows without synthesizing replacements for loss; the later sparse-row correction masks invalid placeholders in the processed primary table while preserving `df_raw` and the source BDQ;
- 24-bit firmware sequence and BMI270 sensor time are unwrapped independently, with gaps, duplicates, reversals, wrap, and tick/sequence inconsistency reported explicitly;
- the spectrum-ready `time_s` retains missing native slots, while logger emission time, acquisition-age-corrected host time, raw native tick time, and their provenance remain separate columns;
- effective range metadata drives raw-to-SI conversion, and a valid mounting rotation produces reversible `body_local` derived channels while retaining all sensor-native raw and SI columns;
- deterministic `bodaqs.imu_qc.v1` reports cover native rate and coverage, loss and status flags, acquisition-age distribution, clock drift/residual, per-axis near-rail event locations, temperature, startup stationary evidence, selected firmware counters, duration, and file-size rate;
- QC is retained in persisted session metadata and secondary stream metadata links to it, so imported rides can be compared without reopening the source BDQ; and
- missing metadata either raises a clear error in strict extraction or produces an explicitly degraded raw stream in automatic import mode.

The public host API is `extract_imu_stream`, `build_imu_streams`, and `imu_qc_report`. Detailed column and QC semantics are documented in [BMI270 IMU Extraction and QC](../analysis/BMI270_IMU_Extraction_and_QC.md).

Automated synthetic coverage includes signed decoding inherited from the BDQ reader, native-clock and sequence wrap, a missing sample, scaling, a right-handed non-identity mounting transform, clock fit, status localization, near-rail localization, persisted QC, idempotent stream construction, and strict/degraded missing-metadata behavior. The implementation was also exercised against `260809_093639_db1cfd00ff6b.bdq`, producing 30719 valid IMU samples at a measured 200 Hz and correctly identifying its known 112-sample discontinuity.

Targeted analysis verification reports 69 passing tests. The complete analysis suite reports 344 passed and 1 skipped; its nine failures are the same pre-existing macOS-on-Windows, catalog-version, and legacy preprocessing-interface expectations recorded before Phase 6. Phase 6 deliberately stops before resampling, interpolation, orientation fusion, bias application, or gravity removal.

### Phase 6 timing and sparse-row correction (2026-08-15)

Ride validation showed that the BMI270 native clock ran consistently faster than the logger clock and that general-purpose consumers could plot the documented invalid zero placeholders in sparse 500 Hz logger rows as measurements. Host extraction now robustly fits each continuous IMU clock epoch to acquisition-age-corrected logger observations. Canonical dense-stream `time_s` is expressed on the logger monotonic clock, while nominal BMI270 `native_time_s`, raw observations, fitted clock scale, logger-relative ODR, and per-epoch QC remain available. Sequence loss still produces an explicit gap and is never interpolated.

The processed primary dataframe now masks sample-dependent IMU fields wherever `sample_valid` is not one. The literal placeholder representation remains unchanged in `df_raw` and in the source BDQ. This prevents charts and generic preprocessing from interpreting absence as physical zero without weakening the raw evidence contract.

## 22. Assisted installation orientation record

Firmware and host implementation completed on 2026-08-15:

- the calibration menu identifies BMI270 orientation as a distinct sensor capability rather than forcing it through scalar zero/range calibration;
- the user selects the sensor-native plane parallel to the bicycle centre plane and which signed normal points toward bicycle positive Y (left);
- capture services the selected BMI270 FIFO outside a logging session and collects 800 native samples while the OLED remains free of competing redraws;
- stationarity, acceleration magnitude, gyro stability, clipping/acquisition quality, and sample-count checks reuse the established startup-observation limits;
- capture rejects more than 2 degrees of observed roll, while accepted small roll error is removed by projecting gravity into the declared plane before solving the right-handed orientation;
- the accepted result and observation evidence are persisted atomically in logger configuration, with the compact stored quaternion reconstructed as a validated rotation matrix;
- contract `bodaqs.bmi270_imu_mvp.v2` emits `orientation_status`, a `sensor_native -> body_local` rotation matrix, and the method, declared geometry, timestamp, sample count, stationary statistics, and roll residual in both embedded BDQ and CSV-sidecar metadata;
- new firmware no longer exposes or emits `mount_x`, `mount_y`, or `mount_z`; legacy keys are removed on the next configuration save; and
- host extraction validates the matrix and produces `body_local` acceleration and angular-velocity channels without changing sensor-native raw or SI channels.

An IMU with no accepted installation orientation remains usable for raw collection and reports `orientation_status=unset`. Hardware acceptance must exercise all three plane choices and both normal signs, confirm rejection beyond 2 degrees of roll and under deliberate movement, verify retry/cancel preserves the previous result, and compare emitted metadata with a known physical pose.
