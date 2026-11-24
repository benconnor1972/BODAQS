# Logger production integration: interview decisions

Status: interview complete; shared understanding explicitly confirmed by the user
on 2026-11-23, including the amended Q24 decision to retain current12-bit ADC
counts. This decision record is not an implementation specification or release
qualification. Source review: [production-readiness review](Logger_Production_Readiness_Review_2026-11-23.md).

Additional scope requested on 2026-11-24: unify acquisition scheduling and shorten
node configuration reconciliation. Supplemental Q25-Q32 and the combined
addendum were explicitly confirmed by the user on 2026-11-24. Earlier confirmed
decisions remain in force. See the addendum below.

## Agreed in round1

- Q1: first deliver an integrated A8 firmware candidate. General admission-policy
  development and hardware qualification remain explicit release gates. This is
  not a rewrite across every board/sensor, or a claim every selectable load works.
- Q2: START requires requested participants ready and admitted by default. An
  explicitly selected best-effort mode may exclude unavailable sensors, showing
  and recording exclusions. Missing participants at START are distinct from
  occasional visible sample loss during acquisition.
- Q3: web configuration/diagnostics operate before and after recording. Wi-Fi
  remains off during acquisition; live web access is deferred. Physical controls
  must remain responsive through preparation, acquisition and finalization.
- Q5: remove obsolete experimental runtime machinery from the release path,
  including serial boot gates, automatic benchmarks and unnecessary diagnostic
  allocations. Preserve operational health/loss evidence, correctness checks,
  useful host tests/exporters, diagnostic builds and sealed evidence. Retire
  alternatives once replacement behavior is established; defer cosmetic refactors.

## Q4 compatibility and retirement scope: resolved through Q6-Q9

The user requested a factual inventory before choosing what to preserve. The
specific decisions in Q6-Q9 below supersede blanket compatibility preservation.
Inspect the current r123 source rather than infer active features from enum names.

- Formats present: BODAQS CSV; compact binary/BDQ v1; multistream binary/BDQ v2.
  The optimized ADC producer uses v2's existing primary stream. V2 native streams
  are separate and are not replaced by that producer. SynBikeRaw is already retired.
- Normal configured sensor output modes are RAW and LINEAR. SensorManager.cpp
  maps legacy POLY/LUT settings to LINEAR and forces identity transform selection;
  registry/loader/UI remnants are not evidence of active configured transforms.
  Calibration/units conversion and optional extra raw columns are separate choices.
- The current raw diagnostic handles only AnalogPot RAW on fixed ordered external
  ADC layouts. Other sensor types, assignments, channel/rate shapes and generic
  row construction need individual compatibility decisions, not automatic deletion.
- CAN IMU native recording already coexists with the optimized raw ADC stream;
  preserving it is part of the feature objective, not preserving generic row overhead.

CRC, source identity, explicit losses/uncertain tails and STOP integrity remain
previously accepted requirements. More detailed lifecycle, UI behavior, admission,
file/import compatibility and release acceptance decisions remain for later rounds.

## Q4 factual inventory (r123)

Checked against `adc-raw-2x650-r123-source/firmware/src`; presence in source is
not qualification on current hardware. Canonical production also already retires
normal configured POLY/LUT selection.

### Formats

| Format/path | Relation to the optimized ADC producer |
|---|---|
| BODAQS CSV (`BodaqsStandard`) | Generic primary-row text writer; outside it. |
| Compact binary / BDQ v1 | Generic single-row binary writer; outside it. |
| Multistream binary / BDQ v2 generic primary rows | Same file format, but generic sensor sampling/float-row construction rather than the typed ADC producer. |
| BDQ v2 native streams | Separate acquisition/recording paths. Current CAN IMUs already coexist with the raw ADC primary stream. |
| SynBikeRaw | Already retired enum value; not an active format to preserve. |

Sources: ConfigManager.h:16, ConfigManager.cpp:623-669, StorageManager.cpp,
BdqV2PrimaryStream.cpp. The raw diagnostic is restricted to BDQ v2, local
AnalogPot RAW columns and specific ordered channel/rate layouts; it is not a
general replacement for every sensor returning raw data.

### Active sensor paths outside that producer

