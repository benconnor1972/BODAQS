# BODAQS Import Agent Implementation Plan

## Goal

Move from the current packaged CLI watcher to a desktop-installed multi-source
 import application with a tray shell and first-run provisioning.

## Guiding Principles

- keep the current artifact contract stable
- preserve the current CLI as a thin wrapper over shared engine code
- prefer one supervisor process over many watcher processes
- keep source adapters acquisition-specific but preprocessing-generic
- keep installers thin and move user-specific setup into the app

## Phases

### Phase 1. Extract reusable engine supervision

Purpose:

- create a stable multi-source supervisor layer that can be embedded by a tray
  app

Scope:

- source pause/resume
- due-scan scheduling
- status snapshots
- one-shot scan orchestration
- watch-loop orchestration

Status:

- started
- first slice implemented in `bodaqs_analysis.import_agent`

Exit criteria:

- CLI `once` and `watch` run through the supervisor
- tests cover scheduling and paused-source behavior

### Phase 2. Add app-level config and provisioning

Purpose:

- separate desktop app configuration from per-source import configuration

Scope:

- app config schema
- libraries root model
- known library registry
- known source registry
- provisioning helpers for:
  - creating a library
  - creating a default source
  - seeding default assets

Exit criteria:

- one function can create a ready-to-use source directory tree
- one function can create a ready-to-use library directory tree

### Phase 3. Prepare shipped defaults

Purpose:

- define the assets bundled with the installed product

Scope:

- default preprocess profile
- default event schema
- example/default bike profile
- source and library template assets

Exit criteria:

- seeded source folders are usable without manual JSON editing

Status:

- shipped default assets implemented
- asset-package discovery now supports flexible filenames by content/type

### Phase 4. Build the desktop shell

Purpose:

- provide the first packaged desktop UI around the engine

Scope:

- standalone setup/admin window
- first-run setup flow
- single-instance app startup
- managed libraries and sources list
- validate sources
- import now
- start/stop in-process watch loop
- enable/disable sources
- later tray/menu-bar host
- tray status
- pause/resume
- open folders
- open logs

Exit criteria:

- user can provision libraries and sources without touching a terminal
- user can validate, import once, and start/stop watching without touching a terminal
- later tray work can reuse the same setup backend and supervisor

Status:

- first non-tray manager slice implemented in `bodaqs_analysis.import_agent_setup`

### Phase 5. Installer and auto-start

Purpose:

- make installation and launch behavior native per platform

Scope:

- Windows installer first
- start-at-login registration
- launch app after install

Exit criteria:

- clean install produces a usable first-run experience on Windows

### Phase 6. New source adapters

Purpose:

- expand beyond filesystem archive sources

Scope:

- serial logger source
- Wi-Fi logger source
- cloud-backed source

Exit criteria:

- each adapter feeds the same local canonical import pipeline

## Immediate Work Queue

### Completed in this step

- architecture note written
- implementation plan written
- supervisor extracted from the CLI watcher path
- app-level provisioning helpers added
- shipped default assets added
- non-tray setup window added
- non-tray manager window added with validate/import/watch controls

### Next recommended coding step

Refine the non-tray manager into a fuller desktop shell by adding:

1. richer status and recent-error presentation
2. open-folder shortcuts
3. source-level pause/resume semantics distinct from persisted enable/disable
4. config migration/version handling UX
5. installer handoff and start-at-login wiring

That will give the future tray shell and installer a stronger desktop foundation
without changing the import engine or artifact contract.
