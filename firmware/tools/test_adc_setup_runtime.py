"""Exercise the production ADC manager against a register/START/DRDY model.

Only includes are replaced, as in the existing runtime fixtures. Run both the
synchronous fallback and ESP32 worker/notification paths. This measures wire
commands, not physical ADC settling or target execution time.
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--manager-source", type=Path,
                        help="Optional saved source for baseline/regression checks")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = (args.manager_source or root / "src/AnalogInputManager.cpp").read_text(encoding="utf-8")
    source = re.sub(r'^#include[^\n]*\n', '', source, flags=re.MULTILINE)
    fixture = (root / "test/adc_setup_runtime_fixture.cpp").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="bodaqs-adc-setup-") as temp:
        temp = Path(temp)
        (temp / "SPI.h").write_text('''#pragma once
#include <stdint.h>
constexpr int MSBFIRST=1, SPI_MODE1=1;
struct SPISettings { SPISettings(uint32_t, int, int) {} };
''', encoding="utf-8")
        cpp = temp / "fixture.cpp"
        cpp.write_text(fixture.replace("// PRODUCTION_MANAGER", source), encoding="utf-8")
        for async_path, wreg_starts in ((0, 0), (1, 0), (0, 1), (1, 1)):
            exe = temp / f"fixture-{async_path}-{wreg_starts}.exe"
            subprocess.run([
                args.compiler, "-std=gnu++2a", "-Wall", "-Wextra", "-Werror",
                "-Wno-unused-variable", "-Wno-unused-function", "-Wno-unused-parameter",
                f"-DADC_TEST_ASYNC={async_path}", "-I", str(temp),
                f"-DADC_TEST_WREG_STARTS={wreg_starts}",
                "-I", str(root / "test/stubs"), "-I", str(root / "src"),
                str(cpp), str(root / "src/SensorParams.cpp"), "-o", str(exe)
            ], check=True)
            subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
