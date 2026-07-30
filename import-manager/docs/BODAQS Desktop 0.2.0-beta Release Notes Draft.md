# BODAQS Desktop 0.2.0-beta Release Notes Draft

Status: draft  
Release date: TBD

BODAQS Desktop `0.2.0-beta` is a bundled Windows beta release of the local
BODAQS workflow. It packages the Import Manager, the local Library Service, the
BODAQS Workbench web application, and an optional demonstration library so users
can import, browse, analyze, and inspect BODAQS data without manually running
Python or Node tooling.

This release remains local-first. The installed application can launch the local
Library Service and Workbench, and the Workbench can also be used against a
separately hosted read-only demo service.

## Component Versions

- BODAQS Desktop bundle: `0.2.0-beta`
- BODAQS Import Manager: `0.1.7-beta`
- BODAQS Library Service: `0.1.1-beta`
- BODAQS Workbench: `0.1.1-beta`

## Installer

Installer filename:

```text
bodaqs-desktop-setup-0.2.0-beta.exe
```

SHA-256:

```text
D47F6605771393667C364F6C0A3986A3CAE82AC5BD4357B7AF698E3B76411410
```

## Headline Changes Since 0.1.6-alpha

- The Windows package is now branded as BODAQS Desktop, reflecting that it
  bundles the Import Manager, Library Service, Workbench, and demo assets.
- The installer can optionally install a demonstration library, with an
  overwrite option for refreshing existing demo data.
- The Import Manager can launch and stop the bundled BODAQS Workbench and local
  Library Service from more prominent controls.
- First-run setup now offers a simpler default workspace path, default library,
  and default local archive source path.
- The Library Service includes read-only hosted-demo support, catalog caching,
  session and study-set refresh support, and expanded APIs used by Workbench
  analysis views.
- The Workbench Library Browser has improved table layout, filtering, column
  resizing, session rename, bulk delete, note copy/paste, signal preview, GPS
  preview, altitude preview, and clearer table controls.
- Simple Suspension Analysis now supports histogram and cumulative-frequency
  views, charted summary-statistic glyphs, normalized or millimetre displacement,
  time-window controls, bookmarks, signal-inspector entry points, and improved
  caching/performance.
- Signal Inspector now supports single-chart and multi-chart modes, synchronized
  window selection, bookmarks, event details with metrics, GPS and altitude
  context, video attachment and sync controls, and local video playback.
- Track Analysis and Lap Timing adds a GPS map workflow for track editing,
  scratch tracks, 3D track altitude profiles, segment labels, untimed segments,
  lap timing comparison, track/session search, and video-assisted trackpoint
  placement.

## Known Limitations

- The Windows installer is not yet code-signed; Windows may show unknown
  publisher or SmartScreen warnings.
- The Workbench is still a beta web UI and some analysis workflows remain
  actively evolving.
- Hosted-demo mode is read-only; write operations such as saving tracks, study
  sets, notes, bookmarks, and video attachments are disabled there.
- Video attachments currently reference local files and are intended for local
  Workbench use, not the hosted demo.
- The installer remains large because it includes Python, scientific analysis
  dependencies, the Library Service, the Workbench, and optional demo assets.

## Suggested Validation Checklist

- Install `bodaqs-desktop-setup-0.2.0-beta.exe` on a clean Windows user account.
- Confirm the optional demo library appears when selected during install.
- Confirm BODAQS Desktop launches the Import Manager.
- Confirm `Open BODAQS Workbench` starts the local Library Service and opens the
  browser UI.
- Confirm the Library Browser lists demo sessions without manually running the
  service.
- Open Simple Suspension Analysis for a single session and for a study set.
- Open Signal Inspector from the Library Browser and from analysis time-window
  controls.
- Open Track Analysis and Lap Timing and confirm demo tracks, GPS paths, altitude
  profile, and lap timing panels render.
- Stop the Workbench from the Import Manager and confirm the browser reports the
  local API as offline.
