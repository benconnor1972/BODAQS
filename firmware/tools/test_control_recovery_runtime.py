"""Full production CanMasterManager lifecycle over real SPI/CAN/control/backend boundaries."""
import argparse
from pathlib import Path
import subprocess
import tempfile

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler",default="g++")
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    source=(root/"src/CanMasterManager.cpp").read_text()
    boundary_headers=("Arduino.h","SPI.h","esp_system.h","DebugLog.h","LoggingManager.h","SensorManager.h","SharedSpiBus.h")
    source="\n".join(line for line in source.splitlines() if not any(line in ('#include <'+h+'>','#include "'+h+'"') for h in boundary_headers))
    fixture=(root/"test/control_recovery_runtime_fixture.cpp").read_text()
    fixture=fixture.replace("// PRODUCTION_MANAGER",source)
    protocol=root/"can-fd/common/protocol"
    sources=[*protocol.glob("bodaqs_control*.c"),protocol/"bodaqs_imu_disabled.c",protocol/"bodaqs_master_service.c",protocol/"bodaqs_master_protocol.c",root/"src/CanMasterProtocol.cpp",root/"src/SensorAssignment.cpp",root/"src/SensorParams.cpp",root/"src/Lsm6dso32xConfig.cpp"]
    with tempfile.TemporaryDirectory(prefix="bodaqs-recovery-") as temp:
        cpp,exe=Path(temp)/"recovery.cpp",Path(temp)/"recovery.exe"
        cpp.write_text(fixture)
        subprocess.run([args.compiler,"-std=c++17","-ffunction-sections","-Wl,--gc-sections","-Wall","-Wextra","-Werror","-Wno-class-memaccess","-I",str(root/"test/stubs"),"-I",str(root/"src"),"-I",str(protocol),"-I",str(root/"can-fd/common/test"),str(cpp),*[str(s) for s in sources],"-o",str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
        subprocess.run([str(exe),"--wrap"],check=True)

if __name__=="__main__": main()
