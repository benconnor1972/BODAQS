"""Exercise the integrated production recording path without devices."""
from __future__ import annotations

import argparse
import os
import struct
from pathlib import Path
import subprocess
import tempfile

from runtime_test_helpers import definition
from test_remote_imu_lifecycle_runtime import fixture_source
from verify_integrated_imu_recording import verify


def saturation_wire(original, output):
    """Known 500-row source; release one-sample packets as a deliberate burst."""
    frames = [(int(i), bytes.fromhex(h)) for i, _, h in (line.split() for line in original.read_text().splitlines())]
    boundary = frames[0][1]
    model = next(p for i, p in frames if i == 144 and p[1] == 0x24)
    anchor = next(p for i, p in frames if i == 144 and p[1] == 0x22)
    generated = [(144, boundary), (144, model), (144, anchor)]
    for seq in range(500):
        generated.append((256, struct.pack("<HBB", seq, 1, 0x41) + bytes.fromhex("0080ff7fffff0080ff7fffff")))
    output.write_text("".join(f"{i} {len(p)} {p.hex()}\n" for i, p in generated), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--first-recording", action="store_true")
    parser.add_argument("--sample-units", action="store_true")
    parser.add_argument("--flow-diagnostics", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    firmware = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="bodaqs-integrated-") as temporary:
        temporary = Path(temporary)
        output = args.output_dir.resolve() if args.output_dir else temporary / "results"
        output.mkdir(parents=True, exist_ok=True)
        producer = temporary / "node.exe"
        common = firmware / "can-fd/common/protocol"
        node = firmware / "can-fd/node"
        subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
            "-I", str(node / "test"), "-I", str(node / "src"), "-I", str(common),
            str(node / "test/test_acquisition.c"),
            *[str(node / "src" / name) for name in ("imu_spi.c", "imu_capture.c", "imu_acquisition.c")],
            str(common / "bodaqs_imu_disabled.c"), str(common / "bodaqs_control.c"), "-o", str(producer)], check=True)
        wire = output / "node-recovery-can.txt"
        subprocess.run([str(producer), *([] if args.first_recording else ["6"])], env=dict(os.environ, BODAQS_NODE_FIXTURE_OUT=str(wire)), check=True)
        source = fixture_source(firmware)
        source = source.replace('namespace LoggingManager { bool isRunning() { return recording; } bool configurationLocked() { return recording || starting; } }', '#include "LoggingManager.h"')
        # Lose one *accepted-object* RAM ACK at the SPI boundary. The master
        # retains the immutable head and the production transport must dedupe it.
        source = source.replace('namespace SharedSpiBus {', 'static bool dropDataAck=true; static unsigned droppedDataAcks=0; static FILE* controlLedger=nullptr; static BodaqsControlRecord firstStarts[4]={};\nnamespace SharedSpiBus {')
        source = source.replace('assert(dispatchControl(address,request,reply));', r'''
  if(request.opcode==0x24 && !firstStarts[address].opcode) firstStarts[address]=request;
  if(controlLedger) {
    const bool optional=(request.opcode==0x28 && (master.acquisition_started&(1u<<address))) ||
      ((request.opcode==7 || request.opcode==8) && request.operation==master.diagnostic_operation[address] && request.session==master.diagnostic_session[address]);
    std::fprintf(controlLedger,"%u\t%u\t%u\t%u\t%u\n",clockMs,address,request.opcode,request.operation,unsigned(optional));
  }
  assert(dispatchControl(address,request,reply));''')
        source = source.replace('const auto slotResult=bodaqs_master_service_process_transfer(&master,tx,length,clockMs,next);', r'''
 BodaqsMeasurementSlot outgoing={};uint8_t replacement[BODAQS_MEASUREMENT_BYTES];const uint8_t* delivered=tx;
 if(length==BODAQS_MEASUREMENT_BYTES && dropDataAck && bodaqs_measurement_decode(tx,length,&outgoing) && (outgoing.kind==5 || outgoing.kind==14) && outgoing.body[0]==1) {
   dropDataAck=false;++droppedDataAcks;outgoing={};outgoing.node=255;outgoing.context=master.measurement.mode.context;
   assert(bodaqs_measurement_encode(&outgoing,replacement,BODAQS_MEASUREMENT_BYTES));delivered=replacement;
 }
 const auto slotResult=bodaqs_master_service_process_transfer(&master,delivered,length,clockMs,next);''')
        support = (firmware / "test/integrated_imu_recording_fixture.cpp").read_text(encoding="utf-8")
        logging = (firmware / "src/LoggingManager.cpp").read_text(encoding="utf-8")
        functions = ("bool LoggingManager::isStarting(", "void LoggingManager::cancelStart(",
                     "bool LoggingManager::configurationLocked(", "LoggingManager::StartResult LoggingManager::requestStart(",
                     "void LoggingManager::loop(", "bool LoggingManager::start(", "void LoggingManager::completeStorageStart(",
                     "void LoggingManager::stop(", "void LoggingManager::finishStorageStop(")
        support = support.replace("// PRODUCTION_LOGGING", "\n".join(definition(logging, f) for f in functions))
        cpp = temporary / "integrated.cpp"
        cpp.write_text(source + support, encoding="utf-8")
        exe = temporary / "integrated.exe"
        sources = [*common.glob("bodaqs_control*.c"), common / "bodaqs_imu_disabled.c", common / "bodaqs_master_service.c", common / "bodaqs_master_protocol.c"]
        sources += [firmware / "src" / name for name in ("CanMasterProtocol.cpp", "SensorAssignment.cpp", "SensorParams.cpp", "Lsm6dso32xConfig.cpp", "RemoteImuStream.cpp", "BdqV2Catalog.cpp", "BdqV2Writer.cpp", "ImuAdmission.cpp")]
        subprocess.run([args.compiler, "-std=c++17", *(["-DBODAQS_SPI_MEASUREMENT_V3=1"] if args.sample_units else []), *(["-DBODAQS_SINGLE_NODE_IMU_SMOKE=1", "-DBODAQS_SPI_MEASUREMENT_V2=1"] if args.first_recording else []), *(["-DBODAQS_IMU_FLOW_DIAGNOSTICS=1"] if args.flow_diagnostics else []), "-pthread", "-DBODAQS_QUEUE_ALLOCATION_TEST", "-ffunction-sections", "-Wl,--gc-sections", "-Wall", "-Wextra", "-Werror", "-Wno-class-memaccess", "-Wno-unused-function", "-Wno-unused-variable", "-I", str(firmware/"test/stubs"), "-I", str(firmware/"src"), "-I", str(common), "-I", str(firmware/"can-fd/common/test"), str(cpp), *map(str, sources), "-o", str(exe)], check=True)
        saturated = output / "saturation-can.txt"
        saturation_wire(wire, saturated)
        for scenario in (("good", "short", "cancel-open", "cancel-prepare") if args.first_recording else ("good", "stall", "short", "cancel-open", "cancel-prepare")):
            subprocess.run([str(exe), str(saturated if scenario == "stall" else wire), str(output / f"{scenario}.bdq"), scenario], check=True, timeout=120)
        if args.first_recording:
            import sys,json
            sys.path.insert(0,str(firmware.parent / "analysis"))
            from bodaqs_analysis.can_imu_packets import read_can_imu_packets
            from bodaqs_analysis.first_imu_recording import assess_first_imu_recording
            decoded=read_can_imu_packets(output / "good.bdq", "can0_imu6")
            assert [r["sequence"] for r in decoded["readings"]]==list(range(65))
            assert all([r[k] for k in ("ax","ay","az","gx","gy","gz")]==[-32768,32767,-1,-32768,32767,-1] for r in decoded["readings"])
            assert not decoded["gaps"] and not decoded["ambiguous_packets"]
            if args.sample_units:
                print("Integrated v3 logger custody/control/recording and independent decode: PASS")
                return
            report,_=assess_first_imu_recording(output / "good.bdq")
            assert report["final_sample_raw_observation_present"]
            # The fixture's minimal footer is deliberately not promoted to the
            # target's full STOP/drain completion certificate.
            assert report["file_outcome"]=="incomplete_or_unresolved"
            (output / "compact_decode.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
            print("Restricted v2 real node -> coordinator/RAM -> storage owner/BDQ -> independent axes/raw decode: PASS")
        else:
            verify(output)


if __name__ == "__main__":
    main()

