# BODAQS Import Manager macOS Coding Agent Notes

This file is for a coding agent helping with macOS packaging. It complements
`import-manager/docs/macOS Packaging Handoff.md`, which is the human-facing
handoff.

The most important instruction: keep Windows behavior stable. Add macOS support
behind platform seams rather than renaming or rewriting the existing
`import_agent` modules.

## Current Naming

User-facing product name:

- `BODAQS Import Manager`

Internal/module naming still uses `import_agent`:

- manager modules: `import-manager/bodaqs_import_manager/import_agent*.py`
- engine modules: `analysis/bodaqs_analysis/import_agent*.py`
- app config filename: `import_agent_app.json`
- default app config dir segment: `import-agent`
- CLI executable: `bodaqs-import`
- existing manager executable name on Windows: `bodaqs-import-setup`

Do not mass-rename internals. The rebrand was intentionally user-facing only.

## Module Layout (read this first)

The manager implementation lives in the `bodaqs_import_manager` package:

- `import-manager/bodaqs_import_manager/import_agent_*.py`

The `analysis/bodaqs_analysis/` directory holds two kinds of `import_agent*`
files:

- thin re-export shims for the manager modules
  (`import_agent_setup.py`, `import_agent_provisioning.py`,
  `import_agent_startup.py`, `import_agent_tray.py`,
  `import_agent_single_instance.py`, `import_agent_profile_builders.py`).
  Each does `from bodaqs_import_manager.import_agent_* import *` after calling
  `_ensure_import_manager_path()`.
- the real import engine and Wi-Fi modules
  (`import_agent.py`, `import_agent_logger_wifi.py`,
  `import_agent_logger_wifi_discovery.py`, `import_agent_sources.py`).

So when editing manager behavior, edit the files under
`import-manager/bodaqs_import_manager/`, not the `analysis/bodaqs_analysis/`
shims. Byte-compiling or grepping the shims will not surface bugs in the real
modules.

Two newer manager modules that were not present in the original handoff:

- `import_agent_single_instance.py` — `SingleInstanceLock`, a per-config
  exclusive file lock. It is **already cross-platform**: it uses `msvcrt` on
  Windows and `fcntl.flock` elsewhere, so it needs no macOS-specific work. The
  GUI acquires it in `main()` via `SingleInstanceLock.for_app_config(...)`.
- `import_agent_profile_builders.py` — bike/preprocess profile and session-note
  builder helpers used by the setup UI. No known macOS-specific concerns.

## High-Value Files To Inspect First

- `import-manager/bodaqs_import_manager/import_agent_setup.py`
- `import-manager/bodaqs_import_manager/import_agent_provisioning.py`
- `import-manager/bodaqs_import_manager/import_agent_startup.py`
- `import-manager/bodaqs_import_manager/import_agent_tray.py`
- `analysis/bodaqs_analysis/import_agent_logger_wifi_discovery.py`
- `import-manager/bodaqs_import_agent_setup.spec`
- `import-manager/bodaqs_import_agent_cli.spec`
- `import-manager/build_import_manager.ps1`
- `analysis/tests/test_import_agent.py`
- `analysis/tests/test_import_agent_logger_wifi.py`

The GUI entry script is intentionally tiny:

```python
from bodaqs_import_manager.import_agent_setup import main
```

The packaged macOS app should call the same entrypoint.

## Platform Seams That Need Work

### App Config Location

Current implementation:

- `import-manager/bodaqs_import_manager/import_agent_provisioning.py`
- functions:
  - `default_import_agent_app_config_dir`
  - `default_import_agent_app_config_path`
  - `runtime_import_agent_app_config_path`

macOS support already exists for:

```text
~/Library/Application Support/BODAQS/import-agent/import_agent_app.json
```

Likely action:

- Add/keep tests for `platform="darwin"`.
- Ensure packaged macOS launches with `--app-config-mode installed`.

Suggested test:

```python
def test_default_import_agent_app_config_path_uses_macos_convention():
    path = default_import_agent_app_config_path(platform="darwin", home="/Users/Test")
    assert path == Path("/Users/Test/Library/Application Support/BODAQS/import-agent/import_agent_app.json")
```

### Startup Registration

Current module is Windows-specific:

- `import-manager/bodaqs_import_manager/import_agent_startup.py`

Current UI imports these names directly:

- `build_windows_startup_command`
- `sync_windows_startup_registration`
- `windows_startup_supported`

Better shape for macOS:

- Preserve the Windows functions for compatibility/tests.
- Add generic wrappers, for example:
  - `startup_supported(platform=None)`
  - `build_startup_command(argv)`
  - `sync_startup_registration(enabled, command, app_label, platform=None, ...)`
  - `read_startup_registration(platform=None, ...)`
