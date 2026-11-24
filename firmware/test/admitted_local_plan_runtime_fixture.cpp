#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <array>
constexpr uint8_t MAX_SENSORS=4;
namespace LoggerLimits {constexpr uint16_t kMaxDynamicColumns=16;}
enum class SensorType {Native,LSM6DSO32XImu};
enum class LogFormat {BodaqsMultiStreamBinary};
struct SensorSpec {bool mutedDefault=false;SensorType type=SensorType::Native;};
struct LoggerConfig {
  bool recordingBestEffort=true;LogFormat logFormat=LogFormat::BodaqsMultiStreamBinary;
  std::array<SensorSpec,2> specs;
  uint8_t sensorCount() const {return specs.size();}
  bool getSensorSpec(uint8_t index,SensorSpec& spec) const {if(index>=specs.size())return false;spec=specs[index];return true;}
};
struct SensorAssignment {enum class Kind {I2C,NodeImu};Kind kind=Kind::I2C;};
namespace board {static void* gBoard=nullptr;}
SensorAssignment sensorAssignment(const SensorSpec& spec,void*) {
  SensorAssignment value;if(spec.type==SensorType::LSM6DSO32XImu)value.kind=SensorAssignment::Kind::NodeImu;return value;
}
enum class SensorIssueCode {SensorAbsent,CapabilityMismatch};
enum class SensorIssueSeverity {Error};enum class SensorIssueImpact {ExcludeSensor};enum class SensorIssueScope {Sensor};
struct SensorDiagnosticIssue {
  SensorIssueCode code;SensorIssueSeverity severity;SensorIssueImpact impact;SensorIssueScope scope;
  uint8_t sensorIndex;int32_t evidenceA=0,evidenceB=0;
};
struct DiagnosticList {
  uint32_t excluded=0;
  bool blocksSession() const {return false;}
  bool excludesSensor(uint8_t index) const {return excluded&(1u<<index);}
  void add(const SensorDiagnosticIssue& issue) {excluded|=1u<<issue.sensorIndex;}
};
struct Sensor {
  unsigned prepares=0,validations=0;bool prepareOk=true,prepared=false,mute=false;
  bool muted() const {return mute;}const char* name() const {return "native";}
  bool prepareLoggingStart(const LoggerConfig&,uint16_t,char*,size_t) {++prepares;prepared=prepareOk;return prepareOk;}
  bool validateLoggingStart(const LoggerConfig&,uint16_t,char*,size_t) {++validations;return prepared;}
  bool usesBdqV2NativeStream() const {return true;}uint8_t columnCount() const {return 1;}
};
namespace RecordingReadiness {static uint32_t selectedMask=1;bool selected(uint8_t index){return selectedMask&(1u<<index);}}
namespace SensorManager {
Sensor first,second;Sensor* s_list[MAX_SENSORS]={&first,&second,nullptr,nullptr};
DiagnosticList configuredDiagnostics,s_sessionDiagnostics;
bool s_sessionPlanActive=false;bool s_sessionParticipating[MAX_SENSORS]{};
const DiagnosticList& configurationDiagnostics(const LoggerConfig&) {return configuredDiagnostics;}
bool requiresBdqV2(const LoggerConfig&) {return true;}
bool getMuted(uint8_t index,bool& out) {if(!s_list[index])return false;out=s_list[index]->mute;return true;}
uint16_t dynamicColumnCount(bool) {return 0;}
#define SENS_LOGW(...) do {} while(0)
// ACTUAL_PLAN
}
int main() {
  LoggerConfig cfg;char error[128]{};
  assert(SensorManager::validateLoggingStart(cfg,500,error,sizeof error));
  assert(SensorManager::first.prepares==1 && SensorManager::second.prepares==0);
  assert(SensorManager::first.validations==1 && SensorManager::second.validations==0);
  assert(SensorManager::sessionParticipantMask()==1);
  // The excluded source could prepare successfully, but admission is authoritative.
  cfg.recordingBestEffort=false;
  assert(!SensorManager::validateLoggingStart(cfg,500,error,sizeof error));
  assert(!SensorManager::s_sessionPlanActive && SensorManager::second.prepares==0);
  assert(SensorManager::sessionParticipantMask()==0);
  cfg.recordingBestEffort=true;RecordingReadiness::selectedMask=3;
  SensorManager::first.prepareOk=false;
  assert(SensorManager::validateLoggingStart(cfg,500,error,sizeof error));
  assert(SensorManager::sessionParticipantMask()==2);
  cfg.recordingBestEffort=false;
  assert(!SensorManager::validateLoggingStart(cfg,500,error,sizeof error));
  SensorManager::first.prepareOk=true;SensorManager::s_list[0]=nullptr;
  cfg.recordingBestEffort=true;
  assert(SensorManager::validateLoggingStart(cfg,500,error,sizeof error));
  assert(SensorManager::sessionParticipantMask()==2);
}
