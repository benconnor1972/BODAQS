"""Exercise the restored production scheduler's client selection and yield limit.

Client methods and time are mocked; the selection functions and BMI270's yield
limit are extracted from production source. This does not simulate wire timing.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

from runtime_test_helpers import definition


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    scheduler = (root / "src/I2CBusScheduler.cpp").read_text()
    header = (root / "src/BMI270FifoAcquisition.h").read_text()
    methods = "\n\n".join(definition(scheduler, signature) for signature in (
        "ClientSlot* nextDueClient_(", "ClientSlot* latencySensitiveClientBeforeBlock_("))
    limit = definition(header, "uint8_t asyncMaximumLatencySensitiveYields() const override")
    fixture = (root / "test/i2c_schedule_runtime_fixture.cpp").read_text()
    fixture = fixture.replace("// PRODUCTION_YIELD_LIMIT", limit)
    fixture = fixture.replace("// PRODUCTION_SELECTION", methods)
    with tempfile.TemporaryDirectory(prefix="bodaqs-simple-schedule-") as temp:
        cpp = Path(temp) / "runtime.cpp"
        exe = Path(temp) / "runtime.exe"
        cpp.write_text(fixture)
        subprocess.run([args.compiler, "-std=gnu++2a", "-Wall", "-Wextra",
                        "-I", str(root / "src"), str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
