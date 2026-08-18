# BMI270 IMU Firmware Roadmap

- Status: Accepted
- Scope: BODAQS firmware, log format, and the minimum host support needed to validate logged IMU data
- Initial hardware: One Bosch BMI270 connected over I2C
- Companion documents:
  - [BMI270 IMU MVP Implementation Plan](BMI270_IMU_MVP_Implementation_Plan.md)
  - [BMI270 IMU MVP Data Contract](BMI270_IMU_MVP_Data_Contract.md)
  - [BMI270 IMU Extraction and QC](../analysis/BMI270_IMU_Extraction_and_QC.md)

## 1. Outcome

BODAQS should be able to record one frame-mounted BMI270 well enough to:

- characterise the bicycle's translational and rotational motion;
- determine whether the logger, mounting, timing, and selected sensor ranges work in real rides;
- preserve the raw evidence needed to develop an offline orientation pipeline; and
- provide a sound base for later multi-IMU vibration and kinematics work.

The first release should be a measurement feature, not an on-device orientation product. Firmware should record timestamp-faithful raw IMU samples, configuration, calibration observations, and health diagnostics. Orientation estimation remains offline until the logged data has established what filtering and calibration are justified.

## 2. Practicality and return on effort

Adding one BMI270 is practical on the current ESP32-S3 architecture if it uses the sensor FIFO and the asynchronous I2C scheduler. The valuable early work is reliable acquisition and timing, not a sophisticated fusion algorithm.

The following constraints materially affect the design:

- A six-axis IMU can estimate roll and pitch relative to gravity only when non-gravitational acceleration is acceptably small or is handled by the estimator.
- A six-axis IMU cannot provide absolute yaw. GPS course can help only while the bicycle is moving with sufficient speed and useful course accuracy; it is not the same quantity as bicycle heading during slip or low-speed manoeuvres.
- Raw accelerometer data on a bicycle contains gravity, rigid-body motion, road input, vibration, mounting resonance, and sensor error. These cannot be cleanly separated in firmware by a single universal filter.
- BMI270 FIFO timing is more useful than assigning the time of an I2C read to every sample in that read.
- Two BMI270 I2C addresses are available. More than two units on one bus requires bus switching or another transport.
- Long I2C runs to fork or wheel-mounted sensors are likely to be fragile and may be unsuitable for the later multi-IMU system.
- BMI270 internal NVM has limited write endurance. BODAQS should store calibration in its own configuration and should not write sensor NVM during normal use.

These points favour a staged programme: prove one unit, preserve timing and diagnostics, then decide which calibration and multi-sensor investments have demonstrated value.

## 3. Governing design decisions

### 3.1 Coordinate conventions

Use a right-handed bicycle body frame:

- positive X: forward;
- positive Y: left;
- positive Z: up.

Use ENU for any later world-frame output. The physical installation is described by a right-handed rotation matrix from the BMI270 package axes into a local frame fixed to the mounted mechanical assembly (`body_local`). The matrix is produced by the assisted gravity-plus-declared-plane workflow. For a frame-mounted sensor this coincides with the bicycle body frame. Steering and unsprung sensors require additional, potentially time-varying articulation information before their values can be expressed in the main bicycle body frame.

The MVP records sensor-native samples and the mounting transform. It does not destructively rotate or bias-correct the stored raw values. Post-processing applies the transform and calibration, preserving the original evidence.

Signal `domain` identifies the physical or analysis subject and is independent of coordinate basis. IMU mounting domains use `unsprung`, `frame`, and `steering`, with `end` providing the front/rear qualifier. `coordinate_frame` describes only the basis in which vector components are currently expressed: firmware raw vectors are `sensor_native`; `body_local`, `bike_body`, and `world_enu` are derived representations produced by post-processing.

### 3.2 Initial measurement profile

The initial profile is:

