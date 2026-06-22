---
title: Import Manager Folder And File Structure Appendix
description: Reference description of the folders and files used by BODAQS Import Manager.
---

# Import Manager Folder And File Structure Appendix

This appendix describes the folders and files used by BODAQS Import Manager.
It is intended as reference material for users who want to understand what is
created during setup, what is safe to share between computers, and which files
should normally be left alone.

## Main Locations

BODAQS Import Manager uses three kinds of storage.

- The app settings folder is local to each computer and stores that computer's
  list of libraries, sources, and root paths.
- The sources root contains one folder per import source.
- The libraries/workspace root contains shared profile folders and the managed
  library collection.

For a standard Windows install, the app settings file lives under:

```text
%LOCALAPPDATA%\BODAQS\import-agent\import_agent_app.json
```

By default, sources and the libraries/workspace root are created under the
user's home folder:

```text
<home>\BODAQS\sources\
<home>\BODAQS\libraries\
```

Inside the libraries/workspace root, current managed libraries are stored under
a child folder named `libraries`:

```text
<libraries-root>\libraries\<library>\
```

This means the default managed library path can contain two folders named
`libraries`. The first is the configured libraries/workspace root; the second is
the managed library collection directory.

Users may choose different source and library roots during setup, including
folders on a cloud-synced drive such as OneDrive.

<!-- TODO screenshot/diagram: add a current workspace tree diagram showing sources, bike_profiles, preprocess_profiles, event_schemas, and libraries/<library>. -->

## Path Vocabulary

The following terms are used throughout this appendix.

- **App settings file**: the per-computer `import_agent_app.json` under
  `%LOCALAPPDATA%`.
- **Sources root**: the folder that contains one folder per source.
- **Libraries/workspace root**: the folder that contains shared bike profiles,
  preprocess profiles, event schemas, and the managed library collection.
- **Managed library collection**: the `libraries/` folder under the
  libraries/workspace root.
- **Library folder**: one processed BODAQS library under the managed library
  collection.
- **Shared profile folders**: `bike_profiles/`, `preprocess_profiles/`, and
  `event_schemas/`.

## Local App Settings

The local app settings file is:

```text
import_agent_app.json
```

This file belongs to one computer. It records the local paths that this
computer uses to find the shared source and library roots.

It contains:

- `sources_root`: the local path to the sources root on this computer.
- `libraries_root`: the local path to the libraries/workspace root on this
  computer.
- `libraries`: the libraries managed by this install.
- `sources`: the sources managed by this install.
- `auto_start`: whether the manager should start at login.

The source and library IDs should match across computers, but the actual paths
inside `import_agent_app.json` may legitimately differ from one computer to
another.

## Portable Shared Workspace

When sources and libraries live on a cloud drive, the shared workspace should
contain the source folders, shared profile folders, and library folders, but not
the per-computer app settings file.

A typical shared workspace looks like this:

```text
BODAQS-data\
  sources\
    default-source\
      import_source.json
      notes\
      fit\
      inbox\
      done\
      failed\
      staging\
  bike_profiles\
    default-bike.json
  preprocess_profiles\
    default-preprocess.json
  event_schemas\
    event_schema.yaml
  libraries\
    default-library\
      library_definition.json
      library\
      runs\
      syn\
```

Each computer can adopt the same shared workspace by selecting the existing
source and library roots and using the existing-workspace setup path. The
manager rebuilds that computer's local `import_agent_app.json` from the shared
source and library definitions.

## Source Folder

Each source has its own folder under the sources root.

```text
<sources-root>\
  <source>\
    import_source.json
    notes\
    fit\
    inbox\
    done\
    failed\
    staging\
```

### `import_source.json`

`import_source.json` is the shared source definition. It describes the import
source, its durable target library ID, and the files used when importing from
that source.

Important fields include:

- `source_id`: stable source identity.
- `display_name`: user-facing source name.
- `source_type`: `filesystem_archive` or `logger_wifi`.
- `library_id`: stable ID of the target library.
- `artifacts_dir`: compatibility/direct-path field. In managed mode, the
  desktop app primarily resolves `library_id` through local app settings.
- `preprocess_profile_path`: path to the selected preprocess profile file,
  usually under the shared `preprocess_profiles/` folder.
- `bike_profile_path`: path to the selected bike profile file, usually under
  the shared `bike_profiles/` folder.
