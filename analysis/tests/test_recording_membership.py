import copy

from bodaqs_analysis.recording_membership import recording_membership


def header():
    return {'schema': 'bodaqs.recording_membership.v1', 'requested_mask': 3, 'selected_mask': 1,
            'excluded_mask': 2, 'qualified': False, 'unqualified_candidate': True, 'sources': [
                {'configured_index': 0, 'sensor_id': 'travel', 'sensor_type': 'analog_pot', 'exclusion_reason': 'none'},
                {'configured_index': 1, 'sensor_id': 'imu0', 'sensor_type': 'lsm6dso32x_imu', 'exclusion_reason': 'unavailable'}]}


def test_zero_data_exclusion_and_missing_footer_do_not_fabricate_final_membership():
    declared = header()
    result, warnings = recording_membership({'recording_membership': declared}, {})
    assert result['sources'][0]['selected_at_finalization'] is None
    assert result['sources'][0]['membership_outcome'] == 'unknown_without_valid_final_membership'
    assert result['sources'][1]['exclusion_declared']
    assert warnings == ['recording_source_excluded:imu0:unavailable']
    assert not result['sources'][1]['sample_count_inferred']


def test_final_selected_subset_is_explicit_and_header_is_preserved():
    initial = header()
    final = {'schema': initial['schema'], 'requested_mask': 3, 'selected_mask': 0, 'excluded_mask': 3}
    result, warnings = recording_membership({'recording_membership': initial}, {'recording_membership': final})
    assert result['sources'][0]['selected_at_finalization'] is False
    assert result['sources'][0]['exclusion_reason'] == 'not_admitted_at_finalization'
    assert len(warnings) == 2 and result['preparation'] == initial


def test_invalid_or_expanding_masks_preserve_declarations_with_unknown_outcome():
    initial = header()
    final = dict(initial, selected_mask=3, excluded_mask=0)
    result, warnings = recording_membership({'recording_membership': initial}, {'recording_membership': final})
    assert result['sources'][0]['selected_at_finalization'] is None
    assert 'recording_membership_invalid:finalization_masks' in warnings
    invalid = copy.deepcopy(initial)
    invalid['requested_mask'] = True
    assert recording_membership({'recording_membership': invalid}, {})[1] == ['recording_membership_invalid:preparation_masks']


def test_historical_files_and_ambiguous_source_identity():
    assert recording_membership({}, {}) == ({}, [])
    initial = header()
    initial['sources'].append(copy.deepcopy(initial['sources'][0]))
    result, warnings = recording_membership({'recording_membership': initial}, {})
    assert len(result['sources']) == 2
    assert 'recording_membership_invalid:source_identity' in warnings


def test_normal_import_exposes_zero_data_sources_and_keeps_unknown_final_membership(tmp_path):
    from test_io_bdq_v2 import (FILE_HEADER, FILE_MAGIC_V2, _metadata, _catalog, _primary_descriptor,
                               _primary_record, _json_chunk, _chunk, _stream_data)
    from bodaqs_analysis.pipeline import load_bdq_session
    path = tmp_path / 'best-effort.bdq'
    catalog = dict(_catalog(), streams=[_primary_descriptor()])
    path.write_bytes(FILE_HEADER.pack(FILE_MAGIC_V2, 2, 0, FILE_HEADER.size, 0, 0, 0) + b''.join([
        _json_chunk(1, 0, dict(_metadata(), stream_count=1, recording_membership=header())),
        _json_chunk(2, 1, catalog),
        _chunk(3, 2, _stream_data(1, 16, [_primary_record(0, 1000, 0)], []))]))
    session = load_bdq_session(path)
    inventory = session['meta']['recording_membership']['sources']
    assert inventory[1]['sensor_id'] == 'imu0' and inventory[1]['exclusion_declared']
    assert inventory[0]['selected_at_finalization'] is None
