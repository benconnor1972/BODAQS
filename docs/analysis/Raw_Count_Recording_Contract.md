# Raw analog recording and embedded calibration

The A8 production integration candidate records local analog inputs in the
existing `uint16` 0..4095 count domain. Native negative conversion results clamp
to zero during count scaling, preserving the existing acquisition behavior.
This does not claim twelve effective bits of accuracy.

BDQ v2 session metadata includes `recording_configuration`, with schema
`bodaqs.recording_configuration.v1`. It snapshots the common local row rate and
each configured sensor's identity, assignment, parameters, count domain, raw
field bindings and calibration model/version. Captured anchors, capture time,
geometry, polarity and units are retained. Missing calibration is explicitly
unavailable; non-finite numeric evidence is JSON `null`. The snapshot excludes
network credentials. Native sensor streams retain their own descriptor contracts.

The initial analog model is `analog_geometry_v1`:

```
scale = sensor_full_travel / abs(sensor_full_count - sensor_zero_count)
value = (counts - installed_zero_count) * scale * (-1 if invert else 1)
```

Geometry must have a nonzero count span, positive finite travel and an explicit
output unit. The captured generic calibration block is provenance; this model
does not silently apply a second overlay or a polynomial/LUT transform.

Normal `load_bdq_session` import preserves the original counts in `df_raw` and
exposes valid basic reconstruction as `stream_dfs["analog_engineering"]`. Its
metadata explicitly labels the stream as derived from `primary` using the
embedded snapshot. It copies sequence/time/status evidence without filling gaps
or aligning independent clocks. Legacy sensor-error rows retain raw evidence and have
missing derived values. Unknown domains, unsupported calibration models,
ambiguous identities or mismatched field bindings remain raw-only.

Incomplete recordings can expose verified readable chunks and reconstruction
without claiming successful finalization. The importer does not consult later
configuration/calibration files. Reprocessing an existing session with different
calibration remains a separate, deferred feature.

The production plan binds raw fields to configured sensor identities, rather
than a diagnostic AIN order; analog fields use `<sensor_id>_raw`. ADCs may have
sparse subsets, unequal counts or an idle device. Applicable direct GPIO inputs
use the same explicitly selected twelve-bit domain. One rational timer cadence
supplies the common row rate. Skipped deadlines appear as sequence gaps, with
no catch-up rows. Reused ADC values carry the timing-degraded bit.

Production catalogs now declare `acquisition.count_validity`, schema
`bodaqs.adc_count_validity.v1`, with `valid_minimum: 0`, `valid_maximum: 4095`,
`missing_count: 65535` and `sensor_error_scope: per_field_missing_count`.
The `uint16` record geometry and valid-count domain are unchanged. Missing or
invalid inputs use the sentinel instead of a plausible zero or repeated cached
count. Normal import retains that raw evidence, suppresses its engineering value
and preserves valid engineering values for other fields in the same row. Files
without this exact declared policy keep the conservative row-wide error rule.

A single external ADC's DRDY timeout retires that device for the rest of the
session, while healthy ADC, GPIO and independent native streams continue. The
primary stream's persistent `adc0_drdy_timeout_persistent` (`0x1000`) and
`adc1_drdy_timeout_persistent` (`0x2000`) bits identify the affected ADC; these
are primary-specific flags, not general BDQ flags. Configured assignment
`bus`/`input` binds the device and channels to sensor identities. Analog string
pots receive the same missing count with invalid-input/tracking-uncertainty
evidence in their native stream. The bounded footer's `adc_source_failures`
records ADC index, affected channel mask, first timeout tick in the logger's
modulo-2^32 microsecond clock, and the missing interval through session STOP.
The failed device is never retried implicitly; a new explicit recording resets
the failure state. Shared SPI transfer, register identity, timer and task faults
still request controlled session STOP.

Host checks establish these software properties. Physical timing and mixed-load
comparison remain required before qualifying the complete candidate.
