"""Recorded integer tracking evidence through the normal importer."""
import struct

import pytest

from test_io_bdq_v2 import (
    FILE_HEADER, FILE_MAGIC_V2, _metadata, _primary_descriptor, _prefix_channels,
    _json_chunk, _chunk, _stream_data, _primary_record,
)
from bodaqs_analysis.pipeline import load_bdq_session


def recording(path, *, calibrated=True, invert=False, digital=False, unknown_domain=False, first_quality=33, reverse=False):
    metadata={**_metadata(), 'stream_count': 2, 'recording_configuration': {
        'schema':'bodaqs.recording_configuration.v1', 'sensors': [{
            'sensor_id':'travel', 'sensor_type':'as5600_string_pot_analog',
            'stream_key':'travel_counts', 'raw_fields':['wrapped_count','unwrapped_count'],
            'count_domain':{'id':'string_pot_counts_v1'}, 'calibration':{
                'available':calibrated, 'model':'string_pot_geometry_v1',
                'installed_zero_count':0, 'sensor_zero_count':0, 'sensor_full_count':4096,
                'sensor_full_travel':100., 'invert':invert, 'output_unit':'mm'}}]}}
    sensor=metadata['recording_configuration']['sensors'][0]
    if digital:
        sensor['sensor_type']='as5600_string_pot_i2c'
    if unknown_domain:
        sensor['count_domain']=None
    descriptor=_primary_descriptor()
    descriptor.update(stream_id=2,stream_key='travel_counts',sensor_id='travel',record_size_bytes=24,
                      acquisition={'payload_schema':'bodaqs.string_pot_counts.v1',
                                   'counts_per_turn':4096,'wrap_threshold_counts':2048,
                                   'assume_turn0_at_start':False})
    descriptor['channels']=_prefix_channels()+[
        dict(field=name,quantity=name,unit='count',storage_type=kind,byte_offset=offset,**{'class':'signal'})
        for name,kind,offset in [('wrapped_count','uint16',12),('tracking_quality','uint16',14),
                                ('unwrapped_count','int32',16),('tracking_epoch','uint32',20)]]
    if digital:
        descriptor['record_size_bytes']=40
        descriptor['channels']+=[dict(field=name,quantity=name,unit='count',storage_type=kind,byte_offset=offset,**{'class':'diagnostic'})
            for name,kind,offset in [('angle_count','uint16',24),('device_status','uint8',26),('agc','uint8',27),
                                    ('magnitude','uint16',28),('auxiliary_validity','uint16',30),
                                    ('read_failures','uint32',32),('diagnostic_failures','uint32',36)]]
    rows=[struct.pack('<IIHHHHiI',seq,10000+seq*5000,0,0,wrapped,quality,unwrapped,1)
          for seq,wrapped,quality,unwrapped in [(0,4090,first_quality,4090),(1,2000,3,4090),(3,3,13,4099),(4,4,9,4100)]]
    if reverse:
        rows=[struct.pack('<IIHHHHiI',seq,10000+seq*5000,0,0,wrapped,quality,unwrapped,1)
              for seq,wrapped,quality,unwrapped in [(0,3,33,3),(1,4090,1,-6)]]
    if digital:
        rows=[row+struct.pack('<HBBHHII',1000,32,3,999,7,0,0) for row in rows]
    catalog=dict(schema_format='bdq.stream_catalog.v1',endianness='little',
                 record_prefix={'format':'bdq.stream_record_prefix.v1','size_bytes':12},
                 streams=[_primary_descriptor(),descriptor])
    path.write_bytes(FILE_HEADER.pack(FILE_MAGIC_V2,2,0,FILE_HEADER.size,0,0,0)+b''.join([
        _json_chunk(1,0,metadata),_json_chunk(2,1,catalog),
        _chunk(3,2,_stream_data(1,16,[_primary_record(0,10000,0)],[])),
        _chunk(3,3,_stream_data(2,descriptor['record_size_bytes'],rows,[]))]))
    return path


@pytest.mark.parametrize('invert',[False,True])
def test_normal_import_preserves_tracking_and_derives_only_supported_values(tmp_path,invert):
    session=load_bdq_session(recording(tmp_path/'counts.bdq',invert=invert))
    raw=session['stream_dfs']['travel_counts']
    assert list(raw.unwrapped_count)==[4090,4090,4099,4100]
    derived=session['stream_dfs']['travel_counts_engineering']
    assert derived.displacement.iloc[0]==pytest.approx((-1 if invert else 1)*99.853515625)
    assert derived.displacement.iloc[1:].isna().all()
    provenance=session['meta']['secondary_streams']['travel_counts_engineering']
    assert provenance['source_stream']=='travel_counts'
    assert provenance['physical_turns_proven'] is False


def test_uncalibrated_recording_remains_raw_with_tracking_evidence(tmp_path):
    session=load_bdq_session(recording(tmp_path/'counts.bdq',calibrated=False))
    assert 'travel_counts_engineering' not in session['stream_dfs']
    assert list(session['stream_dfs']['travel_counts'].tracking_quality)==[33,3,13,9]


def test_i2c_native_diagnostics_survive_normal_import(tmp_path):
    session=load_bdq_session(recording(tmp_path/'counts.bdq',digital=True))
    raw=session['stream_dfs']['travel_counts']
    assert list(raw.angle_count)==[1000]*4
    assert list(raw.auxiliary_validity)==[7]*4
    assert session['stream_dfs']['travel_counts_engineering'].displacement.iloc[0]==99.853515625


def test_unknown_count_domain_stays_raw(tmp_path):
    session=load_bdq_session(recording(tmp_path/'counts.bdq',unknown_domain=True))
    assert 'travel_counts' in session['stream_dfs']
    assert 'travel_counts_engineering' not in session['stream_dfs']


@pytest.mark.parametrize('quality',[1,129])
def test_missing_reset_or_unknown_tracking_flags_do_not_invent_values(tmp_path,quality):
    session=load_bdq_session(recording(tmp_path/'counts.bdq',first_quality=quality))
    assert session['stream_dfs']['travel_counts_engineering'].displacement.isna().all()


def test_reverse_wrap_retains_signed_counts_and_geometry(tmp_path):
    session=load_bdq_session(recording(tmp_path/'counts.bdq',reverse=True))
    assert list(session['stream_dfs']['travel_counts'].unwrapped_count)==[3,-6]
    assert list(session['stream_dfs']['travel_counts_engineering'].displacement)==[.0732421875,-.146484375]
