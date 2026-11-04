"""Exercise the storage worker with an independent blocking filesystem sink."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="bodaqs-storage-worker-") as temp:
        exe = Path(temp) / "storage-worker.exe"
        subprocess.run([args.compiler, "-std=c++17", "-Wall", "-Wextra", "-pthread",
                        "-I", str(root / "src"),
                        str(root / "test/storage_worker_runtime_fixture.cpp"),
                        "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True, timeout=20)


if __name__ == "__main__":
    main()
