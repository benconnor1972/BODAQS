# BODAQS Import Agent Architecture Note

## Status

Draft architecture note for evolving the current archive-watching CLI into a
desktop-installed import product.

## Product Goal

Ship a local-first desktop application that:

- installs through a platform-native installer
- prompts for a sources root and a libraries root on first launch
- creates a ready-to-use directory structure populated with default
  configuration assets
- runs continuously as a tray/menu-bar background app
- manages multiple active import sources at once
- supports multiple library directories under a common libraries root
- preserves the existing BODAQS artifact contract

The system must stay usable without cloud, phone, BLE, Wi-Fi, or a database
server. Future versions may add logger-connected and cloud-connected import
sources without replacing the local canonical pipeline.

## Recommended Product Shape

The product should be structured as three layers:

1. Import engine
2. Desktop shell
3. Installer/provisioner

### 1. Import Engine

The import engine owns:

- source discovery and scheduling
- input settling and claiming
- archive or external-source acquisition
- preprocessing invocation
- artifact writing
- durable import state
- source status and recent error reporting

The current `bodaqs_analysis.import_agent` module already contains most of the
single-source mechanics. The key change is to expose a reusable multi-source
supervisor API that a tray app can embed directly.

### 2. Desktop Shell

The desktop shell should be a single app instance that supervises many sources.
It should not create one long-running process per source.

The shell owns:

- first-run setup wizard
- tray/menu-bar icon and status
- source list management
- pause/resume controls
- open-folder shortcuts
- recent import/error summaries
- start-at-login behavior

The first packaged desktop UI does not need to be the tray shell itself. A
small non-tray setup/admin window is a good intermediate step because it can
exercise packaged GUI delivery on Windows, own the user-specific provisioning
workflow, and remain useful later as an "Add source / Add library" utility
even after a tray shell exists.

### 3. Installer / Provisioner

The installer should remain thin and platform-native:

- install binaries
- install default assets
- register start-at-login if desired
- launch the app

The first-run wizard inside the app should do the user-specific setup:

- choose a sources root
- choose a libraries root
- create a default source
- seed default configuration assets
- validate filesystem access

This split is recommended because installer UI logic is hard to keep consistent
across Windows, macOS, and Linux, while an in-app setup flow is portable and
easier to evolve.

## Core Runtime Model

### One App, Many Sources

The recommended runtime model is one app supervising many sources.

Benefits:

- fewer lock-contention problems
- simpler auto-start behavior
- one status surface for the user
- easier pause/resume semantics
- easier later expansion to non-filesystem sources

### One Libraries Root, Many Libraries

The app should support multiple library directories under a common root.

Recommended shape:

```text
<libraries_root>/
  rider-alice/
    runs/
    library/
  rider-ben/
    runs/
    library/
```

Each import source should target one selected library under that common root.

This suggests a future split between:

- app-level config: knows the libraries root and known libraries
- source-level config: selects one library id or library path

The current `artifacts_dir` field can remain the low-level runtime field, but
the app should eventually manage it indirectly through higher-level library
selection.

## Source Model

All source types should normalize into the same local handoff contract before
preprocessing.

Recommended source adapter classes:

- `filesystem_archive`
- `logger_serial`
- `logger_wifi`
- `cloud_storage`

Each adapter should:

1. discover or acquire one session payload
2. materialize a canonical local staging package
3. hand it to the existing import pipeline
4. commit to the selected library
5. update per-source state

This keeps preprocessing and artifact logic stable while acquisition methods
expand later.

## Filesystem Layout

Recommended app-managed roots:

```text
<sources_root>/
  Alice Enduro/
    import_source.json
    settings/
      preprocess_profile.json
      event_schema.yaml
    bike/
      bike_profile.json
    fit/
    inbox/
    done/
    failed/
    staging/
  Ben DH/
    ...

<libraries_root>/
  Alice Library/
    runs/
    library/
    syn/
  Ben Library/
    runs/
    library/
```

