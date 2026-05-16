# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


analysis_dir = Path.cwd()
cli_excludes = [
    "IPython",
    "jedi",
    "matplotlib",
    "nbformat",
    "PIL",
    "pytest",
    "tkinter",
    "tornado",
    "zmq",
]


a = Analysis(
    ['bodaqs_import_agent_cli.py'],
    pathex=[str(analysis_dir)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=cli_excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='bodaqs-import',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
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
    name='bodaqs-import',
)
