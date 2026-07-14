# Demo Library Build Process

Status: draft  
Audience: BODAQS Desktop release preparation

This note describes how to create the optional demonstration library packaged
with BODAQS Desktop. The demo library lets users open the Workbench and evaluate
the software without a physical logger or their own processed sessions.

## Contract

The packaged demo assets are a relocatable BODAQS libraries-root payload. The
active demo data is not used directly from the install directory. During first
run, the Import Manager copies the packaged template into the user's selected
workspace libraries root.

The installer only shows the `Install demonstration library` task when the build
staging area contains at least one generated demo library definition at
`demo-assets/libraries/*/library_definition.json`.

Default identifiers:

- Demo library ID: `bodaqs-demo`
- Demo library display name: `BODAQS Demo Library`
- Packaged asset root: `demo-assets/`
- Installed template root: `{app}/demo-assets/`
- Runtime copy: `<workspace>/libraries/bodaqs-demo`

The Import Manager must never overwrite an existing demo library silently. If
`bodaqs-demo` already exists in the selected workspace, it is left unchanged.

## Build Steps

1. Copy `demo-assets/recipes/example.demo_library.recipe.json` to a release
   recipe, for example `demo-assets/recipes/bodaqs_demo_library.recipe.json`.
2. Set `source_libraries_root` to an existing BODAQS libraries root.
3. Set `source_library_id` to the source library to curate from.
4. List whole `runs`, explicit `sessions`, one or more `study_sets`, or a
   mixture of these.
5. Add `tracks`, `bookmarks`, and `session_filters` if they should be included
   explicitly.
6. Set anonymization replacements under `anonymize.replace_text`.
7. Run:

   ```powershell
   python tools/build_demo_library.py demo-assets/recipes/bodaqs_demo_library.recipe.json --force
   ```

8. Review `demo-assets/demo_manifest.json`.
9. Start the library service against `demo-assets` and smoke-test the library in
   the Workbench before building the installer.

## What The Exporter Copies

The exporter copies:

- all sessions from selected runs
- selected run/session artifact directories
- filtered run manifests containing only selected sessions
- shared library assets outside `runs` and `syn`
- selected root-level study sets, filtered to copied sessions
- selected tracks
- selected session filters
- selected bookmarks plus, by default, bookmarks for copied sessions

The exporter rewrites selected session references from the source library ID to
the demo library ID. It also removes configured absolute source paths from JSON
payloads and applies explicit text replacements. When `--force` is used, only
generated demo payload directories/files are cleared; recipe files and this
directory's documentation are retained.

## Curation Guidance

Prefer a small but representative library:

- 6-12 sessions is usually enough.
- Include at least one saved study set.
- Include GPS-capable sessions and a track if the demo should show sectors.
- Include notes/bookmarks where they demonstrate the UI.
- Avoid private rider details unless intentionally anonymized.
- Consider location sensitivity before including real GPS tracks.

## Validation Expectations

At minimum, verify:

- the demo library appears in the Workbench library selector
- session selector loads rows without warnings
- signal inspector opens for at least two sessions
- simple suspension analysis opens for the saved study set
- GPS and track previews work where expected
- notes and bookmarks are present where expected

The exporter performs structural checks, but it does not replace a Workbench
smoke test.
