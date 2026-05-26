# BODAQS Import Manager macOS Packaging Handoff

This note is for a technically experienced Mac developer who is taking over
macOS packaging for the BODAQS Import Manager. It assumes good general
development experience, but no prior experience shipping signed/notarized
macOS desktop packages.

The goal is to produce a normal user-installable macOS release of:

- `BODAQS Import Manager.app`
- distributed in a signed and notarized DMG
- able to provision local sources/libraries, watch local files, discover Wi-Fi
  loggers with mDNS, download sessions, and run the existing import pipeline

## Current Repo Context

Work from the repository root.

Important entrypoints:

- Manager GUI entrypoint: `import-manager/bodaqs_import_agent_setup.py`
- CLI/import-agent entrypoint: `import-manager/bodaqs_import_agent_cli.py`
- Manager implementation: `import-manager/bodaqs_import_manager/import_agent_setup.py`
- Core import engine: `analysis/bodaqs_analysis/import_agent.py`
- Wi-Fi logger API client: `analysis/bodaqs_analysis/import_agent_logger_wifi.py`
- mDNS discovery: `analysis/bodaqs_analysis/import_agent_logger_wifi_discovery.py`
- Startup integration, currently Windows-focused: `import-manager/bodaqs_import_manager/import_agent_startup.py`
- Tray/menu integration, currently Windows-gated: `import-manager/bodaqs_import_manager/import_agent_tray.py`
- App/source/library provisioning: `import-manager/bodaqs_import_manager/import_agent_provisioning.py`

Existing Windows packaging references:

- PyInstaller manager spec: `import-manager/bodaqs_import_agent_setup.spec`
- PyInstaller CLI spec: `import-manager/bodaqs_import_agent_cli.spec`
- Windows build script: `import-manager/build_import_manager.ps1`
- Inno Setup installer script: `import-manager/packaging/windows/bodaqs_import_agent_windows.iss`
- Windows installer docs: `import-manager/docs/windows/BODAQS_Import_Agent_Windows_Installer_v1.md`

Branding and default assets:

- Logo source of truth: `bodocs/public/favicon.svg`
- Branding generation helper: `import-manager/tools/generate_import_agent_branding.py`
- Runtime app icon PNG: `import-manager/bodaqs_import_manager/import_agent_assets/app_icon.png`
- Runtime app icon ICO: `import-manager/bodaqs_import_manager/import_agent_assets/app_icon.ico`
- Tray icon PNG: `import-manager/bodaqs_import_manager/import_agent_assets/tray_icon.png`
- Windows ICO: `import-manager/packaging/windows/bodaqs_import_agent.ico`
- Seeded import-source defaults: `import-manager/bodaqs_import_manager/import_agent_assets/`

Planning document already in the repo:

- `import-manager/docs/Phase 6 macOS Plan.md`

## Product Shape

Recommended v1 shape:

- Build a windowed `BODAQS Import Manager.app`.
- Package it in a DMG with an `/Applications` shortcut.
- Do not build a `.pkg` installer for v1 unless a later requirement needs
  privileged install steps.
- Keep user-created data outside the app bundle.

The app already has first-run setup and provisioning UI, so a DMG is enough for
the first Mac release.

## Important Current Behavior

The manager is not just a file watcher anymore. It now supports:

- multiple local libraries
- multiple import sources
- local folder/archive sources
- Wi-Fi logger sources
- mDNS discovery using `_bodaqs-logger._tcp.local.`
- logger upload-mode checks
- FIT enrichment when enabled in source settings
- data.syn.bike export when enabled per library
- draft session notes generated from source note templates/presets
- start-at-login preference
- tray/menu behavior on Windows

That means macOS packaging must handle local filesystem access, local network
access, mDNS/Bonjour behavior, and background/start-at-login behavior.

## Build Machine Recommendation

Use a modern Mac or a macOS CI runner for release builds.

Practical recommendation:

- Best local release machine: Apple Silicon Mac running a current supported
  macOS and current Xcode command line tools.
- Good CI option: GitHub Actions macOS runners.
- Good cloud option: AWS EC2 Mac or a hosted Mac provider such as MacStadium.
- Old Intel MacBook: useful for Intel smoke tests, but not ideal as the release
  signing/notarization machine.

Reasoning:

- PyInstaller must run on macOS to build macOS apps.
- PyInstaller builds are forward-compatible from the macOS version they are
  built on, so the oldest supported macOS version affects the build host choice.
- Apple notarization now expects the modern `notarytool` workflow, which means
  modern Xcode command line tools.
- Apple Silicon support requires either an arm64 build host/runner or a
  universal2-capable build environment.

Suggested first target:

