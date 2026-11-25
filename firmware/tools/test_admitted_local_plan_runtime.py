"""Exercise the actual local plan at its admitted membership boundary."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from runtime_test_helpers import definition


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler',default='g++')
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    source=(root/'src/SensorManager.cpp').read_text(encoding='utf-8')
    actual='\n'.join(definition(source,signature) for signature in (
        '  bool participates_(', '  void addSessionIssue_(',
        'bool validateLoggingStart(', 'uint32_t sessionParticipantMask('))
    fixture=(root/'test/admitted_local_plan_runtime_fixture.cpp').read_text(encoding='utf-8').replace('// ACTUAL_PLAN',actual)
    with tempfile.TemporaryDirectory(prefix='bodaqs-admitted-plan-') as temp:
        cpp,exe=Path(temp)/'test.cpp',Path(temp)/'test.exe';cpp.write_text(fixture,encoding='utf-8')
        subprocess.run([args.compiler,'-std=c++17','-Wall','-Wextra','-Werror','-DBODAQS_PRODUCTION_RECORDING=1',
                        str(cpp),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
    print('Actual local plan preserves admitted masks and strict/best-effort failures')


if __name__=='__main__':
    main()
