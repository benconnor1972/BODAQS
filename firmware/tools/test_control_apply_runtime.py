"""Production logger desired selection, effective agreement and JSON projection."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from runtime_test_helpers import definition


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    manager = (root / "src/CanMasterManager.cpp").read_text()
    api = (root / "src/Routes_Api.cpp").read_text()
    fixture = r'''#include <ArduinoJson.h>
#include "CanMasterManager.h"
#include "SensorAssignment.h"
#include "Lsm6dso32xConfig.h"
#include <cassert>
#include <cstdio>
#include <cstring>
static LoggerConfig config;
static SensorSpec specs[2];
static uint8_t count;
static bool liveMuted;
static CanMasterManager::Diagnostics s_diagnostics;
static const board::BoardProfile* s_board = nullptr;
uint8_t LoggerConfig::sensorCount() const { return count; }
bool LoggerConfig::getSensorSpec(uint8_t i, SensorSpec& out) const { if(i>=count) return false; out=specs[i]; return true; }
const LoggerConfig& ConfigManager::get() { return config; }
namespace SensorManager { bool getMuted(uint8_t, bool& out) { out=liveMuted; return true; } }
// DESIRED
namespace CanMasterManager {
// AGREEMENT
}
// JSON
int main() {
 assert(desiredDisabled_(0)); // fitted but unassigned
 ParamStore params; assert(params.set("provider","can:0") && params.set("endpoint","imu"));
 specs[0].type=SensorType::BMI270ImuI2C; specs[0].params.bind(&params); count=1;
 assert(!desiredDisabled_(0)); // active unresolved legacy BMI never becomes an accepted profile
 liveMuted=true; assert(desiredDisabled_(0));
 liveMuted=false; params.set("provider","can0"); assert(!desiredDisabled_(0));
 assert(desiredDisabled_(1));
 specs[0].type=SensorType::LSM6DSO32XImu; params.set("profile","imu6_3333_32g_2000dps_v1");
 assert(desiredEnabled_(0) && !desiredDisabled_(0));
 params.set("profile","orientation_200"); assert(!desiredEnabled_(0));
 params.set("profile","imu6_3333_32g_2000dps_v1");
 count=2; specs[1]=specs[0]; assert(!desiredEnabled_(0)); count=1;
 auto& node=s_diagnostics.control.nodes[0]; auto& endpoint=node.endpoints[0];
 node.available=node.valid=endpoint.current=endpoint.effective_valid=true;
 s_diagnostics.authority.nodes[0].bound=true; s_diagnostics.authority.session=node.active_session=9;
 s_diagnostics.desiredGeneration[0]=1; s_diagnostics.desiredDisabled[0]=true;
 auto* d=endpoint.effective; d[4]=1; bodaqs_control_put_u32(d+12,0x441);
 bodaqs_control_put_u32(d+20,3);
 bodaqs_control_put_u64(d+144,9); bodaqs_control_put_u64(d+24,1);
 assert(CanMasterManager::configurationReconciled(0));
 s_diagnostics.desiredDisabled[0]=false;s_diagnostics.desiredEnabled[0]=true;
 d[4]=2;d[5]=3;d[40]=d[42]=1;bodaqs_control_put_u32(d+12,0x47f);
 assert(CanMasterManager::configurationReconciled(0));
 d[40]=2; assert(!CanMasterManager::configurationReconciled(0)); d[40]=1;
 s_diagnostics.desiredDisabled[0]=true;s_diagnostics.desiredEnabled[0]=false;d[4]=1;
 bodaqs_control_put_u32(d+12,0x441);
 bodaqs_control_put_u32(d+16,0x400); assert(!CanMasterManager::configurationReconciled(0));
 bodaqs_control_put_u32(d+16,0); bodaqs_control_put_u64(d+144,8);
 assert(!CanMasterManager::configurationReconciled(0));
 bodaqs_control_put_u64(d+144,9); endpoint.current=false;
 assert(!CanMasterManager::configurationReconciled(0));
 JsonDocument doc; auto json=doc.to<JsonObject>(); auto& apply=s_diagnostics.apply;
 apply.phase=1; apply.current.node_address=0; apply.nodes[0].operation=2; apply.nodes[0].desired_generation=1;
 addControlApplyJson_(json,apply,0,UINT64_MAX,true,false);
 assert(!strcmp(json["apply_operation"]["desired_generation"].as<const char*>(),"1"));
 assert(!strcmp(json["desired_generation"].as<const char*>(),"18446744073709551615"));
 assert(!strcmp(json["desired_mode"].as<const char*>(),"disabled"));
 assert(json["apply_operation"]["pending"].as<bool>() && !json["configuration_reconciled"].as<bool>());
 apply.phase=0; apply.nodes[0].kind=3; apply.nodes[0].valid=true; apply.nodes[0].revision=UINT64_MAX;
 addControlApplyJson_(json,apply,0,1,true,true);
 assert(!strcmp(json["apply_operation"]["applied_revision"].as<const char*>(),"18446744073709551615"));
 assert(json["configuration_reconciled"].as<bool>() && !json["apply_operation"]["pending"].as<bool>());
 JsonDocument effectiveDoc; auto effective=effectiveDoc.to<JsonObject>();
 uint8_t image[192]={}; bodaqs_control_put_u32(image+12,0x47f);
 image[4]=2; image[5]=3; image[40]=image[42]=image[47]=1;
 bodaqs_control_put_u32(image+72,122);bodaqs_control_put_u32(image+76,125000);
 bodaqs_control_put_u32(image+80,7);bodaqs_control_put_u32(image+84,100);
 addImuConfigurationJson_(effective,image);
 assert(effective["engine_power_bits"]==3 && effective["acquisition_active"]==false);
 assert(effective["nominal_accel_g_per_count"]["numerator"]==122);
 assert(effective["nominal_accel_g_per_count"]["denominator"]==125000);
 assert(effective["nominal_gyro_dps_per_count"]["denominator"]==100);
 assert(effective["register_image"].size()==24);
 puts("production canonical desired/agreement/API passed");
}
'''
    fixture = fixture.replace("// DESIRED", definition(manager, "bool desiredDisabled_(") + "\n" + definition(manager,"bool desiredEnabled_("))
    fixture = fixture.replace("// AGREEMENT", definition(manager, "bool configurationReconciled("))
    fixture = fixture.replace("// JSON", definition(api, "static void addControlApplyJson_(") + "\n" + definition(api, "static void addImuConfigurationJson_("))
    with tempfile.TemporaryDirectory(prefix="bodaqs-disabled-") as temp:
        cpp, exe = Path(temp) / "runtime.cpp", Path(temp) / "runtime.exe"
        cpp.write_text(fixture)
        subprocess.run([args.compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str(root / "test/stubs"),
                        "-I", str(root / "src"), "-I", str(root / ".pio/libdeps/bodaqs_s3_mini_n4r2/ArduinoJson/src"),
                        str(cpp), str(root / "src/SensorAssignment.cpp"), str(root / "src/SensorParams.cpp"),
                        str(root / "can-fd/common/protocol/bodaqs_control.c"), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
