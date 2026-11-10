# Import recordings from a mounted card

Use an existing **Local archive folder** source configured with the bike,
preprocessing profile, and target library you want. Stop the watcher and wait
for any current manual import to finish. Right-click the source, choose
**Import from mounted card...**, and select the directory containing the card's
ZIP or BDQ recordings.

Import Manager copies settled recordings into that source's local inbox and
imports completed copies through the usual pipeline. Recordings on the card
are retained. Workspace, inbox, staging, and library output must be outside the
selected card directory. Automatic logger discovery/pairing is a separate
feature and is not yet enabled.

The operation runs in the background. Its completion log reports deferred files
and acquisition errors as well as import results. Retry after card writes finish
or reconnect the card if it became unavailable. Failed/interrupted copies never
appear as importable ZIP/BDQ files. Existing successful-import deduplication
prevents a repeated acquisition from creating duplicate library sessions.

Copying and import state stays local. The source card is never used as an inbox
that the importer moves files out of. Ordinary folder and Wi-Fi source behavior
and existing configuration formats are unchanged.
