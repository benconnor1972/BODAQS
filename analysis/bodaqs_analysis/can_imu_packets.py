"""Decode compact CAN packet observations without manufacturing sample times.

Full-sequence floors travel with packets. A subsequent floor or terminal boundary
provides an upper bound. Forward/backward sequence constraints must agree before
high bits are exposed; ambiguous packets remain available with sequence=None.
"""
from pathlib import Path
import struct
import zlib

from .io_bdq import iter_bdq_stream_records, read_bdq

AXES = ("ax", "ay", "az", "gx", "gy", "gz")
SCHEMA = "bodaqs.can_imu_packets.v1"


def _same_readings(left: dict, right: dict) -> bool:
    return (left["first_sequence_low"] == right["first_sequence_low"]
            and left["stream_epoch"] == right["stream_epoch"]
            and left["count"] == right["count"]
            and all(left[f"{axis}{slot}"] == right[f"{axis}{slot}"]
                    for slot in range(left["count"]) for axis in AXES))


def read_can_imu_packets(path: str | Path, stream_key: str) -> dict:
    info = read_bdq(path)
    descriptors = {d["stream_key"]: d for d in info.stream_catalog["streams"]}
    descriptor = descriptors[stream_key]
    acquisition = descriptor["acquisition"]
    unit_schema = acquisition.get("payload_schema") == "bodaqs.can_imu_units.v1"
    if acquisition.get("payload_schema") != SCHEMA and not unit_schema:
        raise ValueError("not a compact CAN packet observation stream")
    packets = list(iter_bdq_stream_records(path, stream_key))
    companion = next((d for d in descriptors.values()
        if d.get("acquisition", {}).get("payload_schema") == "bodaqs.can_timing_evidence.v1"
        and d["acquisition"].get("related_sample_stream_id") == descriptor["stream_id"]), None)
    evidence = list(iter_bdq_stream_records(path, companion["stream_key"])) if companion else []
    if unit_schema:
        identity_fields = ('node_address', 'node_boot', 'provider_uid', 'master_uid',
                           'master_boot', 'recording_id', 'control_session', 'measurement_context')
        if not companion or any(companion['acquisition'].get(key) != acquisition.get(key)
                                for key in identity_fields):
            raise ValueError('sample-unit source companion identity mismatch; readings unverified')
        epochs = {}
        for row in evidence:
            if row['boundary_event_kind'] == 2:
                segment, epoch = row['source_segment_id'], row['stream_epoch']
                if segment in epochs and epochs[segment] != epoch:
                    raise ValueError('conflicting sample-unit source epoch')
                epochs[segment] = epoch
        packets = _unit_packets(packets, acquisition, epochs)
    terminal = {}
    for row in evidence:
        if row["boundary_event_kind"] == 8 and row["boundary_validity_flags"] & 1:
            terminal[row["source_segment_id"]] = row["related_sequence"] + 1
    groups, receptions = {}, {}
    replayed_samples = 0
    last_order = 0
    for index, packet in enumerate(packets):
        count = packet["packet_flags"] & 7
        if (packet["sequence"] != index or not 1 <= count <= 5
                or packet["packet_flags"] & 128 or not 4 + 12*count <= packet["packet_length"] <= 64
                or not packet["source_segment_id"]):
            raise ValueError("invalid compact packet identity or length")
        packet["count"] = count
        order = (packet["master_receive_ordinal_high"] << 32) | packet["master_receive_ordinal_low"]
        # The floor is current logger interpretation state, not immutable
        # master reception content. A replay can arrive after a newer floor.
        identity = {key: value for key, value in packet.items()
                    if key not in ("sequence", "native_tick", "sequence_floor")}
        if order in receptions:
            if receptions[order] != identity:
                raise ValueError("conflicting immutable reception replay")
            replayed_samples += count
            continue
        if not order or order <= last_order:
            raise ValueError("unordered compact reception identity")
        last_order = order
        receptions[order] = identity
        groups.setdefault(packet["source_segment_id"], []).append(packet)
    readings, gaps = [], []
    ambiguous, duplicates = 0, replayed_samples
    for segment, rows in groups.items():
        minimum, maximum = [], [0]*len(rows)
        lower = 0
        for i, packet in enumerate(rows):
            floor = packet["sequence_floor"]
            if i and floor < rows[i-1]["sequence_floor"]:
                raise ValueError("sequence floor went backwards")
            if i and _same_readings(packet, rows[i-1]):
                lower = minimum[-1]
            lower = max(lower, floor)
            candidate = lower + ((packet["first_sequence_low"] - lower) % 65536)
            minimum.append(candidate)
            lower = candidate + packet["count"]
        upper = terminal.get(segment, 1 << 32)
        for i in range(len(rows)-1, -1, -1):
            packet = rows[i]
            if i+1 < len(rows) and rows[i+1]["sequence_floor"] > packet["sequence_floor"]:
                upper = min(upper, rows[i+1]["sequence_floor"])
            ceiling = upper - packet["count"]
            maximum[i] = ceiling - ((ceiling - packet["first_sequence_low"]) % 65536)
            if maximum[i] < minimum[i]:
                raise ValueError("conflicting compact sequence bounds")
            upper = maximum[i]
            if i and _same_readings(packet, rows[i-1]):
                upper += packet["count"]
        expected, seen = 0, {}
        for i, packet in enumerate(rows):
            known = minimum[i] == maximum[i]
            if not known:
                ambiguous += 1
                expected = None
            first = minimum[i] if known else None
            if known and expected is None:
                gaps.append({"source_segment_id": segment, "first": None,
                             "last": first-1, "count": None, "extent": "uncertain"})
            elif known and first > expected:
                gaps.append({"source_segment_id": segment, "first": expected,
                             "last": first-1, "count": first-expected, "extent": "known"})
            for slot in range(packet["count"]):
                sequence = first + slot if known else None
                axes = {axis: packet[f"{axis}{slot}"] for axis in AXES}
                if sequence is not None and sequence in seen:
                    if seen[sequence] != axes:
                        raise ValueError("conflicting duplicate six-axis readings")
                    duplicates += 1
                    continue
                if sequence is not None:
                    seen[sequence] = axes
                readings.append({"source_segment_id": segment, "sequence": sequence,
                    "sequence_low": (packet["first_sequence_low"]+slot) % 65536,
                    "packet_observation": packet["sequence"], **axes})
            if known:
                expected = max(expected or 0, first + packet["count"])
    return {"schema": "bodaqs.can_imu_packet_decode.v1", "source": acquisition,
            "readings": readings, "gaps": gaps, "duplicates": duplicates,
            "ambiguous_packets": ambiguous, "packet_count": len(packets),
            "timing_status": "unreconstructed", "raw_timing_observations": evidence,
            "file_errors": list(info.detected_errors)}


