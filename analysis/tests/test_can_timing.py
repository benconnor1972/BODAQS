"""Worked acquisition-contract mappings through the actual BDQ parser."""
import struct

from bodaqs_analysis.io_bdq import bdq_to_stream_dataframes
from test_io_bdq_can_imu import _sample_descriptor, _evidence_descriptor
from test_io_bdq_v2 import FILE_HEADER, FILE_MAGIC_V2, _catalog, _metadata, _json_chunk, _chunk, _stream_data, _primary_record


def event(kind=2, **values):
    data = bytearray(224)
    struct.pack_into('<I', data, 4, 987654321)  # creation time must never enter mapping
    data[12] = kind
    defaults = {16: (1 << 0) | (1 << 1) | (1 << 2) | (1 << 4) | (1 << 12) | (1 << 20),
                20: 1, 28: 7, 32: 2, 36: 3, 44: 1, 88: 0,
                92: 1000, 96: 10, 100: 3, 108: 500, 112: 150000,
                172: 1, 176: 2}
    defaults.update({int(k): v for k, v in values.items()})
    for offset, value in defaults.items():
        struct.pack_into('<I', data, offset, value)
    data[202] = 1
    struct.pack_into('<H', data, 206, 5)
    return bytes(data)


def sample(sequence, tick, segment=1):
    return struct.pack('<IIHHIhhhhhh', sequence, tick, 16, 0, segment, 1, -2, 3, -4, 5, -6)


def decode(tmp_path, samples, events, acquisition=None, duplicate=None):
    events = [struct.pack('<I', index) + raw[4:] for index, raw in enumerate(events)]
    sd = _sample_descriptor()
    sd['stream_id'] = 3
    ed = _evidence_descriptor()
    if acquisition:
        ed['acquisition'].update(acquisition)
    streams = [_catalog()['streams'][0], ed, sd]
    if duplicate:
        import copy
        extra = copy.deepcopy(ed)
        extra.update(stream_id=4, stream_key='second_evidence')
        extra['acquisition']['provider_uid'] = '456'
        streams.append(extra)
    metadata = _metadata()
    metadata['stream_count'] = 3 + bool(duplicate)
    chunks = [_json_chunk(1, 0, metadata), _json_chunk(2, 1, dict(_catalog(), streams=streams)),
              _chunk(3, 2, _stream_data(1, 16, [_primary_record(0, 100, 20)], [])),
              _chunk(3, 3, _stream_data(2, 224, events, [])),
              _chunk(3, 4, _stream_data(3, 28, samples, []))]
    if duplicate:
        duplicate = [struct.pack('<I', index) + raw[4:] for index, raw in enumerate(duplicate)]
        chunks.append(_chunk(3, 5, _stream_data(4, 224, duplicate, [])))
    path = tmp_path / 'mapped.bdq'
    path.write_bytes(FILE_HEADER.pack(FILE_MAGIC_V2, 2, 0, 32, 0, 0, 0) + b''.join(chunks))
    return bdq_to_stream_dataframes(path)


def test_rational_model_retains_phase_and_unknown_logger_bounds(tmp_path):
    frame = decode(tmp_path, [sample(0, 1000), sample(1, 1003), sample(2, 1006), sample(3, 1010)], [event()])['remote_imu']
    assert frame['source_sequence_unwrapped'].tolist() == [0, 1, 2, 3]
    assert frame['modeled_node_tick'].tolist() == [1000, 1003, 1006, 1010]
    assert frame['clock_epoch'].tolist() == [3, 3, 3, 3]
    assert frame['logger_lower_us'].isna().all()
    assert frame['timing_status'].tolist() == ['native_association_unknown_bound'] * 4


