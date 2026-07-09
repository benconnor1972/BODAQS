# BODAQS Desktop Windows Installer v1

## Purpose

Phase 5A packages BODAQS Desktop into a Windows installer so the local desktop
tooling can be installed like a normal desktop application. The bundle stages
the Import Manager, the Library API service, and the built BODAQS Workbench
frontend together.

## What the Installer Includes

- BODAQS Import Manager at `manager/`
- BODAQS Library Service at `service/`
- BODAQS Workbench frontend at `service/web/`
- component version metadata at `component_versions.json`
- a Start Menu shortcut to the manager
- an optional desktop shortcut to the manager

The service is installed as a support component and is not exposed with a Start
Menu shortcut by default. The intended user-facing launch path is through the
Import Manager.

The Manager screen includes:

- `Open Web App`, which starts the bundled Library API service if needed and
  opens the Study Set Workbench in the user's default browser.
- `Stop Web App`, which stops the service only when this Manager instance
  started it.

If another process is already serving the Library API on the configured local
port, the Manager opens that existing service and leaves it running.

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
.\import-manager\build_import_manager.ps1 -Target installer
```

You can also override the Inno Setup compiler path, bundle version, or component
versions:

```powershell
.\import-manager\build_import_manager.ps1 -Target installer `
  -InnoSetupExe "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" `
  -BundleVersion "0.1.5-dev" `
  -ImportManagerVersion "0.1.5-beta" `
  -LibraryServiceVersion "0.1.0-dev" `
  -WorkbenchVersion "0.1.0-dev"
```

If the existing bundled manager and service outputs are already good and you only
want to restage or recompile the installer, you can skip the PyInstaller
rebuild:

```powershell
.\import-manager\build_import_manager.ps1 -Target installer -SkipPyInstallerBuild
```

If the service executable already exists and you only want to refresh the
bundled web app assets, use:

```powershell
.\import-manager\build_import_manager.ps1 -Target service -SkipPyInstallerBuild
```

The staged service can be smoke-tested with:

```powershell
.\import-manager\dist\pyinstaller\bodaqs-library-service\bodaqs-library-service.exe `
  --libraries-root "C:\Users\benco\OneDrive\BODAQS-data" `
  --host 127.0.0.1 `
  --port 8765 `
  --web-root ".\import-manager\dist\pyinstaller\bodaqs-library-service\web"
```

Then open `http://127.0.0.1:8765/`.

If `ISCC.exe` is not available, the build script still prepares the staged
payload under:

```text
import-manager/build/installer/windows/staging/
```

and reports that installer compilation was skipped.

## Outputs

- staged installer payload:
  `import-manager/build/installer/windows/staging/`
- compiled installer:
  `import-manager/dist/installer/windows/bodaqs-desktop-setup-<version>.exe`

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

## Branding Assets

Windows branding assets are generated from the existing BODAQS favicon source:

- source SVG: `bodocs/public/favicon.svg`
- tray PNG: `import-manager/bodaqs_import_manager/import_agent_assets/tray_icon.png`
- app PNG: `import-manager/bodaqs_import_manager/import_agent_assets/app_icon.png`
- runtime app icon: `import-manager/bodaqs_import_manager/import_agent_assets/app_icon.ico`
- app/installer icon: `import-manager/packaging/windows/bodaqs_import_agent.ico`

The helper script for regenerating those packaged assets is:

- `import-manager/tools/generate_import_agent_branding.py`

## Installer Script

The Windows installer definition lives at:

```text
import-manager/packaging/windows/bodaqs_import_agent_windows.iss
```
