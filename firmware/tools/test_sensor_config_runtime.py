"""Exercise idle sensor edits with production configuration storage and fake hardware."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from runtime_test_helpers import definition


def without_includes(text):
    return "\n".join(line for line in text.splitlines() if not line.startswith("#include"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    json_include = root / ".pio/libdeps/bodaqs_s3_mini_n4r2/ArduinoJson/src"
    if not (json_include / "ArduinoJson.h").exists():
        json_include = root / ".pio/libdeps/bodaqs_a8_production/ArduinoJson/src"
    if not (json_include / "ArduinoJson.h").exists():
        parser.error("Install A8 dependencies first: pio pkg install -d firmware -e bodaqs_s3_mini_n4r2")
    fixture = (root / "test/sensor_config_runtime_fixture.cpp").read_text(encoding="utf-8")
    fixture = fixture.replace("// PRODUCTION_CONFIG", without_includes((root / "src/ConfigManager.cpp").read_text(encoding="utf-8")))
    fixture = fixture.replace("// PRODUCTION_EDIT", without_includes((root / "src/SensorConfigEdit.cpp").read_text(encoding="utf-8")))
    routes = (root / "src/Routes_Api.cpp").read_text(encoding="utf-8")
    fixture = fixture.replace("// PRODUCTION_API", "\n".join(definition(routes, sig) for sig in (
        "constexpr bool productionRecordingBuild_(",
        "static bool configEditLocked_(", "static bool rejectConfigEditLocked_(",
        "static bool parseSensorTypeKey_(", "static const char* loggerOutputModeName_(",
        "static long parseLoggerOutputMode_(", "static void addSensorParamsJson_(",
        "static void addControlApplyJson_(", "static void addImuConfigurationJson_(",
        "static void addSensorJson_(", "static bool readSensorIndexArg_(",
        "static void handleSensorGet_(", "static void seedSensorDefaults_(",
        "static bool commitSensorEdit_(", "static bool applySensorJson_(", "static void handleSensorPut_(",
        "static void handleSensorPost_(", "static void handleSensorDelete_(")))
    web = (root / "src/Routes_Config.cpp").read_text(encoding="utf-8")
    start = web.index('  S->on("/config/sensors", HTTP_POST')
    start = web.index("    noteHttpActivity_();", start)
    end = web.index("\n  });", start)
    body = web[start:end].replace("commitSensorEdit_(", "web::commitSensorEdit_(").replace("parseLoggerOutputMode_(", "web::parseLoggerOutputMode_(").replace("rejectConfigEditLocked_(", "web::rejectConfigEditLocked_(")
    fixture = fixture.replace("// PRODUCTION_WEB", "namespace web {\n" + "\n".join(
        definition(web, sig) for sig in (
            "static bool configEditLocked_(", "static bool rejectConfigEditLocked_(",
            "static bool commitSensorEdit_(", "static OutputMode loggerSupportedOutputMode_(",
            "static OutputMode parseLoggerOutputMode_(", "static const char* defaultNamePrefix_(",
            "static String uniqueSensorName_(", "static bool analogInputConfigured_(")) +
        "\nvoid post(WebServer& srv) {\n" + body + "\n}\n}\n")
    with tempfile.TemporaryDirectory(prefix="bodaqs-sensor-edit-") as temp:
        cpp, exe = Path(temp) / "runtime.cpp", Path(temp) / "runtime.exe"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run([args.compiler, "-std=gnu++2a", "-Wall", "-Wno-unused", "-I", str(json_include), "-I", str(root / "test/stubs"), "-I", str(root / "src"), str(cpp), str(root / "src/ImuAdmission.cpp"), str(root / "src/SensorParams.cpp"), str(root / "src/SensorAssignment.cpp"), str(root / "can-fd/common/protocol/bodaqs_control.c"), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
