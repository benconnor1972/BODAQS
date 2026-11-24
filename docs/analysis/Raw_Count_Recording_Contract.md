# Raw analog recording and embedded calibration

The A8 production integration candidate records local analog inputs in the
existing `uint16` 0..4095 count domain. Negative conversion results clamp to zero
and set the record's sensor-error bit; out-of-range positive values clamp to
4095 with that bit. This does not claim twelve effective bits of accuracy.

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
or aligning independent clocks. Sensor-error rows retain raw evidence and have
missing derived values. Unknown domains, unsupported calibration models,
ambiguous identities or mismatched field bindings remain raw-only.

Incomplete recordings can expose verified readable chunks and reconstruction
without claiming successful finalization. The importer does not consult later
configuration/calibration files. Reprocessing an existing session with different
calibration remains a separate, deferred feature.

This contract change alone does not generalize the benchmark's fixed ADC layout.
The acquisition-plan slice supplies arbitrary subsets, unequal/idle ADCs and the
common timer cadence before the complete candidate is qualified on hardware.
