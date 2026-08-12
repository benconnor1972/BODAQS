# Multi-platform Desktop CI

The `Desktop CI` GitHub Actions workflow validates BODAQS Desktop builds on
clean GitHub-hosted runners. Pull-request, branch, and manually dispatched
builds do not use release credentials and remain unsigned. A `Desktop-v*` tag
also creates a signed and notarized macOS DMG when its required GitHub Actions
secrets are configured. The workflow does not create GitHub Releases or publish
downloads.

## Triggers

The workflow runs for pull requests and `main` pushes that affect the desktop
application, analysis package, Workbench, dependencies, or workflow itself. It
can also be dispatched manually. `Desktop-v*` tags use the tag version without
its `Desktop-v` prefix. They sign, notarize, staple, and verify the macOS DMG
after tests and packaged smoke tests pass.

## Outputs

Each successful non-tag run retains unsigned build artifacts for seven days:

| Platform | Runner | Artifact |
| --- | --- | --- |
| Windows x64 | `windows-latest` | Inno Setup installer `.exe` |
| macOS arm64 | `macos-latest` | `.dmg` containing the application bundle |
| Linux x64 | `ubuntu-latest` | Portable PyInstaller `.tar.gz` bundle |

For a `Desktop-v*` tag, the macOS artifact is instead a signed and notarized
DMG named `macos-arm64-<version>`. Windows and Linux artifacts remain unsigned
until their platform signing workflows are added.

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
CI uses the committed macOS `.icns` asset rather than regenerating it, so the
hosted build does not need the optional `librsvg`/`rsvg-convert` dependency.

## Workbench linting

The workflow runs Workbench linting on every platform, but it is currently
informational because the existing codebase has lint errors unrelated to this
CI setup. The TypeScript/Vite build remains mandatory as part of each desktop
package build. Once the baseline lint debt is resolved, remove
`continue-on-error` from the three lint steps in `desktop-ci.yml`.

## macOS release signing

macOS signing runs only for a `Desktop-v*` tag. Configure these repository
Actions secrets before creating such a tag:

| Secret | Value |
| --- | --- |
| `APPLE_DEVELOPER_ID_P12_BASE64` | Base64 encoding of the Developer ID Application `.p12` bundle |
| `APPLE_DEVELOPER_ID_P12_PASSWORD` | Password selected when exporting that `.p12` bundle |
| `APPLE_NOTARY_API_KEY_BASE64` | Base64 encoding of the App Store Connect team API-key `.p8` file |
| `APPLE_NOTARY_KEY_ID` | App Store Connect API key ID |
| `APPLE_NOTARY_ISSUER_ID` | App Store Connect API issuer ID |

The workflow imports the certificate into a temporary runner keychain, applies
the hardened runtime and timestamp, signs the DMG, submits it to Apple
notarization, staples the ticket, and validates the final DMG. It never writes
these values to the repository or an artifact.

Signing and publishing remain separate: a maintainer must still inspect the
completed artifacts and create the GitHub Release deliberately.
