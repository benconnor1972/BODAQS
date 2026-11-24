"""Reconstruct rotary angles from source-bound, embedded recording settings."""
from collections import Counter
from collections.abc import Mapping

import pandas as pd


def reconstruct_rotary_counts(catalog, frames):
    derived, provenance, warnings = {}, {}, []
    descriptors = catalog.get('streams', [])
    identities = Counter(d.get('sensor_id') for d in descriptors
                         if isinstance(d, Mapping) and isinstance(d.get('sensor_id'), str))
    for descriptor in descriptors:
        if not isinstance(descriptor, Mapping):
            continue
        acquisition = descriptor.get('acquisition')
        if not isinstance(acquisition, Mapping) or acquisition.get('payload_schema') != 'bodaqs.rotary_counts.v1':
            continue
        key = descriptor.get('stream_key')
        frame = frames.get(key)
        if not isinstance(frame, pd.DataFrame):
            continue
        fields = {c.get('field'): (c.get('storage_type'), c.get('byte_offset'))
                  for c in descriptor.get('channels', []) if isinstance(c, Mapping)}
        expected = {'raw_angle': ('uint16', 12), 'auxiliary_validity': ('uint8', 19),
                    'status_flags': ('uint16', 8), 'device_status': ('uint16', 16)}
        family, modulus = acquisition.get('sensor_family'), acquisition.get('counts_per_turn')
        if (not descriptor.get('sensor_id') or identities[descriptor['sensor_id']] != 1
                or descriptor.get('record_size_bytes') != 32
                or type(modulus) is not int or (family, modulus) not in (('as5600', 4096), ('as5048b', 16384))
                or any(fields.get(name) != kind or name not in frame for name, kind in expected.items())):
            warnings.append(f'rotary_raw_only:{key}:invalid_source_binding')
            continue
        output_key = key + '_engineering'
        if output_key in frames:
            warnings.append(f'rotary_raw_only:{key}:stream_key_collision')
            continue
        result = frame[[c for c in ('sequence', 'native_tick', 'time_s', 'status_flags') if c in frame]].copy()
        validity = frame.auxiliary_validity.astype('uint64')
        invalid = ((validity & 1) == 0) | ((validity & 8) != 0) | (validity > 15)
        invalid |= (frame.status_flags.astype('uint64') & 32) != 0
        invalid |= (frame.raw_angle < 0) | (frame.raw_angle >= modulus)
        # A diagnostic snapshot can be older than RAW; preserve its independent
        # validity and suppress known bad health without calling it synchronous.
        diagnostics = (validity & 4) != 0
        health = frame.device_status.astype('uint64')
        if family == 'as5600':
            invalid |= diagnostics & (((health & 32) == 0) | ((health & 24) != 0))
        else:
            invalid |= diagnostics & (((health & 1) == 0) | ((health & 14) != 0))
        result['device_angle_deg'] = (frame.raw_angle.astype('float64') * (360 / modulus)).mask(invalid)
        zero, direction = acquisition.get('zero_count'), acquisition.get('direction_sign')
        configured = (type(zero) is int and 0 <= zero < modulus
                      and type(direction) is int and direction in (-1, 1)
                      and acquisition.get('zero_provenance') == 'configured_not_physical_proof')
        if configured:
            delta = frame.raw_angle.astype('int64') - zero
            # Preserve firmware's positive and negative exact-half-turn choices.
            delta = delta.where(delta <= modulus // 2, delta - modulus)
            delta = delta.where(delta >= -modulus // 2, delta + modulus)
            result['configured_angle_deg'] = (delta * (direction * 360 / modulus)).mask(invalid)
        derived[output_key] = result
        provenance[output_key] = {'source_stream': key, 'derived': True, 'unit': 'deg',
                                  'calibration_source': 'embedded_stream_catalog',
                                  'physical_zero_proven': False, 'configured_zero_available': configured,
                                  'diagnostics_synchronous_with_raw': False}
    return derived, provenance, warnings
