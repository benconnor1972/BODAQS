# BODAQS BYB Source Contract v1

Status: Implemented v1; reader/import workflows validated with two hardware
recordings. Bike-specific calibration and linkage remain unconfirmed for those
recordings. The schema and examples describe the source-local configuration.

Configuration version: `1`  
Schema identifier: `bodaqs.compatibility.byb`  
Scope: `.byb` recordings in local-directory import sources.

## 1. Purpose and boundaries

A source-local `byb.json` supplies the calibration and bike semantics missing
from a BYB recording. It describes one setup for every BYB recording in that
source. Different setups use different sources.

BYB ingestion MUST produce an ordinary BODAQS session and use the shared
preprocessing pipeline. It MUST NOT select a separate analytic pipeline or a
stroke definition based on the file extension. The source's preprocessing
profile and event schema continue to control analysis. This contract does not
replicate BYB's filtering, differentiation, polynomial fitting or statistics.

Initial physical-unit analysis covers suspension and GPS. Other recorded
channels and the original file MUST be preserved, without inventing calibration
for IMU, brakes or wheel speed.

The binary format reference is
[Turning a .byb recording into suspension numbers](https://rentry.co/natsuras).
The reference describes the input format; this contract defines BODAQS-specific
configuration and interpretation choices.

## 2. Ownership, discovery and paths

The only live configuration location is:

```text
<source_root>/
  import_source.json
  byb.json
  geometry/
    bike.bybLeverage          # or a BODAQS bike-profile JSON
  inbox/
    recording.byb
  staging/
  done/
  failed/
```

`source_root` is `ImportSourceConfig.source_root`, the directory containing
`import_source.json`. It is not necessarily `inbox_dir`. Custom inbox locations
do not change where the configuration is discovered.

- There is one setup object, not a collection of profiles or a source-ID map.
- There is no library-root or workspace-root fallback, ancestor search,
  per-recording sidecar, or inherited nested configuration in v1.
- The importer MUST NOT move, claim or expire `byb.json` or referenced geometry
  as if they were input recordings.
- Native ZIP/BDQ inputs ignore `byb.json`, including when it is absent or invalid.
- Missing or invalid BYB configuration MUST NOT block native files in a mixed
  source. A BYB file awaiting configuration remains available for retry.
- Existing explicitly restrictive discovery patterns remain authoritative.

Reference paths identify exactly one local file. Relative paths resolve against
the directory containing the live `byb.json`; absolute paths and `..` references
are allowed. Directories, globs, URLs, environment-variable substitution and
implicit `~` expansion are not supported. The referenced file must be readable.
References internal to a bike profile retain that profile format's own path
resolution rules; they do not acquire the `byb.json` base directory.

For portability, keep geometry under the source and use relative paths. External
references are permitted, but copying the source alone cannot copy their
targets. Source IDs and library destinations are deliberately absent from
`byb.json`.

## 3. JSON structure

The structural schema is
[BODAQS_BYB_Source_v1.schema.json](../../../analysis/config/byb/BODAQS_BYB_Source_v1.schema.json).
JSON MUST be UTF-8, contain one object, and contain no duplicate keys or
non-finite numeric values. Unknown properties and unsupported versions MUST be
rejected. A schema validator is only the first validation stage; it cannot
verify external files, signal compatibility or recording metadata.

| Property | Requirement and meaning |
| --- | --- |
| `schema` | Required; exactly `bodaqs.compatibility.byb`. |
| `version` | Required integer; exactly `1`. |
| `display_name`, `description` | Optional human-readable labels; not identities or analysis settings. |
| `$schema` | Optional editor hint; never a geometry reference or permission to fetch a remote document. |
| `timezone` | Optional IANA timezone for the BYB header. Otherwise use the source's `logger_timezone`. |
| `suspension` | Required object with explicit `front` and `rear` channel declarations. |
| `geometry` | One tagged file reference. Required when rear suspension is enabled. |
| `front_projection` | Front geometry fallback when a profile does not supply a usable front mapping. |
| `travel_overrides` | Optional explicit resolutions of normalization-travel facts. |

There are no preprocessing-profile paths, event-schema paths, smoothing windows,
stroke thresholds, source paths or output paths in this document.

Examples, with illustrative values rather than installation defaults:

- [Curve-based setup](../../../analysis/config/byb/byb_leverage.example.json),
  with [example curve](../../../analysis/config/byb/example.bybLeverage).
- [Bike-profile setup](../../../analysis/config/byb/byb_bike_profile.example.json),
  with [example profile](../../../analysis/config/byb/example_bike_profile.json).

Copy a setup example as `byb.json`, copy its referenced geometry, and replace
the calibration/geometry values before use. Shipping an example MUST NOT make
its sensor lengths or zero counts automatic defaults.

## 4. Suspension semantics and calibration

The front BYB suspension field binds to the front end in the `suspension`
domain; the rear field binds to the rear end in that domain. Raw values have
quantity `raw`, unit `counts`; calibrated values have quantity `disp`, unit
`mm`. The importer supplies these semantics through the normal signal registry
and calibration metadata. Enabled channels have distinct stable motion-source
identities, `byb_front_linear` and `byb_rear_linear`.

Each channel is either:

```json
{"enabled": false}
```

or an enabled declaration containing:

- `sensor_length_mm`: positive physical displacement over the complete
  0..4095 count span. This is a hardware measuring length, not bike travel.
- `compression_direction`: `increasing_counts` or `decreasing_counts`.
- `zero`: optional policy; omission means `{"mode": "recording"}`.

Disabled channels supply no physical analysis signal, normalization range or
events. Preserve their raw recording values. A disabled or unavailable end MUST
NOT become a fabricated all-zero physical signal. Both ends may be disabled for
a recording whose useful initial output is GPS.

For a valid count `c`, sensor length `L`, direction `s` (+1 for increasing,
-1 for decreasing), and resolved zero count `z`:

```text
suspension_displacement_mm = s * (c - z) * L / 4095
```

Compression is positive. Finite values below zero or above declared travel MUST
NOT be silently clipped during this conversion. Preserve excursions and report
them in QC; the declared range is a normalization fact. Counts outside 0..4095
are invalid observations, not a larger sensor span, and MUST be excluded from
calibration/zero estimation and handled through the normal invalid-data policy.

### 4.1 Fixed zero

`{"mode": "fixed", "count": 120}` specifies the count at full extension.
`count` may be fractional, but must lie in 0..4095. This reference is authoritative
for that channel. Subsequent zeroing/normalization MUST NOT replace it with a
recording-derived baseline, even when the preprocessing profile enables general
zeroing. Raw samples remain unchanged.

### 4.2 Recording-based zero

`{"mode": "recording"}` estimates a single reference for each enabled channel
from that recording. Reuse the BODAQS minimum-window-median zero estimator,
with `zero_window_s` and `zero_min_samples` from the resolved preprocessing
profile. Apply it to direction-corrected valid suspension samples. Candidate
windows MUST stay within continuous segments; select the lowest eligible
window median over the recording, with the earliest window breaking ties.
The minimum eligible count follows the BODAQS rule:
`max(zero_min_samples, ceil(zero_window_s / nominal_dt_s))`.

If there is no eligible window, use the first valid sample and record the
fallback warning. If there is no valid sample, the enabled channel cannot be
calibrated and import requires correction. An estimated count MUST be converted
back to the original count convention in the resolved calibration record.

This is a source-calibration requirement even if the profile disables general
zeroing. It is applied once, before linkage mapping; later preprocessing MUST
recognize that the reference has already been resolved. It does not add BYB's
median/moving-average filters or startup trimming. A recording that never reaches
full extension can underestimate absolute displacement; always record that the
reference was estimated and allow a fixed override in a subsequent import.

## 5. Geometry

When present, `geometry` MUST contain exactly one `kind` and one `path`:

```json
{"kind": "byb_leverage", "path": "geometry/bike.bybLeverage"}
```

or:

```json
{"kind": "bodaqs_bike_profile", "path": "geometry/bike.json"}
```

No fallback to the source's native `bike_profile_path` is implicit. BYB geometry
is explicitly selected here. A curve-based BYB-only source does not need a
separate native bike profile for its BYB recordings.

### 5.1 BYB leverage curve

Read shock displacement/wheel displacement pairs in millimetres and the optional
`shockStrokeMm` and `wheelTravelMm` comment metadata described by the reference.
At least two finite, non-negative points with strictly increasing shock
coordinates are required for the BODAQS LUT adapter. Do not silently sort or
deduplicate conflicting points. A curve accepted by BYB's unconstrained
polynomial procedure may therefore need correction before use as a BODAQS LUT.

Preserve the supplied points and generate the normal piecewise-linear BODAQS
LUT, with linear end extrapolation and QC for observations outside its tabulated
domain. Do not normalize its coordinates to the recording's travel values,
assume constant leverage, or reproduce BYB's high-degree polynomial fit.

For each rear travel fact, use positive declared curve metadata when present;
otherwise use the corresponding point-column maximum. Malformed/non-positive
declared metadata is an error rather than an instruction to ignore a declaration.
Table maxima are fallbacks, not additional declarations that must match explicit
metadata: a table may extend beyond a declared normalization range.

This file supplies rear geometry only. An enabled front channel requires
`front_projection` in this branch.

### 5.2 BODAQS bike profile

Validate the referenced profile against the existing
[Bike Profile Contract](BODAQS_Bike_Profile_Contract_v0_draft.md). Preflight the
effective transform chain against BYB's actual linear displacement signals.
Each enabled end MUST have one unambiguous route to a primary `disp`, `wheel`,
`mm` analysis signal, using the profile or the permitted front fallback.

A profile that only maps rotary `ang_disp`/degrees, or selects a different
`motion_source_id`, does not provide such a route. Do not relabel BYB
millimetres as angles or change source identities to force a selector match.
Report the incompatible selector/transform. Unused transforms for disabled
ends or other sensors do not themselves invalidate an otherwise usable profile.

### 5.3 Front projection

`{"head_angle_deg": 64}` under `front_projection` describes the head angle
measured from horizontal, greater than 0 and at most 90 degrees:

```text
front_wheel_displacement_mm = front_suspension_displacement_mm * sin(head_angle)
```

It is required when the front is enabled and no usable profile mapping supplies
that output. Supplying it alongside an enabled usable front profile mapping is
an ambiguity error; edit the profile or remove the fallback. It MUST NOT be
applied on top of that mapping. A profile may explicitly define another front
mapping, including identity; the two examples demonstrate these alternatives.

## 6. Travel resolution and conflicts

Resolve normalization facts independently by end and physical domain:
`front_suspension_mm`, `front_wheel_mm`, `rear_suspension_mm`,
`rear_wheel_mm`. Enabled ends require positive suspension and wheel ranges.

Sources of facts are semantic bike-profile `normalization_ranges`, curve
metadata/fallback maxima, and the recording trailer. Trailer fork travel means
front **suspension** travel, shock travel means rear suspension travel, and rear
wheel travel means rear wheel travel. Do not compare fork travel directly with
a projected front wheel range.

1. If `travel_overrides` contains a fact, use that positive value. This is the
   explicit decision resolving disagreements for that fact. Preserve all
   competing declarations and identify the override in provenance.
2. Otherwise compare all available declarations for the same fact. Two values
   `a`, `b` agree when `abs(a-b) <= max(0.5, 0.001 * max(a,b))`, in millimetres.
   Larger discrepancies require configuration correction before import; no
   profile/curve/trailer silently wins.
3. For agreeing declarations, retain the profile/curve value when available,
   otherwise the trailer value. This tie-breaking rule only handles rounding.
4. When `front_projection` supplies the mapping and no front wheel range is
   declared, derive it from the resolved front suspension range and the same
   sine factor. Do not invent another missing range or rear linkage ratio.

Missing/unparseable trailer values provide no fact and generate a diagnostic;
they need not block a setup that supplies all required facts elsewhere. Positive
conflicting declarations do block it. Malformed explicit configuration and
referenced profiles/curves are errors, not missing-data fallbacks. Facts for
disabled ends do not block import.

Overrides affect normalization ranges, not sensor length, calibration slope,
curve points or profile transform coefficients. For example, overriding rear
wheel travel to 155 mm does not stretch a 150 mm curve. Geometry errors require
editing/replacing the geometry reference itself.

## 7. Timing, GPS and other channels

Use counter differences for relative timing rather than row number or the
declared sample rate. Preserve original counters and record the initial counter
used as the relative origin. Non-zero initial counters MUST NOT add an arbitrary
offset to the elapsed session timeline.

Interpret the header's local date/time using `byb.json.timezone`, otherwise the
source's `logger_timezone`. A valid timezone is required; do not guess from the
host machine or a short display label. Missing timezones and ambiguous/nonexistent
local timestamps require correction rather than silent DST guesses.

The reader's versioned timing policy MUST distinguish repeated/quantized counters
from genuine gaps, preserve elapsed gaps, and report resets/wrap handling. Any
regularization/resampling MUST remain within continuous segments. Filtering,
differentiation and event pairing MUST NOT bridge a gap. Policy
`byb.counter_grid.v1` estimates the nominal period from the median positive
counter difference, rounded to the millisecond clock. It averages valid
suspension observations sharing a counter time, then linearly interpolates onto
a regular grid within each segment. A positive interval greater than eight
nominal periods starts a new segment. Invalid suspension runs are not bridged.
Grid points lie inside the observed segment extent; no fractional-period final
point is extrapolated. The unmodified records remain in `byb_raw`.

A uint32 counter wrap is unwrapped only when the preceding value exceeds
`0xF0000000` and the following value is below `0x0FFFFFFF`. Other backward jumps
are rejected because their missing elapsed time is unknown. This policy is
covered by synthetic fixtures and by original recordings with non-zero initial
counters and repeated/skipped counters. Validation evidence and remaining
calibration limitations are described in the
[import guide](../BYB_Import.md). This contract adds no user-facing timing tuning
fields.

For recognized fixed trailers, 67 NUL-padded fields of 30 bytes follow the
two-byte sentinel. Fork, shock and rear-wheel travel occupy fields 10, 11 and 12
(zero-based), at trailer-relative offsets 302, 332 and 362. Later fields are not
travel. Retain the raw travel strings and bike/frame/wheel labels in recording
QC. Use the compact trailing-travel interpretation only when the recognized
fixed layout is absent; missing/unparseable travel follows section 6.

GPS values held across high-rate records MUST NOT be presented as independent
high-rate fixes. Produce the standard GPS stream, preserving legitimate stationary
fixes rather than deduplicating solely by equal coordinates. Convert latitude/
longitude to degrees and GPS speed from km/h to the normal BODAQS stream units;
altitude is already in metres. Invalid/missing fixes remain missing, with QC.

Retain the original file, raw suspension counts, raw counters, and uncalibrated
ancillary values. Unknown IMU/brake/wheel-speed conversions MUST NOT become
invented g, percent or m/s analysis signals.

## 8. Validation and import lifecycle

Validation occurs in three stages:

1. Structural: JSON syntax, version, unknown keys, types, enabled-channel
   calibration declarations and tagged references.
2. Setup: paths, referenced content, timezone availability, usable signal
   transforms, front mapping and configured normalization facts.
3. Recording: binary integrity, counts/timebase, zero estimation, trailer
   agreement and the complete resolved physical semantics.

Errors MUST identify the field/reference/end involved and an actionable remedy.
Distinguish `needs_configuration` from a corrupt recording. Configuration errors
leave the BYB input unclaimed or safely returned to its inbox and retry after a
configuration change. A corrupt/unsupported recording follows the existing
failed-input workflow. A processing failure must retain enough context for retry.

Do not partially publish a suspension session when a configured enabled channel
has incompatible/missing semantics; the user may explicitly disable that end.
Once valid, use the normal settle, claim, run/session writing, progress,
done/failed retention and reprocessing workflow. Configuration/reference files
are not subject to recording retention rules.

## 9. Reproducibility and processing identity

Before processing a candidate, resolve and freeze the configuration and all
referenced content as one snapshot. Validation, hashing and computation MUST
consume those same bytes, including any transitive profile dependencies. A file
edit while processing applies to a later candidate, not part of the active one.

Persist with the session's source provenance:

- original `.byb` bytes, original filename and content hash;
- original `byb.json` and referenced geometry/dependency snapshots, hashes and
  original path labels, without rewriting their source bytes;
- an effective resolved manifest: channel bindings/directions/scales, fixed or
  estimated zero counts and estimator provenance, selected travel facts and all
  conflicts/overrides, effective geometry, timezone, timing policy and QC;
- reader/calibration adapter versions and the usual resolved preprocessing,
  event-schema and bike-profile inputs.

Snapshots MUST be replayable through the resolved manifest without the original
external paths still existing. Imported sessions MUST NOT depend on a later live
read of the source's `byb.json`.

Raw identity is based on recording content and remains unchanged by a rename,
source move or setup edit. Processing identity includes the effective BYB
configuration and referenced content, adapter/timing versions and normal
analysis inputs. Relevant calibration/geometry edits permit a distinct processing
result; display-label edits alone need not. Resolve omitted defaults explicitly
when computing that effective identity. Identical raw bytes imported under
different effective setups are not the same processing result.

Changing live settings MUST NOT mutate existing sessions or automatically
reprocess an entire library. An ordinary explicit reprocess uses current source
settings and records a new processing identity; reproducing an earlier result
uses its retained snapshot. Native input identities and existing library layouts
remain unaffected. No compatibility folder is added to a library root.

## 10. Acceptance checks for implementation

- Both reference branches and front-only, rear-only and disabled-end cases.
- Fixed and recording-based zeros, both directions, short-recording fallback,
  invalid counts, baseline preservation through later preprocessing, and no
  estimation windows across gaps.
- Missing references, unknown keys/versions, invalid timezones, incompatible
  rotary profiles, ambiguous front mappings and unsupported curve tables.
- Agreeing rounded travel values, unresolved conflicts, missing trailer values,
  per-fact overrides and no implicit curve rescaling.
- Non-zero counter origin, duplicates, skips, resets/wraps, real gaps, GPS held
  samples and final-record/trailer overlap against representative recordings.
- Mixed native/BYB batches, native progress during BYB configuration failure,
  configuration repair/retry, settling, claims, rename deduplication, settings
  changes during import and reprocessing after external files have moved.
- Ordinary signals, motion channels, events, metrics, adequacy and workbench
  stroke-family selection with no format-specific chart implementation.
