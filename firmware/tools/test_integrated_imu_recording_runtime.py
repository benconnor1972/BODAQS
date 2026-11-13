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


def saturation_wire(original, output,count=500):
    """Known 500-row source; release one-sample packets as a deliberate burst."""
    frames = [(int(i), bytes.fromhex(h)) for i, _, h in (line.split() for line in original.read_text().splitlines())]
    boundary = frames[0][1]
    model = next(p for i, p in frames if i == 144 and p[1] == 0x24)
    anchor = next(p for i, p in frames if i == 144 and p[1] == 0x22)
    generated = [(144, boundary), (144, model), (144, anchor)]
    for seq in range(count):
        generated.append((256, struct.pack("<HBB", seq, 1, 0x41) + bytes.fromhex("0080ff7fffff0080ff7fffff")))
    if count>500:
        stop=bytearray(next(p for i,p in frames if i==144 and p[1]==0x25 and p[14]==8))
        struct.pack_into('<I',stop,28,count-1)
        generated.append((144,bytes(stop)))
    output.write_text("".join(f"{i} {len(p)} {p.hex()}\n" for i, p in generated), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--first-recording", action="store_true")
    parser.add_argument("--sample-units", action="store_true")
    parser.add_argument("--two-node", action="store_true")
    parser.add_argument("--window", action="store_true")
    parser.add_argument("--idle-control-fetch", action="store_true")
    parser.add_argument("--flow-diagnostics", action="store_true")
    parser.add_argument("--pressure-diagnostics", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.window:
        args.first_recording=args.sample_units=args.two_node=True
    if args.pressure_diagnostics:
        if not args.window:
            parser.error('--pressure-diagnostics requires --window')
        args.flow_diagnostics=True
    if args.two_node and not (args.first_recording and args.sample_units):
        parser.error('--two-node requires --first-recording --sample-units')
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
        producer_env=dict(os.environ, BODAQS_NODE_FIXTURE_OUT=str(wire))
        if args.two_node: producer_env['BODAQS_NODE_FIXTURE_PARTIAL_STOP']='1'
        subprocess.run([str(producer), *([] if args.first_recording else ["6"])], env=producer_env, check=True)
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
        if args.window:
            # Lose data and the exact retirement response independently. Suppress
            # only one source's first unit until another unit has reached MISO;
            # the final BDQ must still contain each known reading exactly once.
            source=source.replace('namespace SharedSpiBus {', '''
static bool holdWindowUnit=true,windowSuccessorSeen=false,dropWindowProof=true;
static unsigned windowDataSuppressed=0,windowProofSuppressed=0,windowCorrupted=0,windowBackpressureAds=0;
namespace SharedSpiBus {''',1)
            source=source.replace('memcpy(rx,preloaded,length);', '''
 memcpy(rx,preloaded,length);
 if(length==BODAQS_MEASUREMENT_BYTES) {
   BodaqsMeasurementSlot observed={};
   if(bodaqs_measurement_decode(tx,length,&observed)) {
     const uint8_t* credit=observed.kind==15?observed.body:
       observed.kind==14 && observed.body[2]==1?observed.body+16:nullptr;
     if(credit && credit[4]==15 && credit[12]==15) ++windowBackpressureAds;
   }
   if(bodaqs_measurement_decode(rx,length,&observed)) {
     if(observed.kind==2 && observed.node==1 && observed.object==2 && !windowCorrupted) {
       ++windowCorrupted;observed.body[20]^=1;
       assert(bodaqs_measurement_encode(&observed,rx,length)); // valid physical CRC, bad origin CRC
     }
     if(observed.kind==2 && observed.node==0 && observed.object>1) windowSuccessorSeen=true;
     const bool data=holdWindowUnit && observed.kind==2 && observed.node==0 && observed.object==1;
     const bool proof=dropWindowProof && observed.retired && observed.retiredClass==1;
     if(data || proof) {
       if(data) ++windowDataSuppressed;
       if(proof) {dropWindowProof=false;++windowProofSuppressed;}
       observed={};observed.node=255;observed.context=master.measurement.mode.context;
       assert(bodaqs_measurement_encode(&observed,rx,length));
     }
   }
 }''',1)
        support = (firmware / "test/integrated_imu_recording_fixture.cpp").read_text(encoding="utf-8")
        if args.pressure_diagnostics:
            # Real coordinator/retirement barrier and production footer adapter.
            # Only filesystem I/O is simulated; the separate sink test checks
            # the target adapter's physical operation timestamps.
            storage_source=(firmware / 'src/StorageManager.cpp').read_text(encoding='utf-8')
            adapter=definition(storage_source,'static void appendRecordingPressure_(')
            support=support.replace('struct FileStorage final:', '#include <ArduinoJson.h>\n'+adapter+'\nstruct FileStorage final:')
            support=support.replace('gate(1);file=std::fopen', 'RecordingPressureDiagnostics::resetStorage();gate(1);file=std::fopen')
            support=support.replace('return std::fwrite(p,1,n,file)==n;', '''
   const bool written=std::fwrite(p,1,n,file)==n;
   RecordingPressureDiagnostics::storageOperation(3,clockMs*1000,0,n,0);
   return written;''')
            support=support.replace('const char summary[]=R"({"software_candidate":true,"physical_timing_bounds":"unknown","inter_node_alignment":"unknown"})";',
                'JsonDocument summaryDocument;appendRecordingPressure_(summaryDocument);\n'
                '   std::string summary;serializeJson(summaryDocument,summary);')
            support=support.replace('writer.end(summary,sizeof summary-1)', 'writer.end(summary.c_str(),summary.size())')
        logging = (firmware / "src/LoggingManager.cpp").read_text(encoding="utf-8")
        functions = ("bool LoggingManager::isStarting(", "void LoggingManager::cancelStart(",
                     "bool LoggingManager::configurationLocked(", "LoggingManager::StartResult LoggingManager::requestStart(",
                     "void LoggingManager::loop(", "bool LoggingManager::start(", "void LoggingManager::completeStorageStart(",
                     "void LoggingManager::stop(", "void LoggingManager::finishStorageStop(")
        support = support.replace("// PRODUCTION_LOGGING", "\n".join(definition(logging, f) for f in functions))
        if args.window:
            support=support.replace('assert(argc==4);storage.path=argv[2];setup();const std::string scenario=argv[3];',
                'assert(argc==4);storage.path=argv[2];setup();const std::string scenario=argv[3];\n'
                ' if(scenario=="lag") {delayStatusResponses=true;delayedResponseDepth=2;}')
            support=support.replace('feedWire(argv[1],0);','feedWire(argv[1],1);')
            support=support.replace('step(4200);assert(renewalSequence[0]>=before+3',
                'step(200);assert(windowBackpressureAds>0);assert(renewalSequence[0]>=before+1')
            support=support.replace('step(pacing);\n   assert(!RemoteImuRecording::failed());', '''
   if(id==0x100 && frameNumber<=6) {
     // Six arrivals before service create at least two immutable units.
     if(frameNumber==6) {
       step(8);assert(windowSuccessorSeen && windowDataSuppressed);
       holdWindowUnit=false;
     }
   } else step(pacing);
   assert(!RemoteImuRecording::failed());''')
            # frameNumber includes early evidence, so use a separate sample count.
            support=support.replace('unsigned id,length,frameNumber=0;', 'unsigned id,length,frameNumber=0,windowSamples=0;')
            support=support.replace('id==0x100 && frameNumber<=6', 'id==0x100 && ++windowSamples<=6')
            support=support.replace('if(frameNumber==6)', 'if(windowSamples==6)')
            support=support.replace('assert(droppedDataAcks==1);',
                'assert(droppedDataAcks==1 && windowProofSuppressed==1 && windowCorrupted==1 && windowSuccessorSeen);')
        cpp = temporary / "integrated.cpp"
        cpp.write_text(source + support, encoding="utf-8")
        exe = temporary / "integrated.exe"
        sources = [*common.glob("bodaqs_control*.c"), common / "bodaqs_imu_disabled.c", common / "bodaqs_master_service.c", common / "bodaqs_master_protocol.c"]
        if args.idle_control_fetch:
            source_flags=['-DBODAQS_RECLAIM_IDLE_CONTROL_FETCH=1']
        else:
            source_flags=[]
        if args.window:
            source_flags += ['-DBODAQS_SPI_MEASUREMENT_V4=1']
        if args.pressure_diagnostics:
            source_flags += ['-DBODAQS_RECORDING_PRESSURE_DIAGNOSTICS=1', '-I', str(firmware/'.pio/libdeps/bodaqs_s3_mini_n4r2/ArduinoJson/src')]
        sources += [firmware / "src" / name for name in ("CanMasterProtocol.cpp", "SensorAssignment.cpp", "SensorParams.cpp", "Lsm6dso32xConfig.cpp", "RemoteImuStream.cpp", "BdqV2Catalog.cpp", "BdqV2Writer.cpp", "ImuAdmission.cpp")]
        subprocess.run([args.compiler, "-std=c++17", *source_flags, *(["-DBODAQS_SPI_MEASUREMENT_V3=1"] if args.sample_units else []), *(["-DBODAQS_SINGLE_NODE_IMU_SMOKE=1", "-DBODAQS_SPI_MEASUREMENT_V2=1"] if args.first_recording else []), *(["-DBODAQS_V3_TWO_NODE_BENCH=1"] if args.two_node else []), *(["-DBODAQS_IMU_FLOW_DIAGNOSTICS=1"] if args.flow_diagnostics else []), "-pthread", "-DBODAQS_QUEUE_ALLOCATION_TEST", "-ffunction-sections", "-Wl,--gc-sections", "-Wall", "-Wextra", "-Werror", "-Wno-class-memaccess", "-Wno-unused-function", "-Wno-unused-variable", "-I", str(firmware/"test/stubs"), "-I", str(firmware/"src"), "-I", str(common), "-I", str(firmware/"can-fd/common/test"), str(cpp), *map(str, sources), "-o", str(exe)], check=True)
        saturated = output / "saturation-can.txt"
        saturation_wire(wire, saturated,1200 if args.window else 500)
        scenarios=("good", "short", "cancel-open", "cancel-prepare") if args.first_recording and not args.window else ("good", "stall", "short", "cancel-open", "cancel-prepare")
        if args.window:
            scenarios+=("lag",)
        for scenario in scenarios:
            subprocess.run([str(exe), str(saturated if scenario == "stall" else wire), str(output / f"{scenario}.bdq"), scenario], check=True, timeout=120)
        if args.pressure_diagnostics:
            from verify_integrated_imu_recording import read_bdq
            quiet=read_bdq(output/'good.bdq').final_summary['recording_pressure']
            blocked=read_bdq(output/'stall.bdq').final_summary['recording_pressure']
            assert quiet['available'] and not quiet['first_loss_observed']
            assert blocked['available'] and blocked['first_loss_observed']
            assert blocked['first_loss']['stage']==6 and blocked['first_loss']['counter']>0
            assert len(blocked['first_loss']['nodes'])==2
            assert any(node['consumer_wait']>0 for node in blocked['first_loss']['nodes'])
            assert blocked['storage_frozen'] and len(blocked['storage_operations'])<=96
            print('Integrated v4 pressure footer: real loss callback, both queues, retired/no-loss snapshots and clean BDQ CRC: PASS')
        if args.first_recording:
            import sys,json
            sys.path.insert(0,str(firmware.parent / "analysis"))
            from bodaqs_analysis.can_imu_packets import read_can_imu_packets
            from bodaqs_analysis.first_imu_recording import assess_first_imu_recording
            if args.two_node:
                from bodaqs_analysis.multi_imu_recording import assess_multi_imu_recording
                if args.window:
                    pressure=assess_multi_imu_recording(output/'stall.bdq',[0,1])
                    for node in pressure['nodes']:
                        delivery=node['metrics']['sample_delivery']
                        # This legacy hardware stub has UID0, so its overall
                        # identity/qualification metric correctly stays unknown.
                        assert delivery['denominator'] is None
                        assert delivery['unresolved_readings']==0
                        assert node['gaps']==[dict(source_segment_id=1,first=908,last=1199,count=292,extent='known')]
                    print('Full logger sample buffers: renewal/STOP complete; offline losses remain explicit: PASS')
                for case in (('good','lag') if args.window else ('good',)):
                    for node, ax in [(0, -32768), (1, 4660)]:
                        decoded=read_can_imu_packets(output / f'{case}.bdq', f'can{node}_imu6')
                        assert [r['sequence'] for r in decoded['readings']]==list(range(64))
                        assert all([r[k] for k in ('ax','ay','az','gx','gy','gz')]==[ax,32767,-1,-32768,32767,-1] for r in decoded['readings'])
                        assert not decoded['gaps'] and not decoded['ambiguous_packets']
                        assert any(r['boundary_event_kind']==8 and r['boundary_validity_flags']&1 and r['related_sequence']==63
                                   for r in decoded['raw_timing_observations'])
                report=assess_multi_imu_recording(output / 'good.bdq',[0,1])
                assert 'expected_node_membership_mismatch' not in report['issues']
                assert len(report['nodes'])==2
                assert report['file_outcome']=='incomplete_or_unresolved'  # Minimal host footer is not physical completion proof.
                for membership in ([0], [0,1,2,3]):
                    wrong=assess_multi_imu_recording(output / 'good.bdq', membership)
                    assert 'expected_node_membership_mismatch' in wrong['issues']
                print('Integrated window selective data/ACK/proof loss, origin-CRC repair and partial STOP: PASS'
                      if args.window else 'Integrated v3 two-source custody, partial STOP, independent axes and membership: PASS')
                return
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

