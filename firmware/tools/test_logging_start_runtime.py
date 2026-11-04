"""Exercise production log-start preflight and transitions with hardware mocked."""
import argparse
from pathlib import Path
import subprocess
import tempfile

from runtime_test_helpers import definition


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--async-storage", action="store_true")
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
            "  int liveIndex_(", "  bool configuredActive_(", "  bool assignmentMatchesType_(",
            "void noteLiveConfiguration(",
            "const SensorDiagnosticList& configurationDiagnostics(",
            "LoggingConfigIssue configurationIssue(",
            "bool requiresBdqV2(")))
    fixture = fixture.replace("// PRODUCTION_START", "\n".join(
        definition(logging, sig) for sig in (
            "void LoggingManager::refreshConfigurationStatus(",
            "LoggingConfigIssue LoggingManager::configurationIssue(",
            "const char* LoggingManager::configurationDetail(", "bool LoggingManager::isStarting(",
            "void LoggingManager::cancelStart(", "bool LoggingManager::configurationLocked(", "LoggingManager::StartResult LoggingManager::requestStart(",
            "void LoggingManager::loop(", "void LoggingManager::stop(", "void LoggingManager::completeStorageStart(", "void LoggingManager::finishStorageStop(", "bool LoggingManager::start(")))
    fixture = fixture.replace("// PRODUCTION_FORMAT", definition(config, "bool ConfigManager::setLogFormat("))
    fixture = fixture.replace("// PRODUCTION_TOGGLE", definition(buttons, "void ButtonActions::onToggleLogging(").replace("void ButtonActions::onToggleLogging(", "void onToggleLogging("))
    fixture = fixture.replace("// PRODUCTION_BUTTON", definition(buttons, "  void handleButtonBinding_("))
    fixture = fixture.replace("// PRODUCTION_NOTICE", "namespace HtmlUtil {\n" +
        definition(html, "  String htmlEscape(") + "\n}\n" + definition(routes, "static String configurationNotice_("))
    fixture = fixture.replace("// PRODUCTION_BMI_PARAMS", definition(bmi_header, "  struct Params {") + ";")
    fixture = fixture.replace("// PRODUCTION_BMI", "\n".join(
        definition(bmi, sig) for sig in (
            "void copyField_(", "bool readString_(", "bool orientationsEqual_(", "void loadOrientation_(",
            "void canonicalizeToken_(", "bool parseGyroBiasMode_(", "bool BMI270ImuSensor::loadParams_(",
            "bool BMI270ImuSensor::loggingRestartRequired(")))
    if args.async_storage:
        fixture = fixture.replace('#include <cassert>', '#include <cassert>\n#include <atomic>\n#include <thread>\n#include "RecordingStorageWorker.h"')
        fixture = fixture.replace('enum class StopReason { StartFailure, UserRequest, Unspecified };',
                                  'enum class StopReason { StartFailure, UserRequest, Unspecified, StorageFailure, StorageUnresponsive };')
        fixture = fixture.replace('bool StorageManager_startLog() { events.push_back("file"); fileFormat = g_cfg.logFormat; return openOk; }', r"""
std::atomic<bool> blocked{false}, entered{false};
int blockedOperation = 0;
bool serviceFails = false, queueRoom = true;
void gate(int operation) {
  if (operation != blockedOperation) return;
  entered.store(true);
  while (blocked.load()) std::this_thread::yield();
}
struct TestStorageSink : RecordingStorageSink {
  bool healthCheck() override { gate(1); return storageOk; }
  bool start() override { events.push_back("file"); gate(2); return openOk; }
  bool service() override { gate(3); return !serviceFails; }
  bool stop(bool clean) override { gate(4); events.push_back(clean ? "close" : "failed_close"); return clean; }
} storageSink;
RecordingStorageWorker storageWorker(storageSink);
bool StorageManager_startLog() { return storageWorker.requestStart(); }
bool StorageManager_recordingIoPending() { return storageWorker.pending(); }
bool StorageManager_recordingReady() { return storageWorker.recording(); }
bool StorageManager_storageFault() { return storageWorker.fault() != RecordingStorageWorker::Fault::None; }
bool StorageManager_canAcceptSample() { return queueRoom; }
bool StorageManager_storageUnresponsive() { return storageWorker.fault() == RecordingStorageWorker::Fault::Unresponsive; }
""")
        fixture = fixture.replace('void StorageManager_stopLog() { events.push_back("close"); }',
                                  'void StorageManager_stopLog() { storageWorker.requestStop(); }')
        fixture = fixture.replace('extern bool s_stopping;', 'size_t finalRows = 0;\nextern bool s_stopping;')
        fixture = fixture.replace('size_t pendingLoggingRows() { return 0; }',
                                  'size_t pendingLoggingRows() { return finalRows; }')
        fixture = fixture.replace('bool sampleOnce_(bool) { return false; }',
                                  'bool sampleOnce_(bool) { if (!finalRows) return false; --finalRows; events.push_back("tail_row"); return true; }')
        fixture = fixture.replace('void LoggingManager::refreshConfigurationStatus() {', r"""
#define ESP32 1
void* s_sampleTask = reinterpret_cast<void*>(1);
std::atomic<bool> s_sampleInProgress{false};
bool s_storageStartPending = false;
bool s_storageStopRequested = false;
void resetLateStats_() {}
void sampleTaskFn_(void*) {}
void vTaskDelay(int) {}
#define xTaskCreatePinnedToCore(...) do {} while (0)
void LoggingManager::refreshConfigurationStatus() {
""")
        fixture = fixture.replace(definition(fixture, 'int main()'), r"""
int main() {
  reset(); add(SensorType::BMI270ImuI2C,"a",1,104);
  check(LoggingManager::requestStart() == LoggingManager::StartResult::Pending);
  check(s_starting && !s_running && !has("acquire"));
  storageWorker.step(100); LoggingManager::loop();
  check(s_running && has("acquire") && CanMasterManager::fenced);
  LoggingManager::stop(LoggingManager::StopReason::UserRequest, "operator");
  check(!s_running && s_stopping && has("sensor_stop") && !has("wifi_resume"));
  LoggingManager::loop(); check(s_stopping && !has("close"));
  storageWorker.step(200); LoggingManager::loop();
  check(!s_stopping && has("close") && has("wifi_resume") && !CanMasterManager::fenced);
  reset(); add(SensorType::BMI270ImuI2C,"a",1,104);
  check(LoggingManager::requestStart() == LoggingManager::StartResult::Pending);
  LoggingManager::stop(LoggingManager::StopReason::UserRequest,"cancel");
  check(s_stopping && !has("acquire"));
  storageWorker.step(300); LoggingManager::loop();
  check(!s_stopping && !has("file") && has("wifi_resume"));
  reset(); add(SensorType::BMI270ImuI2C,"a",1,104); openOk = false;
  check(LoggingManager::requestStart() == LoggingManager::StartResult::Pending);
  storageWorker.step(400); LoggingManager::loop(); LoggingManager::loop();
  check(!s_running && !s_starting && !s_stopping && has("sensor_stop") && has("wifi_resume"));
  // Health failure never opens a file and still releases initialized sensors.
  reset(); add(SensorType::BMI270ImuI2C,"a",1,104);
  check(LoggingManager::requestStart() == LoggingManager::StartResult::Pending);
  storageOk = false; storageWorker.step(500);
  LoggingManager::loop(); LoggingManager::loop();
  check(!s_starting && !s_stopping && !has("file") && has("sensor_stop"));
  // A blocked open can be cancelled without racing its handle or starting acquisition.
  reset(); add(SensorType::BMI270ImuI2C,"a",1,104);
  check(LoggingManager::requestStart() == LoggingManager::StartResult::Pending);
  blockedOperation = 2; blocked = true; entered = false;
  std::thread opening([] { storageWorker.step(600); });
  while (!entered.load()) std::this_thread::yield();
  storageWorker.poll(5600);
  LoggingManager::stop(LoggingManager::StopReason::StorageUnresponsive,"storage_timeout");
  check(s_stopping && !s_running && !has("acquire") && !has("close"));
  check(LoggingManager::requestStart() == LoggingManager::StartResult::Failed);
  blocked = false; opening.join(); storageWorker.step(5700); LoggingManager::loop();
  check(!s_stopping && !has("acquire") && has("failed_close") && has("wifi_resume"));
  // A new operator start performs health recovery and retains final sensor rows
  // until the worker has made space; bounded control calls do not drain SD.
  reset(); add(SensorType::BMI270ImuI2C,"a",1,104); blockedOperation = 0;
  check(LoggingManager::requestStart() == LoggingManager::StartResult::Pending);
  storageWorker.step(5800); LoggingManager::loop(); check(s_running);
  finalRows = 3; queueRoom = false;
  LoggingManager::stop(LoggingManager::StopReason::UserRequest,"operator");
  LoggingManager::loop(); check(s_stopping && finalRows == 3 && !has("tail_row"));
  queueRoom = true; LoggingManager::loop(); check(finalRows == 0 && has("tail_row"));
  // Close stalls retain membership/configuration fences and block recovery.
  blockedOperation = 4; blocked = true; entered = false;
  std::thread closing([] { storageWorker.step(5900); });
  while (!entered.load()) std::this_thread::yield();
  LoggingManager::loop(); check(s_stopping && !has("wifi_resume") && CanMasterManager::fenced);
  storageWorker.poll(10900); LoggingManager::loop(); check(s_stopping);
  blocked = false; closing.join(); LoggingManager::loop();
  check(!s_stopping && has("wifi_resume") && !CanMasterManager::fenced);
  // A returned sink failure shuts down acquisition and preserves a failed file.
  reset(); add(SensorType::BMI270ImuI2C,"a",1,104); blockedOperation = 0;
  check(LoggingManager::requestStart() == LoggingManager::StartResult::Pending);
  storageWorker.step(11000); LoggingManager::loop(); check(s_running);
  serviceFails = true; storageWorker.step(11100);
  check(StorageManager_storageFault());
  LoggingManager::stop(LoggingManager::StopReason::StorageFailure,"storage_failure");
  check(!s_running && has("sensor_stop") && !has("wifi_resume"));
  LoggingManager::loop(); storageWorker.step(11200); LoggingManager::loop();
  check(!s_stopping && has("failed_close") && has("wifi_resume"));
  printf("Async storage/controller: %d checks passed\n",checks);
}
""")
    with tempfile.TemporaryDirectory(prefix="bodaqs-log-start-") as temp:
        cpp, exe = Path(temp) / "runtime.cpp", Path(temp) / "runtime.exe"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run([args.compiler, "-std=gnu++2a", "-Wall", "-Wextra", "-Wno-unused-variable",
                        "-pthread", "-I", str(root / "test/stubs"), "-I", str(root / "src"),
                        str(cpp), str(root / "src/SensorAssignment.cpp"),
                        str(root / "src/SensorParams.cpp"),
                        str(root / "src/SensorDiagnostics.cpp"),
                        str(root / "src/SensorInventory.cpp"), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
