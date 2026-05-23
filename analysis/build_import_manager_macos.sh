#!/usr/bin/env bash
# Build BODAQS Import Manager.app for macOS via PyInstaller.
#
# Default: unsigned .app at analysis/dist/pyinstaller/BODAQS Import Manager.app.
# Optional flags layer on signing / notarization / DMG packaging — each driven
# by environment variables so credentials never live in the repo.
#
#   --clean          Remove prior dist/build dirs before building.
#   --sign           codesign with $BODAQS_MAC_CODESIGN_IDENTITY (Developer ID
#                    Application certificate name).
#   --notarize       Submit to Apple via $BODAQS_MAC_NOTARY_PROFILE keychain
#                    profile (set up once with `xcrun notarytool
#                    store-credentials`). Requires --sign.
#   --dmg            Wrap the .app in a DMG and place it under analysis/dist/.
#                    If combined with --sign --notarize, the DMG is also
#                    signed/notarized/stapled.
#
# Optional env: BODAQS_APP_VERSION (defaults to 0.1.0-dev).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DO_CLEAN=0
DO_SIGN=0
DO_NOTARIZE=0
DO_DMG=0

while (($#)); do
    case "$1" in
        --clean) DO_CLEAN=1 ;;
        --sign) DO_SIGN=1 ;;
        --notarize) DO_NOTARIZE=1 ;;
        --dmg) DO_DMG=1 ;;
        -h|--help)
            sed -n '2,20p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown flag: $1" >&2
            exit 2
            ;;
    esac
    shift
done

if [[ "$DO_NOTARIZE" == "1" && "$DO_SIGN" == "0" ]]; then
    echo "Error: --notarize requires --sign." >&2
    exit 2
fi

if [[ "$DO_SIGN" == "1" && -z "${BODAQS_MAC_CODESIGN_IDENTITY:-}" ]]; then
    echo "Error: --sign requires BODAQS_MAC_CODESIGN_IDENTITY to be set." >&2
    exit 2
fi

if [[ "$DO_NOTARIZE" == "1" && -z "${BODAQS_MAC_NOTARY_PROFILE:-}" ]]; then
    echo "Error: --notarize requires BODAQS_MAC_NOTARY_PROFILE to be set." >&2
    exit 2
fi

APP_VERSION="${BODAQS_APP_VERSION:-0.1.0-dev}"
export BODAQS_APP_VERSION="$APP_VERSION"

PYTHON_EXE="${PYTHON:-}"
if [[ -z "$PYTHON_EXE" ]]; then
    if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
        PYTHON_EXE="${REPO_ROOT}/.venv/bin/python"
    else
        PYTHON_EXE="$(command -v python3 || command -v python || true)"
    fi
fi
if [[ -z "$PYTHON_EXE" ]]; then
    echo "Error: no Python interpreter found (set PYTHON= or create a .venv)." >&2
    exit 1
fi
echo "Using Python: $PYTHON_EXE"

if ! "$PYTHON_EXE" -c "import PyInstaller" >/dev/null 2>&1; then
    echo "Error: PyInstaller is not installed in the selected Python environment." >&2
    echo "Install with: $PYTHON_EXE -m pip install pyinstaller pillow" >&2
    exit 1
fi

cd "$SCRIPT_DIR"

DIST_DIR="${SCRIPT_DIR}/dist/pyinstaller"
BUILD_DIR="${SCRIPT_DIR}/build/pyinstaller"
APP_PATH="${DIST_DIR}/BODAQS Import Manager.app"
SPEC_PATH="${SCRIPT_DIR}/bodaqs_import_manager_macos.spec"

if [[ ! -f "$SPEC_PATH" ]]; then
    echo "Error: PyInstaller spec not found: $SPEC_PATH" >&2
    exit 1
fi

if [[ "$DO_CLEAN" == "1" ]]; then
    rm -rf "$DIST_DIR" "$BUILD_DIR"
fi

echo "Running PyInstaller..."
"$PYTHON_EXE" -m PyInstaller \
    --noconfirm \
    --clean \
    --distpath "$DIST_DIR" \
    --workpath "$BUILD_DIR" \
    "$SPEC_PATH"

if [[ ! -d "$APP_PATH" ]]; then
    echo "Error: expected .app bundle was not produced: $APP_PATH" >&2
    exit 1
fi

echo "Built: $APP_PATH"

if [[ "$DO_SIGN" == "1" ]]; then
    echo "Signing nested binaries..."
    while IFS= read -r -d '' nested; do
        codesign --force --options runtime --timestamp \
            --sign "$BODAQS_MAC_CODESIGN_IDENTITY" \
            "$nested" >/dev/null
    done < <(find "$APP_PATH" -type f \( -name "*.dylib" -o -name "*.so" \) -print0)

    echo "Signing app bundle..."
    codesign --force --options runtime --timestamp \
        --sign "$BODAQS_MAC_CODESIGN_IDENTITY" \
        "$APP_PATH"

    echo "Verifying signature..."
    codesign --verify --deep --strict --verbose=2 "$APP_PATH"
fi

if [[ "$DO_NOTARIZE" == "1" ]]; then
    NOTARIZE_ZIP="${DIST_DIR}/BODAQS-Import-Manager-${APP_VERSION}.zip"
    echo "Creating notarization zip..."
    rm -f "$NOTARIZE_ZIP"
    ditto -c -k --keepParent "$APP_PATH" "$NOTARIZE_ZIP"

    echo "Submitting to notary service..."
    xcrun notarytool submit "$NOTARIZE_ZIP" \
        --keychain-profile "$BODAQS_MAC_NOTARY_PROFILE" \
        --wait

    echo "Stapling .app..."
    xcrun stapler staple "$APP_PATH"

    rm -f "$NOTARIZE_ZIP"
fi

if [[ "$DO_DMG" == "1" ]]; then
    DMG_PATH="${SCRIPT_DIR}/dist/BODAQS-Import-Manager-${APP_VERSION}.dmg"
    DMG_ROOT="${SCRIPT_DIR}/build/dmg-root"

    rm -rf "$DMG_ROOT"
    mkdir -p "$DMG_ROOT"
    cp -R "$APP_PATH" "$DMG_ROOT/"
    ln -s /Applications "$DMG_ROOT/Applications"

    mkdir -p "$(dirname "$DMG_PATH")"
    rm -f "$DMG_PATH"
    echo "Creating DMG..."
    hdiutil create \
        -volname "BODAQS Import Manager" \
        -srcfolder "$DMG_ROOT" \
        -ov \
        -format UDZO \
        "$DMG_PATH"

    if [[ "$DO_SIGN" == "1" ]]; then
        echo "Signing DMG..."
        codesign --force --timestamp \
            --sign "$BODAQS_MAC_CODESIGN_IDENTITY" \
            "$DMG_PATH"
    fi

    if [[ "$DO_NOTARIZE" == "1" ]]; then
        echo "Notarizing DMG..."
        xcrun notarytool submit "$DMG_PATH" \
            --keychain-profile "$BODAQS_MAC_NOTARY_PROFILE" \
            --wait
        xcrun stapler staple "$DMG_PATH"
    fi

    echo "DMG: $DMG_PATH"
fi

echo ""
echo "Done."
echo "App: $APP_PATH"
