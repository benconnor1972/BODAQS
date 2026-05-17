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

### Phase 4. Build the desktop shell

Purpose:

- provide a tray/menu-bar host for the engine

Scope:

- single-instance app startup
- first-run setup flow
- tray status
- source list
- pause/resume
- scan now
- open folders
- open logs

Exit criteria:

- user can install and operate the watcher without touching a terminal

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

### Next recommended coding step

Add app-level provisioning helpers that can:

1. create a libraries root entry
2. create a source folder under a chosen sources root
3. seed `settings/`, `bike/`, and `import_source.json`
4. point the source at a chosen library

That will give the future tray app and installer a stable non-UI backend for
first-run setup.