- Produce an unsigned local `x86_64` or `arm64` app first.
- Then add signing/notarization.
- Then decide whether to ship separate Intel/Apple Silicon builds or a
  universal2 build.

For v1, separate Intel and Apple Silicon DMGs may be easier to debug than a
single universal2 bundle, especially because scientific Python dependencies can
make universal builds large and fiddly.

## Local Development Setup On macOS

From a clean checkout:

```bash
cd /path/to/BODAQS
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller pillow
```

Run the manager from source:

```bash
cd analysis
python bodaqs_import_agent_setup.py
```

Run focused tests before packaging:

```bash
cd analysis
python -m pytest tests/test_import_agent.py tests/test_import_agent_logger_wifi.py -q
```

If dependency wheels are unavailable for the chosen macOS/Python combination,
try a newer macOS runner first before attempting source builds of NumPy/SciPy.

## Code Changes Needed Before Packaging

### 1. macOS PyInstaller Spec

Create a macOS-specific spec, for example:

- `import-manager/bodaqs_import_manager_macos.spec`

Base it on:

- `import-manager/bodaqs_import_agent_setup.spec`

Keep these essentials:

- entry script: `bodaqs_import_agent_setup.py`
- package data: `collect_data_files("bodaqs_import_manager.import_agent_assets")`
- hidden imports:
  - `bodaqs_analysis.import_agent_logger_wifi`
  - `bodaqs_analysis.import_agent_logger_wifi_discovery`
  - `bodaqs_analysis.import_agent_sources`
  - `zeroconf`
  - `pystray._darwin` if tray/menu-bar support is enabled

Set app name:

- `BODAQS Import Manager`

Suggested bundle identifier:

- `org.bodaqs.importmanager`

The Windows specs currently use Windows ICO assets. macOS should use an `.icns`
file instead.

### 2. macOS Icon

Generate:

- `import-manager/packaging/macos/bodaqs_import_manager.icns`

Use the existing logo source:

- `bodocs/public/favicon.svg`

The existing helper may need extending:

- `import-manager/tools/generate_import_agent_branding.py`

Expected output sizes for `.icns` normally include 16, 32, 64, 128, 256, 512,
and 1024 px variants. The exact toolchain is flexible as long as the final app
bundle gets a proper `.icns`.

### 3. Info.plist

The app bundle needs a macOS `Info.plist` with normal identity fields and local
network privacy fields.

Required/strongly recommended fields:

```xml
<key>CFBundleName</key>
<string>BODAQS Import Manager</string>
<key>CFBundleDisplayName</key>
<string>BODAQS Import Manager</string>
<key>CFBundleIdentifier</key>
<string>org.bodaqs.importmanager</string>
<key>CFBundleShortVersionString</key>
<string>0.1.0-dev</string>
<key>CFBundleVersion</key>
<string>0.1.0-dev</string>
<key>NSLocalNetworkUsageDescription</key>
<string>BODAQS Import Manager uses the local network to discover and download sessions from BODAQS loggers.</string>
<key>NSBonjourServices</key>
<array>
  <string>_bodaqs-logger._tcp</string>
</array>
```

Do not make the app agent-only (`LSUIElement`) for v1 unless the UI/tray model
is deliberately redesigned. It should be a normal visible app with a Dock icon.

### 4. Local Network And mDNS

The Wi-Fi logger discovery service is:

- `_bodaqs-logger._tcp.local.`

The Python constant is in:

- `analysis/bodaqs_analysis/import_agent_logger_wifi_discovery.py`

macOS local-network privacy is now a real release risk. Test this early:

- launch app
- trigger logger discovery
- confirm macOS prompts for local network access
- allow access
- confirm discovery sees the logger
- deny access and confirm the app reports the problem sensibly

The current discovery uses the Python `zeroconf` package. If zeroconf multicast
behavior proves unreliable on macOS, consider a small macOS-specific discovery
backend using Apple's Bonjour APIs. Keep the public app behavior the same.

### 5. App Config Location

The app already has macOS installed-mode path support:

- `import-manager/bodaqs_import_manager/import_agent_provisioning.py`

Current macOS location:

```text
~/Library/Application Support/BODAQS/import-agent/import_agent_app.json
```

The packaged macOS app should launch with:

```text
--app-config-mode installed
```

This mirrors the installed Windows behavior and keeps user state out of the app
bundle.

### 6. Start At Login

Current startup integration is Windows-specific:

- `import-manager/bodaqs_import_manager/import_agent_startup.py`

Implement a platform abstraction rather than putting macOS logic directly into
the UI code.

Recommended v1 implementation:

- per-user LaunchAgent plist in `~/Library/LaunchAgents/`
- command launches the app executable with:
  - `--app-config-mode installed`
  - `--startup-launch`
