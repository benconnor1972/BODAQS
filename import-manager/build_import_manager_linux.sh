#!/usr/bin/env bash
#
# Build an unsigned, portable Linux x64 BODAQS Import Manager bundle.
# The result is a .tar.gz containing the manager, bundled library service, and
# Workbench static files. It is intended for CI validation and early testing;
# it is not yet a native Linux installer or signed release artifact.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
import_manager_dir="${script_dir}"
repo_root="$(cd "${import_manager_dir}/.." && pwd)"

app_version="0.1.4-dev"
manager_version=""
service_version="0.1.0-dev"
workbench_version=""
python_bin=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --version) app_version="$2"; shift 2 ;;
        --manager-version) manager_version="$2"; shift 2 ;;
        --service-version) service_version="$2"; shift 2 ;;
        --workbench-version) workbench_version="$2"; shift 2 ;;
        --python) python_bin="$2"; shift 2 ;;
        *) echo "error: unknown option: $1" >&2; exit 2 ;;
    esac
done

if [[ -z "${python_bin}" ]]; then
    if [[ -x "${repo_root}/.venv/bin/python" ]]; then
        python_bin="${repo_root}/.venv/bin/python"
    else
        python_bin="python3"
    fi
fi

manager_version="${manager_version:-${app_version}}"
workbench_version="${workbench_version:-${app_version}}"

"${python_bin}" -c "import PyInstaller" >/dev/null 2>&1 || {
    echo "error: PyInstaller is not importable by ${python_bin}" >&2
    echo "       install it with: ${python_bin} -m pip install pyinstaller pillow" >&2
    exit 1
}

if ! command -v npm >/dev/null 2>&1; then
    echo "error: npm not found, cannot build the bundled Workbench" >&2
    exit 1
fi

dist_dir="${import_manager_dir}/dist/pyinstaller"
work_dir="${import_manager_dir}/build/pyinstaller"
manager_dir="${dist_dir}/bodaqs-import-manager"
service_dir="${dist_dir}/bodaqs-library-service"
web_app_dir="${repo_root}/application/cohort-workbench-prototype"
web_app_dist="${web_app_dir}/dist"
archive_name="BODAQS-Import-Manager-${app_version}-linux-x64"
archive_root="${import_manager_dir}/build/release/linux/${archive_name}"
archive_path="${import_manager_dir}/dist/${archive_name}.tar.gz"

echo "==> Python: ${python_bin}"
echo "==> Desktop: ${app_version}"
echo "==> Manager: ${manager_version}"
echo "==> Service: ${service_version}"
echo "==> Workbench: ${workbench_version}"

rm -rf "${manager_dir}" "${service_dir}"
rm -rf "${work_dir}/bodaqs-import-manager" "${work_dir}/bodaqs-library-service"
rm -rf "${archive_root}"
rm -f "${archive_path}"

echo "==> Building Linux Import Manager"
(
    cd "${import_manager_dir}"
    BODAQS_IMPORT_MANAGER_APP_VERSION="${manager_version}" \
        "${python_bin}" -m PyInstaller --noconfirm --clean \
        --distpath "${dist_dir}" --workpath "${work_dir}" \
        bodaqs_import_manager_linux.spec
)

echo "==> Building Linux Library Service"
(
    cd "${import_manager_dir}"
    BODAQS_LIBRARY_SERVICE_VERSION="${service_version}" \
        "${python_bin}" -m PyInstaller --noconfirm --clean \
        --distpath "${dist_dir}" --workpath "${work_dir}" \
        bodaqs_library_service_linux.spec
)

echo "==> Building Workbench"
(
    cd "${web_app_dir}"
    npm run build
)

if [[ ! -x "${manager_dir}/bodaqs-import-manager" ]]; then
    echo "error: manager executable was not built" >&2
    exit 1
fi
if [[ ! -x "${service_dir}/bodaqs-library-service" ]]; then
    echo "error: library service executable was not built" >&2
    exit 1
fi
if [[ ! -f "${web_app_dist}/index.html" ]]; then
    echo "error: Workbench build did not produce dist/index.html" >&2
    exit 1
fi

echo "==> Bundling service and Workbench into manager"
mkdir -p "${manager_dir}/service"
cp -R "${service_dir}/." "${manager_dir}/service/"
mkdir -p "${manager_dir}/service/web"
cp -R "${web_app_dist}/." "${manager_dir}/service/web/"
rm -rf "${service_dir}"

echo "==> Writing component version metadata"
"${python_bin}" - "${manager_dir}/component_versions.json" "${app_version}" "${manager_version}" "${service_version}" "${workbench_version}" <<'PY'
import json
import sys
from pathlib import Path

output, bundle, manager, service, workbench = sys.argv[1:]
payload = {
    "bundle": {"name": "BODAQS Desktop", "version": bundle},
    "components": [
        {"name": "BODAQS Import Manager", "version": manager, "path": "bodaqs-import-manager"},
        {"name": "BODAQS Library Service", "version": service, "path": "service/bodaqs-library-service"},
        {"name": "BODAQS Workbench", "version": workbench, "path": "service/web/index.html"},
    ],
}
Path(output).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY

echo "==> Running packaged smoke tests"
"${python_bin}" "${import_manager_dir}/tools/smoke_test_packaged_imu_bdq.py" \
    "${manager_dir}/bodaqs-import-manager"
"${python_bin}" "${import_manager_dir}/tools/smoke_test_packaged_imu_bdq.py" \
    "${manager_dir}/bodaqs-import-manager" --check-workbench-layout

mkdir -p "${archive_root}"
cp -R "${manager_dir}/." "${archive_root}/"
tar -C "$(dirname "${archive_root}")" -czf "${archive_path}" "${archive_name}"

echo "==> Built unsigned Linux archive: ${archive_path}"
