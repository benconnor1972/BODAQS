#!/usr/bin/env bash
#
# Build a macOS release of BODAQS Import Manager.
#
# Produces an unsigned .app (and, by default, an unsigned .dmg) using the macOS
# PyInstaller spec. Code signing and notarization are intentionally optional and
# OFF by default so that local unsigned development builds stay first-class.
# DMG filenames include macos-arm64 or macos-x64 so both release builds can be
# attached to the same GitHub Release without an asset-name collision.
#
# The build also produces the BODAQS Library Service and bundles it inside the
# .app at Contents/Resources/service/, along with the web app dist if available.
#
# Usage:
#   import-manager/build_import_manager_macos.sh [options]
#
# Options:
#   --skip-dmg            Build only the .app, skip the .dmg.
#   --skip-icns           Do not (re)generate the .icns first.
#   --skip-service        Skip building the library service.
#   --skip-web-app        Skip building and bundling the web app.
#   --include-demo        Bundle demo-assets into the .app (if available).
#   --version <ver>       Override the Desktop bundle version (default: 0.1.4-dev).
#   --manager-version <v> Override the Import Manager version (default: bundle version).
#   --service-version <v> Override the Library Service version (default: 0.1.0-dev).
#   --workbench-version <v> Override the Workbench version (default: bundle version).
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
manager_version=""
service_version="0.1.0-dev"
workbench_version=""
include_demo=0
make_dmg=1
make_icns=1
make_service=1
make_web_app=1
python_bin=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-dmg) make_dmg=0; shift ;;
        --skip-icns) make_icns=0; shift ;;
        --skip-service) make_service=0; shift ;;
        --skip-web-app) make_web_app=0; shift ;;
        --include-demo) include_demo=1; shift ;;
        --version) app_version="$2"; shift 2 ;;
        --manager-version) manager_version="$2"; shift 2 ;;
        --service-version) service_version="$2"; shift 2 ;;
        --workbench-version) workbench_version="$2"; shift 2 ;;
        --python) python_bin="$2"; shift 2 ;;
        *) echo "error: unknown option: $1" >&2; exit 2 ;;
    esac
done

machine_arch="$(uname -m)"
case "${machine_arch}" in
    arm64|aarch64) package_arch="arm64" ;;
    x86_64|amd64) package_arch="x64" ;;
    *)
        echo "error: unsupported macOS packaging architecture: ${machine_arch}" >&2
        exit 1
        ;;
esac

# Pick an interpreter: explicit --python, then repo .venv, then python3.
if [[ -z "${python_bin}" ]]; then
    if [[ -x "${repo_root}/.venv/bin/python" ]]; then
        python_bin="${repo_root}/.venv/bin/python"
    else
        python_bin="python3"
    fi
fi

manager_version="${manager_version:-${app_version}}"
workbench_version="${workbench_version:-${app_version}}"

echo "==> Python:       ${python_bin}"
echo "==> Desktop:      ${app_version}"
echo "==> Manager:      ${manager_version}"
echo "==> Service:      ${service_version}"
echo "==> Workbench:    ${workbench_version}"
echo "==> Architecture: ${package_arch}"
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
rm -rf "${dist_dir}/bodaqs-library-service"
rm -rf "${work_dir}/BODAQS Import Manager" "${work_dir}/bodaqs-library-service"

