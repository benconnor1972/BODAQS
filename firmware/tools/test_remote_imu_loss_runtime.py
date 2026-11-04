"""Exercise bounded remote queues through the actual stream API."""
from pathlib import Path
import argparse
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--compiler", default="g++")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="bodaqs-loss-") as folder:
    executable = Path(folder) / "loss.exe"
    subprocess.run([args.compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                    "-I", str(root / "src"), str(root / "test/remote_imu_loss_fixture.cpp"),
                    str(root / "src/RemoteImuStream.cpp"), "-o", str(executable)], check=True)
    subprocess.run([str(executable)], check=True)
print("Remote whole-batch loss, exact counters and periodic evidence reserve passed")
