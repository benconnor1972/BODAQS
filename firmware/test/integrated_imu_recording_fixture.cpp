// Included after the production lifecycle composition by the acceptance runner.
// Only clocks, sensor hardware, SPI delivery and filesystem I/O are simulated.
#include "RecordingStorageWorker.h"
#include "BdqV2Writer.h"
#include "BdqV2StreamQueue.h"
#include <atomic>
#include <thread>
#include <fstream>
#include <string>
#include <algorithm>
#define ESP32 1
#define TRACE(...) do {} while(0)
#define LOGGING_LOGI(...) do {} while(0)
#define LOGGING_LOGW(...) do {} while(0)
#define RTC_LOGW(...) do {} while(0)
#define xTaskCreatePinnedToCore(...) do {} while(0)
#include "RecordingLifecycle.h"
using LifecycleState = RecordingLifecycle::State;
static RecordingLifecycle s_lifecycle;
static bool phaseIs_(LifecycleState state) {return s_lifecycle.state()==state;}
static bool isLifecycleOwner_() {return true;} // This fixture has one control-loop owner.
static bool s_localStopPending=false,s_remotePreparing=false,s_remoteFaultShown=false;
#define s_running phaseIs_(LifecycleState::Recording)
#define s_starting phaseIs_(LifecycleState::Preparing)
#define s_stopping (phaseIs_(LifecycleState::Stopping) || phaseIs_(LifecycleState::Finalizing))
static bool s_storageStartPending=false,s_storageStopRequested=false;
static const LoggerConfig* s_cfg=&config;
static LoggingManager::StartFailureHint s_startFailureHint;
static LoggingManager::StopContext s_stopContext;
static LoggingConfigIssue s_configurationIssue=LoggingConfigIssue::None;
static char s_configurationDetail[160]={};
static uint32_t s_intervalUs=2000;
static uint64_t s_t0UnixUs=0,s_sampleCount=0;
static void* s_sampleTask=reinterpret_cast<void*>(1);
static std::atomic<bool> s_sampleInProgress{false};
static unsigned localStarts=0,localStops=0,finalizations=0;
static std::string uiStatus;
namespace LoggingManager {
bool isRunning() {return s_running;}
void refreshConfigurationStatus() {}
const char* stopReasonName(StopReason) {return "fixture";}
}
static void captureStopContext_(LoggingManager::StopReason reason,const char* event) {s_stopContext.reason=reason;s_stopContext.triggerEvent=event;}
static void resetLateStats_() {}
static void vTaskDelay(int) {}
namespace UI {
void status(const String& text) {uiStatus=text.c_str();}
void toast(const char*,int,int) {}
void loop() {}
enum {TARGET_SERIAL,LVL_INFO};
void println(const char*,const char*,int,int) {}
}
namespace SensorManager {
bool requiresBdqV2(const LoggerConfig&) {return true;}
uint16_t synchronousMaxSampleRateHz() {return 0;}
bool validateLoggingStart(const LoggerConfig&,uint16_t,char*,size_t) {return true;}
bool onLoggingStart(char*,size_t) {return true;}
bool startLoggingAcquisition() {++localStarts;return true;}
void onLoggingStop() {++localStops;}
void onLoggingFinalized() {++finalizations;}
uint8_t activeCount() {return 5;}
uint8_t sessionExcludedCount() {return 0;}
size_t pendingLoggingRows() {return 0;}
}
namespace AnalogInputManager {
uint16_t configureFromConfig(const LoggerConfig&,uint16_t hz) {return hz;}
void onLoggingStart() {}
void onLoggingStop() {}
}
namespace PowerManager {bool canStartLogging(){return true;}void restoreCpuFreqAfterLogging(){}}
namespace UploadModeManager {bool isActive(){return false;}}
namespace WebServerManager {bool isRunning(){return false;}void stop(){}}
namespace WiFiManager {void suspendForLogging(){}void resumeAfterLogging(){}}
namespace I2CManager {void resetRecoveryStats(){}}
// This CAN-only composition has no local I2C producer. Retirement races with
// a live I2C owner are covered by the independent lifecycle adapter fixture.
namespace I2CBusScheduler {void requestStop(){}bool stopped(){return true;}}
namespace DisplayManager {void prepareLoggingScreen(uint16_t,uint8_t){}}
namespace IndicatorManager {void ledOn(){}void ledOff(){}}
void ButtonManager_setPollingEnabled(bool) {}
bool ConfigManager::setLogFormat(LogFormat,bool) {return true;}
bool RTCManager_hasValidTime(){return true;}
uint64_t RTCManager_getEpochMs(){return 0;}

