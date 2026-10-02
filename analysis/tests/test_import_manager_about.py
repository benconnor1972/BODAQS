import codecs
import json
import sys
from pathlib import Path


IMPORT_MANAGER_ROOT = Path(__file__).resolve().parents[2] / "import-manager"
if str(IMPORT_MANAGER_ROOT) not in sys.path:
    sys.path.insert(0, str(IMPORT_MANAGER_ROOT))

from bodaqs_import_manager import import_agent_setup  # noqa: E402


def test_component_version_lines_accept_windows_utf8_bom(
    tmp_path: Path,
    monkeypatch,
) -> None:
    executable = tmp_path / "manager" / "bodaqs-import-setup.exe"
    executable.parent.mkdir()
    executable.touch()
    payload = {
        "bundle": {"name": "BODAQS Desktop", "version": "0.6.0-dev"},
        "components": [
            {"name": "BODAQS Import Manager", "version": "0.2.0-dev"},
            {"name": "BODAQS Library Service", "version": "0.2.0-dev"},
            {"name": "BODAQS Workbench", "version": "0.6.0-dev"},
        ],
    }
    manifest = tmp_path / "component_versions.json"
    manifest.write_bytes(codecs.BOM_UTF8 + json.dumps(payload).encode("utf-8"))
    monkeypatch.setattr(import_agent_setup.sys, "executable", str(executable))

    assert import_agent_setup._component_version_lines() == [
        "BODAQS Desktop: 0.6.0-dev",
        "BODAQS Import Manager: 0.2.0-dev",
        "BODAQS Library Service: 0.2.0-dev",
        "BODAQS Workbench: 0.6.0-dev",
    ]
