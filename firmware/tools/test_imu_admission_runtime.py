"""Independent complete-link and mixed ADC resource schedules."""
from pathlib import Path
import argparse
import subprocess
import tempfile
p=argparse.ArgumentParser();p.add_argument("--compiler",default="g++");p.add_argument("--channel-rate",action="store_true");p.add_argument("--scaling",action="store_true");p.add_argument("--multi-node",action="store_true");p.add_argument("--sample-units-two-node",action="store_true");args=p.parse_args()
if args.multi_node: args.scaling=True
if args.scaling: args.channel_rate=True
root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="bodaqs-admission-") as temp:
    exe=Path(temp)/"admission.exe"
    flags=["-DBODAQS_ADC_CHANNEL_RATE_BENCH=1","-DBODAQS_SINGLE_NODE_IMU_ADC_SMOKE=1","-DBODAQS_SINGLE_NODE_IMU_SMOKE=1"] if args.channel_rate else []
    if args.scaling: flags.append("-DBODAQS_ADC_SCALING_BENCH=1")
    if args.multi_node: flags.append("-DBODAQS_MULTI_NODE_BENCH=1")
    if args.sample_units_two_node: flags += ["-DBODAQS_SPI_MEASUREMENT_V3=1", "-DBODAQS_SINGLE_NODE_IMU_SMOKE=1", "-DBODAQS_V3_TWO_NODE_BENCH=1"]
    subprocess.run([args.compiler,"-std=c++17",*flags,"-Wall","-Wextra","-Werror","-I",str(root/"src"),str(root/"test/imu_admission_fixture.cpp"),str(root/"src/ImuAdmission.cpp"),"-o",str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
    if args.sample_units_two_node:
        for invalid in [
            ['-DBODAQS_SINGLE_NODE_IMU_SMOKE=1','-DBODAQS_V3_TWO_NODE_BENCH=1'],
            flags+['-DBODAQS_SINGLE_NODE_IMU_ADC_SMOKE=1'],
            flags+['-DBODAQS_MULTI_NODE_BENCH=1'],
        ]:
            rejected=subprocess.run([args.compiler,'-std=c++17',*invalid,'-I',str(root/'src'),
                '-x','c++','-fsyntax-only','-'],input='#include "ImuAdmission.h"\n',text=True,
                stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            assert rejected.returncode!=0, 'Incompatible bench build unexpectedly compiled'
