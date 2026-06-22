# Import Manager Documentation Audit

Status: draft  
Date: 2026-06-21  
Scope: `bodocs/src/content/docs/software-guide/setup-import-manager.mdx`, `bodocs/src/content/docs/user-guide/import-manager-user-guide.mdx`, and `bodocs/src/content/docs/user-guide/import-manager-folder-structure-appendix.md`  
Import Manager context: current `import-manager` and `analysis` trees after the 0.1.4-Beta work.

This note identifies changes needed before editing the website content. It is intentionally an audit/planning document, not an edit of the published docs.

## Source Docs Reviewed

- `bodocs/src/content/docs/software-guide/setup-import-manager.mdx`
- `bodocs/src/content/docs/user-guide/import-manager-user-guide.mdx`
- `bodocs/src/content/docs/user-guide/import-manager-folder-structure-appendix.md`

## Code And Local Context Checked

- Import Manager UI and provisioning: `import-manager/bodaqs_import_manager/import_agent_setup.py`, `import-manager/bodaqs_import_manager/import_agent_provisioning.py`
- Import/preprocess execution: `analysis/bodaqs_analysis/import_agent.py`, `analysis/bodaqs_analysis/preprocess_profile.py`, `analysis/bodaqs_analysis/io_logger.py`
- data.syn.bike exporter: `analysis/bodaqs_analysis/exporters/data_syn_bike.py`
- Library shape note: `docs/analysis/Library_Shape_Run_Session_Bike_Profile_Changes.md`
- Release notes draft: `import-manager/docs/BODAQS Import Manager 0.1.4-Beta Release Notes Draft.md`
- Existing screenshot assets in `bodocs/src/assets/pics/`

## Summary

The Import Manager setup guide, user guide, and folder-structure appendix are now materially out of date. The largest conceptual drift is that the docs still describe a mostly source-local model:

- each source has its own bike profile folder;
- each source has its own settings/preprocess folder;
- libraries live directly under the library root;
- one imported archive generally equals one run;
- removing a source only removes the catalog/config entry.

The current app has moved toward a shared workspace model:

- shared bike profiles live under the libraries/workspace root;
- shared preprocess profiles live under the libraries/workspace root;
- shared event schemas live under the libraries/workspace root;
- new managed libraries live under a `libraries/` collection directory below that root;
- sources point at shared bike/preprocess profile files;
- a source scan can import multiple sessions into the same run;
- sources and libraries can be removed from the manager only, or completely removed from disk after confirmation.

The docs should be updated before they are used as end-user guidance for 0.1.4-Beta.

## Recommended Responsibility Split

- `software-guide/setup-import-manager.mdx` should be the first successful setup path:
  - install the app;
  - create or adopt a workspace;
  - create the first library and source;
  - configure the bike profile and optional note template;
  - run one first import.
- `user-guide/import-manager-user-guide.mdx` should be the operating guide:
  - everyday importing;
  - watch mode;
  - source and library management;
  - shared profile assignment;
  - naming;
  - Wi-Fi logger workflows;
  - exports;
  - troubleshooting.
- `user-guide/import-manager-folder-structure-appendix.md` should be the path and file reference:
  - app settings;
  - current managed workspace layout;
  - source folders;
  - shared bike/preprocess/event-schema folders;
  - managed library folders;
  - legacy compatibility notes.

## Existing Items Whose Details Have Changed

### Import Manager Setup Guide

- The setup guide currently shows the old provisioning workflow and should be updated around **Create Initial Library + Source**.
- It should introduce the split between:
  - **Libraries root**, which now contains managed libraries and shared profile folders;
  - **Sources root**, which contains source folders and workflow folders.
- It should mention **Use Existing Workspace** for adopting already-created shared roots on another computer.
- The setup steps should include:
  - `Generate data.syn.bike exports`;
  - source type selection;
  - optional session auto-naming;
  - optional draft setup note attachment.
- The quick folder tree should no longer show active source-local `bike/` and `settings/` folders for new sources.
- The bike-profile section should describe shared bike profile files under `bike_profiles/`, not source-local `<source>/bike`.
- The rear LUT section should say it maps rear sensor travel to rear wheel travel, and mention `mm`/`deg` input units.
- The setup guide should keep only a short conceptual folder tree and link to the appendix for full detail.
- The setup guide should include a short first-import test path:
  - local archive: copy `.zip` or supported logger file such as `.bdq` into `inbox/`;
  - run **Import Now**;
  - check `done/`, `failed/`, `runs/`, and optionally `syn/`.

