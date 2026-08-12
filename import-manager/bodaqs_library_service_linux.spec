# -*- mode: python ; coding: utf-8 -*-
#
# Linux PyInstaller spec for the BODAQS Library Service. The resulting bundle
# is placed in the manager bundle's service/ directory by the Linux build
# script.

import os
from pathlib import Path


import_manager_dir = Path.cwd()
repo_root = import_manager_dir.parent
analysis_dir = repo_root / "analysis"
generated_dir = import_manager_dir / "build" / "generated"
generated_dir.mkdir(parents=True, exist_ok=True)
service_version = os.environ.get("BODAQS_LIBRARY_SERVICE_VERSION", "").strip() or "0.1.0-dev"
(generated_dir / "bodaqs_library_service_build_version.py").write_text(
    f"SERVICE_VERSION = {service_version!r}\n",
    encoding="utf-8",
)

service_excludes = [
    "IPython",
    "jedi",
    "matplotlib",
    "nbformat",
    "PIL",
    "pytest",
    "tornado",
    "zmq",
]


a = Analysis(
    ["bodaqs_library_service.py"],
    pathex=[str(generated_dir), str(import_manager_dir), str(analysis_dir)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "bodaqs_analysis.library_api_service",
        "bodaqs_analysis.library_api_service.app",
        "bodaqs_analysis.library_api_service.cli",
        "fastapi",
        "starlette",
        "uvicorn",
        "uvicorn.lifespan.on",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.logging",
        "tkinter",
        "tkinter.filedialog",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=service_excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="bodaqs-library-service",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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
    upx=False,
    upx_exclude=[],
    name="bodaqs-library-service",
)