- accelerometer output data rate: 200 Hz;
- gyroscope output data rate: 200 Hz;
- accelerometer range: plus or minus 16 g;
- gyroscope range: plus or minus 2000 degrees per second;
- FIFO enabled with accelerometer, gyroscope, and sensor-time information;
- I2C at 400 kHz on the least-contended available bus;
- BMI270 interrupt line not required for the first rideable prototype.

This is a robust first profile rather than a final optimum. It reduces clipping risk and is adequate for orientation development. The rides must measure saturation, noise, timing, and useful bandwidth before narrower ranges or a higher output data rate are selected.

### 3.3 Logging semantics

The existing BODAQS logger has a single row timebase. The MVP will keep that architecture and use the following adapter:

1. The I2C scheduler drains complete BMI270 FIFO frames into a bounded in-memory queue.
2. A 500 Hz logger consumes at most one queued IMU sample per row.
3. Each native 200 Hz IMU sample is emitted exactly once.
4. Rows with no IMU sample are explicitly invalid; values are not held and presented as new samples.
5. Sequence, BMI270 sensor time, acquisition age, and status fields make gaps and timing uncertainty observable.

The 500 Hz logger rate is deliberate. A 200 Hz consumer is not safely faster than a nominally 200 Hz sensor with an independent clock. This sparse-row adapter is acceptable for one-IMU validation but is not the desired long-term multi-stream storage model.

### 3.4 Raw and derived data

The authoritative logged quantities are raw signed counts plus the information required to convert them:

- raw accelerometer X, Y, and Z;
- raw gyroscope X, Y, and Z;
- raw die temperature or a documented temperature sample associated with the drain;
- native sensor-time tick;
- firmware sequence modulo 2^24, for exact transport through the current float row buffer;
- valid/status flags;
- acquisition age or equivalent host-to-sensor timing observation.

Range, output data rate, filter settings, scale factors, mounting transform, device identity, driver version, and calibration references belong in session metadata.

Scaled SI channels, Euler angles, quaternions, earth-frame acceleration, and fused GPS/IMU outputs are derived products and are not part of the MVP firmware data contract.

### 3.5 Calibration authority

Firmware exposes and records calibration inputs but does not make permanently corrected raw data the only available data.

The calibration progression is:

1. MVP: device identity and health, mounting transform, stationary start observation, raw temperature, and an explicit calibration reference.
2. Next: guided six-position accelerometer calibration and repeatable gyroscope zero checks.
3. Later if justified: imported temperature-dependent bias models and optional Bosch component re-trimming.
4. Research only until validated: gyro internal offset compensation and any automatic in-ride bias application.

The stationary start observation estimates gyro mean and variance only when stationarity tests pass. It is recorded for post-processing and quality control; it does not alter the raw log.

## 4. Scope by milestone

### Milestone 0 — Data and configuration contract (complete)

Purpose: remove ambiguity before driver work.

Deliverables:

- BMI270 sensor type and stable sensor instance identity;
- coordinate and mounting metadata contract;
- explicit signed and unsigned BDQ storage types;
- one-sample-once sparse row semantics;
- validity, sequence, sensor-time, and diagnostic flag definitions;
- named initial hardware profile;
- calibration record version and provenance fields.

Exit condition: a synthetic IMU session can be represented and decoded without losing signed counts, native timing, invalid-row semantics, or configuration provenance.

### Milestone 1 — Single-IMU rideable prototype

Purpose: collect trustworthy 200 Hz data on a bicycle.

Deliverables:

- pinned Bosch BMI270 driver integration;
- I2C transport, configuration read-back, FIFO draining, and bounded queue;
- BODAQS registry/configuration integration;
- Phase 4.5 domain/end and coordinate-frame semantic consolidation;
- raw BDQ channels and session metadata;
- startup stationary-bias observation and runtime diagnostics;
- host decoder changes and an IMU quality-control summary;
- bench, soak, fault-injection, and real-ride validation.

Firmware deliverables through Phase 5 and the Phase 6 host extraction/QC slice are implemented. Milestone 1 remains open for the documented hardware acceptance work, including the deferred state-loss/disconnect exercise.