| Sensor | Transport / processing to consider separately |
|---|---|
| AnalogPot outside the admitted external-ADC layout | Other AIN/channel/rate layouts or direct/internal GPIO ADC; RAW or calibrated linear displacement, polarity, optional extra raw column. |
| AS5600 analog string pot | AIN/direct GPIO ADC; wrap tracking, unwrapped position, calibrated displacement and polarity. Its RAW output still includes linear displacement alongside wrapped counts; optional unwrapped raw column. |
| AS5600 I2C string pot | Asynchronous I2C acquisition; string-pot unwrap/displacement processing and quality fields. |
| AS5600 I2C angle | Asynchronous I2C; raw counts or zero-relative signed degrees, optional raw/quality fields, and a dedicated v2 native acquisition/timing stream. |
| AS5048B I2C angle | Asynchronous I2C; raw counts or zero-relative signed degrees and optional raw/quality fields. |
| BMI270 I2C FIFO IMU | Native signed accel/gyro/temperature counts, timing/validity, rate selection/decimation and v2 native stream. Hardware gyro offset compensation is distinct from output transforms; saved orientation is metadata, not streamed-axis rotation. |
| DAN-F10N UART GPS | UBX acquisition; receiver fixed-point values converted to coordinates, altitude, speed/course and optional fix/accuracy/age/freshness/time fields. |
| LSM6DSO32X CAN IMU | Master/remote native recording, raw axes and source/CAN timing evidence plus scale/configuration/orientation metadata. Already used alongside the current ADC path; not a generic primary-row fallback. |

Key sources: SensorTypes.h:8; AnalogPotSensor.cpp:159,190,493;
AS5600StringPotSensorBase.cpp:99,137,285; AS5600StringPotAnalog.cpp:79;
AS5600StringPotI2C.h:30; AS5600AngleSensor.cpp:1298,1394,1495;
AS5048BAngleSensor.cpp:739,896; BMI270ImuSensor.cpp:486,532;
BMI270Device.cpp:376; DANF10NGpsSensor.cpp:348,520,632;
Lsm6dso32xConfig.cpp:4; RemoteImuStream.cpp:428,530.

### Active conversions versus retired transformation infrastructure

Active choices include zero/span calibration, counts-to-displacement/angle,
polarity, optional raw alongside engineering values, string-pot wrap tracking,
GPS unit conversion, and sensor-specific hardware correction/rate handling.
These are not all equivalent to removable polynomial math. Live previews and
calibration controls are also distinct from what is written during recording.

POLY/LUT enum/branch and registry/file-loader infrastructure remains, but
SensorManager.cpp:425-449 forces identity and maps those legacy modes to LINEAR
for normal configuration. TransformRegistry.cpp:77 still loads polynomial JSON,
legacy polynomial text/config and lookup-table CSV. Sample-time smoothing in
AnalogPotSensor.cpp:193 is explicitly retired. Those remnants should be audited
for remaining callers and migration obligations rather than treated as active
features requiring blanket preservation.

Q4 was resolved through the separate Q6-Q9 decisions below. Keeping a sensor
feature need not mean keeping every old algorithm.

## Agreed in round2; interview paused

- Q6: new recordings use BDQ v2 only. Retire CSV and BDQ v1 writers from the
  production release path; preserve reading old files and provide CSV export
  through analysis/import tooling. Old logger configurations receive a clear
  migration notice rather than silent reinterpretation.
- Q7: ADC recordings contain counts, timing, status and enough calibration and
  configuration metadata for offline engineering-unit reconstruction. On-device
  linear/polynomial/LUT conversion is not required in acquisition/recording.
  Acquisition-essential processing, including sufficient information for reliable
  string-pot wrap reconstruction, still needs a specific design decision.
- Q8: preserve existing sensor families in A8 integration scope: analog pots,
  analog/I2C string pots, I2C angle sensors, local BMI270, UART GPS and CAN IMUs.
  Adapt representations as needed; do not preserve every historical algorithm.
  Driver presence does not qualify every mixed load; reject unsupported
  combinations before START.
- Q9: retain useful engineering-unit previews and calibration controls outside
  recording. Persist calibration for offline conversion without adding those
  conversions to urgent acquisition. Retire obsolete polynomial/LUT selection
  machinery where neither previews nor analysis handoff needs it.

