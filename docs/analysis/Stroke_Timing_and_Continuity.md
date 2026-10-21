# Stroke timing and continuity

Implemented: 2026-10-21.

## Corrected behaviour

SegmentBundle metrics use each event's own timestamp grid, instead of assuming
that every row has the first event's alignment. This corrects systematically
shifted stroke measurements when the first event window is clipped. Original
absolute timestamps are preferred for interval bounds; float64 arithmetic
tolerance preserves inclusive endpoints without rounding to a sample interval.
Peak timestamps and integrals also use their own event's grid.

Time arrays are always float64. Extracted signals default to float64; an explicit
`OutputSpec(dtype=np.float32)` remains supported for signals only. Incomplete
interval coverage produces NaN metrics instead of a partial stroke measurement.

## Continuous segments

Filter and detector state resets at changes in `segment_id`, non-increasing or
invalid timestamps, and timestamp gaps exceeding 1.5 nominal sample intervals.
The nominal interval comes from the declared sample rate when a processing
stage supplies one; otherwise it is the median positive timestamp difference.
This deliberately detects missing samples shorter than a fixed 250 ms cutoff.

Motion derivation filters and differentiates segments independently. Missing
source samples further split motion processing into finite runs. Runs too short
for filtering remain NaN with a warning; they never borrow adjacent segments.
Legacy Butterworth/Savitzky-Golay paths and raw dropout detection/repair also
respect recording boundaries.

Event candidates, conditions, secondary searches, debounce, metric smoothing,
and extracted windows cannot bridge recording boundaries. Unavailable trigger
samples reset trigger state and constrain subsequent searches on that signal.
`edge_ignore_s` applies at continuous signal boundaries for all trigger types.

## Trigger caching and validation

Extrema, threshold, zero-crossing, and phased-threshold candidates are cached
within one detection call by signal and trigger configuration. Each continuous
signal run is scanned once per configuration. Relative search windows select
from those candidates instead of restarting peak detection, hysteresis, or
phase matching at arbitrary search edges. Peak prominence and distance are
therefore determined on a complete continuous run, not a cropped search window.

The unimplemented `custom` primary and secondary trigger types are rejected by
basic validation, schema parsing, and direct detection calls.

## Existing libraries

Existing artifacts are not rewritten automatically. Reprocess source sessions
to replace affected motion signals, events, and persisted metrics. Recalculating
metrics alone fixes alignment on existing signals but cannot undo motion filters
that previously crossed gaps or repair already incorrect trigger pairings.

New event rows identify `schema/v1-continuous` as their detector version.
The raw dropout behaviour version is now `bodaqs.raw_signal_dropout_filter.v4`,
which participates in Import Manager processing identity. Reimporting identical
source data is consequently distinguished from processing with the old code.
Normal import duplicate/source-selection rules still apply.

Notebook and web distribution definitions are unchanged. No new excursion,
velocity, or study-population rejection threshold is introduced.