- Update `import_agent_setup.py` to call generic wrappers.
- Keep existing Windows tests passing.

macOS v1 implementation recommendation:

- write a LaunchAgent plist under `~/Library/LaunchAgents/`
- label: `org.bodaqs.importmanager`
- command should launch the bundled app/executable with:
  - `--app-config-mode installed`
  - `--startup-launch`
- load/unload with `launchctl bootstrap gui/<uid>` and `launchctl bootout`
  where practical; for tests, keep the file-writing logic pure and injectable.

Suggested macOS LaunchAgent path:

```text
~/Library/LaunchAgents/org.bodaqs.importmanager.plist
```

Keep a testable pure function for generating the plist payload.

### Tray / Menu-Bar

Current module:

- `import-manager/bodaqs_import_manager/import_agent_tray.py`

Current support gate:

```python
return resolved_platform.startswith("win") and pystray is not None and Image is not None and ImageDraw is not None
```

Likely action:

- Try enabling `darwin` if `pystray` works acceptably:

```python
return (
    (resolved_platform.startswith("win") or resolved_platform == "darwin")
    and pystray is not None
    and Image is not None
    and ImageDraw is not None
)
```

- Add hidden import `pystray._darwin` to the macOS PyInstaller spec.
- If pystray is poor on macOS, leave tray disabled and let the app behave as a
  normal windowed app for v1.

Do not block packaging on tray polish.

### Windows App User Model ID

Current function:

- `_apply_windows_app_user_model_id` in `import_agent_setup.py`

This is already a no-op unless `sys.platform.startswith("win")`. It should not
need macOS changes.

## PyInstaller macOS Spec Notes

Create a separate spec rather than mutating the Windows spec too much:

- proposed: `import-manager/bodaqs_import_manager_macos.spec`

Base on:

- `import-manager/bodaqs_import_agent_setup.spec`

Keep:

- `collect_data_files("bodaqs_import_manager.import_agent_assets")`
- excludes for notebook/dev-only packages
- hidden imports for Wi-Fi source and zeroconf

Add or adjust:

- app name: `BODAQS Import Manager`
- bundle identifier: `org.bodaqs.importmanager`
- icon: `import-manager/packaging/macos/bodaqs_import_manager.icns`
- macOS `Info.plist` entries:
  - `NSLocalNetworkUsageDescription`
  - `NSBonjourServices` with `_bodaqs-logger._tcp`
- possibly `pystray._darwin`

The Windows spec currently creates a one-dir bundle named
`bodaqs-import-setup`. On macOS, use a `BUNDLE` block so the result is a normal
`.app`.

Sketch only:

```python
app = BUNDLE(
    coll,
    name="BODAQS Import Manager.app",
    icon=str(app_icon_path),
    bundle_identifier="org.bodaqs.importmanager",
    info_plist={
        "CFBundleName": "BODAQS Import Manager",
        "CFBundleDisplayName": "BODAQS Import Manager",
        "NSLocalNetworkUsageDescription": (
            "BODAQS Import Manager uses the local network to discover and "
            "download sessions from BODAQS loggers."
        ),
        "NSBonjourServices": ["_bodaqs-logger._tcp"],
    },
)
```

Check current PyInstaller docs/examples for exact `EXE`, `COLLECT`, and
`BUNDLE` shape for the version installed on the Mac.

## mDNS / Local Network Details

Discovery constant:

- `analysis/bodaqs_analysis/import_agent_logger_wifi_discovery.py`
- `BODAQS_LOGGER_SERVICE_TYPE = "_bodaqs-logger._tcp.local."`

Firmware advertises:

- service type: `_bodaqs-logger._tcp`
- port: `80`
- TXT records include `api`, `logger_id`, `upload_mode`, `hostname`

macOS `Info.plist` should use:

```text
_bodaqs-logger._tcp
```

not the fully-qualified `.local.` form.

Important runtime behavior:

- Discovery may fail because local-network permission is denied.
- Discovery may fail because VPN/firewall blocks multicast.
- A source may still work with a manually entered IP/base URL even if mDNS
  fails.

Tests to keep green:

```bash
cd analysis
python -m pytest tests/test_import_agent_logger_wifi.py -q
```

## Branding Notes

Source SVG:

- `bodocs/public/favicon.svg`

Existing helper:

- `import-manager/tools/generate_import_agent_branding.py`

Existing outputs:

- `import-manager/bodaqs_import_manager/import_agent_assets/app_icon.png`
- `import-manager/bodaqs_import_manager/import_agent_assets/tray_icon.png`
- `import-manager/bodaqs_import_manager/import_agent_assets/app_icon.ico`
- `import-manager/packaging/windows/bodaqs_import_agent.ico`

