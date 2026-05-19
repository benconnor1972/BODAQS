# BODAQS Logger Wi-Fi Upload API v1

Status: draft

This document defines the firmware HTTP API used by the desktop import agent
to acquire completed logger sessions over Wi-Fi.

The API is deliberately mode-neutral: a logger in station mode and a logger in
access-point mode expose the same endpoints and response shapes. The desktop
app may discover or reach the logger differently in each mode, but once it can
open an HTTP connection, the transfer contract is identical.

## Goals

- require explicit upload mode before sessions can be transferred
- prevent session import while the logger is still collecting data
- identify loggers by the configured logger ID string
- identify sessions by `logger_id + session_stem`
- transfer exactly the same archive contract consumed by the import agent
- allow safe retry after interrupted downloads
- keep deletion optional and conservative

## Non-Goals

- automatic PC Wi-Fi switching into logger AP mode
- cloud synchronization
- streaming live data
- exposing partially open logs
- using file size as part of session identity

## Terms

### Logger ID

`logger_id` is the stable configured identity string for the logger.

For API v1, the firmware derives `logger_id` from the existing persisted
`logger_name` config value. Normal names are unchanged; whitespace is trimmed,
path/filename-unsafe characters are replaced with underscores, and an empty
result falls back to `BODAQS`.

Future firmware may add a separate display-name field if the project needs a
human-readable alias that can change without changing the stable logger
identity.

The API may also report interface MAC addresses for diagnostics, but MAC
addresses are not the primary app-level identity in this contract.

### Session Stem

`session_stem` is the shared basename of the session files, without extension.

Example:

```text
2026-05-16_20-15-42.CSV
2026-05-16_20-15-42.json
```

The `session_stem` is:

```text
2026-05-16_20-15-42
```

### Session ID

`session_id` is:

```text
<logger_id>__<session_stem>
```

The separator is the literal string `__`.

Clients must treat `session_id` as an opaque string and URL-encode it when
placing it in query parameters. Firmware should reject or escape path
separators in configured logger IDs so session IDs remain safe to display and
persist.

## Upload Mode

The API is gated by explicit upload mode.

When upload mode is inactive:

- the logger may record sessions normally
- session list/download/delete endpoints return `409`
- discovery and status endpoints may still respond if the web server is active

When upload mode is active:

- logging cannot start
- any active log must already be closed
- the web/API server may serve completed sessions
- session list/download endpoints expose only complete importable sessions

The user enters upload mode explicitly from the logger UI, button/menu action,
or web UI. The desktop import agent does not automatically force the logger
into upload mode as part of normal discovery.

The built-in HTML file browser exposes human-facing upload mode controls at
`/files`:

- `POST /upload-mode/enter`
- `POST /upload-mode/exit`

These are browser convenience routes that redirect back to `/files`. Machine
clients should use the JSON API routes under `/api/v1/upload-mode/*`.

While logging or upload mode is active, the generic file browser disables and
rejects manual SD-card mutation routes such as upload, mkdir, rmdir, and
delete. Downloads remain available, and upload-session cleanup should go
through `POST /api/v1/session/delete` after acknowledgement.

## Archive Contract

The logger should create a session archive when a log is closed and the
same-stem JSON metadata has been written.

For each completed session:

```text
<session_stem>.CSV
<session_stem>.json
<session_stem>.zip
```

The archive must contain exactly two root-level files:

```text
<session_stem>.CSV
<session_stem>.json
```

The CSV and JSON filenames inside the archive must have the same basename.

The archive should be generated only after both source files have been closed.
If archive generation fails, the session may still be listed with
`archive_ready: false`, but it must not be downloadable as a completed archive.

## Response Envelope

JSON responses should include:

```json
{
  "schema": "bodaqs.logger.<kind>",
  "api_version": 1
}
```

Errors should use JSON where possible:

```json
{
  "schema": "bodaqs.logger.error",
  "api_version": 1,
  "error": "upload_mode_required",
  "message": "Upload mode is required for this endpoint."
}
```

Recommended status codes:

- `200`: success
- `400`: missing or invalid request argument
- `404`: unknown session
- `409`: logger state blocks the operation
- `500`: internal firmware/storage error
- `503`: storage unavailable

## Endpoints

### `GET /api/v1/device`

Returns logger identity and capabilities.

Available outside upload mode.

Example response:

```json
{
  "schema": "bodaqs.logger.device",
  "api_version": 1,
  "logger_id": "Prototype E",
  "display_name": "Prototype E",
  "firmware_version": "0.2.0",
  "hostname": "bodaqs-prototype-e",
  "wifi_mode": "station",
  "sta_mac": "AA:BB:CC:DD:EE:FF",
  "ap_mac": "AA:BB:CC:DD:EE:00",
  "capabilities": [
    "upload_mode",
    "session_archive_zip",
    "session_ack",
    "session_delete",
    "mdns_discovery"
  ]
}
```

In station mode, reachable loggers may advertise mDNS service
`_bodaqs-logger._tcp` on port `80` with TXT records including `api=1`,
`logger_id`, `upload_mode`, and `hostname`. AP mode does not require mDNS; the
PC confirms identity through this endpoint after connecting.

