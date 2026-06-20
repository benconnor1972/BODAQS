# BODAQS Import Manager 0.1.4-Beta Release Notes Draft

BODAQS Import Manager `0.1.4-Beta` is a Windows beta update focused on shared
library configuration, more reliable logger imports, and smoother source
management.

## Changes Since 0.1.2-alpha

- Added a managed workspace layout with libraries stored under a `libraries`
  directory and reusable configuration stored at the BODAQS data-root level.
- Bike profiles can now be shared across sources and libraries that use the
  same data root, rather than being tied to one import source.
- Preprocess profiles can now be shared and assigned to sources from the source
  context menu.
- Event schemas can be kept in the shared `event_schemas` directory and
  referenced from shared preprocess profiles.
- Import batches detected in the same source pass can now be processed into the
  same run, instead of creating one run per session.
- `Import Now` supports an optional run-description override, and source
  settings support default or base-name-plus-index session descriptions.
- Large import batches now update the manager output during detection and
  processing, rather than waiting until the whole batch is complete.
- Logger CSV loading now repairs rare out-of-order primary timestamp rows before
  preprocessing, fixing failures caused by non-monotonic `time_s` values.
- Logger GPS imports now tolerate initial invalid GPS rows and preserve valid
  GPS points in the `gps_logger` stream.
- Activity detection now prefers GPS velocity when available, then falls back to
  wheel-motion signals, while keeping legacy preprocess profiles usable.
- data.syn.bike exports now use logger GPS data as well as FIT-style GPS column
  names.
- data.syn.bike exports now write zero-filled travel columns when one end of the
  bike has no available travel signal, so the visualizer can still open the
  export.
- Rotary-sensor workflows now support degree-based calibration materialization
  and rear wheel lookup-table inputs in either sensor millimetres or sensor
  degrees.
- Duplicating a bike profile no longer automatically assigns the duplicate to
  the current source.
- Source and library removal now distinguishes between removing an entry from
  the manager and completely deleting its files after confirmation.
- Complete source/library deletion now handles read-only Windows directories
  more reliably and only updates the manager configuration after the filesystem
  deletion succeeds.
- Fixed source table updates so `Type` and `Status` remain separate columns.
- Fixed watch-mode startup behavior.
- Improved Wi-Fi logger upload/discovery state reporting, including logger
  AP-mode workflows.
- Added the packaged application version to the Import Manager window title.

## Compatibility Notes

- Existing Import Manager configuration files should continue to load.
- Existing source-local bike and preprocess profile files remain valid when a
  source still references them.
- Existing libraries that live directly under the data root remain discoverable;
  newly created managed libraries are placed under `libraries`.
- New shared bike profiles, preprocess profiles, and event schemas are stored at
  the data-root level.
- Complete source/library deletion is destructive once confirmed and should be
  tested first on disposable data.

## Installer

The Windows installer output is:

```text
bodaqs-import-manager-setup-0.1.4-Beta.exe
```

The installer remains GUI-only; standalone command-line utilities are not
installed as separate user-facing commands.