The product should ship with default assets for a new source:

- one default preprocess profile
- one default event schema
- one example bike profile
- one default session-note template
- one default bike setup preset

Each source also has a `fit/` directory. When FIT import is enabled in the
preprocess profile, FIT files must be fully copied into this directory before
import. The agent leaves original FIT files untouched, selects the
largest-overlap match, and treats FIT enrichment failure as a QC warning rather
than an import failure.

Each library may optionally enable data.syn.bike export output. When enabled,
new imports also write headerless data.syn.bike CSV files under the library's
`syn/` directory, plus a per-session helper text file containing the manual
data.syn.bike settings derived from the bike profile. These files are an
external-format convenience layer, not part of the canonical BODAQS artifact
contract, and old sessions are not backfilled automatically.

Each source may also enable automatic draft session notes. The source owns the
policy (`session_note.attach_on_import`) and stores a `notes/` directory with:

- exactly one valid session-note template JSON file
- exactly one valid bike setup preset JSON file

The bike profile remains the processing-facing description of the bike, while
the setup preset is the user-facing bridge from that bike profile to default
session-note values. On import, the agent creates a draft note, records
bike-profile and setup-preset provenance in `source_context`, and copies the
template into the target library under `library/session_note_templates/` so the
library manager can interpret the note even if the source folder later changes.

## Configuration Layers

### App Config

The app needs a user-level config, likely under platform-specific app-data.

Suggested responsibilities:

- app schema/version
- sources root
- libraries root
- known libraries
- known sources
- per-source draft-note attach preference
- auto-start preference
- logging preference
- UI preference

### Source Config

The existing `import_source.json` remains the source contract, but the desktop
app will likely manage it rather than asking users to edit it manually.

Likely future fields:

- `source_id`
- `source_type`
- `library_id`
- source-specific acquisition settings
- source-local note template / bike setup preset settings
- poll timing
- enabled / paused state

## Tray App Requirements

Minimum tray/menu-bar actions:

- open sources root
- open libraries root
- add source
- edit source
- pause source
- resume source
- import now
- open logs
- quit

Minimum status model:

- idle
- importing
- paused
- warning
- error

The tray shell should consume structured status from the supervisor rather than
parsing console logs.

## Cross-Platform Packaging Strategy

### Windows

Likely first target:

- packaged app bundle
- installer such as Inno Setup, WiX, or NSIS
- start-at-login registration

### macOS

Likely target:

- signed app bundle
- LaunchAgent or login item
- notarization required for polished distribution

### Linux

Likely target:

- AppImage or distro-specific packages
- autostart `.desktop` entry
- optional systemd user service later

## Major Open Issues

### 1. GUI stack

Need to choose between:

- staying in Python with a native-capable toolkit such as PySide6
- a split architecture with a small local web UI

Recommendation: PySide6-style desktop shell first, despite the larger bundle,
because tray/menu-bar support is straightforward.

### 2. Background lifetime

Need to decide whether the app runs only during logged-in desktop sessions or
whether it should support service-style headless execution.

Recommendation: logged-in desktop session only for the first product version.

### 3. Library naming and identity

Need a stable library id model that can survive display-name changes.

Recommendation: each library gets:

- `library_id`
- display name
- resolved artifact-store root path

### 4. Migration

Need migration rules for:

- app config
- source config
- default seeded assets

### 5. Adapter expansion

Need a source-adapter interface that is not filesystem-specific, even though the
initial UI will mostly create filesystem archive sources.

## Recommended Next Steps

1. Extract and stabilize the in-process multi-source supervisor API.
2. Add app-level config and provisioning utilities.
3. Add a first-launch setup flow that creates roots, libraries, and a default
   source populated with shipped defaults.
4. Build the Windows tray shell on top of the supervisor.
5. Add installer and start-at-login behavior.
6. Extend the source model for serial, Wi-Fi, and cloud acquisition.
