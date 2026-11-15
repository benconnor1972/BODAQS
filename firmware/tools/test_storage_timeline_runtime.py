"""Production SD observer/pump branch and late timeline coverage, JSON and owners."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from runtime_test_helpers import definition

p=argparse.ArgumentParser();p.add_argument('--compiler',default='g++');p.add_argument('--control-state',action='store_true');a=p.parse_args()
root=Path(__file__).resolve().parents[1];source=(root/'src/StorageManager.cpp').read_text()
observer=definition(source,'static void observeBdqV2FileOperation_(')
pump=definition(source,'static void storageService_() {')
branch=definition(pump,'  if (loggingActive && isBdqV2Format_()) {')
assert 'RecordingTimelineDiagnostics::storageService' in branch
assert 'RecordingTimelineJson::append(document,timelineFinished!=nullptr' in source
fixture=r'''
#include <ArduinoJson.h>
#include "RecordingPressureDiagnostics.h"
#include "RecordingTimelineJson.h"
#include "BdqV2FileSink.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <thread>
uint32_t clockUs=0;
uint32_t micros(){return clockUs;}
uint32_t millis(){return clockUs/1000;}
int64_t esp_timer_get_time(){return clockUs;}
static uint16_t queueDepthSnapshot_(){return 91;}
static void recordStorageWriteStall_(uint8_t,uint32_t,uint32_t,uint32_t,uint16_t){}
// OBSERVER
static BdqV2FileSink* activeSink;
static bool pending=true,loggingActive=true,g_sdTrackEnabled=false,g_sdWriteSinceLastSample=false;
static uint32_t s_flushCount=0,s_flushTotalMs=0,s_flushMaxMs=0,s_storageWriteFailures=0;
static struct {uint32_t drainLoops=0,drainRows=0,drainLoopUs=0;} s_storageTiming;
static void TimingStats_record(uint32_t& value,uint32_t duration){value+=duration;}
static bool isBdqV2Format_(){return true;}
struct Writer {
 bool hasPendingData(){return pending;}
 bool flush(){return activeSink->flush();}
} s_bdqV2Writer;
static bool drainOneReadyBdqV2Chunk_(uint64_t){
 clockUs+=1000;uint8_t bytes[16384]={};pending=false;return activeSink->write(bytes,sizeof bytes);
}
static void pump(){static unsigned long lastFlush=0;unsigned long now=millis();
// PUMP
}
int main(){
 namespace T=RecordingTimelineDiagnostics;namespace P=RecordingPressureDiagnostics;
 constexpr uint64_t context=UINT64_C(9223372036854775931);
 P::resetStorage();T::resetStorage(500000);P::resetAcquisition(context,500000);
 P::loss(0,2,9,6,1,510000);
 P::storageOperation(3,3000000,1,1,1);assert(P::storage.frozen);
 for(unsigned i=1;i<=350000;++i)P::service(500000+i*1000);
 assert(P::acquisition.frozen);
 clockUs=350500000;
 T::consumer(2,1,false,128,16,clockUs);P::loss(2,1,9,6,25,clockUs);
 File file;file.writeUs=200000;file.flushUs=1000;
 BdqV2FileSink sink(file);sink.configure(nullptr,0,observeBdqV2FileOperation_);activeSink=&sink;
 pump();
 assert(P::storage.operations.count==1); // Old first-loss ring froze long ago.
 const auto& b=T::storage.bins[17];assert(b.writes==1 && b.bytes==16384);
 assert(b.writeUs==200000 && b.flushUs==1000 && b.slowWrites==1);
 assert(b.serviceCalls==1 && b.serviceUs==202000 && b.nonIoServiceUs==1000);
 assert(b.primaryPeak==91 && T::acquisition.bins[17].samplePeak[2]==128);
 clockUs+=10000;pump();assert(b.serviceGapMaxUs==10000);
 assert(T::acquisition.bins[17].sourceLossReports[2]==1);
 assert(T::acquisition.bins[17].sampleWaits==1);
 JsonDocument unsafe;RecordingTimelineJson::append(unsafe,false,context);
 assert(unsafe["recording_timeline"]["available"]==false);
 JsonDocument wrong;RecordingTimelineJson::append(wrong,true,context+1);
 assert(wrong["recording_timeline"]["available"]==false);
 JsonDocument doc;RecordingTimelineJson::append(doc,true,context);
 assert(doc["recording_timeline"]["available"]==true);
 assert(doc["recording_timeline"]["context"].as<uint64_t>()==context);
 std::string json;serializeJson(doc,json);puts(json.c_str());
 T::storageOperation(3,clockUs,999,1,1);assert(b.writes==1); // Footer excluded.
 T::resetStorage(0xffff0000u);T::resetAcquisition(789,0xffff0000u);
 T::service(uint32_t(0xffff0000u+20000000u));assert(T::acquisition.bins[1].services==1);
 T::storageOperation(3,uint32_t(0xffff0000u+720000000u),1,1,1);
 assert(T::storage.overflow==1 && !T::storage.used);
 T::storageOperation(3,0xffff0000u,1,1,1);assert(T::storage.overflow==2 && !T::storage.used);
 T::service(uint32_t(0xffff0000u+720000000u));assert(T::acquisition.overflow==1);
 T::service(0xffff0000u);assert(T::acquisition.overflow==2 && !T::acquisition.bins[0].services);
 T::resetStorage(100);T::resetAcquisition(790,100);
 assert(!T::storage.overflow && !T::acquisition.overflow && !T::acquisition.used && !T::storage.frozen);
 // Two real owners write distinct banks concurrently; footer reads after join.
 std::thread sd([]{for(unsigned i=0;i<10000;++i)T::storageOperation(3,100+i*100,2,16,7);});
 std::thread acq([]{for(unsigned i=0;i<10000;++i){T::service(100+i*100);T::consumer(0,1,true,4,1,100+i*100);}});
 sd.join();acq.join();assert(T::storage.bins[0].writes==10000);
 assert(T::acquisition.bins[0].services==10000 && T::acquisition.bins[0].sampleCalls==10000);
 T::storageService(1000001,1,0,0);assert(T::storage.bins[0].serviceTimeInvalid==1);
}
'''.replace('// OBSERVER',observer).replace('// PUMP',branch)
if a.control_state:
    fixture=fixture.replace('#include "RecordingTimelineJson.h"','#include "RecordingTimelineJson.h"\n#include "ControlPollingJson.h"')
    fixture=fixture.replace('static uint16_t queueDepthSnapshot_()',
        'constexpr int MALLOC_CAP_INTERNAL=1,MALLOC_CAP_8BIT=2,MALLOC_CAP_SPIRAM=4;\n'
        'static unsigned heapCalls=0;\n'
        'static uint32_t heap_caps_get_free_size(int caps){++heapCalls;return caps&1?40000:180000;}\n'
        'static uint32_t heap_caps_get_largest_free_block(int caps){++heapCalls;return caps&1?30000:150000;}\n'
        'static uint16_t queueDepthSnapshot_()')
    fixture=fixture.replace('T::resetStorage(500000);P::resetAcquisition',
        'T::resetStorage(500000);ControlPollingDiagnostics::resetStorage(500000);P::resetAcquisition')
    fixture=fixture.replace('std::string json;serializeJson(doc,json);',
        'ControlPollingJson::append(doc,true,context);\n'
        'assert(doc["control_poll_timeline"]["available"]==true);\n'
        'assert(ControlPollingDiagnostics::memory.bins[17].internalFree==40000 && heapCalls==4);\n'
        'assert(ControlPollingDiagnostics::memory.bins[17].psramLargest==150000);\n'
        'std::string json;serializeJson(doc,json);')
with tempfile.TemporaryDirectory(prefix='bodaqs-timeline-') as temp:
    temp=Path(temp)
    (temp/'Arduino.h').write_text('#pragma once\n#include <stdint.h>\n#include <stddef.h>\nuint32_t micros();\n')
    (temp/'FS.h').write_text('''#pragma once
#include <stdint.h>
#include <stddef.h>
extern uint32_t clockUs;
struct File {
 uint32_t writeUs=0,flushUs=0;
 explicit operator bool()const{return true;}
 size_t write(const uint8_t*,size_t n){clockUs+=writeUs;return n;}
 void flush(){clockUs+=flushUs;}
};
''')
    cpp=temp/'fixture.cpp';exe=temp/'fixture.exe';cpp.write_text(fixture)
    subprocess.run([a.compiler,'-std=c++17','-O2','-pthread','-Wall','-Wextra','-Werror',
        *(['-DBODAQS_CONTROL_POLL_DIAGNOSTICS=1','-DBODAQS_ORDINARY_FETCH_INTERVAL_MS=20'] if a.control_state else []),
        '-DBODAQS_STORAGE_TIMELINE=1','-DBODAQS_RECORDING_PRESSURE_DIAGNOSTICS=1','-DBODAQS_IMU_FLOW_DIAGNOSTICS=1',
        '-DBODAQS_TIMING_INSTRUMENTATION=1','-I',str(temp),'-I',str(root/'src'),
        '-I',str(root/'.pio/libdeps/bodaqs_s3_mini_n4r2/ArduinoJson/src'),str(cpp),'-o',str(exe)],check=True)
    result=subprocess.run([str(exe)],check=True,capture_output=True,text=True)
    t=json.loads(result.stdout)['recording_timeline'];assert t['context']==9223372036854775931
    assert len(t['bins'])==18 and t['bins'][17]['storage']['non_io_service_us']==1000
    assert t['bins'][17]['acquisition']['source_loss_reports']==[0,0,1,0]
print('Actual SD observer/pump non-I/O split, late350s after first-loss freeze, retired JSON, wrap/reset/overflow and concurrent owners PASS')