### Import Manager User Guide

#### Opening Overview

- The overview currently says each source can have its own import settings, bike profile, and notes template. This needs to be revised:
  - sources still own note templates/presets under their `notes/` folder;
  - sources now normally reference shared bike profile files;
  - sources now normally reference shared preprocess profile files;
  - legacy source-local bike/settings folders can still work if a source config points at them.
- The opening should introduce the shared workspace concepts before listing source/library folders.
- The app title now includes the app version, for example `BODAQS Import Manager 0.1.4-Beta`.

#### Quick Folder Layout

- The user guide currently presents a simplified layout like:

  ```text
  BODAQS/
    libraries/<library>/
    sources/<source>/
  ```

  This no longer matches the current managed layout.
- A current conceptual layout should show the shared profile directories and the managed library collection, for example:

  ```text
  <data-or-workspace-root>/
    bike_profiles/
    preprocess_profiles/
    event_schemas/
    libraries/
      <library>/
        runs/
        library/
        syn/
    sources/
      <source>/
        import_source.json
        notes/
        fit/
        inbox/
        done/
        failed/
        staging/
  ```

- The docs should be careful with the terms `libraries root`, `library folder`, `sources root`, and `workspace/data root`. Current code can use separate source and library roots, while many real deployments use a common parent folder.

#### Sources

- The typical source folder no longer contains active `bike/` and `settings/` folders for newly provisioned managed sources.
- Current source folders normally contain:
  - `import_source.json`
  - `notes/`
  - `fit/`
  - `inbox/`
  - `done/`
  - `failed/`
  - `staging/`
- `bike/` and `settings/` should be documented as legacy/source-local compatibility locations, not the default current layout.
- `.bdq` archives/logs should be included where the docs currently imply that local archive sources are only `.zip` based.
- The source config now has explicit pointers to shared files:
  - `bike_profile_path`
  - `preprocess_profile_path`
- The source config can also include session naming configuration under `naming.session_description`.

#### Libraries

- New managed libraries are now created under:

  ```text
  <libraries-root>/libraries/<library>/
  ```

- Existing direct-child library folders remain supported for compatibility, but should not be presented as the default new layout.
- The current guide should distinguish:
  - the shared libraries/workspace root;
  - the `libraries/` collection directory;
  - an individual library artifact folder.
- The docs should mention that shared bike/preprocess/event-schema folders are not inside an individual library. They are shared across libraries that use the same root.

#### Manager Tab

- The current Libraries table has changed. It currently shows:
  - `Library Name`
  - `Syn Export`
- The current Sources table has changed. It currently shows:
  - `Enabled`
  - `Allow Reprocessing`
  - `Source Name`
  - `Type`
  - `Status`
  - `Target Library`
  - `Bike Name`
  - `Attach Note`
- The actions row has changed. It now includes:
  - `Refresh`
  - `Sync Workspace`
  - `Import Now`
  - `Start Watch`
  - `Stop Watch`
- The docs should explain `Allow Reprocessing`, especially because it affects whether archives in `done/` can be reprocessed.
- The docs should explain `Sync Workspace`: it discovers libraries/sources/profile files from the configured workspace roots and reconciles the UI with disk.

#### Source Context Menu

The documented context menu is out of date. The current source context menu includes:

- `Edit bike`
- `Assign bike profile`
- `Duplicate bike profile`
- `Assign preprocess profile`
- `Change target library`
- `Import naming`
- `Details`
- Wi-Fi source actions where applicable:
  - `Edit Wi-Fi settings`
  - `Check Logger`
  - `Request Upload Mode`
  - `Open Logger Web UI`
- `Validate`
- `Rename source`
- `Remove Source`

The docs should explain the difference between:

- editing the currently assigned shared bike profile;
- assigning an existing shared bike profile;
- duplicating a shared bike profile;
- assigning a different preprocess profile.

The docs should also mention that duplicating a bike profile does not automatically assign the duplicate to the source.

#### Library Context Menu

The guide should document the current library context menu:

- `Rename library`
- `Details`
- `Remove Library`

The remove behavior has changed and is described separately below.

#### Adding Libraries And Sources

- New library provisioning now creates or ensures the shared directories:
  - `bike_profiles/`
  - `preprocess_profiles/`
  - `event_schemas/`
