"""Run the actual BMI270 preview adapter against independent acquisition evidence."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from runtime_test_helpers import definition


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', default='g++')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    adapter = definition((root / 'src/BMI270ImuSensor.cpp').read_text(),
                         'void BMI270ImuSensor::sampleValues(')
    retire = definition((root / 'src/BMI270FifoAcquisition.cpp').read_text(),
                        'bool BMI270FifoAcquisition::stopSession()')
    fixture = (root / 'test/bmi270_preview_runtime_fixture.cpp').read_text()
    fixture = fixture.replace('// PRODUCTION_RETIREMENT', retire)
    with tempfile.TemporaryDirectory(prefix='bodaqs-bmi-preview-') as temp:
        cpp, exe = Path(temp) / 'test.cpp', Path(temp) / 'test.exe'
        cpp.write_text(fixture.replace('// PRODUCTION_PREVIEW', adapter))
        subprocess.run([args.compiler, '-std=gnu++2a', '-Wall', '-Wextra',
                        '-I', str(root / 'src'), str(cpp), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