- `session_note`: note-template settings for automatic draft notes.
- `fit_dir`: usually `fit`.
- `inbox_dir`: usually `inbox`.
- `done_dir`: usually `done`.
- `failed_dir`: usually `failed`.
- `staging_dir`: usually `staging`.
- `force_reprocess`: whether duplicate source archives may be reprocessed.
- `logger_wifi`: Wi-Fi logger identity, network, timeout, and cleanup settings
  for Wi-Fi logger sources.
- `naming.session_description`: optional settings for automatic session
  descriptions.

For portability, the Import Manager treats `library_id` as the durable target.
In managed mode, the local app settings file resolves that `library_id` to the
correct library path for the current computer.

Older source files may still contain an `artifacts_dir` field. The managed
desktop app does not rely on that field when resolving the target library.

### `notes\`

The `notes` folder contains the source's note profile/template and bike setup
preset.

Typical files are:

```text
notes\
  session_note_template.json
  bike_setup_preset.json
```

When automatic note attachment is enabled for a source, new imported sessions
receive a draft note based on these files.

### `fit\`

The `fit` folder stores optional FIT files for enrichment.

FIT files are read in place. The Import Manager does not move or delete FIT
files after use.

### `inbox\`

For local archive sources, `inbox` is where completed logger session archives
or files are placed for import.

Typical inputs are ZIP session archives or supported logger files such as `.bdq`
compact binary logs.

Files should be fully copied before the Import Manager processes them. The
manager waits for files to settle before importing.

### `done\`

After a local archive is imported successfully, it is moved to `done`.

Archives in `done` are retained as source records. Moving one back to `inbox`
will only reprocess it if the source has **Allow Reprocessing** enabled.

### `failed\`

Archives that cannot be imported are moved to `failed`.

### `staging\`

`staging` is temporary workspace used during import. Users should not place
files there manually.

## Shared Bike Profiles

Current managed sources normally use bike profiles stored under:

```text
<libraries-root>\bike_profiles\
```

A source points to a specific bike profile file with `bike_profile_path`.
Multiple sources can use the same bike profile.

Bike profiles define:

- bike identity and display name
- suspension travel values
- front suspension transform
- rear sensor-to-wheel lookup table
- normalization ranges used by preprocessing and exports

Duplicating a bike profile creates a new shared profile file. It does not
automatically assign the duplicate to the source.

## Shared Preprocess Profiles

Current managed sources normally use preprocess profiles stored under:

```text
<libraries-root>\preprocess_profiles\
```

A source points to a specific preprocess profile file with
`preprocess_profile_path`. Multiple sources can use the same preprocess profile.

The preprocess profile controls how raw logger signals are transformed into
processed BODAQS session data. It can also reference event schemas.

The seeded shared preprocess profile refers to the seeded event schema with
this relative path:

```text
../event_schemas/event_schema.yaml
```

Relative schema paths are resolved from the preprocess profile's location.

## Shared Event Schemas

Current managed workspaces store event schemas under:

```text
<libraries-root>\event_schemas\
```

The Import Manager does not need a separate source-level event schema setting
because event schemas are referenced from preprocess profiles.

## Legacy Source-Local `bike\` And `settings\`

Older sources may contain:

```text
<source>\
  bike\
  settings\
```

These folders are still supported if `bike_profile_path` or
`preprocess_profile_path` points to them.

In current managed setups, these folders are compatibility locations rather
than the normal place to create new profiles. New shared profiles should usually
live under `bike_profiles/` or `preprocess_profiles/` in the libraries/workspace
root.

## Library Folder

Each current managed library has its own folder under the managed library
collection:

```text
<libraries-root>\
  libraries\
    <library>\
      library_definition.json
      library\
      runs\
      syn\
```

Older workspaces may have library folders directly under the libraries root.
The Import Manager can still discover and use those legacy libraries, but new
libraries are created under the managed `libraries/` collection.

### `library_definition.json`

`library_definition.json` is the shared library definition.

It contains:

- `library_id`: stable library identity.
- `display_name`: user-facing library name.
- export settings, including data.syn.bike export settings.

Older library definitions may include an absolute `artifacts_dir`. In a
portable workspace, the Import Manager treats the folder containing
`library_definition.json` as the library path on the current computer.

### `runs\`

