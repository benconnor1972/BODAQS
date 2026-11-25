"""Run real BMI270 readiness, preparation and prepared validation with independent I/O."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from runtime_test_helpers import definition


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler',default='g++')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    source=(root/'src/BMI270ImuSensor.cpp').read_text(encoding='utf-8')
    header=(root/'src/BMI270ImuSensor.h').read_text(encoding='utf-8')
    fixture=(root/'test/bmi270_readiness_runtime_fixture.cpp').read_text(encoding='utf-8')
    fixture=fixture.replace('// ACTUAL_PARAMS',definition(header,'  struct Params {')+';')
    sensor_header=(root/'src/Sensor.h').read_text(encoding='utf-8')
    fixture=fixture.replace('// ACTUAL_DEFAULT_OBSERVER',definition(sensor_header,'  virtual bool observeLoggingReadiness('))
    signatures=(
        'void copyField_(', 'bool fail_(', 'bool readString_(', 'bool orientationsEqual_(',
        'void loadOrientation_(', 'void canonicalizeToken_(', 'bool validMountSemantics_(',
        'bool parseGyroBiasMode_(', 'BMI270ImuSensor::BMI270ImuSensor(',
        'bool BMI270ImuSensor::loadParams_(', 'bool BMI270ImuSensor::validateSpec(',
        'bool BMI270ImuSensor::loggingRestartRequired(',
        'bool BMI270ImuSensor::prepareLoggingStart(', 'bool BMI270ImuSensor::validateLoggingStart(',
    )
    methods='\n'.join(definition(source,signature) for signature in signatures)
    # The old idle preflight used the prepared validator. Preserve that baseline
    # for red/green: a missing observational hook must still fail the 400 Hz case.
    observation='bool BMI270ImuSensor::observeLoggingReadiness('
    if observation in source:
        methods+='\n'+definition(source,observation)
    else:
        methods+='\n'+definition(source,'bool BMI270ImuSensor::validateLoggingStart(').replace(
            'BMI270ImuSensor::validateLoggingStart','BMI270ImuSensor::observeLoggingReadiness')
    if 'bool BMI270ImuSensor::resolveLoggingConfiguration_(' in source:
        methods+='\n'+definition(source,'bool BMI270ImuSensor::resolveLoggingConfiguration_(')
    fixture=fixture.replace('// ACTUAL_METHODS',methods)
    with tempfile.TemporaryDirectory(prefix='bodaqs-bmi-readiness-')as temp:
        cpp,exe=Path(temp)/'test.cpp',Path(temp)/'test.exe'
        cpp.write_text(fixture,encoding='utf-8')
        subprocess.run([args.compiler,'-std=gnu++2a','-Wall','-Wextra','-Werror',
                        '-I',str(root/'test/stubs'),'-I',str(root/'src'),str(cpp),
                        str(root/'src/SensorParams.cpp'),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)


if __name__=='__main__':main()
