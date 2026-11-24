"""Independent wire fixtures exercise the normal importer, including upstream CRC."""
import struct
import zlib

import pytest

from test_io_bdq_v2 import (
    FILE_HEADER, FILE_MAGIC_V2, _metadata, _primary_descriptor, _prefix_channels,
    _json_chunk, _chunk, _stream_data, _primary_record,
)
from bodaqs_analysis.pipeline import load_bdq_session


def recording(path, *, rate=3333, stop=True, corrupt=False, epoch=5,
              terminal=1, claimed_profile=None, boot=9, first=0):
    profile = {3333: 1, 1667: 2, 833: 3}[rate]
    effective = bytearray(192)
    struct.pack_into('<HH', effective, 40, profile, 1)
    struct.pack_into('<IIII', effective, 48, rate, 1, rate, 1)
    struct.pack_into('<IIII', effective, 72, 122, 125000, 7, 100)
    source = dict(node_address=0, node_boot=9, provider_uid='42', master_uid='84',
                  master_boot='11', recording_id='300', control_session='200',
                  measurement_context='400', related_sample_stream_id=2,
                  known_mask=16, historical_mask=0,
                  requested_profile=f'imu6_{rate}_32g_2000dps_v1',
                  effective_descriptor_hex=effective.hex(),
                  raw_axis_scaling={'valid': True}, nominal_sensitivities=dict(
                      accel_g_numerator=122, accel_g_denominator=125000,
                      gyro_dps_numerator=7, gyro_dps_denominator=100))
    if claimed_profile is not None:
        source['requested_profile'] = claimed_profile
    source['node_boot'] = boot

    def descriptor(key, sid, size, schema, layout, names):
        result = _primary_descriptor()
        result.update(stream_key=key, stream_id=sid, record_size_bytes=size,
                      transport='can', clock_id='logger_monotonic_creation',
                      acquisition={**source, 'payload_schema': schema})
        result['timebase'] = {**result['timebase'], 'clock_relation': 'independent'}
        result['channels'] = _prefix_channels() + [dict(
            field=names.get(offset, f'field_{offset}'), storage_type=kind,
            byte_offset=offset, quantity='diagnostic', unit='count', **{'class': 'diagnostic'})
            for offset, kind in sorted(layout.items())]
        return result

    unit_layout = {o: 'uint32' for o in (12, 16, 24, 28, 32)}
    unit_layout.update({36: 'uint8', 37: 'uint8', 38: 'uint8', 40: 'uint16'})
    unit_layout.update({o: 'uint32' for o in range(44, 516, 4)})
    names = dict(zip((12, 16, 24, 28, 32, 36, 37, 38, 40),
                    ('source_segment_id', 'sequence_floor', 'context_low', 'context_high',
                     'object_id', 'node', 'object_class', 'direction', 'total')))
    names.update({44+4*i: f'unit_word{i}' for i in range(118)})
    units = descriptor('can0_imu6', 2, 516, 'bodaqs.can_imu_units.v2', unit_layout, names)
    evidence_layout = {o: 'uint32' for o in (
        *range(16, 84, 4), *range(88, 140, 4), *range(144, 168, 4),
        172, 176, 180, 188, 192, 196)}
    evidence_layout.update({o: 'uint8' for o in (12,13,14,84,85,86,87,168,184,185,186,200,201,202)})
    evidence_layout.update({o: 'uint16' for o in (140,142,170,204,206,208)})
    evidence = descriptor('can0_timing', 3, 224, 'bodaqs.can_timing_evidence.v1',
                          evidence_layout, {12:'evidence_type',14:'stream_epoch',20:'source_segment_id',
                                            24:'related_sequence',200:'boundary_event_kind',208:'boundary_validity_flags'})
    data = bytearray(472)
    struct.pack_into('<HBBIIHH', data, 0, 2, 1, 0, 9, 0, 1, 0)
    struct.pack_into('<HBB', data, 16, first, 5, 0x42)
    struct.pack_into('<12h', data, 20, -32768,32767,-1,1,-2,3,100,-200,300,-400,500,-600)
    checksum = zlib.crc32(struct.pack('<QIBBBxHxx', 400,1,0,1,1,84) + data[:80])
    struct.pack_into('<I', data, 80, checksum)
    if corrupt:
        data[20] ^= 1
    unit = bytearray(516)
    struct.pack_into('<IIHH', unit, 0, 0,10000,8,0)
    for offset, value in ((12,1),(16,first),(24,400),(32,1)):
        struct.pack_into('<I', unit, offset, value)
    unit[37:39] = b'\x01\x01'
    struct.pack_into('<H', unit, 40, 84)
    unit[44:] = data
    boundaries = []
    for index, kind in enumerate((2,8) if stop else (2,)):
        row = bytearray(224)
        struct.pack_into('<IIHH', row, 0, index,10000+index,0,0)
        row[12], row[14], row[200] = 1, epoch, kind
        struct.pack_into('<I', row, 20, 1)
        struct.pack_into('<I', row, 24, terminal if kind == 8 else first)
        struct.pack_into('<H', row, 208, 1)
        boundaries.append(bytes(row))
    metadata = {**_metadata(), 'stream_count': 3}
    catalog = dict(schema_format='bdq.stream_catalog.v1', endianness='little',
                   record_prefix=dict(format='bdq.stream_record_prefix.v1', size_bytes=12),
                   streams=[_primary_descriptor(), units, evidence])
    path.write_bytes(FILE_HEADER.pack(FILE_MAGIC_V2,2,0,FILE_HEADER.size,0,0,0) + b''.join([
        _json_chunk(1,0,metadata), _json_chunk(2,1,catalog),
        _chunk(3,2,_stream_data(1,16,[_primary_record(0,10000,1)],[])),
        _chunk(3,3,_stream_data(2,516,[bytes(unit)],[])),
        _chunk(3,4,_stream_data(3,224,boundaries,[]))]))
    return path