- preserve the existing app-facing `auto_start` preference

Test cases:

- enabling start at login creates/loads the LaunchAgent
- disabling it unloads/removes the LaunchAgent
- login launch starts the watch loop
- login launch hides or minimizes according to the existing startup behavior

If LaunchAgent handling feels too fragile for a bundled `.app`, defer
start-at-login for the first unsigned test build but do not ship without a
clear decision.

### 7. Tray / Menu-Bar Behavior

Current tray support is Windows-gated:

- `import-manager/bodaqs_import_manager/import_agent_tray.py`

On macOS, evaluate whether `pystray` gives an acceptable menu-bar item.

Possible outcomes:

- If `pystray` works well, enable it on `darwin` and include `pystray._darwin`
  in the spec.
- If it is flaky or un-native, ship v1 as a normal windowed app and defer
  menu-bar/background polish.

Do not let tray work block the first successful signed app build.

## Build Commands

A first unsigned build will look roughly like:

```bash
cd analysis
python -m PyInstaller \
  --noconfirm \
  --clean \
  --distpath dist/pyinstaller \
  --workpath build/pyinstaller \
  bodaqs_import_manager_macos.spec
```

Expected unsigned output:

```text
import-manager/dist/pyinstaller/BODAQS Import Manager.app
```

Open locally:

```bash
open "dist/pyinstaller/BODAQS Import Manager.app"
```

If PyInstaller creates a one-dir folder rather than a clean `.app`, adjust the
spec to use a macOS `BUNDLE` block.

## Signing And Notarization

Public macOS distribution outside the App Store should use Developer ID:

- Apple Developer Program membership
- Developer ID Application certificate
- Xcode command line tools
- `notarytool`
- hardened runtime signing

Create/store notarization credentials first:

```bash
xcrun notarytool store-credentials "BODAQS-notary" \
  --apple-id "APPLE_ID_EMAIL" \
  --team-id "TEAM_ID" \
  --password "APP_SPECIFIC_PASSWORD"
```

Sign the app:

```bash
codesign --force --deep --options runtime --timestamp \
  --sign "Developer ID Application: YOUR NAME (TEAMID)" \
  "dist/pyinstaller/BODAQS Import Manager.app"
```

Verify:

```bash
codesign --verify --deep --strict --verbose=2 \
  "dist/pyinstaller/BODAQS Import Manager.app"

spctl --assess --type execute --verbose=4 \
  "dist/pyinstaller/BODAQS Import Manager.app"
```

If signing fails, sign nested binaries/frameworks explicitly rather than relying
only on `--deep`. PyInstaller apps often contain nested `.dylib` and extension
modules.

Notarize the app:

```bash
ditto -c -k --keepParent \
  "dist/pyinstaller/BODAQS Import Manager.app" \
  "dist/pyinstaller/BODAQS-Import-Manager.zip"

xcrun notarytool submit \
  "dist/pyinstaller/BODAQS-Import-Manager.zip" \
  --keychain-profile "BODAQS-notary" \
  --wait

xcrun stapler staple \
  "dist/pyinstaller/BODAQS Import Manager.app"
```

## DMG Packaging

Create a staging folder with:

- `BODAQS Import Manager.app`
- symlink to `/Applications`
- optional short README

Example:

```bash
mkdir -p build/dmg-root
cp -R "dist/pyinstaller/BODAQS Import Manager.app" build/dmg-root/
ln -s /Applications build/dmg-root/Applications

hdiutil create \
  -volname "BODAQS Import Manager" \
  -srcfolder build/dmg-root \
  -ov \
  -format UDZO \
  "dist/BODAQS-Import-Manager-0.1.0-dev.dmg"
```

Then sign, notarize, and staple the DMG:

```bash
codesign --force --timestamp \
  --sign "Developer ID Application: YOUR NAME (TEAMID)" \
  "dist/BODAQS-Import-Manager-0.1.0-dev.dmg"

xcrun notarytool submit \
  "dist/BODAQS-Import-Manager-0.1.0-dev.dmg" \
  --keychain-profile "BODAQS-notary" \
  --wait

xcrun stapler staple \
  "dist/BODAQS-Import-Manager-0.1.0-dev.dmg"
```

Final release artifact:

```text
import-manager/dist/BODAQS-Import-Manager-<version>.dmg
```

## Test Plan

Use a clean user account or a clean Mac VM where possible.

### Basic app tests

- Launch from Finder.
- Confirm app title says `BODAQS Import Manager`.
- Confirm the app icon appears correctly in Finder, Dock, and app switcher.
- Confirm first-run setup can create:
  - sources root
  - libraries root
  - default library
  - default source
