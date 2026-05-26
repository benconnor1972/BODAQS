from pathlib import Path
import sys


_REPO_ROOT = Path(__file__).resolve().parents[1]
_ANALYSIS_DIR = _REPO_ROOT / "analysis"
if str(_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_ANALYSIS_DIR))

from bodaqs_import_manager.import_agent_setup import main


if __name__ == "__main__":
    raise SystemExit(main())
