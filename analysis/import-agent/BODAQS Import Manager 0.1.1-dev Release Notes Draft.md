# BODAQS Import Manager 0.1.1-dev Release Notes Draft

Status: draft  
Release date: TBD

BODAQS Import Manager `0.1.1-dev` is the current packaged desktop build of the
local BODAQS import workflow. It is designed to let users create local
libraries, configure import sources, watch for completed logger sessions, run
the existing BODAQS preprocessing pipeline, and write processed artifacts
without running Python or opening notebooks.

This is a Windows-first development release. It remains local-first: it does
not require cloud services, a phone bridge, BLE, or a database server.

## Highlights

- New Windows installer for BODAQS Import Manager.
- New windowed manager UI for creating and managing libraries and import
  sources.
- Local archive-folder import sources for completed logger ZIP files.
- Wi-Fi logger import sources using the BODAQS Wi-Fi Upload API v1.
- mDNS discovery for station-mode BODAQS loggers where the local network
  allows it.
- Multi-source and multi-library management from one app.
- Background watch mode with Windows tray integration.
- Start-at-login support for the installed manager.
- Per-source bike, settings, FIT, and note-template folders.
- Optional FIT enrichment when enabled by the preprocess profile.
- Optional draft session-note creation on import.
- Optional data.syn.bike export generation per library.
- Branded Windows app, tray, taskbar, and installer icons.

## Compatibility

### Operating System

This build targets Windows desktop/laptop use.

macOS packaging is planned separately. Linux packaging is not part of this
release.

### Firmware

Wi-Fi logger sources are intended to pair with BODAQS firmware `0.3.0` or later,
using the Wi-Fi Upload API v1.

For Wi-Fi import, the logger must:

- be reachable on the local network
- expose `/api/v1/` upload routes
- have completed ZIP-backed sessions
- be in explicit upload mode before session transfer

Local archive-folder sources can import compatible logger ZIP files without a
network connection.

### Session Archive Contract

The import manager expects one completed logger session per ZIP archive.

Each archive should contain a same-stem CSV and JSON pair:

```text
<session_stem>.CSV
<session_stem>.json
```

The files inside the archive do not need fixed names, but the CSV and JSON must
have the same stem.

## Installer And Packaging

The Windows installer output is named:

```text
bodaqs-import-manager-setup-0.1.1-dev.exe
```

The installer includes:

- the windowed Import Manager app
- the CLI import/watch tool as a support utility
- bundled default import assets
- Windows icon assets
- Start Menu integration
- optional desktop shortcut support

Installed-mode app configuration is stored in per-user app data rather than in
the installation directory. This keeps user state separate from installed
program files and makes upgrades/uninstalls safer.

The installer is currently unsigned. Users may see Windows "unknown publisher"
or SmartScreen warnings until code signing is added and reputation builds.

## Manager UI

The Import Manager window provides two main workflows:

- `Provision`: create libraries and sources.
- `Manager`: operate existing libraries and sources.

The manager can:

- create additional libraries under a common libraries root
- create additional sources under a common sources root
- target multiple sources at one central library
- remove a source from the managed configuration without deleting any source or
  library files
- enable/disable sources directly from the source table
- toggle draft-note creation directly from the source table
- toggle data.syn.bike exports directly from the library table
- run one-shot imports
- start and stop background watching
- open source, library, and logger-related locations from the UI

## Source Types

### Local Archive Folder

Local archive sources watch a source `inbox/` directory for completed ZIP files.

On successful import:

- processed artifacts are written to the selected library
- the source archive is moved to `done/`

On failed import:

- the source archive is moved to `failed/`
- the manager records the failure in import state and UI status

The source folder contains:

```text
<source>/
  import_source.json
  bike/
  settings/
  notes/
  fit/
  inbox/
  done/
  failed/
  staging/
```

### Wi-Fi Logger

Wi-Fi sources can download completed session archives directly from a BODAQS
logger over the local network.

The workflow is:

1. Confirm logger identity with `/api/v1/device`.
2. Confirm upload readiness with `/api/v1/status`.
3. Discover completed sessions with `/api/v1/sessions`.
4. Download an archive to a local temporary `.part` file.
5. Validate the downloaded ZIP before import.
6. Import through the same local archive pipeline.
7. Acknowledge successful import to the logger.
8. Optionally request logger-side cleanup.

Upload mode is always required for Wi-Fi session transfer. If the logger is
reachable but not in upload mode, the manager treats that as a normal waiting
state rather than an import failure.

Remote cleanup policies are:

- keep remote files
- move acknowledged sessions to the logger's uploaded area
- delete acknowledged sessions

The default should remain conservative until the user trusts the workflow.

## Logger Discovery

Station-mode logger discovery uses mDNS service:

```text
_bodaqs-logger._tcp
```

The logger ID remains the stable identity. Discovered addresses are treated as
reachability hints and are verified with `/api/v1/device` before importing.

Manual logger addresses remain supported for:

- AP-mode workflows
- networks that block mDNS
- VPN/firewall/guest-network cases
- troubleshooting

## Libraries

Each library contains processed BODAQS artifacts and library metadata:

```text
<library>/
  runs/
  library/
  syn/
  library_definition.json
```

Multiple libraries can live under one libraries root. This supports workflows
such as one library per rider, logger, bike, or test program.

