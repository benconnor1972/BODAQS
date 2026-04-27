````markdown
# Context: Sample-rate-independent derivative preprocessing for displacement signals

I am working with displacement signals from a data logger, typically for suspension analysis. The pipeline currently supports Butterworth-filtered versions of displacement at various cutoff frequencies, and I want to derive velocity and possibly acceleration from those displacement signals.

The chosen approach is to keep the **user-facing preprocessing parameters expressed in physical/analytical terms**, rather than in sample-count terms, so users do not need to reconfigure the pipeline whenever the sample rate changes.

## Core principle

Separate configuration into two layers:

1. **User/config parameters**  
   These should express the analysis intent and should usually be independent of sample rate.

2. **Internal/materialized parameters**  
   These are derived from the sample rate and are used to actually run the filters and derivative estimators.

In other words:

```text
User-facing config: physical meaning / analysis intent
Internal implementation: sample-rate-specific coefficients and sample counts
````

## User-facing parameters

Butterworth filter cutoffs should be specified in **Hz**, for example:

```yaml
displacement_lowpass_hz: 80
velocity_lowpass_hz: 60
acceleration_lowpass_hz: 30
```

Savitzky–Golay settings should specify window duration in **milliseconds**, not samples, for example:

```yaml
velocity_sg_window_ms: 20
acceleration_sg_window_ms: 40
sg_polyorder: 3
```

This means the user is choosing the real-world smoothing duration and bandwidth, not a number of samples that only makes sense at one sample rate.

## Internal/materialized parameters

At runtime, the pipeline should infer or receive the sample rate, then convert the physical parameters into implementation parameters.

For Butterworth filters:

```text
normalized_cutoff = cutoff_hz / (fs_hz / 2)
```

Then generate the actual filter coefficients for the current sample rate.

For Savitzky–Golay:

```text
window_samples = round(window_ms / 1000 * fs_hz)
```

Then adjust to satisfy S-G requirements:

```text
window_samples must be odd
window_samples must be greater than polyorder
window_samples must be valid for the available signal length
```

This gives equivalent real-world smoothing across sample rates.

Example:

| Setting             |        At 500 Hz |       At 1000 Hz |
| ------------------- | ---------------: | ---------------: |
| `sg_window_ms = 20` | about 11 samples | about 21 samples |
| `sg_window_ms = 40` | about 21 samples | about 41 samples |

The physical window duration remains the same even though the sample count changes.

## Recommended processing structure

A sensible derivative pipeline is:

```text
raw displacement
→ Butterworth low-pass displacement
→ Savitzky–Golay derivative estimate for velocity/acceleration
→ optional Butterworth low-pass on derived velocity/acceleration
```

The final velocity or acceleration filter is not just a “cleanup” step. It should be treated as defining the final bandwidth of the derived analysis channel.

So a velocity channel might be interpreted as:

```text
velocity derived from displacement filtered to 80 Hz, with final velocity bandwidth limited to 60 Hz
```

and acceleration might be:

```text
acceleration derived from displacement filtered to 80 Hz, with final acceleration bandwidth limited to 30 Hz
```

This provenance should be preserved in column names, metadata, registry entries, or schema/config records.

## Why final derivative filtering can be valid

Differentiation amplifies high-frequency content. Velocity amplifies high-frequency noise, and acceleration amplifies it even more strongly. A second filter pass on the derived series can be valid and useful if it defines the analysis bandwidth expected to contain physically meaningful information.

The tradeoff is that peak values and sharp transient features become bandwidth-dependent. This is acceptable if the bandwidth choices are explicit and recorded.

## Do not make cutoffs automatically scale with sample rate

The sample rate should affect feasibility and internal implementation, not automatically change the analysis question.

For example, do **not** automatically do this:

```text
500 Hz sample rate → velocity cutoff 60 Hz
1000 Hz sample rate → velocity cutoff 120 Hz
```

That would imply that simply sampling faster means higher-frequency motion should be included in the analysis. That may or may not be physically justified.

Instead:

```text
same preset + higher sample rate → same physical cutoffs, different internal coefficients/window sample counts
```

A higher sample rate may support a more detailed preset, but it should not silently change the meaning of an existing preset.

## Presets

Presets should be defined in physical terms, for example:

```yaml
derivatives:
  preset: general

  displacement:
    lowpass_hz: 80

  velocity:
    sg_window_ms: 20
    sg_polyorder: 3
    final_lowpass_hz: 60

  acceleration:
    sg_window_ms: 40
    sg_polyorder: 3
    final_lowpass_hz: 30
