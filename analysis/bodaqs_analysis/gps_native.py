"""Receiver-native GPS conversion; receive timestamps never prove GNSS/RTC alignment."""
from collections import Counter
from collections.abc import Mapping
import pandas as pd

_FIELDS = {
    'latitude_e7': ('int32', 12), 'longitude_e7': ('int32', 16),
    'altitude_msl_mm': ('int32', 20), 'ground_speed_mm_s': ('int32', 24),
    'course_e5': ('int32', 28), 'horizontal_accuracy_mm': ('uint32', 32),
    'vertical_accuracy_mm': ('uint32', 36), 'speed_accuracy_mm_s': ('uint32', 40),
    'course_accuracy_e5': ('uint32', 44), 'receiver_tow_ms': ('uint32', 48),
    'receiver_unix_seconds': ('uint32', 52), 'received_ms': ('uint32', 56),
    'receiver_flags': ('uint16', 60), 'fix_type': ('uint8', 62), 'satellites': ('uint8', 63),
}


def reconstruct_gps(catalog, frames):
    result, provenance, warnings = {}, {}, []
    descriptors = catalog.get('streams', [])
    identities = Counter(d.get('sensor_id') for d in descriptors
                         if isinstance(d, Mapping) and isinstance(d.get('sensor_id'), str))
    for descriptor in descriptors:
        acquisition = descriptor.get('acquisition', {})
        if not isinstance(acquisition, Mapping) or acquisition.get('payload_schema') != 'bodaqs.gps_nav_pvt.v1':
            continue
        key = descriptor['stream_key']
        frame = frames.get(key)
        if not isinstance(frame, pd.DataFrame):
            continue
        fields = {c.get('field'): (c.get('storage_type'), c.get('byte_offset'))
                  for c in descriptor.get('channels', []) if isinstance(c, Mapping)}
        if (descriptor.get('record_size_bytes') != 64 or not descriptor.get('sensor_id')
                or identities[descriptor['sensor_id']] != 1
                or any(fields.get(name) != kind or name not in frame for name, kind in _FIELDS.items())
                or type(acquisition.get('validity_policy')) is not int
                or acquisition['validity_policy'] not in (0, 1, 2)
                or type(acquisition.get('stale_after_ms')) is not int
                or acquisition['stale_after_ms'] < 0
                or any(type(acquisition.get(k)) is not bool for k in ('emit_position', 'emit_altitude', 'emit_motion'))):
            warnings.append(f'gps_raw_only:{key}:unknown_representation_or_configuration')
            continue
        derived_key = key + '_engineering'
        if derived_key in frames:
            warnings.append(f'gps_raw_only:{key}:stream_key_collision')
            continue
        derived = frame.loc[:, [c for c in ('time_s', 'sequence', 'native_tick', 'status_flags',
                                            'receiver_flags', 'fix_type', 'satellites', 'receiver_tow_ms') if c in frame]].copy()
        flags = frame.receiver_flags.astype('uint64')
        have = (flags & 1) != 0
        known = (flags <= 31) & frame.fix_type.between(0, 5)
        coordinates = frame.latitude_e7.between(-900000000, 900000000) & frame.longitude_e7.between(-1800000000, 1800000000)
        source_ok = (frame.status_flags.astype('uint64') & 32) == 0
        valid = have & known & coordinates & source_ok & ((flags & 6) == 2) & frame.fix_type.isin([2, 3, 4])
        derived['valid'] = valid
        derived['receiver_time_of_week_s'] = frame.receiver_tow_ms.astype('float64') / 1000
        # Each row is one newly received observation; no upsampling, repeat-last, or stale holding.
        allowed = (have & known & coordinates) if acquisition['validity_policy'] == 1 else valid
        conversions = []
        if acquisition['emit_position']:
            conversions += [('latitude', 'latitude_e7', 1e7), ('longitude', 'longitude_e7', 1e7)]
        if acquisition['emit_altitude']:
            conversions += [('altitude', 'altitude_msl_mm', 1000)]
        if acquisition['emit_motion']:
            conversions += [('speed', 'ground_speed_mm_s', 1000), ('course_over_ground', 'course_e5', 1e5)]
        for output, source, divisor in conversions:
            derived[output] = (frame[source].astype('float64') / divisor).where(allowed)
        for output, source, divisor in [
            ('horizontal_accuracy', 'horizontal_accuracy_mm', 1000),
            ('vertical_accuracy', 'vertical_accuracy_mm', 1000),
            ('speed_accuracy', 'speed_accuracy_mm_s', 1000),
            ('course_accuracy', 'course_accuracy_e5', 1e5)]:
            derived[output] = (frame[source].astype('float64') / divisor).where(have)
        derived['receiver_unix_seconds'] = frame.receiver_unix_seconds.where(have & ((flags & 24) == 24))
        derived.attrs.update(frame.attrs)
        result[derived_key] = derived
        provenance[derived_key] = {
            'derived': True, 'source_stream': key, 'sensor_id': descriptor['sensor_id'],
            'representation': 'bodaqs.gps_nav_pvt.v1', 'configuration_source': 'embedded_stream_catalog',
            'utc_alignment_proven': False, 'timestamp_basis': 'logger_receive_time_not_measurement_time',
            'stale_after_ms': acquisition['stale_after_ms'], 'interpolation': 'none',
            'course_semantics': 'course_over_ground_not_bicycle_heading',
            'source_kind': 'logger_sensor',
            'signals': {column: {'quantity': quantity, 'unit': unit,
                                 'sensor': descriptor['sensor_id'], 'source_kind': 'logger_sensor',
                                 'source': 'logger_gps', 'domain': 'world'}
                        for column, quantity, unit in [
                            ('latitude', 'position_latitude', 'deg'), ('longitude', 'position_longitude', 'deg'),
                            ('altitude', 'altitude', 'm'), ('speed', 'speed', 'm/s'),
                            ('course_over_ground', 'course_over_ground', 'deg'), ('valid', 'valid', 'bool'),
                            ('sequence', 'seq', 'count'), ('fix_type', 'fix_type', 'code'),
                            ('satellites', 'satellites', 'count'),
                            ('horizontal_accuracy', 'horizontal_accuracy', 'm'),
                            ('vertical_accuracy', 'vertical_accuracy', 'm'),
                            ('speed_accuracy', 'speed_accuracy', 'm/s'), ('course_accuracy', 'course_accuracy', 'deg'),
                            ('receiver_time_of_week_s', 'receiver_time_of_week', 's')]
                        if column in derived},
        }
    return result, provenance, warnings
