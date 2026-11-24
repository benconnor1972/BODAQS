# Local BMI270 production preservation (#223)

Software integration candidate; physical I2C qualification remains open.

The BMI270 keeps its existing dedicated BDQ v2 FIFO stream, independent of the
ADC primary cadence and CAN IMU clocks. Signed 16-bit accel/gyro/temperature
counts, mixed-rate gyro validity, status bits and bounded clock observations
retain their existing contracts. Device readback and metadata retain effective
ODR/range/filter settings, hardware gyro correction mode, identity and saved
orientation. Saved orientation affects offline body-frame channels, not recorded
native axes. Hardware IOC compensation remains explicitly identified.

## Changes

- `sampleValues()` now copies the acquisition owner's latest published sample
  and IOC snapshot. Observing repeatedly does not pop recording/IOC queues,
  create bus traffic, or update recording-use diagnostics. Missing publication
  produces `sample_valid=0` and unavailable sample age. Snapshot publication is
  bounded and uses lock-free 32-bit atomic words with a generation check; readers
  reject concurrent partial publication. Shutdown and new sessions invalidate
  the old publication. After STOP, the last snapshot remains inspectable with
  increasing age until shutdown/restart.
- Normal BDQ v2 import now invokes the existing IMU stream reconstruction step.
  Embedded valid scale/orientation metadata yields engineering/body channels;
  original native streams remain present. Missing metadata leaves raw evidence
  and QC warnings. Missing clock observations leave native time only and do not
  fabricate logger alignment. Sources with zero samples retain catalog identity
  and fail derived extraction explicitly.
- FIFO retirement is unchanged: STOP disables production, suspends the device,
  performs the bounded final drain and retains queued samples for the recorder.
  Repeated STOP is harmless; drain failure returns false and increments evidence.
  Strict/best-effort source membership remains the shared START gate's concern.

## Verification

- Red/green preview regression: the actual production `sampleValues()` initially
  failed because it consumed evidence and updated row diagnostics; it now passes
  repeated observation, signed count/temperature preservation, absent publication,
  and new-epoch invalidation with the real atomic publication helper. Concurrent
  publication/read stress checks coherent axes, sequence and both timestamp words.
- `firmware/tools/test_bmi270_preview_runtime.py` also compiles the actual FIFO
  `stopSession()` against an independent device/drain model: late tail retention,
  stopped producer before drain, idempotent STOP and explicit final-drain failure.
- `firmware/tools/test_i2c_startup_runtime.py`: 46 startup/recovery checks pass.
- Focused Python import checks: `test_bmi270_production_import.py`,
  `test_io_bdq_v2.py`, and `test_io_bdq_storage_types.py` (43 passed). The new normal
  import fixture first failed because BDQ v2 skipped IMU reconstruction; it now
  confirms signed counts, literal scale/rotation results, FIFO missing-sample
  evidence, embedded metadata, zero-sample identity and absent clock relations.
- `pio run -e bodaqs_a8_production`: passed (RAM 286180 / 327680 bytes;
  flash 2183513 / 4063232 bytes). Existing ArduinoJson deprecation warnings
  remain outside this change.

The runtime fixture runs production adapters verbatim with independently supplied
hardware/time evidence. It does not model physical wire timing, FIFO service
capacity, sensor noise or bus contention. Full-suite/integrated reviews are owned
by the integration branch.

## Remaining physical release gates

On the A8 candidate, record the firmware commit, board and wiring, chosen profile,
400 kHz bus, FIFO service rate and admitted mixed load. Verify sensor readback,
signed axes/temperature and ordinary Import Manager engineering values, native
clock observations and gaps; confirm previews do not change recorded sample
counts. Exercise START/STOP/restart, absent sensor and disconnect/recovery, and
check final-drain failure/tail evidence. Measure sustained service and responsive
controls with the intended rotary-sensor-plus-optional-local-IMU workload.
Additional I2C permutation/capacity characterization remains deferred. Host tests
and target compilation do not qualify any physical load.
