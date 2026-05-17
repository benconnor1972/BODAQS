# BODAQS Import Agent Manager v1

## Purpose

The manager window is a small packaged desktop utility for provisioning,
extending, and operating a local BODAQS import-agent installation without
editing JSON files by hand.

It can:

- the managed app config
- add libraries under the chosen libraries root
- add sources under the chosen sources root
- seed default assets in `settings/` and `bike/`
- validate managed sources
- run one-shot imports
- start and stop the in-process watch loop

## What It Creates

For each new source:

```text
<sources_root>/
  <Source Name>/
    import_source.json
    settings/
      preprocess_profile.json
      event_schema.yaml
    bike/
      bike_profile.json
    inbox/
    done/
    failed/
    staging/
```

For each new library:

```text
<libraries_root>/
  <Library Name>/
    runs/
    library/
    library_definition.json
```

## Launcher

Source entrypoint:

```powershell
python analysis\bodaqs_import_agent_setup.py
```

Packaged Windows build target:

```powershell
.\analysis\build_import_agent.ps1 -Target setup
```

Output bundle:

```text
analysis/dist/pyinstaller/bodaqs-import-setup/
```

## Notes

- The manager window manages the app-settings file automatically and does not
  ask the user to choose that path during normal setup.
- The logger timezone field is presented as a dropdown seeded from the
  available IANA timezone list, with a blank option for "unspecified".
- In packaged builds, it will use the executable directory when that location
  is writable. If not, it falls back to the per-user app-data location.
- The shipped default asset package is discovered by content, not fixed
  filenames: it must contain exactly one valid preprocess-profile JSON file,
  one valid bike-profile JSON file, and one valid event-schema YAML file.
- Re-running the manager against the same app config can add another library
  and source under the same managed roots.
- The watcher CLI remains separate and unchanged; this windowed manager shares
  the same engine and provisioning backend.
