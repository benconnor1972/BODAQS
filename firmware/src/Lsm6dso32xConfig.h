#pragma once
#include "SensorAssignment.h"
#include <cmath>
#include <strings.h>
namespace Lsm6dso32xConfig {
constexpr const char* profile = "imu6_3333_32g_2000dps_v1";
inline const ParamDef* paramDefs(size_t& count) {
  static const ParamDef defs[] = {
    {"profile",ParamType::Enum,profile,nullptr,nullptr,profile,"Verified stopped profile; sample acquisition unavailable"},
    {"imu_id",ParamType::String,"frame_imu_001",nullptr,nullptr,nullptr,"Stable physical IMU identity"},
    {"domain",ParamType::Enum,"frame",nullptr,nullptr,"unsprung,frame,steering","Mechanically co-moving bicycle domain"},
    {"end",ParamType::Enum,"none",nullptr,nullptr,"none,front,rear","Bike end"},
    {"mount_point",ParamType::String,"",nullptr,nullptr,nullptr,"Descriptive mounting point"},
    {"calibration_ref",ParamType::String,"",nullptr,nullptr,nullptr,"Host calibration reference"},
    {"orient_valid",ParamType::Bool,"false",nullptr,nullptr,nullptr,"Saved mounting orientation",true},
    {"orient_qw",ParamType::Float,"1",nullptr,nullptr,nullptr,"Mounting quaternion W",true},
    {"orient_qx",ParamType::Float,"0",nullptr,nullptr,nullptr,"Mounting quaternion X",true},
    {"orient_qy",ParamType::Float,"0",nullptr,nullptr,nullptr,"Mounting quaternion Y",true},
    {"orient_qz",ParamType::Float,"0",nullptr,nullptr,nullptr,"Mounting quaternion Z",true}
  };
  count=sizeof(defs)/sizeof(defs[0]); return defs;
}
inline bool validateSpec(const SensorSpec& spec, char* error, size_t capacity) {
  const auto assignment=sensorAssignment(spec,nullptr);
  String selected; spec.params.get("profile",selected);
  if (assignment.provider.kind!=SensorProviderKind::CanNode || assignment.kind!=SensorAssignment::Kind::NodeImu ||
      !selected.equalsIgnoreCase(profile)) {
    snprintf(error,capacity,"LSM6DSO32X requires a CAN IMU assignment and supported LSM profile"); return false;
  }
  String domain="frame", end="none", identity=spec.name;
  spec.params.get("domain",domain); spec.params.get("end",end); spec.params.get("imu_id",identity);
  const bool front=end.equalsIgnoreCase("front"), rear=end.equalsIgnoreCase("rear");
  if (!identity.length() || (!(domain.equalsIgnoreCase("frame") && (front || rear || end.equalsIgnoreCase("none"))) &&
      !(domain.equalsIgnoreCase("unsprung") && (front || rear)) && !(domain.equalsIgnoreCase("steering") && front))) {
    snprintf(error,capacity,"Invalid IMU identity or mounting domain/end"); return false;
  }
  bool orientation=false; spec.params.getBool("orient_valid",orientation);
  if (orientation) {
    double sum=0;
    const char* keys[]={"orient_qw","orient_qx","orient_qy","orient_qz"};
    for (const char* key:keys) { double value; if(!spec.params.getFloat(key,value)||!std::isfinite(value)) {
      snprintf(error,capacity,"Invalid mounting quaternion"); return false; } sum+=value*value; }
    if (std::fabs(sum-1)>0.001) { snprintf(error,capacity,"Mounting quaternion must be normalized"); return false; }
  }
  return true;
}
}
