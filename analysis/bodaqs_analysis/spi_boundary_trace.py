"""Strict r8 same-exchange join. No timing reconstruction or header repair."""
from __future__ import annotations
import hashlib
import struct
import zlib

HEADER=("version","bytes","capacity","count","next","ordinal","frozen","overflow",
        "boot_low","boot_high","context_low","context_high","marker_ordinal","nonce",
        "failed_device_sequence","logger_slot","request_crc","reply_crc","arm_max_us","end_max_us","source_address")
HARDWARE=("tick","epoch","stat","ctl0","ctl1","tx_src","tx_dst","rx_src","rx_dst","tx_remaining","rx_remaining")
TRACE_BYTES=7328
ENTRY_BYTES=868

def exact64(value):
    if isinstance(value,str) and value.isascii() and value.isdecimal():number=int(value)
    elif type(value) is int and 0<value<=2**53-1:number=value
    else:raise ValueError("Identity must be an exact positive uint64")
    if not 0<number<2**64:raise ValueError("Identity outside uint64")
    return number

def parse_trace(raw:bytes)->dict:
    if len(raw)!=TRACE_BYTES:raise ValueError("Truncated or incompatible trace block")
    h=dict(zip(HEADER,struct.unpack_from("<21I",raw)))
    if (h["version"],h["bytes"],h["capacity"],h["frozen"],h["overflow"])!=(1,TRACE_BYTES,8,1,0):
        raise ValueError("Trace not a frozen, nonsaturated r8 export")
    if not 1<=h["count"]<=8 or not 0<=h["next"]<8 or h["ordinal"]!=h["marker_ordinal"]:
        raise ValueError("Invalid ring metadata")
    entries=[]
    for n in range(h["count"]):
        index=(h["next"]-h["count"]+n)%8;offset=384+ENTRY_BYTES*index
        ordinal,length,address=struct.unpack_from("<3I",raw,offset)
        entries.append({"ordinal":ordinal,"length":length,"source_address":address,
            "arm":dict(zip(HARDWARE,struct.unpack_from("<11I",raw,offset+12))),
            "end":dict(zip(HARDWARE,struct.unpack_from("<11I",raw,offset+56))),
            "tx_arm":raw[offset+100:offset+356],"tx_end":raw[offset+356:offset+612],
            "request":raw[offset+612:offset+868]})
    if [e["ordinal"] for e in entries]!=list(range(h["marker_ordinal"]-h["count"],h["marker_ordinal"])) or entries[0]["ordinal"]<1:
        raise ValueError("Ring history is not consecutive before marker")
    boot=h["boot_low"]|(h["boot_high"]<<32);context=h["context_low"]|(h["context_high"]<<32)
    if not boot or not context:raise ValueError("Missing trace identity")
    return {"header":h,"master_boot":str(boot),"context":str(context),"entries":entries,
            "sha256":hashlib.sha256(raw).hexdigest()}

def _wire(value):
    if not isinstance(value,str) or len(value)!=512:raise ValueError("Missing complete256-byte logger capture")
    try:
        result=bytes.fromhex(value)
        if len(result)!=256:raise ValueError("Capture hex contains whitespace")
        return result
    except ValueError as error:raise ValueError("Invalid capture hex") from error

def _header_crc(data):
    return data[:3]==b"BM\x02" and zlib.crc32(data[:252])&0xffffffff==int.from_bytes(data[252:],"little")

def correlate(raw:bytes,summary:dict,source:dict)->dict:
    trace=parse_trace(raw);h=trace["header"]
    if exact64(trace["master_boot"])!=exact64(source.get("master_boot")) or exact64(trace["context"])!=exact64(source.get("measurement_context")):
        raise ValueError("Master boot/context differs from recording")
    failures=summary.get("remote_measurement_failures",{});capture=failures.get("rejected_replies",{})
    if not failures.get("available") or not capture.get("available") or not capture.get("entries"):
        raise ValueError("No matching finalized rejected reply")
    probe=capture.get("boundary_trace",{});entry=capture["entries"][0];bus=entry.get("bus",{})
    if not all(probe.get(k) is True for k in ("attempted","transferred","adjacent")):
        raise ValueError("Missing successful adjacent marker transfer")
    if bus.get("available") is not True or bus.get("device_sequence_valid") is not True or bus.get("cs")!=40:
        raise ValueError("Missing valid A8 CAN-CS sequence")
    sequence=bus.get("device_sequence");nonce=entry.get("slot")
    if type(sequence) is not int or not 0<sequence<2**32-1 or type(nonce) is not int or not 0<nonce<2**32-1:
        raise ValueError("Saturated/invalid logger sequence")
    for other in capture["entries"][1:]:
        if other.get("slot")==nonce or other.get("bus",{}).get("device_sequence")==sequence:
            raise ValueError("Duplicate logger exchange identity")
    if probe.get("failed_device_sequence")!=sequence or probe.get("marker_device_sequence")!=sequence+1 or sequence+1==2**32-1:
        raise ValueError("Intervening CAN transaction or saturated marker sequence")
    if probe.get("nonce")!=nonce or h["nonce"]!=nonce or h["logger_slot"]!=nonce or h["failed_device_sequence"]!=sequence:
        raise ValueError("Marker identity differs from first rejected exchange")
    if entry.get("request_available") is not True:raise ValueError("Original MOSI unavailable")
    request,received=_wire(entry.get("request_hex")),_wire(entry.get("reply_hex"))
    if not _header_crc(request) or int.from_bytes(request[4:12],"little")!=exact64(trace["context"]):
        raise ValueError("Original request CRC/context invalid")
    if h["request_crc"]!=int.from_bytes(request[252:],"little") or h["reply_crc"]!=int.from_bytes(received[252:],"little"):
        raise ValueError("Marker fingerprints differ from logger originals")
    previous=trace["entries"][-1]
    if previous["length"]!=256 or previous["request"]!=request:
        raise ValueError("Immediate master predecessor is not the exact failed MOSI")
    staged,ended=previous["tx_arm"],previous["tx_end"]
    difference=[i for i,(a,b) in enumerate(zip(staged,received)) if a!=b]
    changed=[i for i,(a,b) in enumerate(zip(staged,ended)) if a!=b]
    classification=("selected_source_changed" if changed else "source_header_or_crc_invalid_at_arm" if not _header_crc(staged)
        else "zero_first_byte_after_header_crc_valid_staging" if difference==[0] and staged[0]==0x42 and received[0]==0
        else "received_bytes_equal_staged_source" if not difference else "other_receive_difference_after_staging")
    return {"schema":"bodaqs.spi-boundary-join.v1","same_exchange_proven":True,
        "classification":classification,"master_boot":trace["master_boot"],"context":trace["context"],
        "logger_slot":nonce,"master_physical_ordinal":previous["ordinal"],"freeze_marker_ordinal":h["marker_ordinal"],
        "trace_sha256":trace["sha256"],"source_address":previous["source_address"],
        "source_header_crc_valid":_header_crc(staged),"source_changed_offsets":changed,
        "source_canonical_decode_checked":False,
        "received_diff_offsets":difference,"arm":previous["arm"],"end":previous["end"],
        "arm_max_us":h["arm_max_us"],"end_max_us":h["end_max_us"],
        "tx_arm_hex":staged.hex(),"tx_end_hex":ended.hex(),"request_hex":request.hex(),"received_hex":received.hex(),
        "first_clock_readiness_proven":False,"physical_wire_or_logger_receive_location_proven":False}
