"""Compile real ESP32 ADC/shared-SPI code against GPIO/SPI/RTOS boundary fixtures."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--case-runner", action="store_true", help="Also compile public serial/result and transport seam")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="bodaqs-spi-probe-") as temp:
        temp = Path(temp)
        arduino = (root / "test/stubs/Arduino.h").read_text(encoding="utf-8")
        arduino = arduino.replace('inline void delay(unsigned long /*ms*/) {}', 'void delay(unsigned long ms);')
        start = arduino.index('inline unsigned long millis()')
        end = arduino.index('\n}', start) + 2
        arduino = arduino[:start] + 'unsigned long millis();' + arduino[end:]
        arduino += (root / "test/spi_probe_stubs/ArduinoBoundary.h").read_text(encoding="utf-8")
        (temp / "Arduino.h").write_text(arduino, encoding="utf-8")
        for src in (root / "test/spi_probe_stubs").rglob("*.h"):
            if src.name == "ArduinoBoundary.h":
                continue
            dest = temp / src.relative_to(root / "test/spi_probe_stubs")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        fixture = (root / "test/spi_probe_runtime_fixture.cpp").read_text(encoding="utf-8")
        config_support = (root / "test/sensor_config_runtime_fixture.cpp").read_text(encoding="utf-8").split('// PRODUCTION_CONFIG')[0]
        config_support = '\n'.join(line for line in config_support.splitlines()
            if not any(s in line for s in ('ArduinoJson', 'convertFromJson', 'canConvertFromJson', 'WebServer.h', 'namespace AnalogInputManager')))
        config = '\n'.join(line for line in (root / "src/ConfigManager.cpp").read_text(encoding="utf-8").splitlines() if not line.startswith('#include'))
        fixture = fixture.replace('// CONFIG_SUPPORT', config_support + '\n' + config)
        if args.case_runner:
            fixture = '#define TEST_CASE_RUNNER 1\n' + fixture
        cpp, exe = temp / "fixture.cpp", temp / "fixture.exe"
        cpp.write_text(fixture, encoding="utf-8")
        sources = [root / 'src' / name for name in ('AnalogInputManager.cpp', 'SharedSpiBus.cpp', 'SensorParams.cpp', 'SensorAssignment.cpp', 'BoardProfile.cpp')]
        sources += [root / 'can-fd/common/protocol/bodaqs_control.c']
        if args.case_runner:
            sources += [root / 'src' / name for name in ('SpiMeasurementProbe.cpp', 'SpiProbeTransport.cpp', 'SpiProbeCodec.cpp')]
        subprocess.run([args.compiler, '-std=gnu++2a', '-pthread', '-DESP32=1', '-DBODAQS_SPI_PROBE=1', '-DLOG_COMPILED=0', '-Wno-unused', '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', '-I', str(temp), '-I', str(root / 'test/stubs'), '-I', str(root / 'src'), str(cpp), *map(str, sources), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True, timeout=15)


if __name__ == '__main__':
    main()