## Processing Pipeline

Imports reuse the existing BODAQS preprocessing and artifact-writing contract.

The manager:

- loads the source bike profile from `bike/`
- loads preprocess settings from `settings/`
- loads an event schema from `settings/` when available
- runs preprocessing
- runs event detection and metrics when an event schema is available
- writes processed run/session artifacts to the target library

The active source folders use an "exactly one valid file" rule:

- `bike/` should contain exactly one valid bike profile
- `settings/` should contain exactly one valid preprocess profile
- `settings/` may contain exactly one valid event schema

## FIT Enrichment

Each source has a `fit/` directory.

When FIT enrichment is enabled in the preprocess profile:

- FIT files are read from the source `fit/` directory
- files should be fully copied before import
- FIT files are not moved or deleted by the manager
- the largest-overlap matching FIT file is preferred
- parse failures or ambiguity do not block the import
- failed FIT enrichment is recorded as a quality-control note/warning

## Draft Session Notes

Each source can optionally attach a draft session note to incoming sessions.

The source owns:

- a session-note template
- a bike setup preset
- an `Attach Note` setting

Notes created during import are marked as draft so users can distinguish
automatically generated setup notes from notes intentionally created or edited
later.

The import process records note/template/setup provenance in the run manifest
and copies needed note-template information into the target library so notes
remain interpretable if the source folder changes later.

## data.syn.bike Exports

Each library can opt in to data.syn.bike export generation.

When enabled before import, new sessions produce files under:

```text
<library>/syn/
```

Outputs include:

- headerless data.syn.bike CSV export files
- per-session helper text files with manual data.syn.bike settings
- an export manifest

The helper text includes values derived from the bike profile, including travel
and normalization-related settings. Raw data can be scaled from the logger's
calibrated raw range to a full ADC-count range for data.syn.bike compatibility.

Old sessions are not backfilled automatically when the library setting is
enabled later.

## Background Operation

The manager can run in watch mode and continue operating from the Windows tray.

Supported behavior:

- closing the window hides to tray when tray support is active
- tray menu can reopen the manager or quit the app
- start-at-login can launch the manager in installed mode
- startup launches can start watch mode automatically
- offline Wi-Fi sources report waiting/error status without modal error storms

## User-Visible Behavior Changes From Notebook/CLI Workflows

- Users no longer need to edit JSON files for normal source/library setup.
- App-level configuration is managed automatically.
- Source bike/settings/note assets are copied into each source folder.
- A source can be removed from the manager without deleting files.
- Wi-Fi downloads are normalized into the same archive-import path as local
  files.
- Event detection and metrics run automatically when an event schema is
  available.
- Logger timezone is not requested in normal setup; session timing comes from
  log metadata.

## Known Limitations

- This is a `dev` release, not a polished public stable release.
- Windows packaging is implemented first; macOS and Linux packages are not yet
  available.
- The Windows installer is not yet code-signed.
- The installer bundle is relatively large because it includes Python runtime
  and scientific dependencies.
- Wi-Fi imports require the logger to be in upload mode.
- Automatic PC switching into logger AP mode is not implemented.
- mDNS discovery depends on local network multicast behavior and may be blocked
  by firewalls, VPNs, guest Wi-Fi, AP isolation, or router configuration.
- Manual logger address entry is still needed for AP mode and troublesome
  networks.
- Old imported sessions are not automatically backfilled for data.syn.bike
  exports or draft notes.
- FIT enrichment is best-effort and intentionally does not block import.
- Remote cleanup should be used conservatively until tested with real logger
  data.

## Suggested Validation Checklist

Installer checks:

- Install BODAQS Import Manager on a clean Windows user account.
- Confirm the Start Menu shortcut launches the manager.
- Confirm the app title and taskbar icon use BODAQS Import Manager branding.
- Confirm the app config is created under per-user app data in installed mode.
- Confirm uninstall behavior when the manager is closed.

Local archive checks:

- Create a library and local archive source.
- Replace the seeded bike profile with a real target-bike profile.
- Copy a completed session ZIP into `inbox/`.
- Run `Import Now`.
- Confirm the archive moves to `done/`.
- Confirm processed artifacts appear in the target library `runs/` directory.

Wi-Fi logger checks:

- Use firmware `0.3.0` or later.
- Put the logger and computer on the same local network.
- Put the logger into upload mode.
- Discover the logger with mDNS, or enter a manual address.
- Use `Check Logger`.
- Import a completed session.
- Confirm the manager acknowledges the import to the logger.
- Test cleanup mode only after confirming the local library artifacts.

Optional-output checks:

- Enable `Syn Export` on a library before import.
- Confirm data.syn.bike CSV/helper files appear under `syn/`.
- Enable `Attach Note` on a source before import.
- Confirm a draft session note appears in the target library.
- Add a fully copied FIT file to the source `fit/` directory and confirm FIT
  enrichment succeeds or records a non-blocking warning.

Failure checks:

- Try importing a malformed ZIP and confirm it moves to `failed/`.
- Try Wi-Fi import when the logger is reachable but not in upload mode.
- Try Wi-Fi discovery on a network where mDNS is blocked and confirm manual
  address entry still works.
- Interrupt a Wi-Fi download and confirm partial `.part` files are not imported.
- Remove a source from the manager and confirm source/library files remain on
  disk.