static BdqV2StreamQueue<16,64,2> local(1,uint64_t{1}<<32);
static const BdqV2CatalogChannel localChannels[]={
 {"sequence","sequence","count","uint32",0,"diagnostic"},
 {"native_tick","time","us","uint32",4,"time"},
 {"status_flags","status","bitfield","uint16",8,"diagnostic"},
 {"value","raw","count","int16",12,"signal"}};
static const BdqV2CatalogStatusFlag localFlags[]={{"discontinuity_before",1}};
static uint32_t localSequence=0;
static FILE* inputLedger=nullptr;
static uint32_t rejectedSamples[4]={};
static void localRow() {
 uint8_t row[16]={};BdqV2Format::putU32(row,localSequence++);BdqV2Format::putU32(row+4,clockMs*1000);
 BdqV2Format::putU16(row+12,20);assert(local.enqueueRecord(row,sizeof row));
}

struct FileStorage final:RecordingStorageSink,BdqV2ByteSink {
 const char* path=nullptr;FILE* file=nullptr;
 BdqV2Writer writer;uint8_t workspace[4096]={};
 std::atomic<bool> blocked{false},entered{false};
 int blockOperation=0;bool shortNext=false,cleanClosed=false;unsigned healthChecks=0;
 void gate(int operation) {if(operation==blockOperation) {entered=true;while(blocked.load()) std::this_thread::yield();}}
 bool healthCheck() override {++healthChecks;return true;}
 bool start() override {
   gate(1);file=std::fopen(path,"wb");assert(file);writer.clearStreams();
   BdqV2StreamDescriptor descriptors[9]={};
   const unsigned count=fixtureSensorCount*2;
   assert(RemoteImuRecording::describe(descriptors,8,34)==count);
   auto& d=descriptors[count];d.source=local.source();d.channels=localChannels;d.channelCount=4;
   std::strcpy(d.streamKey,"primary");std::strcpy(d.transport,"local");std::strcpy(d.clockId,"logger_monotonic");
   std::strcpy(d.clockRelation,"logger_monotonic");d.nominalSampleRateNumeratorHz=500;d.statusFlags=localFlags;d.statusFlagCount=1;
   size_t size=BdqV2Catalog::measure("integrated_host",descriptors,count+1);assert(size);
   std::vector<char> catalog(size+1);size_t written=0;
   assert(BdqV2Catalog::write("integrated_host",descriptors,count+1,catalog.data(),catalog.size(),written));
   for(unsigned i=0;i<=count;++i) assert(writer.addStream(descriptors[i].source));
   const char metadata[]=R"({"format":"bdq.v2","format_name":"BDQLOG v2","recording_id":"integrated","device_id":"integrated_host","firmware_name":"BODAQS","firmware_version":"174-host","hardware_version":"host","created_unix_us":0,"timezone":"Australia/Perth","log_format":"bodaqs_multi_stream_binary","native_stream_contract":"bodaqs.native_stream.v1","stream_count":9,"logger_monotonic_clock":{"clock_id":"logger_monotonic","unit":"us","nondecreasing":true}})";
   std::string metadataText(metadata);
   const auto position=metadataText.find("\"stream_count\":9");assert(position!=std::string::npos);
   metadataText.replace(position,16,"\"stream_count\":"+std::to_string(count+1));
   return writer.begin(*this,workspace,sizeof workspace,0,metadataText.c_str(),metadataText.size(),catalog.data(),written);
 }
 bool write(const uint8_t* p,size_t n) override {
   gate(2);
   if(shortNext) {shortNext=false;assert(n>1);assert(std::fwrite(p,1,n-1,file)==n-1);return false;}
   return std::fwrite(p,1,n,file)==n;
 }
 bool flush() override {return std::fflush(file)==0;}
 bool service() override {
   if(writer.hasPendingData()) (void)writer.drainNextChunk();
   return !writer.failed();
 }
 bool stop(bool clean) override {
   const char summary[]=R"({"software_candidate":true,"physical_timing_bounds":"unknown","inter_node_alignment":"unknown"})";
   cleanClosed=clean && writer.end(summary,sizeof summary-1);
   if(!clean) writer.abort();
   assert(std::fclose(file)==0);file=nullptr;return cleanClosed;
 }
} storage;
static RecordingStorageWorker worker(storage);
bool StorageManager_startLog(){return worker.requestStart();}
void StorageManager_stopLog(){worker.requestStop();}
bool StorageManager_recordingReady(){return worker.recording();}
bool StorageManager_recordingIoPending(){return worker.pending();}
bool StorageManager_storageFault(){return worker.fault()!=RecordingStorageWorker::Fault::None;}
bool StorageManager_storageUnresponsive(){return worker.fault()==RecordingStorageWorker::Fault::Unresponsive;}
bool StorageManager_readyForLogging(){return true;}
const char* StorageManager_lastStatus(){return "host";}
unsigned StorageManager_getSampleRateHz(){return 500;}
uint32_t StorageManager_getSampleIntervalUs(){return 2000;}
void StorageManager_setSampleRate(uint16_t){}
bool StorageManager_usesIndependentStreams(){return true;}
bool StorageManager_canAcceptSample(){return true;}
bool sampleOnce_(bool){return false;}
struct Allocation {size_t primaryQueueBytes=0,workspaceBytes=4096,outputBufferBytes=0,catalogPeakBytes=0,primaryColumnsPeakBytes=0,metadataPayloadBytes=0,staticStateBytes=0,storageTaskStackBytes=0;};
Allocation StorageManager_recordingAllocation(){return {};}
// PRODUCTION_LOGGING