`runs` contains processed BODAQS artifacts.

A run is an import/preprocess batch for a source pass. A run may contain one or
more sessions. Each session remains separately addressable by its stable
`run_id` and `session_id`.

Run folders contain session folders with processed data, metadata, events,
metrics, manifests, and annotations.

Run and session IDs are stable machine-facing identifiers. Run and session
descriptions are the human-friendly names shown by downstream tools.

### `library\`

`library` stores library-level support files, including import state and
library-local session-note templates copied during import.

Typical files and folders include:

```text
library\
  import_agent_state_v1.json
  session_note_templates\
```

`import_agent_state_v1.json` records source archives that have already been
processed. This is why deleting processed run artifacts alone does not make an
archive import again. Use the source's **Allow Reprocessing** option when you
intentionally want to reprocess an archive.

### `syn\`

`syn` contains optional data.syn.bike export outputs when **Syn Export** is
enabled for a library before import or reprocess.

Typical outputs include:

- data.syn.bike CSV files
- per-session helper/settings text files
- export metadata or manifests

Exports are session-based. If a session is reprocessed while **Syn Export** is
enabled, its export files can be regenerated.

The exporter can use logger GPS as well as FIT-derived GPS. If travel data for
one end of the bike is missing, the exporter writes zeros in the relevant
columns so the data.syn.bike visualiser can still open the file.

<!-- TODO screenshot: add a current syn folder screenshot showing generated CSV, helper/settings text, and manifest files. -->

## Wi-Fi Sources

Wi-Fi logger sources use the same source folder structure, but they acquire
archives from a logger over the local network rather than requiring users to
drop files into `inbox`.

The source `import_source.json` contains a `logger_wifi` block with the logger
ID, cleanup policy, timeout settings, and optional fixed address.

If no fixed address is stored, the manager can use mDNS discovery where the
network allows it. If a fixed address is stored, users can edit the Wi-Fi source
settings later from the Manager screen.

When a logger is in access-point mode, discovery may be less reliable than on a
normal station Wi-Fi network. Use a fixed/manual address when needed.

## Removing Sources And Libraries

The Import Manager has two removal modes.

**Remove from Import Manager only** removes the entry from local app settings.
It leaves the source or library folder on disk.

**Remove from Import Manager and delete folder** removes the entry and deletes
the selected folder from disk. This mode requires a second confirmation where
the user types `DELETE`.

Complete source removal deletes the source folder, including `notes/`, `fit/`,
`inbox/`, `done/`, `failed/`, and `staging/`.

Complete library removal deletes the individual library folder under the
managed library collection. It does not delete shared workspace-level folders
such as:

- `bike_profiles/`
- `preprocess_profiles/`
- `event_schemas/`

Deletion can fail if files are read-only or locked by another process, including
cloud-sync tools. Close open file browsers, editors, notebooks, and sync
previews before retrying.

<!-- TODO screenshot: add current removal dialogs and DELETE confirmation screenshots. -->

## Sharing Across Computers

For a two-computer workflow:

- Put `sources_root` and `libraries_root` on the shared/cloud drive.
- Install BODAQS Import Manager on each computer.
- On the first computer, create the workspace normally.
- On the second computer, choose the existing source and library roots and use
  the existing-workspace setup path.

The second computer rebuilds its own local app settings from the shared
definitions. It does not need the same local cloud-drive path as the first
computer.

Shared bike profiles, preprocess profiles, and event schemas are usable by all
libraries and sources that share the same libraries/workspace root.

Only one computer should actively watch/import from the same shared workspace
at a time. Running two active watchers against the same cloud-synced source can
create races around `inbox`, `done`, staging files, and import state.

## Files Usually Safe To Edit

Use the Import Manager UI where possible. If you edit files manually, make a
backup first and stop watch mode.

Files that are usually intended to be user-editable include:

- shared bike profile JSON files under `bike_profiles/`
- shared preprocess profile JSON files under `preprocess_profiles/`, for
  advanced users
- event schema YAML files under `event_schemas/`, for advanced users
- note templates and presets under a source `notes/` folder
- `import_source.json`, for advanced repair or portability work

Files that should usually be left to the Import Manager include:

- `import_agent_app.json`
- `library/import_agent_state_v1.json`
- files under `staging/`
- generated files under `runs/`
- generated files under `syn/`
