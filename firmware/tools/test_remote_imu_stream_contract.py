"""Verify native stream ordering and provenance through independent CAN fixtures."""
from pathlib import Path
import argparse
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    firmware = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="bodaqs-stream-contract-") as temporary:
        executable = Path(temporary) / "stream_contract.exe"
        subprocess.run([
            args.compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-I", str(firmware / "src"),
            str(firmware / "test/remote_imu_stream_contract_fixture.cpp"),
            str(firmware / "src/RemoteImuStream.cpp"), "-o", str(executable),
        ], check=True)
        subprocess.run([str(executable)], check=True)
    print("Remote stream canonical anchor/model and provenance checks passed")


if __name__ == "__main__":
    main()
