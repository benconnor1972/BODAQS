"""Bounded owner-only trace windows, freeze, wrap, reset and real JSON export."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler",default="g++")
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    fixture=r'''
#include "MeasurementPipelineTrace.h"
#include <cassert>
#include <cstring>
#include <cstdio>
namespace T=MeasurementPipelineTrace;
int main() {
 T::reset(UINT64_C(18446744073709551614),10);T::setParticipants(3);
 T::pending(0,0);
 BodaqsMeasurementSlot poll={},reply={};poll.kind=1;poll.node=0;poll.body[0]=1;
 reply.node=255;reply.available=3;reply.context=T::context;
 for(unsigned i=0;i<300;++i) T::record(poll,&reply,0xffffff00u+i*600u,500,1,3,0,0,i+1,true);
 assert(T::firstLoss.count==128 && T::firstLoss.overwritten==172 && !T::stop.count);
 assert(T::slots==300 && T::empty==300 && T::emptyWithAvailable==300);
 assert(!T::dump([](const char*){assert(false);})); // never serialize live owner memory
 T::loss();const auto frozen=T::firstLoss;
 poll.kind=12;poll.body[12]=0x25;poll.node=1;
 T::record(poll,&reply,200000,600,0,0,0,0,305,true);assert(T::stopArmed && T::stop.count==1);
 T::terminal(0);assert(!T::stop.reason);
 poll={};poll.kind=14;poll.node=1;poll.object=77;poll.body[0]=2;
 poll.body[2]=1;poll.body[3]=0;poll.body[12]=4;bodaqs_measurement_put(poll.body+8,17,4);
 reply={};reply.context=T::context;reply.kind=2;reply.node=0;reply.object=15;reply.index=2;reply.retired=true;
 T::record(poll,&reply,201000,610,3,5,7,T::KnownFragment,309,true);
 T::terminal(1);assert(T::stop.reason==2 && T::stop.count==2);
 T::record(poll,nullptr,202000,3,0,0,0,0,0,false);assert(T::invalid==1 && T::stop.count==2);
 assert(!memcmp(&frozen,&T::firstLoss,sizeof frozen));
 T::finish();assert(T::dump([](const char* line){std::fputs(line,stdout);}));
 T::reset(2,0);assert(!T::slots && !T::firstLoss.count && !T::stopArmed);
 T::setParticipants(1);poll={};poll.kind=12;poll.body[12]=0x25;
 reply={};reply.context=1;reply.kind=7;reply.node=0;reply.body[0]=1;reply.body[1]=14;reply.body[2]=6;
 T::record(poll,&reply,1,1,0,0,0,0,310,true);
 assert(!T::stop.reason); // Old context cannot freeze current STOP evidence.
 reply.context=2;reply.body[8]=1;
 T::record(poll,&reply,2,1,0,0,0,0,311,true);
 assert(!T::stop.reason); // Nor may malformed reserved bytes.
 reply.body[8]=0;
 T::record(poll,&reply,3,1,0,0,0,0,312,true);
 assert(T::stop.reason==4);T::terminal(0);assert(T::stop.reason==4);
 T::finish();
 T::reset(3,0);T::slots=UINT32_MAX-1;
 T::record(poll,nullptr,1,1,0,0,0,0,0,false);assert(T::slots==UINT32_MAX && !T::exhausted);
 T::record(poll,nullptr,2,1,0,0,0,0,0,false);assert(T::slots==UINT32_MAX && T::exhausted && T::firstLoss.count==1);
 T::finish();T::reset(4,0);assert(!T::slots && !T::exhausted && !T::firstLoss.count);
}
'''
    with tempfile.TemporaryDirectory(prefix="bodaqs-pipeline-") as tmp:
        cpp,exe=Path(tmp)/"trace.cpp",Path(tmp)/"trace.exe"
        cpp.write_text(fixture,encoding="utf-8")
        subprocess.run([args.compiler,"-std=c++17","-O2","-Wall","-Wextra","-Werror",
            "-DBODAQS_SPI_MEASUREMENT_V2=1","-DBODAQS_IMU_FLOW_DIAGNOSTICS=1","-DBODAQS_PIPELINE_TRACE=1",
            "-I",str(root/"src"),str(cpp),"-o",str(exe)],check=True)
        rows=[json.loads(line) for line in subprocess.check_output([str(exe)],text=True).splitlines()]
        summary=rows[0]
        assert summary["context"]=="18446744073709551614" and summary["slots"]==303
        assert summary["terminal_mask"]==3 and summary["invalid"]==1
        windows={r["window"]:r for r in rows if r["type"]=="window"}
        frames={n:[r["v"] for r in rows if r["type"]=="frame" and r["window"]==n] for n in windows}
        assert len(frames[0])==128 and frames[0][0][0]==173 and frames[0][-1][0]==300
        assert [r[0] for r in frames[1]]==[305,309]
        entry=dict(zip(windows[1]["columns"],frames[1][1]))
        assert {k:entry[k] for k in ("target_object","ack_object","target_class","target_node","target_index","ack_class","ack_node")}==dict(
            target_object=17,ack_object=77,target_class=1,target_node=0,target_index=4,ack_class=2,ack_node=1)
        assert rows[-1]["type"]=="end"
    print("Actual pipeline trace bounded windows/freeze/wrap/reset and JSON schema: PASS")

if __name__=="__main__":
    main()