- New source provisioning now creates a source folder with workflow subfolders, and points the source at shared bike/preprocess profile files.
- The current Provision tab includes session auto-naming controls:
  - `Auto-name sessions on import`
  - `Session base name`
- The current Provision tab includes a `Generate data.syn.bike exports` library option.
- The current Provision tab action row includes:
  - `Create Initial Library + Source`
  - `Use Existing Workspace`
  - `Apply App Settings`
- The guide should document when to use `Use Existing Workspace` versus creating a new library/source.

#### Import Now And Watch Mode

- `Import Now` can now prompt for an optional run-description override. Leaving it blank uses source/default naming.
- Session descriptions can be auto-generated from a base name and index.
- Detected sessions from the same source scan can now be processed into the same run, rather than every session being forced into a separate run.
- The docs should explain that run and session IDs remain stable machine-facing identifiers, while run/session descriptions are the user-facing names seen by downstream tools.
- The guide should mention that bulk detection and processing progress is now shown during the pass, rather than waiting for all sessions to complete.
- The user-facing difference between `Import Now` and `Start Watch` should be refreshed:
  - `Import Now` performs an immediate scan/import pass;
  - `Start Watch` starts continuous watching for enabled sources;
  - `Stop Watch` stops the watcher.

#### Run And Session Model

- The current docs still imply a one-archive/one-session/one-run mapping in several places.
- Current behavior is better described as:
  - a run is an import/preprocess batch for a source pass;
  - a run may contain one or more sessions;
  - each session remains addressable by `(run_id, session_id)`;
  - run and session descriptions are separate from IDs.
- The appendix should carry the detailed disk layout; the user guide only needs the operational model.

#### Bike Profiles

- The current guide says each source has its own bike profile. This is no longer the default model.
- Bike profiles are now shared files under:

  ```text
  <libraries-root>/bike_profiles/
  ```

- A source points to a bike profile file via `bike_profile_path`.
- Multiple sources can use the same bike profile.
- Assigning a bike profile changes which shared profile the source uses.
- Duplicating a bike profile creates a new shared file but does not automatically assign it.
- The guide should advise users to duplicate a profile before experimental edits if the same profile is shared by multiple sources.
- The rear wheel LUT section has changed:
  - the top text should refer to sensor travel, not shock travel;
  - LUT input units can be `mm` or `deg`;
  - the first table column heading updates to `sensor mm` or `sensor deg`;
  - the second table column maps to wheel travel in `mm`.
- The calibration/materialization text should account for rotary sensor channels and degree-based calibration/LUT input.

#### Preprocess Profiles And Event Schemas

- Preprocess profiles are no longer best described as source-local `settings/` files.
- Shared preprocess profiles now live under:

  ```text
  <libraries-root>/preprocess_profiles/
  ```

- Shared event schemas now live under:

  ```text
  <libraries-root>/event_schemas/
  ```

- A source references a preprocess profile via `preprocess_profile_path`.
- Event schemas are referenced from preprocess profiles by path. For the seeded shared profile, the event schema path is relative to the preprocess profile directory:

  ```text
  ../event_schemas/event_schema.yaml
  ```

- The docs should make clear that legacy source-local settings files remain usable if a source points at them.

#### Activity Detection

- The current guide does not cover the updated activity detection strategy.
- The current strategy should be documented at a user level:
  - GPS velocity is preferred when available;
  - wheel motion is used as the next option;
  - legacy preprocess profiles remain supported;
  - analog flat-zero signals can be genuine inactivity or a missing sensor, so the profile/source configuration matters.
- The seeded preprocess profile now uses a 0.1 second zeroing window.

#### GPS Handling

- The guide should be updated to reflect that logger GPS data is now used downstream, not just FIT-style GPS naming.
- Initial invalid GPS rows from logger files are tolerated when validity flags and finite coordinates indicate which points are usable.
- data.syn.bike exports now use logger GPS where available.
- FIT files are still useful for enrichment/fallback workflows, but the guide should not imply that FIT is the only way GPS gets into downstream exports.

#### data.syn.bike Exports

- The guide should mention that exports now handle missing travel at one end by writing zeros in the relevant columns, so the data.syn.bike visualiser can still open the file.
- The guide should explain that export files are re-generated on reprocess when the library/source settings request data.syn.bike output.
- The output description should include:
  - the CSV export file;
  - the helper/settings text file;
  - export manifests where relevant.