static bool serviceStorage=true;
static uint32_t maxRenewalGap[4]={},lastRenewal[4]={},renewalSequence[4]={};
static void step(unsigned duration) {
 const uint32_t until=clockMs+duration;
 while(int32_t(clockMs-until)<0) {
   ++clockMs;
   for(unsigned n=0;n<fixtureSensorCount;++n) {
     auto& a=acquisitions[n];bodaqs_control_acquisition_tick(&a,clockMs);
     if(!a.lease_valid) lastRenewal[n]=0;
     if(a.lease_valid && a.renewal_sequence!=renewalSequence[n]) {
       if(lastRenewal[n]) maxRenewalGap[n]=std::max(maxRenewalGap[n],clockMs-lastRenewal[n]);
       lastRenewal[n]=clockMs;renewalSequence[n]=a.renewal_sequence;
     }
   }
   if(master.acquisition_retirement_pending) bodaqs_master_service_measurement_fence(&master,true,true);
   CanMasterManager::loop();
   // Host-only scheduling envelope: multiple nonblocking service turns per
   // logical millisecond. SPI itself advances the injected clock every ten
   // slots; no wall-clock or physical throughput conclusion follows.
   for(unsigned slots=0;slots<12;++slots) {AcquisitionControl::service();LoggingManager::loop();}
   if(serviceStorage) worker.step(clockMs);
 }
}
static void setup() {
 ImuAdmission::Profile costs;costs.maximumSourceSamplesPerSecond=3333;costs.qualified=true;
 costs.adcAttemptsPerConversion=1;costs.canBurstFrames=20;costs.spiBurstSlots=32;
 costs.sampleSlotUs=64;costs.auxiliarySlotUs=64;costs.sampleDrainSlotsPerSecond=14000;
 if(!ImuAdmission::singleNodeSmokeBuild()) assert(RemoteImuRecording::setAdmissionProfile(costs));
 saved.type=SensorType::LSM6DSO32XImu;std::strcpy(saved.name,"remote_imu");
 assert(savedParams.set("provider","can:0"));assert(savedParams.set("endpoint","imu"));
 assert(savedParams.set("profile","imu6_3333_32g_2000dps_v1"));saved.params.bind(&savedParams);
 fixtureSensorCount=ImuAdmission::fourNodeSampleUnitBenchBuild()?4:ImuAdmission::sampleUnitBenchBuild()?2:ImuAdmission::singleNodeSmokeBuild()?1:4;
 for(unsigned n=1;n<fixtureSensorCount;++n) {
   extra[n-1]=saved;extraParams[n-1]=savedParams;
   char provider[8];std::snprintf(provider,sizeof provider,"can:%u",n);
   assert(extraParams[n-1].set("provider",provider));extra[n-1].params.bind(&extraParams[n-1]);
 }
 reset();lifecycleEnabled=true;fastMeasurementClock=true;config.logFormat=LogFormat::BodaqsMultiStreamBinary;
 if(ImuAdmission::sampleUnitBenchBuild()) config.sampleRateHz=500;
 BodaqsMasterDiscoveryRecord records[4]={};
 for(uint8_t n=0;n<fixtureSensorCount;++n) {
   auto& f=peerFixture(n);f.view.active_session=0;f.authority={};f.view.flags=0;f.view.boot_id=17;
   f.authority.next_challenge=1;
   bodaqs_control_acquisition_init(&acquisitions[n],&f.authority,&f.view,f.apply.effective,backendEvent,reinterpret_cast<void*>(static_cast<uintptr_t>(n)));
   acquisitionSnapshots[n]={};acquisitionSnapshots[n].capture=bodaqs_control_apply_capture;acquisitionSnapshots[n].capture_context=&f.apply;
   acquisitionSnapshots[n].capture_acquisition=bodaqs_control_acquisition_capture;acquisitionSnapshots[n].acquisition_context=&acquisitions[n];
   records[n].node_address=n;records[n].flags=1;records[n].boot_id=17;
   records[n].capabilities=BODAQS_CAN_LINK_CAP_ACQUISITION;records[n].endpoint_mask=1;records[n].hardware_uid=123+n;
 }
 bodaqs_master_service_set_inventory(&master,2,records,4);assert(CanMasterManager::probeNow());
 for(unsigned i=0;i<300000;++i) {advance(1);bool ready=true;for(unsigned n=0;n<fixtureSensorCount;++n) ready&=CanMasterManager::configurationReconciled(n);if(ready) break;}
 for(unsigned n=0;n<fixtureSensorCount;++n) assert(CanMasterManager::configurationReconciled(n));
}
static void awaitRunning() {
 const unsigned expectedStarts=localStarts+1;
 assert(LoggingManager::requestStart()==LoggingManager::StartResult::Pending);
 for(unsigned i=0;i<20000 && !s_running;++i) step(1);
 if(!s_running || RemoteImuRecording::failed()) {std::fprintf(stderr,"start diagnostic: expected%u starts%u starting%d stopping%d configured%d prepared%d remote_failed%d worker%d UI%s reason%s\n",expectedStarts,localStarts,s_starting,s_stopping,RemoteImuRecording::configured(),RemoteImuRecording::prepared(),RemoteImuRecording::failed(),worker.recording(),uiStatus.c_str(),RemoteImuRecording::failureReason());for(unsigned n=0;n<fixtureSensorCount;++n){AcquisitionControl::Outcome o;AcquisitionControl::outcome(n,o);std::fprintf(stderr,"node%u result%u action%u reason%u phase%u record%llu epoch%llu\n",n,unsigned(o.result),unsigned(o.action),o.reason,acquisitions[n].phase,(unsigned long long)acquisitions[n].recording,(unsigned long long)peerFixture(n).view.endpoint_epoch[0]);}}
 assert(s_running && !s_starting && localStarts==expectedStarts && worker.recording() && !RemoteImuRecording::failed());
 for(unsigned n=0;n<fixtureSensorCount;++n) assert(acquisitions[n].phase==3 && acquisitions[n].lease_valid);
}
static void feedWire(const char* path,unsigned pacing=40,uint8_t liveMask=0x0f) {
 std::ifstream input(path);assert(input);unsigned id,length,frameNumber=0;std::string hex;
 while(input>>id>>length>>hex) {
   assert(length<=64 && hex.size()==length*2);uint8_t payload[64]={};
   for(unsigned i=0;i<length;++i) payload[i]=std::stoul(hex.substr(i*2,2),nullptr,16);
   if(pacing<40 && id!=0x100) step(80); // preserve essential definitions under deliberate overload
   for(uint8_t n=0;n<fixtureSensorCount;++n) {
     if(!(liveMask&(1u<<n))) continue;
     uint8_t nodePayload[64];std::memcpy(nodePayload,payload,sizeof payload);
     // Distinct source axes make accidental source substitution observable.
     if(ImuAdmission::sampleUnitBenchBuild() && n>0 && id==0x100) {
       const uint16_t sourceAx[]={0,4660,9029,13398};
       for(unsigned i=0;i<(payload[3]&7);++i) BdqV2Format::putU16(nodePayload+4+12*i,sourceAx[n]);
     }
     const bool accepted=bodaqs_master_service_receive_can(&master,n,id==0x100?1:2,id+(id==0x100?8*n:n),nodePayload,length,0,clockMs*1000,clockMs);
     if(id==0x100) {
       std::fprintf(inputLedger,"%u\t%u\t%u\t%u\t%u\n",n,unsigned(payload[2]),unsigned(BdqV2Format::getU16(payload)),unsigned(payload[3]&7),unsigned(accepted));
       if(!accepted) rejectedSamples[n]+=payload[3]&7;
     }
     if(!accepted) {
       if(pacing==40 || id!=0x100) {std::fprintf(stderr,"CAN input rejected: t%u node%u id%x ingress%u\n",clockMs,n,id,master.ingress[n].count);assert(false);}
     }
   }
   if(pacing==40 && ++frameNumber==20) {
     // Drop full-duplex replies while live receptions and retained fragments
     // exist. Fresh same-boot status must resume their immutable identities.
     loseMeasurementReplies=true;step(40);loseMeasurementReplies=false;
   }
   // WINDOW_SAMPLE_SERVICE
   step(pacing);
   for(uint8_t n=0;n<fixtureSensorCount;++n) if(liveMask&(1u<<n)) {
     RemoteImuRecording::Failure failure;
     assert(!RemoteImuRecording::failure(n,failure));
   }
 }
 step(100);
}
static void awaitFinalized(unsigned expectedFinalizations=1) {
 for(unsigned i=0;i<20000 && s_stopping;++i) step(1);
 assert(!s_stopping && !worker.pending() && !AcquisitionControl::active() && !RemoteImuRecording::configured());
 assert(finalizations==expectedFinalizations && !LoggingManager::configurationLocked());
}
int main(int argc,char** argv) {
 assert(argc==4);storage.path=argv[2];setup();const std::string scenario=argv[3];
 if(scenario=="allocation") {
   assert(ImuAdmission::fourNodeSampleUnitBenchBuild());
   const auto before=DynamicSpscQueueDetail::liveAllocations;
   DynamicSpscQueueDetail::allocationsBeforeFailure=15;
   assert(RemoteImuRecording::configure(config));
   assert(RemoteImuRecording::admission().reason==ImuAdmission::Reason::Allocation);
   assert(!RemoteImuRecording::configured() && !AcquisitionControl::active());
   assert(DynamicSpscQueueDetail::liveAllocations==before);
   for(unsigned n=0;n<fixtureSensorCount;++n)
     assert(!acquisitions[n].recording && !acquisitions[n].lease_valid);
   DynamicSpscQueueDetail::allocationsBeforeFailure=-1;
   puts("Four-source partial allocation failure: all buffers retired before remote authorization PASS");return 0;
 }
 const std::string ledgerPath=std::string(argv[2])+".input.tsv";inputLedger=std::fopen(ledgerPath.c_str(),"w");assert(inputLedger);
 const std::string controlPath=std::string(argv[2])+".control.tsv";controlLedger=std::fopen(controlPath.c_str(),"w");assert(controlLedger);
 if(scenario=="cancel-open" || scenario=="cancel-prepare") {
   serviceStorage=false;
   assert(LoggingManager::requestStart()==LoggingManager::StartResult::Pending);
   while(!s_remotePreparing) step(1);
   if(scenario=="cancel-open") {
     storage.blockOperation=1;storage.blocked=true;
     std::thread opening([] {worker.step(clockMs);});
     while(!storage.entered.load()) std::this_thread::yield();
     LoggingManager::cancelStart();step(100);
     assert(s_stopping && !localStarts && worker.pending());
     assert(LoggingManager::requestStart()==LoggingManager::StartResult::Failed);
     for(unsigned n=0;n<fixtureSensorCount;++n) assert(!acquisitions[n].recording);
     storage.blocked=false;opening.join();
   } else {
     delayNodeZero=true;worker.step(clockMs);
     for(unsigned i=0;i<2000 && !acquisitions[0].recording;++i) step(1);
     assert(acquisitions[0].recording && !s_running && !localStarts);
     LoggingManager::cancelStart();step(200);delayNodeZero=false;
     assert(s_stopping && !localStarts);
   }
   serviceStorage=true;awaitFinalized();
   for(unsigned n=0;n<fixtureSensorCount;++n) assert(!acquisitions[n].recording && !acquisitions[n].lease_valid);
   assert(!localStarts && localStops==1 && storage.healthChecks==1);
   assert(std::fclose(inputLedger)==0);assert(std::fclose(controlLedger)==0);puts("Integrated operator cancellation, storage ownership and lease cleanup: PASS");return 0;
 }
 // SHARED_METADATA_RETIREMENT_CASES
 awaitRunning();if(ImuAdmission::singleNodeSmokeBuild()) step(4200);localRow();
 std::thread writing;
 if(scenario=="stall") {
   serviceStorage=false;storage.blockOperation=2;storage.blocked=true;
   writing=std::thread([] {worker.step(clockMs);});
   while(!storage.entered.load()) std::this_thread::yield();
   const auto before=renewalSequence[0];
   feedWire(argv[1],0);
   step(4200);assert(renewalSequence[0]>=before+3 && !RemoteImuRecording::failed());
   localRow(); // local producer retains a new row while the owner is still blocked
 } else {
   feedWire(argv[1]);
 }
 assert(droppedDataAcks==1);
 if(scenario=="short") {
   localRow();storage.shortNext=true;worker.step(clockMs);
   assert(StorageManager_storageFault() && storage.writer.failed());
 }
 const uint32_t stopAt=clockMs;
 const uint64_t oldContext=master.measurement.mode.context;
 const uint64_t oldSession=master.measurement.mode.session;
 const uint64_t oldRecording=master.measurement.mode.recording;
 LoggingManager::stop(scenario=="short"?LoggingManager::StopReason::StorageFailure:LoggingManager::StopReason::UserRequest,"operator");
 assert(!s_running && s_stopping && LoggingManager::configurationLocked());
 assert(LoggingManager::requestStart()==LoggingManager::StartResult::Failed);
 step(200);for(unsigned n=0;n<fixtureSensorCount;++n) assert(acquisitions[n].terminal && !acquisitions[n].lease_valid);
 assert(s_stopping && clockMs-stopAt<5000);
 if(scenario=="stall") {
   assert(worker.pending() && !storage.cleanClosed);
   assert(LoggingManager::requestStart()==LoggingManager::StartResult::Failed);
   worker.poll(clockMs);assert(!StorageManager_storageFault());
   storage.blocked=false;writing.join();serviceStorage=true;
 }
 awaitFinalized();
 assert(localStops==1 && storage.cleanClosed==(scenario!="short"));
 for(unsigned n=0;n<fixtureSensorCount;++n) assert(maxRenewalGap[n]<1500 && renewalSequence[n]>3);
 assert(uiStatus==(scenario=="short"?"Storage failure":"Recording finalized"));
 assert(std::fclose(inputLedger)==0);
 const uint32_t recordingGaps[4]={maxRenewalGap[0],maxRenewalGap[1],maxRenewalGap[2],maxRenewalGap[3]};
 const std::string resultPath=std::string(argv[2])+".runtime.json";FILE* result=std::fopen(resultPath.c_str(),"w");assert(result);
 std::fprintf(result,"{\"scenario\":\"%s\",\"host_only_schedule\":true,\"service_turns_per_tick\":12,\"spi_slots_per_injected_ms\":10,\"renewal_gap_ms\":[%u,%u,%u,%u],\"stop_terminal_verified_within_ms\":200,\"clean_close\":%s,\"rejected_source_samples\":[%u,%u,%u,%u]}\n",scenario.c_str(),recordingGaps[0],recordingGaps[1],recordingGaps[2],recordingGaps[3],storage.cleanClosed?"true":"false",rejectedSamples[0],rejectedSamples[1],rejectedSamples[2],rejectedSamples[3]);
 assert(std::fclose(result)==0);
 // Completed old identities cannot authorize a successor. Only another
 // explicit operator start can create fresh membership and a storage owner.
 if(scenario=="good" || scenario=="short") {
   const BodaqsControlRecord stale=firstStarts[0];BodaqsControlRecord reply={};
   assert(stale.opcode==0x24 && stale.session==oldSession && stale.node_boot_id==17 && stale.data_length==24);
   assert(bodaqs_control_get_u64(stale.data)==oldRecording && bodaqs_control_get_u64(stale.data+8) && bodaqs_control_get_u64(stale.data+16));
   assert(dispatchControl(0,stale,reply));assert(reply.opcode==127 || reply.data[0]>=4);
   // Acquisition deliberately changes endpoint epochs. Let the production
   // idle observer reconcile that new configuration-effective state before
   // the next explicit start, as in the baseline lifecycle regression.
   advance(12000);
   for(unsigned wait=0;wait<300000;++wait) {
     bool ready=true;for(unsigned n=0;n<fixtureSensorCount;++n) ready&=CanMasterManager::configurationReconciled(n);
     if(ready) break;
     advance(1);
   }
   for(unsigned n=0;n<fixtureSensorCount;++n) assert(CanMasterManager::configurationReconciled(n));
   std::fill(std::begin(lastRenewal),std::end(lastRenewal),0);
   std::fill(std::begin(maxRenewalGap),std::end(maxRenewalGap),0);
   const std::string restarted=std::string(argv[2])+".restart.bdq";storage.path=restarted.c_str();
   storage.blockOperation=0;storage.entered=false;storage.cleanClosed=false;
   awaitRunning();assert(storage.healthChecks==2 && !StorageManager_storageFault() && master.measurement.mode.context!=oldContext && master.measurement.mode.recording!=oldRecording);
   // Replay the exact earlier valid authorization, including its original
   // revision/epoch, against the fresh recording. Rejection cannot be credited
   // merely to an invented malformed payload.
   assert(dispatchControl(0,stale,reply));assert(reply.opcode==127 || reply.data[0]>=4);
   assert(acquisitions[0].recording==2 && acquisitions[0].phase==3 && acquisitions[0].lease_valid);
   uint8_t request[BODAQS_MEASUREMENT_BYTES],response[BODAQS_MASTER_TRANSFER_BYTES];BodaqsMeasurementSlot old={};old.kind=1;old.node=0;old.context=oldContext;old.body[0]=1;
   assert(bodaqs_measurement_encode(&old,request,BODAQS_MEASUREMENT_BYTES));
   assert(bodaqs_master_service_process_transfer(&master,request,BODAQS_MEASUREMENT_BYTES,clockMs,response)==BODAQS_MASTER_SLOT_PROCESSED);
   BodaqsMeasurementSlot rejected={};assert(bodaqs_measurement_decode(response,BODAQS_MEASUREMENT_BYTES,&rejected));assert(rejected.kind==7);
   assert(s_running && !RemoteImuRecording::failed());step(500);assert(!RemoteImuRecording::failed());localRow();
   LoggingManager::stop(LoggingManager::StopReason::UserRequest,"explicit_restart_stop");awaitFinalized(2);
   assert(storage.cleanClosed && localStarts==2 && localStops==2);
 }
 assert(std::fclose(controlLedger)==0);
 std::printf("Integrated operator/four-node/recovery/ACK retry/writer/storage: PASS; renewal gaps %u %u %u %u ms\n",recordingGaps[0],recordingGaps[1],recordingGaps[2],recordingGaps[3]);
}

