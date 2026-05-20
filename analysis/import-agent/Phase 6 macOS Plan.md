# BODAQS Import Manager Phase 6 macOS Plan

## Goal

Package the existing import-manager desktop shell for macOS as a normal
user-installable app without changing the current import pipeline, artifact
contract, or source-folder workflow.

## Scope

Phase 6 covers:

- macOS build and packaging for the existing manager app
- macOS branding assets (`.icns`)
- macOS app-config location rules
- macOS start-at-login behavior
- signing and notarization for outside-App-Store distribution
- release packaging, most likely as a DMG

Phase 6 does not cover:

- new source adapters such as serial, Wi-Fi, or cloud
- a redesign of the core import engine
- a rewrite of the UI stack

## Assumptions

- the first macOS release is outside the Mac App Store
- the current Python/Tk + tray architecture remains in place for v1
- the installed app still owns first-run provisioning
- sources and libraries remain user-chosen directories outside the app bundle

## Recommended Product Shape

Ship a signed and notarized `BODAQS Import Manager.app` in a DMG.

Reasoning:

- the app already performs first-run setup, so a heavy installer is not needed
- a DMG is the most natural first macOS distribution shape
- it keeps platform-specific installer logic smaller than a `.pkg`

## Main Technical Changes

### 1. macOS build target

Add a macOS PyInstaller target for the manager app that produces:

- a windowed `.app` bundle
- a bundle identifier
- version metadata
- macOS-specific `Info.plist` entries

Notes:

- this must be built on macOS
- the build should happen on the oldest macOS version we intend to support, to
  maximize forward compatibility

### 2. Branding assets

Generate a macOS `.icns` from the same BODAQS logo source already used for the
Windows tray/ICO assets.

Recommended outputs:

- `analysis/import-agent/macos/bodaqs_import_agent.icns`
- keep `bodocs/public/favicon.svg` as the source of truth

### 3. App-config location

For installed macOS builds, store managed app config in a per-user
Application Support location rather than beside the app bundle.

Recommended location:

- `~/Library/Application Support/BODAQS/import-agent/import_agent_app.json`

Rationale:

- consistent with the installed-mode rule already adopted on Windows
- keeps upgrades and app replacement separate from user state

### 4. Start-at-login

Replace the Windows registry-based startup registration with a macOS-specific
mechanism.

Recommended v1 approach:

- implement a per-user macOS launch-at-login integration behind a platform
  abstraction
- treat this as the macOS equivalent of the current Windows `auto_start`
  preference

Open design choice:

- whether to start with a LaunchAgent-based implementation
- or move directly toward a more Apple-native login-item/helper approach

Recommendation:

- use the simplest robust per-user launch-at-login mechanism that works well
  with a Python app bundle for v1
- keep the app-facing preference model identical to Windows

### 5. Tray/menu-bar behavior

Evaluate the current tray implementation on macOS.

Needed checks:

- whether `pystray` behaves well on current macOS releases
- whether the manager can hide/reopen cleanly from a menu-bar item
- whether close-to-tray behavior feels native enough for v1

Recommendation:

- keep the current tray/menu model if it proves reliable
- if it is unstable or visibly un-native, ship macOS first with a normal
  windowed app and defer the background shell refinement

### 6. Signing and notarization

For distribution outside the Mac App Store, the app should follow the normal
Developer ID path:

- sign with Developer ID
- submit for notarization
- staple the notarization ticket

Practical requirements:

- Apple Developer Program membership
- Developer ID Application certificate
- Xcode / notarytool-capable environment
- hardened runtime configuration for the notarized app

### 7. DMG packaging

Wrap the signed/notarized `.app` in a DMG for distribution.

Recommended DMG contents:

- `BODAQS Import Manager.app`
- shortcut to `/Applications`
- short install/readme text if needed

## Platform-Specific Seams In The Current Code

The import engine is already mostly portable. The main Windows-specific seams
to abstract or replace are:

- `bodaqs_analysis.import_agent_startup`
- Windows-only tray gating in `bodaqs_analysis.import_agent_tray`
- Windows-focused packaging/build flow in `analysis/build_import_agent.ps1`
- Inno Setup packaging in `analysis/import-agent/windows/`

## Suggested Work Breakdown

### Step 1. Create platform abstractions

- separate startup registration behind a platform-neutral interface
- separate installed app-config location policy from Windows-specific code
- stop hard-gating tray support to Windows only

### Step 2. Add macOS branding assets

- generate `.icns`
- add macOS asset regeneration/build notes

### Step 3. Add macOS build target

- create a macOS PyInstaller spec for the manager app
- set bundle identifier and version metadata
- verify unsigned local builds on a Mac

### Step 4. Add macOS runtime behaviors

- implement macOS app-data path rules
- implement start-at-login support
- validate menu-bar/tray behavior

### Step 5. Add distribution tooling

- sign the `.app`
- notarize it
- staple the ticket
- build a DMG

### Step 6. Release testing

- clean-machine install test
- first-run provisioning test
- import-once and watch-loop test
- start-at-login test
- Gatekeeper/open-from-downloads test

## Risks And Decisions To Resolve

### Minimum supported macOS version

This affects:

- build environment choice
- PyInstaller compatibility expectations
- signing/notarization workflow details

### Apple Silicon vs Intel

Need to decide whether v1 should be:

- Apple Silicon only
- separate Intel and Apple Silicon builds
- or a universal build later

### Tray quality

The current Windows tray approach may not feel equally native on macOS.

Recommendation:

- validate early on a real Mac before locking in the shell behavior

### Startup implementation

The startup mechanism should be chosen for:

- user visibility in System Settings
- reliability
- maintainability from a Python-packaged app

### Signing readiness

Unsigned local testing can happen early, but public distribution should assume:

- Developer ID signing
- notarization
- a reproducible mac build environment

## Exit Criteria

Phase 6 is done when:

- a macOS `.app` can be built from the repo on a Mac
- the app provisions and manages import sources successfully
- start-at-login works with the persisted `auto_start` preference
- the distributed artifact is signed and notarized
- a user can install it from a DMG and run it without developer-only workarounds

## Recommended Next Coding Step

Start by extracting a small platform layer for:

- startup registration
- installed app-config location selection
- tray support gating

That will make the macOS build work much more cleanly than trying to bolt mac
packaging directly onto the current Windows-oriented seams.
