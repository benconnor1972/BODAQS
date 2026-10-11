"""Exercise production startup capture and SD rotation with injected failures.

Production collector, bounded buffer, atomic text-save and rotation code are
compiled verbatim. Serial, time, memory allocation and filesystem are mocked.
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

from runtime_test_helpers import definition


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    collector = (root / "src/StartupLog.cpp").read_text()
    collector = re.sub(r'^#include[^\n]*\n', '', collector, flags=re.MULTILINE)
    storage = (root / "src/StorageManager.cpp").read_text()
    methods = "\n\n".join(definition(storage, signature) for signature in (
        "static bool ensureParentDirs_(", "bool StorageManager_saveTextFile(",
        "bool StorageManager_saveStartupReport("))
    fixture = (root / "test/startup_log_runtime_fixture.cpp").read_text()
    fixture = fixture.replace("// PRODUCTION_STORAGE", methods)
    fixture = fixture.replace("// PRODUCTION_COLLECTOR", collector)
    with tempfile.TemporaryDirectory(prefix="bodaqs-startup-report-") as temp:
        cpp = Path(temp) / "runtime.cpp"
        exe = Path(temp) / "runtime.exe"
        cpp.write_text(fixture)
        subprocess.run([args.compiler, "-std=gnu++2a", "-Wall", "-Wextra",
                        "-I", str(root / "src"), str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