No implementation is authorized solely by this interview. Resume later with
representation/metadata migration, lifecycle/failure behavior, admission and
release acceptance details; the design tree is not yet complete.

## Agreed in round3 (Q10-Q13)

- Q10: each file embeds the calibration/configuration snapshot needed for later
  engineering reconstruction: values, units, source identities and versions
  actually used. Do not depend on subsequently changed SD files; preserve unknowns.
- Q11: block sensor assignment, rate and calibration mutation from preparation
  through finalization. Allow read-only status, STOP and safe navigation. No
  pending-configuration staging system in the first release.
- Q12: STOP is a request until producers retire, storage finalizes and ownership
  is released. Show the phase; refuse new START/restart while busy; repeated STOP
  is harmless and controls remain responsive.
- Q13: import exposes raw data, explicit gaps and uncertainty. It must not invent
  engineering values or timestamps when required metadata/proof is absent.
  Recoverable reconstruction belongs offline; firmware retains CRC, identity
  and honest loss evidence.

## Agreed in round4 (Q14-Q17)

- Q14: healthy sources continue after a participant fails, with its failure and
  missing interval explicit. Shared timing/identity/storage integrity faults
  instead trigger controlled STOP.
- Q15: storage failure or unresponsive I/O stops acquisition and attempts bounded,
  visible safe cleanup. Report finalization success/uncertainty; do not free or
  reuse resources still owned by outstanding I/O or retry invisibly forever.
- Q16: preserve admitted sensor rates and explicitly report losses during
  overload. No silent rate reduction or participant removal to hide overload.
  Any later overload-response thresholds require separate documented policy.
- Q17: missing engineering calibration does not prohibit raw recording when
  acquisition configuration and source identity are known. Mark calibration
  unavailable and disable unsupported derived engineering values.

## Agreed in round5 (Q18-Q20)

- Q18: retain wrapped measurements, firmware unwrapped counts, tracking quality,
  and reset/start assumptions for string pots; mm conversion remains offline.
  Unwrapped counts preserve an interpretation, not proof of unobserved turns.
- Q19: previews/diagnostics consume published acquisition snapshots. They must
  not trigger extra reads, consume FIFO data or advance tracking state, so merely
  observing a sensor cannot change the recorded acquisition.
- Q20: preserve the original configuration during upgrade; show exact BDQ-v2/raw
  migration changes and require one acknowledgement before saving. Later boots
  use accepted settings without prompts. Unsupported/ambiguous settings remain
  visible and block START rather than being discarded.

String-pot evidence: AS5600StringPotSensorBase.cpp separates count-domain unwrap
from mm conversion; StringPotWrapTracker.h has analog settling holds and hidden
pending state. Existing tracking lacks explicit hold/timeout/ambiguity flags and
previews currently can advance it. Initial turn assumptions, calibration/reset
epochs and quality must be addressed during implementation; counts alone cannot
recover physically unobserved rotations. See AS5600_String_Pot_Wrapping.md and
Sensor_Lifecycle_and_Deferred_Recovery.md for existing contracts.

Firmware changes discussed in this interview remain unimplemented. Numerical
admission/loss limits and hardware qualification remain separate follow-up work;
they do not prevent specification of the agreed production integration. Release
verification must cover the agreed lifecycle, integrity and import requirements.

## Agreed in round6 (Q21-Q22), including later calibration

- Q21: ordinary Import Manager support is a production release gate. Decode new
  recordings, expose source identities/gaps and reconstruct basic engineering
  values where valid calibration exists. Bench assessors alone are insufficient;
  retain raw evidence/uncertainty and do not implicitly align independent streams.
- Q22: default processing uses the calibration snapshot recorded with the file.
  Later logger calibration applies to future recordings. Applying different
  calibration to an older session is an explicit processing operation with
  provenance, preserving original evidence.
- Users often record without calibration and establish it afterward. Recording
  and import must retain sufficient raw data and honestly identify absent
  calibration. Future reprocessing must support both supplying initially missing
  calibration and revising existing calibration. The reprocessing capability is
  deferred; it is not required for the first release, and missing calibration
  does not make an otherwise valid raw session unusable.

