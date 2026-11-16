"""Real acquisition owner, transport and master: ordinary fetch scheduling seam."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
from test_remote_imu_lifecycle_runtime import fixture_source

p=argparse.ArgumentParser();p.add_argument('--compiler',default='g++');p.add_argument('--scenario');p.add_argument('--interval',type=int,choices=(0,20),default=20);p.add_argument('--control-state',action='store_true');p.add_argument('--acquisition-profile',action='store_true');a=p.parse_args()
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
static uint8_t heldOrdinaryNode;static uint16_t heldOrdinaryTransaction;
static BodaqsControlRecord heldOrdinaryRequest;
namespace SharedSpiBus {''',1)
fixture=fixture.replace('if(holdControl(address,request)) return true;', '''if(holdControl(address,request)) return true;
  if(holdOrdinaryReply && request.opcode==0x28){
   ordinaryHeld=true;heldOrdinaryRequest=request;heldOrdinaryNode=address;heldOrdinaryTransaction=transaction;return true;
  }''')
fixture=fixture.replace(' if(!spiAvailable) return false;', ''' if(!spiAvailable) return false;
 if(length==BODAQS_MEASUREMENT_BYTES) {BodaqsMeasurementSlot r={};assert(bodaqs_measurement_decode_request(tx,length,&r));capturedSchedule.push_back(r);wireJournal.insert(wireJournal.end(),tx,tx+length);}''',1)
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
 }
#endif
 printf("Actual512 logger/master ordinary-fetch %s: PASS\n",scenario.c_str());
}
'''
sources=[*common.glob('bodaqs_control*.c'),common/'bodaqs_imu_disabled.c',common/'bodaqs_master_service.c',common/'bodaqs_master_protocol.c']
sources += [root/'src'/n for n in ('CanMasterProtocol.cpp','SensorAssignment.cpp','SensorParams.cpp','Lsm6dso32xConfig.cpp','RemoteImuStream.cpp','BdqV2Catalog.cpp','ImuAdmission.cpp')]
with tempfile.TemporaryDirectory(prefix='bodaqs-ordinary-fetch-') as tmp:
    cpp=Path(tmp)/'fixture.cpp';exe=Path(tmp)/'fixture.exe';cpp.write_text('#include <cstdlib>\n'+fixture,encoding='utf-8')
    scenarios=[a.scenario] if a.scenario else ['ack-only','lost-ack','pending','wrap','fair','new-command','new-scope','partial','blocked','protected','no-data','periodic0','periodic1','timeout']
    saved={}
    for enabled in ([False,True] if a.control_state else [False]):
        subprocess.run([a.compiler,'-std=c++17',f'-DBODAQS_ACQUISITION_PROFILE={int(enabled and a.acquisition_profile)}', *(['-DBODAQS_STORAGE_TIMELINE=1','-DBODAQS_RECORDING_PRESSURE_DIAGNOSTICS=1','-DBODAQS_IMU_FLOW_DIAGNOSTICS=1',f'-DBODAQS_CONTROL_POLL_DIAGNOSTICS={int(enabled)}'] if a.control_state else []), '-DBODAQS_SPI_MEASUREMENT_V4=1','-DBODAQS_SPI_BULK_BYTES=512',
        '-DBODAQS_RECLAIM_IDLE_CONTROL_FETCH=1',f'-DBODAQS_ORDINARY_FETCH_INTERVAL_MS={a.interval}',
        '-ffunction-sections','-Wl,--gc-sections','-Wall','-Wextra','-Werror','-Wno-class-memaccess','-Wno-unused-function',
        '-I',str(root/'test/stubs'),'-I',str(root/'src'),'-I',str(common),'-I',str(root/'can-fd/common/test'),
            str(cpp),*map(str,sources),'-o',str(exe)],check=True)
        for scenario in scenarios:
            journal=Path(tmp)/f'{scenario}.bin'
            subprocess.run([str(exe),scenario],env=dict(os.environ,BODAQS_SCHEDULE_OUT=str(journal)),check=True)
            data=journal.read_bytes()
            if enabled:assert data==saved[scenario],f'Diagnostic changed MOSI schedule: {scenario}'
            else:saved[scenario]=data
    if a.control_state:print('All selected scenarios: complete MOSI bytes/order unchanged with control observer enabled PASS')