Add macOS outputs under:

- `import-manager/packaging/macos/`

Suggested file:

- `import-manager/packaging/macos/bodaqs_import_manager.icns`

Do not replace the Windows ICO unless intentionally updating Windows branding.

## Build Script Strategy

The current Windows build script is PowerShell:

- `import-manager/build_import_manager.ps1`

For macOS, prefer a separate shell script:

- proposed: `import-manager/build_import_manager_macos.sh`

Responsibilities:

- verify PyInstaller is importable
- clean macOS build/dist paths
- run the macOS spec
- optionally sign
- optionally notarize
- optionally create DMG

Keep signing/notarization optional via flags/env vars so unsigned local builds
remain easy.

Suggested outputs:

```text
import-manager/dist/pyinstaller/BODAQS Import Manager.app
import-manager/dist/BODAQS-Import-Manager-<version>.dmg
```

## Tests To Run After Code Changes

Focused import-manager tests:

```bash
cd analysis
python -m pytest tests/test_import_agent.py tests/test_import_agent_logger_wifi.py -q
```

Compile changed modules (run from the repo root; compile the real modules, not
the `analysis/bodaqs_analysis/` shims):

```bash
python -m compileall \
  import-manager/bodaqs_import_manager/import_agent_setup.py \
  import-manager/bodaqs_import_manager/import_agent_provisioning.py \
  import-manager/bodaqs_import_manager/import_agent_startup.py \
  import-manager/bodaqs_import_manager/import_agent_tray.py \
  analysis/bodaqs_analysis/import_agent_logger_wifi_discovery.py
```

From repo root, check whitespace:

```bash
git diff --check
```

Full test suite may have unrelated legacy failures. If it fails outside
import-manager tests, report the failures rather than "fixing" unrelated
preprocessing behavior.

## Suggested New Tests

Add tests near the existing startup/app-config/tray tests in:

- `analysis/tests/test_import_agent.py`

Suggested tests:

- macOS app config path uses Application Support.
- generic startup command still quotes paths with spaces.
- macOS LaunchAgent plist generation includes:
  - `Label`
  - `ProgramArguments`
  - `RunAtLoad`
  - `--startup-launch`
  - `--app-config-mode installed`
- disabling macOS startup removes or unloads the LaunchAgent using injected
  filesystem/subprocess fakes.
- `tray_supported(platform="darwin")` behavior is explicit, whichever decision
  is made.

If a macOS PyInstaller spec is added, consider a lightweight static test that
asserts the spec file contains:

- `org.bodaqs.importmanager`
- `NSLocalNetworkUsageDescription`
- `_bodaqs-logger._tcp`

## Signing / Notarization Agent Notes

Do not hard-code identities, passwords, Apple IDs, or team IDs.

Use env vars or CI secrets, for example:

- `BODAQS_MAC_CODESIGN_IDENTITY`
- `BODAQS_MAC_NOTARY_PROFILE`
- `BODAQS_APP_VERSION`

Signing can be scripted, but keep the unsigned build path first-class.

When notarization fails:

- fetch the notary log
- look for unsigned nested `.dylib`, `.so`, or Python extension modules
- sign nested binaries explicitly if needed
- only then re-sign the outer `.app`

Avoid using `--deep` as the only signing strategy if it masks nested failures.
It is acceptable for a first attempt, but release signing may need an explicit
walk of the bundle.

## Manual Test Checklist For The Agent To Preserve

After a successful unsigned local app build:

- `open "dist/pyinstaller/BODAQS Import Manager.app"` launches the UI.
- The app title says `BODAQS Import Manager`.
- First-run setup creates a source and library.
- App config lands under Application Support in installed mode.
- A local archive can be imported.
- A Wi-Fi logger can be discovered or manually checked on the LAN.

After signing/notarization:

- `codesign --verify --deep --strict --verbose=2` passes.
- `spctl --assess --type execute --verbose=4` passes.
- DMG opens cleanly.
- App launches from `/Applications`.
- Local network prompt appears when discovery is attempted.

## Things Not To Do

- Do not rename `bodaqs_import_manager.import_agent*` or
  `bodaqs_analysis.import_agent*` modules, and do not break the
  `analysis/bodaqs_analysis/` re-export shims.
- Do not remove Windows startup/tray behavior.
- Do not make source/library paths live inside the `.app`.
- Do not require admin privileges for v1.
- Do not make notarization a prerequisite for local unsigned development builds.
- Do not introduce a database or cloud dependency.
- Do not edit example datasets under `Examples/logs/`.