Not included:

- on-device orientation;
- accelerometer multi-position calibration workflow;
- automatic bias application;
- 400 Hz operation;
- multiple IMUs;
- interrupt-driven acquisition;
- a new asynchronous BDQ stream format.

The companion MVP plan defines the implementation and acceptance gates.

### Milestone 2 — Calibration and data quality

Purpose: make comparisons between units and sessions defensible.

Candidate deliverables:

- guided six-position accelerometer offset and scale calibration;
- explicit calibration records with unit serial, date, method, firmware, temperature, residuals, and validity;
- repeatable gyro zero capture and comparison reports;
- optional import of laboratory temperature-dependent gyro bias models;
- manual self-test and component re-trimming service actions with clear preconditions;
- calibration selection in configuration and complete provenance in the log.

Decision gate: implement only the calibration terms shown by MVP data to materially improve the target analyses. A full cross-axis sensitivity matrix is deferred unless fixture testing shows sufficient benefit.

### Milestone 3 — Offline single-IMU orientation

Purpose: establish useful bicycle-frame and world-frame derived signals.

Candidate deliverables:

- raw-to-SI conversion and mounting transform;
- sensor-time reconstruction and gap handling;
- stationary detection and bias-estimator experiments;
- offline six-axis orientation filters with quality/confidence outputs;
- GPS course and accuracy channels where useful for conditional yaw constraints;
- reproducible estimator configuration and versioned derived-data products.

Firmware impact should be limited to any metadata or timing evidence found missing during MVP analysis.

### Milestone 4 — Higher bandwidth and tighter timing

Purpose: support measurements whose useful bandwidth exceeds the MVP profile.

Candidate deliverables:

- microsecond or rational global cadence instead of integer milliseconds;
- evaluated 400 Hz BMI270 profile;
- measured digital-filter bandwidth and group delay;
- interrupt-assisted FIFO service if polling jitter is limiting;
- higher-g accelerometer decision for unsprung locations;
- timing anchor quality and drift characterization.

Decision gate: proceed only if ride spectra show useful energy or clipping beyond the MVP capability.

### Milestone 5 — Multiple IMUs

Purpose: analyse transmission from unsprung to sprung bicycle structures.

Required architectural work:

- native per-stream sample storage rather than sparse columns in a global row;
- clock offset and drift estimation between IMUs;
- per-unit mounting, calibration, identity, domain/end, optional mount point, and health metadata;
- phase-preserving gap and resampling rules;
- a physical transport suitable for cable length and environment;
- storage, CPU, queue, and power budgets for the chosen channel count and rate.

Likely hardware questions:

- whether two local I2C units are enough for the first study;
- whether remote units should use SPI, a bus extender, differential transport, or a small satellite logger;
- how synchronization events or common time observations reach each unit.

The current 64-column row capacity and two-address I2C topology must not be treated as the long-term multi-IMU architecture.

### Milestone 6 — Optional on-device derived output

Purpose: provide immediate rider feedback only if a demonstrated use case warrants it.

Possible outputs include a low-rate orientation preview or health indication. Raw acquisition remains independent and authoritative. This milestone is optional because on-device fusion adds tuning, validation, and failure-mode cost without improving the evidence collected for initial algorithm work.

## 5. Calibration methods to expose

### Required in MVP

- Installation orientation: the user declares the sensor plane parallel to the bicycle centre plane and which signed normal points left; a stationary level capture projects gravity into that plane and records the resulting rotation matrix plus quality evidence.
- Startup stillness observation: configurable duration; validity based on gyro variance and accelerometer magnitude stability; mean, variance, temperature, sample count, and rejection reason recorded.
- Calibration reference: optional identifier linking the session to an external versioned calibration record.
- Raw retention: no calibration setting can suppress the uncorrected raw samples.

### Recommended next

