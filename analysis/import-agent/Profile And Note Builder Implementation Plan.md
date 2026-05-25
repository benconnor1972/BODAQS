# BODAQS Import Manager Profile And Note Builder Plan

Status: implemented second slice

## Goal

Make normal source setup possible without hand-editing JSON. A user should be
able to create or duplicate a bike profile, edit the rear shock-to-wheel LUT,
choose note-template fields from a master catalog, and redirect a source to a
different library from the Import Manager UI.

The bike profile is the user-facing anchor for bike-specific configuration.
The rear LUT remains part of the bike profile, and bike-specific note templates
and setup presets are managed from the bike-profile editing flow.

## Phase 1. Source Library Retargeting

Implemented:

- app-config update helper for changing a source's target library
- source-local `import_source.json` update for `library_id` and `artifacts_dir`
- Manager UI `Change Library` action
- tests for app-config and source-config consistency

## Phase 2. Reusable Builder Models

Implemented:

- `bodaqs_analysis.import_agent_profile_builders`
- source-local discovery of exactly one valid bike profile, session note
  template, and bike setup preset
- form-value extraction/application for bike profiles
- rear LUT parse/format/update helpers
- note-template field catalog loading and validation
- tests for builder behavior

## Phase 3. Bike Profile Editor

Implemented:

- Manager UI `Edit Bike` action
- editable bike/profile basics
- editable front fork travel, rear shock travel, and rear wheel travel
- save-time bike-profile validation
- setup-preset synchronization to keep draft notes linked to the active bike
  profile
- profile IDs are derived from the display name for normal UI use
- note-template IDs are kept/derived internally rather than exposed in the
  normal field-selection UI
- bike-profile `setup` fields have been removed from the shipped default and
  are stripped when profiles are saved through the builder

Future refinement:

- richer field grouping and validation hints
- optional sensor/install details in the form

## Phase 4. Rear LUT Editor

Implemented:

- rear LUT editing is launched from the bike-profile editor
- dedicated LUT dialog using editable `shock_mm, wheel_mm` lines
- interpolation/extrapolation controls
- enabled/disabled control
- save-time strict monotonic input validation

Future refinement:

- graphical preview
- add/delete row table controls
- import/export LUT CSV

## Phase 5. Note Template Field Builder

Implemented:

- master field catalog asset in `import_agent_assets`
- note-template editing is launched from the bike-profile editor
- scrollable field selector
- template id, version, title, description, and custom-field controls
- setup-preset filtering to selected fields
- target bike-profile relinking

Future refinement:

- preset value editor for chosen fields
- field catalog grouping/filtering
- custom user-defined field creation

## Phase 6. Copy From Existing Source

Implemented:

- Manager UI `Copy Bike` action
- Manager UI `Copy Notes` action
- copied files remain independent source-local files
- copied note setup presets relink to the target source's bike profile

## Phase 7. Provisioning Shortcuts

Implemented:

- newly created sources are selected in the Manager tab
- after source creation, the app offers to open the bike-profile editor
- after source creation, the app offers to open the note-template field selector

Future refinement:

- first-run wizard page for choosing "start from defaults" vs "copy from
  existing source"
- combined bike/profile/note summary screen before creating the source
