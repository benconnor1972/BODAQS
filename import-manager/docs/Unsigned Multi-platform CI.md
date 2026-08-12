# Unsigned Multi-platform CI

The `Unsigned Desktop CI` GitHub Actions workflow validates BODAQS Desktop
builds on clean GitHub-hosted runners. It does not sign artifacts, use release
credentials, create GitHub Releases, or publish downloads.

## Triggers

The workflow runs for pull requests and `main` pushes that affect the desktop
application, analysis package, Workbench, dependencies, or workflow itself. It
can also be dispatched manually. `Desktop-v*` tags run the same unsigned build
as a release candidate, using the tag version without its `Desktop-v` prefix;
they do not publish a release.

## Outputs

Each successful run retains its unsigned build artifacts for seven days:

| Platform | Runner | Artifact |
| --- | --- | --- |
| Windows x64 | `windows-latest` | Inno Setup installer `.exe` |
| macOS arm64 | `macos-latest` | `.dmg` containing the application bundle |
| Linux x64 | `ubuntu-latest` | Portable PyInstaller `.tar.gz` bundle |

The Linux archive expands to a directory containing `bodaqs-import-manager`.
Run that executable from the expanded directory; its bundled `service/`
subdirectory contains the Library Service and Workbench files it needs.

## Local equivalents

Run the Python tests first:

```powershell
python -m pytest analysis/tests -q
```

Build the Windows installer:

```powershell
.\import-manager\build_import_manager.ps1 -Target installer -BundleVersion 0.0.0-dev
```

Build the unsigned macOS DMG from macOS:

```bash
./import-manager/build_import_manager_macos.sh --version 0.0.0-dev
```

Build the unsigned Linux archive from Linux:

```bash
./import-manager/build_import_manager_linux.sh --version 0.0.0-dev
```

The Windows and Linux scripts run packaged smoke tests. The macOS workflow runs
the same non-interactive tests against the executable within the app bundle.

## Workbench linting

The workflow runs Workbench linting on every platform, but it is currently
informational because the existing codebase has lint errors unrelated to this
CI setup. The TypeScript/Vite build remains mandatory as part of each desktop
package build. Once the baseline lint debt is resolved, remove
`continue-on-error` from the three lint steps in `desktop-ci.yml`.

## Future release work

Signing and publishing remain intentionally separate. A later release workflow
will consume these proven platform build steps, apply signing/notarization in
protected environments, verify the resulting artifacts, and then publish a
GitHub Release.
