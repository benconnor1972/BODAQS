# BODAQS Desktop 0.2.2-beta Release Notes Draft

Status: draft  
Release date: TBD

BODAQS Desktop `0.2.2-beta` improves the local import, library-management, and
analysis workflow. It brings a more responsive Workbench, clearer adequacy and
signal-inspection tools, better Wi-Fi source handling, and automatic retention
management for processed import archives.

## Component Versions

- BODAQS Desktop bundle: `0.2.2-beta`
- BODAQS Import Manager: `0.1.8-beta`
- BODAQS Library Service: `0.1.2-beta`
- BODAQS Workbench: `0.1.2-beta`

The installed package records these values in `component_versions.json`. They
are also available from **Help → About BODAQS Desktop** in the Import Manager.

## Highlights

### Import Manager

- Wi-Fi sources now scan their local inbox as well as the logger when importing
  is enabled. This supports re-processing a run with the same source settings.
- Processed `done` and `failed` archives can now be retained automatically for
  a configurable number of days, defaulting to 30 days. A **retain forever**
  option remains available.
- Archive cleanup runs after each completed scan and also sweeps existing
  archives after upgrading. New archive retention uses the time the run entered
  `done` or `failed`; existing archives use their modified time.
- The Provision page exposes the retention setting and applies it through
  **Apply app settings**.

### BODAQS Workbench

- The Workbench now uses a clearer, more consistent visual language and heading
  structure, including rationalised context glyphs.
- The Study Set Builder automatically expands when sessions or tracks are added.
- Session selection is more flexible: Ctrl/Cmd-click and Shift-click work from
  any data column. A deliberate second click on the Session name starts a
  rename, while a quick double-click still opens analysis.
- Session renaming and multi-session note paste now update optimistically,
  making library changes feel immediate while retaining error recovery.
- Signal previews can show data modestly below zero rather than pinning the
  lower axis at zero.
- Signal Inspector now shows full signal names on hover, defaults to primary
  analysis signals, orders signals by sensor and analysis quantity, and keeps
  its controls more compact.
- Track Analysis and Lap Timing now shows the first scratch-track point on the
  initial map click, provides a visible armed state for adding scratch points,
  and improves its drawer layout and controls.
- Adequacy assessment now displays a compact per-session matrix of ticks and
  crosses beside each criterion. Required failures are red; recommended and
  optional failures are orange.

### Library Service

- Adequacy responses now expose per-session criterion results, supporting the
  Workbench’s criterion matrix.
- Description updates avoid unnecessary rereads of manifests while preserving
  the same API response shape.

## Downloads and Verification

| Platform | Package | Release status |
| --- | --- | --- |
| Windows x64 | `bodaqs-desktop-setup-0.2.2-beta.exe` | Unsigned; SHA-256 to be published after the release build. |
| macOS Apple Silicon | `BODAQS-Import-Manager-0.2.2-beta-macos-arm64.dmg` | Developer ID signed, notarized, and stapled. Download the `macos-arm64-0.2.2-beta` build artifact. |
| macOS Intel | `BODAQS-Import-Manager-0.2.2-beta-macos-x64.dmg` | Developer ID signed, notarized, and stapled. Download the `macos-x64-0.2.2-beta` build artifact. |
| Linux x64 | `BODAQS-Import-Manager-0.2.2-beta-linux-x64.tar.gz` | Keylessly signed with Sigstore. The `linux-x64-0.2.2-beta` artifact also includes its `.sigstore.json` verification bundle. |

The macOS package is a drag-to-Applications DMG. The Linux package is a
portable archive; extract it and run `bodaqs-import-manager` from the expanded
directory.

## Known Limitations

- **The Windows installer is not yet code-signed.** Windows may show an
  unknown-publisher or SmartScreen warning during installation. Verify the
  published SHA-256 before proceeding.
- macOS and Linux builds are produced from the release tag. The macOS signing
  and notarization workflow requires its configured Apple credentials; the
  Linux archive is accompanied by a Sigstore verification bundle.
- This remains a beta release; Workbench analysis workflows and the Import
  Manager configuration experience are still evolving.
- The desktop package is large because it bundles Python, scientific-analysis
  dependencies, the local Library Service, and the Workbench.

## Suggested Validation Checklist

- Install on a clean Windows user account and confirm the expected unsigned
  installer warning is understood.
- Confirm **Help → About BODAQS Desktop** shows the Desktop and three component
  versions listed above.
- Import from a Wi-Fi source with an inbox present, and confirm both the inbox
  and logger source are considered.
- Set a short processed-archive retention period in Provision, apply settings,
  and confirm completed scans clean eligible `done` and `failed` archives.
- In the Workbench, multi-select sessions from several columns; verify rename
  and quick double-click analysis behaviour from the Session column.
- Open Signal Inspector, Adequacy, and Track Analysis and Lap Timing for a
  representative local library.
