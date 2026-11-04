"""Compile actual master timer adapter against explicit hardware register fixtures."""
from pathlib import Path
import argparse
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "can-fd/master"
    with tempfile.TemporaryDirectory(prefix="bodaqs-master-timing-") as temporary:
        executable = Path(temporary) / "timing.exe"
        subprocess.run([args.compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                        "-I", str(root / "test"), "-I", str(root / "include"),
                        str(root / "test/test_timing.c"), str(root / "src/master_timing.c"),
                        "-o", str(executable)], check=True)
        subprocess.run([str(executable)], check=True)
    print("Master native clock, hardware SYNC events, wrap and periodic backpressure passed")


if __name__ == "__main__":
    main()
