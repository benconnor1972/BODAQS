"""Run the production remote recording coordinator over real control/master logic."""
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
    fixture = fixture.replace("assert(bodaqs_control_node_process(&node.view,&request,&reply));", "if(holdControl(request)) return true;\n  assert(dispatchControl(address,request,reply));")
    acquisition = (root / "test/acquisition_control_runtime_fixture.cpp").read_text()
    fixture += acquisition[:acquisition.index("int main() {")]
    manager = (root / "src/CanMasterManager.cpp").read_text()
    headers = ("Arduino.h", "SPI.h", "esp_system.h", "DebugLog.h", "LoggingManager.h", "SensorManager.h", "SharedSpiBus.h")
    manager = "\n".join(line for line in manager.splitlines() if not any(line in ('#include <'+h+'>', '#include "'+h+'"') for h in headers))
    fixture = fixture.replace("// PRODUCTION_MANAGER", manager)
    fixture += '\nint64_t esp_timer_get_time() { return int64_t(clockMs)*1000; }\nnamespace board { const BoardProfile* gBoard=&profile; }\n'
    fixture += (root / "src/AcquisitionControl.cpp").read_text().replace('#include <Arduino.h>', '')
    coordinator = (root / "src/RemoteImuRecording.cpp").read_text()
    for header in ('#include <Arduino.h>', '#include <esp_timer.h>', '#include "SensorManager.h"'):
        coordinator = coordinator.replace(header, '')
    fixture += coordinator
    fixture += (root / "test/remote_imu_lifecycle_runtime_fixture.cpp").read_text()
    protocol = root / "can-fd/common/protocol"
    sources = [*protocol.glob("bodaqs_control*.c"), protocol / "bodaqs_imu_disabled.c", protocol / "bodaqs_master_service.c", protocol / "bodaqs_master_protocol.c"]
    sources += [root / "src" / name for name in ("CanMasterProtocol.cpp", "SensorAssignment.cpp", "SensorParams.cpp", "Lsm6dso32xConfig.cpp", "RemoteImuStream.cpp", "BdqV2Catalog.cpp")]
    with tempfile.TemporaryDirectory(prefix="bodaqs-remote-lifecycle-") as temp:
        cpp, exe = Path(temp)/"fixture.cpp", Path(temp)/"fixture.exe"
        cpp.write_text(fixture)
        subprocess.run([args.compiler, "-std=c++17", "-ffunction-sections", "-Wl,--gc-sections", "-Wall", "-Wextra", "-Werror", "-Wno-class-memaccess", "-Wno-unused-function", "-I", str(root/"test/stubs"), "-I", str(root/"src"), "-I", str(protocol), "-I", str(root/"can-fd/common/test"), str(cpp), *map(str, sources), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
