"""Production logger/master measurement negotiation over pipelined SPI boundary."""
import argparse
from pathlib import Path
import subprocess
import tempfile

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler",default="g++")
    parser.add_argument("--reply-capture",action="store_true")
    parser.add_argument("--cs-setup-us",type=int,default=0)
    parser.add_argument("--manager-source",type=Path,help="Negative proof against a saved production manager")
    args=parser.parse_args()
    flags=["-DBODAQS_SPI_MEASUREMENT_V2=1","-DBODAQS_IMU_FLOW_DIAGNOSTICS=1","-DBODAQS_MEASUREMENT_REPLY_CAPTURE=1"] if args.reply_capture else []
    if args.cs_setup_us: flags.append(f"-DBODAQS_MEASUREMENT_CS_SETUP_US={args.cs_setup_us}")
    root=Path(__file__).resolve().parents[1]
    source=(args.manager_source or root/"src/CanMasterManager.cpp").read_text()
    boundary_headers=("Arduino.h","SPI.h","esp_system.h","DebugLog.h","LoggingManager.h","SensorManager.h","SharedSpiBus.h")
    source="\n".join(line for line in source.splitlines() if not any(line in ('#include <'+h+'>','#include "'+h+'"') for h in boundary_headers))
    fixture=(root/"test/measurement_runtime_fixture.cpp").read_text()
    fixture=fixture.replace("// PRODUCTION_MANAGER",source)
    protocol=root/"can-fd/common/protocol"
    sources=[*protocol.glob("bodaqs_control*.c"),protocol/"bodaqs_imu_disabled.c",protocol/"bodaqs_master_service.c",protocol/"bodaqs_master_protocol.c",root/"src/CanMasterProtocol.cpp",root/"src/SensorAssignment.cpp",root/"src/SensorParams.cpp",root/"src/Lsm6dso32xConfig.cpp"]
    with tempfile.TemporaryDirectory(prefix="bodaqs-recovery-") as temp:
        cpp,exe=Path(temp)/"recovery.cpp",Path(temp)/"recovery.exe"
        cpp.write_text(fixture)
        subprocess.run([args.compiler,"-std=c++17",*flags,"-ffunction-sections","-Wl,--gc-sections","-Wall","-Wextra","-Werror","-Wno-class-memaccess","-I",str(root/"test/stubs"),"-I",str(root/"src"),"-I",str(protocol),"-I",str(root/"can-fd/common/test"),str(cpp),*[str(s) for s in sources],"-o",str(exe)],check=True)
        subprocess.run([str(exe)],check=True)

if __name__=="__main__": main()
