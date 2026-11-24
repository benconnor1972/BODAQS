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
    parser.add_argument("--production-readiness", action="store_true",
                        help="exercise production admission with asynchronous storage")
    args = parser.parse_args()
    if args.production_readiness:
        args.async_storage = True
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
    fixture = fixture.replace("// PRODUCTION_LIFECYCLE", definition(logging, "  bool phaseIs_(") + "\n" + definition(logging, "  unsigned stopPriority_("))
    fixture = fixture.replace("// PRODUCTION_START", "\n".join(
        definition(logging, sig) for sig in (
            "bool retireLocalAcquisition_() {", "void LoggingManager::refreshConfigurationStatus(",
            "LoggingConfigIssue LoggingManager::configurationIssue(",
            "const char* LoggingManager::configurationDetail(", "bool LoggingManager::isStarting(",
            "void LoggingManager::cancelStart(", "LoggingManager::LifecycleState LoggingManager::lifecycleState(", "const char* LoggingManager::lifecycleStateName(", "bool LoggingManager::configurationLocked(", "LoggingManager::StartResult LoggingManager::requestStart(",
            "void LoggingManager::loop(", "void LoggingManager::stop(", "void LoggingManager::completeStorageStart(", "void LoggingManager::finishStorageStop(", "bool LoggingManager::start(")))
    fixture = fixture.replace("// PRODUCTION_FORMAT", "namespace LoggingManager { bool configurationLocked(); }\n// PRODUCTION_FORMAT")
    fixture = fixture.replace("// PRODUCTION_FORMAT", definition(config, "bool ConfigManager::setLogFormat("))
    fixture = fixture.replace("// PRODUCTION_TOGGLE", definition(buttons, "void ButtonActions::onToggleLogging(").replace("void ButtonActions::onToggleLogging(", "void onToggleLogging("))
    fixture = fixture.replace("// PRODUCTION_BUTTON", definition(buttons, "  void handleButtonBinding_("))
    fixture = fixture.replace("// PRODUCTION_NOTICE", "namespace HtmlUtil {\n" +
        definition(html, "  String htmlEscape(") + "\n}\n" + definition(routes, "static String productionMigrationHtml_(") + "\n" + definition(routes, "static String configurationNotice_("))
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
struct FixtureAllocation {size_t primaryQueueBytes=0,workspaceBytes=0,outputBufferBytes=0,catalogPeakBytes=0,primaryColumnsPeakBytes=0,metadataPayloadBytes=0,staticStateBytes=0,storageTaskStackBytes=0;};
FixtureAllocation StorageManager_recordingAllocation() {return {};}
bool StorageManager_recordingIoPending() { return storageWorker.pending(); }
bool StorageManager_recordingReady() { return storageWorker.recording(); }
bool StorageManager_storageFault() { return storageWorker.fault() != RecordingStorageWorker::Fault::None; }
bool StorageManager_canAcceptSample() { return queueRoom; }
bool StorageManager_storageUnresponsive() { return storageWorker.fault() == RecordingStorageWorker::Fault::Unresponsive; }
""")
        fixture = fixture.replace('void StorageManager_stopLog() { events.push_back("close"); }',
                                  'void StorageManager_stopLog() { storageWorker.requestStop(); }')
        fixture = fixture.replace('extern RecordingLifecycle s_lifecycle;', 'size_t finalRows = 0;\nextern RecordingLifecycle s_lifecycle;')
        fixture = fixture.replace('size_t pendingLoggingRows() { return 0; }',
                                  'size_t pendingLoggingRows() { return finalRows; }')
        fixture = fixture.replace('bool sampleOnce_(bool) { return false; }',
                                  'bool sampleOnce_(bool) { if (!finalRows) return false; --finalRows; events.push_back("tail_row"); return true; }')
        fixture = fixture.replace('bool retireLocalAcquisition_() {', r"""
