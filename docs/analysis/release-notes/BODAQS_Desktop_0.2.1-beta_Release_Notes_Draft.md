# BODAQS Desktop 0.2.1-beta Release Notes Draft

Status: draft  
Release date: TBD

BODAQS Desktop `0.2.1-beta` is a maintenance beta release of the bundled
Windows BODAQS workflow. It packages the Import Manager, local Library Service,
and BODAQS Workbench for local-first importing, library management, analysis,
signal inspection, GPS, and video-assisted workflows.

## Component Versions

- BODAQS Desktop bundle: `0.2.1-beta`
- BODAQS Import Manager: `0.1.7-beta`
- BODAQS Library Service: `0.1.1-beta`
- BODAQS Workbench: `0.1.1-beta`

## Installer

Installer filename:

```text
bodaqs-desktop-setup-0.2.1-beta.exe
```

SHA-256:

```text
03528A440D02BA0A2D8E9DCA9AA3A1D9FAE4BF6635E5B3BCFD54D6E130D9ABE5
```

This desktop build does not include demonstration-library assets. The hosted
demo remains available separately at `https://demo.bodaqs.net/`.

## Changes Since 0.2.0-beta

- Signal Inspector navigator interactions are more reliable at short time
  windows. Compact navigator selections retain generous invisible hit areas for
  moving and resizing, while the pointer indicates the available gesture.
- Dragging the navigator now pans the main signal chart continuously rather
  than waiting for pointer release.
- Signal-window navigation now keeps a symmetric data buffer around the active
  time window, so users can drag in either direction without an immediate
  reload.
- Signal Inspector coalesces navigation fetches so a long drag does not queue
  one expensive time-series request for every pointer movement.
- The updated Workbench build is included in both the local desktop service and
  the hosted-demo deployment artifact.

## Known Limitations

- The Windows installer is not yet code-signed; Windows may show unknown
  publisher or SmartScreen warnings.
- The Workbench remains a beta interface. Signal windows that move beyond the
  available local buffer still require a Library Service fetch, although the
  interface now avoids request backlogs.
- Hosted-demo mode is read-only. Saving tracks, study sets, notes, bookmarks,
  video attachments, and other library changes is unavailable there.
- Video attachments refer to local files and are intended for local Workbench
  use rather than the hosted demo.

## Suggested Validation

- Install `bodaqs-desktop-setup-0.2.1-beta.exe` on a clean Windows user
  account.
- Start BODAQS Workbench from the Import Manager and confirm the Library
  Browser is populated.
- Open Signal Inspector and drag a short navigator window forwards and
  backwards across a session.
- Confirm the main chart follows the drag while buffered data is available and
  recovers without a prolonged request backlog when new data is required.
- Confirm Simple Suspension Analysis and Track Analysis and Lap Timing still
  open from the Analysis Launcher.