- Six-position accelerometer calibration: guided plus/minus gravity poses on each sensor axis, solving offsets and per-axis scale with residual checks.
- Gyro zero capture: a deliberate stationary service action, separate from automatic session observation, with repeatability and temperature recorded.
- Temperature model import: host-generated coefficients imported as a versioned record after enough chamber or field evidence exists.

### Conditional or deferred

- Bosch component re-trimming: expose as a deliberate maintenance operation only after integration testing confirms its benefit and operational requirements.
- Gyro internal offset compensation: keep off by default because it hides raw behaviour and may complicate provenance.
- Sensor NVM programming: exclude from normal BODAQS operation.
- Full misalignment and cross-axis calibration: defer until suitable fixtures and repeatability justify the effort.

## 6. Configuration surface

Use a named profile to keep the common configuration short. Proposed logical fields are:

    sensorN.type=bmi270_imu_i2c
    sensorN.name=frame_imu
    sensorN.imu_id=frame_imu_001
    sensorN.domain=frame
    sensorN.end=rear
    sensorN.mount_point=
    sensorN.i2c_bus=1
    sensorN.i2c_addr=104
    sensorN.profile=orientation_200
    sensorN.startup_bias_capture_s=5
    sensorN.calibration_ref=

The profile expands to the actual ODR, ranges, FIFO configuration, and filter settings. Firmware records both the requested profile and register read-back/effective configuration. Advanced overrides should be added only when a real measurement need appears.

Invalid sensor types, invalid axis transforms, duplicate axes, unsupported buses, and unavailable addresses must fail configuration visibly. Unknown sensor types must not silently become another sensor class.

## 7. Diagnostics and observability

At minimum, each session should report:

- detected chip identity and initialization result;
- requested and effective sensor configuration;
- FIFO frames received;
- sensor-time frames or anchors received;
- FIFO skip/overflow events;
- queue high-water mark and software queue drops;
- duplicate or out-of-order observations;
- I2C transaction failures and recovery attempts;
- sequence gaps visible in the stored log;
- minimum, median, high-percentile, and maximum acquisition age;
- accelerometer and gyroscope saturation counts by axis;
- temperature range;
- startup stillness result and bias statistics;
- SD/logging queue drops and logger overruns.

There must be no silent data loss. If exact loss cannot be counted, a discontinuity or degraded-timing flag must be stored.

## 8. Post-processing dependencies to preserve

Detailed estimator design is deferred, but firmware and file-format choices must enable:

- extraction of a dense native-rate IMU stream from valid rows;
- unwrap of the 24-bit BMI270 sensor clock;
- host-time alignment with stated uncertainty;
- raw-to-SI conversion from recorded effective ranges;
- application of mounting and calibration records;
- detection of gaps, repeated data, saturation, and FIFO faults;
- use of temperature as a bias-model input;
- comparison to GPS using receiver time and GPS accuracy where available;
- later promotion of IMUs to independent session streams without changing their semantic identity.

The later GPS work should expose receiver time, speed accuracy, and course accuracy. This is useful for alignment and conditional yaw constraints, but is not required to prove raw IMU collection.

### 8.1 Shared-I2C scheduling direction

The single-IMU MVP uses the FIFO to tolerate deliberate, bounded bus gaps. FIFO length and FIFO data are acquired under one bus reservation, and long low-priority OLED transfers are admitted only shortly after participating FIFO clients have been serviced. While logging, full OLED refresh is capped at 1 Hz. Every shared-bus library must preserve the configured bus clock; in particular, the SSD1306 integration must not restore a 400 kHz sensor bus to its 100 kHz library default.

This is an MVP coordination policy, not the final multi-device scheduler. Before deploying several IMUs on one bus, extend the per-bus scheduler toward a single-owner, deadline-aware arbiter in which clients declare:

- maximum service interval or FIFO deadline;
- expected and worst-case non-preemptible transaction duration;
- priority and whether work is deferrable;
- FIFO capacity, current or conservatively estimated backlog, and recovery state; and
- any maximum latency required for host-clock observations.

