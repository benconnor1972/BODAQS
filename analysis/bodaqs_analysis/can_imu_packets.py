"""Decode compact CAN packet observations without manufacturing sample times.

Full-sequence floors travel with packets. A subsequent floor or terminal boundary
provides an upper bound. Forward/backward sequence constraints must agree before
high bits are exposed; ambiguous packets remain available with sequence=None.
"""
from pathlib import Path

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
    if acquisition.get("payload_schema") != SCHEMA:
        raise ValueError("not a compact CAN packet observation stream")
    packets = list(iter_bdq_stream_records(path, stream_key))
    companion = next((d for d in descriptors.values()
        if d.get("acquisition", {}).get("payload_schema") == "bodaqs.can_timing_evidence.v1"
        and d["acquisition"].get("related_sample_stream_id") == descriptor["stream_id"]), None)
    evidence = list(iter_bdq_stream_records(path, companion["stream_key"])) if companion else []
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
