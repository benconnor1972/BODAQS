"""Normal-import view of verified retained CAN units.

Observation time is deliberately not used as acquisition time. Original units
and timing evidence remain separate streams for subsequent reconstruction.
"""
import struct

import pandas as pd

from .can_imu_packets import AXES, read_can_imu_packets


def _profile(source):
    try:
        effective = bytes.fromhex(source['effective_descriptor_hex'])
        profile, version = struct.unpack_from('<HH', effective, 40)
        rate = {1: 3333, 2: 1667, 3: 833}.get(profile)
        if (version != 1 or rate is None
                or source.get('requested_profile') != f'imu6_{rate}_32g_2000dps_v1'
                or struct.unpack_from('<IIII', effective, 48) != (rate, 1, rate, 1)):
            return None, None
        nominal = source['nominal_sensitivities']
        rational = tuple(nominal[key] for key in ('accel_g_numerator', 'accel_g_denominator',
                                                 'gyro_dps_numerator', 'gyro_dps_denominator'))
        if (not source.get('raw_axis_scaling', {}).get('valid')
                or not source.get('known_mask', 0) & 16
                or source.get('historical_mask', 0) & 16
                or any(type(value) is not int or value <= 0 for value in rational)
                or struct.unpack_from('<IIII', effective, 72) != rational):
            return rate, None
        return rate, (rational[0]/rational[1], rational[2]/rational[3])
    except (KeyError, TypeError, ValueError, struct.error):
        return None, None


def _delivery(decoded):
    result = dict(expected=None, retained=len(decoded['readings']), missing=None)
    source = decoded['source']
    try:
        if any(int(source[key]) <= 0 for key in ('provider_uid', 'master_uid', 'node_boot',
               'master_boot', 'recording_id', 'control_session', 'measurement_context')):
            return result
    except (KeyError, TypeError, ValueError):
        return result
    if decoded['file_errors'] or decoded['ambiguous_packets']:
        return result
    bounds = {}
    for row in decoded['raw_timing_observations']:
        kind = row['boundary_event_kind']
        if kind not in (2, 8) or not row['boundary_validity_flags'] & 1:
            continue
        segment = bounds.setdefault(row['source_segment_id'], {})
        value = row['related_sequence']
        if kind in segment and segment[kind] != value:
            return result
        segment[kind] = value
    if not bounds or any(2 not in b or 8 not in b or b[8] < b[2] for b in bounds.values()):
        return result
    unique = set()
    for row in decoded['readings']:
        segment, sequence = row['source_segment_id'], row['sequence']
        if segment not in bounds or sequence is None or not bounds[segment][2] <= sequence <= bounds[segment][8]:
            return result
        unique.add((segment, sequence))
    expected = sum(b[8]-b[2]+1 for b in bounds.values())
    return dict(expected=expected, retained=len(unique), missing=expected-len(unique))


def decode_can_imu_streams(path, catalog):
    """Return sample frames, provenance and per-source warnings; never discard raw units."""
    frames, metadata, warnings = {}, {}, []
    for descriptor in catalog.get('streams', []):
        source = descriptor.get('acquisition', {})
        if source.get('payload_schema') not in ('bodaqs.can_imu_units.v1', 'bodaqs.can_imu_units.v2',
                                                 'bodaqs.can_imu_packets.v1'):
            continue
        key = descriptor['stream_key']
        try:
            decoded = read_can_imu_packets(path, key)
        except (ValueError, KeyError, TypeError, OverflowError, struct.error) as error:
            warnings.append(f'can_imu_unverified:{key}:{error}')
            continue
        sample_key = key + '_samples'
        # Avoid silently overwriting a physical stream with a derived view.
        if any(d.get('stream_key') == sample_key for d in catalog.get('streams', [])):
            warnings.append(f'can_imu_unverified:{key}:sample stream key collision')
            continue
        frame = pd.DataFrame(decoded['readings'], columns=[
            'source_segment_id', 'sequence', 'sequence_low', 'packet_observation', *AXES])
        frame['sequence'] = pd.array(frame['sequence'], dtype='UInt32')
        frame['time_s'] = float('nan')
        rate, scaling = _profile(source)
        if scaling is not None:
            for axis in AXES:
                frame[axis + ('_g' if axis.startswith('a') else '_dps')] = frame[axis] * scaling[0 if axis.startswith('a') else 1]
        else:
            warnings.append(f'can_imu_scaling_unavailable:{key}')
        frames[sample_key] = frame
        metadata[sample_key] = dict(
            decoded=True, source_stream=key, source_identity=dict(source),
            native_profile_hz=rate, clock_alignment={'state': 'unknown'},
            timing_status=decoded['timing_status'], gaps=decoded['gaps'],
            duplicates=decoded['duplicates'], ambiguous_packets=decoded['ambiguous_packets'],
            source_bounded_delivery=_delivery(decoded))
    return frames, metadata, warnings
