# BODAQS Import Manager / Tray App v1

## Purpose

The manager window is a small packaged desktop utility for provisioning,
extending, and operating a local BODAQS import-manager installation without
editing JSON files by hand.

It can:

- the managed app config
- add libraries under the chosen libraries root
- add sources under the chosen sources root
- seed default assets in `settings/` and `bike/`
- persist the Windows start-at-login preference
- validate managed sources
- run one-shot imports
- start and stop the in-process watch loop
- hide to the Windows system tray and keep running in the background

Branding is sourced from the existing BODAQS favicon/logo mark and packaged as:

- a tray PNG for the Windows system tray
- an app PNG for the live Tk manager window/taskbar icon
- an app `.ico` for the live Windows taskbar/window icon path
- a Windows `.ico` for the manager, CLI, and installer executables

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
    syn/
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

Installed Windows build target:

```powershell
.\analysis\build_import_agent.ps1 -Target installer
```

Installer output:

```text
analysis/dist/installer/windows/
```

## Notes

- The manager window manages the app-settings file automatically and does not
  ask the user to choose that path during normal setup.
- Logger timestamp interpretation comes from per-session log metadata; the
  manager does not ask for a logger timezone during normal source setup.
- On Windows, the manager can persist a start-at-login preference. Startup
  launches begin the watch loop automatically and hide the window to the tray.
- Closing the window hides it to the tray instead of quitting the app when the
  tray icon is available. Use the tray icon to reopen the manager or quit.
- The live manager window now sets its own branded icon at runtime through
  both Tk PNG and Windows `.ico` paths, and it applies an explicit
  AppUserModelID before creating the window so the taskbar is less likely to
  fall back to the generic Tk icon.
- The Libraries and Sources table headers are left-aligned to match the column
  content.
- Portable packaged builds will use the executable directory when that
  location is writable. If not, they fall back to the per-user app-data
  location.
- Installed Windows launches use an explicit installed-mode shortcut and keep
  the app config in the per-user app-data location even when the install
  directory would be writable.
- The shipped default asset package is discovered by content, not fixed
  filenames: it must contain exactly one valid preprocess-profile JSON file,
  one valid bike-profile JSON file, and one valid event-schema YAML file.
- Re-running the manager against the same app config can add another library
  and source under the same managed roots.
- Libraries can opt in to data.syn.bike exports. When enabled, new imports
  write headerless CSV files and per-session manual-settings helper text files
  under the library's `syn/` directory.
- The watcher CLI remains separate and unchanged; this windowed manager shares
  the same engine and provisioning backend.
