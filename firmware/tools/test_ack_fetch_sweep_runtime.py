"""Characterize the real ACK-fetch scheduler under delayed response publication."""
import argparse
from pathlib import Path
import subprocess
import tempfile

from test_remote_imu_lifecycle_runtime import fixture_source


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler",default="g++")
    parser.add_argument("--reference-only",action="store_true")
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];common=root/"can-fd/common/protocol"
    fixture=fixture_source(root)
    fixture=fixture.replace("static ParamStore extraParams[7];", "[[maybe_unused]] static ParamStore extraParams[7];")
    fixture=fixture.replace("namespace SharedSpiBus {", "static std::vector<BodaqsMeasurementSlot> observedRequests;\nnamespace SharedSpiBus {",1)
    fixture=fixture.replace(" if(!spiAvailable) return false;", " if(length==BODAQS_MEASUREMENT_BYTES) {BodaqsMeasurementSlot sent={};assert(bodaqs_measurement_decode(tx,length,&sent));observedRequests.push_back(sent);}\n if(!spiAvailable) return false;",1)
    fixture+=(root/"test/ack_fetch_sweep_fixture.cpp").read_text(encoding="utf-8")
    sources=[*common.glob("bodaqs_control*.c"),*[common/name for name in ("bodaqs_master_service.c","bodaqs_master_protocol.c","bodaqs_imu_disabled.c")]]
    sources += [root/"src"/name for name in ("CanMasterProtocol.cpp","SensorAssignment.cpp","SensorParams.cpp","Lsm6dso32xConfig.cpp","RemoteImuStream.cpp","BdqV2Catalog.cpp","ImuAdmission.cpp")]
    with tempfile.TemporaryDirectory(prefix="bodaqs-ack-sweep-") as temp:
        cpp=Path(temp)/"fixture.cpp";cpp.write_text(fixture,encoding="utf-8")
        for enabled in ((0,) if args.reference_only else (0,1)):
            exe=Path(temp)/f"sweep{enabled}.exe"
            subprocess.run([args.compiler,"-std=c++17","-DBODAQS_SPI_MEASUREMENT_V2=1",f"-DBODAQS_ACK_FETCH_FRAGMENT_SWEEP={enabled}",
                "-ffunction-sections","-Wl,--gc-sections","-Wall","-Wextra","-Werror","-Wno-class-memaccess","-Wno-unused-function",
                "-I",str(root/"test/stubs"),"-I",str(root/"src"),"-I",str(common),"-I",str(root/"can-fd/common/test"),str(cpp),*map(str,sources),"-o",str(exe)],check=True)
            subprocess.run([str(exe)],check=True,timeout=30)


if __name__=="__main__":main()
