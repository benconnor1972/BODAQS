"""Execute production bus management and FIFO startup recovery with injected faults.

The manager source and FIFO begin method are compiled verbatim against fake
controllers, GPIO and semaphores. This checks policy and failure handling;
it cannot establish electrical timing or actual ESP32 driver behaviour.
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

from runtime_test_helpers import definition


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    manager = (root / "src/I2CManager.cpp").read_text()
    manager = re.sub(r'^#include[^\n]*\n', '', manager, flags=re.MULTILINE)
    fifo = definition((root / "src/BMI270FifoAcquisition.cpp").read_text(),
                      "bool BMI270FifoAcquisition::begin(bool allowBusRecovery)")
    fixture = (root / "test/i2c_startup_runtime_fixture.cpp").read_text()
    fixture = fixture.replace("// PRODUCTION_MANAGER", manager)
    fixture = fixture.replace("// PRODUCTION_FIFO_BEGIN", fifo)
    with tempfile.TemporaryDirectory(prefix="bodaqs-startup-runtime-") as temp:
        cpp = Path(temp) / "runtime.cpp"
        exe = Path(temp) / "runtime.exe"
        (Path(temp) / "Wire.h").write_text("#pragma once\n")
        cpp.write_text(fixture)
        subprocess.run([args.compiler, "-std=gnu++2a", "-Wall", "-Wextra",
                        "-Wno-unused-parameter", "-I", temp, "-I", str(root / "src"),
                        str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
