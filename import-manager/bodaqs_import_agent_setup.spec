# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


import_manager_dir = Path.cwd()
repo_root = import_manager_dir.parent
analysis_dir = repo_root / "analysis"
generated_dir = import_manager_dir / "build" / "generated"
generated_dir.mkdir(parents=True, exist_ok=True)
app_version = os.environ.get("BODAQS_IMPORT_MANAGER_APP_VERSION", "").strip()
(generated_dir / "bodaqs_import_manager_build_version.py").write_text(
    f"APP_VERSION = {app_version!r}\n",
    encoding="utf-8",
)
setup_datas = collect_data_files("bodaqs_import_manager.import_agent_assets")
app_icon_path = (import_manager_dir / "packaging" / "windows" / "bodaqs_import_agent.ico").resolve()
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
        "pystray._win32",
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
    name='bodaqs-import-setup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
    upx=True,
    upx_exclude=[],
    name='bodaqs-import-setup',
)