The arbiter should admit long transfers only when every deadline retains margin, drain FIFO clients before and after an admitted gap where useful, and provide fairness when a recovering device has a large backlog. Evaluate page-sized OLED transfers if full-frame reservations remain material. Measure lock wait separately from wire-transfer time, retain actual transfer timestamps, and calculate per-bus nominal and worst-case utilization for each supported sensor set.

FIFO buffering removes the need to read every IMU at every sample instant, but it does not synchronize different IMU clocks. Multi-IMU post-processing still requires per-device native time, host-clock anchors, drift estimation, phase-preserving gap handling, and possibly a physical synchronization mechanism if measured clock alignment is insufficient. Interrupt or watermark-assisted service remains a later option if polling and conservative backlog estimates limit timing quality.

## 9. Risks and mitigations

| Risk | Consequence | Mitigation |
|---|---|---|
| I2C or logger stalls | FIFO overflow or unreported gaps | FIFO, bounded queue, counters, sequence/tick discontinuity detection, soak and forced-overflow tests |
| Long low-priority I2C transfer | Deadline miss, stale FIFO length, or poor host-time anchor | Atomic FIFO reservation, admission window, logging-time display throttle, lock-wait and transfer timing diagnostics |
| Shared library changes bus clock | Read duration and FIFO planning differ from metadata | Restore and verify the board-profile clock at device transaction boundaries |
| Row timestamp mistaken for sample time | Phase and fusion errors | Store native tick and acquisition age; document sparse-row timing |
| 16 g or 2000 dps clipping | Lost peak information | Count saturation and inspect event clusters before changing hardware/profile |
| Mount flex or poor alignment | Misleading rigid-body motion | Rigid keyed mount, recorded axis map, installation check |
| Automatic bias correction during motion | Real motion removed or bias corrupted | Record observations only in MVP; apply offline |
| Sensor configuration drift or init error | Incomparable sessions | Read back effective configuration and fail visibly |
| Responsive sensor silently loses volatile configuration | FIFO remains empty for the rest of a ride | Validate state at session start, supervise native-sample progress, capture health evidence, and perform bounded full recovery |
| Long I2C wiring in future | Intermittent remote sensors | Treat transport as a milestone-5 hardware decision |
| Sparse global-row representation scaled to many IMUs | Wasted space and timing ambiguity | Use only for MVP; plan native asynchronous streams before multi-IMU |
| Unknown sensor type fallback | Wrong driver instantiated silently | Reject unknown types as part of the foundation work |

## 10. Programme acceptance

The roadmap remains on track when the MVP demonstrates:

- repeatable signs and axes in known orientations and rotations;
- reconstruction of a continuous 200 Hz native stream;
- no unreported sample loss during bench soaks and representative rides;
- observable and bounded timing uncertainty;
- no material regression to existing sensors, UI responsiveness, or SD logging;
- enough range for normal rides, with any clipping localized and quantified;
- usable stationary gyro and temperature evidence for initial bias studies;
- complete configuration, mounting, identity, and calibration provenance;
- a small set of real rides from which the post-processing pipeline can be designed.

If these conditions are not met, effort should stay on acquisition, timing, mounting, and observability rather than advancing to orientation algorithms.

## 11. Open decisions

The following should be resolved during MVP implementation or validation:

1. Exact BMI270 filter/performance-mode settings for the orientation_200 profile.
2. FIFO watermark and polling cadence after measured bus load and acquisition-age tests.
3. Whether die temperature is captured per drain or at a lower independent cadence.
4. Provisional acceptable loss, timing-age, and saturation thresholds for field trials.
5. Whether the existing BDQ v1 schema receives additive signed types or the change is named as a compatible schema revision.
6. Whether the BMI270 interrupt pin is available on the intended logger-to-sensor connector.
7. The rigid mounting design and how sensor identity and axis orientation are made difficult to misconfigure.
