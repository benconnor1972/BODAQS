"""Independent complete-link and mixed ADC resource schedules."""
from pathlib import Path
import argparse
import subprocess
import tempfile
p=argparse.ArgumentParser();p.add_argument("--compiler",default="g++");args=p.parse_args()
root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="bodaqs-admission-") as temp:
    exe=Path(temp)/"admission.exe"
    subprocess.run([args.compiler,"-std=c++17","-Wall","-Wextra","-Werror","-I",str(root/"src"),str(root/"test/imu_admission_fixture.cpp"),str(root/"src/ImuAdmission.cpp"),"-o",str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