Thus Q21's engineering-value release requirement applies where calibration is
available; it does not require inventing values for uncalibrated sessions or
implementing the deferred calibration/reprocessing workflow now.

## Agreed in round7 (Q23)

- Q23: production acquisition supports arbitrary valid ADC channel subsets,
  unequal channel counts and one ADC idle. Build the recording plan once at
  START, preserve sensor assignment flexibility and let admission constrain
  supported channel/rate combinations. Do not retain fixed diagnostic AIN order
  or paired-device layouts as product requirements.

## Factual prerequisite for Q24: meaning of recorded ADC counts

The current r124 ADS1220 path sign-extends the native signed24-bit result, then
clamps negative results to zero and rescales positive full scale to configured
12-bit counts0..4095 before publishing the cache (AnalogInputManager.cpp:422,
761-763; BoardProfile.cpp:348,364). RawAdcRecording.h stores uint16 fields.
Thus its RAW output is uncalibrated but already quantized, not native converter
words. Native capture requires explicit signed schema/encoder changes, not merely
changing effective_bits. An int32 representation would make six-channel records
36bytes rather than24bytes; old count-based calibration anchors need their
original count domain preserved or explicitly mapped. Native width is not a
claim of24 effective bits of physical measurement precision. Existing throughput
evidence describes the current representation. No representation change has been
implemented; the final Q24 decision below retains the current representation.

## Final Q24 decision: retain current 12-bit counts

- The user reversed the initial Q24 acceptance: retain the existing ADC count
  conversion and uint16 recording fields. Positive full scale maps to0..4095;
  negative converter results remain clamped to zero. Describe this count domain
  honestly rather than calling it native signed converter output.
- There is no current practical requirement for greater than12-bit resolution.
  Avoid reopening performance qualification through larger records or requiring
  calibration migration solely for a count-domain change.
- Native signed counts are deferred and may be reconsidered if a practical need
  emerges. They are not part of production integration scope or a release gate.
  Existing record sizes and count-based calibration semantics remain unchanged.

## Subsequent agreement: intended IMU rate profiles

- The intended supported native six-axis IMU rates are nominal833,1667 and3333Hz,
  with matched accelerometer and gyro rates. This extends the profile roadmap.
- Retain3333Hz for the current ADC boundary trials. Introducing lower-rate
  profiles is separate work requiring node acquisition/FIFO configuration,
  profile identity, logger selection, accurate timing/filter metadata and
  validation. Support for all three rates is not implied by the existing image.
- Follow-up implementation: the isolated r127 test candidate now implements all
  three profile identities in node/logger firmware and has host/target-build
  validation. Its first physical trial selects1667Hz on four nodes. This is not
  a canonical production merge or physical qualification of the lower profiles.

## Subsequent scope: incremental local I2C testing

- Defer I2C characterization until after the current ADC/CAN work. The intended
  incremental workload is one or two rotary sensors and optionally one local
  IMU across the two I2C buses, on top of the established ADC/CAN baseline.
- Multiple local I2C IMUs sharing buses with rotary sensors are not a target
  configuration; CAN IMUs are intended to avoid that arrangement. Reuse the
  earlier I2C findings rather than reopening the retired multi-IMU scheduling
  experiments. No new I2C implementation or qualification is authorized by this
  scope note alone.

## Supplemental interview: scheduling and reconciliation (2026-11-24)

Status: interview complete; Q25-Q32 and shared understanding explicitly confirmed
by the user on 2026-11-24. No implementation is authorized solely by this interview.
These additions do not
reopen the agreed integrity, membership,
configuration-locking, responsive-control or STOP/finalization requirements.

Evidence motivating the additions:

- Isolated r133 at one1000Hz channel per ADC with four3333Hz IMUs used absolute
  timer appointments and delivered1000.000264 rows/s with zero missed rows,
  zero reused/unavailable readings and complete source-bounded delivery of
  3092594 IMU readings. Historical tick-driven1000Hz RAW runs had approximately
  0.04% row omissions. This is promising short-run evidence, not proof of universal
  scheduler superiority or a contemporaneous paired control. Sealed report:
  `BODAQS-worktrees/adc-timer-1x1000-3333-r133/Assessments/01-timer-1x1000-3333/attempt1/ASSESSMENT.md`.