#define ESP32 1
void* s_sampleTask = reinterpret_cast<void*>(1);
std::atomic<bool> s_sampleInProgress{false};
bool s_storageStartPending = false;
bool s_storageStopRequested = false;
void resetLateStats_() {}
void sampleTaskFn_(void*) {}
void vTaskDelay(int) {}
#define xTaskCreatePinnedToCore(...) do {} while (0)
bool retireLocalAcquisition_() {
""")
        fixture = fixture.replace(definition(fixture, 'int main()'), r"""
int main() {
  reset(); add(SensorType::BMI270ImuI2C,"a",1,104);
  check(LoggingManager::requestStart() == LoggingManager::StartResult::Pending);
  check(s_starting && !s_running && !has("acquire"));
  storageWorker.step(100); LoggingManager::loop();
  check(s_running && has("acquire") && CanMasterManager::fenced);
  LoggingManager::stop(LoggingManager::StopReason::UserRequest, "operator");
  check(!s_running && s_stopping && !has("sensor_stop") && !has("wifi_resume"));
  LoggingManager::loop(); check(s_stopping && !has("close"));
  storageWorker.step(200); LoggingManager::loop();
  check(!s_stopping && has("close") && has("wifi_resume") && !CanMasterManager::fenced);
  reset(); add(SensorType::BMI270ImuI2C,"a",1,104);
  check(LoggingManager::requestStart() == LoggingManager::StartResult::Pending);
  LoggingManager::stop(LoggingManager::StopReason::UserRequest,"cancel");
  check(s_stopping && !has("acquire"));
  LoggingManager::loop(); storageWorker.step(300); LoggingManager::loop();
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
  LoggingManager::loop();
  blocked = false; opening.join(); storageWorker.step(5700); LoggingManager::loop();
  check(!s_stopping && !has("acquire") && has("failed_close") && has("wifi_resume"));
  // A new operator start performs health recovery and retains final sensor rows
  // until the worker has made space; bounded control calls do not drain SD.
  reset(); add(SensorType::BMI270ImuI2C,"a",1,104); blockedOperation = 0;
  check(LoggingManager::requestStart() == LoggingManager::StartResult::Pending);
  storageWorker.step(5800); LoggingManager::loop(); check(s_running);
  finalRows = 3; queueRoom = false;
  I2CBusScheduler::held=true;I2CBusScheduler::stopRequested=false;
  LoggingManager::stop(LoggingManager::StopReason::UserRequest,"operator");
  LoggingManager::loop();
  check(I2CBusScheduler::stopRequested && !has("sensor_stop") && !has("finalize_locked"));
  check(s_stopping && finalRows == 3 && !has("tail_row"));
  I2CBusScheduler::held=false;
  LoggingManager::loop(); check(has("sensor_stop"));
  queueRoom = true; LoggingManager::loop(); check(finalRows == 0 && has("tail_row"));
  // Close stalls retain membership/configuration fences and block recovery.
  blockedOperation = 4; blocked = true; entered = false;
  std::thread closing([] { storageWorker.step(5900); });
  while (!entered.load()) std::this_thread::yield();
  LoggingManager::loop(); check(s_stopping && !has("wifi_resume") && CanMasterManager::fenced);
  storageWorker.poll(10900); LoggingManager::loop(); check(s_stopping);
  blocked = false; closing.join(); LoggingManager::loop();
  check(!s_stopping && has("wifi_resume") && !CanMasterManager::fenced);
  // A source fault must outrank a simultaneous normal sleep request.
  reset(); add(SensorType::BMI270ImuI2C,"a",1,104); blockedOperation=0;
  check(LoggingManager::requestStart() == LoggingManager::StartResult::Pending);
  storageWorker.step(11010); LoggingManager::loop();
  std::thread powerFault([] {
    lifecycleOwner=false;
    LoggingManager::stop(LoggingManager::StopReason::SleepRequest,"sleep");
    LoggingManager::stop(LoggingManager::StopReason::AnalogRailFault,"rail");
  });
  powerFault.join();LoggingManager::loop();
  check(s_stopContext.reason == LoggingManager::StopReason::AnalogRailFault);
  LoggingManager::stop(LoggingManager::StopReason::UserRequest,"repeat");
  LoggingManager::loop();storageWorker.step(11011);LoggingManager::loop();
  check(LoggingManager::lifecycleState() == LifecycleState::Failed);
  // A returned sink failure shuts down acquisition and preserves a failed file.
  reset(); add(SensorType::BMI270ImuI2C,"a",1,104); blockedOperation = 0;
  check(LoggingManager::requestStart() == LoggingManager::StartResult::Pending);
  storageWorker.step(11000); LoggingManager::loop(); check(s_running);
  serviceFails = true; storageWorker.step(11100);
  check(StorageManager_storageFault());
  LoggingManager::stop(LoggingManager::StopReason::StorageFailure,"storage_failure");
  check(!s_running && !has("sensor_stop") && !has("wifi_resume"));
  LoggingManager::loop(); storageWorker.step(11200); LoggingManager::loop();
  check(!s_stopping && has("failed_close") && has("wifi_resume"));
  // A closed file need not wait forever for uncertain administrative cleanup.
  // Native diagnostics finalize once, while remote ownership remains fenced.
  reset(); add(SensorType::BMI270ImuI2C,"a",1,104); blockedOperation=0;
  check(LoggingManager::requestStart() == LoggingManager::StartResult::Pending);
  storageWorker.step(11500); LoggingManager::loop();
  RemoteImuRecording::remoteStopped=false;CanMasterManager::handoffActive=true;
  LoggingManager::stop(LoggingManager::StopReason::UserRequest,"operator");
  LoggingManager::loop();storageWorker.step(11501);LoggingManager::loop();
  check(LoggingManager::lifecycleState()==LifecycleState::Uncertain && has("finalize_locked"));
  const auto finalizations=std::count(events.begin(),events.end(),"finalize_locked");
  LoggingManager::loop();check(LoggingManager::configurationLocked());
  check(std::count(events.begin(),events.end(),"finalize_locked")==finalizations);
  RemoteImuRecording::remoteStopped=true;CanMasterManager::handoffActive=false;
  LoggingManager::loop();check(!LoggingManager::configurationLocked());
  check(std::count(events.begin(),events.end(),"finalize_locked")==finalizations);
  // Shared clock/identity corruption requests STOP while independent source
  // faults remain source-local in the real remote lifecycle fixture.
  reset(); add(SensorType::BMI270ImuI2C,"a",1,104); blockedOperation=0;
  check(LoggingManager::requestStart() == LoggingManager::StartResult::Pending);
  storageWorker.step(12000); LoggingManager::loop(); check(s_running);
  RemoteImuRecording::sharedFault=true; LoggingManager::loop();
  check(s_stopping && !s_running);
  check(s_stopContext.reason == LoggingManager::StopReason::Unspecified);
  RemoteImuRecording::sharedFault=false;LoggingManager::loop();
  storageWorker.step(12001); LoggingManager::loop();
  check(!LoggingManager::configurationLocked());
  printf("Async storage/controller: %d checks passed\n",checks);
}
""")
    if args.async_storage:
        fixture = fixture.replace('  // A returned sink failure shuts down acquisition', r"""
  // Concurrent producer faults are requests, never synchronous self-retirement.
  reset(); add(SensorType::BMI270ImuI2C,"a",1,104); blockedOperation=0;
  check(LoggingManager::requestStart() == LoggingManager::StartResult::Pending);
  storageWorker.step(11000); LoggingManager::loop(); check(s_running);
  s_sampleInProgress = true;
  std::thread producer([] {
    lifecycleOwner = false;
    LoggingManager::stop(LoggingManager::StopReason::StartFailure,"temporary_producer_context");
    LoggingManager::stop(LoggingManager::StopReason::StorageFailure,"second_fault");
  });
  producer.join();
  check(s_running && !has("sensor_stop") && LoggingManager::configurationLocked());
  LoggingManager::loop();
  check(!s_running && s_stopping && !has("sensor_stop"));
  check(LoggingManager::requestStart() == LoggingManager::StartResult::Failed);
  LoggingManager::stop(LoggingManager::StopReason::UserRequest,"repeat");
  s_sampleInProgress = false;
  LoggingManager::loop();
  check(!s_running && s_stopping && s_stopContext.reason == LoggingManager::StopReason::StorageFailure);
  LoggingManager::loop(); storageWorker.step(11001); LoggingManager::loop();
  check(!s_stopping && !LoggingManager::configurationLocked());
  // A returned sink failure shuts down acquisition""")
    if args.production_readiness:
        import re
        additions = (root / "test/logging_production_readiness_fixture.cpp").read_text(encoding="utf-8")
        adapters, production_main = additions.split("// PRODUCTION_MAIN", 1)
        actual = (root / "src/RecordingReadiness.cpp").read_text(encoding="utf-8")
        actual = re.sub(r'^#include "[^\n]+$', '', actual, flags=re.M)
        adapters = adapters.replace("// ACTUAL_READINESS", actual)
        fixture = fixture.replace('#include "RecordingLifecycle.h"', '#include "RecordingLifecycle.h"\n#include "RecordingReadiness.h"')
        fixture = fixture.replace('  uint8_t sensorN = 0;', '  uint8_t sensorN = 0;\n  bool recordingBestEffort = false;')
        fixture = fixture.replace('  bool muted() const { return mute; }', '  bool muted() const { return mute; }\n  bool observeLoggingReadiness(const LoggerConfig&, uint16_t, char*, size_t) const { return !stale; }')
        begin = fixture.index('namespace RemoteImuRecording {')
        end = fixture.index('namespace CanMasterManager {', begin)
        remote, adapters = adapters.split('// REMOTE_END', 1)
        fixture = fixture[:begin] + remote + fixture[end:]
        fixture = fixture.replace('  bool handoffReady = true, fenced = false;', '  uint8_t availableNodes = 0;\n  bool configurationReconciled(uint8_t node) { return availableNodes & (1u << node); }\n  bool acquisitionLinkCompatible(uint8_t node) { return configurationReconciled(node); }\n  bool handoffReady = true, fenced = false;')
        fixture = fixture.replace('  void onLoggingStart() {}', '  void onLoggingStart() {}\n  bool activateRecordingPlan() { events.push_back("activate"); return true; }')
        fixture = fixture.replace('  uint16_t synchronousMaxSampleRateHz() { return 0; }',
            '  uint16_t syncLimit = 0;\n  uint16_t synchronousMaxSampleRateHz() { return syncLimit; }')
        fixture = fixture.replace('  uint16_t configureFromConfig(const LoggerConfig&, uint16_t rate) { return rate; }',
            '  uint16_t effectiveRate = 0;\n  uint16_t configureFromConfig(const LoggerConfig&, uint16_t rate) { return effectiveRate?effectiveRate:rate; }')
        fixture = fixture.replace('  bool onLoggingStart(char*, size_t) { events.push_back("sensors"); return sensorsStartOk; }', '  bool onLoggingStart(char*, size_t) { events.push_back("sensors"); return sensorsStartOk; }\n  uint32_t localAllocationMask = ~uint32_t{0};\n  uint32_t sessionParticipantMask() {\n    uint32_t mask=0;\n    for(uint8_t i=0;i<g_cfg.sensorCount();++i) if(s_list[i] && !s_list[i]->muted()) mask |= uint32_t{1}<<i;\n    return mask & localAllocationMask;\n  }\n  Sensor* getConfiguredSensor(uint8_t i) { return i<g_cfg.sensorCount()?s_list[i]:nullptr; }\n  bool getMuted(uint8_t i,bool& muted) { if(!getConfiguredSensor(i)) return false; muted=s_list[i]->muted(); return true; }')
        # Insert the real adapter before extracted lifecycle methods, after all mocks.
        anchor = definition(logging, "  bool phaseIs_(")
        fixture = fixture.replace(anchor, adapters + "\n" + definition(logging, "static bool freezeProductionMembership_(") + "\n" + anchor, 1)
        fixture = fixture.replace(definition(fixture, 'int main()'), production_main)
        fixture = fixture.replace('#define check(condition) checkAt((condition), __LINE__)',
            '#define check(condition) do { const bool ok=bool(condition); if(!ok) fprintf(stderr,"%s\\n",#condition); checkAt(ok,__LINE__); } while(0)')
    for old, value in {
        "s_running": "phaseIs_(LifecycleState::Recording)",
        "s_starting": "phaseIs_(LifecycleState::Preparing)",
        "s_stopping": "(phaseIs_(LifecycleState::Stopping) || phaseIs_(LifecycleState::Finalizing))",
    }.items():
        import re
        fixture = re.sub(r"\b" + old + r"\b", value, fixture)
    with tempfile.TemporaryDirectory(prefix="bodaqs-log-start-") as temp:
        cpp, exe = Path(temp) / "runtime.cpp", Path(temp) / "runtime.exe"
        cpp.write_text(fixture, encoding="utf-8")
        for candidate in ((0, 1) if args.production_readiness else (0,)):
            subprocess.run([args.compiler, "-std=gnu++2a",
                        f"-DBODAQS_UNQUALIFIED_INTEGRATION_CANDIDATE={candidate}",
                        f"-DBODAQS_PRODUCTION_RECORDING={int(args.production_readiness)}", "-Wall", "-Wextra", "-Wno-unused-variable",
                        "-pthread", "-I", str(root / "test/stubs"), "-I", str(root / "src"),
                        str(cpp), str(root / "src/SensorAssignment.cpp"),
                        str(root / "src/SensorParams.cpp"),
                        str(root / "src/SensorDiagnostics.cpp"),
                        str(root / "src/SensorInventory.cpp"), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
