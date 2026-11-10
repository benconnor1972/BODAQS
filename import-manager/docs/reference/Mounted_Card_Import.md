# Import recordings from a mounted card

Use an existing **Local archive folder** source configured with the bike,
preprocessing profile, and target library you want. Stop the watcher and wait
for any current manual import to finish. Right-click the source, choose
**Import from mounted card...**, and select the directory containing the card's
ZIP or BDQ recordings.

Import Manager copies settled recordings into that source's local inbox and
imports completed copies through the usual pipeline. Recordings on the card
are retained. Workspace, inbox, staging, and library output must be outside the
selected card directory.

Import Manager also checks mounted volumes for the
[USB logger identity marker](../../../docs/interchange/USB_Logger_Identity_v1.md).
On first discovery, choose an existing local archive source to pair with that
logger. Its bike, profile, inbox, and library settings apply to subsequent USB
imports. The pairing remembers the logger's immutable identity across changes
to its display name or drive letter. Use **Discover / pair USB loggers...** in a
local source's context menu to discover or change a pairing manually.

Start the watcher to enable background acquisition from paired loggers. Stopping
the watcher stops automatic acquisition; pausing a source skips its paired
logger. A copy already underway finishes before access to the library is handed
to the watcher. Completed local copies enter the usual watched import pipeline.
Reconnects and unfinished copies are retried; unchanged completed acquisitions
are skipped. Successful-import deduplication still applies. Discovery problems
and copy errors appear in the activity log. Unmarked cards use the manual import
above. Ambiguous duplicate identities are not imported automatically.

The operation runs in the background. Its completion log reports deferred files
and acquisition errors as well as import results. Retry after card writes finish
or reconnect the card if it became unavailable. Failed/interrupted copies never
appear as importable ZIP/BDQ files. Existing successful-import deduplication
prevents a repeated acquisition from creating duplicate library sessions.
Acquisition copies all eligible recordings; the source's per-scan limit applies
to subsequent import processing. Existing pending copies stay ahead of newly
reacquired duplicates so repeated manual operations can make progress.

Copying and import state stays local. The source card is never used as an inbox
that the importer moves files out of. Ordinary folder and Wi-Fi source behavior
and existing configuration formats are unchanged.
