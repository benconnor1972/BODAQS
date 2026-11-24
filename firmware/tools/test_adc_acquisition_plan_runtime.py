"""Check acquisition-plan behavior against independently specified deadlines/layouts."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="bodaqs-adc-plan-") as tmp:
        exe = Path(tmp) / "plan.exe"
        subprocess.run([args.compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                        "-I", str(root / "src"), str(root / "test/adc_acquisition_plan_runtime_fixture.cpp"),
                        "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True, timeout=15)


if __name__ == "__main__":
    main()
