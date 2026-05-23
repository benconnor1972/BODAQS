# Building the macOS Import Manager

This is the practical "I'm at a Mac, I want to build `BODAQS Import Manager.app`"
guide. For the wider architectural context see
[`macOS Packaging Handoff.md`](./macOS%20Packaging%20Handoff.md) and the agent
notes in [`macOS Coding Agent Notes.md`](./macOS%20Coding%20Agent%20Notes.md).

The build script (`analysis/build_import_manager_macos.sh`) handles the
heavy lifting. This guide explains what you need on the machine, what the
script does, and how to layer on signing/notarization/DMG once you have an
Apple Developer ID.

---

## What you'll produce

An unsigned local build creates one thing:

```
analysis/dist/pyinstaller/BODAQS Import Manager.app
```

That `.app` is a fully self-contained bundle (Python runtime, Tk, scientific
deps, `bodaqs_analysis` package, mDNS support). You can `open` it directly,
drag it onto another Mac, or pass `--sign --notarize --dmg` to wrap it for
distribution.

---

## Prerequisites

You need:

- **macOS 11 (Big Sur) or newer**, on Apple Silicon or Intel.
- **Xcode Command Line Tools** — `xcode-select --install` if you've never
  done it.
- **Homebrew** — most builds here assume `brew` is on `PATH`.
- **Python 3.14 with Tk support**:
  ```bash
  brew install python@3.14 python-tk@3.14
  ```
  The `python-tk@3.14` package is critical. Without it the build still
  succeeds, but the resulting `.app` fails at launch with
  `ModuleNotFoundError: No module named '_tkinter'`. PyInstaller bundles
  only what is importable at build time.
- **A repo checkout** with a hydrated virtualenv at `BODAQS/.venv/`. If
  the venv is empty, hydrate it:
  ```bash
  cd /path/to/BODAQS
  /opt/homebrew/bin/python3.14 -m venv .venv      # one-time, if .venv missing
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  .venv/bin/python -m pip install pyinstaller pillow
  ```

Sanity check the venv has the right pieces:

```bash
.venv/bin/python -c "import tkinter, PyInstaller, zeroconf, pystray, PIL; print('OK')"
```

If that prints `OK`, you're set.

---

## Step 1 — Run the focused tests

Confirm the platform-seam refactor and macOS-specific code are healthy
before packaging:

```bash
cd analysis
../.venv/bin/python -m pytest tests/test_import_agent.py tests/test_import_agent_logger_wifi.py -q
```

Expected: 78 passed, 1 failed.

The single expected failure is
`test_default_import_agent_app_config_path_uses_windows_convention`. It can
only pass on Windows hosts — it asserts a `C:\…` path is parsed natively,
which POSIX `pathlib` can't do. Everything else should be green. If anything
*else* fails, fix that before continuing.

---

## Step 2 — Build the unsigned `.app`

From the repo root:

```bash
export PYTHON="$(pwd)/.venv/bin/python"   # absolute path to the venv Python
bash analysis/build_import_manager_macos.sh --clean
```

What the script does, in order:

1. Resolves the Python interpreter (prefers `$PYTHON`, then `.venv/bin/python`,
   then `python3`/`python` from `PATH`).
2. Verifies PyInstaller is importable — it does **not** auto-install.
3. Cleans `analysis/dist/pyinstaller/` and `analysis/build/pyinstaller/`
   (only when `--clean` is passed).
4. Runs `python -m PyInstaller` against `analysis/bodaqs_import_manager_macos.spec`.
5. Emits the `.app` to `analysis/dist/pyinstaller/BODAQS Import Manager.app`.

A clean build on Apple Silicon takes roughly **45–90 seconds**. Most of the
time goes into building the COLLECT and BUNDLE stages.

When it finishes you'll see (paths relative to your repo root):

```
Built: …/analysis/dist/pyinstaller/BODAQS Import Manager.app

Done.
App: …/analysis/dist/pyinstaller/BODAQS Import Manager.app
```

---

## Step 3 — Smoke-test the bundle

Two quick checks before opening the GUI:

```bash
APP="$(pwd)/analysis/dist/pyinstaller/BODAQS Import Manager.app"

# (a) The executable boots and the argparse layer works.
"$APP/Contents/MacOS/BODAQS Import Manager" --help

# (b) Info.plist has the expected identity and local-network metadata.
/usr/libexec/PlistBuddy -c "Print :CFBundleIdentifier" "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Print :NSBonjourServices" "$APP/Contents/Info.plist"
```

You should see `org.bodaqs.importmanager` and an array containing
`_bodaqs-logger._tcp`. If (a) crashes with `No module named '_tkinter'`,
you skipped `python-tk@3.14` — install it, then re-run Step 2.

Now open the GUI:

```bash
open "$APP"
```

A Tk window titled **BODAQS Import Manager** should appear. From here, walk
the manual checklist from the packaging handoff:

- First-run setup creates a source and library.
- App config lands at
  `~/Library/Application Support/BODAQS/import-agent/import_agent_app.json`
  (not next to the `.app`).
- Drop a logger archive into the source inbox → **Import Now** moves it
  into the target library.
- Enable **Start at Login**, log out and back in, confirm the
  `~/Library/LaunchAgents/org.bodaqs.importmanager.plist` file exists and the
  app launched. Disable it and confirm the plist is removed.
