#!/usr/bin/env bash
#
# Generate the macOS app icon (.icns) for BODAQS Import Manager from the shared
# logo SVG. Uses native macOS tooling (rsvg-convert + iconutil) rather than the
# Chromium-based Windows branding helper.
#
# Requirements:
#   - rsvg-convert  (brew install librsvg)
#   - iconutil      (ships with macOS)
#
# Usage:
#   import-manager/tools/generate_macos_icns.sh
#
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
import_manager_dir="$(cd "${script_dir}/.." && pwd)"
repo_root="$(cd "${import_manager_dir}/.." && pwd)"

svg_path="${BODAQS_LOGO_SVG:-${repo_root}/bodocs/public/favicon.svg}"
out_dir="${import_manager_dir}/packaging/macos"
icns_path="${out_dir}/bodaqs_import_manager.icns"

if ! command -v rsvg-convert >/dev/null 2>&1; then
    echo "error: rsvg-convert not found (install with: brew install librsvg)" >&2
    exit 1
fi
if ! command -v iconutil >/dev/null 2>&1; then
    echo "error: iconutil not found (expected on macOS)" >&2
    exit 1
fi
if [[ ! -f "${svg_path}" ]]; then
    echo "error: logo SVG not found: ${svg_path}" >&2
    exit 1
fi

mkdir -p "${out_dir}"
workdir="$(mktemp -d -t bodaqs-icns)"
iconset="${workdir}/bodaqs_import_manager.iconset"
mkdir -p "${iconset}"
trap 'rm -rf "${workdir}"' EXIT

# (filename, pixel size) pairs required by iconutil.
render() {
    local name="$1" size="$2"
    rsvg-convert --width "${size}" --height "${size}" \
        --keep-aspect-ratio \
        --background-color none \
        --output "${iconset}/${name}" \
        "${svg_path}"
}

render icon_16x16.png 16
render icon_16x16@2x.png 32
render icon_32x32.png 32
render icon_32x32@2x.png 64
render icon_128x128.png 128
render icon_128x128@2x.png 256
render icon_256x256.png 256
render icon_256x256@2x.png 512
render icon_512x512.png 512
render icon_512x512@2x.png 1024

iconutil --convert icns --output "${icns_path}" "${iconset}"

echo "Generated macOS icns: ${icns_path}"
