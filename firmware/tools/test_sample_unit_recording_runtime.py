"""Known node output through production master, unit custody, BDQ and offline decode."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import struct
import zlib


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='gcc')
    parser.add_argument('--compiler', default='g++')
    args = parser.parse_args()
    firmware = Path(__file__).resolve().parents[1]
    common = firmware / 'can-fd/common/protocol'
    node = firmware / 'can-fd/node'
    with tempfile.TemporaryDirectory(prefix='bodaqs-sample-unit-') as folder:
        folder = Path(folder)
        producer, consumer = folder / 'node.exe', folder / 'record.exe'
        wire, bdq = folder / 'can.txt', folder / 'record.bdq'
        subprocess.run([args.cc, '-std=c11', '-Wall', '-Wextra', '-Werror',
            '-I', str(node / 'test'), '-I', str(node / 'src'), '-I', str(common),
            str(node / 'test/test_acquisition.c'),
            *[str(node / 'src' / name) for name in ('imu_spi.c', 'imu_capture.c', 'imu_acquisition.c')],
            str(common / 'bodaqs_imu_disabled.c'), str(common / 'bodaqs_control.c'),
            '-o', str(producer)], check=True)
        subprocess.run([str(producer)], env=dict(os.environ, BODAQS_NODE_FIXTURE_OUT=str(wire)), check=True)
        subprocess.run([args.compiler, '-std=c++17', '-DBODAQS_SPI_MEASUREMENT_V3=1',
            '-Wall', '-Wextra', '-Werror', '-I', str(firmware / 'src'), '-I', str(common),
            str(firmware / 'test/node_master_bdq_fixture.cpp'),
            *[str(firmware / 'src' / name) for name in ('RemoteImuStream.cpp', 'BdqV2Catalog.cpp', 'BdqV2Writer.cpp')],
            *[str(common / name) for name in ('bodaqs_master_service.c', 'bodaqs_master_protocol.c',
                                           'bodaqs_control.c', 'bodaqs_control_exchange.c')],
            '-o', str(consumer)], check=True)
        subprocess.run([str(consumer), str(wire), str(bdq), 'units'], check=True)
        sys.path.insert(0, str(firmware.parent / 'analysis'))
        from bodaqs_analysis.can_imu_packets import read_can_imu_packets
        decoded = read_can_imu_packets(bdq, 'can0_imu6')
        assert decoded['source']['payload_schema'] == 'bodaqs.can_imu_units.v1'
        assert [row['sequence'] for row in decoded['readings']] == list(range(65))
        assert all([row[axis] for axis in ('ax', 'ay', 'az', 'gx', 'gy', 'gz')]
                   == [-32768, 32767, -1, -32768, 32767, -1] for row in decoded['readings'])
        assert decoded['ambiguous_packets'] == 0 and not decoded['gaps']
        from bodaqs_analysis.io_bdq import read_bdq, STREAM_DATA_HEADER_STRUCT
        # Corrupt accepted sample bytes, then recompute the BDQ chunk CRC. The
        # retained master checksum must still reject the altered readings.
        saved = bdq.read_bytes()
        damaged = bytearray(saved)
        cursor = 32
        while cursor < len(damaged):
            _, _, kind, _, length, _ = struct.unpack_from('<4sHHIII', damaged, cursor)
            payload = cursor + 20
            if kind == 3 and struct.unpack_from('<H', damaged, payload)[0] == 2:
                damaged[payload + STREAM_DATA_HEADER_STRUCT.size + 44 + 16 + 4] ^= 1
                struct.pack_into('<I', damaged, cursor+16, zlib.crc32(damaged[payload:payload+length]))
                break
            cursor = payload + length
        else:
            raise AssertionError('sample unit chunk missing')
        bdq.write_bytes(damaged)
        assert not read_bdq(bdq).detected_errors
        try:
            read_can_imu_packets(bdq, 'can0_imu6')
        except ValueError as error:
            assert 'upstream checksum' in str(error)
        else:
            raise AssertionError('buffer damage passed upstream verification')
        # A valid origin CRC must not authorize attaching readings to another
        # source epoch's sequence bounds. Simulate a semantic source mismatch.
        damaged = bytearray(saved)
        record = payload + STREAM_DATA_HEADER_STRUCT.size
        damaged[record+44+16+2] = 255
        total = struct.unpack_from('<H', damaged, record+40)[0]
        canonical = damaged[record+24:record+44] + damaged[record+44:record+44+total-4]
        struct.pack_into('<I', damaged, record+44+total-4, zlib.crc32(canonical))
        struct.pack_into('<I', damaged, cursor+16, zlib.crc32(damaged[payload:payload+length]))
        bdq.write_bytes(damaged)
        assert not read_bdq(bdq).detected_errors
        try:
            read_can_imu_packets(bdq, 'can0_imu6')
        except ValueError as error:
            assert 'source epoch' in str(error)
        else:
            raise AssertionError('foreign epoch was assigned to source sequence bounds')
        # Exercise actual node STOP with a nonempty partial packet. The default
        # 65-reading trace fills every packet and cannot detect tail flag drift.
        subprocess.run([str(producer)], env=dict(os.environ,
            BODAQS_NODE_FIXTURE_OUT=str(wire), BODAQS_NODE_FIXTURE_PARTIAL_STOP='1'), check=True)
        subprocess.run([str(consumer), str(wire), str(bdq), 'units'], check=True)
        tail = read_can_imu_packets(bdq, 'can0_imu6')
        assert [row['sequence'] for row in tail['readings']] == list(range(64))
        assert tail['ambiguous_packets'] == 0 and not tail['gaps']
        assert any(row['boundary_event_kind'] == 8 and
                   row['boundary_validity_flags'] & 1 and
                   row['source_segment_id'] == 1 and row['related_sequence'] == 63
                   for row in tail['raw_timing_observations'])
        print('Sample unit: real node fixture -> production master/RAM -> BDQ -> independent decode, including partial STOP PASS')


if __name__ == '__main__':
    main()