@pytest.mark.parametrize('rate', [833,1667,3333])
def test_normal_import_decodes_native_units(tmp_path, rate):
    session = load_bdq_session(recording(tmp_path/'test.bdq', rate=rate))
    frame = session['stream_dfs']['can0_imu6_samples']
    assert list(frame.ax) == [-32768,100]
    assert list(frame.sequence) == [0,1]
    assert frame.time_s.isna().all()
    assert frame.ax_g.iloc[1] == pytest.approx(.0976)
    meta = session['meta']['secondary_streams']['can0_imu6_samples']
    assert meta['source_bounded_delivery']['expected'] == 2
    assert meta['source_bounded_delivery']['missing'] == 0
    assert meta['native_profile_hz'] == rate


def test_missing_stop_keeps_counts_without_claiming_completeness(tmp_path):
    session = load_bdq_session(recording(tmp_path/'test.bdq', stop=False))
    assert len(session['stream_dfs']['can0_imu6_samples']) == 2
    meta = session['meta']['secondary_streams']['can0_imu6_samples']
    assert meta['source_bounded_delivery']['expected'] is None


@pytest.mark.parametrize('options', [{'corrupt': True}, {'epoch': 6}, {'boot': 10}])
def test_invalid_source_preserves_raw_evidence_without_verified_axes(tmp_path, options):
    session = load_bdq_session(recording(tmp_path/'test.bdq', **options))
    assert 'can0_imu6' in session['stream_dfs']
    assert 'can0_imu6_samples' not in session['stream_dfs']
    assert any('can_imu_unverified' in str(w) for w in session['qc']['warnings'])


def test_terminal_tail_loss_is_counted(tmp_path):
    session = load_bdq_session(recording(tmp_path/'test.bdq', terminal=3))
    delivery = session['meta']['secondary_streams']['can0_imu6_samples']['source_bounded_delivery']
    assert delivery == {'expected': 4, 'retained': 2, 'missing': 2}
    gaps = session['meta']['secondary_streams']['can0_imu6_samples']['gaps']
    assert gaps == [{'source_segment_id': 1, 'first': 2, 'last': 3, 'count': 2, 'extent': 'known'}]


def test_mismatched_profile_is_not_presented_as_applied_or_scaled(tmp_path):
    session = load_bdq_session(recording(tmp_path/'test.bdq', claimed_profile='imu6_833_32g_2000dps_v1'))
    frame = session['stream_dfs']['can0_imu6_samples']
    assert list(frame.ax) == [-32768,100]
    assert 'ax_g' not in frame
    assert session['meta']['secondary_streams']['can0_imu6_samples']['native_profile_hz'] is None


def test_nonzero_start_does_not_invent_pre_session_loss(tmp_path):
    session = load_bdq_session(recording(tmp_path/'test.bdq', first=3, terminal=4))
    meta = session['meta']['secondary_streams']['can0_imu6_samples']
    assert meta['gaps'] == []
    assert meta['source_bounded_delivery'] == {'expected': 2, 'retained': 2, 'missing': 0}
