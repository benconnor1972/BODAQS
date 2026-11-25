#include "RecordingReadiness.h"
#include "ConfigManager.h"
#include "SensorManager.h"
#include "CanMasterManager.h"
#include "LoggingManager.h"
#include "SensorAssignment.h"
#include "Lsm6dso32xConfig.h"
#include "BoardSelect.h"
#include <stdio.h>
#include <string.h>

namespace RecordingReadiness {
namespace {
QualificationProfile profile_;
Observation session_;
RecordingAdmission::Inputs sessionInputs_;
bool invalidIssue_(SensorIssueCode code) {
  switch(code) {
    case SensorIssueCode::DuplicateSensorName:case SensorIssueCode::DuplicateSensorIdentity:
    case SensorIssueCode::EndpointConflict:case SensorIssueCode::ReservedEndpoint:
    case SensorIssueCode::UnknownSensorType:case SensorIssueCode::InvalidEndpoint:
    case SensorIssueCode::CapabilityMismatch:case SensorIssueCode::RuntimeConfigurationDiffers:
      return true;
    default:return false;
  }
}
RecordingAdmission::Inputs inputs_(const LoggerConfig& cfg,bool owned) {
  RecordingAdmission::Inputs result;result.bestEffort=cfg.recordingBestEffort;
  result.owned=owned;result.migrationPending=ConfigManager::migrationPending();
  result.candidateBuild=candidateBuild();
  const auto& diagnostics=SensorManager::configurationDiagnostics(cfg);
  for(uint8_t index=0;index<cfg.sensorCount() && index<32;++index) {
    SensorSpec spec;if(!cfg.getSensorSpec(index,spec)) continue;
    bool muted=spec.mutedDefault;(void)SensorManager::getMuted(index,muted);
    if(muted) continue;
    const uint32_t bit=uint32_t{1}<<index;result.requested|=bit;
    if(diagnostics.excludesSensor(index)) continue;
    const auto assignment=sensorAssignment(spec,board::gBoard);
    if(assignment.provider.kind==SensorProviderKind::CanNode) {
      char error[96]{};const auto node=assignment.provider.index;
      if(spec.type!=SensorType::LSM6DSO32XImu || assignment.kind!=SensorAssignment::Kind::NodeImu || node>3 ||
          !Lsm6dso32xConfig::validateSpec(spec,error,sizeof error)) {result.invalid|=bit;continue;}
      if(CanMasterManager::configurationReconciled(node) && CanMasterManager::acquisitionLinkCompatible(node))
        result.available|=bit;
    } else {
      Sensor* sensor=SensorManager::getConfiguredSensor(index);char error[96]{};
      if(sensor && !sensor->muted() && sensor->observeLoggingReadiness(cfg,cfg.sampleRateHz,error,sizeof error))
        result.available|=bit;
    }
  }
  if(cfg.sensorCount()>32 || diagnostics.blocksSession() || diagnostics.truncated()) result.invalid|=result.requested;
  for(uint8_t i=0;i<diagnostics.count();++i) {
    const auto* issue=diagnostics.at(i);if(!issue || !invalidIssue_(issue->code)) continue;
    if(issue->sensorIndex<32) result.invalid|=uint32_t{1}<<issue->sensorIndex;
    if(issue->relatedSensorIndex<32) result.invalid|=uint32_t{1}<<issue->relatedSensorIndex;
  }
  if(!result.migrationPending && ConfigManager::configurationBlocker().length()) result.invalid|=result.requested;
  return result;
}
Observation evaluate_(const LoggerConfig& cfg,RecordingAdmission::Inputs& input) {
  Observation result;const uint32_t selection=input.requested&input.available&~input.invalid;
  if(profile_.coverage) {
    const bool bound=board::gBoard && profile_.boardProfile &&
        !strcmp(profile_.boardProfile,board::gBoard->name) &&
        profile_.acquisitionContract && !strcmp(profile_.acquisitionContract,kAcquisitionContract);
    input.profilePresent=bound && profile_.identifier && profile_.identifier[0] && profile_.revision;
    input.qualification=input.profilePresent?profile_.coverage(cfg,selection):RecordingAdmission::Qualification::Invalid;
    if(input.profilePresent) {
      snprintf(result.profileId,sizeof result.profileId,"%s",profile_.identifier);
      result.profileRevision=profile_.revision;
    }
  }
  result.invalid=input.invalid;result.unavailable=input.requested&~input.available;
  result.reservation=input.reservation;result.decision=RecordingAdmission::decide(input);return result;
}
}
bool candidateBuild() {
#if BODAQS_PRODUCTION_RECORDING && BODAQS_UNQUALIFIED_INTEGRATION_CANDIDATE
  return true;
#else
  return false;
#endif
}
bool setQualificationProfile(const QualificationProfile* profile) {
  if(LoggingManager::configurationLocked()) return false;
  if(!profile) {profile_=QualificationProfile{};return true;}
  if(!profile->identifier || !profile->identifier[0] || strlen(profile->identifier)>=sizeof session_.profileId ||
      !profile->revision || !profile->boardProfile || !profile->acquisitionContract || !profile->coverage) return false;
  profile_=*profile;return true;
}
Observation observe(const LoggerConfig& cfg) {
  auto input=inputs_(cfg,LoggingManager::configurationLocked());return evaluate_(cfg,input);
}
bool beginPreparation(const LoggerConfig& cfg) {
  sessionInputs_=inputs_(cfg,false);session_=evaluate_(cfg,sessionInputs_);return session_.decision.mayPrepare;
}
bool freezeMembership(const LoggerConfig& cfg,uint32_t availableMask) {
  sessionInputs_.available&=availableMask;
  session_=evaluate_(cfg,sessionInputs_);return session_.decision.mayPrepare;
}
void setReservation(RecordingAdmission::Reservation state) {
  sessionInputs_.reservation=state;session_.reservation=state;
  session_.decision=RecordingAdmission::decide(sessionInputs_);
}
const Observation& session() {return session_;}
bool selected(uint8_t index) {return index<32 && (session_.decision.selected&(uint32_t{1}<<index));}
const char* reason(const Observation& observation) {return RecordingAdmission::blockerText(observation.decision.blocker);}
}