- Current idle control servicing advances at100ms intervals, ordinary discovery
  refresh at30s, with additional conditional authority/reapply retry delays.
  A fixed90s runbook allowance is not a measured minimum preparation time.
  Reconciliation proves the relationship between desired and effective
  configuration; it is distinct from acquisition becoming active.

Agreed supplemental round1 (Q25-Q28):

- Q25: unify local ADC acquisition/row cadence using an absolute-deadline timer;
  avoid imposing identical scheduling on CAN, storage, I2C or UI, and preserve
  current task priorities/core assignments within this addition.
- Q26: accelerate bounded idle reconciliation progress while configured nodes
  are unready, returning to inexpensive background monitoring when ready;
  preserve identity/authority/readback and responsive controls, without adding
  recording-time work.
- Q27: expose actual configured-participant readiness, progress and blockers;
  retain established START membership rules without automatic recording start.
- Q28: target a substantial measured healthy four-node preparation improvement;
  characterize boot/change/recovery paths before promising a fixed latency,
  without redesigning the control protocol solely for startup speed.

User accepted all four recommendations: ADC cadence only; bounded faster idle
preparation; actual readiness visibility; measured improvement without an invented
latency promise. Task priorities/core assignments and recording-time control work
are outside these additions.

Factual follow-up for subsequent questions:

- The trial scan owner currently requires equal contiguous channel counts on both
  ADCs and shares one pending-channel index. Its timer already supports fractional
  appointment spacing, cancellation and late-slot accounting. Previously agreed
  Q23 flexibility still requires a recording plan for arbitrary subsets, unequal
  counts and an idle ADC; changing the wake mechanism alone does not implement it.
- The control observer currently downloads capability and effective snapshots on
  each endpoint scan, in a serialized chain. Capabilities use six pages, effective
  state eight, with open/release and final state/epoch validation around the reads.
  Cached capability_valid alone is not a sufficient reuse predicate: current
  boot/unavailability invalidation does not clear every cached validity field.
  Safe reuse needs explicit source/context binding and invalidation semantics.

Agreed supplemental round2 (Q29-Q32):

- Q29: reuse unchanged capability/effective information only when bound to the
  current node identity and control context, supported by fresh state/version
  evidence. Refetch after reboot, identity/context/configuration change or
  uncertainty; stale cache-valid flags never establish current agreement.
  Preserve coherent readback and final epoch validation when snapshots are read.
- Q30: prioritize configured unreconciled participants with bounded fair progress.
  Absent/failing participants must not prevent healthy participants reaching
  readiness or monopolize controls. Keep deliberate retry backoff and the
  already-agreed strict/best-effort START membership rules.
- Q31: support the Q23 layouts with an explicit per-ADC acquisition plan under
  one common local row cadence. Avoid requiring equal counts, a shared channel
  index or dummy conversions on the less populated ADC. Detailed appointment
  placement is an implementation choice; no simultaneous-sampling promise or
  new per-channel rate system is introduced.
- Q32: validate replacements with representative checks, then retire the ADC
  tick alternative and redundant reconciliation reads. Do not retain both
  indefinitely or require every workload permutation. Cover exact/fractional
  cadence, unequal/idle ADC layouts, late wakes, STOP/restart; four-node cold
  boot, settings changes, late arrival/reboot and a failing node. Use host tests
  for failure paths and a small hardware set including a sustained mixed load.

The accepted defaults on timing/data integrity remain in force: deadlines and
reported missed work rather than silent rate changes, verified conversion and
source identity before publication, safe cancellation/retirement and explicit
uncertainty. A timer wake alone does not prove ADC conversion readiness.
Faster reconciliation does not relax admission, clock trust, authority, snapshot
lifetime, or fencing requirements. Startup/progress visibility must distinguish
configuration agreement from complete recording readiness, including admission.

The design frontier is empty at product/scope level. Numeric servicing budgets,
cache keys/epoch validation details, representative test loads and final latency
measurements belong in the specification/implementation against these requirements,
not guessed guarantees in this interview. No new universal scheduler, task/core
retuning, control-protocol redesign or deep optimization is added. No ADR is
needed for these reversible implementation choices. GLOSSARY.md now defines
configuration reconciliation separately from active acquisition and readiness.
