"""Bounded observer classification, retirement serialization, memory points and owners."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from assess_control_polling import summarize

p=argparse.ArgumentParser();p.add_argument('--compiler',required=True);p.add_argument('--acquisition-profile',action='store_true');p.add_argument('--transport-profile',action='store_true');a=p.parse_args()
if a.transport_profile and not a.acquisition_profile:p.error('--transport-profile requires --acquisition-profile')
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
 heapFail=true;T::resetStorage(origin);C::resetStorage(origin);
 RecordingPressureDiagnostics::resetAcquisition(context,origin);
 assert(!C::acquisition && !C::memory);
 C::peer(0,true,0,1,0x28,0);C::event(0,0,0,origin);C::request(3,0,0,0,0,0,0,0,0,origin);
 JsonDocument missing;ControlPollingJson::append(missing,true,context);assert(missing["control_poll_timeline"]["available"]==false);
 heapFail=false;
 T::resetStorage(origin);C::resetStorage(origin);RecordingPressureDiagnostics::resetAcquisition(context,origin);
 const auto* originalBank=C::memory;
 assert(heapAllocCalls==2 && heapAllocationBytes==sizeof(C::Banks));
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
 const auto& b=C::acquisition->bins[0];
 for(unsigned i=0;i<8;++i)assert(b.reasons[i]==1);
 assert(b.targets[1]==1&&b.targets[3]==8&&b.fetches[0]==8&&b.pendingFetches[0]==6);
 assert(b.ageSumMs[0]==12&&b.ageMaxMs[0]==2&&b.matchedAgeMaxMs[0]==50);
 assert(b.firstOperation[0]==100&&b.lastOperation[0]==107&&b.lastPage[0]==7);
 assert(C::memoryDue(origin+1));C::sampleMemory(origin+1,40000,45000,180000,150000);
 C::sampleMemory(origin+2,1,1,1,1);assert(C::memory->bins[0].samples==1&&C::memory->bins[0].internalFree==40000);
 C::sampleMemory(origin+20000000U,39000,29000,170000,140000);assert(C::memory->bins[1].samples==1);
 JsonDocument unsafe;ControlPollingJson::append(unsafe,false,context);assert(!unsafe["control_poll_timeline"]["available"]);
 JsonDocument wrong;ControlPollingJson::append(wrong,true,context+1);assert(!wrong["control_poll_timeline"]["available"]);
#if BODAQS_ACQUISITION_PROFILE
 C::profile(C::Service,origin+100,250,0);C::profile(C::Service,origin+200,500,1);
 C::profile(C::SpiTransfer,origin+300,350);C::profile(C::Sleep,origin+400,950);
 assert(C::acquisition->bins[0].profile.calls[C::Service]==0); // hot updates do not touch PSRAM bank
 C::profile(C::Encode,origin+20000001U,10);
 assert(C::acquisition->bins[0].profile.calls[C::Service]==2); // transition flush
 C::profile(C::Decode,origin+999U,20); // nested parent/child can report an older start bin
 assert(C::hotIndex==1 && C::profileAt(0).totalUs[C::Decode]==20);
 C::profile(C::Service,origin+20000002U,30,0);
 assert(C::profileAt(1).calls[C::Service]==1);
#if BODAQS_TRANSPORT_PROFILE
 C::profile(C::TransportRequest,origin+500U,21);
 C::profile(C::TransportExchange,origin+700U,80);
 C::profile(C::TransportResponse,origin+900U,17);
 C::profile(C::FragmentAccept,origin+910U,8);
 assert(C::hotIndex==1 && C::profileAt(0).totalUs[C::FragmentAccept]==8);
 assert(C::profileAt(0).calls[C::TransportRequest]==1);
 C::profile(C::TransportRequest,origin+20000003U,3);
 assert(C::profileAt(1).calls[C::TransportRequest]==1);
 assert(sizeof(C::Profile)==288);
 assert(C::reservedBytes()==20540+3*sizeof(void*)); // Host pointers are wider than ESP32 pointers.
#endif

 assert(C::profileAt(0).totalUs[C::Service]==750);
 assert(C::profileAt(0).maxUs[C::Service]==500);
 assert(C::profileAt(0).calls[C::Service]==2);
 assert(C::profileAt(0).cores[0]==1&&C::profileAt(0).cores[1]==1);
#endif
 JsonDocument doc;ControlPollingJson::append(doc,true,context);
 assert(doc["control_poll_timeline"]["available"]==true);
 std::string text;serializeJson(doc,text);puts(text.c_str());
 assert(!C::memoryDue(origin+40000000U));
 T::resetStorage(100);C::resetStorage(100);RecordingPressureDiagnostics::resetAcquisition(7,100);
 assert(C::memory==originalBank); // No per-recording allocation/growth.
 assert(heapAllocCalls==2);
#if BODAQS_ACQUISITION_PROFILE
 assert(C::hotIndex==C::capacity && C::hotProfile.calls[C::Service]==0);
#endif
 assert(!C::memory->frozen&&C::acquisition->peers[0].operation==0&&C::acquisition->bins[0].targets[3]==0);
 std::thread sd([]{for(unsigned i=0;i<10000;++i)C::sampleMemory(100+i*100,40000,30000,180000,150000);});
 std::thread acq([]{for(unsigned i=0;i<10000;++i)C::request(1,255,0,0,0,0,0,0,i,100+i*100);});
 sd.join();acq.join();assert(C::acquisition->bins[0].targets[1]==10000&&C::memory->bins[0].samples==1);
 C::request(1,255,0,0,0,0,0,0,0,720000100);C::request(1,255,0,0,0,0,0,0,0,100);
 assert(C::acquisition->overflow==2&&C::acquisition->bins[0].targets[1]==10000);
 C::sampleMemory(720000100,1,1,1,1);C::sampleMemory(100,1,1,1,1);
 assert(C::memory->overflow==2&&C::memory->bins[0].internalFree==40000);
}
'''
with tempfile.TemporaryDirectory() as temp:
    temp=Path(temp);src=temp/'control.cpp';exe=temp/'control.exe';src.write_text(fixture)
    (temp/'esp_heap_caps.h').write_text('''#pragma once
#include <cstdlib>
#include <cassert>
constexpr int MALLOC_CAP_SPIRAM=4,MALLOC_CAP_8BIT=2;
inline bool heapFail=false;
inline unsigned heapAllocCalls=0;
inline size_t heapAllocationBytes=0;
inline void* heap_caps_malloc(size_t n,int caps){
 assert(caps==(MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));++heapAllocCalls;heapAllocationBytes=n;
 return heapFail?nullptr:std::malloc(n);
}
''')
    subprocess.run([a.compiler,*(['-DBODAQS_ACQUISITION_PROFILE=1'] if a.acquisition_profile else []),*(['-DBODAQS_TRANSPORT_PROFILE=1'] if a.transport_profile else []),'-std=c++17','-O2','-pthread','-Wall','-Wextra','-Werror',
        '-DARDUINO_ARCH_ESP32=1','-DBODAQS_CONTROL_POLL_DIAGNOSTICS=1','-DBODAQS_STORAGE_TIMELINE=1','-DBODAQS_ORDINARY_FETCH_INTERVAL_MS=20',
        '-DBODAQS_RECORDING_PRESSURE_DIAGNOSTICS=1','-DBODAQS_IMU_FLOW_DIAGNOSTICS=1',
        '-I',str(temp),'-I',str(root/'src'),'-I',str(root/'.pio/libdeps/bodaqs_s3_mini_n4r2/ArduinoJson/src'),str(src),'-o',str(exe)],check=True)
    result=subprocess.check_output([str(exe)],text=True)
    t=json.loads(result)['control_poll_timeline']
    if a.acquisition_profile:
        assert t['profile_version']==(2 if a.transport_profile else 1) and len(t['profile_stages'])==(16 if a.transport_profile else 12)
        assert t['bins'][0]['profile']['total_us'][0]==750
        assert t['bins'][0]['profile']['cores']==[1,1,0]
        if a.transport_profile:
            assert t['bins'][0]['profile']['total_us'][12:]==[21,80,17,8]
            assert t['bins'][1]['profile']['total_us'][12:]==[3,0,0,0]
    r=summarize(t,2**63+123)
    assert r['complete_capture'] and len(r['rows'])==2
    assert list(r['rows'][0]['ordinary_reasons'].values())==[1]*8
    assert r['rows'][0]['pending_age_mean_ms']==[2,None,None,None]
print('Control reasons, exact context/ages, memory sampling/freeze, JSON/parser, reset/wrap/sticky overflow and separate concurrent owners PASS')
