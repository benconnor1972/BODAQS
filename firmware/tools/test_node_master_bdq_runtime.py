"""Run actual node SPI/capture/FIFO adapter output through master and BDQ writer."""
from pathlib import Path
import argparse
import os
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    firmware = Path(__file__).resolve().parents[1]
    node = firmware / "can-fd/node"
    common = firmware / "can-fd/common/protocol"
    with tempfile.TemporaryDirectory(prefix="bodaqs-node-master-bdq-") as temporary:
        temporary = Path(temporary)
        producer = temporary / "node.exe"
        consumer = temporary / "master_bdq.exe"
        can = temporary / "node-can.txt"
        bdq = temporary / "node.bdq"
        subprocess.run([
            args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
            "-I", str(node / "test"), "-I", str(node / "src"), "-I", str(common),
            str(node / "test/test_acquisition.c"),
            *[str(node / "src" / name) for name in ("imu_spi.c", "imu_capture.c", "imu_acquisition.c")],
            str(common / "bodaqs_imu_disabled.c"), str(common / "bodaqs_control.c"), "-o", str(producer),
        ], check=True)
        environment = dict(os.environ, BODAQS_NODE_FIXTURE_OUT=str(can))
        subprocess.run([str(producer)], env=environment, check=True)
        subprocess.run([
            args.compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-I", str(firmware / "src"), "-I", str(common),
            str(firmware / "test/node_master_bdq_fixture.cpp"),
            *[str(firmware / "src" / name) for name in ("RemoteImuStream.cpp", "BdqV2Catalog.cpp", "BdqV2Writer.cpp")],
            *[str(common / name) for name in ("bodaqs_master_service.c", "bodaqs_master_protocol.c", "bodaqs_control.c", "bodaqs_control_exchange.c")],
            "-o", str(consumer),
        ], check=True)
        subprocess.run([str(consumer), str(can), str(bdq)], check=True)
        sys.path.insert(0, str(firmware.parent / "analysis"))
        from bodaqs_analysis.io_bdq import iter_bdq_stream_records, read_bdq
        info = read_bdq(bdq)
        assert info.detected_errors == ()
        samples = list(iter_bdq_stream_records(bdq, "can0_imu6"))
        assert len(samples) == 65
        assert [row["sequence"] for row in samples] == list(range(65))
        # Known input DRDY fixture: 300us steps, fixed first selected capture.
        assert [row["native_tick"] for row in samples] == [156400 + 300 * n for n in range(65)]
        for row in samples:
            assert [row[name] for name in ("ax", "ay", "az", "gx", "gy", "gz")] == [-32768, 32767, -1, -32768, 32767, -1]
            assert row["source_segment_id"] == 1
            assert row["status_flags"] & 24 == 24  # Estimated and unknown/degraded alignment.
        evidence = list(iter_bdq_stream_records(bdq, "can0_timing"))
        assert [row["kind"] for row in evidence] == [6, 6, 2, 1, 6]
        assert [row["boundary_event_kind"] for row in evidence] == [2, 7, 0, 0, 8]
        assert evidence[-1]["related_sequence"] == 64
        assert evidence[-1]["boundary_validity_flags"] & 512
        chunks = list(info.stream_data_chunks)
        assert min(c.sequence_number for c in chunks if c.stream_id == 3) < min(c.sequence_number for c in chunks if c.stream_id == 2)
        # The real node recovery path must survive transport, writer staging and
        # reopening with separate origins; clock continuity is not source continuity.
        subprocess.run([str(producer), "6"], env=environment, check=True)
        subprocess.run([str(consumer), str(can), str(bdq)], check=True)
        recovered = list(iter_bdq_stream_records(bdq, "can0_imu6"))
        assert {row["source_segment_id"] for row in recovered} == {1, 2}
        first = next(row for row in recovered if row["source_segment_id"] == 2)
        assert first["sequence"] == 0 and first["status_flags"] & 5 == 5
        assert not first["status_flags"] & 2  # recovery is not a software queue drop
        for row in recovered:
            assert [row[name] for name in ("ax", "ay", "az", "gx", "gy", "gz")] == [-32768, 32767, -1, -32768, 32767, -1]
        recovery_evidence = list(iter_bdq_stream_records(bdq, "can0_timing"))
        boundaries = [row for row in recovery_evidence if row["boundary_event_kind"]]
        assert [row["boundary_event_kind"] for row in boundaries] == [2, 7, 1, 4, 2, 5]
        for row in boundaries[2:]:
            assert row["sensor_clock_epoch"] == row["node_clock_epoch"] == 1
            assert not row["boundary_validity_flags"] & 28  # no invented loss counts
        assert boundaries[-1]["recovery_elapsed_us"] < 100000
    print("Production node adapter -> master fragments -> native BDQ -> independent reader passed")


if __name__ == "__main__":
    main()
