#include <cassert>
#include <cstring>
#include <string>
#include <array>
#include "RecordingReadiness.h"
enum class SensorType {AnalogPot,LSM6DSO32XImu,Unknown};
enum class SensorProviderKind {Local,CanNode};
struct SensorAssignment {
  enum class Kind {ExternalAdc,NodeImu,I2C};
  struct {SensorProviderKind kind=SensorProviderKind::Local;uint8_t index=0;} provider;
  Kind kind=Kind::ExternalAdc;
};
struct SensorSpec {SensorType type=SensorType::AnalogPot;bool mutedDefault=false;SensorAssignment assignment;};
struct LoggerConfig {
  std::array<SensorSpec,4> sensors;bool recordingBestEffort=false;uint16_t sampleRateHz=500;
  uint8_t sensorCount() const {return sensors.size();}
  bool getSensorSpec(uint8_t i,SensorSpec& out) const {if(i>=sensors.size())return false;out=sensors[i];return true;}
};
namespace board {struct Board {const char* name="fixture_board";};static Board board;static Board* gBoard=&board;}
SensorAssignment sensorAssignment(const SensorSpec& spec,const board::Board*) {return spec.assignment;}
enum class SensorIssueCode {DuplicateSensorName,DuplicateSensorIdentity,EndpointConflict,ReservedEndpoint,
  UnknownSensorType,InvalidEndpoint,CapabilityMismatch,RuntimeConfigurationDiffers,SensorAbsent};
struct SensorDiagnosticIssue {SensorIssueCode code=SensorIssueCode::SensorAbsent;uint8_t sensorIndex=255,relatedSensorIndex=255;};
struct DiagnosticList {
  bool block=false,overflow=false;uint32_t excluded=0;SensorDiagnosticIssue issue;bool issuePresent=false;
  bool excludesSensor(uint8_t i) const {return excluded&(1u<<i);}
  bool blocksSession() const {return block;}bool truncated() const {return overflow;}
  uint8_t count() const {return issuePresent?1:0;}const SensorDiagnosticIssue* at(uint8_t) const {return &issue;}
};
struct Sensor {bool ready=true;bool muted() const {return false;}
  bool observeLoggingReadiness(const LoggerConfig&,uint16_t,char*,size_t) const {return ready;}};
constexpr unsigned MAX_SENSORS=4;
namespace SensorManager {
  static std::array<Sensor,4> sensors;static DiagnosticList diagnostics;
  static Sensor* s_list[4]={&sensors[0],&sensors[1],&sensors[2],&sensors[3]};
  static bool runtimeOverride=false;static uint32_t runtimeMuted=0;
  const DiagnosticList& configurationDiagnostics(const LoggerConfig&) {return diagnostics;}
  bool getMuted(uint8_t i,bool& muted) {if(!runtimeOverride)return false;muted=runtimeMuted&(1u<<i);return true;}
  // ACTUAL_CONFIGURED_ACCESS
}
namespace ConfigManager {
  static bool migration=false,invalid=false;
  bool migrationPending() {return migration;}
  std::string configurationBlocker() {return invalid?"unsupported source":"";}
}
namespace LoggingManager {static bool owned=false;bool configurationLocked(){return owned;}}
namespace CanMasterManager {static uint8_t ready=1;bool configurationReconciled(uint8_t n){return ready&(1u<<n);}
  bool acquisitionLinkCompatible(uint8_t){return true;}}
