"""Offline string-pot geometry with firmware tracking uncertainty preserved."""
from collections import Counter
import math
from typing import Mapping

import pandas as pd


def reconstruct_string_pots(metadata, catalog, frames):
    result, provenance, warnings = {}, {}, []
    snapshot=metadata.get('recording_configuration', {})
    sensors=snapshot.get('sensors', []) if isinstance(snapshot, Mapping) else []
    if not isinstance(sensors,list):
        sensors=[]
    identities=Counter(s.get('sensor_id') for s in sensors if isinstance(s,Mapping) and isinstance(s.get('sensor_id'),str))
    for descriptor in catalog.get('streams', []):
        acquisition=descriptor.get('acquisition', {})
        if not isinstance(acquisition,Mapping) or acquisition.get('payload_schema')!='bodaqs.string_pot_counts.v1':
            continue
        key=descriptor['stream_key']
        frame=frames.get(key)
        if not isinstance(frame,pd.DataFrame):
            continue
        provenance[key]={'physical_turns_proven':False, 'unwrapped_interpretation':'firmware_estimate',
                         'quality_field':'tracking_quality','tracking_epoch_field':'tracking_epoch'}
        if not isinstance(snapshot,Mapping) or snapshot.get('schema')!='bodaqs.recording_configuration.v1':
            warnings.append(f'string_pot_raw_only:{key}:missing_configuration_snapshot')
            continue
        identity=descriptor.get('sensor_id')
        matches=[s for s in sensors if isinstance(s,Mapping) and s.get('sensor_id')==identity and s.get('stream_key')==key]
        if not isinstance(identity,str) or identities[identity]!=1 or len(matches)!=1:
            warnings.append(f'string_pot_raw_only:{key}:ambiguous_source_identity')
            continue
        sensor=matches[0]
        domain=sensor.get('count_domain')
        fields={c.get('field'):(c.get('storage_type'),c.get('byte_offset')) for c in descriptor.get('channels', []) if isinstance(c,Mapping)}
        expected={'wrapped_count':('uint16',12),'unwrapped_count':('int32',16),
                  'tracking_quality':('uint16',14),'tracking_epoch':('uint32',20)}
        if (sensor.get('sensor_type') not in ('as5600_string_pot_analog','as5600_string_pot_i2c')
                or not isinstance(domain,Mapping) or domain.get('id')!='string_pot_counts_v1'
                or descriptor.get('record_size_bytes') not in (24,40)
                or sensor.get('raw_fields')!=['wrapped_count','unwrapped_count']
                or any(fields.get(name)!=kind or name not in frame for name,kind in expected.items())):
            warnings.append(f'string_pot_raw_only:{key}:source_binding_mismatch')
            continue
        calibration=sensor.get('calibration', {})
        if not isinstance(calibration,Mapping) or calibration.get('available') is not True:
            continue
        try:
            names=('installed_zero_count','sensor_zero_count','sensor_full_count','sensor_full_travel')
            if any(type(calibration.get(name)) not in (int,float) for name in names):
                raise ValueError('unknown numeric calibration')
            zero,low,high,travel=(float(calibration[name]) for name in names)
            unit,invert=calibration.get('output_unit'),calibration.get('invert')
            if (calibration.get('model')!='string_pot_geometry_v1'
                    or not all(math.isfinite(v) for v in (zero,low,high,travel))
                    or travel<=0 or low==high or not isinstance(unit,str) or not unit.strip()
                    or type(invert) is not bool):
                raise ValueError('invalid geometry')
            scale=travel/abs(high-low)*(-1 if invert else 1)
            if not math.isfinite(scale):
                raise ValueError('unrepresentable scale')
        except (KeyError,ValueError,OverflowError,ZeroDivisionError):
            warnings.append(f'string_pot_raw_only:{key}:invalid_calibration')
            continue
        derived_key=key+'_engineering'
        if derived_key in frames:
            warnings.append(f'string_pot_raw_only:{key}:stream_key_collision')
            continue
        derived=frame.loc[:,[c for c in ('time_s','sequence','native_tick','status_flags','tracking_epoch','tracking_quality') if c in frame]].copy()
        # Settling holds and uncertain tracking cannot establish displacement.
        invalid=(frame.tracking_quality.astype('uint64') & (2|4|8|16|64))!=0
        quality=frame.tracking_quality.astype('uint64')
        invalid|=quality>0x7f
        invalid|=(quality & 1)==0
        modulus=acquisition.get('counts_per_turn')
        if type(modulus) is not int or not 2<=modulus<=65535:
            warnings.append(f'string_pot_raw_only:{key}:unknown_count_modulus')
            continue
        invalid|=(frame.wrapped_count<0) | (frame.wrapped_count>=modulus)
        invalid|=frame.tracking_epoch==0
        epoch_change=frame.tracking_epoch.ne(frame.tracking_epoch.shift())
        reset_seen=((quality & 32)!=0).groupby(epoch_change.cumsum()).cummax()
        invalid|=~reset_seen
        if 'status_flags' in frame:
            invalid|=(frame.status_flags.astype('uint64') & 0x20)!=0
        values=(frame.unwrapped_count.astype('float64')-zero)*scale
        invalid|=~values.map(math.isfinite)
        derived['displacement']=values.mask(invalid)
        result[derived_key]=derived
        provenance[derived_key]={'derived':True,'source_stream':key,'source_field':'unwrapped_count',
                                 'calibration_source':'embedded_recording_configuration',
                                 'calibration_model':'string_pot_geometry_v1','unit':unit,
                                 'physical_turns_proven':False}
    return result,provenance,warnings
