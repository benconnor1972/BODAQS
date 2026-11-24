# Production configuration migration (#225)

Production records BDQ v2 counts/native streams. RAW and LINEAR remain idle
preview preferences. Existing calibration anchors retain their original count
domain; ADC anchors still describe the established 0..4095 representation.
Calibration is optional for raw recording and does not become available merely
because migration was accepted. Qualification/admission is a separate observation.

## Shared migration owner

`ProductionConfigMigration` captures the loaded file before parsing, default
insertion or BMI normalization. Loading/rendering is read-only. Its proposal
preserves unchanged lines and unknown sensor type tokens, recognizes keys
case-insensitively with the loader's final duplicate taking precedence, changes legacy formats
to `bodaqs_multi_stream_binary`, explicitly retires POLY/LUT and output transform
selection, records revision 1, and defaults membership to strict only when no
explicit prior `recording_best_effort` exists. Web/API and the paged physical
Settings / Log format review use the same ordered changes and source revision.
The physical control requires review through the last page before acceptance.

Until acceptance, ordinary configuration, parameter and calibration writes are
blocked, along with START. Acceptance verifies the source is unchanged, saves and
reads back the exact original at `<config-path>.original-<source-revision>`, then
uses the existing atomic text-file replacement to persist the proposed file.
An existing matching backup permits retry; a differing or unreadable backup is
never overwritten. Backup/save failures retain the original and pending state.
A successful reload sees the persisted revision and does not prompt again.
Application failures report saved-but-not-applied and require repair/restart.
`ProductionConfigMigrationApply` owns the post-acceptance ownership check,
runtime rebuild, ADC cadence application and status refresh. UI callers render
its explicit result. ConfigManager exposes a typed persistence/reload result
without depending on new hardware/application work; its existing boolean
acceptance wrapper remains compatible. A completed save followed by failed reload
is still reported as saved, and does not rebuild runtime sensors.

The migration forms are `POST /config/migration` (`acknowledge=yes`, `revision`)
and `POST /api/v1/config/migration` (JSON boolean `acknowledge`, string `revision`).
`GET /api/v1/config` supplies the pending state, revision and exact changes.
Regular production format changes accept BDQ v2 only. Historical formats remain
parseable for migration and analysis readers remain unchanged.

Unsupported sensor tokens remain visible and are preserved through ordinary
saves, sensor deletion/reindexing and edit rollback. Unknown types or ambiguous
output modes block START rather than silently becoming another sensor/mode.

## Mutation and calibration

`ConfigManager::configurationMutable()` combines the full lifecycle ownership
lock, upload ownership and migration state. Direct analog/string calibration and
BMI orientation entry points use it. Web/API mutations and physical calibration
recheck ownership; file mutation uses the full lifecycle lock. Production
transform selection/reload endpoints explicitly return HTTP 410.

`saveSensorParamsByName(name, keys, values, count)` stages all parameters, writes
once and restores the complete prior ParamStore on failure. It does not rebuild
runtime sensors while their calibration methods are active. Analog/string/BMI
calibration applies live anchors only after successful persistence. The canonical
serializer now retains the separate calibration cache (including mode and capture
metadata); reload resets absent calibration instead of retaining a previous file's
values. Saved count anchors and calibration mode survive later ordinary saves.
Rate/format/Wi-Fi menu actions expose persistence failure instead of announcing
an unapplied choice.

`LoggerConfig::recordingBestEffort` defaults false; its storage/API/web key is
`recording_best_effort`. Settings provides an explicit membership toggle. This
setting does not establish readiness, qualification or admission; the shared
recording policy owns those decisions.

## Validation and remaining gates

Focused host checks execute the real ConfigManager, migration owner, HTML
renderer, web/API acknowledgment handlers and physical acceptance adapter with
independent file/controller/display outcomes. Cases include no write on load or
render, stale acknowledgment, backup failure, config replacement failure after a
successful backup, repeat boot, explicit best effort, unknown token persistence,
calibration roundtrip, multiple-parameter rollback and lifecycle rejection.

Additional focused checks cover real analog calibration preview behavior after
save failure/success, string-pot calibration guards and unchanged raw previews,
existing sensor web/JSON edits and START lifecycle fixtures. Target compilation
uses `bodaqs_a8_production` and passed (RAM 286348 / 327680 bytes, flash
2209489 / 4063232 bytes). START checks: 135 passed; async storage/controller:
39 passed. Existing ArduinoJson deprecation warnings remain. No flash was performed. The integration branch owns
full-suite and fresh standards/spec reviews.

Physical release checks remain: migrate an actual old mixed-sensor config, inspect
all change pages and backup bytes, power-cycle after acceptance, simulate SD save
failure and confirm visible failure/retained anchors, and verify calibration and
read-only navigation throughout preparation/finalization. Host models and target
linking do not establish SD power-loss behavior, physical FIFO/I2C capacity or
qualification of any mixed load.
