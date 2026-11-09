"""Run actual node SPI/capture/FIFO adapter output through master and BDQ writer."""
from pathlib import Path
import argparse
import os
import subprocess
import sys
import struct
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
        assert [row["kind"] for row in evidence] == [6, 6, 2, 1, 3, 6]
        assert [row["boundary_event_kind"] for row in evidence] == [2, 7, 0, 0, 0, 8]
        assert evidence[4]['kind'] == 3 and evidence[4]['node_sync_tick'] > 0
        assert evidence[4]['sync_sequence'] == 0 and evidence[4]['bridge_method'] == 0
        assert evidence[4]['original_message_type'] == 33 and evidence[4]['original_message_length'] == 24
        assert evidence[-1]["related_sequence"] == 64
        assert evidence[-1]["boundary_validity_flags"] & 512
        chunks = list(info.stream_data_chunks)
        assert min(c.sequence_number for c in chunks if c.stream_id == 3) < min(c.sequence_number for c in chunks if c.stream_id == 2)
        # Same real node/master/writer seam, with timing models deliberately
        # omitted: packets remain independently decodable by sequence.
        compact_can=temporary / "without-models.txt"
        compact_can.write_text("\n".join(line for line in can.read_text().splitlines()
            if not (line.split()[0]=="144" and line.split()[2][2:4] == "24"))+"\n")
        subprocess.run([str(consumer), str(compact_can), str(bdq), "compact"], check=True)
        from bodaqs_analysis.can_imu_packets import read_can_imu_packets
        decoded=read_can_imu_packets(bdq, "can0_imu6")
        assert [row["sequence"] for row in decoded["readings"]] == list(range(65))
        assert decoded["timing_status"] == "unreconstructed"
        assert decoded["ambiguous_packets"] == 0
        for row in decoded["readings"]:
            assert [row[name] for name in ("ax", "ay", "az", "gx", "gy", "gz")] == [-32768,32767,-1,-32768,32767,-1]
            assert "native_tick" not in row and "time_s" not in row
        # Missing optional raw clock observations still leaves START/STOP
        # sequence bounds; the axes do not depend on native timing coverage.
        no_clock=temporary / "without-clocks.txt"
        no_clock.write_text("\n".join(line for line in compact_can.read_text().splitlines()
            if not (line.split()[0]=="144" and line.split()[2][2:4]=="23"))+"\n")
        subprocess.run([str(consumer), str(no_clock), str(bdq), "compact"], check=True)
        assert [r["sequence"] for r in read_can_imu_packets(bdq,"can0_imu6")["readings"]] == list(range(65))
        saved=bdq.read_bytes()
        subprocess.run([str(consumer), str(no_clock), str(bdq), "compact", "duplicate"], check=True)
        repeated=read_can_imu_packets(bdq,"can0_imu6")
        assert repeated["duplicates"]==5 and len(repeated["readings"])==65
        subprocess.run([str(consumer), str(no_clock), str(bdq), "compact", "nonadjacent"], check=True)
        repeated=read_can_imu_packets(bdq,"can0_imu6")
        assert repeated["duplicates"]==5 and len(repeated["readings"])==65
        # The sample chunk is readable before its optional timing companions.
        # A torn tail retains exact axes and reports unresolved high sequence
        # bits, rather than guessing or requiring a predecessor timing write.
        cursor=32
        while cursor<len(saved):
            magic,version,kind,chunk_sequence,length,crc=struct.unpack_from("<4sHHIII",saved,cursor)
            end=cursor+20+length
            if kind==3 and struct.unpack_from("<H",saved,cursor+20)[0]==2:
                prefix_path=temporary / "compact-prefix.bdq"
                prefix_path.write_bytes(saved[:end])
                partial=read_can_imu_packets(prefix_path,"can0_imu6")
                assert 0<len(partial["readings"])<=65
                assert partial["ambiguous_packets"]>0
                assert all(r["sequence"] is None for r in partial["readings"])
                break
            cursor=end
        else:
            raise AssertionError("compact packet chunk missing")
        # Explicit independent packet sequences exercise low16 rollover, a
        # five-sample gap and a variable-length final packet.
        lines=compact_can.read_text().splitlines()
        prefix=[]
        for line in lines:
            ident,length,hexdata=line.split()
            if ident=="256":
                axes=bytes.fromhex(hexdata)[4:64]
                break
            payload=bytearray.fromhex(hexdata)
            if ident=="144" and payload[1] in (0x22,0x23):
                struct.pack_into("<I",payload,12 if payload[1]==0x22 else 20,65530)
            prefix.append(f"{ident} {length} {payload.hex()}")
        tail=next(bytearray.fromhex(line.split()[2]) for line in lines
            if line.split()[0]=="144" and line.split()[2][2:4]=="25" and bytes.fromhex(line.split()[2])[14]==8)
        struct.pack_into("<I",tail,28,65550)
        packets=[struct.pack("<HBB",seq%65536,1,count)+axes[:12*count]
                 for seq,count in ((65530,5),(65535,5),(65545,5),(65550,1))]
        wrap=temporary / "wrap-gap.txt"
        wrap.write_text("\n".join(prefix+[f"256 {len(p)} {p.hex()}" for p in packets]+[f"144 64 {tail.hex()}"])+"\n")
        subprocess.run([str(consumer), str(wrap), str(bdq), "compact"], check=True)
        result=read_can_imu_packets(bdq,"can0_imu6")
        assert [r["sequence"] for r in result["readings"]] == list(range(65530,65540))+list(range(65545,65551))
        assert {"source_segment_id":1,"first":65540,"last":65544,"count":5,"extent":"known"} in result["gaps"]
        # A longer normalized CAN fixture exercises periodic full-sequence
        # floors. Physical timestamp quality is outside this codec test.
        periodic_prefix=[]
        for line in prefix:
            ident,length,hexdata=line.split();payload=bytearray.fromhex(hexdata)
            if ident=="144" and payload[1] in (0x22,0x23):
                struct.pack_into("<I",payload,12 if payload[1]==0x22 else 20,0)
            periodic_prefix.append(f"{ident} {length} {payload.hex()}")
        anchor=next(bytearray.fromhex(line.split()[2]) for line in periodic_prefix
                    if line.split()[0]=="144" and line.split()[2][2:4]=="22")
        snapshot=next(bytearray.fromhex(line.split()[2]) for line in periodic_prefix
                    if line.split()[0]=="144" and line.split()[2][2:4]=="23")
        periodic_lines=list(periodic_prefix)
        for seq in range(0,1000,5):
            if seq and seq%300==0:
                struct.pack_into("<I",anchor,12,seq)
                struct.pack_into("<I",snapshot,20,seq)
                struct.pack_into("<I",snapshot,16,20+seq//300)
                periodic_lines += [f"144 32 {anchor.hex()}",f"144 64 {snapshot.hex()}"]
            payload=struct.pack("<HBB",seq,1,5)+axes
            periodic_lines.append(f"256 64 {payload.hex()}")
        struct.pack_into("<I",tail,28,999)
        periodic_lines.append(f"144 64 {tail.hex()}")
        periodic=temporary / "periodic.txt";periodic.write_text("\n".join(periodic_lines)+"\n")
        subprocess.run([str(consumer), str(periodic), str(bdq), "compact"], check=True)
        assert [r["sequence"] for r in read_can_imu_packets(bdq,"can0_imu6")["readings"]] == list(range(1000))
        # Two missing low16 cycles cannot be reconstructed from the same raw
        # low bits. Keep the axes and distinguish uncertainty from known loss.
        struct.pack_into("<I",anchor,12,131072);struct.pack_into("<I",snapshot,20,131072)
        struct.pack_into("<I",tail,28,131072)
        first=struct.pack("<HBB",0,1,1)+axes[:12]
        second=struct.pack("<HBB",10,1,1)+axes[:12]
        uncertain_lines=periodic_prefix+[f"256 16 {first.hex()}",f"256 16 {second.hex()}",
            f"144 32 {anchor.hex()}",f"144 64 {snapshot.hex()}",f"256 16 {first.hex()}"]
        uncertain=temporary / "multiwrap.txt"
        uncertain.write_text("\n".join(uncertain_lines+[f"144 64 {tail.hex()}"])+"\n")
        subprocess.run([str(consumer),str(uncertain),str(bdq),"compact"],check=True)
        unclear=read_can_imu_packets(bdq,"can0_imu6")
        assert [r["sequence"] for r in unclear["readings"]]==[None,None,131072]
        assert unclear["ambiguous_packets"]==2 and unclear["gaps"][-1]["extent"]=="uncertain"
        struct.pack_into("<I",tail,28,131071)
        uncertain.write_text("\n".join(uncertain_lines+[f"144 64 {tail.hex()}"])+"\n")
        subprocess.run([str(consumer),str(uncertain),str(bdq),"compact"],check=True)
        try:
            read_can_imu_packets(bdq,"can0_imu6")
        except ValueError as error:
            assert "conflicting compact sequence bounds" in str(error)
        else:
            raise AssertionError("contradictory STOP must not fabricate a full sequence")
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
        subprocess.run([str(consumer), str(can), str(bdq), "compact"], check=True)
        raw_recovery=read_can_imu_packets(bdq,"can0_imu6")
        assert {r["source_segment_id"] for r in raw_recovery["readings"]}=={1,2}
        assert raw_recovery["ambiguous_packets"]>0  # no normal terminal boundary
        for row in raw_recovery["readings"]:
            assert [row[axis] for axis in ("ax","ay","az","gx","gy","gz")]==[-32768,32767,-1,-32768,32767,-1]
    print("Production node adapter -> master fragments -> native BDQ -> independent reader passed")


if __name__ == "__main__":
    main()
