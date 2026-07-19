# BODAQS Desktop 0.1.6-alpha Release Notes

Status: draft  
Release date: 2026-07-14

BODAQS Desktop `0.1.6-alpha` is a Windows desktop bundle containing the BODAQS
Import Manager, local Library Service, bundled BODAQS Workbench web app, and an
optional demonstration library. This release is primarily about making the local
"website in a box" workflow installable and testable without requiring users to
run Python, start services manually, or own a logger before trying the
Workbench.

## Build Artifact

Installer:

```text
bodaqs-desktop-setup-0.1.6-alpha.exe
```

Location:

```text
import-manager/dist/installer/windows/bodaqs-desktop-setup-0.1.6-alpha.exe
```

SHA-256:

```text
3AEABC9CD7F0DA65640C6528FBC8BDF6AEC90439D2805BE92E986BDD4F731E5E
```

Installer size:

```text
311,179,808 bytes
```

Component versions:

- BODAQS Desktop: `0.1.6-alpha`
- BODAQS Import Manager: `0.1.6-alpha`
- BODAQS Library Service: `0.1.0-dev`
- BODAQS Workbench: `0.1.0-dev`

## Headline Changes Since 0.1.5-dev

- The desktop installer now packages the Import Manager, Library Service, and
  bundled Workbench together as `BODAQS Desktop`.
- The Import Manager can launch and stop the local BODAQS Workbench stack from
  prominent `Open BODAQS Workbench` and `Stop BODAQS Workbench` controls.
- First-run setup has been simplified with a workspace setup prompt, default
  library/default local archive source creation, and safer handling of existing
  workspaces.
- The installer can optionally install a curated `BODAQS Demo Library`, enabled
  by default, with an overwrite option for replacing an existing demo library.
- The bundled demo library contains 11 sessions, 3 study sets, 2 tracks, 4
  bookmarks, and the `Good GPS data` session filter.
- The Workbench has had substantial performance work across browser-side
  caching, memoisation, and server-side adequacy caching.
- Session management in the browser now includes guarded single-session delete,
  multi-delete, session rename, right-click actions, note copy/paste, and richer
  date/time filtering.
- The browser gained a selected-session signal preview, column resizing,
  improved table control layout, standardised row highlighting, and more compact
  panel behaviour.
- Simple Suspension Analysis now opens as a dedicated browser tab and includes
  a left-side select/filter pull-out, time-window controls, bookmark shortcuts,
  signal-inspector entry points, histogram/ECDF display modes, charted summary
  statistic glyphs, and optional millimetre displacement display.
- The Signal Inspector now uses the uPlot-based charting path, supports smoother
  window navigation, bookmark creation/rename/display, GPS context, event dots,
  responsive axes, and disambiguated signal names when duplicate motion-source
  semantics are present.

## Installer And Demo Library

The installer offers the demonstration library as an optional task. The demo
library installs into the selected workspace root alongside normal user
libraries, not into a separate hidden location.

Default installer behaviour:

- `Install demonstration library` is checked by default.
- `Overwrite existing demonstration library` is checked by default and is a
  child option of demo-library installation.
- If demo installation is enabled and overwrite is disabled, the installer will
  leave an existing demo library in place.
- Demo assets are generated from the documented recipe in
  `demo-assets/recipes/bodaqs_demo_library.recipe.json`.

## Notes And Limitations

- This installer is not code-signed. Windows may show unknown-publisher or
  SmartScreen warnings.
- The Library Service is intended to run locally and is launched by the Import
  Manager; it is not installed as a Windows service.
- The Workbench is served from the bundled local Library Service.
- The package remains large because it includes Python, scientific processing
  dependencies, the local web app, and the demonstration library.
- This is an alpha desktop bundle. It is suitable for evaluation and guided
  testing, not yet a polished stable release.

