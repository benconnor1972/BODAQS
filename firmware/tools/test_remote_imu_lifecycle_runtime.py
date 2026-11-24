"""Run the production remote recording coordinator over real control/master logic."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def fixture_source(root,pipeline_trace=False):
    """Real control/master/coordinator composition shared with acceptance."""
    fixture = (root / "test/measurement_runtime_fixture.cpp").read_text()
    fixture = '#include "SpiTransferTiming.h"\n'+fixture
    fixture = fixture.replace('SpiTransactionContext* context=nullptr) {',
        'SpiTransactionContext* context=nullptr,SpiTransferTiming* phaseTiming=nullptr) {\n if(phaseTiming)*phaseTiming={}; // host has no physical SPI/RTOS timing')
    fixture = fixture[:fixture.index("int main() {")]
    if pipeline_trace:
        fixture += '\nconstexpr int LOG_WARN=2;static void Log_taggedPrintln(int,const char*,const char*) {}\n'
        fixture=fixture.replace("namespace SharedSpiBus {","static uint32_t pipelineBusSequence=0;\nnamespace SharedSpiBus {",1)
        fixture=fixture.replace(" if(!spiAvailable) return false;",
            " if(!spiAvailable) return false;\n ++pipelineBusSequence; if(context) {context->deviceSequence=pipelineBusSequence;context->deviceSequenceValid=pipelineBusSequence!=UINT32_MAX;}",1)
    fixture = fixture.replace("namespace SharedSpiBus {", "static bool dispatchControl(uint8_t,const BodaqsControlRecord&,BodaqsControlRecord&);\nstatic bool holdControl(uint8_t,const BodaqsControlRecord&);\nnamespace SharedSpiBus {")
    fixture = fixture.replace("assert(bodaqs_control_node_process(&node.view,&request,&reply));", "if(holdControl(address,request)) return true;\n  assert(dispatchControl(address,request,reply));")
    acquisition = (root / "test/acquisition_control_runtime_fixture.cpp").read_text()
    fixture = fixture.replace('static void advance(unsigned ms)', 'static void tickFixtureApplications();\nstatic void advance(unsigned ms)')
    fixture = fixture.replace('bodaqs_control_apply_tick(&node.apply,clockMs);','tickFixtureApplications();')
    fixture += acquisition[:acquisition.index("int main(")]
    fixture += '\nstatic void tickFixtureApplications() {for(unsigned n=0;n<4;++n) {peerFixture(n).now=clockMs; bodaqs_control_apply_tick(&peerFixture(n).apply,clockMs);} }\n' 
    manager = (root / "src/CanMasterManager.cpp").read_text()
    headers = ("Arduino.h", "SPI.h", "esp_system.h", "DebugLog.h", "LoggingManager.h", "SensorManager.h", "SharedSpiBus.h")
    manager = "\n".join(line for line in manager.splitlines() if not any(line in ('#include <'+h+'>', '#include "'+h+'"') for h in headers))
    fixture = fixture.replace("// PRODUCTION_MANAGER", manager)
    fixture += '\nint64_t esp_timer_get_time() { return int64_t(clockMs)*1000; }\nnamespace board { const BoardProfile* gBoard=&profile; }\n'
    fixture += (root / "src/AcquisitionControl.cpp").read_text().replace('#include <Arduino.h>', '')
    coordinator = (root / "src/RemoteImuRecording.cpp").read_text()
    for header in ('#include <Arduino.h>', '#include <esp_timer.h>', '#include <esp_system.h>', '#include "SensorManager.h"', '#include "DebugLog.h"'):
        coordinator = coordinator.replace(header, '')
    fixture += '\nstatic uint8_t fixtureAdcChannels=0;static uint16_t fixtureAdcSps=100;static bool fixtureConcentrated=false;\nnamespace AnalogInputManager { uint8_t activeChannelCount(uint8_t a) {return fixtureConcentrated?(a?0:2):fixtureAdcChannels;} uint16_t configuredDataRateSps(uint8_t) {return fixtureConcentrated?2000:fixtureAdcSps;} }\n'
    fixture = fixture.replace('static SensorSpec saved;', 'static SensorSpec saved; static unsigned fixtureSensorCount=1; static SensorSpec extra[7]; static ParamStore extraParams[7];')
    fixture = fixture.replace('return 1; }\nbool LoggerConfig::getSensorSpec', 'return fixtureSensorCount; }\nbool LoggerConfig::getSensorSpec')
    fixture = fixture.replace('if(i) return false; spec=saved;', 'if(i>=fixtureSensorCount) return false; spec=i?extra[i-1]:saved;')
    fixture = fixture.replace('identity.capabilities=15;', 'identity.capabilities=15 | BODAQS_CAN_LINK_CAP_ACQUISITION;')
    fixture += coordinator
    return fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--production-idle", action="store_true")
    parser.add_argument("--flow-diagnostics", action="store_true")
    parser.add_argument("--reply-capture",action="store_true")
    parser.add_argument("--cs-setup-us",type=int,default=0)
    parser.add_argument("--start-spacing-us", type=int, default=0,
                        help="Verify measurement pacing propagation; physical clock tested separately")
    parser.add_argument("--v2", action="store_true", help="Exercise coordinated 256-byte measurement profile")
    parser.add_argument("--smoke", action="store_true", help="Exercise opt-in unqualified single-node build without installing synthetic costs")
    parser.add_argument("--mixed", action="store_true", help="Exact 500 Hz two-ADC bench scope plus one compact IMU")
    parser.add_argument("--channel-rate",action="store_true")
    parser.add_argument("--scaling",action="store_true")
    parser.add_argument("--multi-node",action="store_true")
    parser.add_argument("--ack-sweep",action="store_true")
    parser.add_argument("--pipeline-trace",action="store_true")
    parser.add_argument("--idle-control-fetch",action="store_true")
    args = parser.parse_args()
    if args.ack_sweep: args.multi_node=True
    if args.multi_node: args.scaling=True;args.flow_diagnostics=True
    if args.scaling: args.channel_rate=True
    if args.channel_rate: args.mixed=True
    if args.mixed: args.smoke=True;args.v2=True
    if args.reply_capture:
        assert args.v2 or args.mixed
        args.flow_diagnostics=True
    root = Path(__file__).resolve().parents[1]
    fixture = fixture_source(root,pipeline_trace=args.pipeline_trace)
    if args.mixed:
        fixture=fixture.replace('bool getMuted(uint8_t,bool& value) { value=muted; return true; }',
            'bool getMuted(uint8_t i,bool& value) {SensorSpec s;if(!config.getSensorSpec(i,s)) return false;value=muted || s.mutedDefault;return true;}')
    if args.flow_diagnostics:
        fixture=fixture.replace('#include "RemoteImuRecording.h"', '''
static unsigned flowLogCalls=0;
static void captureFlowLog(const char* tag,const char*,...) {if(!std::strcmp(tag,"FLOW")) ++flowLogCalls;}
#undef LOGW_TAG
#define LOGW_TAG(tag,...) captureFlowLog(tag,__VA_ARGS__)
#include "RemoteImuRecording.h"''')
    if args.production_idle:
        # These idle reconciliation scenarios return before recording admission.
        # Make the boundary explicit: accidentally starting a recording fails.
        fixture += "\nnamespace RecordingReadiness { bool selected(uint8_t) {assert(false);return false;} const Observation& session() {assert(false);static Observation unused;return unused;} }\n"
    fixture += (root / "test/remote_imu_lifecycle_runtime_fixture.cpp").read_text()
    protocol = root / "can-fd/common/protocol"
    sources = [*protocol.glob("bodaqs_control*.c"), protocol / "bodaqs_imu_disabled.c", protocol / "bodaqs_master_service.c", protocol / "bodaqs_master_protocol.c"]
    sources += [root / "src" / name for name in ("CanMasterProtocol.cpp", "SensorAssignment.cpp", "SensorParams.cpp", "Lsm6dso32xConfig.cpp", "RemoteImuStream.cpp", "BdqV2Catalog.cpp", "ImuAdmission.cpp")]
    with tempfile.TemporaryDirectory(prefix="bodaqs-remote-lifecycle-") as temp:
        cpp, exe = Path(temp)/"fixture.cpp", Path(temp)/"fixture.exe"
        cpp.write_text(fixture)
        flags=["-DBODAQS_SINGLE_NODE_IMU_SMOKE=1"] if args.smoke else []
        if args.production_idle: flags.append("-DBODAQS_PRODUCTION_RECORDING=1")
        if args.mixed: flags.append("-DBODAQS_SINGLE_NODE_IMU_ADC_SMOKE=1")
        if args.channel_rate: flags.append("-DBODAQS_ADC_CHANNEL_RATE_BENCH=1")
        if args.scaling: flags.append("-DBODAQS_ADC_SCALING_BENCH=1")
        if args.multi_node: flags.append("-DBODAQS_MULTI_NODE_BENCH=1")
        if args.ack_sweep: flags.append("-DBODAQS_ACK_FETCH_FRAGMENT_SWEEP=1")
        if args.pipeline_trace: flags += ["-DBODAQS_PIPELINE_TRACE=1","-DBODAQS_IMU_FLOW_DIAGNOSTICS=1"]
        if args.idle_control_fetch: flags.append("-DBODAQS_RECLAIM_IDLE_CONTROL_FETCH=1")
        if args.v2:
            flags.append("-DBODAQS_SPI_MEASUREMENT_V2=1")
        if args.start_spacing_us:
            flags.append(f"-DBODAQS_MEASUREMENT_START_SPACING_US={args.start_spacing_us}")
        if args.flow_diagnostics:
            flags.append("-DBODAQS_IMU_FLOW_DIAGNOSTICS=1")
        if args.reply_capture: flags.append("-DBODAQS_MEASUREMENT_REPLY_CAPTURE=1")
        if args.cs_setup_us: flags.append(f"-DBODAQS_MEASUREMENT_CS_SETUP_US={args.cs_setup_us}")
        subprocess.run([args.compiler, "-std=c++17", *flags, "-DBODAQS_QUEUE_ALLOCATION_TEST", "-ffunction-sections", "-Wl,--gc-sections", "-Wall", "-Wextra", "-Werror", "-Wno-class-memaccess", "-Wno-unused-function", "-I", str(root/"test/stubs"), "-I", str(root/"src"), "-I", str(protocol), "-I", str(root/"can-fd/common/test"), str(cpp), *map(str, sources), "-o", str(exe)], check=True)
        if args.production_idle:
            subprocess.run([str(exe), "readiness"], check=True)
            subprocess.run([str(exe), "readiness-failing"], check=True)
            return
        subprocess.run([str(exe)], check=True)
        if args.multi_node:
            for case in ("multi-1-none","multi-2-none","multi-4-none","multi-2-200","multi-4-200","multi-4-500","multi-4-fault"):
                subprocess.run([str(exe),case],check=True)
        if args.channel_rate:
            for case in ("channel-rate-500","channel-rate-700","channel-rate-1000"):
                subprocess.run([str(exe),case],check=True)
        if args.scaling:
            for case in ("scaling-200","scaling-500","mixed-reject-scaling-rate","mixed-reject-scaling-duplicate","mixed-reject-scaling-map","mixed-reject-scaling-raw"):
                subprocess.run([str(exe),case],check=True)
        if args.flow_diagnostics:
            subprocess.run([str(exe), "flow-cancel-scope"], check=True)
        subprocess.run([str(exe), "shared-integrity"], check=True)
        subprocess.run([str(exe), "start-clock-boundary"], check=True)
        subprocess.run([str(exe), "lost-control-ack"], check=True)
        subprocess.run([str(exe), "rx-overrun"], check=True)
        subprocess.run([str(exe), "rx-overrun-odd"], check=True)
        subprocess.run([str(exe), "legacy-rx-overrun"], check=True)
        subprocess.run([str(exe), "delayed-cleanup-status"], check=True)
        subprocess.run([str(exe), "entry-timeout"], check=True)
        subprocess.run([str(exe), "entry-offline"], check=True)
        subprocess.run([str(exe), "entry-precheck"], check=True)
        subprocess.run([str(exe), "lost-stop-result"], check=True)
        subprocess.run([str(exe), "uncertain-stop"], check=True)
        for scenario in ("lost-exit-request", "lost-exit-stage", "lost-exit-confirm", "expired-exit-stage"):
            subprocess.run([str(exe), scenario], check=True)
        if args.smoke and args.v2:
            subprocess.run([str(exe), "tail-pressure"], check=True)
            subprocess.run([str(exe), "tail-pressure-deferred-status"], check=True)
        if args.smoke:
            for scenario in (("scope-other", "scope-adc") if args.multi_node else ("scope-two", "scope-other", "scope-adc")):
                subprocess.run([str(exe), scenario], check=True)
            if args.mixed:
                for scenario in ("mixed-control","mixed-reject-ain","mixed-reject-rate",
                                 "mixed-reject-channels","mixed-reject-duplicate","mixed-reject-transform"):
                    subprocess.run([str(exe),scenario],check=True)
            return
        subprocess.run([str(exe), "four"], check=True)
        for scenario in ("node-reboot", "master-reboot", "bus-off", "lease-expiry", "four-bus-off"):
            subprocess.run([str(exe), scenario], check=True)


if __name__ == "__main__":
    main()
