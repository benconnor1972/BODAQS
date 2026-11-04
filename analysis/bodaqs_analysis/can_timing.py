"""Explicit CAN clock evidence interpretation; receipt timestamps are never anchors.

Raw frames are retained. Finite cross-clock bounds additionally require declared
conservative capture/quantization and oscillator drift bounds in the acquisition
catalog; nominal frequency and fit residuals cannot supply those bounds.
"""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Mapping
from fractions import Fraction

import pandas as pd

MODULUS = 1 << 32


def _values(frame, descriptor):
    names = {c['byte_offset']: c['field'] for c in descriptor['channels']}
    return [{offset: int(row[name]) for offset, name in names.items()}
            for row in frame.to_dict('records')]


def _valid(row, *bits):
    return all(row.get(16, 0) & (1 << bit) for bit in bits)


def _signed_delta(value, origin):
    return (value - origin + MODULUS // 2) % MODULUS - MODULUS // 2


def _bound(acquisition, name):
    bounds = acquisition.get('timing_bounds', {})
    value = bounds.get(name) if isinstance(bounds, Mapping) else None
    if not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
        return Fraction(str(value))
    return None


def map_can_timing(frames, descriptors, logger_origin_us=0):
    """Decorate CAN sample grids in place with scoped source positions and bounds.

    Shared observations are keyed by original master UID/boot/epoch and token,
    never by the per-node companion creation sequence. Conflicting copies cannot
    establish a mapping. Raw copies remain available in their original frames.
    """
    evidence = []
    shared = {}
    conflicts = set()
    for descriptor in descriptors.values():
        acquisition = descriptor.get('acquisition', {})
        if acquisition.get('payload_schema') != 'bodaqs.can_timing_evidence.v1':
            continue
        frame = frames[descriptor['stream_key']]
        if frame.empty:
            continue
        for row in _values(frame, descriptor):
            evidence.append((row, acquisition))
            kind = row[12]
            if kind not in (4, 5) or not _valid(row, 3):
                continue
            uid, boot = acquisition.get('master_uid'), acquisition.get('master_boot')
            if uid is None or boot is None:
                continue
            key = (str(uid), str(boot), row[40], kind, row[64 if kind == 4 else 144])
            offsets = (16, 72) if kind == 4 else (16, 120, 124, 128, 132, 136, 140, 180)
            signature = tuple(row.get(offset, 0) for offset in offsets)
            if key in shared and shared[key][0] != signature:
                conflicts.add(key)
            else:
                shared[key] = (signature, row, acquisition)
    for descriptor in descriptors.values():
        acquisition = descriptor.get('acquisition', {})
        if acquisition.get('payload_schema') != 'bodaqs.can_imu6.v1':
            continue
        key = descriptor['stream_key']
        frame = frames[key]
        if frame.empty:
            continue
        out = frame.copy()
        samples = _values(frame, descriptor)
        positions, previous = [], {}
        for row in samples:
            segment, sequence = row[12], row[0]
            prior = previous.get(segment)
            position = sequence if prior is None else prior[1] + (sequence - prior[0]) % MODULUS
            positions.append(position)
            previous[segment] = (sequence, position)
        out['source_sequence_unwrapped'] = pd.array(positions, dtype='UInt64')
        models = [(r, a) for r, a in evidence if r[12] == 2
                  and a.get('related_sample_stream_id') == descriptor['stream_id']
                  and a.get('provider_uid') == acquisition.get('provider_uid')
                  and r[28] == acquisition.get('node_boot')
                  and _valid(r, 0, 1, 2, 4, 12, 20)
                  and r[202] == 1 and r[206] & 5 == 5
                  and r[172] <= r[176] and 0 < r[100] <= 65535
                  and r[96] > 0 and 0 < r[108] <= 500 and 0 < r[112] <= 150000]
        positions_by_segment = {}
        for row, position in zip(samples, positions):
            positions_by_segment.setdefault(row[12], []).append(position)
        prepared = {}
        for model, binding in models:
            source_positions = positions_by_segment.get(model[20], [])
            aliases = []
            if source_positions:
                first = (source_positions[0] - model[108] - model[88] + MODULUS - 1) // MODULUS
                last = (source_positions[-1] - model[88]) // MODULUS
                for cycle in range(first, last + 1):
                    anchor = model[88] + cycle * MODULUS
                    index = bisect_left(source_positions, anchor)
                    if index < len(source_positions) and source_positions[index] <= anchor + model[108]:
                        aliases.append(anchor)
            if len(aliases) == 1:
                prepared.setdefault(model[20], []).append((aliases[0], model, binding))
        for segment in prepared:
            prepared[segment].sort(key=lambda value: value[0])
        anchor_positions = {segment: [value[0] for value in values] for segment, values in prepared.items()}
        ticks, epochs, sensor_epochs, model_ids, lower, upper, statuses = [], [], [], [], [], [], []
        for row, position in zip(samples, positions):
            candidates = []
            segment_models = prepared.get(row[12], [])
            starts = anchor_positions.get(row[12], [])
            for anchor, model, binding in segment_models[bisect_left(starts, position - 500):bisect_right(starts, position)]:
                delta = (row[0] - model[88]) % MODULUS
                duration = delta * model[96] // model[100]
                if delta > model[108] or duration > model[112]:
                    continue
                # Reject aliases if a stream spans another entire source cycle.
                if anchor != position - delta:
                    continue
                tick = (model[92] + duration) % MODULUS
                candidates.append((anchor, model, binding, tick))
            status, lo, hi = 'unknown', None, None
            if candidates:
                latest = max(c[0] for c in candidates)
                selected = [c for c in candidates if c[0] == latest]
                definitions = {tuple(c[1][offset] for offset in
                                     (14, 16, 20, 28, 32, 36, 44, 88, 92, 96, 100, 104, 108, 112, 172, 176, 202, 206))
                               for c in selected}
                if len(definitions) != 1:
                    status = 'model_conflict'
                elif selected[0][3] == row[4]:
                    _, model, binding, tick = selected[0]
                    status = 'native_association_unknown_bound'
                    lo, hi = _logger_bounds(model, binding, tick, evidence, shared, conflicts)
                    if lo is not None:
                        status = 'bounded'
                    ticks.append(tick)
                    epochs.append(model[36])
                    sensor_epochs.append(model[32])
                    model_ids.append(model[44])
            if len(ticks) < len(statuses) + 1:
                ticks.append(None); epochs.append(None); sensor_epochs.append(None); model_ids.append(None)
            lower.append(lo); upper.append(hi); statuses.append(status)
        for name, values in [('modeled_node_tick', ticks), ('clock_epoch', epochs),
                             ('sensor_clock_epoch', sensor_epochs), ('timing_model_id', model_ids)]:
            out[name] = pd.array(values, dtype='UInt32')
        unwrapped, elapsed, origins, previous_ticks = [], [], {}, {}
        for tick, epoch in zip(ticks, epochs):
            if tick is None:
                unwrapped.append(None); elapsed.append(math.nan)
                continue
            prior = previous_ticks.get(epoch)
            absolute = tick if prior is None else prior[1] + _signed_delta(tick, prior[0])
            previous_ticks[epoch] = (tick, absolute)
            origins.setdefault(epoch, absolute)
            unwrapped.append(absolute)
            elapsed.append((absolute - origins[epoch]) / 1e6)
        out['native_tick_unwrapped'] = pd.array(unwrapped, dtype='Int64')
        out['native_time_s'] = elapsed
        out['logger_lower_us'] = pd.array(lower, dtype='UInt64')
        out['logger_upper_us'] = pd.array(upper, dtype='UInt64')
        out['timing_status'] = statuses
        if any(value is not None for value in lower):
            out['time_s'] = [(math.nan if lo is None else ((lo + hi) / 2 - logger_origin_us) / 1e6)
                             for lo, hi in zip(lower, upper)]
        out.attrs['bdq_clock_alignment'] = {
            'status': 'bounded' if all(s == 'bounded' for s in statuses) else 'unknown_or_degraded',
            'method': 'explicit_can_evidence', 'clock_id': descriptor.get('clock_id'),
            'shared_observation_count': len(shared) - len(conflicts),
            'shared_conflict_count': len(conflicts), 'provider_uid': acquisition.get('provider_uid'),
            'node_boot': acquisition.get('node_boot'), 'bounds': 'logger_lower_us/logger_upper_us',
        }
        # Keep the established unknown status when no native association exists.
        if all(s == 'unknown' for s in statuses):
            out.attrs['bdq_clock_alignment']['status'] = 'unknown'
        frames[key] = out


def _logger_bounds(model, binding, tick, evidence, shared, conflicts):
    if not _valid(model, 13) or not model[206] & 2:
        return None, None
    node_error = _bound(binding, 'node_sync_capture_us')
    master_error = _bound(binding, 'master_sync_capture_us')
    bridge_error = _bound(binding, 'bridge_quantization_us')
    node_drift = _bound(binding, 'node_master_drift_ppm')
    master_drift = _bound(binding, 'master_logger_drift_ppm')
    if None in (node_error, master_error, bridge_error, node_drift, master_drift):
        return None, None
    intervals = []
    for sync, acquisition in evidence:
        if sync[12] != 3 or not _valid(sync, 0, 1, 3, 7):
            continue
        if (acquisition.get('provider_uid'), sync[28], sync[36], sync[14]) != (binding.get('provider_uid'), model[28], model[36], model[14]):
            continue
        master_identity = (str(binding.get('master_uid')), str(binding.get('master_boot')), sync[40])
        sync_key = master_identity + (4, sync[64])
        if sync_key not in shared or sync_key in conflicts:
            continue
        master_sync = shared[sync_key][1]
        if not _valid(master_sync, 8):
            continue
        delta_node = _signed_delta(tick, sync[68])
        if abs(delta_node) > 150000:
            continue
        master_tick = (master_sync[72] + delta_node) % MODULUS
        for key, (_, bridge, _) in shared.items():
            if key[:3] != master_identity or key[3] != 5 or key in conflicts:
                continue
            if not _valid(bridge, 14, 15, 22) or bridge[140] != 1:
                continue
            lo = (bridge[124] << 32) | bridge[120]
            hi = (bridge[132] << 32) | bridge[128]
            if hi < lo:
                continue
            delta_master = _signed_delta(master_tick, bridge[136])
            if abs(delta_master) > 150000:
                continue
            error = (model[104] + node_error + master_error + bridge_error
                     + abs(delta_node) * node_drift / 1000000 + abs(delta_master) * master_drift / 1000000)
            intervals.append((lo + delta_master - error, hi + delta_master + error))
    if not intervals:
        return None, None
    lo, hi = max(i[0] for i in intervals), min(i[1] for i in intervals)
    return (math.floor(lo), math.ceil(hi)) if 0 <= lo <= hi < (1 << 64) else (None, None)
