from __future__ import annotations

from importlib.resources.abc import TraversableResources
from pathlib import Path
from typing import BinaryIO, Iterable


_ASSET_ROOT = Path(__file__).resolve().parents[3] / "import-manager" / "bodaqs_import_manager" / "import_agent_assets"


class _ImportManagerAssetReader(TraversableResources):
    def files(self) -> Path:
        return _ASSET_ROOT

    def open_resource(self, resource: str) -> BinaryIO:
        return (_ASSET_ROOT / resource).open("rb")

    def resource_path(self, resource: str) -> str:
        return str(_ASSET_ROOT / resource)

    def is_resource(self, path: str) -> bool:
        return (_ASSET_ROOT / path).is_file()

    def contents(self) -> Iterable[str]:
        return (entry.name for entry in _ASSET_ROOT.iterdir())


class _ImportManagerAssetLoader:
    def get_resource_reader(self, fullname: str) -> _ImportManagerAssetReader:
        return _ImportManagerAssetReader()


if __spec__ is not None:
    __spec__.loader = _ImportManagerAssetLoader()