- Trigger Wi-Fi logger discovery — macOS should prompt for **Local Network**
  access the first time. Allow it, then confirm `_bodaqs-logger._tcp` shows
  up in discovery.

---

## Step 4 (optional) — Sign, notarize, and ship a DMG

You need these once:

- An **Apple Developer Program** membership.
- A **Developer ID Application** certificate installed in your login
  keychain.
- A **notary keychain profile** stored locally:
  ```bash
  xcrun notarytool store-credentials "BODAQS-notary" \
      --apple-id "you@example.com" \
      --team-id "ABCDE12345" \
      --password "<app-specific-password>"
  ```

Then export the env vars the build script reads:

```bash
export BODAQS_MAC_CODESIGN_IDENTITY="Developer ID Application: Your Name (ABCDE12345)"
export BODAQS_MAC_NOTARY_PROFILE="BODAQS-notary"
export BODAQS_APP_VERSION="0.1.0-dev"   # ends up in CFBundleVersion + DMG filename
```

Run the full pipeline:

```bash
bash analysis/build_import_manager_macos.sh --clean --sign --notarize --dmg
```

The script:

1. Builds the unsigned `.app` (as above).
2. Walks every nested `.dylib` and `.so` and signs each one with hardened
   runtime + a timestamp before signing the outer bundle. This avoids the
   most common notarization failure mode (`--deep` alone often leaves
   embedded Python extensions unsigned).
3. Verifies the signature with `codesign --verify --deep --strict`.
4. Zips the `.app`, submits it to Apple's notary service with `notarytool
   submit --wait`, and staples the ticket once approved.
5. Stages `build/dmg-root/` with the `.app` and an `/Applications` symlink,
   then runs `hdiutil create … -format UDZO` to produce
   `analysis/dist/BODAQS-Import-Manager-${BODAQS_APP_VERSION}.dmg`.
6. Signs, notarizes, and staples the DMG.

Each flag is independent — `--sign` without `--notarize` gives a locally
signed but un-notarized bundle that you can install on your own Mac but
that Gatekeeper will block elsewhere. `--notarize` requires `--sign`.

Verify the signed output on the build machine before sharing:

```bash
codesign --verify --deep --strict --verbose=2 "$APP"
spctl --assess --type execute --verbose=4 "$APP"
```

Both should report `accepted`.

---

## Regenerating the icon

The `.icns` already lives in the repo at
`analysis/import-agent/macos/bodaqs_import_manager.icns`. You only need to
regenerate it if you change the source logo (`bodocs/public/favicon.svg`) or
the rendered PNG (`analysis/bodaqs_analysis/import_agent_assets/app_icon.png`).

The helper prefers Apple's `iconutil` when available (canonical multi-size
output) and falls back to Pillow elsewhere:

```bash
# Regenerate just the .icns from the existing app_icon.png:
.venv/bin/python - <<'PY'
import sys
sys.path.insert(0, "analysis/import-agent")
from generate_import_agent_branding import (
    build_icns_from_png, DEFAULT_APP_PNG_PATH, DEFAULT_APP_ICNS_PATH,
)
build_icns_from_png(png_path=DEFAULT_APP_PNG_PATH, icns_path=DEFAULT_APP_ICNS_PATH)
print("Wrote:", DEFAULT_APP_ICNS_PATH)
PY

# Or run the full branding pipeline from the SVG (needs a headless Chromium):
.venv/bin/python analysis/import-agent/generate_import_agent_branding.py
```

`file analysis/import-agent/macos/bodaqs_import_manager.icns` should report
`Mac OS X icon` with a multi-size set (`ic12`, `ic13`, etc).

---

## Troubleshooting

**`No module named '_tkinter'` when launching the `.app`**
You built without `python-tk@3.14`. Install it
(`brew install python-tk@3.14`) and rebuild — PyInstaller bundles only what
was importable at build time.

**`No module named 'PyInstaller'` from the script**
Install it into the same Python the script will use:
`.venv/bin/python -m pip install pyinstaller pillow`. The script
deliberately does not auto-install.

**`codesign` fails on a nested binary**
Run the script with `--clean` to discard any partial signatures, then
re-run with `--sign`. The script signs nested `.dylib`/`.so` files first
in their own loop, then the outer bundle. If a specific path is rejected,
sign it manually with the same identity and hardened runtime, then re-run
the bundle signing.

**Notarization comes back rejected**
Fetch the log:
```bash
xcrun notarytool log <submission-id> --keychain-profile "$BODAQS_MAC_NOTARY_PROFILE"
```
Most rejections list an unsigned nested binary — sign that specific path
with hardened runtime, then resubmit.

**Local-network permission isn't prompted**
macOS only prompts when discovery actually attempts mDNS. Trigger logger
discovery from the manager UI, not just by launching it. If the prompt
never appears, check System Settings → Privacy & Security → Local Network
and see if the app is already listed (it may have been silently denied).

**App opens from Terminal but not Finder**
Almost always an `Info.plist` issue. Run
`/usr/libexec/PlistBuddy -c "Print" "$APP/Contents/Info.plist"` and verify
`CFBundleIdentifier`, `CFBundleExecutable`, and `CFBundleName` are all set.

**Bundle is very large (300+ MB)**
Expected. The scientific Python stack (NumPy, SciPy, pandas, zeroconf,
Pillow, Tk) is what dominates the size. There's no quick win here — the
sensible time to optimize is after the signed build is shipping.
