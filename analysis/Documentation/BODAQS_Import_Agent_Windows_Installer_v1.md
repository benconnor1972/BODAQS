# BODAQS Import Agent Windows Installer v1

## Purpose

Phase 5A packages the existing manager and CLI bundles into a Windows installer
so the import agent can be installed like a normal desktop application.

## What the Installer Includes

- the windowed manager bundle at `manager/`
- the CLI watcher bundle at `cli/`
- a Start Menu shortcut to the manager
- an optional desktop shortcut to the manager

The CLI is installed as a support/debug tool but is not exposed with a Start
Menu shortcut by default.

## Wi-Fi Logger Source Support

The Windows bundles include the Wi-Fi logger source modules used by both the
CLI importer and the manager.

This support does not add a third-party network dependency. The logger API
client uses Python standard-library outbound HTTP calls, so the installed
manager should not need an inbound Windows Firewall exception. If a logger is
offline or unreachable during watch mode, the source reports a remote status
error without raising a modal dialog or marking the local import scan as a
failed archive import.

## Build

First make sure PyInstaller is available in the repo environment.

If Inno Setup 6 is installed in its normal Windows location, build the
installer with:

```powershell
.\analysis\build_import_agent.ps1 -Target installer
```

You can also override the Inno Setup compiler path or the installer version:

```powershell
.\analysis\build_import_agent.ps1 -Target installer `
  -InnoSetupExe "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" `
  -AppVersion "0.1.0-dev"
```

If the existing bundled CLI or manager outputs are already good and you only
want to restage or recompile the installer, you can skip the PyInstaller
rebuild:

```powershell
.\analysis\build_import_agent.ps1 -Target installer -SkipPyInstallerBuild
```

If `ISCC.exe` is not available, the build script still prepares the staged
payload under:

```text
analysis/build/installer/windows/staging/
```

and reports that installer compilation was skipped.

## Outputs

- staged installer payload:
  `analysis/build/installer/windows/staging/`
- compiled installer:
  `analysis/dist/installer/windows/bodaqs-import-agent-setup-<version>.exe`

## Config Location Behavior

The installed app launches the manager with:

```text
--app-config-mode installed
```

That forces the managed app config to live in the per-user app-data location
instead of beside the installed executable. This keeps user state separate from
installed binaries and makes upgrades/uninstall safer.

## Start At Login

The installer itself stays thin and does not write the Windows login-start
entry directly.

Instead, the installed manager owns that preference:

- the managed app config stores `auto_start`
- the manager writes or removes the per-user `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
  entry
- the registered command launches the manager in installed mode with
  `--startup-launch`

Startup launches:

- reuse the installed app-data config location
- start the watch loop automatically when `auto_start` is enabled
- hide the manager window to the tray

Portable bundled runs still keep the older behavior:

- prefer the executable directory when it is writable
- otherwise fall back to per-user app-data

## Uninstall Behavior

The Inno Setup installer is configured to detect running manager/CLI processes
and ask Windows to close them during uninstall. As a fallback, the uninstall
script stops installed `bodaqs-import-setup.exe` and `bodaqs-import.exe`
processes before files are removed, which avoids leaving PyInstaller bundle
files behind when the tray app or watcher is still running.

Uninstall also removes the per-user `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
value named `BODAQS Import Agent` so start-at-login does not point at a removed
install.

## Branding Assets

Windows branding assets are generated from the existing BODAQS favicon source:

- source SVG: [bodocs/public/favicon.svg](/C:/Users/benco/dev/BODAQS/bodocs/public/favicon.svg)
- tray PNG: [tray_icon.png](/C:/Users/benco/dev/BODAQS/analysis/bodaqs_analysis/import_agent_assets/tray_icon.png)
- app PNG: [app_icon.png](/C:/Users/benco/dev/BODAQS/analysis/bodaqs_analysis/import_agent_assets/app_icon.png)
- runtime app icon: [app_icon.ico](/C:/Users/benco/dev/BODAQS/analysis/bodaqs_analysis/import_agent_assets/app_icon.ico)
- app/installer icon: [bodaqs_import_agent.ico](/C:/Users/benco/dev/BODAQS/analysis/import-agent/windows/bodaqs_import_agent.ico)

The helper script for regenerating those packaged assets is:

- [generate_import_agent_branding.py](/C:/Users/benco/dev/BODAQS/analysis/import-agent/generate_import_agent_branding.py)

## Installer Script

The Windows installer definition lives at:

```text
analysis/import-agent/windows/bodaqs_import_agent_windows.iss
```
