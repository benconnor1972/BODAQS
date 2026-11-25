# USB logger identity v1

The A8 USB development firmware writes `/.bodaqs-logger.json` while it still
owns the filesystem, before exporting the card. Import Manager discovers mounted
volumes by this marker, rather than drive letter, volume label, or logger name.

```json
{
  "schema": "bodaqs.logger.usb",
  "version": 1,
  "device_id": "esp32s3-1cdbd4bc5e2c",
  "logger_id": "A8",
  "display_name": "My logger",
  "recordings_path": "."
}
```

`device_id` is `esp32s3-` plus the twelve lowercase hexadecimal digits of the
factory MAC. It stays stable when the configurable `logger_id` or display name
changes. The marker identifies the logger that last exported the card; it is
not authenticated identity. Duplicated identities on simultaneously mounted
volumes are rejected instead of choosing one.

Version must be the integer 1. Text fields must be nonempty, contain no control
characters, and be at most 255 characters. The marker must be a regular file,
at most 4096 bytes. `recordings_path` is a POSIX relative directory within the
volume; `.` means its root. Absolute paths, `..`, backslashes, colons, symbolic
links in the path, and unavailable directories are rejected. Unknown fields
are ignored. Discovery does not mount or modify any volume.

Pairings live on the computer in `usb_logger_pairings.json`, beside Import
Manager's application configuration. Schema `bodaqs.usb_pairings`, integer
version 1, maps `sources` from device ID to the absolute path of an existing
local-source configuration. That source supplies bike, profile, inbox, and
library settings. Mount paths are not persisted as identity. Moving a source
configuration requires pairing it again.

The Import Manager's **Discover / pair USB loggers...** action offers enabled
local archive sources. Missing Wi-Fi source files do not prevent USB pairing.
A missing local source configuration is reported as a pairing error; repair its
path or disable that source and retry. Manual discovery also reports when no
logger is found. Pairing failures leave subsequent discovery available.

Pairing and acquisition reject workspace, inbox, staging, library, state, and
other output paths anywhere on the mounted card, including siblings of the
recording directory. Manual acquisition uses the enclosing mounted volume as
the same boundary.

## Upload control additions

The development firmware retains `upload_mode` and adds `exit_pending`,
`usb_state`, and `transfer_status` to upload status/control responses. The
existing `/api/v1/upload-mode/status` endpoint remains available while the card
is shared. `usb_state` is `normal`, `upload`, `waiting`, `shared`,
`disconnecting`, `reclaiming`, `ejected`, or `error`; normal builds report
`disabled`. Existing entry/exit controls remain compatible, but exit can return
HTTP 202 while pending. `upload_mode` remains true until local reclaim succeeds.

`POST /api/v1/upload-mode/cancel-exit` returns 200 when cancelled, or 409 when
there is no cancellable exit. `POST /api/v1/upload-mode/retry-storage` returns
202 when an explicit error-state retry is accepted, or 409 otherwise. Poll status
to observe completion. SD-based Wi-Fi operations are paused during ownership
handoff and external ownership; status and mode controls remain available.

Exit waits at least three seconds and for one second without reads or writes.
Continuous traffic can postpone exit indefinitely; cancellation resumes sharing.
The delay cannot flush unseen computer write caches. Finishing copies and
optionally ejecting on the computer reduces risk but is not required by the UI.