- Confirm app config is written to:
  - `~/Library/Application Support/BODAQS/import-agent/import_agent_app.json`

### Local archive import tests

- Create a local source.
- Drop a known-good logger archive into the source inbox.
- Run `Import Now`.
- Confirm a run appears in the target library.
- Confirm artifacts, draft notes, optional FIT enrichment, and optional syn
  export behave the same as Windows.

### Wi-Fi logger tests

- Put a logger on the same network.
- Put the logger into upload mode.
- Use discovery in the manager.
- Confirm the macOS local-network permission prompt appears.
- Confirm discovery finds `_bodaqs-logger._tcp`.
- Add the logger as a source.
- Run `Check Logger`.
- Run import/download.
- Confirm partial downloads are not imported.
- Confirm completed downloads are imported and acknowledged.

### Background/startup tests

- Enable start at login.
- Log out and back in.
- Confirm the manager starts in startup mode.
- Confirm watch mode starts only when expected.
- Disable start at login and confirm it no longer starts.

### Gatekeeper tests

- Copy the DMG as if downloaded from the internet, or test on another Mac.
- Open the DMG and drag the app to `/Applications`.
- Launch from Finder.
- Confirm there is no "unidentified developer" block.
- Run:

```bash
spctl --assess --type execute --verbose=4 "/Applications/BODAQS Import Manager.app"
```

## CI / Online Build Options

### GitHub Actions

Good first choice for repeatable builds.

Use macOS runners:

- Intel: `macos-15-intel`
- Apple Silicon: `macos-15` or another arm64 macOS runner

Store signing/notarization material as GitHub Actions secrets:

- Developer ID certificate as base64 `.p12`
- certificate password
- Apple team ID
- notarization credentials, preferably notary API key or a keychain profile set
  up during the workflow

CI should:

- install Python
- create venv
- install requirements, PyInstaller, Pillow
- build `.app`
- sign
- notarize
- create DMG
- notarize/staple DMG
- upload DMG artifact

Do not rely on GitHub Actions for real logger discovery testing. Hosted runners
will not be on the same LAN as the logger.

### AWS EC2 Mac / Hosted Mac

Good for heavier release work or manual debugging.

Pros:

- real Apple hardware
- suitable for signing/notarization
- easier to inspect failed builds interactively than GitHub Actions

Cons:

- EC2 Mac has a 24-hour minimum host allocation
- still not on your local logger network unless you arrange VPN/network access

### Old Local MacBook

Useful for:

- Intel-only smoke tests
- running the app from source
- checking basic Tk behavior

Not ideal for:

- final release signing/notarization
- Apple Silicon builds
- current macOS local-network privacy testing if it cannot run recent macOS

## Common Failure Modes

- PyInstaller misses a hidden import. Add it to the macOS spec.
- App opens from Terminal but not Finder. Check bundle structure and `Info.plist`.
- App is blocked by Gatekeeper. Check Developer ID signing, hardened runtime,
  notarization, stapling, and quarantine state.
- mDNS discovery fails. Check local-network permission, `NSBonjourServices`,
  firewall/VPN, and whether zeroconf multicast works on that macOS version.
- App cannot write config. Confirm it launched with `--app-config-mode installed`
  and writes under `~/Library/Application Support/BODAQS/import-agent/`.
- Start at login launches the wrong executable path. Use the `.app` bundle path
  or the bundled executable path consistently in the LaunchAgent.
- Bundle size is very large. This is expected with Python scientific
  dependencies; optimize only after the signed build works.

## Suggested First Milestone

The first milestone should be deliberately modest:

1. Add `import-manager/packaging/macos/`.
2. Generate `bodaqs_import_manager.icns`.
3. Add a macOS PyInstaller spec.
4. Build an unsigned `BODAQS Import Manager.app`.
5. Launch it locally.
6. Provision a local folder source and import one archive.
7. Document any missing imports or macOS-specific runtime errors.

Do not start with notarization. The happy path is:

```text
unsigned local app -> signed local app -> notarized app -> DMG -> notarized DMG
```

## External References

Useful official/current references:

- Apple Developer ID and Gatekeeper:
  `https://developer.apple.com/developer-id/`
- Apple notarization workflow:
  `https://developer.apple.com/documentation/security/notarizing_macos_software_before_distribution`
- PyInstaller macOS requirements and compatibility:
  `https://pyinstaller.org/en/stable/requirements.html`
- PyInstaller macOS usage and forward-compatibility notes:
  `https://pyinstaller.org/en/stable/usage.html`
- GitHub macOS runners:
  `https://docs.github.com/en/actions/reference/runners/github-hosted-runners`
- AWS EC2 Mac:
  `https://aws.amazon.com/ec2/instance-types/mac/`

