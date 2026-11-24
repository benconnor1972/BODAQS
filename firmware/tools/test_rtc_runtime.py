"""Run production RTC detection/drivers against register-level I2C fault injection.

Uses the same extraction harness as the other firmware runtime tests. Network
services and system time are mocked; device timing and backup retention need
bench checks on each board revision.
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
    source = (root / "src/RTCManager.cpp").read_text()
    state = source[source.index("static RTCSource currentSource"):
                   source.index("static char s_timezone_")]
    clock = source[source.index("static constexpr time_t kSaneEpoch_"):
                   source.index("static void splitCsv3_")]
    drivers = source[source.index("static constexpr uint8_t kRv3028StatusReg_"):
                     source.index("static bool setSystemEpoch_")]
    signatures = (
        "static int64_t daysFromCivil_(", "static bool epochFromUtcTm_(",
        "static uint8_t bcdToDec_(", "static uint8_t decToBcd_(",
        "static bool rtcI2cRead_(", "static bool rtcI2cWrite_(",
    )
    methods = "\n\n".join(definition(source, s) for s in signatures)
    api = "\n\n".join(definition(source, s) for s in (
        "static bool setSystemEpoch_(", "bool RTCManager_usingExternalRtc(",
        "bool RTCManager_externalRtcLastReadOk(", "bool RTCManager_externalRtcPorf(",
        "const char* RTCManager_sourceLabel(",
        "void RTCManager_begin(RTCSource source,", "void RTCManager_begin(const board::",
        "void RTCManager_sync(",
    ))
    fixture = (root / "test/rtc_runtime_fixture.cpp").read_text()
    fixture = fixture.replace("// PRODUCTION_RTC", "\n\n".join(
        (state, clock, methods, drivers, api)))
    with tempfile.TemporaryDirectory(prefix="bodaqs-rtc-runtime-") as temp:
        cpp, exe = Path(temp) / "runtime.cpp", Path(temp) / "runtime.exe"
        cpp.write_text(fixture)
        subprocess.run([args.compiler, "-std=gnu++2a", "-Wall", "-Wextra",
                        "-Wno-unused-parameter", "-Wno-unused-variable",
                        "-I", str(root / "test/stubs"), "-I", str(root / "src"),
                        str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
