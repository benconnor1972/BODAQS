import copy
import math

import pandas as pd
import pytest

from bodaqs_analysis.rotary_counts import reconstruct_rotary_counts


def inputs(family='as5600', modulus=4096):
    descriptor = {'sensor_id': 'steering', 'stream_key': 'steering_native', 'record_size_bytes': 32,
                  'acquisition': {'payload_schema': 'bodaqs.rotary_counts.v1', 'sensor_family': family,
                                  'counts_per_turn': modulus, 'zero_count': 0, 'direction_sign': -1,
                                  'zero_provenance': 'configured_not_physical_proof'},
                  'channels': [{'field': name, 'storage_type': kind, 'byte_offset': offset}
                               for name, kind, offset in [('raw_angle', 'uint16', 12), ('auxiliary_validity', 'uint8', 19),
                                                         ('device_status', 'uint16', 16), ('status_flags', 'uint16', 8)]]}
    frame = pd.DataFrame({'sequence': [0, 1, 2, 3], 'native_tick': [100, 200, 300, 400],
                          'raw_angle': [modulus // 2, modulus - 1, 0, 8],
                          'status_flags': [0, 0, 32, 0], 'auxiliary_validity': [5, 5, 8, 5],
                          'device_status': [32, 32, 32, 16] if family == 'as5600' else [1, 1, 1, 2]})
    return {'streams': [descriptor]}, {'steering_native': frame}


@pytest.mark.parametrize('family,modulus', [('as5600', 4096), ('as5048b', 16384)])
def test_signed_half_turn_polarity_invalid_health_and_raw_preservation(family, modulus):
    catalog, frames = inputs(family, modulus)
    original = frames['steering_native'].copy(deep=True)
    result, metadata, warnings = reconstruct_rotary_counts(catalog, frames)
    derived = result['steering_native_engineering']
    assert derived.configured_angle_deg.iloc[0] == -180
    assert derived.configured_angle_deg.iloc[1] == 360 / modulus
    assert derived.device_angle_deg.iloc[2:].isna().all()
    assert not metadata['steering_native_engineering']['physical_zero_proven']
    assert warnings == []
    pd.testing.assert_frame_equal(original, frames['steering_native'])


def test_unknown_zero_retains_absolute_angle_without_inventing_calibration():
    catalog, frames = inputs()
    del catalog['streams'][0]['acquisition']['zero_count']
    derived, metadata, _ = reconstruct_rotary_counts(catalog, frames)
    assert 'configured_angle_deg' not in derived['steering_native_engineering']
    assert derived['steering_native_engineering'].device_angle_deg.iloc[0] == 180
    assert not metadata['steering_native_engineering']['configured_zero_available']


@pytest.mark.parametrize('fault', ['duplicate', 'offset', 'family', 'precision'])
def test_malformed_binding_preserves_raw_only(fault):
    catalog, frames = inputs()
    descriptor = catalog['streams'][0]
    if fault == 'duplicate':
        catalog['streams'].append(copy.deepcopy(descriptor))
    elif fault == 'offset':
        descriptor['channels'][0]['byte_offset'] = 13
    elif fault == 'family':
        descriptor['acquisition']['sensor_family'] = 'unknown'
    else:
        descriptor['acquisition']['counts_per_turn'] = 16384
    result, _, warnings = reconstruct_rotary_counts(catalog, frames)
    assert result == {} and warnings
