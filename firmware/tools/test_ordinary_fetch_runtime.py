"""Real acquisition owner, transport and master: ordinary fetch scheduling seam."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
from test_remote_imu_lifecycle_runtime import fixture_source

p=argparse.ArgumentParser();p.add_argument('--compiler',default='g++');p.add_argument('--scenario');p.add_argument('--interval',type=int,choices=(0,20),default=20);p.add_argument('--control-state',action='store_true');p.add_argument('--acquisition-profile',action='store_true');p.add_argument('--transport-profile',action='store_true');p.add_argument('--block-crc',action='store_true');p.add_argument('--fast-request-build',action='store_true');p.add_argument('--poison-auto-vars',action='store_true');a=p.parse_args()
if a.transport_profile and not a.acquisition_profile:p.error('--transport-profile requires --acquisition-profile')
if a.acquisition_profile and not a.control_state:p.error('--acquisition-profile requires --control-state')
if a.control_state and a.interval!=20:p.error('--control-state requires ordinary20')
root=Path(__file__).resolve().parents[1];common=root/'can-fd/common/protocol'
fixture=fixture_source(root).replace('static ParamStore extraParams[7];','[[maybe_unused]] static ParamStore extraParams[7];')
fixture=fixture.replace('bodaqs_measurement_decode(tx,','bodaqs_measurement_decode_request(tx,')
fixture=fixture.replace('bodaqs_measurement_encode(&ackSlot,lostAckReplacement,','bodaqs_measurement_encode_request(&ackSlot,lostAckReplacement,')
fixture=fixture.replace('memcpy(rx,lostAckReplacement,BODAQS_MEASUREMENT_BYTES);','assert(bodaqs_measurement_encode(&ackSlot,rx,BODAQS_MEASUREMENT_BYTES));')
fixture=fixture.replace('namespace SharedSpiBus {', '''static std::vector<uint8_t> wireJournal;
static std::vector<BodaqsMeasurementSlot> capturedSchedule;
static bool holdOrdinaryReply=false,ordinaryHeld=false;
static bool forceProfileReply=false;
static BodaqsMeasurementSlot forcedProfileReply={};
static uint8_t heldOrdinaryNode;static uint16_t heldOrdinaryTransaction;
static BodaqsControlRecord heldOrdinaryRequest;
namespace SharedSpiBus {''',1)
fixture=fixture.replace('if(holdControl(address,request)) return true;', '''if(holdControl(address,request)) return true;
  if(holdOrdinaryReply && request.opcode==0x28){
   ordinaryHeld=true;heldOrdinaryRequest=request;heldOrdinaryNode=address;heldOrdinaryTransaction=transaction;return true;
  }''')
fixture=fixture.replace(' if(!spiAvailable) return false;', ''' if(!spiAvailable) return false;
 if(length==BODAQS_MEASUREMENT_BYTES) {BodaqsMeasurementSlot r={};assert(bodaqs_measurement_decode_request(tx,length,&r));capturedSchedule.push_back(r);wireJournal.insert(wireJournal.end(),tx,tx+length);}
 if(forceProfileReply && length==BODAQS_MEASUREMENT_BYTES) return bodaqs_measurement_encode(&forcedProfileReply,rx,length);''',1)
fixture+=r'''
static bool consumeSchedule(uint8_t,uint8_t,uint32_t,const uint8_t*,uint16_t){return false;}
static unsigned fetchClass(const BodaqsMeasurementSlot& r){return r.kind==15?1:r.kind==14?r.body[2]:r.kind==1?r.body[0]:0;}
static void acceptedControl(unsigned n) {
 auto& in=AcquisitionControl::transport.inboxes[2][n];in={};
 assert(bodaqs_fragment_seal(&in.state,in.bytes,sizeof in.bytes,456,71,n,3,1,64));
 in.admitted=true;in.ackPending=true;CanMasterManager::rememberMeasurementAcknowledgement(in);
 master.lanes[0][n].tx=in.state;
}
static BodaqsMeasurementSlot turn(unsigned cursorValue=0){
 AcquisitionControl::serviceCursor=3;AcquisitionControl::cursor=cursorValue;
 capturedSchedule.clear();AcquisitionControl::service();assert(capturedSchedule.size()==1);return capturedSchedule.back();
}
int main(int argc,char** argv){
 assert(argc==2);const std::string scenario=argv[1];reset();fixedMeasurementClock=true;
 CanMasterManager::beginRecordingHandoff();
 for(unsigned i=0;i<5500 && !CanMasterManager::recordingHandoffReady();++i)advance(1);
 assert(CanMasterManager::recordingHandoffReady());
#if BODAQS_CONTROL_POLL_DIAGNOSTICS
 RecordingTimelineDiagnostics::resetStorage(micros());
 ControlPollingDiagnostics::resetStorage(RecordingTimelineDiagnostics::storage.originUs);
#endif
 assert(AcquisitionControl::setDataConsumer(consumeSchedule,3));assert(AcquisitionControl::begin(123,456));
 for(unsigned i=0;i<100 && !CanMasterManager::measurementReady();++i)AcquisitionControl::service();
 assert(CanMasterManager::measurementReady());
 using namespace AcquisitionControl;
 transport.bridgeNext=clockMs+10000;nextHealthObservation=clockMs+10000;dataCursor=0;
 if(scenario=="ack-only" || scenario=="lost-ack"){
  const unsigned ackNode=scenario=="lost-ack"?0:3;
  acceptedControl(ackNode);const auto expected=transport.inboxes[2][ackNode].pendingAck;
  if(scenario=="lost-ack")dropOrdinaryControlAck=true;
  const auto r=turn();assert(r.kind==14 && r.body[0]==3 && r.node==ackNode && r.object==71);
  assert(r.context==expected.context && r.total==expected.total && !memcmp(r.body+4,expected.body+4,4));
  assert(r.body[2]==1 && "An ordinary ACK alone must not force another control fetch");
  assert(transport.inboxes[2][ackNode].ackPending); // Sending is never retirement proof.
  turn();
  if(scenario=="lost-ack"){
   assert(transport.inboxes[2][ackNode].ackPending && droppedControlAcks==1);
   turn();
  }
  assert(!transport.inboxes[2][ackNode].ackPending); // Real master proof returned on MISO.
#if BODAQS_ORDINARY_FETCH_INTERVAL_MS
  assert(!transport.ordinaryFetchSeen); // Sample fetch half does not consume ordinary poll budget.
#endif
 }else if(scenario=="pending" || scenario=="wrap" || scenario=="fair"){
  if(scenario=="wrap"){
   clockMs=UINT32_MAX-5;transport.bridgeNext=clockMs+10000;nextHealthObservation=clockMs+10000;
   for(unsigned c=0;c<2;++c)for(unsigned n=0;n<4;++n)transport.nextHeadPollMs[c][n]=clockMs-1;
  }
  peers[0].ordinary.pending=true;peers[0].ordinary.started=clockMs;
  if(scenario=="fair"){peers[2].ordinary.pending=true;peers[2].ordinary.started=clockMs;}
  auto r=turn();assert(fetchClass(r)==3);const unsigned first=r.node;
  r=turn();
  if(scenario=="fair")assert(fetchClass(r)==3 && r.node!=first);
  else assert(fetchClass(r)==1 && "Repeated not-ready ordinary fetch must yield to sample fetch");
  unsigned polls=1+(scenario=="fair"?1:0);
  for(unsigned i=1;i<20;++i){++clockMs;r=turn();polls+=fetchClass(r)==3;}
  assert(polls==(scenario=="fair"?2U:1U));
  ++clockMs;r=turn();assert(fetchClass(r)==3); // Due exactly at20ms including wrap.
 }else if(scenario=="new-command"){
#if BODAQS_ORDINARY_FETCH_INTERVAL_MS
  peers[0].ordinary.pending=true;peers[0].ordinary.started=clockMs;
  assert(fetchClass(turn())==3);assert(transport.ordinaryFetchSeen&1);
  const auto q=request(0,3,allocate(nextRead));
  servicing=true;
  const auto object=CanMasterManager::nextMeasurementObjectId(3,0);
  assert(CanMasterManager::queueMeasurementControl(transport,q,object,false));servicing=false;
  assert(!(transport.ordinaryFetchSeen&1));
  transport.ordinaryFetchSeen|=1;transport.ordinaryFetchMs[0]=clockMs;
  servicing=true;assert(CanMasterManager::queueMeasurementControl(transport,q,object,false));servicing=false;
  assert(transport.ordinaryFetchSeen&1); // Identical requeue must not reset the budget.
  assert(turn().kind==4); // A queued command is transmitted immediately, not paced as a result fetch.
#endif
 }else if(scenario=="periodic0" || scenario=="periodic1"){
  alternateRxLoss=true;physicalSlots=scenario=="periodic0"?0:1;
  holdOrdinaryReply=true;
  AcquisitionControl::Request query;query.node=0;query.recording=123;query.action=Action::Snapshot;
  assert(AcquisitionControl::enqueue(query));
  bool completed=false;unsigned elapsed=0;
  for(;elapsed<3400;++elapsed){
   if(elapsed==37){
    assert(ordinaryHeld);holdOrdinaryReply=false;BodaqsControlRecord reply;
    assert(dispatchControl(heldOrdinaryNode,heldOrdinaryRequest,reply));
    assert(bodaqs_master_service_control_receive(&master,heldOrdinaryNode,heldOrdinaryTransaction,&reply));
   }
   ++clockMs;AcquisitionControl::service();
   Outcome out;assert(AcquisitionControl::outcome(0,out));
   if(out.serial && out.result!=Result::Pending && out.result!=Result::Idle){
    assert(out.result==Result::Rejected); // Real node rejects unsupported snapshot, must reach logger.
    completed=true;break;
   }
  }
  assert(completed && "Ordinary result must arrive despite alternating dropped SPI requests");
  printf("Periodic RX loss result latency %u ms\n",elapsed);
 }else if(scenario=="new-scope"){
#if BODAQS_ORDINARY_FETCH_INTERVAL_MS
  transport.ordinaryFetchSeen=15;for(auto& stamp:transport.ordinaryFetchMs)stamp=clockMs;
  assert(AcquisitionControl::requestExit());
  for(unsigned i=0;i<100 && AcquisitionControl::active();++i){++clockMs;AcquisitionControl::service();}
  assert(!AcquisitionControl::active());
  assert(AcquisitionControl::begin(124,457));
  assert(!transport.ordinaryFetchSeen);for(auto stamp:transport.ordinaryFetchMs)assert(!stamp);
#endif
 }else if(scenario=="partial" || scenario=="blocked"){
  peers[0].ordinary.pending=true;peers[0].ordinary.started=clockMs;
  assert(fetchClass(turn())==3);
  auto& result=transport.inboxes[2][0];result.state.context=456;result.state.object=71;
  result.state.cls=3;result.state.node=0;result.state.total=1024;result.state.mask=1;
  if(scenario=="blocked"){result.state.complete=1;result.admitted=false;}
  assert(fetchClass(turn())==3); // Never pace known partial/unaccepted result work.
 }else if(scenario=="protected"){
  peers[1].protectedLane.pending=true;peers[1].protectedLane.started=clockMs;
  for(unsigned i=0;i<10;++i)assert(fetchClass(turn())==4);
 }else if(scenario=="timeout"){
  peers[0].ordinary.pending=true;peers[0].ordinary.started=clockMs-3500U;peers[0].observing=true;
  turn();assert(!peers[0].ordinary.pending && !peers[0].observing);
 }else if(scenario=="request-build"){
  const auto owner=CanMasterManager::s_measurementOwner.load();
  CanMasterManager::s_measurementOwner.store(+[]{return true;});
  forceProfileReply=true;forcedProfileReply={};forcedProfileReply.context=456;
  CanMasterManager::MeasurementTransport probe;
  auto init=[&]{probe={};probe.context=456;probe.sampleNodes=15;probe.bridgeNext=clockMs+10000;};
  CanMasterManager::MeasurementInbox* completed=nullptr;
  // A later timeout must still win after an outgoing candidate was selected.
  init();
  for(unsigned n:{0U,2U}) {
   auto& out=probe.controls[1][n];out.bytes[12]=0x25;
   assert(bodaqs_fragment_seal(&out.state,out.bytes,sizeof out.bytes,456,n+1,n,4,0,64));
   out.startedMs=n?clockMs-300:clockMs;
  }
  const auto before=capturedSchedule.size();
  assert(CanMasterManager::serviceMeasurementTransport(probe,1,0,completed)==-12);
  assert(capturedSchedule.size()==before && probe.nextControlNode[1]==1 && probe.controls[1][0].nextFragment==1);
  assert(!probe.controls[1][2].state.complete && probe.controls[1][2].error==12);
  // Deterministic request-selector state matrix. Raw empty MISO uses the real
  // outer codec, while existing integrated tests exercise actual control peers.
  uint32_t seed=0x35202611U;
  auto random=[&]{seed^=seed<<13;seed^=seed>>17;seed^=seed<<5;return seed;};
  auto journal=[&](uint32_t v){for(unsigned b=0;b<4;++b)wireJournal.push_back((uint8_t)(v>>(8*b)));};
  for(unsigned turn=0;turn<512;++turn) {
   init();probe.nextSampleAck=random()%16;probe.nextEvidenceAck=random()%4;
   probe.sampleAckBurst=random()%5;probe.evidenceAckRepeat=random()%2;
   for(unsigned cls=1;cls<=5;++cls)for(unsigned n=0;n<(cls==5?1U:4U);++n) {
    const unsigned slots=cls==1?4:1;
    for(unsigned slot=0;slot<slots;++slot) {
     auto& in=cls==1?CanMasterManager::sampleWindowInbox(probe,n,slot):probe.inboxes[cls-1][n];
     in.state.context=456;in.state.object=slot+1;in.state.node=cls==5?255:n;
     in.state.cls=cls;in.state.direction=1;in.state.total=cls==1?84:cls==2?96:cls==5?28:68;
     in.state.checksum=random();in.state.complete=random()%2;
     in.state.mask=in.state.complete?1:0;in.admitted=random()%2;
     in.ackPending=random()%3==0;in.requestedFragments=random()%2;
     CanMasterManager::rememberMeasurementAcknowledgement(in);
    }
   }
   for(unsigned lane=0;lane<2;++lane) {
    probe.nextControlNode[lane]=random()%4;
    for(unsigned n=0;n<4;++n)if(random()%4==0) {
     auto& out=probe.controls[lane][n];out.bytes[12]=(lane && random()%2)?0x25:0x21;
     assert(bodaqs_fragment_seal(&out.state,out.bytes,sizeof out.bytes,456,1,n,lane+3,0,64));
     out.startedMs=clockMs-(random()%310);out.nextFragment=random()%4;
    }
   }
   const unsigned cls=random()%5+1,node=cls==5?255:random()%4;
   journal((uint32_t)CanMasterManager::serviceMeasurementTransport(probe,cls,node,completed));
   journal(probe.nextSampleAck);journal(probe.nextEvidenceAck);journal(probe.sampleAckBurst);journal(probe.evidenceAckRepeat);
   journal(probe.ordinaryFetchSeen);journal(probe.nextControlNode[0]);journal(probe.nextControlNode[1]);
   for(const auto& lane:probe.controls)for(const auto& out:lane){journal(out.state.complete);journal(out.nextFragment);journal(out.error);}
   for(const auto& lane:probe.inboxes)for(const auto& in:lane)journal(in.requestedFragments);
   for(const auto& lane:probe.sampleExtra)for(const auto& in:lane)journal(in.requestedFragments);
   for(auto stamp:probe.ordinaryFetchMs)journal(stamp);
   for(const auto& lane:probe.nextHeadPollMs)for(auto stamp:lane)journal(stamp);
  }
  forceProfileReply=false;CanMasterManager::s_measurementOwner.store(owner);
 }else if(scenario=="profile-paths"){
  // Real transport and codecs, with controlled raw MISO at the physical seam.
  // The same operations also run with diagnostics off for MOSI equivalence.
  const auto owner=CanMasterManager::s_measurementOwner.load();
  CanMasterManager::s_measurementOwner.store(+[]{return true;});
  CanMasterManager::MeasurementTransport probe;
  unsigned profileStep=0;
  auto& diagnosticState=const_cast<CanMasterManager::Diagnostics&>(CanMasterManager::diagnostics());
  const bool confirmed=diagnosticState.measurementConfirmed;
  const bool unavailable=diagnosticState.measurementUnavailable;
  auto initialize=[&]{probe={};probe.context=456;probe.timingEnabled=true;probe.sampleNodes=15;probe.bridgeNext=clockMs+10000;
   diagnosticState.measurementConfirmed=confirmed;diagnosticState.measurementUnavailable=unavailable;};
  auto invoke=[&](uint8_t cls,int expected,unsigned requestCount,unsigned exchangeCount,unsigned responseCount,unsigned fragmentCount){
#if BODAQS_TRANSPORT_PROFILE
   auto calls=[](unsigned stage){uint32_t count=0;for(unsigned i=0;i<ControlPollingDiagnostics::capacity;++i)count+=ControlPollingDiagnostics::profileAt(i).calls[stage];return count;};
   uint32_t before[4];for(unsigned i=0;i<4;++i)before[i]=calls(12+i);
#else
   (void)requestCount;(void)exchangeCount;(void)responseCount;(void)fragmentCount;
#endif
   CanMasterManager::MeasurementInbox* completed=nullptr;
   const int result=CanMasterManager::serviceMeasurementTransport(probe,cls,0,completed);
   ++profileStep;if(result!=expected)std::fprintf(stderr,"Profile step %u: result %d expected %d\n",profileStep,result,expected);
   assert(result==expected);
   if(result<0)assert(!completed);
#if BODAQS_TRANSPORT_PROFILE
   const unsigned want[4]={requestCount,exchangeCount,responseCount,fragmentCount};
   for(unsigned i=0;i<4;++i)assert(calls(12+i)-before[i]==want[i]);
#endif
  };
  initialize();probe.nextHeadPollMs[1][0]=clockMs+20;
  invoke(2,0,1,0,0,0); // Deferred empty evidence probe.
  initialize();probe.controls[0][0].state.complete=1;probe.controls[0][0].startedMs=clockMs-300;
  invoke(3,-12,1,0,0,0); // Outgoing control expired before any physical exchange.
  initialize();spiAvailable=false;
  invoke(1,0,1,1,1,0);assert(probe.recovering);spiAvailable=true;
  forceProfileReply=true;forcedProfileReply={};forcedProfileReply.context=456;
  invoke(1,0,1,1,1,0);assert(probe.recovering); // Empty response to recovery query.
  probe.recoveryStarted=clockMs-300;
  invoke(1,-14,1,0,0,0); // Expired recovery exits in request preparation.
  initialize();
  BodaqsFragmentState sealed={};uint8_t bytes[68]={};
  assert(bodaqs_fragment_seal(&sealed,bytes,sizeof bytes,456,1,0,3,1,64));
  assert(bodaqs_fragment_emit(&sealed,bytes,0,&forcedProfileReply));
  invoke(3,1,1,1,1,1); // Production fragment assembly and object checksum.
  invoke(3,1,1,1,1,1); // Duplicate object remains unadmitted; still classify validation.
  initialize();forcedProfileReply.body[0]^=1; // Outer CRC regenerated, logical CRC invalid.
  invoke(3,-14,1,1,1,1);assert(probe.failed && !probe.inboxes[2][0].ackPending);
  forceProfileReply=false;CanMasterManager::s_measurementOwner.store(owner);
 }else if(scenario=="no-data"){
  peers[0].ordinary.pending=true;peers[0].ordinary.started=clockMs;dataConsumer=nullptr;
  for(unsigned i=0;i<5;++i)assert(fetchClass(turn(8))==3); // No data opportunity, keep drain turns.
 }else assert(false);
#if BODAQS_CONTROL_POLL_DIAGNOSTICS
 if(scenario=="pending") {
   const auto& b=ControlPollingDiagnostics::acquisition->bins[0];
   assert(b.reasons[ControlPollingDiagnostics::PendingFirst]>=1 && b.reasons[ControlPollingDiagnostics::PendingDue]>=1);
 }
 if(scenario=="periodic0" || scenario=="periodic1" || scenario=="timeout"){
   uint32_t begins=0,matched=0,timeouts=0;
   for(const auto& b:ControlPollingDiagnostics::acquisition->bins){begins+=b.begins[0];matched+=b.matched[0];timeouts+=b.timeouts[0];}
   if(scenario=="timeout")assert(timeouts==1);
   else assert(begins==1 && matched==1 && timeouts==0);
 }
#endif
 // A maintenance exchange is allowed with no acquisition owner. An old
 // retired diagnostic bank may still exist; it must remain immutable.
 if(scenario=="periodic0" || scenario=="periodic1") {
  const auto oldOwner=CanMasterManager::s_measurementOwner.load();
  CanMasterManager::s_measurementOwner.store(nullptr);
#if BODAQS_ACQUISITION_PROFILE
  const auto bankBefore=*ControlPollingDiagnostics::acquisition;
  const auto hotBefore=ControlPollingDiagnostics::hotProfile;const auto hotIndexBefore=ControlPollingDiagnostics::hotIndex;
#endif
  BodaqsMeasurementSlot request={},reply={};request.context=456;request.node=255;
  assert(CanMasterManager::exchangeMeasurementSlot(request,reply));
#if BODAQS_ACQUISITION_PROFILE
  assert(!memcmp(&bankBefore,ControlPollingDiagnostics::acquisition,sizeof bankBefore));
  assert(!memcmp(&hotBefore,&ControlPollingDiagnostics::hotProfile,sizeof hotBefore));assert(hotIndexBefore==ControlPollingDiagnostics::hotIndex);
#endif
  CanMasterManager::s_measurementOwner.store(oldOwner);
 }
 if(const char* path=std::getenv("BODAQS_SCHEDULE_OUT")){
   FILE* f=std::fopen(path,"wb");assert(f);assert(std::fwrite(wireJournal.data(),1,wireJournal.size(),f)==wireJournal.size());std::fclose(f);
 }
#if BODAQS_ACQUISITION_PROFILE
 if(scenario=="periodic0" || scenario=="periodic1") {
  uint32_t service=0,transfer=0;
  for(unsigned i=0;i<ControlPollingDiagnostics::capacity;++i){const auto& p=ControlPollingDiagnostics::profileAt(i);service+=p.calls[ControlPollingDiagnostics::Service];transfer+=p.calls[ControlPollingDiagnostics::Transport];}
  assert(service && transfer);
#if BODAQS_TRANSPORT_PROFILE
  uint32_t request=0,exchange=0,response=0;
  for(unsigned i=0;i<ControlPollingDiagnostics::capacity;++i){const auto& p=ControlPollingDiagnostics::profileAt(i);
   request+=p.calls[ControlPollingDiagnostics::TransportRequest];exchange+=p.calls[ControlPollingDiagnostics::TransportExchange];response+=p.calls[ControlPollingDiagnostics::TransportResponse];}
  assert(request && exchange && response);
  assert(request>=exchange && exchange==response);
#endif
 }
#endif
 printf("Actual512 logger/master ordinary-fetch %s: PASS\n",scenario.c_str());
}
'''
sources=[*common.glob('bodaqs_control*.c'),common/'bodaqs_imu_disabled.c',common/'bodaqs_master_service.c',common/'bodaqs_master_protocol.c']
sources += [root/'src'/n for n in ('CanMasterProtocol.cpp','SensorAssignment.cpp','SensorParams.cpp','Lsm6dso32xConfig.cpp','RemoteImuStream.cpp','BdqV2Catalog.cpp','ImuAdmission.cpp')]
with tempfile.TemporaryDirectory(prefix='bodaqs-ordinary-fetch-') as tmp:
    cpp=Path(tmp)/'fixture.cpp';exe=Path(tmp)/'fixture.exe';cpp.write_text('#include <cstdlib>\n'+fixture,encoding='utf-8')
    scenarios=[a.scenario] if a.scenario else ['ack-only','lost-ack','pending','wrap','fair','new-command','new-scope','partial','blocked','protected','no-data','periodic0','periodic1','timeout']+(['profile-paths'] if a.transport_profile else [])+(['request-build'] if a.fast_request_build else [])
    saved={}
    for fast,enabled in [(fast,enabled) for fast in ([False,True] if a.fast_request_build else [False]) for enabled in ([False,True] if a.control_state else [False])]:
        subprocess.run([a.compiler,'-std=c++17',*(['-ftrivial-auto-var-init=pattern'] if a.poison_auto_vars else []),f'-DBODAQS_REQUEST_BUILD_FAST={int(fast)}',f'-DBODAQS_ACQUISITION_PROFILE={int(enabled and a.acquisition_profile)}',f'-DBODAQS_TRANSPORT_PROFILE={int(enabled and a.transport_profile)}',f'-DBODAQS_MASTER_BLOCK_CRC={int(a.block_crc)}', *(['-DBODAQS_STORAGE_TIMELINE=1','-DBODAQS_RECORDING_PRESSURE_DIAGNOSTICS=1','-DBODAQS_IMU_FLOW_DIAGNOSTICS=1',f'-DBODAQS_CONTROL_POLL_DIAGNOSTICS={int(enabled)}'] if a.control_state else []), '-DBODAQS_SPI_MEASUREMENT_V4=1','-DBODAQS_SPI_BULK_BYTES=512',
        '-DBODAQS_RECLAIM_IDLE_CONTROL_FETCH=1',f'-DBODAQS_ORDINARY_FETCH_INTERVAL_MS={a.interval}',
        '-ffunction-sections','-Wl,--gc-sections','-Wall','-Wextra','-Werror','-Wno-class-memaccess','-Wno-unused-function',
        '-I',str(root/'test/stubs'),'-I',str(root/'src'),'-I',str(common),'-I',str(root/'can-fd/common/test'),
            str(cpp),*map(str,sources),'-o',str(exe)],check=True)
        for scenario in scenarios:
            journal=Path(tmp)/f'{scenario}.bin'
            subprocess.run([str(exe),scenario],env=dict(os.environ,BODAQS_SCHEDULE_OUT=str(journal)),check=True)
            data=journal.read_bytes()
            if enabled or fast:assert data==saved[scenario],f'Diagnostic/optimization changed MOSI/state schedule: {scenario}'
            else:saved[scenario]=data
    if a.control_state:print('All selected scenarios: complete MOSI bytes/order and selected state unchanged across diagnostic/optimization matrix PASS')
