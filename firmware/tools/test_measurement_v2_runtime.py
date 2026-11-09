"""Actual retained CAN batches over the explicitly versioned larger wire codec."""
import argparse
from pathlib import Path
import struct
import subprocess
import tempfile
import zlib
from test_remote_imu_lifecycle_runtime import fixture_source


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler",default="g++")
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    common=root / "can-fd/common/protocol"
    with tempfile.TemporaryDirectory(prefix="bodaqs-real-v2-") as temp:
        exe=Path(temp)/"fixture.exe";wire=Path(temp)/"wire.bin"
        subprocess.run([args.compiler,"-std=c++17","-Wall","-Wextra","-Werror","-O2",
            "-DBODAQS_SPI_MEASUREMENT_V2=1","-I",str(common),
            str(root / "test/measurement_v2_fixture.cpp"),
            *[str(common/name) for name in ("bodaqs_master_service.c","bodaqs_master_protocol.c","bodaqs_control.c","bodaqs_control_exchange.c")],
            "-o",str(exe)],check=True)
        subprocess.run([str(exe),str(wire)],check=True)
        data=wire.read_bytes()
        assert len(data)==256 and data[:4]==b"BM\x02\x02"
        assert zlib.crc32(data[:252]) & 0xffffffff == struct.unpack_from("<I",data,252)[0]
        assert data[236:240]==bytes((1,0,1,0))
        assert struct.unpack_from("<H",data,244)[0]==1008
        fixture=fixture_source(root)
        fixture=fixture.replace("static ParamStore extraParams[3];", "[[maybe_unused]] static ParamStore extraParams[3];")
        # No acquisition owner is required for this transport/RAM test.
        fixture += (root / "test/measurement_v2_logger_fixture.cpp").read_text()
        cpp=Path(temp)/"logger.cpp";cpp.write_text(fixture)
        sources=[*common.glob("bodaqs_control*.c"), *[common/name for name in
            ("bodaqs_master_service.c","bodaqs_master_protocol.c","bodaqs_imu_disabled.c")]]
        sources += [root/"src"/name for name in
            ("CanMasterProtocol.cpp","SensorAssignment.cpp","SensorParams.cpp","Lsm6dso32xConfig.cpp","RemoteImuStream.cpp","BdqV2Catalog.cpp","ImuAdmission.cpp")]
        subprocess.run([args.compiler,"-std=c++17","-DBODAQS_SPI_MEASUREMENT_V2=1","-ffunction-sections","-Wl,--gc-sections",
            "-Wall","-Wextra","-Werror","-Wno-class-memaccess","-Wno-unused-function",
            "-I",str(root/"test/stubs"),"-I",str(root/"src"),"-I",str(common),"-I",str(root/"can-fd/common/test"),
            str(cpp),*map(str,sources),"-o",str(exe)],check=True)
        subprocess.run([str(exe)],check=True)


if __name__=="__main__":
    main()
