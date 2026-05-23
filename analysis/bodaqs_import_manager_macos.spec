# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


analysis_dir = Path.cwd()
setup_datas = collect_data_files("bodaqs_analysis.import_agent_assets")
app_icon_path = (analysis_dir / "import-agent" / "macos" / "bodaqs_import_manager.icns").resolve()
app_version = os.environ.get("BODAQS_APP_VERSION", "0.1.0-dev")
codesign_identity = os.environ.get("BODAQS_MAC_CODESIGN_IDENTITY") or None

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
    pathex=[str(analysis_dir)],
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
    name='BODAQS Import Manager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    icon=str(app_icon_path),
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=codesign_identity,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='BODAQS Import Manager',
)

app = BUNDLE(
    coll,
    name='BODAQS Import Manager.app',
    icon=str(app_icon_path),
    bundle_identifier='org.bodaqs.importmanager',
    info_plist={
        'CFBundleName': 'BODAQS Import Manager',
        'CFBundleDisplayName': 'BODAQS Import Manager',
        'CFBundleIdentifier': 'org.bodaqs.importmanager',
        'CFBundleShortVersionString': app_version,
        'CFBundleVersion': app_version,
        'CFBundleExecutable': 'BODAQS Import Manager',
        'NSHighResolutionCapable': True,
        'NSLocalNetworkUsageDescription': (
            'BODAQS Import Manager uses the local network to discover and '
            'download sessions from BODAQS loggers.'
        ),
        'NSBonjourServices': ['_bodaqs-logger._tcp'],
        'LSMinimumSystemVersion': '11.0',
    },
)