```

Possible conceptual presets:

```text
conservative
general
high_detail
```

These should differ in physical bandwidth and smoothing duration, not in raw sample counts.

## Sample-rate guardrails

Although user-facing parameters can be sample-rate independent, they cannot be sample-rate blind.

The pipeline should check that requested cutoffs are feasible for the current sample rate. For example:

```text
cutoff_hz must be comfortably below Nyquist
```

A practical policy might be:

```text
maximum cutoff ≈ 0.35–0.40 × fs_hz
```

For example:

| Sample rate | Nyquist | Practical maximum cutoff at 0.35 × fs |
| ----------: | ------: | ------------------------------------: |
|      250 Hz |  125 Hz |                               87.5 Hz |
|      500 Hz |  250 Hz |                                175 Hz |
|     1000 Hz |  500 Hz |                                350 Hz |

The exact policy can be configurable.

In strict mode, unsupported settings should raise an error.

In tolerant mode, the pipeline may clamp the cutoff and issue a warning, for example:

```text
Requested cutoff 120 Hz is too high for fs = 250 Hz; clamped to 87.5 Hz.
```

This fits well with a strict/tolerant preprocessing philosophy.

## Suggested helper behavior

A helper for S-G window materialization should:

```text
1. Convert milliseconds to samples.
2. Round to nearest integer.
3. Force the result to be odd.
4. Ensure the result is greater than polyorder.
5. Ensure the result is not longer than the available signal.
6. Warn or fail if adjustment is significant.
```

Conceptually:

```python
def sg_window_samples(window_ms, fs_hz, polyorder):
    n = round(window_ms * 1e-3 * fs_hz)

    if n is even:
        n += 1

    min_n = polyorder + 2
    if min_n is even:
        min_n += 1

    return max(n, min_n)
```

The actual implementation should also handle very short signals and strict/tolerant behavior.

## Uniform sampling assumption

Standard Savitzky–Golay derivative estimation assumes uniform sample spacing.

If timestamps are irregular enough to matter, the pipeline should either:

```text
resample to a uniform time grid before using S-G
```

or use a derivative method that explicitly supports irregular spacing.

For normal logger data with a stable sample rate, using:

```text
delta = 1 / fs_hz
```

is reasonable, but the inferred sample interval should be validated.

## Recommended interpretation

A derived velocity or acceleration channel should not be treated as a universal truth. It is a bandwidth-limited estimate with known provenance.

For example:

```text
v_sg_from_x_lp80_lp60
```

means:

```text
velocity estimated by Savitzky–Golay from displacement low-pass filtered at 80 Hz, then velocity low-pass filtered at 60 Hz
```

Similarly:

```text
a_sg_from_x_lp80_lp30
```

means:

```text
acceleration estimated by Savitzky–Golay from displacement low-pass filtered at 80 Hz, then acceleration low-pass filtered at 30 Hz
```

The pipeline should preserve this provenance clearly enough that metrics such as peak velocity, RMS velocity, peak acceleration, and acceleration RMS are not ambiguous.

## Overall recommendation

Keep user-facing derivative preprocessing settings in physical units:

```text
Butterworth cutoffs: Hz
S-G windows: milliseconds
S-G polyorder: dimensionless
```

Use the sample rate only to materialize:

```text
filter coefficients
normalized cutoff frequencies
S-G window sample counts
validity checks
```

This should allow users to change logger sample rate without having to rethink their preprocessing configuration, while still keeping the analysis physically meaningful and reproducible.

```
```