- The explanation of raw/travel scaling should be refreshed, especially for processed wheel travel mode and rotary sensors.
- The current `synoutputs.png` image shows the data.syn.bike web analyser, not the Import Manager's `syn/` output folder. It should not be the only visual for this section.

#### Removing Sources And Libraries

- The current guide says removing a source only removes it from the Import Manager and leaves folders untouched. This is now incomplete.
- Current remove dialogs offer two choices:
  - remove from Import Manager only;
  - remove from Import Manager and delete the folder from disk.
- Complete removal requires an additional confirmation where the user types `DELETE`.
- Complete source removal deletes the source folder if the filesystem operation succeeds.
- Complete library removal deletes the individual library data folder if the filesystem operation succeeds.
- Complete library removal does not delete shared workspace-level folders such as:
  - `bike_profiles/`
  - `preprocess_profiles/`
  - `event_schemas/`
- The guide should mention practical failure causes such as read-only/locked folders, especially under cloud-synced roots such as OneDrive.

#### Troubleshooting

The troubleshooting section should be expanded or refreshed for current behavior:

- Source removal/delete fails:
  - folder may be open in another process;
  - cloud sync may hold locks;
  - file attributes may be read-only;
  - user may have insufficient permission for that folder.
- Source appears with unexpected type/status:
  - this was fixed in the current build, but users should refresh/sync workspace after upgrading.
- Wi-Fi logger not discovered:
  - check AP versus station mode;
  - use fixed logger address where discovery is not available;
  - use `Open Logger Web UI` to confirm browser connectivity.
- No GPS in downstream export:
  - check whether logger GPS points are valid;
  - check FIT enrichment only if relying on FIT GPS;
  - check the preprocess profile's GPS stream handling.
- Session appears inactive:
  - check available activity signals;
  - GPS velocity is preferred;
  - wheel motion is fallback;
  - missing/flat analog signals can look like parked-bike inactivity.
- data.syn.bike file missing or incomplete:
  - verify library export setting;
  - verify reprocess setting;
  - check source `failed/` and logs;
  - remember that missing one-end travel should now produce zero-filled columns rather than an unreadable export.

#### Safe Operating Habits

- The current advice to keep one active bike profile per source is no longer right.
- Recommended habits should become:
  - treat shared bike/preprocess profiles as reusable workspace assets;
  - duplicate a profile before experimental edits if it is shared;
  - assign the intended profile explicitly after duplicating;
  - stop watch mode before major source/profile changes;
  - keep shared profiles under the managed profile directories rather than adding ad hoc source-local files;
  - back up shared profile directories along with libraries and sources.

### Folder And File Structure Appendix

#### Main Locations

- The appendix currently describes three locations: app settings, sources root, and libraries root. It needs one more layer of precision.
- The app settings file remains:

  ```text
  %LOCALAPPDATA%/BODAQS/import-agent/import_agent_app.json
  ```

- The sources root still contains source folders.
- The libraries/workspace root now contains shared assets plus the managed library collection:

  ```text
  <libraries-root>/
    bike_profiles/
    preprocess_profiles/
    event_schemas/
    libraries/
      <library>/
  ```

- The appendix should explain that code defaults and user-chosen roots can produce confusing names. For example, a folder named `libraries` may be the configured libraries root, and it may itself contain the managed `libraries/` collection directory.
- A vocabulary table would help:
  - app settings path;
  - sources root;
  - libraries/workspace root;
  - shared profile directories;
  - managed library collection directory;
  - individual library folder.

#### Portable Shared Workspace Example

- The portable/shared workspace example should include shared profile directories.
- A clearer example would be:

  ```text
  BODAQS-data/
    sources/
      <source>/
    bike_profiles/
      <bike-profile>.json
    preprocess_profiles/
      <preprocess-profile>.json
    event_schemas/
      event_schema.yaml
    libraries/
      <library>/
        runs/
        library/
        syn/
  ```

- The docs should explain that sources and libraries can be configured under the same data root, but they are still separate roots in app settings.

#### Source Folder

- The current source folder tree includes active `bike/` and `settings/` folders. That should move to a legacy compatibility note.
- The current managed source folder should be documented as:

  ```text
  <sources-root>/<source>/
    import_source.json
    notes/
    fit/
    inbox/
    done/
    failed/
    staging/
  ```

- `inbox/`, `done/`, `failed/`, and `staging/` should be described as workflow folders for local archives and logger downloads.
- `fit/` remains the place for FIT enrichment files.
- `notes/` remains source-owned.

