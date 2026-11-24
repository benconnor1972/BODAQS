"""Exercise actual file-sink timing and the additive recording-pressure footer."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from runtime_test_helpers import definition


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    storage = (root / "src/StorageManager.cpp").read_text(encoding="utf-8")
    adapter = definition(storage, "static void appendRecordingPressure_(")
    observer = definition(storage, "static void observeBdqV2FileOperation_(")
    footer = definition(storage, "static String buildBdqV2FinalSummary_(")
    assert "appendRecordingPressure_(document);" in footer
    fixture = (root / "test/recording_pressure_fixture.cpp").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="bodaqs-pressure-") as temporary:
        temp = Path(temporary)
        (temp / "Arduino.h").write_text(
            "#pragma once\n#include <stdint.h>\n#include <stddef.h>\nuint32_t micros();\n", encoding="utf-8")
        (temp / "FS.h").write_text('''#pragma once
#include <stddef.h>
#include <stdint.h>
extern uint32_t clockUs;
struct File {
 uint32_t writeUs=0,flushUs=0;
 explicit operator bool() const {return true;}
 size_t write(const uint8_t*,size_t n) {clockUs+=writeUs;return n;}
 void flush() {clockUs+=flushUs;}
};
''', encoding="utf-8")
        cpp, exe = temp / "fixture.cpp", temp / "fixture.exe"
        cpp.write_text(fixture.replace("// PRODUCTION_ADAPTER", adapter + "\n" + observer), encoding="utf-8")
        subprocess.run([args.compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-DBODAQS_IMU_FLOW_DIAGNOSTICS=1", "-DBODAQS_RECORDING_PRESSURE_DIAGNOSTICS=1",
            "-I", str(temp), "-I", str(root / "src"),
            "-I", str(root / ".pio/libdeps/bodaqs_s3_mini_n4r2/ArduinoJson/src"),
            str(cpp), "-o", str(exe)], check=True)
        result = subprocess.run([str(exe)], check=True, text=True, capture_output=True)
        report = json.loads(result.stdout)
        pressure = report["recording_pressure"]
        assert pressure["available"] and pressure["first_loss"]["node"] == 1
        assert pressure["first_loss"]["observed_us"] == 400000
        assert pressure["first_loss"]["nodes"][0]["packet_queue_depth"] == 2048
        assert pressure["first_loss"]["nodes"][0]["consumer_wait"] == 1
        assert pressure["first_loss"]["nodes"][0]["first_consumer_wait_us"] == 350000
        assert pressure["storage_frozen"] and pressure["storage_overwritten"] == 0
        writes = pressure["storage_operations"]
        assert writes[0] == dict(started_us=300000, duration_us=200000, bytes=16384,
                                primary_queue_depth=91, operation=3)
        assert writes[1]["operation"] == 4 and writes[1]["duration_us"] == 100
        assert len(writes) == 3  # Includes the operation crossing the post-loss cutoff.
        assert pressure["service_gaps"] == [dict(started_us=350000, duration_us=50000),
                                             dict(started_us=400000, duration_us=2100000)]
        print("recording pressure: actual sink intervals, queue snapshot, wrap/reset, bounded freeze and JSON PASS")


if __name__ == "__main__":
    main()
