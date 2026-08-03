# BODAQS Firmware 0.3.0 Release Notes Draft

Status: draft  
Release date: TBD

Firmware `0.3.0` is the first firmware release designed to work directly with
the BODAQS Import Manager. The headline change is a safer local upload workflow:
completed logger sessions are packaged on the logger as ZIP archives, exposed
through an explicit upload mode, and downloadable over the local Wi-Fi API.

This release remains local-first. It does not require cloud services, a phone
bridge, BLE, or a database server.

## Highlights

- New explicit upload mode for transferring completed sessions.
- New Wi-Fi Upload API v1 for the desktop import manager.
- Completed logs are automatically wrapped into same-stem session ZIP archives.
- Station-mode mDNS discovery advertises BODAQS loggers on the local network.
- Logger identity is based on the configured logger name.
- Upload acknowledgements and optional logger-side cleanup are supported.
- The on-device menu now has a dedicated upload status screen and a cleaner
  settings submenu.
- Web UI file/config mutations are blocked while logging or upload mode is
  active.

## Compatibility

### Import Manager

This firmware is intended to pair with BODAQS Import Manager builds that support
Wi-Fi logger sources and the Wi-Fi Upload API v1.

The desktop import sequence is:

1. Discover or connect to the logger.
2. Confirm logger identity with `/api/v1/device`.
3. Confirm upload readiness with `/api/v1/status`.
4. List completed sessions with `/api/v1/sessions`.
5. Download session archives with `/api/v1/session/archive`.
6. Import the archive locally.
7. Acknowledge successful import.
8. Optionally request logger-side cleanup.

### Session Archive Contract

For normal metadata-enabled logs, the logger now creates:

```text
<session_stem>.zip
```

The archive contains exactly:

```text
<session_stem>.CSV
<session_stem>.json
```

The ZIP is written as a temporary file first:

```text
<session_stem>.zip.tmp
```

and renamed only after archive creation succeeds.

After successful ZIP creation, the loose same-stem CSV and JSON files are
removed. The ZIP is the canonical import artifact.

<session_stem>.zip files are compatible with the BODAQS Import Manager archive
pipeline.

## New Features

### Upload Mode

Upload mode is a runtime mode that must be entered before completed sessions can
be listed, downloaded, acknowledged, moved, or deleted over the Wi-Fi API.

While upload mode is active:

- logging cannot start
- only completed, closed sessions are exposed
- the upload API can list and download session archives
- web/file mutations are restricted

Upload mode can be entered from:

- the on-device upload menu/status screen
- the web UI upload panel
- the JSON API route `POST /api/v1/upload-mode/enter`
- an optional `upload_mode_toggle` button binding

Upload mode intentionally does not automatically start Wi-Fi. This keeps the
mode transport-neutral for future serial or other upload paths.

### Wi-Fi Upload API v1

The firmware now exposes a machine-readable API under `/api/v1/`.

Available routes include:

- `GET /api/v1/device`
- `GET /api/v1/status`
- `POST /api/v1/upload-mode/enter`
- `POST /api/v1/upload-mode/exit`
- `GET /api/v1/sessions`
- `GET /api/v1/session/archive?id=<session_id>`
- `POST /api/v1/session/ack`
- `POST /api/v1/session/delete`

`/api/v1/device` and `/api/v1/status` are available outside upload mode.
Session list, download, acknowledgement, and cleanup operations require upload
mode and return a conflict response when upload mode is not active.

### Logger Identity

The configured `logger_name` is now the source of truth for logger identity in
the upload API.

The API reports a filename-safe `logger_id` derived from `logger_name`:

- whitespace is trimmed
- path/filename-unsafe characters are replaced with underscores
- an empty result falls back to `BODAQS`

Session IDs are formed as:

```text
<logger_id>__<session_stem>
```

For multi-logger setups, give each logger a unique name before using the import
manager.

### Automatic Session Archives

When a log is stopped and metadata is enabled, the firmware now packages the
session CSV and JSON into a ZIP archive on the SD card.

Archive creation happens only after:

- the CSV has been closed
- the same-stem JSON metadata has been written successfully

If archive creation fails, the loose CSV and JSON are left in place and the
incomplete temporary ZIP is removed where possible.

Metadata-disabled logs do not create importable ZIP archives because the import
contract requires both CSV and JSON metadata.

### Session Discovery

The new session scanner finds completed ZIP-backed sessions on the SD card.

It:

- treats same-stem `.zip` files as canonical importable sessions
- ignores `.zip.tmp` files as incomplete
- ignores incomplete loose CSV/JSON pairs as importable sessions
- reports incomplete candidates for diagnostics
- reads acknowledgement state from the upload index

### Upload Acknowledgements

The firmware can persist acknowledgement records from the desktop import
manager.

Acknowledgements are stored in:

```text
/upload_index.ndjson
```

The latest valid record for a session wins. Corrupt lines are skipped so one bad
record does not block session listing.

Acknowledged sessions remain acknowledged after reboot.

### Optional Session Cleanup

After a session has been acknowledged, the import manager may ask the logger to:

- move the session archive to `/uploaded`
- delete the session archive

Cleanup is conservative:

- upload mode is required
- prior acknowledgement is required
- partial cleanup failures are reported per file
- loose legacy CSV/JSON companions are moved or deleted when present

The default desktop-side policy should remain conservative until users are
comfortable with the workflow.

### mDNS Discovery

In station mode, the logger advertises:

```text
_bodaqs-logger._tcp
```

on port `80`.

mDNS TXT records include:

- `api=1`
- `logger_id=<logger_id>`
- `upload_mode=true|false`
- `hostname=<hostname>`

The hostname is derived from the logger identity. The advertisement is refreshed
when upload mode changes so the desktop app can see whether the logger is ready
for upload.

AP mode does not rely on mDNS. A computer connected to the logger AP should
confirm identity through `/api/v1/device`.

### Web UI Upload Panel

The `/files` page now includes a logger upload panel showing:

- upload mode state
- Wi-Fi/network details
- importable session count
- incomplete session diagnostics
- enter/exit upload mode controls

The existing file browser remains available for human use, but mutating actions
are locked while logging or upload mode is active.

### Menu Updates

The on-device menu now includes an upload workflow:

- `Upload: ON/OFF` appears in the main menu
- selecting it opens an upload status screen
- the screen shows upload mode, Wi-Fi SSID/mode, IP address, and session counts
- Enter/Right toggles upload mode from the status screen

Lower-frequency items have been grouped under `Settings` to reduce main-menu
clutter:

- Wi-Fi mode
- log format
- reset time
- restart
- about

### Button Binding Improvements

The `web_toggle` action can now be bound to button actions other than the
original web button gesture. This makes it easier to customise physical control
layouts.

The optional `upload_mode_toggle` action is available for users who want a
hardware shortcut for upload mode.

## Behavior Changes

- Successful log close now creates a ZIP and removes loose same-stem CSV/JSON
  files.
- Upload mode blocks logging.
- Logging cannot expose a currently open session for upload.
- Session list/download/cleanup API routes require upload mode.
- Config edits and generic SD-card mutations are rejected while logging or
  upload mode is active.
- The stable API logger identity is derived from `logger_name`.
- Several main-menu items moved into the `Settings` submenu.

## Upgrade Notes

Before upgrading:

- Back up the SD card if it contains important logs.
- Make sure `logger_name` is unique for each logger you intend to use with the
  import manager.
- Keep metadata enabled if you want automatic import-manager ZIP archives.
- Review any custom button bindings if you want to use `web_toggle` or
  `upload_mode_toggle` on different gestures.

After upgrading:

- Record a short test session.
- Confirm a same-stem `.zip` is created.
- Confirm the ZIP imports successfully in BODAQS Import Manager.
- Enter upload mode and check `/api/v1/status` or use **Check Logger** in the
  import manager.

If `/upload_index.ndjson` grows unexpectedly large or the firmware reports that
the upload index is oversized, remove or compact that file on the SD card after
making sure any needed sessions have already been imported.

## Known Limitations

- Upload mode does not automatically start Wi-Fi.
- Automatic PC switching into the logger AP is not implemented.
- mDNS discovery depends on the local network allowing multicast traffic.
- AP mode may require the user to manually connect the computer to the logger
  access point before using the API.
- Only completed ZIP-backed sessions are importable through the API.
- Metadata-disabled logs do not produce importable session ZIPs.
- Cleanup is intentionally conservative and requires prior acknowledgement.

## Suggested Validation Checklist

Build checks:

- Build all active PlatformIO environments.
- Confirm firmware reports version `0.3.0` on the About screen and API.

Bench checks:

- Record and stop a short log.
- Confirm `<session_stem>.zip` appears.
- Confirm loose same-stem CSV/JSON are removed after successful archiving.
- Confirm the ZIP opens on a PC.
- Confirm the ZIP imports through BODAQS Import Manager.

Wi-Fi/API checks:

- Start Wi-Fi in station mode.
- Confirm mDNS discovery from BODAQS Import Manager.
- Enter upload mode.
- Fetch `/api/v1/device`.
- Fetch `/api/v1/status`.
- Fetch `/api/v1/sessions`.
- Download a session archive.
- Acknowledge the session.
- Reboot and confirm acknowledgement persists.

Failure checks:

- Try listing sessions outside upload mode and confirm it is rejected.
- Interrupt a download and retry.
- Leave a `.zip.tmp` file on the SD card and confirm it is ignored.
- Try cleanup before acknowledgement and confirm it is rejected.