namespace Lsm6dso32xConfig {bool validateSpec(const SensorSpec& spec,char*,size_t){return spec.type==SensorType::LSM6DSO32XImu;}}
// ACTUAL_READINESS
using namespace RecordingAdmission;
static Qualification fixtureCoverage(const LoggerConfig& config,uint32_t) {
  return config.sampleRateHz<=500?Qualification::Covered:Qualification::Rejected;
}
int main() {
  LoggerConfig config;
  for(uint8_t i=2;i<4;++i) {config.sensors[i].type=SensorType::LSM6DSO32XImu;
    config.sensors[i].assignment.provider.kind=SensorProviderKind::CanNode;
    config.sensors[i].assignment.provider.index=i-2;config.sensors[i].assignment.kind=SensorAssignment::Kind::NodeImu;}
  RecordingReadiness::QualificationProfile profile{"host_fixture_only",1,"fixture_board",RecordingReadiness::kAcquisitionContract,fixtureCoverage};
  assert(RecordingReadiness::setQualificationProfile(&profile));
  auto result=RecordingReadiness::observe(config);
  assert(result.decision.blocker==Blocker::ParticipantUnavailable && result.unavailable==8);
  config.recordingBestEffort=true;result=RecordingReadiness::observe(config);
  assert(result.decision.selected==7 && result.decision.excluded==8 && result.decision.mayPrepare && !result.decision.mayRecord);
  assert(result.profileRevision==1 && !strcmp(result.profileId,"host_fixture_only"));
  assert(RecordingReadiness::beginPreparation(config));
  assert(RecordingReadiness::selected(2) && !RecordingReadiness::selected(3));
  assert(RecordingReadiness::freezeMembership(config,5));
  assert(RecordingReadiness::session().decision.selected==5);
  RecordingReadiness::setReservation(Reservation::Acquired);
  assert(RecordingReadiness::session().decision.mayRecord);
  RecordingReadiness::setReservation(Reservation::Failed);
  assert(!RecordingReadiness::session().decision.mayRecord);
  ConfigManager::migration=true;assert(!RecordingReadiness::beginPreparation(config));
  assert(RecordingReadiness::session().decision.blocker==Blocker::MigrationRequired);ConfigManager::migration=false;
  SensorManager::diagnostics.excluded=1;SensorManager::diagnostics.issuePresent=true;
  SensorManager::diagnostics.issue={SensorIssueCode::UnknownSensorType,0,255};
  assert(RecordingReadiness::observe(config).decision.blocker==Blocker::InvalidConfiguration);
  SensorManager::diagnostics={};config.sampleRateHz=1000;
  assert(RecordingReadiness::observe(config).decision.blocker==Blocker::QualificationRejected);
  config.sampleRateHz=500;LoggingManager::owned=true;
  assert(!RecordingReadiness::setQualificationProfile(nullptr));
  assert(RecordingReadiness::observe(config).decision.blocker==Blocker::OwnershipRetained);
  LoggingManager::owned=false;assert(RecordingReadiness::setQualificationProfile(nullptr));
  result=RecordingReadiness::observe(config);
#if BODAQS_UNQUALIFIED_INTEGRATION_CANDIDATE
  assert(result.decision.candidate && result.decision.mayPrepare && !result.decision.qualified);
#else
  assert(!result.decision.mayPrepare && result.decision.blocker==Blocker::Unqualified);
#endif
  assert(RecordingReadiness::setQualificationProfile(&profile));
  config.sensors[0].mutedDefault=true;
  assert(!(RecordingReadiness::observe(config).decision.requested&1));
  SensorManager::runtimeOverride=true;
  assert(RecordingReadiness::observe(config).decision.requested&1); // Explicit runtime unmute.
  SensorManager::runtimeOverride=false;config.sensors[0].mutedDefault=false;
  const auto previous=config.sensors;
  config.sensors[0]=previous[2];config.sensors[1]=previous[3];
  config.sensors[2]=previous[0];config.sensors[3]=previous[1];
  SensorManager::s_list[0]=SensorManager::s_list[1]=nullptr;
  assert(RecordingReadiness::observe(config).decision.selected==13); // CAN slots do not compress local indices.
  profile.boardProfile="wrong_board";assert(RecordingReadiness::setQualificationProfile(&profile));
  assert(!RecordingReadiness::observe(config).decision.mayPrepare);
}
