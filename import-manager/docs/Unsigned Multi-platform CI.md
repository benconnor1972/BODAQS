# Multi-platform Desktop CI

The `Desktop CI` GitHub Actions workflow validates BODAQS Desktop builds on
clean GitHub-hosted runners. Pull-request, branch, and manually dispatched
builds do not use release credentials and remain unsigned. A `Desktop-v*` tag
creates a signed and notarized macOS DMG when its required GitHub Actions
secrets are configured, and keylessly signs the Linux archive with Sigstore.
The workflow does not create GitHub Releases or publish downloads.

## Triggers

The workflow runs for pull requests and `main` pushes that affect the desktop
application, analysis package, Workbench, dependencies, or workflow itself. It
can also be dispatched manually. `Desktop-v*` tags use the tag version without
its `Desktop-v` prefix. They sign, notarize, staple, and verify the macOS DMG,
and create and verify a keyless Sigstore signature bundle for the Linux archive,
after tests and packaged smoke tests pass.

## Outputs

Each successful non-tag run retains unsigned build artifacts for seven days:

| Platform | Runner | Artifact |
| --- | --- | --- |
| Windows x64 | `windows-latest` | Inno Setup installer `.exe` |
| macOS arm64 | `macos-latest` | `.dmg` containing the application bundle |
| Linux x64 | `ubuntu-latest` | Portable PyInstaller `.tar.gz` bundle |

For a `Desktop-v*` tag, the macOS artifact is instead a signed and notarized
DMG named `macos-arm64-<version>`. The Linux artifact is
`linux-x64-<version>` and contains the archive plus its
`.tar.gz.sigstore.json` verification bundle. Windows artifacts remain unsigned
until their SignPath workflow is added.

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

## Workbench validation

Workbench linting is not currently run by this platform workflow because the
existing lint baseline produces non-actionable annotations on every platform.
The TypeScript/Vite build remains mandatory as part of each desktop package
build. Restore linting as a separate required CI check after the baseline lint
debt is resolved.

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

## Linux release signing

Linux signing runs only for a `Desktop-v*` tag and uses Sigstore keyless
signing with the GitHub Actions OpenID Connect identity. It does not require a
stored signing key or GitHub secret. The corresponding artifact contains both
the Linux archive and its `.sigstore.json` bundle.

To verify a downloaded release, install a current version of
[Cosign](https://docs.sigstore.dev/cosign/system_config/installation/) and run:

```bash
cosign verify-blob BODAQS-Import-Manager-<version>-linux-x64.tar.gz \
  --bundle BODAQS-Import-Manager-<version>-linux-x64.tar.gz.sigstore.json \
  --certificate-identity "https://github.com/benconnor1972/BODAQS/.github/workflows/desktop-ci.yml@refs/tags/Desktop-v<version>" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com"
```

Replace `<version>` with the release version, for example `0.2.2-beta`.
