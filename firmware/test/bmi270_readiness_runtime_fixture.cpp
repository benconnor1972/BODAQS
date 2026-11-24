#include "Arduino.h"
#include "SensorTypes.h"
#include "BMI270Profile.h"
#include "BMI270FifoReadPlan.h"
#include "ImuOrientation.h"
#include "BoardProfile.h"
#include <cassert>
#include <cstdarg>
#include <cmath>
#include <cstring>

#define BMI270_SENSOR_LOGW(...) ((void)0)
#define BMI270_SENSOR_LOGI(...) ((void)0)
enum class LogFormat { BodaqsStandard, BodaqsCompactBinary, BodaqsMultiStreamBinary };
struct LoggerConfig {
  SensorSpec spec;
  ParamStore store;
  bool present=true;
  LogFormat logFormat=LogFormat::BodaqsMultiStreamBinary;
  int8_t findSensorByName(const char* name)const {return present && !strcmp(name,spec.name)?0:-1;}
  bool getSensorSpec(uint8_t index,SensorSpec& out)const {
    if(!present || index)return false;
    out=spec;out.params.bind(&store);return true;
  }
};
namespace I2CManager {
  bool busAvailable=true;
  board::I2CProfile bus;
  bool available(uint8_t index) {return index==1 && busAvailable;}
  const board::I2CProfile* profile(uint8_t index) {return index==1?&bus:nullptr;}
}
enum class BMI270GyroBiasMode { Off, InUseOffsetCorrection };
// Device boundary: setters change the applied host-side acquisition plan;
// initialization is the only modeled hardware operation. Queries never do I/O.
struct Acquisition {
  const BMI270Profile::NativeProfile* selected=&BMI270Profile::kNativeProfiles[0];
  uint16_t output=200,poll=200;
  unsigned mutations=0,hardwareReads=0;
  bool devicePresent=true;
  Acquisition(uint8_t,uint8_t,const char*){}
  bool setProfile(const BMI270Profile::NativeProfile& profile){selected=&profile;++mutations;return true;}
  bool setOutputRateHz(uint16_t rate){++mutations;if(!rate || selected->accelOdrHz%rate)return false;output=rate;return true;}
  bool setFifoPollRateHz(uint16_t rate){++mutations;poll=rate;return true;}
  bool setGyroBiasMode(BMI270GyroBiasMode){++mutations;return true;}
  void setIocDiagnosticsEnabled(bool){++mutations;}
  bool mixedRate()const{return selected->isMixedRate();}
  uint16_t nativeRateHz()const{return selected->accelOdrHz;}
  uint16_t fifoPollRateHz()const{return poll;}
  uint16_t outputRateHz()const{return output;}
};
class CompatibilitySensor {
public:
  bool accepted=false;
  mutable unsigned validations=0;
  virtual bool validateLoggingStart(const LoggerConfig&,uint16_t,char*,size_t)const {++validations;return accepted;}
  // ACTUAL_DEFAULT_OBSERVER
};
class BMI270ImuSensor : public CompatibilitySensor {
public:
  // ACTUAL_PARAMS
  explicit BMI270ImuSensor(const Params&);
  bool observeLoggingReadiness(const LoggerConfig&,uint16_t,char*,size_t)const;
  bool prepareLoggingStart(const LoggerConfig&,uint16_t,char*,size_t);
  bool validateLoggingStart(const LoggerConfig&,uint16_t,char*,size_t)const;
  bool loggingRestartRequired(const SensorSpec&,char*,size_t)const;
  static bool validateSpec(const SensorSpec&,char*,size_t);
  static bool loadParams_(Params&,const char*,const ParamPack&);
  Params params_;
  Acquisition acquisition_;
  bool muted_=false,sessionAvailable_=false,captureClockObservations_=false;
private:
  bool resolveLoggingConfiguration_(const LoggerConfig&,uint16_t,uint16_t&,char*,size_t)const;
  bool ensureInitialized_(char*,size_t) {++acquisition_.hardwareReads;return acquisition_.devicePresent;}
};
// ACTUAL_METHODS
int main() {
  I2CManager::bus.hz=400000;
  LoggerConfig config;config.spec.type=SensorType::BMI270ImuI2C;
  strcpy(config.spec.name,"frame_imu");config.store.set("profile","orientation_400");
  BMI270ImuSensor::Params params;strcpy(params.profile,"orientation_400");
  CompatibilitySensor compatibility;
  char legacyError[8]{};
  assert(!compatibility.observeLoggingReadiness(config,100,legacyError,sizeof(legacyError)));
  compatibility.accepted=true;
  assert(compatibility.observeLoggingReadiness(config,100,legacyError,sizeof(legacyError)) && compatibility.validations==2);
  BMI270ImuSensor sensor(params);
  assert(sensor.acquisition_.outputRateHz()==200);
  const unsigned constructorMutations=sensor.acquisition_.mutations;
  char error[128]{};
  const CompatibilitySensor& observer=sensor;
  assert(observer.observeLoggingReadiness(config,100,error,sizeof(error)));
  assert(sensor.acquisition_.outputRateHz()==200 && sensor.acquisition_.mutations==constructorMutations);
  assert(sensor.acquisition_.hardwareReads==0);
  assert(!sensor.validateLoggingStart(config,100,error,sizeof(error)));
  assert(sensor.prepareLoggingStart(config,100,error,sizeof(error)));
  assert(sensor.acquisition_.outputRateHz()==400 && sensor.acquisition_.hardwareReads==1);
  assert(sensor.validateLoggingStart(config,100,error,sizeof(error)));
  const auto preparedMutations=sensor.acquisition_.mutations;
  assert(sensor.observeLoggingReadiness(config,100,error,sizeof(error)));
  assert(sensor.acquisition_.mutations==preparedMutations && sensor.acquisition_.hardwareReads==1);
  config.present=false;
  assert(!sensor.observeLoggingReadiness(config,100,error,sizeof(error)) && error[0]);
  config.present=true;config.store.set("profile","unsupported");
  assert(!sensor.observeLoggingReadiness(config,100,error,sizeof(error)) && error[0]);
  config.store.set("profile","orientation_400");I2CManager::busAvailable=false;
  assert(!sensor.observeLoggingReadiness(config,100,error,sizeof(error)) && error[0]);
  I2CManager::busAvailable=true;I2CManager::bus.hz=100000;
  assert(!sensor.observeLoggingReadiness(config,100,error,sizeof(error)) && error[0]);
  assert(sensor.acquisition_.mutations==preparedMutations && sensor.acquisition_.hardwareReads==1);
  I2CManager::bus.hz=400000;
  config.store.set("max_output_rate_hz","201");
  BMI270ImuSensor::Params malformed=params;malformed.maximumOutputRateHz=201;
  BMI270ImuSensor invalidRate(malformed);
  const auto invalidMutations=invalidRate.acquisition_.mutations;
  assert(!invalidRate.observeLoggingReadiness(config,100,error,sizeof(error)) && error[0]);
  assert(invalidRate.acquisition_.hardwareReads==0 && invalidRate.acquisition_.mutations==invalidMutations);
  config.store.set("max_output_rate_hz","200");
  config.logFormat=LogFormat::BodaqsStandard;
  // Legacy sparse rows resolve prospectively too, while prepared validation
  // still requires preparation to select the effective decimation rate.
  assert(sensor.observeLoggingReadiness(config,50,error,sizeof(error)));
  assert(!sensor.validateLoggingStart(config,50,error,sizeof(error)));
  assert(sensor.prepareLoggingStart(config,50,error,sizeof(error)));
  assert(sensor.acquisition_.outputRateHz()==25 && sensor.validateLoggingStart(config,50,error,sizeof(error)));
}
