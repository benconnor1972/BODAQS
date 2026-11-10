"""Deterministic recipe fingerprint; never an assertion of installed image bytes."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path


def identity(root: Path, environment: str, options: dict) -> dict:
    inputs = {}
    board=root/"boards"/(str(options.get("board",""))+".json")
    if board.is_file():inputs[board.relative_to(root).as_posix()]=hashlib.sha256(
        board.read_bytes().replace(b"\r\n",b"\n")).hexdigest()
    for folder in ("src", "variants", "can-fd/common/protocol", "can-fd/common/transport"):
        for path in sorted((root / folder).rglob("*")):
            if path.is_file() and path.suffix in (".h", ".c", ".cpp", ".S"):
                inputs[path.relative_to(root).as_posix()] = hashlib.sha256(
                    path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    for pattern in ("platformio.ini", "*.csv", "tools/build_identity.py", "tools/configure_build_identity.py"):
        for path in sorted(root.glob(pattern)):
            inputs[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    recipe = {"schema": "bodaqs.build-recipe.v1", "environment": environment,
              "options": options, "inputs": inputs}
    fingerprint = hashlib.sha256(json.dumps(recipe, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**recipe, "id": "recipe-sha256:" + fingerprint}