def test_model_limits_use_acquisition_position_and_keep_delayed_revisions(tmp_path):
    frame = decode(tmp_path, [sample(0, 1000), sample(499, 5990), sample(500, 6000), sample(501, 6010)],
                   [event(**{'96': 10, '100': 1}), event(**{'44': 2, '88': 501, '92': 6010, '96': 10, '100': 1})])['remote_imu']
    assert frame['timing_model_id'].iloc[[0, 1, 3]].tolist() == [1, 1, 2]
    assert frame['timing_model_id'].isna().iloc[2]  # Exactly 500 records, deltas 0..499.
    frame = decode(tmp_path, [sample(499, 151000)],
                   [event(**{'96': 150000, '100': 499})])['remote_imu']
    assert frame['modeled_node_tick'].tolist() == [151000]  # 150000 us is inclusive.
    frame = decode(tmp_path, [sample(499, 151001)], [event(**{'96': 150001, '100': 499})])['remote_imu']
    assert frame['modeled_node_tick'].isna().all()


def test_source_wrap_and_explicit_reset_do_not_alias_segments(tmp_path):
    frame = decode(tmp_path, [sample(4294967294, 4294967290), sample(4294967295, 4294967293),
                              sample(0, 0), sample(1, 4), sample(0, 1000, 2)],
                   [event(**{'88': 4294967294, '92': 4294967290}),
                    event(**{'20': 2, '36': 4})])['remote_imu']
    assert frame['source_sequence_unwrapped'].tolist() == [4294967294, 4294967295, 4294967296, 4294967297, 0]
    assert frame['modeled_node_tick'].tolist() == [4294967290, 4294967293, 0, 4, 1000]
    assert frame['clock_epoch'].tolist() == [3, 3, 3, 3, 4]


def test_conflicting_canonical_model_is_reported(tmp_path):
    frame = decode(tmp_path, [sample(0, 1000)], [event(), event(**{'92': 2000})])['remote_imu']
    assert frame['timing_status'].tolist() == ['model_conflict']


def mapped_events():
    model = bytearray(event(**{'16': 1060887, '104': 2}))
    struct.pack_into('<H', model, 206, 7)
    sync = event(3, **{'16': 139, '40': 4, '64': 9, '68': 900, '140': 1})
    master = event(4, **{'16': 264, '40': 4, '64': 9, '72': 1900})
    bridge = event(5, **{'16': 4243464, '40': 4, '120': 10000, '128': 10020,
                         '136': 2000, '140': 1, '144': 7})
    return bytes(model), sync, master, bridge


BOUNDS = {'master_uid': '999', 'master_boot': '10', 'timing_bounds': {
    'node_sync_capture_us': 1, 'master_sync_capture_us': 1,
    'bridge_quantization_us': 1, 'node_master_drift_ppm': 0, 'master_logger_drift_ppm': 0}}


def test_causal_bridge_composes_literal_interval_and_deduplicates_shared_copies(tmp_path):
    events = mapped_events()
    frame = decode(tmp_path, [sample(0, 1000)], events, BOUNDS, duplicate=list(events[2:]))['remote_imu']
    assert frame['logger_lower_us'].tolist() == [9995]
    assert frame['logger_upper_us'].tolist() == [10025]
    assert frame['time_s'].tolist() == [0.00991]  # primary origin 100 us
    assert frame.attrs['bdq_clock_alignment']['shared_observation_count'] == 2
    assert frame.attrs['bdq_clock_alignment']['shared_conflict_count'] == 0


def test_conflicting_shared_bridge_keeps_bounds_unknown(tmp_path):
    events = mapped_events()
    conflict = bytearray(events[3])
    struct.pack_into('<I', conflict, 128, 10021)
    frame = decode(tmp_path, [sample(0, 1000)], events, BOUNDS, duplicate=[bytes(conflict)])['remote_imu']
    assert frame['logger_lower_us'].isna().all()
    assert frame.attrs['bdq_clock_alignment']['shared_conflict_count'] == 1