echo "==> Running PyInstaller (macOS manager spec)"
(
    cd "${import_manager_dir}"
    BODAQS_IMPORT_MANAGER_APP_VERSION="${manager_version}" \
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

# ---------------------------------------------------------------------------
# Build and bundle the library service
# ---------------------------------------------------------------------------
if [[ "${make_service}" -eq 1 ]]; then
    echo "==> Running PyInstaller (macOS library service spec)"
    (
        cd "${import_manager_dir}"
        BODAQS_LIBRARY_SERVICE_VERSION="${service_version}" \
        "${python_bin}" -m PyInstaller \
            --noconfirm \
            --clean \
            --distpath "${dist_dir}" \
            --workpath "${work_dir}" \
            bodaqs_library_service_macos.spec
    )

    service_src="${dist_dir}/bodaqs-library-service"
    service_dst="${app_path}/Contents/Resources/service"

    if [[ ! -d "${service_src}" ]]; then
        echo "error: library service bundle not found: ${service_src}" >&2
        exit 1
    fi

    echo "==> Bundling library service into .app"
    mkdir -p "${service_dst}"
    cp -R "${service_src}/"* "${service_dst}/"
    rm -rf "${service_src}"
    echo "==> Service bundled at: ${service_dst}"

    # Bundle the web app if available
    if [[ "${make_web_app}" -eq 1 ]]; then
        web_app_dir="${repo_root}/application/cohort-workbench-prototype"
        web_app_dist="${web_app_dir}/dist"

        if [[ ! -f "${web_app_dir}/package.json" ]]; then
            echo "error: web app package.json not found at ${web_app_dir}" >&2
            echo "       use --skip-web-app to build without the Workbench" >&2
            exit 1
        fi
        if ! command -v npm >/dev/null 2>&1; then
            echo "error: npm not found, cannot build web app" >&2
            echo "       use --skip-web-app to build without the Workbench" >&2
            exit 1
        fi

        echo "==> Building web app (deterministic rebuild)"
        (
            cd "${web_app_dir}"
            npm run build
        )

        if [[ ! -f "${web_app_dist}/index.html" ]]; then
            echo "error: web app build did not produce dist/index.html" >&2
            echo "       use --skip-web-app to build without the Workbench" >&2
            exit 1
        fi

        web_dst="${service_dst}/web"
        echo "==> Bundling web app into service"
        rm -rf "${web_dst}"
        mkdir -p "${web_dst}"
        cp -R "${web_app_dist}/"* "${web_dst}/"
        echo "==> Web app bundled at: ${web_dst}"
    fi
fi

echo "==> Writing component version metadata"
"${python_bin}" - "${app_path}/Contents/Resources/component_versions.json" "${app_version}" "${manager_version}" "${service_version}" "${workbench_version}" <<'PY'
import json
import sys
from pathlib import Path

output, bundle, manager, service, workbench = sys.argv[1:]
payload = {
    "bundle": {"name": "BODAQS Desktop", "version": bundle},
    "components": [
        {"name": "BODAQS Import Manager", "version": manager, "path": "Contents/MacOS/BODAQS Import Manager"},
        {"name": "BODAQS Library Service", "version": service, "path": "Contents/Resources/service/bodaqs-library-service"},
        {"name": "BODAQS Workbench", "version": workbench, "path": "Contents/Resources/service/web/index.html"},
    ],
}
Path(output).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY

# ---------------------------------------------------------------------------
# Bundle demo assets if requested and available
# ---------------------------------------------------------------------------
if [[ "${include_demo}" -eq 1 ]]; then
    demo_src="${repo_root}/demo-assets"
    demo_dst="${app_path}/Contents/Resources/demo-assets"
    if [[ -d "${demo_src}/libraries" ]] && find "${demo_src}/libraries" -name "library_definition.json" -print -quit | grep -q .; then
        echo "==> Bundling demo assets into .app"
        rm -rf "${demo_dst}"
        mkdir -p "${demo_dst}"
        cp -R "${demo_src}/"* "${demo_dst}/"
        echo "==> Demo assets bundled at: ${demo_dst}"
    else
        echo "   warning: demo-assets/libraries with library_definition.json not found, skipping demo" >&2
        echo "   Build demo library first with the recipe tooling."
    fi
fi

if [[ "${make_dmg}" -eq 1 ]]; then
    dmg_root="${import_manager_dir}/build/dmg-root"
    dmg_path="${import_manager_dir}/dist/BODAQS-Import-Manager-${app_version}-macos-${package_arch}.dmg"
    echo "==> Staging DMG contents"
    rm -rf "${dmg_root}"
    mkdir -p "${dmg_root}"
    cp -R "${app_path}" "${dmg_root}/"
    ln -s /Applications "${dmg_root}/Applications"

    # Add a short README to the DMG
    cat > "${dmg_root}/README.txt" <<'README_EOF'
BODAQS Import Manager
=====================

Drag BODAQS Import Manager to the Applications folder to install.

First launch:
  - Open BODAQS Import Manager from Applications (or Launchpad).
  - The app will prompt you to choose a workspace root for your libraries
    and sources.
  - After setup, you can add local archive folder sources or Wi-Fi logger
    sources to import sessions.

Wi-Fi logger:
  - Ensure your BODAQS logger is on the same network and in upload mode.
  - Use discovery or enter the logger's IP address manually.

This is an unsigned build.  If macOS blocks the launch, right-click the app
and choose "Open" to bypass Gatekeeper, or run:
  xattr -cr "/Applications/BODAQS Import Manager.app"
README_EOF

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
