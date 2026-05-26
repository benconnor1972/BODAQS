# BODAQS Import Manager 0.1.1-alpha Release Notes Draft

Status: draft  
Release date: TBD

BODAQS Import Manager `0.1.1-alpha` is a Windows alpha build of the local
BODAQS import workflow. It focuses on the windowed manager experience: creating
libraries and sources, watching for completed logger sessions, importing local
archive and Wi-Fi logger sources, running the BODAQS preprocessing pipeline, and
writing processed library artifacts without requiring users to run Python.

This release remains local-first. It does not require cloud services, a phone
bridge, BLE, or a database server.

## Headline Changes Since 0.1.0-dev

- The Windows installer now ships the GUI Import Manager only; the separate CLI
  utility is no longer included in the GUI installer package.
- The installer version and output filename are now `0.1.1-alpha`.
- The Manager screen has been simplified around context menus rather than rows
  of action buttons.
- Libraries can be renamed from the Manager screen without changing their
  library IDs or artifact directories.
- Sources can be renamed from the Manager screen without changing their source
  IDs, source roots, or target libraries.
- Source table wording now uses `Target Library` to make the library
  relationship clearer.
- Source context menus now include validation, bike editing, target-library
  changes, details, rename, and removal actions.
- Wi-Fi source provisioning now treats fixed logger addresses as an explicit
  opt-in, so discovered IP addresses are not automatically remembered.
- Existing Wi-Fi source connection settings can be viewed and edited from the
  source context menu.
- Library context menus now include rename and details actions.
- The manager now prevents multiple running instances for the same app
  configuration.
- Bike-profile and note-template editing has been expanded with builder-style
  UI support, including LUT editing and draft note profile generation.

## Installer And Packaging

The Windows installer output is named:

```text
bodaqs-import-manager-setup-0.1.1-alpha.exe
```

The installer includes:

- the windowed BODAQS Import Manager app
- bundled default import assets
- Windows icon assets
- Start Menu integration
- optional desktop shortcut support

The installer no longer includes the standalone `bodaqs-import.exe` CLI utility.
This reduces the package and installed size by avoiding a second bundled Python
runtime and scientific dependency stack. Users who need the CLI can still build
or receive it as a separate artifact.

Installed-mode app configuration is stored in per-user app data rather than in
the installation directory.

The installer is currently unsigned. Users may see Windows "unknown publisher"
or SmartScreen warnings until code signing is added and reputation builds.

## Manager UI

The Import Manager window provides two main workflows:

- `Provision`: create libraries and sources.
- `Manager`: operate existing libraries and sources.

Manager table changes in this release:

- The library table shows `Library Name` and `Syn Export`.
- Library details are available from the library row context menu.
- The source table shows enabled state, source name, source type, status,
  target library, bike name, and attach-note state.
- Source details are available from the source row context menu.
- Source validation has moved from the main button row into the source context
  menu.
- Wi-Fi source actions appear only for Wi-Fi sources.
- Wi-Fi source settings can be edited after provisioning, including logger ID,
  fixed-address mode, fixed address, cleanup policy, and timeouts.

Rename behavior is display-name-only. Renaming a library or source does not
change IDs, paths, import history, or processed artifact locations.

Only one manager instance can run at a time for a given app configuration. If a
second copy is launched, it exits with an already-running message rather than
starting another watcher or tray icon.

## Source And Profile Builders

This alpha includes the current bike-profile and note-template builder work:

- bike profile creation/editing from a guided form
- display-name-driven profile IDs
- front suspension vertical-wheel transform generation from steering head angle
- rear shock-to-wheel LUT editing
- source-local note profile/template editing
- note field defaults
- custom note fields when enabled by the field catalog
- create-from workflows for copying profiles/templates from existing sources

The generated JSON remains compatible with the existing import pipeline and
library artifact contracts.

## Import Capabilities

This release keeps the existing Import Manager capabilities:

- local archive-folder sources for completed logger ZIP files
- Wi-Fi logger sources using the BODAQS Wi-Fi Upload API v1
- mDNS discovery where the local network allows it
- optional fixed logger addresses for networks where mDNS is unavailable or
  unreliable
- multi-source and multi-library management
- background watch mode with Windows tray integration
- start-at-login support
- optional FIT enrichment when enabled by the preprocess profile
- optional draft session-note creation on import
- optional data.syn.bike export generation per library

Wi-Fi logger sources are intended to pair with BODAQS firmware `0.3.0` or later.
Upload mode is required before Wi-Fi session transfer.

## Compatibility Notes

- This is an alpha release, not a polished public stable release.
- Existing app configuration should continue to load.
- Running multiple manager instances with the same app configuration is now
  blocked to avoid duplicate watchers and competing config edits.
- Removing the CLI from the GUI installer does not change the manager app's
  import behavior.
- Existing source and library IDs remain stable when display names are renamed.
- Existing source folders and library folders are not deleted by rename or
  remove-from-manager actions.
- Existing Wi-Fi sources with remembered addresses continue to work, and those
  addresses can now be cleared or updated from the manager.
- macOS packaging is planned separately.

## Known Limitations

- The installer is not yet code-signed.
- The package remains relatively large because the manager includes Python,
  pandas, NumPy, SciPy, parquet support, Tk, tray support, and network discovery
  dependencies.
- The GUI installer no longer installs a command-line import utility.
- mDNS discovery may be blocked by firewall, VPN, guest Wi-Fi, AP isolation, or
  router multicast settings.
- FIT enrichment is best-effort and does not block otherwise successful import.
- data.syn.bike helper files still require manual settings entry in
  data.syn.bike.

## Suggested Validation Checklist

- Install `bodaqs-import-manager-setup-0.1.1-alpha.exe` on a clean Windows user
  account.
- Confirm the Start Menu shortcut launches BODAQS Import Manager.
- Confirm no separate CLI folder or `bodaqs-import.exe` is installed by the GUI
  installer.
- Create a library and local archive source.
- Rename the library and confirm only its display name changes.
- Rename the source and confirm only its display name changes.
- Validate a source from the source context menu.
- Change a source target library from the source context menu.
- Open source and library details dialogs from their context menus.
- Provision a Wi-Fi source from discovery with fixed address off and confirm no
  address is written to the source config.
- Edit a Wi-Fi source, enable fixed address, verify the logger, save, then clear
  fixed address again.
- Edit a bike profile and note profile from the source workflow.
- Launch the manager a second time and confirm it reports that the manager is
  already running rather than opening a duplicate instance.
- Import a completed logger ZIP and confirm artifacts appear in the target
  library.
- If testing Wi-Fi, use firmware `0.3.0` or later, put the logger in upload
  mode, and confirm discovery/import behavior.
