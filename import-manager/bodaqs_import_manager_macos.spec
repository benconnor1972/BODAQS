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
# / Bonjour Info.plist keys. Tray/menu-bar support is intentionally NOT enabled
# on macOS for v1, so pystray (and its pyobjc backend) is excluded to keep the
# bundle lean; the tray module degrades gracefully when pystray is absent.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


APP_NAME = "BODAQS Import Manager"
APP_VERSION = "0.1.4-dev"
BUNDLE_IDENTIFIER = "org.bodaqs.importmanager"

import_manager_dir = Path.cwd()
repo_root = import_manager_dir.parent
analysis_dir = repo_root / "analysis"
setup_datas = collect_data_files("bodaqs_import_manager.import_agent_assets")
app_icon_path = (import_manager_dir / "packaging" / "macos" / "bodaqs_import_manager.icns").resolve()
setup_excludes = [
    "IPython",
    "jedi",
    "matplotlib",
    "nbformat",
    "pystray",
    "pytest",
    "tornado",
    "zmq",
]


a = Analysis(
    ['bodaqs_import_agent_setup.py'],
    pathex=[str(import_manager_dir), str(analysis_dir)],
    binaries=[],
    datas=setup_datas,
    hiddenimports=[
        "bodaqs_analysis.import_agent_logger_wifi",
        "bodaqs_analysis.import_agent_logger_wifi_discovery",
        "bodaqs_analysis.import_agent_sources",
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
    version=APP_VERSION,
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_IDENTIFIER,
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        "NSHighResolutionCapable": True,
        # Local-network access for Wi-Fi logger discovery (mDNS/Bonjour).
        "NSLocalNetworkUsageDescription": (
            "BODAQS Import Manager uses the local network to discover and "
            "download sessions from BODAQS loggers."
        ),
        "NSBonjourServices": ["_bodaqs-logger._tcp"],
    },
)
