"""Exercise the production logger owner over the real pipelined master SPI fixture."""
import argparse
from pathlib import Path
import subprocess
import tempfile

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    fixture = (root / "test/measurement_runtime_fixture.cpp").read_text()
    fixture = fixture[:fixture.index("int main() {")]
    fixture = fixture.replace("namespace SharedSpiBus {", "static bool dispatchControl(uint8_t,const BodaqsControlRecord&,BodaqsControlRecord&);\nstatic bool holdControl(const BodaqsControlRecord&);\nnamespace SharedSpiBus {")
    fixture = fixture.replace("assert(bodaqs_control_node_process(&node.view,&request,&reply));", "assert(dispatchControl(address,request,reply));")
    fixture = fixture.replace("assert(dispatchControl(address,request,reply));", "if(holdControl(request)) return true;\n  assert(dispatchControl(address,request,reply));")
    fixture += (root / "test/acquisition_control_runtime_fixture.cpp").read_text()
    manager = (root / "src/CanMasterManager.cpp").read_text()
    headers = ("Arduino.h", "SPI.h", "esp_system.h", "DebugLog.h", "LoggingManager.h", "SensorManager.h", "SharedSpiBus.h")
    manager = "\n".join(line for line in manager.splitlines() if not any(line in ('#include <'+h+'>', '#include "'+h+'"') for h in headers))
    fixture = fixture.replace("// PRODUCTION_MANAGER", manager)
    client = (root / "src/AcquisitionControl.cpp").read_text().replace('#include <Arduino.h>', '')
    fixture += "\n" + client
    protocol = root / "can-fd/common/protocol"
    sources = [*protocol.glob("bodaqs_control*.c"), protocol/"bodaqs_imu_disabled.c", protocol/"bodaqs_master_service.c", protocol/"bodaqs_master_protocol.c"]
    sources += [root/"src"/name for name in ("CanMasterProtocol.cpp", "SensorAssignment.cpp", "SensorParams.cpp", "Lsm6dso32xConfig.cpp")]
    with tempfile.TemporaryDirectory(prefix="bodaqs-acquisition-") as temp:
        cpp, exe = Path(temp)/"fixture.cpp", Path(temp)/"fixture.exe"
        cpp.write_text(fixture)
        subprocess.run([args.compiler, "-std=c++17", "-ffunction-sections", "-Wl,--gc-sections", "-Wall", "-Wextra", "-Werror", "-Wno-class-memaccess", "-Wno-unused-function", "-I", str(root/"test/stubs"), "-I", str(root/"src"), "-I", str(protocol), "-I", str(root/"can-fd/common/test"), str(cpp), *map(str, sources), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)

if __name__ == "__main__":
    main()
