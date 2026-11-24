"""Actual shared readiness adapter with independent configuration/hardware observations."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile
from runtime_test_helpers import definition


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler',default='g++')
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    actual=(root/'src/RecordingReadiness.cpp').read_text(encoding='utf-8')
    actual=re.sub(r'^#include "[^\n]+$', '', actual, flags=re.M)
    configured_access=definition((root/'src/SensorManager.cpp').read_text(encoding='utf-8'),'Sensor* getConfiguredSensor(')
    fixture=(root/'test/recording_readiness_runtime_fixture.cpp').read_text(encoding='utf-8').replace('// ACTUAL_READINESS',actual).replace('// ACTUAL_CONFIGURED_ACCESS',configured_access)
    with tempfile.TemporaryDirectory(prefix='bodaqs-readiness-') as temp:
        cpp,exe=Path(temp)/'test.cpp',Path(temp)/'test.exe';cpp.write_text(fixture,encoding='utf-8')
        for candidate in (0,1):
            subprocess.run([args.compiler,'-std=c++17','-Wall','-Wextra','-Werror','-DBODAQS_PRODUCTION_RECORDING=1',
                f'-DBODAQS_UNQUALIFIED_INTEGRATION_CANDIDATE={candidate}','-I',str(root/'src'),str(cpp),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)
        subprocess.run([args.compiler,'-std=c++17','-Wall','-Wextra','-Werror','-I',str(root/'src'),
            str(root/'test/recording_admission_decision_runtime_fixture.cpp'),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
    print('Shared readiness and strict/best-effort qualification/reservation decisions passed')


if __name__=='__main__':
    main()