def test_unknown_bounds_do_not_discard_full_vector_axes(tmp_path):
    from bodaqs_analysis.imu import build_imu_streams
    frames = decode(tmp_path, [sample(0, 1000), sample(1, 1003)], [event()])
    signals = {f'{vector}_{axis}_raw': {'quantity': quantity, 'component': axis}
               for vector, quantity in [('accel', 'linear_acceleration_raw'), ('gyro', 'angular_velocity_raw')]
               for axis in 'xyz'}
    session = {'df': frames['primary'], 'stream_dfs': frames, 'meta': {'secondary_streams': {
        'remote_imu': {'schema': 'bdq.native_stream.v1', 'sensor': 'imu0', 'signals': signals,
                       'acquisition': dict(_sample_descriptor()['acquisition'], raw_axis_scaling={
                           'valid': True, 'accel_ug_per_count': 244, 'gyro_udps_per_count': 8750}),
                       'clock_alignment': frames['remote_imu'].attrs['bdq_clock_alignment']}}}}
    original = set(frames)
    build_imu_streams(session)
    derived = [f for name, f in session['stream_dfs'].items() if name not in original]
    assert len(derived) == 1
    assert derived[0]['accel_y_raw_count'].tolist() == [-2, -2]
    assert derived[0]['logger_time_s'].isna().all()
    assert derived[0]['source_sequence_unwrapped'].tolist() == [0, 1]
    import pytest
    assert derived[0]['accel_x_m_s2'].tolist() == pytest.approx([0.0023928226, 0.0023928226])


def test_composed_bounds_and_source_identity_survive_artifact_export(tmp_path):
    from bodaqs_analysis.artifacts import ArtifactStore, load_session_artifacts, save_session_artifacts
    frames = decode(tmp_path, [sample(0, 1000)], mapped_events(), BOUNDS)
    store = ArtifactStore(tmp_path / 'artifacts')
    save_session_artifacts(store, run_id='timing', session_id='node', session_df=frames['primary'],
                           session_meta={}, secondary_stream_dfs={k: v for k, v in frames.items() if k != 'primary'},
                           secondary_stream_meta={'remote_imu': {'descriptor': _sample_descriptor()}})
    restored = load_session_artifacts(store, run_id='timing', session_id='node')
    frame = restored['stream_dfs']['remote_imu']
    assert frame['logger_lower_us'].tolist() == [9995]
    assert frame['logger_upper_us'].tolist() == [10025]
    assert frame['source_segment_id'].tolist() == [1]
    assert frame['clock_epoch'].tolist() == [3]
    evidence = restored['stream_dfs']['node_evidence']
    assert evidence['native_tick'].tolist() == [987654321] * 4
    assert evidence['bridge_token'].tolist() == [0, 0, 0, 7]


def test_absent_uncertainty_and_unqualified_capture_keep_bounds_unknown(tmp_path):
    events = list(mapped_events())
    frame = decode(tmp_path, [sample(0, 1000)], events)['remote_imu']
    assert frame['logger_lower_us'].isna().all()
    model = bytearray(events[0])
    struct.pack_into('<H', model, 206, 5)
    frame = decode(tmp_path, [sample(0, 1000)], [bytes(model)] + events[1:], BOUNDS)['remote_imu']
    assert frame['logger_lower_us'].isna().all()
    assert frame['modeled_node_tick'].tolist() == [1000]




def test_model_input_capture_ordinal_wrap_does_not_reset_native_clock(tmp_path):
    frame = decode(tmp_path, [sample(0, 1000), sample(1, 1003)],
                   [event(**{'172': 4294967280, '176': 16})])['remote_imu']
    assert frame['modeled_node_tick'].tolist() == [1000, 1003]
    assert frame['clock_epoch'].tolist() == [3, 3]


def test_periodic_raw_sync_capture_cannot_prove_a_marker_pair(tmp_path):
    events = list(mapped_events())
    raw = bytearray(events[1])
    struct.pack_into('<H', raw, 140, 0)  # raw capture; absolute sequence unproven
    events[1] = bytes(raw)
    frame = decode(tmp_path, [sample(0, 1000)], events, BOUNDS)['remote_imu']
    assert frame['logger_lower_us'].isna().all()
    assert frame['timing_status'].tolist() == ['native_association_unknown_bound']
