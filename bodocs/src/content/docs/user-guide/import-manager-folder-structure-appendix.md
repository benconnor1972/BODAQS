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

- The app settings folder is local to each computer and stores the manager's
  list of libraries and sources.
- The sources root contains one folder per import source.
- The libraries root contains one folder per processed BODAQS library.

For a standard Windows install, the app settings file lives under:

```text
%LOCALAPPDATA%\BODAQS\import-agent\import_agent_app.json
```

By default, sources and libraries are created under:

```text
<home>\BODAQS\sources\
<home>\BODAQS\libraries\
```

Users may choose different source and library roots during setup, including
folders on a cloud-synced drive such as OneDrive.

## Local App Settings

The local app settings file is:

```text
import_agent_app.json
```

This file belongs to one computer. It records the local paths that this computer
uses to find the shared source and library roots.

It contains:

- `sources_root`: the local path to the sources root on this computer.
- `libraries_root`: the local path to the libraries root on this computer.
- `libraries`: the libraries managed by this install.
- `sources`: the sources managed by this install.
- `auto_start`: whether the manager should start at login.

The source and library IDs should match across computers, but the actual paths
inside `import_agent_app.json` may legitimately differ from one computer to
another.

## Portable Shared Workspace

When sources and libraries live on a cloud drive, the shared workspace should
contain the source and library folders, but not the per-computer app settings
file.

A typical shared workspace looks like this:

```text
BODAQS\
  sources\
    default-source\
      import_source.json
      bike\
      settings\
      notes\
      fit\
      inbox\
      done\
      failed\
      staging\
  libraries\
    default-library\
      library_definition.json
      library\
      runs\
      syn\
```

Each computer can adopt the same shared workspace by selecting the existing
source and library roots. The manager rebuilds that computer's local
`import_agent_app.json` from the shared source and library definitions.

## Source Folder

Each source has its own folder under the sources root.

```text
<sources_root>\
  <source>\
    import_source.json
    bike\
    settings\
    notes\
    fit\
    inbox\
    done\
    failed\
    staging\
```

### `import_source.json`

`import_source.json` is the shared source definition. It describes the import
source and its durable target library ID.

Important fields include:

- `source_id`: stable source identity.
- `display_name`: user-facing source name.
- `source_type`: `filesystem_archive` or `logger_wifi`.
- `library_id`: stable ID of the target library.
- `preprocess_profile_path`: usually `settings`.
- `bike_profile_path`: usually `bike`.
- `session_note`: note-template settings for automatic draft notes.
- `fit_dir`: usually `fit`.
- `force_reprocess`: whether duplicate source archives may be reprocessed.

For portability, the Import Manager treats `library_id` as the durable target.
In managed mode, the local app settings file resolves that `library_id` to the
correct library path for the current computer.

Older source files may still contain an `artifacts_dir` field. The managed
desktop app does not rely on that field when resolving the target library.

### `bike\`

The `bike` folder contains exactly one active bike profile JSON file.

The bike profile defines:

- bike identity and display name
- suspension travel values
- front suspension transform
- rear shock-to-wheel lookup table
- normalization ranges used by preprocessing and exports

### `settings\`

The `settings` folder contains the preprocessing settings and, when available,
the event schema.

Typical files are:

```text
settings\
  preprocess_profile.json
  event_schema.yaml
```

The preprocess profile controls how raw logger signals are transformed into
processed BODAQS session data. The event schema controls event detection and
metrics where applicable.

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

For local archive sources, `inbox` is where completed logger session ZIP files
are placed for import.

Each archive should contain one same-stem CSV and JSON pair.

### `done\`

After a local archive is imported successfully, it is moved to `done`.

Archives in `done` are retained as source records. Moving one back to `inbox`
will only reprocess it if the source has `Allow Reprocessing` enabled.

### `failed\`

Archives that cannot be imported are moved to `failed`.

### `staging\`

`staging` is temporary workspace used during import. Users should not place
files there manually.

## Library Folder

Each library has its own folder under the libraries root.

```text
<libraries_root>\
  <library>\
    library_definition.json
    library\
    runs\
    syn\
```

### `library_definition.json`

`library_definition.json` is the shared library definition.

It contains:

- `library_id`: stable library identity.
- `display_name`: user-facing library name.
- export settings, including data.syn.bike export settings.

Older library definitions may include an absolute `artifacts_dir`. In a portable
workspace, the Import Manager treats the folder containing
`library_definition.json` as the library path on the current computer.

### `runs\`

`runs` contains processed BODAQS artifacts.

The manager currently creates one run per imported session. Each run contains a
session folder with processed data, metadata, events, metrics, manifests, and
annotations.

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
archive import again. Use the source's `Allow Reprocessing` option when you
intentionally want to reprocess an archive.

### `syn\`

`syn` contains optional data.syn.bike export outputs when Syn Export is enabled
for a library before import.

Typical outputs include:

- data.syn.bike CSV files
- per-session helper text files
- an export manifest

## Wi-Fi Sources

Wi-Fi logger sources use the same source folder structure, but they acquire
archives from a logger over the local network rather than requiring users to
drop ZIP files into `inbox`.

The source `import_source.json` contains a `logger_wifi` block with the logger
ID, cleanup policy, and optional fixed address.

If no fixed address is stored, the manager can use mDNS discovery where the
network allows it. If a fixed address is stored, users can edit the Wi-Fi source
settings later from the Manager screen.

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

Only one computer should actively watch/import from the same shared workspace
at a time. Running two active watchers against the same cloud-synced source can
create races around `inbox`, `done`, staging files, and import state.

