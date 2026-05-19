# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


analysis_dir = Path.cwd()
setup_datas = collect_data_files("bodaqs_analysis.import_agent_assets")
app_icon_path = (analysis_dir / "import-agent" / "windows" / "bodaqs_import_agent.ico").resolve()
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
