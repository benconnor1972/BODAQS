# Importing BYB recordings

Local-directory sources accept `.byb` alongside native `.zip` and `.bdq` inputs.
The normal discovery, settling, import, retention and reprocess controls apply.
Default and legacy default discovery patterns include BYB; custom restricted
patterns must explicitly include it if wanted.

## Configure a source

1. In Import Manager, right-click a local-directory source and choose **Edit BYB
   settings**, or create `byb.json` beside its `import_source.json`.
2. Supply the installed sensors' full measuring lengths and compression
   directions. These lengths are hardware calibration, not the bike's fork or
   shock travel. The editor's zero-length template cannot be saved until these
   values are supplied.
3. Select one `.bybLeverage` file or a BODAQS bike-profile JSON under `geometry`.
   Relative paths resolve from `byb.json`. Keeping the referenced file under the
   source makes the setup portable. A curve supplies rear geometry; provide
   `front_projection.head_angle_deg` for the front. A profile must accept linear
   suspension displacement in millimetres, rather than only rotary angles.
4. Select a timezone, or use the source's configured `logger_timezone`.
5. Leave `zero.mode` as `recording` to estimate the reference from each recording,
   or use `fixed` with a measured `count`. Estimation can shift the absolute
   baseline when the suspension never reaches full extension.
6. Drop recordings into the configured inbox. Use separate sources for different
   setups. The setup applies to every BYB file in that source.

[Curve-based example](../../analysis/config/byb/byb_leverage.example.json) and
[bike-profile example](../../analysis/config/byb/byb_bike_profile.example.json)
include matching illustrative geometry files. Packaged manager builds include
these examples and their JSON schema under the bundled
`bodaqs_import_manager/import_agent_assets/byb/examples` resources. They are not
automatically installed as a live sensor setup.

## Configuration problems and travel conflicts

The source status/log reports **BYB needs configuration** with the offending
field or reference. The recording remains in its inbox and is retried after
correction. Native files in the same inbox can still import. Corrupt binary
recordings follow the ordinary failed-input workflow.

Conflicting travel declarations in a recording and geometry require correction
or an explicit per-fact `travel_overrides` decision. An override changes the
normalization range; it does not stretch a curve or change sensor calibration.
The [contract](contracts/BODAQS_BYB_Source_Contract_v1_draft.md) defines tolerance,
precedence and required fields.

## Analysis and retained inputs

The importer uses the source's ordinary preprocessing profile and event schema.
The workbench's **Use BYB stroke definition** option remains independent of file
format. IMU, brake and wheel-speed records are retained as raw values, without
unsupported physical-unit conversions.

`byb.counter_grid.v1` combines repeated counter times and regularizes short skips
within continuous segments. Intervals longer than eight inferred sample periods
start a new segment. Filtering and derivatives do not cross those boundaries.
Original counters and all records remain in the `byb_raw` secondary stream and
the original `.byb` source. GPS uses one observation per 100 recorded rows,
including repeated stationary fixes. The reference's final record overlapping
the trailer is retained; trailing padding does not become samples.

The timing policy is tested with synthetic repeated/skipped counters, selection
origins, wraps and gaps. Validation against representative original recordings
is still needed. Counter resets whose elapsed time cannot be recovered are
rejected rather than repaired by inventing time.

Each imported session retains:

```text
source/
  input.byb
  byb/
    manifest.json
    byb.json
    geometry.json             # or geometry.bybLeverage
    preprocess_profile.json
    event_schema.yaml
    effective_bike_profile.json
```

The manifest includes hashes, original reference paths and effective calibration,
zero, geometry/travel and timing provenance. Changing live setup files does not
alter existing sessions. Explicit reprocessing through the source uses current
settings and a distinct processing identity when relevant settings change.

For an isolated replay of retained inputs in Python:

```python
from bodaqs_analysis.byb import preprocess_byb_snapshot

result = preprocess_byb_snapshot(
    session_dir / "source/input.byb",
    session_dir / "source/byb/manifest.json",
)
```

This checks retained asset/recording hashes and uses the frozen configuration.
Selected FIT inputs, when present, are read from the ordinary retained
`source_aux` folder. Direct preprocessing also supports explicit
`byb_config_path` or `byb_snapshot_path` arguments to `preprocess_session`.
