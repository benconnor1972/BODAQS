import struct
import pytest
from test_io_bdq_v2 import FILE_HEADER,FILE_MAGIC_V2,_metadata,_primary_descriptor,_prefix_channels,_json_chunk,_chunk,_stream_data,_primary_record
from bodaqs_analysis.pipeline import load_bdq_session

FIELDS=[('latitude_e7','int32',12),('longitude_e7','int32',16),('altitude_msl_mm','int32',20),('ground_speed_mm_s','int32',24),('course_e5','int32',28),('horizontal_accuracy_mm','uint32',32),('vertical_accuracy_mm','uint32',36),('speed_accuracy_mm_s','uint32',40),('course_accuracy_e5','uint32',44),('receiver_tow_ms','uint32',48),('receiver_unix_seconds','uint32',52),('received_ms','uint32',56),('receiver_flags','uint16',60),('fix_type','uint8',62),('satellites','uint8',63)]

def recording(path,unknown=False,fix_type=3,latitude=-319512345,longitude=1158612345,status=None,duplicate=False,policy=0):
    descriptor=_primary_descriptor()
    descriptor.update(stream_id=2,stream_key='gps_native',sensor_id='gps',record_size_bytes=64,
        acquisition={'payload_schema':'bodaqs.gps_nav_pvt.v1','uart_port':0,'baud':38400,'update_rate_hz':10,
                     'stale_after_ms':1500,'validity_policy':policy,'quality_columns':2,
                     'emit_position':True,'emit_altitude':True,'emit_motion':True})
    descriptor['channels']=_prefix_channels()+[dict(field=name,quantity=name,unit='count',storage_type=kind,byte_offset=offset,**{'class':'signal'}) for name,kind,offset in FIELDS]
    if unknown: descriptor['channels'][3]['storage_type']='uint32'
    rows=[struct.pack('<IIHHiiiiiIIIIIIIHBB',seq,10000+seq*100000,(0 if flags==27 else 32) if status is None else status,0,
        latitude,longitude,-1234,12345,35912345,123,456,789,12345,604799999,0,10+seq*100,flags,fix_type,12)
        for seq,flags in [(0,27),(1,1)]]
    catalog=dict(schema_format='bdq.stream_catalog.v1',endianness='little',record_prefix={'format':'bdq.stream_record_prefix.v1','size_bytes':12},streams=[_primary_descriptor(),descriptor])
    if duplicate:
        catalog['streams'].append({**descriptor,'stream_id':3,'stream_key':'other_gps_native'})
    path.write_bytes(FILE_HEADER.pack(FILE_MAGIC_V2,2,0,FILE_HEADER.size,0,0,0)+b''.join([
        _json_chunk(1,0,{**_metadata(),'stream_count':2}),_json_chunk(2,1,catalog),
        _chunk(3,2,_stream_data(1,16,[_primary_record(0,10000,0)],[])),
        _chunk(3,3,_stream_data(2,64,rows,[]))]))
    return path

def test_normal_import_preserves_native_precision_and_masks_no_fix(tmp_path):
    session=load_bdq_session(recording(tmp_path/'gps.bdq'))
    raw=session['stream_dfs']['gps_native']
    assert list(raw.latitude_e7)==[-319512345]*2
    assert list(raw.receiver_tow_ms)==[604799999]*2
    derived=session['stream_dfs']['gps_native_engineering']
    assert derived.latitude.iloc[0]==pytest.approx(-31.9512345,abs=1e-10)
    assert derived.longitude.iloc[0]==pytest.approx(115.8612345,abs=1e-10)
    assert derived.altitude.iloc[0]==-1.234
    assert derived.speed.iloc[0]==12.345
    assert derived.course_over_ground.iloc[0]==359.12345
    assert derived.latitude.iloc[1:].isna().all()
    assert session['meta']['secondary_streams']['gps_native_engineering']['utc_alignment_proven'] is False

def test_unknown_native_schema_remains_raw(tmp_path):
    session=load_bdq_session(recording(tmp_path/'gps.bdq',unknown=True))
    assert 'gps_native_engineering' not in session['stream_dfs']

def test_native_engineering_stream_is_discoverable_by_normal_gps_semantics(tmp_path):
    from bodaqs_analysis.gps_semantics import refresh_gps_source_metadata, resolve_gps_columns
    session=load_bdq_session(recording(tmp_path/'gps.bdq'))
    refresh_gps_source_metadata(session)
    assert session['meta']['gps_sources']['preferred_source']=='gps_native_engineering'
    metadata=session['meta']['secondary_streams']['gps_native_engineering']
    columns=resolve_gps_columns(metadata)
    assert columns.heading=='course_over_ground'
    assert columns.receiver_time_of_week_unit=='s'


@pytest.mark.parametrize('fix_type',[0,1,5,255])
def test_unknown_or_non_position_fix_never_invents_position(tmp_path,fix_type):
    session=load_bdq_session(recording(tmp_path/'gps.bdq',fix_type=fix_type))
    assert session['stream_dfs']['gps_native_engineering'].latitude.isna().all()
    assert list(session['stream_dfs']['gps_native'].fix_type)==[fix_type]*2


@pytest.mark.parametrize('kwargs',[{'latitude':900000001},{'longitude':-1800000001},{'status':32}])
def test_invalid_position_or_source_error_is_preserved_without_trusted_values(tmp_path,kwargs):
    session=load_bdq_session(recording(tmp_path/'gps.bdq',**kwargs))
    assert session['stream_dfs']['gps_native_engineering'].latitude.isna().all()
    assert len(session['stream_dfs']['gps_native'])==2


def test_ambiguous_receiver_identity_remains_raw(tmp_path):
    session=load_bdq_session(recording(tmp_path/'gps.bdq',duplicate=True))
    assert 'gps_native_engineering' not in session['stream_dfs']
    assert list(session['stream_dfs']['gps_native'].latitude_e7)==[-319512345]*2


def test_explicit_latest_policy_preserves_known_no_fix_evidence(tmp_path):
    session=load_bdq_session(recording(tmp_path/'gps.bdq',policy=1,fix_type=0))
    frame=session['stream_dfs']['gps_native_engineering']
    assert list(frame.latitude)==[-31.9512345]*2
    assert not frame.valid.any()