#### Source Manifest

The `import_source.json` field descriptions need updates:

- `source_id`: stable source identifier.
- `display_name`: UI-facing source name.
- `source_type`: local archive or Wi-Fi logger style source.
- `library_id`: target library identifier used by the managed app.
- `artifacts_dir`: compatibility/direct path field; managed app primarily resolves `library_id` through app settings.
- `preprocess_profile_path`: path to the selected preprocess profile file, usually in shared `preprocess_profiles/`.
- `bike_profile_path`: path to the selected bike profile file, usually in shared `bike_profiles/`.
- `session_note`: source-local note template/preset configuration under `notes/`.
- `fit_dir`, `inbox_dir`, `done_dir`, `failed_dir`, `staging_dir`: source workflow directories.
- `force_reprocess`: whether already processed archives can be reprocessed.
- `logger_wifi`: Wi-Fi logger connection and upload-mode settings.
- `naming.session_description`: optional auto-naming settings for session descriptions.

#### Shared Bike Profiles

The appendix should add a new section for:

```text
<libraries-root>/bike_profiles/
```

It should explain:

- bike profiles are shared workspace assets;
- a source references a specific profile file;
- multiple sources may share one profile;
- duplicate creates a new profile file;
- duplicate does not automatically assign the new file;
- source-local `bike/` folders are legacy-compatible, not the normal new layout.

#### Shared Preprocess Profiles

The appendix should add a new section for:

```text
<libraries-root>/preprocess_profiles/
```

It should explain:

- preprocess profiles are shared workspace assets;
- a source references a specific profile file;
- a profile can reference event schemas by relative or absolute path;
- the seeded relative event schema path is:

  ```text
  ../event_schemas/event_schema.yaml
  ```

- source-local `settings/` folders are legacy-compatible, not the normal new layout.

#### Shared Event Schemas

The appendix should add a new section for:

```text
<libraries-root>/event_schemas/
```

It should explain:

- event schemas are shared workspace assets;
- the Import Manager does not need source-level event schema assignment because preprocess profiles already reference schema paths;
- event schemas can be reused by multiple preprocess profiles.

#### Library Folder

- The library folder example should be updated from direct-child library roots to the current managed default:

  ```text
  <libraries-root>/libraries/<library>/
    library_definition.json
    runs/
    library/
    syn/
  ```

- The docs should mention that older direct-child library folders remain readable for compatibility, but new libraries are created under the managed `libraries/` directory.

#### Runs And Sessions

- The appendix currently states that each run usually corresponds to one imported session. That is now misleading.
- Current wording should describe:
  - a run as a source scan/import batch;
  - a run may contain multiple sessions;
  - sessions are stored below the run;
  - the stable physical address is `(run_id, session_id)`.
- The run manifest can contain batch import metadata, including the import mode and session count.
- The appendix should describe run/session descriptions separately from run/session IDs.

#### Library Index And Catalog

- The existing `library/` state/index section is broadly still relevant, but should be checked for wording that assumes one run per session.
- Downstream tools should use manifests/catalogs and IDs rather than folder names alone.
- The docs should clarify whether browser/study-set columns labelled `run` and `session` show descriptions, IDs, or both, depending on the current downstream UI.

#### data.syn.bike Output Folder

- The appendix should include the current `syn/` folder output shape.
- It should show that exports are session-based and include generated CSV plus helper/settings/manifest files where present.
- It should explain that exports may be regenerated on reprocess.
- It should mention zero-filled columns for missing one-end travel.

#### Removing Data

- The appendix should add a section distinguishing:
  - remove from Import Manager only;
  - complete removal from Import Manager plus disk deletion.
- It should state exactly what complete deletion affects:
  - complete source removal deletes the source folder;
  - complete library removal deletes the individual library folder;
  - complete library removal does not delete shared profile/schema directories.
- It should caution that manual deletion outside the app may require `Sync Workspace` or app restart.

## New Items And Features Not Currently Covered

