# -*- mode: python ; coding: utf-8 -*-
#
# macOS PyInstaller spec for BODAQS Import Manager.
#
# Run from the import-manager directory (cwd must be import-manager so the
# Path.cwd() resolution below points at the right tree):
#
#   cd import-manager
#   python -m PyInstaller --noconfirm --clean \
#       --distpath dist/pyinstaller --workpath build/pyinstaller \
#       bodaqs_import_manager_macos.spec
#
# Output: dist/pyinstaller/BODAQS Import Manager.app
#
# This mirrors bodaqs_import_agent_setup.spec (Windows) but produces a windowed
# .app via a BUNDLE block, uses an .icns icon, and adds the macOS local-network
# / Bonjour Info.plist keys. Tray/menu-bar support is enabled on macOS via
# pystray's Darwin backend (pystray._darwin).

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


APP_NAME = "BODAQS Import Manager"
BUNDLE_IDENTIFIER = "org.bodaqs.importmanager"

import_manager_dir = Path.cwd()
repo_root = import_manager_dir.parent
analysis_dir = repo_root / "analysis"

# Generate a build-version module so the packaged app can display its version.
generated_dir = import_manager_dir / "build" / "generated"
generated_dir.mkdir(parents=True, exist_ok=True)
app_version = os.environ.get("BODAQS_IMPORT_MANAGER_APP_VERSION", "").strip() or "0.1.4-dev"
(generated_dir / "bodaqs_import_manager_build_version.py").write_text(
    f"APP_VERSION = {app_version!r}\n",
    encoding="utf-8",
)

setup_datas = collect_data_files("bodaqs_import_manager.import_agent_assets")
app_icon_path = (import_manager_dir / "packaging" / "macos" / "bodaqs_import_manager.icns").resolve()
setup_excludes = [
    "IPython",
    "jedi",
    "matplotlib",
    "nbformat",
    "pytest",
    "tornado",
    "zmq",
]


a = Analysis(
    ['bodaqs_import_agent_setup.py'],
    pathex=[str(generated_dir), str(import_manager_dir), str(analysis_dir)],
    binaries=[],
    datas=setup_datas,
    hiddenimports=[
        "bodaqs_analysis.import_agent_logger_wifi",
        "bodaqs_analysis.import_agent_logger_wifi_discovery",
        "bodaqs_analysis.import_agent_sources",
        "pystray._darwin",
        "zeroconf",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=setup_excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    icon=str(app_icon_path),
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=str(app_icon_path),
    bundle_identifier=BUNDLE_IDENTIFIER,
    version=app_version,
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_IDENTIFIER,
        "CFBundleShortVersionString": app_version,
        "CFBundleVersion": app_version,
        "NSHighResolutionCapable": True,
        # Local-network access for Wi-Fi logger discovery (mDNS/Bonjour).
        "NSLocalNetworkUsageDescription": (
            "BODAQS Import Manager uses the local network to discover and "
            "download sessions from BODAQS loggers."
        ),
        "NSBonjourServices": ["_bodaqs-logger._tcp"],
    },
)
