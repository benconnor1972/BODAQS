#include "Lsm6dso32xConfig.h"
#include "SensorRegistry.h"
namespace {
Sensor* noAcquisition(const char*, const ParamPack&, bool) { return nullptr; }
const bool registered = SensorRegistry::registerType(SensorType::LSM6DSO32XImu,
    "lsm6dso32x_imu", "LSM6DSO32X IMU (CAN)", Lsm6dso32xConfig::paramDefs, noAcquisition, CAL_NONE);
}