def _unit_packets(units: list[dict], acquisition: dict, epochs: dict[int, int]) -> list[dict]:
    """Verify retained master bytes before exposing readings; never trust a file CRC alone."""
    packets = []
    previous = 0
    for index, unit in enumerate(units):
        context = unit['context_low'] | unit['context_high'] << 32
        identity, total, node = unit['object_id'], unit['total'], unit['node']
        if (unit['sequence'] != index or identity <= previous or not unit['source_segment_id']
                or context != int(acquisition['measurement_context'])
                or node != acquisition['node_address'] or unit['object_class'] != 1
                or unit['direction'] != 1 or not 84 <= total <= 212 or (total-20) % 64):
            raise ValueError('invalid sample-unit identity or geometry')
        previous = identity
        data = b''.join(struct.pack('<I', unit[f'unit_word{i}']) for i in range(54))
        prefix = struct.pack('<QIBBBxHxx', context, identity, node, 1, 1, total)
        expected = struct.unpack_from('<I', data, total-4)[0]
        if zlib.crc32(prefix + data[:total-4]) != expected:
            raise ValueError('sample-unit upstream checksum mismatch; readings unverified')
        version, cls, address, boot, _, count, reserved = struct.unpack_from('<HBBIIHH', data)
        if (version != 2 or cls != 1 or address != node or boot != acquisition['node_boot']
                or count != (total-20)//64 or reserved or any(data[total:])):
            raise ValueError('invalid sample-unit source definition')
        for slot in range(count):
            payload = data[16+64*slot:80+64*slot]
            low, epoch, flags = struct.unpack_from('<HBB', payload)
            if epoch != epochs.get(unit['source_segment_id']):
                raise ValueError('sample-unit source epoch mismatch or missing definition; readings unverified')
            readings = flags & 7
            if not 1 <= readings <= 5 or flags & 128 or any(payload[4+12*readings:]):
                raise ValueError('invalid sample-unit CAN payload')
            # This is a unit/slot observation order, not a captured CAN ordinal.
            order = identity*4 + slot
            packet = dict(sequence=len(packets), native_tick=unit['native_tick'],
                status_flags=unit['status_flags'], source_segment_id=unit['source_segment_id'],
                sequence_floor=unit['sequence_floor'], master_receive_ordinal_low=order & 0xffffffff,
                master_receive_ordinal_high=order >> 32, first_sequence_low=low,
                stream_epoch=epoch, packet_flags=flags, packet_length=4+12*readings)
            for sample in range(readings):
                for axis, value in zip(AXES, struct.unpack_from('<hhhhhh', payload, 4+12*sample)):
                    packet[f'{axis}{sample}'] = value
            packets.append(packet)
    return packets