- Shared bike profile directory under the libraries/workspace root.
- Shared preprocess profile directory under the libraries/workspace root.
- Shared event schema directory under the libraries/workspace root.
- Managed `libraries/` collection directory below the configured libraries/workspace root.
- Assign bike profile action.
- Duplicate bike profile action and its non-auto-assignment behavior.
- Assign preprocess profile action.
- Import naming dialog for session auto-naming.
- Session auto-naming controls during source provisioning.
- Import Now run-description override prompt.
- Batch import behavior where multiple detected sessions can be processed into the same run.
- Progress updates during detection and processing of large batches.
- `Sync Workspace` action.
- `Allow Reprocessing` source column and behavior.
- Complete source removal with disk deletion and typed confirmation.
- Complete library removal with disk deletion and typed confirmation.
- Version number in the app title.
- Updated Wi-Fi logger AP-mode/fixed-address/open-web-UI workflows.
- Logger GPS use in downstream exports.
- data.syn.bike export behavior when one end of travel data is missing.
- Rotary-sensor related bike profile behavior:
  - degree-based LUT input;
  - degree-capable calibration materialization;
  - sensor travel wording for rear LUT.
- Updated activity detection preference order:
  - GPS velocity first;
  - wheel motion fallback;
  - legacy profiles supported.
- Seeded preprocess profile's 0.1 second zeroing window.
- Local archive handling for compact binary `.bdq` where relevant.

## Screenshots That Are Out Of Date

The following existing screenshots should be updated before the docs are refreshed.

### `import-manager.png`

Used near the start of both `setup-import-manager.mdx` and `import-manager-user-guide.mdx`.

This is substantially outdated:

- it shows the old unversioned app title;
- it shows old library/source table columns such as library/source IDs;
- it does not show the current `Allow Reprocessing`, `Bike Name`, and `Attach Note` columns;
- it does not show the current `Sync Workspace` action;
- it predates the shared profile model and current source status/type column fixes.

Recommendation: replace with a current full-window Manager tab screenshot from 0.1.4-Beta.

### `import-mgr-provisioning.png`

Used in `setup-import-manager.mdx`.

This screenshot is outdated:

- it does not show the current session auto-naming controls;
- it does not show the current action row, especially **Create Initial Library + Source** and **Use Existing Workspace**;
- it likely predates shared bike/preprocess/event-schema provisioning.

Recommendation: replace with a current Provision tab screenshot focused on first setup.

### `just-say-yes.png`

Used in `setup-import-manager.mdx`.

This screenshot should be checked against the current post-create prompt:

- the prompt still offers to open the bike-profile editor after source creation;
- the text may now mention the rear LUT and note template;
- the styling may need refreshing for a consistent 0.1.4-Beta screenshot set.

Recommendation: refresh if the current prompt differs materially from the image.

### `manager-tab.png`

This screenshot is outdated:

- it lacks the current app title/version;
- it lacks the current `Allow Reprocessing` source column;
- it lacks the current `Sync Workspace` button;
- it shows old table content/columns.

Recommendation: replace with a current Manager tab screenshot, preferably with one local source and one Wi-Fi logger source visible.

### `source-context-menu.png`

This screenshot is outdated:

- it is missing `Assign bike profile`;
- it is missing `Duplicate bike profile`;
- it is missing `Assign preprocess profile`;
- it is missing `Import naming`;
- it predates the current source table columns.

Recommendation: replace with a current source context menu screenshot.

### `provision-tab.png`

This screenshot is outdated:

- it does not show the current session auto-naming controls;
- it does not show the current action row including `Use Existing Workspace` and `Apply App Settings`;
- it does not show the current app title/version;
- it likely predates the current shared profile provisioning behavior.

Recommendation: replace with a current Provision tab screenshot with the session auto-naming row visible.

### `bike-profile-complete.png`

This screenshot is outdated:

- it refers to rear shock travel instead of rear sensor travel;
- it does not show the `mm`/`deg` LUT input unit radio buttons;
- it does not show the dynamic `sensor mm` or `sensor deg` first column heading;
- it predates the current shared bike profile model.

Recommendation: replace with a current bike profile editor screenshot showing the rear LUT area.

### `edit-note-profile.png`

This screenshot appears broadly consistent with the source-local note profile concept, but it should be checked during the final doc edit.

Recommendation: refresh only if the current dialog styling/fields have changed, or if a consistent 0.1.4-Beta screenshot set is desired.

### `synoutputs.png`

This image shows the data.syn.bike web analyser rather than the Import Manager output folder.

Recommendation: either move/use it in a data.syn.bike workflow section, or supplement it with a screenshot of the Import Manager/library `syn/` folder containing generated CSV/helper/manifest files.

## Screenshots Or Photos That Should Be Added

