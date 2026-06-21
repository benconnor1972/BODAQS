#!/usr/bin/env bash
#
# Build a macOS release of BODAQS Import Manager.
#
# Produces an unsigned .app (and, by default, an unsigned .dmg) using the macOS
# PyInstaller spec. Code signing and notarization are intentionally optional and
# OFF by default so that local unsigned development builds stay first-class.
#
# Usage:
#   import-manager/build_import_manager_macos.sh [options]
#
# Options:
#   --skip-dmg            Build only the .app, skip the .dmg.
#   --skip-icns           Do not (re)generate the .icns first.
#   --version <ver>       Override the release version (default: 0.1.4-dev).
#   --python <path>       Python interpreter to use (default: auto-detected).
#
# Signing/notarization are deliberately not implemented here. See
# docs/macOS Packaging Handoff.md for the signing + notarytool workflow.
#
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
import_manager_dir="${script_dir}"
repo_root="$(cd "${import_manager_dir}/.." && pwd)"

app_version="0.1.4-dev"
make_dmg=1
make_icns=1
python_bin=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-dmg) make_dmg=0; shift ;;
        --skip-icns) make_icns=0; shift ;;
        --version) app_version="$2"; shift 2 ;;
        --python) python_bin="$2"; shift 2 ;;
        *) echo "error: unknown option: $1" >&2; exit 2 ;;
    esac
done

# Pick an interpreter: explicit --python, then repo .venv, then python3.
if [[ -z "${python_bin}" ]]; then
    if [[ -x "${repo_root}/.venv/bin/python" ]]; then
        python_bin="${repo_root}/.venv/bin/python"
    else
        python_bin="python3"
    fi
fi

echo "==> Python:       ${python_bin}"
echo "==> Version:      ${app_version}"
echo "==> Working dir:  ${import_manager_dir}"

"${python_bin}" -c "import PyInstaller" >/dev/null 2>&1 || {
    echo "error: PyInstaller is not importable by ${python_bin}" >&2
    echo "       install it with: ${python_bin} -m pip install pyinstaller pillow" >&2
    exit 1
}

icns_path="${import_manager_dir}/packaging/macos/bodaqs_import_manager.icns"
if [[ "${make_icns}" -eq 1 ]]; then
    echo "==> Generating macOS icns"
    "${import_manager_dir}/tools/generate_macos_icns.sh"
elif [[ ! -f "${icns_path}" ]]; then
    echo "error: ${icns_path} missing and --skip-icns was given" >&2
    exit 1
fi

dist_dir="${import_manager_dir}/dist/pyinstaller"
work_dir="${import_manager_dir}/build/pyinstaller"
app_path="${dist_dir}/BODAQS Import Manager.app"

echo "==> Cleaning previous macOS build/dist artifacts"
rm -rf "${dist_dir}/BODAQS Import Manager.app" "${dist_dir}/BODAQS Import Manager"
rm -rf "${work_dir}/BODAQS Import Manager"

echo "==> Running PyInstaller (macOS spec)"
(
    cd "${import_manager_dir}"
    "${python_bin}" -m PyInstaller \
        --noconfirm \
        --clean \
        --distpath "${dist_dir}" \
        --workpath "${work_dir}" \
        bodaqs_import_manager_macos.spec
)

if [[ ! -d "${app_path}" ]]; then
    echo "error: expected app bundle not found: ${app_path}" >&2
    exit 1
fi
echo "==> Built: ${app_path}"

if [[ "${make_dmg}" -eq 1 ]]; then
    dmg_root="${import_manager_dir}/build/dmg-root"
    dmg_path="${import_manager_dir}/dist/BODAQS-Import-Manager-${app_version}.dmg"
    echo "==> Staging DMG contents"
    rm -rf "${dmg_root}"
    mkdir -p "${dmg_root}"
    cp -R "${app_path}" "${dmg_root}/"
    ln -s /Applications "${dmg_root}/Applications"

    echo "==> Creating DMG: ${dmg_path}"
    rm -f "${dmg_path}"
    hdiutil create \
        -volname "BODAQS Import Manager" \
        -srcfolder "${dmg_root}" \
        -ov \
        -format UDZO \
        "${dmg_path}"
    echo "==> Built: ${dmg_path}"
fi

echo
echo "Done. This is an UNSIGNED build."
echo "Gatekeeper will warn until the app/dmg is signed and notarized."
echo "Open locally with:"
echo "  open \"${app_path}\""
