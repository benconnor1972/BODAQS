"""Exercise production log-start preflight and transitions with hardware mocked."""
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
    manager = (root / "src/SensorManager.cpp").read_text(encoding="utf-8")
    logging = (root / "src/LoggingManager.cpp").read_text(encoding="utf-8")
    config = (root / "src/ConfigManager.cpp").read_text(encoding="utf-8")
    buttons = (root / "src/ButtonActions.cpp").read_text(encoding="utf-8")
    bmi = (root / "src/BMI270ImuSensor.cpp").read_text(encoding="utf-8")
    bmi_header = (root / "src/BMI270ImuSensor.h").read_text(encoding="utf-8")
    routes = (root / "src/Routes_Config.cpp").read_text(encoding="utf-8")
    html = (root / "src/HtmlUtil.cpp").read_text(encoding="utf-8")
    fixture = (root / "test/logging_start_runtime_fixture.cpp").read_text(encoding="utf-8")
    fixture = fixture.replace("// PRODUCTION_PREFLIGHT", "\n".join(
        definition(manager, sig) for sig in (
            "  int liveIndex_(", "  bool configuredActive_(", "void noteLiveConfiguration(",
            "LoggingConfigIssue configurationIssue(", "bool requiresBdqV2(")))
    fixture = fixture.replace("// PRODUCTION_START", "\n".join(
        definition(logging, sig) for sig in (
            "void LoggingManager::refreshConfigurationStatus(",
            "LoggingConfigIssue LoggingManager::configurationIssue(",
            "const char* LoggingManager::configurationDetail(", "bool LoggingManager::start(")))
    fixture = fixture.replace("// PRODUCTION_FORMAT", definition(config, "bool ConfigManager::setLogFormat("))
    fixture = fixture.replace("// PRODUCTION_BUTTON", definition(buttons, "  void handleButtonBinding_("))
    fixture = fixture.replace("// PRODUCTION_NOTICE", "namespace HtmlUtil {\n" +
        definition(html, "  String htmlEscape(") + "\n}\n" + definition(routes, "static String configurationNotice_("))
    fixture = fixture.replace("// PRODUCTION_BMI_PARAMS", definition(bmi_header, "  struct Params {") + ";")
    fixture = fixture.replace("// PRODUCTION_BMI", "\n".join(
        definition(bmi, sig) for sig in (
            "void copyField_(", "bool readString_(", "bool orientationsEqual_(", "void loadOrientation_(",
            "void canonicalizeToken_(", "bool parseGyroBiasMode_(", "bool BMI270ImuSensor::loadParams_(",
            "bool BMI270ImuSensor::loggingRestartRequired(")))
    with tempfile.TemporaryDirectory(prefix="bodaqs-log-start-") as temp:
        cpp, exe = Path(temp) / "runtime.cpp", Path(temp) / "runtime.exe"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run([args.compiler, "-std=gnu++2a", "-Wall", "-Wextra", "-Wno-unused-variable",
                        "-I", str(root / "test/stubs"), "-I", str(root / "src"),
                        str(cpp), str(root / "src/SensorAssignment.cpp"),
                        str(root / "src/SensorParams.cpp"), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
