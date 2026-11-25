#include <ArduinoJson.h>
#include "ImuFlowDiagnostics.h"
#include "RecordingPressureDiagnostics.h"
#include "BdqV2FileSink.h"
#include <cassert>
#include <cstdio>
#include <string>

uint32_t clockUs=0;
uint32_t micros() {return clockUs;}
static bool retired=true;
namespace RemoteImuRecording {
const ImuFlowDiagnostics::Snapshot* finalFlowSnapshot(bool first) {
 if(!retired || !ImuFlowDiagnostics::haveFinished) return nullptr;
 return first?(ImuFlowDiagnostics::haveFirstLoss?&ImuFlowDiagnostics::firstLoss:nullptr):&ImuFlowDiagnostics::finished;
}
}
static uint16_t queueDepthSnapshot_() {return 91;}
static void recordStorageWriteStall_(uint8_t,uint32_t,uint32_t,uint32_t,uint16_t) {}
// PRODUCTION_ADAPTER

int main() {
 using namespace RecordingPressureDiagnostics;
 resetStorage();resetAcquisition(123,300000);ImuFlowDiagnostics::reset(123,300);
 ImuFlowDiagnostics::nodeConsumer(0,false,7,105,2048,4,2048,512,350000);
 service(350000);service(400000);
 loss(1,1,9,6,3,400000);
 ImuFlowDiagnostics::loss(3,400,400000);
 File file;file.writeUs=200000;file.flushUs=100;
 BdqV2FileSink sink(file);sink.configure(nullptr,0,observeBdqV2FileOperation_);
 uint8_t bytes[16384]={};clockUs=300000;assert(sink.write(bytes,sizeof bytes));assert(sink.flush());
 clockUs=2400000;file.writeUs=10;assert(sink.write(bytes,1));
 assert(sink.write(bytes,2));service(2500000); // Both histories stay frozen.
 ImuFlowDiagnostics::finish(2600,2600000);
 JsonDocument doc;appendRecordingPressure_(doc);
 std::string json;serializeJson(doc,json);puts(json.c_str());
 retired=false;JsonDocument unavailable;appendRecordingPressure_(unavailable);
 assert(unavailable["recording_pressure"]["available"]==false);
 retired=true;
 // Last-N order, explicit overwrite count, modulo-32 clock wrap, and restart.
 resetStorage();resetAcquisition(456,0xffff0000u);
 for(unsigned i=0;i<100;++i) storageOperation(3,0xffff0000u+i*100,10,i,0);
 assert(storage.operations.count==96 && storage.operations.overwritten==4);
 assert(storage.operations.at(0).bytes==4 && storage.operations.at(95).bytes==99);
 loss(0,1,9,6,1,0xfffffff0u);
 storageOperation(4,0xfffffff0u,32,0,0);assert(!storage.frozen);
 // A completion timestamp just before a concurrently published loss must not
 // be mistaken for billions of microseconds after it.
 storageOperation(3,0xffffff00u,1,0,0);assert(!storage.frozen);
 storageOperation(3,2000000,1,0,0);assert(storage.frozen);
 resetStorage();resetAcquisition(789,1);
 assert(!triggered.load() && !storage.frozen && !storage.operations.count);
 assert(acquisition.context==789 && !acquisition.gaps.count);
}
