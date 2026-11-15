"""Bounded observer classification, retirement serialization, memory points and owners."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from assess_control_polling import summarize

p=argparse.ArgumentParser();p.add_argument('--compiler',required=True);a=p.parse_args()
root=Path(__file__).resolve().parents[1]
fixture=r'''
#include "RecordingPressureDiagnostics.h"
#include "ControlPollingJson.h"
#include <cassert>
#include <cstdio>
#include <string>
#include <thread>
int main(){
 namespace T=RecordingTimelineDiagnostics;namespace C=ControlPollingDiagnostics;
 const uint64_t context=UINT64_C(9223372036854775931);
 const uint32_t origin=0xffff0000U;
 T::resetStorage(origin);C::resetStorage(origin);RecordingPressureDiagnostics::resetAcquisition(context,origin);
 struct Case {bool outgoing,partial,unadmitted,ack,pending,seen;uint32_t last;};
 const Case cases[]={{1,1,1,1,1,1,99},{0,1,1,1,1,1,99},{0,0,1,1,1,1,99},
   {0,0,0,0,1,0,99},{0,0,0,0,1,1,80},{0,0,0,0,1,1,81},
   {0,0,0,1,0,1,99},{0,0,0,0,0,1,99}};
 for(unsigned i=0;i<8;++i){
  const auto& c=cases[i];C::peer(0,c.pending,98,100+i,0x28,i);
  C::request(3,0,c.outgoing,c.partial,c.unadmitted,c.ack,c.seen,c.last,100,origin+100+i);
 }
 C::request(1,255,false,false,false,false,false,0,100,origin+200);
 C::event(0,0,0,origin+201);C::event(0,1,50,origin+202);C::event(0,2,0,origin+203);
 const auto& b=C::acquisition.bins[0];
 for(unsigned i=0;i<8;++i)assert(b.reasons[i]==1);
 assert(b.targets[1]==1&&b.targets[3]==8&&b.fetches[0]==8&&b.pendingFetches[0]==6);
 assert(b.ageSumMs[0]==12&&b.ageMaxMs[0]==2&&b.matchedAgeMaxMs[0]==50);
 assert(b.firstOperation[0]==100&&b.lastOperation[0]==107&&b.lastPage[0]==7);
 assert(C::memoryDue(origin+1));C::sampleMemory(origin+1,40000,45000,180000,150000);
 C::sampleMemory(origin+2,1,1,1,1);assert(C::memory.bins[0].samples==1&&C::memory.bins[0].internalFree==40000);
 C::sampleMemory(origin+20000000U,39000,29000,170000,140000);assert(C::memory.bins[1].samples==1);
 JsonDocument unsafe;ControlPollingJson::append(unsafe,false,context);assert(!unsafe["control_poll_timeline"]["available"]);
 JsonDocument wrong;ControlPollingJson::append(wrong,true,context+1);assert(!wrong["control_poll_timeline"]["available"]);
 JsonDocument doc;ControlPollingJson::append(doc,true,context);
 assert(doc["control_poll_timeline"]["available"]==true);
 std::string text;serializeJson(doc,text);puts(text.c_str());
 assert(!C::memoryDue(origin+40000000U));
 T::resetStorage(100);C::resetStorage(100);RecordingPressureDiagnostics::resetAcquisition(7,100);
 assert(!C::memory.frozen&&C::acquisition.peers[0].operation==0&&C::acquisition.bins[0].targets[3]==0);
 std::thread sd([]{for(unsigned i=0;i<10000;++i)C::sampleMemory(100+i*100,40000,30000,180000,150000);});
 std::thread acq([]{for(unsigned i=0;i<10000;++i)C::request(1,255,0,0,0,0,0,0,i,100+i*100);});
 sd.join();acq.join();assert(C::acquisition.bins[0].targets[1]==10000&&C::memory.bins[0].samples==1);
 C::request(1,255,0,0,0,0,0,0,0,720000100);C::request(1,255,0,0,0,0,0,0,0,100);
 assert(C::acquisition.overflow==2&&C::acquisition.bins[0].targets[1]==10000);
 C::sampleMemory(720000100,1,1,1,1);C::sampleMemory(100,1,1,1,1);
 assert(C::memory.overflow==2&&C::memory.bins[0].internalFree==40000);
}
'''
with tempfile.TemporaryDirectory() as temp:
    temp=Path(temp);src=temp/'control.cpp';exe=temp/'control.exe';src.write_text(fixture)
    subprocess.run([a.compiler,'-std=c++17','-O2','-pthread','-Wall','-Wextra','-Werror',
        '-DBODAQS_CONTROL_POLL_DIAGNOSTICS=1','-DBODAQS_STORAGE_TIMELINE=1','-DBODAQS_ORDINARY_FETCH_INTERVAL_MS=20',
        '-DBODAQS_RECORDING_PRESSURE_DIAGNOSTICS=1','-DBODAQS_IMU_FLOW_DIAGNOSTICS=1',
        '-I',str(root/'src'),'-I',str(root/'.pio/libdeps/bodaqs_s3_mini_n4r2/ArduinoJson/src'),str(src),'-o',str(exe)],check=True)
    result=subprocess.check_output([str(exe)],text=True)
    t=json.loads(result)['control_poll_timeline'];r=summarize(t,2**63+123)
    assert r['complete_capture'] and len(r['rows'])==2
    assert list(r['rows'][0]['ordinary_reasons'].values())==[1]*8
    assert r['rows'][0]['pending_age_mean_ms']==[2,None,None,None]
print('Control reasons, exact context/ages, memory sampling/freeze, JSON/parser, reset/wrap/sticky overflow and separate concurrent owners PASS')
