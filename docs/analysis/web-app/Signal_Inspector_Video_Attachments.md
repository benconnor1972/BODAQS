# Signal Inspector Video Attachments

Status: draft  
Audience: web app, library service, import manager packaging

This note records the initial metadata and service shape for local video
integration in the BODAQS Signal Inspector.

## Scope

Video attachments are user-managed local resources associated with a processed
session. They are not preprocessing outputs, and the BODAQS library does not own
or manage the external video files.

The first implementation slice supports metadata persistence and safe streaming
by attachment id. Signal Inspector playback UI is planned as a later slice.

## Metadata Location

Session video attachments are stored as a session annotation:

```text
runs/<run_id>/sessions/<session_id>/annotations/session_videos.json
```

This keeps video metadata session-owned and portable with a cloud-backed
library, without mutating pipeline-facing `session/meta.json`.

## Document Shape

```json
{
  "schema": "bodaqs.session_video_attachments",
  "version": 1,
  "revision": 1,
  "run_id": "run-id",
  "session_id": "session-id",
  "session_key": "run-id::session-id",
  "attachments": [
    {
      "attachment_id": "helmet-camera",
      "display_name": "Helmet camera",
      "camera_label": "Helmet",
      "path": "",
      "workspace_relative_path": "video/ride.mp4",
      "library_relative_path": "",
      "session_relative_path": "",
      "uri": "",
      "media_type": "video/mp4",
      "enabled": true,
      "session_time_at_video_zero_s": 12.5
    }
  ],
  "created_at_utc": "2026-07-27T00:00:00Z",
  "updated_at_utc": "2026-07-27T00:00:00Z"
}
```

## Path Policy

Attachments may carry:

- `workspace_relative_path`: the preferred portable path, resolved relative to
  the configured libraries/workspace root.
- `path`: a native local path, normally absolute, used as a fallback when the
  video is outside the configured workspace root.
- `library_relative_path`: a portable path resolved relative to the library root.
- `session_relative_path`: a portable path resolved relative to the session
  artifact directory.
- `uri`: reserved for future schemes.

The Signal Inspector UI exposes a single `Video path` field. The local Browse
button stores a workspace-relative path when possible; otherwise it stores an
absolute path. Streaming resolution currently prefers `workspace_relative_path`,
then `session_relative_path`, then `library_relative_path`, then `path`.

The browser never asks the service to stream an arbitrary path. It asks for a
declared session attachment by `attachment_id`; the service resolves the stored
metadata and streams the resulting file.

## Initial Sync Guess

When the local desktop file picker selects an MP4/MOV file, the Library API
attempts to read the movie-header creation timestamp from the file. If that
timestamp and the session start time are both available, Signal Inspector
pre-fills `session_time_at_video_zero_s` as:

```text
session_started_at_unix_s - video_creation_time_unix_s
```

This is a convenience starting point only. It depends on the camera clock and
MP4 metadata being accurate, so users can still edit the offset manually.

## API Shape

```text
GET /api/v1/libraries/{library_id}/runs/{run_id}/sessions/{session_id}/videos
PUT /api/v1/libraries/{library_id}/runs/{run_id}/sessions/{session_id}/videos
GET /api/v1/libraries/{library_id}/runs/{run_id}/sessions/{session_id}/videos/{attachment_id}/stream
POST /api/v1/local/video-file-dialog
```

Read and stream endpoints are available in read-only mode. The write endpoint is
disabled in read-only mode. The native file picker endpoint is intended for the
local desktop service and is disabled in read-only hosted mode.

## Deferred Decisions

- Video UI in Signal Inspector.
- Offset nudge controls and “sync current chart time to current video frame”.
- Multi-camera display and simultaneous playback.
- Same-video-across-sessions convenience tools.
- Whether video presence should appear in the session catalog.
- Whether hosted demo builds should include explicitly bundled demo video assets.