### `GET /api/v1/status`

Returns state relevant to import readiness.

Available outside upload mode.

Example response:

```json
{
  "schema": "bodaqs.logger.status",
  "api_version": 1,
  "logger_id": "Prototype E",
  "upload_mode": true,
  "logging_active": false,
  "storage_available": true,
  "wifi_mode": "access_point",
  "network_up": true,
  "ip": "192.168.4.1",
  "session_count": 8,
  "importable_session_count": 8
}
```

### `POST /api/v1/upload-mode/enter`

Requests upload mode.

This endpoint is optional for v1 if upload mode is controlled only on-device.
If implemented, it must not silently interrupt an active logging session.

Success response:

```json
{
  "schema": "bodaqs.logger.upload_mode",
  "api_version": 1,
  "logger_id": "Prototype E",
  "upload_mode": true
}
```

If logging is active and cannot be cleanly closed:

```text
409 Conflict
```

### `POST /api/v1/upload-mode/exit`

Exits upload mode.

Success response:

```json
{
  "schema": "bodaqs.logger.upload_mode",
  "api_version": 1,
  "logger_id": "Prototype E",
  "upload_mode": false
}
```

### `GET /api/v1/sessions`

Lists completed sessions.

Requires upload mode.

A session is importable only when:

- CSV exists
- same-stem JSON exists
- same-stem ZIP exists
- ZIP was generated after the CSV and JSON were closed

Example response:

```json
{
  "schema": "bodaqs.logger.sessions",
  "api_version": 1,
  "logger_id": "Prototype E",
  "sessions": [
    {
      "session_id": "Prototype E__2026-05-16_20-15-42",
      "session_stem": "2026-05-16_20-15-42",
      "csv_path": "/logs/2026-05-16_20-15-42.CSV",
      "json_path": "/logs/2026-05-16_20-15-42.json",
      "archive_path": "/logs/2026-05-16_20-15-42.zip",
      "archive_ready": true,
      "uploaded": false,
      "acknowledged": false
    }
  ]
}
```

### `GET /api/v1/session/archive?id=<session_id>`

Downloads the session archive.

Requires upload mode.

Response:

```text
Content-Type: application/zip
Content-Disposition: attachment; filename="<session_id>.zip"
```

The import agent downloads to a `.part` file first, validates the completed zip,
and only then moves the archive into the local import inbox/staging area.

### `POST /api/v1/session/ack`

Acknowledges that the PC has successfully imported a session.

Requires upload mode.

Request JSON:

```json
{
  "session_id": "Prototype E__2026-05-16_20-15-42",
  "status": "imported",
  "library_id": "default-library",
  "run_id": "run_2026-05-16T19-23-26_AWST",
  "imported_at": "2026-05-16T19:23:26+08:00"
}
```

Firmware should persist acknowledgement in a small upload index or sidecar so
the logger can report which sessions have already been handled.

### `POST /api/v1/session/delete`

Deletes or archives a completed session on the logger.

Requires upload mode.

Default policy:

- deletion is disabled unless explicitly requested by the user/source setting
- firmware should reject deletion unless the session has been acknowledged
- prefer move-to-uploaded/trash over immediate permanent deletion where storage
  layout permits

Request JSON:

```json
{
  "session_id": "Prototype E__2026-05-16_20-15-42",
  "mode": "move_to_uploaded"
}
```

Allowed `mode` values:

- `move_to_uploaded`
- `delete`

Successful cleanup response:

```json
{
  "schema": "bodaqs.logger.session_delete",
  "api_version": 1,
  "logger_id": "Prototype E",
  "session_id": "Prototype E__2026-05-16_20-15-42",
  "acknowledged": true,
  "mode": "move_to_uploaded",
  "ok": true,
  "files": {
    "csv": {
      "ok": true,
      "path": "/2026-05-16_20-15-42.CSV",
      "target_path": "/uploaded/2026-05-16_20-15-42.CSV"
    },
    "json": {
      "ok": true,
      "path": "/2026-05-16_20-15-42.json",
      "target_path": "/uploaded/2026-05-16_20-15-42.json"
    },
    "archive": {
      "ok": true,
      "path": "/2026-05-16_20-15-42.zip",
      "target_path": "/uploaded/2026-05-16_20-15-42.zip"
    }
  }
}
```

Partial cleanup failures return a non-`200` response with the same file result
shape and an `error` string. Clients should treat partial cleanup as requiring
manual review.

## Desktop Import Agent Policy

The import agent should use this sequence:

1. Discover or connect to a logger.
2. Call `GET /api/v1/device`.
3. Match/store `logger_id`.
4. Call `GET /api/v1/status`.
5. If `upload_mode` is false, report "Upload mode required".
6. Call `GET /api/v1/sessions`.
7. Skip sessions already imported locally.
8. Download each new archive to `.part`.
9. Validate the zip contract.
10. Import using the existing archive pipeline.
11. Acknowledge successful imports.
12. Optionally request logger cleanup if enabled.

The desktop app should not require the user to select AP mode vs station mode.
It should simply report whether a logger is reachable and whether upload mode
is active.
