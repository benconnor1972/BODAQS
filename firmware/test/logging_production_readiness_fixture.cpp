// Hardware-facing adapter: observations and failure injection are independent
// of LoggingManager's lifecycle. Shared RecordingReadiness.cpp is inserted below.
namespace ImuAdmission { enum class Reason {None, Allocation}; struct Report {Reason reason=Reason::None;}; }
namespace RemoteImuRecording {
bool enabled=false, prepareDone=false, failedStatus=false, commitFails=false, commitSettled=false, resourceOk=true;
bool remoteStopped=true, sharedFault=false;
uint8_t healthy=0;
ImuAdmission::Report report;
const ImuAdmission::Report& admission() {return report;}
uint8_t healthyNodeMask() {return healthy;}
const char* failureReason() {return "fixture remote failure";}
bool configure(const LoggerConfig& cfg) {
  enabled=false;
  for(uint8_t i=0;i<cfg.sensorCount();++i) {
    SensorSpec spec;cfg.getSensorSpec(i,spec);
    if(sensorAssignment(spec,board::gBoard).kind==SensorAssignment::Kind::NodeImu) enabled=true;
  }
  return true;
}
bool configured() {return enabled;}
bool resourcesReady(size_t=0) {events.push_back("resources");return resourceOk;}
bool prepared() {return prepareDone;}
bool failed() {return failedStatus;}
bool recording() {return !enabled || (prepareDone && (!commitFails || commitSettled));}
bool sharedIntegrityFault() {return sharedFault;}
void start() {
  if(!enabled) return;
  events.push_back("commit");
  if(commitFails) {failedStatus=true;healthy &= ~(1u<<3);}
}
void stop() {events.push_back("remote_stop");remoteStopped=true;}
void service() {}
void release() {enabled=false;}
bool stopped() {return remoteStopped;}
bool tailDrained() {return true;}
bool readyForFileFinalization() {return true;}
}
// REMOTE_END
// Actual readiness module consumes configured slots and external observations.
// It has its own focused runtime fixture; this harness tests its controller seam.
// ACTUAL_READINESS
// PRODUCTION_MAIN
RecordingAdmission::Qualification covered(const LoggerConfig&, uint32_t) {
  return RecordingAdmission::Qualification::Covered;
}
void productionReset(bool qualify=true) {
  reset();
  s_remotePreparing=false;s_remoteFaultShown=false;
  s_storageStartPending=false;s_storageStopRequested=false;
  SensorManager::localAllocationMask=~uint32_t{0};
  SensorManager::syncLimit=0;AnalogInputManager::effectiveRate=0;
  CanMasterManager::availableNodes=0;CanMasterManager::handoffActive=false;
  RemoteImuRecording::enabled=false;RemoteImuRecording::prepareDone=false;
  RemoteImuRecording::failedStatus=false;RemoteImuRecording::commitFails=false;
  RemoteImuRecording::commitSettled=false;RemoteImuRecording::resourceOk=true;RemoteImuRecording::healthy=0;
  RemoteImuRecording::report={};RemoteImuRecording::remoteStopped=true;
  g_cfg.logFormat=LogFormat::BodaqsMultiStreamBinary;
  static RecordingReadiness::QualificationProfile qualification{
    "lifecycle-fixture-only",1,nullptr,RecordingReadiness::kAcquisitionContract,covered};
  qualification.boardProfile=board::gBoard->name;
  check(RecordingReadiness::setQualificationProfile(qualify?&qualification:nullptr));
}
void local(const char* name="local") {add(SensorType::BMI270ImuI2C,name,1,104);}
void remote(uint8_t node) {
  char name[16];snprintf(name,sizeof name,"remote%u",node);
  add(SensorType::LSM6DSO32XImu,name,0,0,false);
  char provider[8];snprintf(provider,sizeof provider,"can:%u",node);
  set(g_cfg.sensorN-1,"provider",provider);
  set(g_cfg.sensorN-1,"endpoint","imu");
  set(g_cfg.sensorN-1,"profile",Lsm6dso32xConfig::profile);
  set(g_cfg.sensorN-1,"domain","frame");
  set(g_cfg.sensorN-1,"end","none");
  CanMasterManager::availableNodes|=1u<<node;
  RemoteImuRecording::healthy|=1u<<node;
}
void settleStop() {
  for(int i=0;i<5;++i) {LoggingManager::loop();storageWorker.step(10000+i);}
  LoggingManager::loop();
  check(!LoggingManager::configurationLocked());
}
void finish() {LoggingManager::stop(LoggingManager::StopReason::UserRequest,"fixture");settleStop();}
void opened() {
  check(!has("acquire"));
  check(RecordingReadiness::session().reservation==RecordingAdmission::Reservation::NotAttempted);
  storageWorker.step(100);
  check(has("file") && !has("acquire"));
  check(RecordingReadiness::session().reservation==RecordingAdmission::Reservation::NotAttempted);
}
int main() {
  // Strict missing hardware refuses before initialization or file creation.
  productionReset();local();add(SensorType::BMI270ImuI2C,"absent",0,105,false);
  check(LoggingManager::requestStart()==LoggingManager::StartResult::Failed);
  check(!has("sensors") && !has("file") && !has("acquire"));
  check(RecordingReadiness::session().decision.excluded==2);

  // Qualification comes only from a fixture callback; a missing callback has
  // candidate behavior solely in the explicitly compiled candidate build.
  productionReset(false);local();
  auto result=LoggingManager::requestStart();
#if BODAQS_UNQUALIFIED_INTEGRATION_CANDIDATE
  check(result==LoggingManager::StartResult::Pending);opened();LoggingManager::loop();
  check(s_running && RecordingReadiness::session().decision.candidate);
  check(!RecordingReadiness::session().decision.qualified);finish();
#else
  check(result==LoggingManager::StartResult::Failed);
  check(!has("file") && !has("acquire"));
#endif
  productionReset();local();
  check(LoggingManager::requestStart()==LoggingManager::StartResult::Pending);
  opened();LoggingManager::loop();
  check(s_running && RecordingReadiness::session().decision.qualified);
  check(RecordingReadiness::session().decision.mayRecord);
  check(index("file")<index("acquire"));finish();

  // Qualified requested geometry cannot silently change under its profile.
  for(bool synchronousLimit:{false,true}) {
    productionReset();local();
    if(synchronousLimit) SensorManager::syncLimit=100;
    else AnalogInputManager::effectiveRate=100;
    check(LoggingManager::requestStart()==LoggingManager::StartResult::Failed);
    check(!has("file") && !has("acquire"));
    check(g_cfg.sampleRateHz==500);
  }

  // Local allocation loses a source after initial readiness: strict aborts,
  // best effort records the remaining configured slot with an explicit mask.
  for(bool bestEffort:{false,true}) {
    productionReset();local();add(SensorType::AnalogPot,"second",0,0);
    g_cfg.recordingBestEffort=bestEffort;SensorManager::localAllocationMask=1;
    auto outcome=LoggingManager::requestStart();
    if(!bestEffort) {
      check(outcome==LoggingManager::StartResult::Failed);
      check(!has("file") && !has("acquire") && has("sensor_stop"));
    } else {
      check(outcome==LoggingManager::StartResult::Pending);opened();LoggingManager::loop();
      check(s_running);check(RecordingReadiness::session().decision.selected==1);
      check(RecordingReadiness::session().decision.excluded==2);finish();
    }
  }

  // CAN node 3 is configured slot 0; a native source follows at slot 1.
  // PREPARE excludes node 3 while native slot 1 and node 1 at slot 2 continue.
  for(bool bestEffort:{false,true}) {
    productionReset();remote(3);local();remote(1);g_cfg.recordingBestEffort=bestEffort;
    check(LoggingManager::requestStart()==LoggingManager::StartResult::Pending);opened();
    RemoteImuRecording::healthy=1u<<1;RemoteImuRecording::failedStatus=true;
    RemoteImuRecording::prepareDone=true;
    LoggingManager::loop();LoggingManager::loop();
    if(bestEffort) {
      check(s_running && has("acquire"));
      check(RecordingReadiness::session().decision.selected==6);
      check(RecordingReadiness::session().decision.excluded==1);finish();
    } else {
      check(!s_running && !has("acquire"));settleStop();
      check(has("close") || has("failed_close"));
    }
  }

  // A failed COMMIT aborts strict preparation; best effort retains native and
  // healthy remote membership after the adapter retires the failed source.
  for(bool bestEffort:{false,true}) {
    productionReset();remote(3);local();remote(1);g_cfg.recordingBestEffort=bestEffort;
    check(LoggingManager::requestStart()==LoggingManager::StartResult::Pending);opened();
    RemoteImuRecording::prepareDone=true;RemoteImuRecording::commitFails=true;
    LoggingManager::loop();LoggingManager::loop();
    check(has("commit") && !has("acquire"));
    if(bestEffort) {
      // Remote lifecycle reports recording once failed sources have retired.
      RemoteImuRecording::commitSettled=true;LoggingManager::loop();
      check(s_running && RecordingReadiness::session().decision.selected==6);
      finish();
    } else {
      LoggingManager::loop();check(!s_running && !has("acquire"));settleStop();
    }
  }

  // Reservation failure and operator cancellation never activate acquisition.
  productionReset();remote(3);local();
  check(LoggingManager::requestStart()==LoggingManager::StartResult::Pending);opened();
  RemoteImuRecording::resourceOk=false;LoggingManager::loop();
  check(!has("commit") && !has("acquire"));settleStop();
  check((has("close") || has("failed_close")) && !RecordingReadiness::session().decision.mayRecord);
  productionReset();remote(3);local();
  check(LoggingManager::requestStart()==LoggingManager::StartResult::Pending);
  LoggingManager::cancelStart();settleStop();
  check(!has("acquire") && !has("file"));

  // An all-remote failed selection closes preparation without enabling a
  // zero-member recording; node 3 still occupies configured slot zero.
  productionReset();remote(3);g_cfg.recordingBestEffort=true;
  check(LoggingManager::requestStart()==LoggingManager::StartResult::Pending);opened();
  RemoteImuRecording::healthy=0;RemoteImuRecording::failedStatus=true;
  RemoteImuRecording::prepareDone=true;LoggingManager::loop();LoggingManager::loop();
  check(!has("acquire") && !RecordingReadiness::session().decision.mayRecord);
  settleStop();check(has("close") || has("failed_close"));

  // Best effort with no remaining members cannot produce an empty ghost file.
  productionReset();local();g_cfg.recordingBestEffort=true;
  SensorManager::localAllocationMask=0;
  check(LoggingManager::requestStart()==LoggingManager::StartResult::Failed);
  check(!has("file") && !has("acquire"));
  printf("Production readiness/controller: %d checks passed\n",checks);
}