- Current full-window Manager tab showing:
  - versioned app title;
  - Libraries table;
  - Sources table with all current columns;
  - `Sync Workspace`, `Import Now`, `Start Watch`, and `Stop Watch`.
- Current Provision tab showing:
  - libraries root;
  - sources root;
  - target library;
  - source type;
  - session auto-naming controls;
  - action row.
- Current first-setup Provision tab screenshot for the setup guide, with **Create Initial Library + Source** clearly visible.
- Current post-create prompt asking whether to open the bike-profile editor.
- Source context menu showing the shared profile and import naming actions.
- Assign Bike Profile dialog.
- Duplicate Bike Profile dialog, ideally with a caption noting that the duplicate is not auto-assigned.
- Assign Preprocess Profile dialog/file picker.
- Import Naming dialog.
- Import Now run-description override prompt.
- Remove Source dialog showing the two removal choices.
- Typed `DELETE` confirmation dialog for complete removal.
- Remove Library dialog, including the warning that shared profile/schema folders are not deleted.
- Bike Profile editor showing the current rear LUT unit controls and `sensor mm`/`sensor deg` heading.
- Wi-Fi logger settings dialog showing discovery/fixed-address/upload/open-web-UI workflow.
- A progress/log screenshot from a multi-archive import showing detection and per-session processing updates.
- A current folder tree screenshot or generated diagram showing:
  - `sources/`
  - `bike_profiles/`
  - `preprocess_profiles/`
  - `event_schemas/`
  - `libraries/<library>/runs`
- A `syn/` output folder screenshot showing generated CSV, helper/settings text, and manifest files.
- Optional: a data.syn.bike web analyser screenshot after upload, kept separate from the file-output screenshot.

## Suggested Restructure

### Setup Guide

The setup guide should stay short and task-oriented. It should cover only the
first successful setup:

1. Install the app.
2. Create or adopt a workspace.
3. Create the first library and source.
4. Configure the bike profile and optional note template.
5. Run one first import.
6. Link onward to the user guide and appendix.

It should avoid becoming the full source/library management guide. It only
needs a short conceptual folder tree, with path details left to the appendix.

### Import Manager User Guide

The user guide should assume first setup is complete. It should be organised
around normal operation and ongoing management:

1. What the Import Manager manages
   - sources;
   - libraries;
   - shared profiles;
   - runs and sessions.
2. Everyday importing
   - local archive sources;
   - Wi-Fi logger sources;
   - `Import Now`;
   - watch mode;
   - progress and failures.
3. Naming and descriptions
   - run IDs versus run descriptions;
   - session IDs versus session descriptions;
   - Import Now run-description override;
   - session base-name auto-naming.
4. Managing shared profiles
   - bike profiles;
   - preprocess profiles;
   - event schemas;
   - source-local legacy compatibility.
5. Managing libraries and sources
   - sync workspace;
   - rename;
   - retarget;
   - remove from manager;
   - complete delete from disk.
6. Exports and downstream tools
   - data.syn.bike;
   - FIT enrichment;
   - logger GPS;
   - `syn/` folder outputs.
7. Troubleshooting
   - source discovery;
   - Wi-Fi logger discovery/AP mode;
   - failed imports;
   - inactive sessions;
   - deletion/access-denied problems.

### Folder And File Structure Appendix

The appendix should become the authoritative disk-layout reference and should separate current layout from legacy compatibility:

1. App settings
2. Workspace/library roots vocabulary
3. Current managed workspace tree
4. Source folders
5. Shared profile folders
6. Managed library folders
7. Runs and sessions
8. Library indices/catalogs
9. data.syn.bike outputs
10. Legacy source-local bike/settings folders
11. Remove/delete behavior
12. Sharing a workspace across computers

This would keep the main guide practical while letting the appendix carry the precise path details.

## Editorial Notes For The Later Content Edit

- Use `profile` carefully:
  - bike profile is shared;
  - preprocess profile is shared;
  - note profile/template is source-local.
- Use `description` for user-facing run/session names and `ID` for stable machine-facing names.
- Prefer `assign` for selecting an existing shared profile and `duplicate` for creating a new profile file.
- Avoid saying a source "owns" a bike/preprocess profile unless discussing legacy source-local compatibility.
- Be explicit that complete deletion is destructive and separate from ordinary removal from the Import Manager.
- Keep detailed implementation fields in the appendix; keep the main guide focused on what users need to do.
